#if canImport(CoreML) && canImport(CoreGraphics) && canImport(ImageIO)
import Testing
import Foundation
import CoreML
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
@testable import BioForgeCore

/// Counts the distinct input sizes the model is given and passes the calls on.
private final class CountingUpscaler: Upscaler, @unchecked Sendable {
    private let inner: Upscaler, lock = NSLock()
    private var seen = Set<[Int]>()
    var shapes: Int { lock.lock(); defer { lock.unlock() }; return seen.count }
    init(_ inner: Upscaler) { self.inner = inner }
    func upscale(_ rgb: [UInt8], width w: Int, height h: Int) throws -> [Float] {
        lock.lock(); seen.insert([w, h]); lock.unlock()
        return try inner.upscale(rgb, width: w, height: h)
    }
}

/// Opt-in measurement of the art pack build: PACK_BENCH, BIOFORGE_DATA and BIOFORGE_HD_MODEL set. Builds a fixed sample (12 rooms of CHAOS, BEACH and
/// CONTROL, 40 textures, the CRYM and PIMM monitors) once per variant into re/out/pack_bench/<scale>x/<variant>/ and counts the pixels whose palette
/// index differs from the baseline `cpu` (the shipped settings), so a speed-up is adopted only if it leaves the pixels alone.
///   PACK_BENCH_VARIANTS  comma list, default cpu,gpu,pad8,pad12,pad16,pad32: cpu | gpu | ane | pad<N> (CPU, crop margin N); `alt-` before any of
///                        them takes the model from PACK_BENCH_MODEL2. PACK_BENCH_SCALE=2 for 2x (default 4).
///   PACK_BENCH_CLEAN=1   deletes the variant folders first; otherwise frames on disk are reused, so seconds count only the frames built this run.
/// Writes summary.md and, per variant, <variant>-diff/<frame>.png (baseline | variant | changed pixels) of the 3 frames with most flips.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["PACK_BENCH"] != nil && game != nil && ProcessInfo.processInfo.environment["BIOFORGE_HD_MODEL"] != nil,
                "PACK_BENCH, BIOFORGE_DATA and BIOFORGE_HD_MODEL are not all set"))
struct PackBenchTests {
    struct Variant { let name: String, model: URL, units: MLComputeUnits, pad: Int }
    struct Result { let name: String, built: Int, seconds: Double, peak: Int, shapes: Int, flipped: Int, masked: Int, files: Int, differing: Int }

    static let env = ProcessInfo.processInfo.environment

    static func variant(_ spec: String) throws -> Variant {
        let alt = spec.hasPrefix("alt-"), base = alt ? String(spec.dropFirst(4)) : spec
        guard let path = alt ? env["PACK_BENCH_MODEL2"] : env["BIOFORGE_HD_MODEL"] else { throw FormatError("PACK_BENCH_MODEL2 is not set (variant \(spec))") }
        let model = URL(fileURLWithPath: path)
        switch base {
        case "cpu": return Variant(name: spec, model: model, units: .cpuOnly, pad: 24)
        case "gpu": return Variant(name: spec, model: model, units: .cpuAndGPU, pad: 24)
        case "ane": return Variant(name: spec, model: model, units: .cpuAndNeuralEngine, pad: 24)
        default:
            guard base.hasPrefix("pad"), let n = Int(base.dropFirst(3)) else { throw FormatError("unknown variant \(spec)") }
            return Variant(name: spec, model: model, units: .cpuOnly, pad: n)
        }
    }

    /// The first 4 cameras (sorted) of each level that are rooms in the game folder.
    static func rooms(_ g: GameFolder) throws -> [String] {
        let have = Set(g.list("ROOMS", ext: "CAM").map { ($0 as NSString).deletingPathExtension.uppercased() })
        return try ["CHAOS", "BEACH", "CONTROL"].flatMap { level in
            Array(try Level(name: level, data: g.read("INITGAME/\(level).IFF")).cameras.keys.sorted().filter(have.contains).prefix(4))
        }
    }

    static func frames(_ dir: URL) -> [String] {
        ((try? FileManager.default.subpathsOfDirectory(atPath: dir.path)) ?? []).filter { $0.hasSuffix(".frm") }.sorted()
    }

    /// The palette a pack file is drawn with: its room's or monitor's CAM, the base palette for textures.
    static func palette(_ rel: String, _ g: GameFolder, _ base: [UInt8]) throws -> [UInt8] {
        let part = rel.split(separator: "/").map(String.init)
        guard part.count == 3, part[0] == "rooms" || part[0] == "monitors" else { return base }
        return try CAMFile(data: g.read("\(part[0] == "rooms" ? "ROOMS" : "MONITORS")/\(part[1]).CAM")).palette
    }

    /// baseline | variant | changed pixels (white on black), 2 px apart; pixels outside the mask are dark purple.
    static func writePNG(_ a: CAMFrame, _ b: CAMFrame, palette: [UInt8], to url: URL) throws {
        let w = a.width, h = a.height, W = 3 * w + 4
        var rgba = (0..<(W * h * 4)).map { UInt8($0 % 4 == 3 ? 255 : 0) }
        for y in 0..<h { for x in 0..<w {
            let i = y * w + x
            let colour: [[UInt8]] = [
                a.mask[i] != 0 ? Array(palette[(3 * Int(a.pixels[i]))..<(3 * Int(a.pixels[i]) + 3)]) : [40, 0, 40],
                b.mask[i] != 0 ? Array(palette[(3 * Int(b.pixels[i]))..<(3 * Int(b.pixels[i]) + 3)]) : [40, 0, 40],
                a.mask[i] != 0 && a.pixels[i] != b.pixels[i] ? [255, 255, 255] : [0, 0, 0]]
            for (k, c) in colour.enumerated() { let o = (y * W + k * (w + 2) + x) * 4; rgba[o] = c[0]; rgba[o + 1] = c[1]; rgba[o + 2] = c[2]; rgba[o + 3] = 255 }
        } }
        let image = try #require(rgba.withUnsafeMutableBytes { p in
            CGContext(data: p.baseAddress, width: W, height: h, bitsPerComponent: 8, bytesPerRow: W * 4, space: CGColorSpaceCreateDeviceRGB(),
                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)?.makeImage() })
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let dest = try #require(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, image, nil)
        #expect(CGImageDestinationFinalize(dest))
    }

    @Test func measure() throws {
        let g = try requireGame()
        let scale = Self.env["PACK_BENCH_SCALE"] == "2" ? 2 : 4
        let specs = (Self.env["PACK_BENCH_VARIANTS"] ?? "cpu,gpu,pad8,pad12,pad16,pad32").split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }
        let variants = try (specs.contains("cpu") ? specs : ["cpu"] + specs).map(Self.variant)
        let rooms = try Self.rooms(g), out = repoRoot.appendingPathComponent("re/out/pack_bench/\(scale)x")
        let base = try PixelPackBuilder(game: g, root: out, factor: scale, upscaler: NearestUpscaler()).basePalette()
        print("PackBench sample: \(rooms.count) rooms \(rooms.joined(separator: " ")), 40 textures, monitors CRYM PIMM, \(scale)x")

        var results: [Result] = []
        let baseline = out.appendingPathComponent("cpu")
        for v in variants {
            let root = out.appendingPathComponent(v.name)
            if Self.env["PACK_BENCH_CLEAN"] != nil {
                try? FileManager.default.removeItem(at: root)
                try? FileManager.default.removeItem(at: out.appendingPathComponent("\(v.name)-diff"))
            }
            let up = CountingUpscaler(try CoreMLUpscaler(modelURL: v.model, computeUnits: v.units))
            let builder = PixelPackBuilder(game: g, root: root, factor: scale, upscaler: up, rooms: rooms, monitors: ["CRYM", "PIMM"], textureLimit: 40, pad: v.pad)
            var built = 0, peak = PixelPackBuilder.footprint()
            let start = Date()
            try builder.run(isCancelled: { false }, progress: { _ in built += 1; peak = Swift.max(peak, PixelPackBuilder.footprint()) }, roomDone: { _ in }, monitorDone: { _ in })
            let seconds = Date().timeIntervalSince(start)

            var flipped = 0, masked = 0, differing = 0, flips: [(rel: String, n: Int)] = []
            let files = Self.frames(root)
            for rel in files {
                guard let a = HiResPack.decode(try Data(contentsOf: baseline.appendingPathComponent(rel))),
                      let b = HiResPack.decode(try Data(contentsOf: root.appendingPathComponent(rel))), a.width == b.width, a.height == b.height else { continue }
                var n = 0
                for i in 0..<a.pixels.count where a.mask[i] != 0 { masked += 1; if a.pixels[i] != b.pixels[i] { n += 1 } }
                flipped += n
                if n > 0 { differing += 1; flips.append((rel, n)) }
            }
            if v.name != "cpu" {
                for (rel, _) in flips.sorted(by: { $0.n != $1.n ? $0.n > $1.n : $0.rel < $1.rel }).prefix(3) {
                    let a = try #require(HiResPack.decode(Data(contentsOf: baseline.appendingPathComponent(rel))))
                    let b = try #require(HiResPack.decode(Data(contentsOf: root.appendingPathComponent(rel))))
                    let name = String(rel.dropLast(4)).replacingOccurrences(of: "/", with: "_") + ".png"
                    try Self.writePNG(a, b, palette: Self.palette(rel, g, base), to: out.appendingPathComponent("\(v.name)-diff/\(name)"))
                }
            }
            results.append(Result(name: v.name, built: built, seconds: seconds, peak: peak, shapes: up.shapes, flipped: flipped, masked: masked, files: files.count, differing: differing))
        }

        var table = "| variant | frames built | s/frame | peak MB | shapes | flipped px | flip % | files differing |\n|---|---|---|---|---|---|---|---|\n"
        for r in results {
            table += "| \(r.name) | \(r.built) | \(r.built > 0 ? String(format: "%.3f", r.seconds / Double(r.built)) : "-") | \(r.peak >> 20) | \(r.shapes) | \(r.flipped) | "
                + "\(String(format: "%.4f", r.masked > 0 ? 100 * Double(r.flipped) / Double(r.masked) : 0)) | \(r.differing) of \(r.files) |\n"
        }
        try Data(table.utf8).write(to: out.appendingPathComponent("summary.md"))
        print(table)
        #expect((results.first?.built ?? 0) > 0, "the baseline built no frames (is the folder already complete? set PACK_BENCH_CLEAN=1)")
    }
}
#endif
