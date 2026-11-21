// Builds the High-Resolution Art pack (HiResFrame.swift) in the app: a port of re/tools/pixel_pack.py and pixel_filters.py, bit-exact with
// them for the same upscaled guide. An AI upscale (Upscaler) is only a guide: every new pixel stays a palette index, the colour of the
// source pixel's 3x3 neighbourhood closest to the guide.
import Foundation
#if canImport(CoreML)
import CoreML
#endif

/// The model's 4x picture of an RGB image: (4 height) x (4 width) x 3 floats in 0...255, clamped.
public protocol Upscaler: Sendable {
    func upscale(_ rgb: [UInt8], width: Int, height: Int) throws -> [Float]
}

#if canImport(CoreML)
/// The converted model (re/tools/convert_model.py): HDCube.mlmodelc, "image" [1,3,H,W] RGB 0...1 -> "upscaled" [1,3,4H,4W]; in the 70 sizes of
/// `PixelPackBuilder.bucket` (H 32...200, W 32...320).
/// It runs on the Neural Engine (fixed shapes): about 3x faster than the CPU, and it leaves the CPU and GPU to the game. The first load compiles
/// for about 2 minutes; macOS caches the result. The GPU starved the game and the window server (a build once made macOS restart the GPU).
/// `computeUnits` is for the benchmark (PackBenchTests).
public final class CoreMLUpscaler: Upscaler, @unchecked Sendable {
    private let model: MLModel

    public init(modelURL: URL, computeUnits: MLComputeUnits = .cpuAndNeuralEngine) throws {
        let config = MLModelConfiguration()
        config.computeUnits = computeUnits
        model = try MLModel(contentsOf: modelURL, configuration: config)
    }

    /// Each call drains its own autorelease pool: Core ML's outputs would otherwise pile up in the builder's long block.
    public func upscale(_ rgb: [UInt8], width w: Int, height h: Int) throws -> [Float] {
        try withPool { try predict(rgb, width: w, height: h) }
    }

    private func predict(_ rgb: [UInt8], width w: Int, height h: Int) throws -> [Float] {
        let input = try MLMultiArray(shape: [1, 3, NSNumber(value: h), NSNumber(value: w)], dataType: .float32)
        let p = input.dataPointer.assumingMemoryBound(to: Float.self)
        for c in 0..<3 { for i in 0..<(w * h) { p[c * w * h + i] = Float(rgb[3 * i + c]) / 255 } }
        let result = try model.prediction(from: MLDictionaryFeatureProvider(dictionary: ["image": MLFeatureValue(multiArray: input)]))
        guard let out = result.featureValue(for: "upscaled")?.multiArrayValue, out.shape.count == 4, out.shape[1].intValue == 3,
              out.shape[2].intValue == 4 * h, out.shape[3].intValue == 4 * w else { throw FormatError("the model's output is not 3 x \(4 * h) x \(4 * w)") }
        let s = out.strides.map(\.intValue), H = 4 * h, W = 4 * w
        var big = [Float](repeating: 0, count: H * W * 3)
        func put(_ at: (Int) -> Float) {
            for y in 0..<H { for x in 0..<W { for c in 0..<3 {
                big[(y * W + x) * 3 + c] = Swift.max(0, Swift.min(1, at(c * s[1] + y * s[2] + x * s[3]))) * 255
            } } }
        }
        if out.dataType == .float32 {
            let q = out.dataPointer.assumingMemoryBound(to: Float.self)
            put { q[$0] }
        }
        #if arch(arm64)                                      // Swift's Float16 is unavailable on Intel Macs: they take the slow path below
        if out.dataType == .float16 {
            let q = out.dataPointer.assumingMemoryBound(to: Float16.self)
            put { Float(q[$0]) }
            return big
        }
        #endif
        if out.dataType != .float32 {
            put { out[$0].floatValue }
        }
        return big
    }
}
#endif

/// Drains Core ML's autoreleased outputs where there is an autorelease pool (Apple platforms); just runs `body` elsewhere.
func withPool<T>(_ body: () throws -> T) rethrows -> T {
    #if canImport(ObjectiveC)
    return try autoreleasepool(invoking: body)
    #else
    return try body()
    #endif
}

public enum PixelFilter {
    /// palette index -> first index with the same RGB, so duplicate palette entries compare equal.
    public static func canon(_ palette: [UInt8]) -> [Int] {
        var seen: [Int: Int] = [:], out = [Int](repeating: 0, count: 256)
        for i in 0..<256 {
            let key = Int(palette[3 * i]) << 16 | Int(palette[3 * i + 1]) << 8 | Int(palette[3 * i + 2])
            out[i] = seen[key] ?? i
            seen[key] = out[i]
        }
        return out
    }

    /// `src`: width x height palette indices; `guide`: (factor width) x (factor height) RGB, the model's picture truncated to integers; `solid`:
    /// false where `src` is empty (its value is never used). Each of a pixel's factor^2 new pixels takes the neighbourhood colour closest to
    /// the guide; at least half keep the source colour, the rest going back to it in order of least gain. Ties go to the lowest index.
    public static func constrain(src: [Int], width w: Int, height h: Int, guide: [Int32], palette: [UInt8], solid: [Bool]? = nil, factor f: Int) -> [Int] {
        let F = f * f, W = w * f
        let c = canon(palette), P = palette.map(Int.init)
        var out = [Int](repeating: 0, count: F * w * h)
        var n = [Int](repeating: 0, count: 9), pick = [Int](repeating: 0, count: F), gain = pick
        for y in 0..<h {
            for x in 0..<w {
                let s = src[y * w + x]
                var m = 0
                for dy in -1...1 {
                    let yy = Swift.min(Swift.max(y + dy, 0), h - 1)
                    for dx in -1...1 {
                        let i = yy * w + Swift.min(Swift.max(x + dx, 0), w - 1)
                        let t = solid?[i] ?? true ? src[i] : s
                        var j = m
                        while j > 0 && n[j - 1] > t { n[j] = n[j - 1]; j -= 1 }
                        n[j] = t; m += 1
                    }
                }
                for j in 0..<F {
                    let g = (((y * f + j / f) * W) + x * f + j % f) * 3
                    let vr = Int(guide[g]), vg = Int(guide[g + 1]), vb = Int(guide[g + 2])
                    var best = Int.max, k = 0
                    for q in 0..<9 {
                        let r = P[3 * n[q]] - vr, gg = P[3 * n[q] + 1] - vg, b = P[3 * n[q] + 2] - vb
                        let d = r * r + gg * gg + b * b
                        if d < best { best = d; k = q }
                    }
                    pick[j] = n[k]
                    let r = P[3 * s] - vr, gg = P[3 * s + 1] - vg, b = P[3 * s + 2] - vb
                    gain[j] = c[n[k]] == c[s] ? -1 : r * r + gg * gg + b * b - best
                }
                for j in 0..<F {
                    var rank = 0
                    for i in 0..<F where gain[i] < gain[j] || (gain[i] == gain[j] && i < j) { rank += 1 }
                    out[((y * f + j / f) * W) + x * f + j % f] = rank < F / 2 ? s : pick[j]
                }
            }
        }
        return out
    }
}

/// Builds the pack into `root` (rooms/<CAM>/<ENTRY>.<frame>.frm, monitors/<CAM>/<ENTRY>.<frame>.frm, tex/<key>.frm, written atomically) and
/// resumes where it stopped: frames already on disk are skipped. `factor`: 2 or 4. `rooms`, `monitors`, `textureLimit`: limit the work (tests);
/// nil = everything.
public struct PixelPackBuilder {
    /// The `complete` marker holds this number. A lower one (version 1: an empty marker, before the monitor pass; version 2: before the smoothed
    /// outlines, 'BFX2' frames) means the pack is offered again, and only the frames it lacks are built.
    static let marker = "complete", version = 3
    let game: GameFolder, root: URL, factor: Int, upscaler: Upscaler, pad: Int
    let firstLevel: String?, rooms: Set<String>?, monitors: Set<String>?, textureLimit: Int?
    /// `run` stops with an error when the process's physical footprint passes this many bytes (the model's output buffers once grew it to tens of GB).
    let memoryLimit: Int

    public init(game: GameFolder, root: URL, factor: Int, upscaler: Upscaler, firstLevel: String? = nil, rooms: [String]? = nil, monitors: [String]? = nil, textureLimit: Int? = nil, memoryLimit: Int = 3 << 30, pad: Int = 24) {
        self.memoryLimit = memoryLimit; self.pad = pad
        self.game = game; self.root = root; self.factor = factor; self.upscaler = upscaler
        self.firstLevel = firstLevel; self.rooms = rooms.map { Set($0.map { $0.uppercased() }) }; self.textureLimit = textureLimit
        self.monitors = monitors.map { Set($0.map { $0.uppercased() }) }
    }

    /// The process's physical footprint in bytes (what Activity Monitor shows as Memory).
    static func footprint() -> Int {
        #if canImport(Darwin)
        var info = task_vm_info_data_t(), count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let r = withUnsafeMutablePointer(to: &info) { $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count) } }
        return r == KERN_SUCCESS ? Int(info.phys_footprint) : 0
        #else
        return 0        // the guard only protects the Core ML build
        #endif
    }

    /// Round `n` up to a multiple of 32, at most `limit`: the model's inputs come in 10 x 7 sizes, so Core ML does not plan each new one.
    static func bucket(_ n: Int, limit: Int) -> Int { Swift.min((n + 31) / 32 * 32, limit) }

    /// Grows [lo, hi) inside 0..<limit to `bucket(hi - lo)`: towards the end first, then the start.
    private static func grow(_ lo: Int, _ hi: Int, limit: Int) -> (Int, Int) {
        let more = bucket(hi - lo, limit: limit) - (hi - lo), right = Swift.min(more, limit - hi)
        return (lo - (more - right), hi + right)
    }

    /// True once a run of this version has finished with nothing left to build.
    public static func isComplete(root: URL) -> Bool {
        guard let d = try? Data(contentsOf: root.appendingPathComponent(marker)), let text = String(data: d, encoding: .utf8) else { return false }
        return (Int(text.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 1) >= version
    }

    /// The 'BFX3' file for a frame (HiResPack.decode is its inverse): u16 width, height, then raw DEFLATE of the indices and the mask.
    static func encode(width w: Int, height h: Int, pixels: [UInt8], mask: [UInt8]) throws -> Data {
        #if canImport(Darwin)
        let packed = try (Data(pixels + mask) as NSData).compressed(using: .zlib) as Data
        return Data("BFX3".utf8) + Data([UInt8(w & 0xff), UInt8(w >> 8), UInt8(h & 0xff), UInt8(h >> 8)]) + packed
        #else
        throw FormatError("High-Resolution Art packs need macOS")
        #endif
    }

    private func file(_ rel: String) -> URL { root.appendingPathComponent(rel + ".frm") }
    /// A frame on disk; one in the old 'BFX2' format (blocky outline) counts as missing, so it is built again.
    private func exists(_ rel: String) -> Bool {
        guard let h = try? FileHandle(forReadingFrom: file(rel)) else { return false }
        defer { try? h.close() }
        return (try? h.read(upToCount: 4)) != Data("BFX2".utf8)
    }

    private func write(_ rel: String, width: Int, height: Int, pixels: [UInt8], mask: [UInt8]) throws {
        let url = file(rel)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Self.encode(width: width, height: height, pixels: pixels, mask: mask).write(to: url, options: .atomic)
    }

    /// The model's picture as the filter's guide: as is at 4x, each 2x2 block averaged at 2x.
    private func guide(_ rgb: [UInt8], width w: Int, height h: Int) throws -> [Int32] {
        let pw = Swift.max(w, Self.bucket(w, limit: 320)), ph = Swift.max(h, Self.bucket(h, limit: 200))
        if pw != w || ph != h {                   // the model sees few sizes (and at least 2x2): repeat the edge, crop after
            var padded = [UInt8](repeating: 0, count: pw * ph * 3)
            for y in 0..<ph { for x in 0..<pw { for c in 0..<3 { padded[(y * pw + x) * 3 + c] = rgb[(min(y, h - 1) * w + min(x, w - 1)) * 3 + c] } } }
            let g = try guide(padded, width: pw, height: ph), f = factor
            var out = [Int32](repeating: 0, count: f * w * f * h * 3)
            for y in 0..<(f * h) { for x in 0..<(f * w) { for c in 0..<3 { out[(y * f * w + x) * 3 + c] = g[(y * f * pw + x) * 3 + c] } } }
            return out
        }
        let big = try upscaler.upscale(rgb, width: w, height: h)
        if factor == 4 { return big.map { Int32($0) } }
        let W = 4 * w
        var out = [Int32](repeating: 0, count: 2 * h * 2 * w * 3)
        for y in 0..<(2 * h) { for x in 0..<(2 * w) { for c in 0..<3 {
            let i = (2 * y * W + 2 * x) * 3 + c
            out[(y * 2 * w + x) * 3 + c] = Int32((big[i] + big[i + 3] + big[i + 3 * W] + big[i + 3 * W + 3]) / 4)
        } } }
        return out
    }

    private func enlarge<T>(_ a: [T], width w: Int, height h: Int) -> [T] {
        let f = factor
        var out = [T](); out.reserveCapacity(a.count * f * f)
        for y in 0..<(h * f) { for x in 0..<(w * f) { out.append(a[y / f * w + x / f]) } }
        return out
    }

    /// Scale2x (EPX) of a 0/1 mask: each pixel becomes 2x2, and a corner takes the value of the two neighbours beside it where they agree and
    /// the other two differ. Edges are replicated.
    static func scale2x(_ m: [UInt8], width w: Int, height h: Int) -> [UInt8] {
        var o = [UInt8](repeating: 0, count: 4 * w * h)
        for y in 0..<h { for x in 0..<w {
            let e = m[y * w + x], a = m[Swift.max(y - 1, 0) * w + x], d = m[Swift.min(y + 1, h - 1) * w + x]
            let b = m[y * w + Swift.max(x - 1, 0)], c = m[y * w + Swift.min(x + 1, w - 1)], i = 4 * y * w + 2 * x
            o[i] = a == b && a != c && b != d ? a : e
            o[i + 1] = a == c && a != b && c != d ? c : e
            o[i + 2 * w] = b == d && b != a && d != c ? b : e
            o[i + 2 * w + 1] = d == c && d != b && c != a ? d : e
        } }
        return o
    }

    /// A frame's outline smoothed: `mask` is the source's, `pixels` the output at `factor` (the colours of the enlarged mask are what counts).
    /// The mask is Scale2x once at 2x, twice at 4x. A sub-pixel that becomes opaque takes the colour of the nearest opaque one: 4-neighbour
    /// dilation, each pass reading the state at its start (up, down, left, right). One that becomes transparent only loses its mask.
    private func smoothed(_ pixels: [UInt8], mask: [UInt8], width w: Int, height h: Int) -> (pixels: [UInt8], mask: [UInt8]) {
        let src = mask.map { $0 != 0 ? UInt8(1) : 0 }, big = enlarge(src, width: w, height: h), W = factor * w, H = factor * h
        var m = src, n = 1
        while n < factor { m = Self.scale2x(m, width: n * w, height: n * h); n *= 2 }
        var solid = big.map { $0 != 0 }, fill = pixels
        let need = (0..<(W * H)).filter { m[$0] != 0 && big[$0] == 0 }
        while need.contains(where: { !solid[$0] }) {
            let s = solid, p = fill
            for i in 0..<(W * H) where !s[i] {
                let y = i / W, x = i % W
                for (ny, nx) in [(y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)] where ny >= 0 && ny < H && nx >= 0 && nx < W && s[ny * W + nx] {
                    fill[i] = p[ny * W + nx]; solid[i] = true; break
                }
            }
        }
        var out = pixels
        for i in need { out[i] = fill[i] }
        return (out, m)
    }

    // MARK: rooms

    /// Every sprite frame of a room in painting order (far to near, as Compositor), with the room's palette.
    private func roomEntries(_ name: String) throws -> (palette: [UInt8], entries: [(name: String, frames: [CAMFrame])]) {
        let room = try CAMFile(data: game.read("ROOMS/\(name).CAM"))
        var depths: [String: Int] = [:]
        for e in room.flex.entries { if let d = e.depth { depths[e.name.uppercased()] = d } }
        let sorted = room.images.sorted { a, b in
            let da = depths[a.name.uppercased()] ?? 99999, db = depths[b.name.uppercased()] ?? 99999
            return da != db ? da > db : a.index < b.index
        }
        return (room.palette, try sorted.map { ($0.name.uppercased(), try room.frames(of: $0)) })
    }

    private static func paint(_ img: inout [UInt8], _ f: CAMFrame) {
        let x0 = -f.hotX, y0 = -f.hotY
        let sx0 = Swift.max(0, x0), sy0 = Swift.max(0, y0), sx1 = Swift.min(Framebuffer.width, x0 + f.width), sy1 = Swift.min(Framebuffer.height, y0 + f.height)
        if sx1 <= sx0 || sy1 <= sy0 { return }
        for y in sy0..<sy1 { for x in sx0..<sx1 {
            let i = (y - y0) * f.width + x - x0
            if f.mask[i] != 0 { img[y * Framebuffer.width + x] = f.pixels[i] }
        } }
    }

    /// The frames of a room still to build, as (entry, frame index).
    private func roomTodo(_ name: String, _ entries: [(name: String, frames: [CAMFrame])]) -> [(entry: Int, frame: Int)] {
        var out: [(Int, Int)] = [], seen = Set<String>()
        for (e, entry) in entries.enumerated() {
            for (k, f) in entry.frames.enumerated() {
                let rel = "rooms/\(name)/\(entry.name).\(k)"
                if f.mask.contains(where: { $0 != 0 }) && !exists(rel) && seen.insert(rel).inserted { out.append((e, k)) }
            }
        }
        return out
    }

    private func buildRoomFrame(_ dir: String, palette: [UInt8], entries: [(name: String, frames: [CAMFrame])], finished: [UInt8], entry e: Int, frame k: Int) throws {
        let f = factor, W = Framebuffer.width, H = Framebuffer.height
        let fr = entries[e].frames[k]
        var out = enlarge(fr.pixels, width: fr.width, height: fr.height)
        let x0 = -fr.hotX, y0 = -fr.hotY
        let sx0 = Swift.max(0, x0), sy0 = Swift.max(0, y0), sx1 = Swift.min(W, x0 + fr.width), sy1 = Swift.min(H, y0 + fr.height)
        if sx1 > sx0 && sy1 > sy0 {                                  // the part on screen, filtered in place; the rest stays enlarged
            var img = finished
            Self.paint(&img, fr)
            let (cx0, cx1) = Self.grow(Swift.max(0, sx0 - pad), Swift.min(W, sx1 + pad), limit: W)
            let (cy0, cy1) = Self.grow(Swift.max(0, sy0 - pad), Swift.min(H, sy1 + pad), limit: H)
            let cw = cx1 - cx0, ch = cy1 - cy0
            var crop = [Int](), rgb = [UInt8]()
            for y in cy0..<cy1 { for x in cx0..<cx1 {
                let v = Int(img[y * W + x]); crop.append(v); rgb += palette[(3 * v)..<(3 * v + 3)]
            } }
            let big = PixelFilter.constrain(src: crop, width: cw, height: ch, guide: try guide(rgb, width: cw, height: ch), palette: palette, factor: f)
            let ox = f * (sx0 - cx0), oy = f * (sy0 - cy0), dx = f * (sx0 - x0), dy = f * (sy0 - y0)
            for y in 0..<(f * (sy1 - sy0)) { for x in 0..<(f * (sx1 - sx0)) {
                out[(dy + y) * f * fr.width + dx + x] = UInt8(big[(oy + y) * f * cw + ox + x])
            } }
        }
        let (pixels, mask) = smoothed(out, mask: fr.mask, width: fr.width, height: fr.height)
        try write("\(dir)/\(entries[e].name).\(k)", width: f * fr.width, height: f * fr.height, pixels: pixels, mask: mask)
    }

    // MARK: textures

    /// DATA/PALETTE.IFF's base palette: the PALT chunk's 768 bytes after a 4-byte header.
    func basePalette() throws -> [UInt8] {
        let d = try game.read("DATA/PALETTE.IFF")
        func find(_ nodes: [IFFNode]) -> IFFNode? {
            for n in nodes { if n.id == "PALT" { return n }; if let k = n.children, let f = find(k) { return f } }
            return nil
        }
        guard let n = find(try IFF.parse(d)), n.offset + 4 + 768 <= d.count else { throw FormatError("no PALT chunk in DATA/PALETTE.IFF") }
        return CAMImage.palette(Array(d[(n.offset + 4)..<(n.offset + 4 + 768)]))
    }

    /// Every distinct texture frame of the figures and items that has opaque texels, as (pack path, width, height, indices).
    private func textureFrames() -> [(rel: String, width: Int, height: Int, pixels: [UInt8])] {
        var out: [(String, Int, Int, [UInt8])] = [], seen = Set<String>()
        for path in game.list("BODY", ext: "EOR").map({ "BODY/\($0)" }) + game.list("ITEMS", ext: "IFF").map({ "ITEMS/\($0)" }) {
            guard let mesh = (try? game.read(path)).flatMap({ try? EORMesh(data: $0) }) else { continue }
            for (i, t) in mesh.textures.enumerated() {
                for frame in mesh.frames[i] ?? [t.pixels] {
                    let rel = String(format: "tex/%08x", HDArt.key(frame))
                    if frame.count == t.width * t.height && frame.contains(where: { $0 != 255 }) && seen.insert(rel).inserted { out.append((rel, t.width, t.height, frame)) }
                }
            }
        }
        return textureLimit.map { Array(out.prefix($0)) } ?? out
    }

    /// Spreads opaque colours over transparent texels so the model does not smear the key colour into the edges. Like np.roll, it wraps around.
    static func dilate(_ rgb: [UInt8], solid: [Bool], width w: Int, height h: Int) -> [UInt8] {
        var rgb = rgb, solid = solid
        while solid.contains(false) && solid.contains(true) {
            var grown = solid
            for (axis, shift) in [(0, 1), (0, -1), (1, 1), (1, -1)] {
                for y in 0..<h { for x in 0..<w {
                    let q = axis == 0 ? ((y - shift + h) % h) * w + x : y * w + (x - shift + w) % w, p = y * w + x
                    if solid[q] && !grown[p] { rgb.replaceSubrange((3 * p)..<(3 * p + 3), with: rgb[(3 * q)..<(3 * q + 3)]); grown[p] = true }
                } }
            }
            solid = grown
        }
        return rgb
    }

    private func buildTexture(_ t: (rel: String, width: Int, height: Int, pixels: [UInt8]), palette: [UInt8]) throws {
        try buildStandalone(t, solid: t.pixels.map { $0 != 255 }, palette: palette)
    }

    /// A frame on its own (no neighbours): masked pixels are dilated into the guide's input, never picked, and left transparent (255) in the output.
    private func buildStandalone(_ t: (rel: String, width: Int, height: Int, pixels: [UInt8]), solid: [Bool], palette: [UInt8]) throws {
        let f = factor
        var rgb = [UInt8]()
        for v in t.pixels { rgb += palette[(3 * Int(v))..<(3 * Int(v) + 3)] }
        let guide = try guide(Self.dilate(rgb, solid: solid, width: t.width, height: t.height), width: t.width, height: t.height)
        let big = PixelFilter.constrain(src: t.pixels.map(Int.init), width: t.width, height: t.height, guide: guide, palette: palette, solid: solid, factor: f)
        let source = solid.map { $0 ? UInt8(1) : 0 }, enlarged = enlarge(source, width: t.width, height: t.height)
        let (pixels, mask) = smoothed(zip(big, enlarged).map { $1 == 0 ? 255 : UInt8($0) }, mask: source, width: t.width, height: t.height)
        try write(t.rel, width: f * t.width, height: f * t.height, pixels: zip(pixels, mask).map { $1 == 0 ? 255 : $0 }, mask: mask)
    }

    // MARK: monitors

    private enum MonitorWork { case background(CAMFrame), element(CAMFrame) }      // element: a pointer frame

    /// The frames MonitorScreen.render takes from the pack for MONITORS/<name>.CAM that still need building, with their pack paths: frame 0 of the
    /// first entry named like the file is the background (filtered like a room). The screen's other elements (buttons, gauges, scale bars, plain
    /// art) are drawn plain-doubled like the text, so they are not built. A CAM without such an entry is a pointer (POINTER.CAM, or one MON_SETPTR
    /// names): every frame of its first entry is built standalone. Skipped: 1x1 or empty frames.
    private func monitorTodo(_ name: String, _ cam: CAMFile) throws -> [(rel: String, work: MonitorWork)] {
        var out: [(String, MonitorWork)] = []
        if let entry = cam.images.first(where: { $0.name.uppercased() == name }) {
            if let f = try cam.frames(of: entry).first, f.mask.contains(where: { $0 != 0 }), !exists("monitors/\(name)/\(name).0") {
                out.append(("monitors/\(name)/\(name).0", .background(f)))
            }
        } else if let entry = cam.images.first {
            let n = entry.name.uppercased()
            for (k, f) in try cam.frames(of: entry).enumerated() where f.width * f.height > 1 && f.mask.contains(where: { $0 != 0 }) && !exists("monitors/\(name)/\(n).\(k)") {
                out.append(("monitors/\(name)/\(n).\(k)", .element(f)))
            }
        }
        return out
    }

    private func monitorNames() -> [String] {
        let names = game.list("MONITORS", ext: "CAM").map { ($0 as NSString).deletingPathExtension.uppercased() }
        return monitors.map { m in names.filter(m.contains) } ?? names
    }

    private func buildMonitorFrame(_ name: String, _ cam: CAMFile, rel: String, work: MonitorWork) throws {
        switch work {
        case .background(let f):                                           // a room's finished picture is its background; here, itself
            var finished = [UInt8](repeating: 0, count: Framebuffer.width * Framebuffer.height)
            Self.paint(&finished, f)
            try buildRoomFrame("monitors/\(name)", palette: cam.palette, entries: [(name, [f])], finished: finished, entry: 0, frame: 0)
        case .element(let f):
            try buildStandalone((rel, f.width, f.height, f.pixels), solid: f.mask.map { $0 != 0 }, palette: cam.palette)
        }
    }

    // MARK: run

    /// Room names to build, those of `firstLevel` first: (those, the rest).
    private func roomNames() -> (first: [String], rest: [String]) {
        var names = game.list("ROOMS", ext: "CAM").map { ($0 as NSString).deletingPathExtension.uppercased() }
        if let rooms { names = names.filter(rooms.contains) }
        let first = firstLevel.flatMap { try? Level(name: $0.uppercased(), data: game.read("INITGAME/\($0.uppercased()).IFF")) }.map { Set($0.cameras.keys) } ?? []
        return (names.filter(first.contains), names.filter { !first.contains($0) })
    }

    private func checkMemory() throws {
        let used = Self.footprint()
        if used > memoryLimit { throw FormatError("stopped building art: BioForge was using \(used >> 20) MB of memory") }
    }

    /// Builds what is missing: textures, the rooms of `firstLevel`, the monitors, then the other rooms. `isCancelled` is asked between frames.
    /// `progress`: share of the work found at the start that is done, 0...1. `roomDone`: a room's frames are on disk ("" after the textures), so a
    /// HiResPack can forget its misses; `monitorDone` the same for a monitor (POINTER included). Writes the `complete` marker when the run ends
    /// with nothing left.
    public func run(isCancelled: () -> Bool, progress: (Double) -> Void, roomDone: (String) -> Void, monitorDone: (String) -> Void = { _ in }) throws {
        let palette = try basePalette()
        let textures = textureFrames().filter { !exists($0.rel) }
        let (firstRooms, otherRooms) = roomNames()
        var cams: [(name: String, cam: CAMFile, todo: [(rel: String, work: MonitorWork)])] = []
        for name in monitorNames() {
            let cam = try CAMFile(data: game.read("MONITORS/\(name).CAM"))
            let todo = try monitorTodo(name, cam)
            if !todo.isEmpty { cams.append((name, cam, todo)) }
        }
        var total = textures.count + cams.reduce(0) { $0 + $1.todo.count }, done = 0
        for name in firstRooms + otherRooms { let r = try roomEntries(name); total += roomTodo(name, r.entries).count }
        func tick() { done += 1; progress(Double(done) / Double(total)) }
        for t in textures {
            if isCancelled() { return }
            try checkMemory()
            try withPool { try buildTexture(t, palette: palette) }
            tick()
        }
        if !textures.isEmpty { roomDone("") }
        func buildRooms(_ names: [String]) throws -> Bool {
            for name in names {
                let (pal, entries) = try roomEntries(name)
                let todo = roomTodo(name, entries)
                if todo.isEmpty { continue }
                var finished = [UInt8](repeating: 0, count: Framebuffer.width * Framebuffer.height)
                for entry in entries { if let f = entry.frames.first { Self.paint(&finished, f) } }
                for (e, k) in todo {
                    if isCancelled() { return false }
                    try checkMemory()
                    try withPool { try buildRoomFrame("rooms/\(name)", palette: pal, entries: entries, finished: finished, entry: e, frame: k) }
                    tick()
                }
                roomDone(name)
            }
            return true
        }
        guard try buildRooms(firstRooms) else { return }
        for (name, cam, todo) in cams {
            for (rel, work) in todo {
                if isCancelled() { return }
                try checkMemory()
                try withPool { try buildMonitorFrame(name, cam, rel: rel, work: work) }
                tick()
            }
            monitorDone(name)
        }
        guard try buildRooms(otherRooms) else { return }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("\(Self.version)\n".utf8).write(to: root.appendingPathComponent(Self.marker))
    }
}
