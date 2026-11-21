import Testing
import Foundation
@testable import BioForgeCore

/// The model's picture replaced by the source enlarged 4x, so a build is deterministic and needs no model.
struct NearestUpscaler: Upscaler {
    func upscale(_ rgb: [UInt8], width w: Int, height h: Int) throws -> [Float] {
        (0..<(16 * w * h)).flatMap { i in (0..<3).map { Float(rgb[3 * ((i / (4 * w) / 4) * w + i % (4 * w) / 4) + $0]) } }
    }
}

/// Records every input size it is given.
final class ShapeRecorder: Upscaler, @unchecked Sendable {
    private let lock = NSLock()
    private var seen = Set<[Int]>()
    var shapes: Set<[Int]> { lock.lock(); defer { lock.unlock() }; return seen }
    func upscale(_ rgb: [UInt8], width w: Int, height h: Int) throws -> [Float] {
        lock.lock(); seen.insert([w, h]); lock.unlock()
        return try NearestUpscaler().upscale(rgb, width: w, height: h)
    }
}

/// The packs' DEFLATE codec is Apple Foundation's; elsewhere packs are not built or read yet.
#if canImport(Darwin)
let packCodec = true
#else
let packCodec = false
#endif

@Suite struct PixelPackTests {

    @Test func bucketRoundsUpToThirtyTwoWithinTheLimit() {
        let w = [1, 2, 32, 33, 64, 300, 320].map { PixelPackBuilder.bucket($0, limit: 320) }
        #expect(w == [32, 32, 32, 64, 64, 320, 320])
        let h = [1, 32, 33, 192, 193, 199, 200].map { PixelPackBuilder.bucket($0, limit: 200) }
        #expect(h == [32, 32, 64, 192, 200, 200, 200])
    }
    static func tempDir() -> URL { FileManager.default.temporaryDirectory.appendingPathComponent("pixelpack-\(UUID().uuidString)") }

    @Test func constrainMatchesPython() throws {
        let url = try #require(Bundle.module.url(forResource: "pixel_filters", withExtension: "json"))
        let fx = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? JSON)
        let palette = (fx["palette"] as! [Int]).map { UInt8($0) }
        let cases = fx["cases"] as! [JSON]
        #expect(!cases.isEmpty)
        for c in cases {
            let f = c["factor"] as! Int, w = c["width"] as! Int, h = c["height"] as! Int
            let out = PixelFilter.constrain(src: c["src"] as! [Int], width: w, height: h, guide: (c["guide"] as! [Int]).map { Int32($0) }, palette: palette,
                                            solid: (c["solid"] as? [Int]).map { $0.map { $0 != 0 } } ?? (c["solid"] as? [Bool]), factor: f)
            #expect(out == c["out"] as! [Int], "factor \(f) \(w)x\(h) solid \(c["solid"] is NSNull ? "none" : "mask")")
        }
    }

    @Test(.enabled(if: packCodec, "High-Resolution Art packs need macOS")) func encodeDecodeRoundTrip() throws {
        let px = (0..<(6 * 4)).map { UInt8($0 * 7 % 256) }, mask = (0..<(6 * 4)).map { UInt8($0 % 3 == 0 ? 0 : 1) }
        let f = try #require(HiResPack.decode(PixelPackBuilder.encode(width: 6, height: 4, pixels: px, mask: mask)))
        #expect(f.width == 6 && f.height == 4 && f.pixels == px && f.mask == mask)
    }

    @Test func scale2xSmoothsStaircasesOnly() {
        let stairs: [UInt8] = [1, 0, 0, 1, 1, 0, 1, 1, 1]       // the same pattern and result as test_pixel_pack.py
        let rows = stride(from: 0, to: 36, by: 6).map { r in PixelPackBuilder.scale2x(stairs, width: 3, height: 3)[r..<(r + 6)].map(String.init).joined() }
        #expect(rows == ["110000", "111000", "111000", "111110", "111111", "111111"])
        func enlarged(_ m: [UInt8], _ w: Int, _ h: Int) -> [UInt8] { (0..<(4 * w * h)).map { m[$0 / (2 * w) / 2 * w + $0 % (2 * w) / 2] } }
        let edge: [UInt8] = [1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0], lone: [UInt8] = [0, 0, 0, 0, 1, 0, 0, 0, 0]
        #expect(PixelPackBuilder.scale2x(edge, width: 4, height: 3) == enlarged(edge, 4, 3), "a straight edge stays")
        #expect(PixelPackBuilder.scale2x(lone, width: 3, height: 3) == enlarged(lone, 3, 3), "a lone pixel stays")
    }

    @Test(.enabled(if: packCodec, "High-Resolution Art packs need macOS")) func decodeReadsBFX2AndBFX3() throws {
        let px = [UInt8](repeating: 7, count: 6), mask = [UInt8](repeating: 1, count: 6)
        let v3 = try PixelPackBuilder.encode(width: 3, height: 2, pixels: px, mask: mask)
        #expect(v3.prefix(4) == Data("BFX3".utf8))
        let v2 = Data("BFX2".utf8) + v3.dropFirst(4)
        for data in [v3, v2] { #expect(HiResPack.decode(data)?.pixels == px) }
        #expect(HiResPack.decode(Data("BFX1".utf8) + v3.dropFirst(4)) == nil)
    }

    @Test func dilateWrapsAround() {
        let rgb: [UInt8] = [10, 11, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0], solid = [true, false, false, false]
        let out = PixelPackBuilder.dilate(rgb, solid: solid, width: 4, height: 1)
        #expect(out == [10, 11, 12, 10, 11, 12, 10, 11, 12, 10, 11, 12])
    }
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .enabled(if: packCodec, "High-Resolution Art packs need macOS"))
struct PixelPackBuildTests {
    @Test func buildsResumesAndMarksComplete() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        func builder() -> PixelPackBuilder { PixelPackBuilder(game: g, root: root, factor: 2, upscaler: NearestUpscaler(), rooms: ["ce11"], monitors: [], textureLimit: 3) }

        var progress: [Double] = [], done: [String] = [], calls = 0
        try builder().run(isCancelled: { calls += 1; return calls > 2 }, progress: { progress.append($0) }, roomDone: { done.append($0) })
        #expect(progress.count == 2 && !PixelPackBuilder.isComplete(root: root), "cancelled between frames")

        progress = []; done = []
        try builder().run(isCancelled: { false }, progress: { progress.append($0) }, roomDone: { done.append($0) })
        #expect(progress.last == 1 && done.first == "" && done.last == "CE11" && PixelPackBuilder.isComplete(root: root))

        let room = try CAMFile(data: g.read("ROOMS/CE11.CAM"))
        var frames = 0
        for e in room.images {
            for (k, f) in try room.frames(of: e).enumerated() {
                let url = root.appendingPathComponent("rooms/CE11/\(e.name.uppercased()).\(k).frm")
                guard f.mask.contains(where: { $0 != 0 }) else { #expect(!FileManager.default.fileExists(atPath: url.path)); continue }
                let big = try #require(HiResPack.decode(Data(contentsOf: url)), Comment(rawValue: url.lastPathComponent))
                #expect(big.width == 2 * f.width && big.height == 2 * f.height && big.mask.count == big.width * big.height)
                #expect(big.mask == PixelPackBuilder.scale2x(f.mask.map { $0 != 0 ? 1 : 0 }, width: f.width, height: f.height), "the outline is smoothed: \(url.lastPathComponent)")
                frames += 1
            }
        }
        #expect(frames > 0)
        let texDir = root.appendingPathComponent("tex")
        let texFiles = try FileManager.default.contentsOfDirectory(atPath: texDir.path).filter { $0.hasSuffix(".frm") }
        #expect(texFiles.count == 3)
        for name in texFiles {
            let t = try #require(HiResPack.decode(Data(contentsOf: texDir.appendingPathComponent(name))))
            #expect(name.range(of: "^[0-9a-f]{8}\\.frm$", options: .regularExpression) != nil)
            #expect(zip(t.pixels, t.mask).allSatisfy { $1 != 0 || $0 == 255 })
        }

        let stamp = try FileManager.default.subpathsOfDirectory(atPath: root.path).filter { $0.hasSuffix(".frm") }.map { p in
            (p, (try? FileManager.default.attributesOfItem(atPath: root.appendingPathComponent(p).path)[.modificationDate] as? Date) ?? nil) }
        progress = []; done = []
        try builder().run(isCancelled: { false }, progress: { progress.append($0) }, roomDone: { done.append($0) })
        #expect(progress.isEmpty && done.isEmpty, "a finished pack has nothing left")
        let after = try FileManager.default.subpathsOfDirectory(atPath: root.path).filter { $0.hasSuffix(".frm") }.map { p in
            (p, (try? FileManager.default.attributesOfItem(atPath: root.appendingPathComponent(p).path)[.modificationDate] as? Date) ?? nil) }
        #expect(stamp.count == after.count && zip(stamp, after).allSatisfy { $0 == $1 })
        #expect(after.count == frames + 3)
    }
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .enabled(if: packCodec, "High-Resolution Art packs need macOS"))
struct PixelPackMonitorTests {
    static func builder(_ g: GameFolder, _ root: URL, monitors: [String]) -> PixelPackBuilder {
        PixelPackBuilder(game: g, root: root, factor: 2, upscaler: NearestUpscaler(), rooms: [], monitors: monitors, textureLimit: 0)
    }

    /// What the pass should write for a CAM: pack path -> frame, as MonitorScreen draws them from the pack: the background (frame 0 of the
    /// entry named like the file) and nothing else; a CAM without one is a pointer, all frames of its first entry (no 1x1 dummies).
    static func expected(_ g: GameFolder, _ name: String) throws -> [String: CAMFrame] {
        let cam = try CAMFile(data: g.read("MONITORS/\(name).CAM"))
        if let e = cam.images.first(where: { $0.name.uppercased() == name }) { return ["monitors/\(name)/\(name).0": try cam.frames(of: e)[0]] }
        let e = try #require(cam.images.first), n = e.name.uppercased()
        var out: [String: CAMFrame] = [:]
        for (k, f) in try cam.frames(of: e).enumerated() where f.width * f.height > 1 && f.mask.contains(where: { $0 != 0 }) { out["monitors/\(name)/\(n).\(k)"] = f }
        return out
    }

    @Test func monitorPassBuildsOnlyBackgrounds() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        try Self.builder(g, root, monitors: ["pimm", "crym"]).run(isCancelled: { false }, progress: { _ in }, roomDone: { _ in })
        let files = try FileManager.default.subpathsOfDirectory(atPath: root.path).filter { $0.hasSuffix(".frm") }
        #expect(Set(files) == ["monitors/PIMM/PIMM.0.frm", "monitors/CRYM/CRYM.0.frm"], "buttons, gauges and bars are drawn plain-doubled")
    }

    @Test func monitorPassWritesResumesAndMarksComplete() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        let want = try Self.expected(g, "POINTER")
        #expect(want.count == 3 && want.keys.contains("monitors/POINTER/HAND.1"), "frame 0 is an empty full-screen frame")

        var calls = 0, done: [String] = [], progress: [Double] = []
        try Self.builder(g, root, monitors: ["pointer"]).run(isCancelled: { calls += 1; return calls > 2 }, progress: { progress.append($0) }, roomDone: { _ in }, monitorDone: { done.append($0) })
        #expect(progress.count == 2 && done.isEmpty && !PixelPackBuilder.isComplete(root: root), "stopped between frames")

        progress = []
        try Self.builder(g, root, monitors: ["pointer"]).run(isCancelled: { false }, progress: { progress.append($0) }, roomDone: { _ in }, monitorDone: { done.append($0) })
        #expect(progress.count == want.count - 2 && progress.last == 1 && done == ["POINTER"] && PixelPackBuilder.isComplete(root: root))
        let files = try FileManager.default.subpathsOfDirectory(atPath: root.path).filter { $0.hasSuffix(".frm") }
        #expect(Set(files.map { String($0.dropLast(4)) }) == Set(want.keys), "no dummy frames")
        for (rel, f) in want {
            let big = try #require(HiResPack.decode(Data(contentsOf: root.appendingPathComponent(rel + ".frm"))), Comment(rawValue: rel))
            #expect(big.width == 2 * f.width && big.height == 2 * f.height, Comment(rawValue: rel))
            #expect(big.mask == PixelPackBuilder.scale2x(f.mask.map { $0 != 0 ? 1 : 0 }, width: f.width, height: f.height), "the mask is the source's, smoothed: \(rel)")
            #expect(zip(big.pixels, big.mask).allSatisfy { $1 != 0 || $0 == 255 }, "masked pixels are transparent: \(rel)")
        }

        var again = 0
        try Self.builder(g, root, monitors: ["pointer"]).run(isCancelled: { false }, progress: { _ in again += 1 }, roomDone: { _ in }, monitorDone: { _ in again += 1 })
        #expect(again == 0, "a finished pack has nothing left")
    }

    /// A frame in the old 'BFX2' format counts as missing: a run builds it again, as 'BFX3'.
    @Test func oldFormatFramesAreRebuilt() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        let b = Self.builder(g, root, monitors: ["BLNK"])
        try b.run(isCancelled: { false }, progress: { _ in }, roomDone: { _ in })
        let rel = try #require((try FileManager.default.subpathsOfDirectory(atPath: root.path)).first { $0.hasSuffix(".frm") })
        let url = root.appendingPathComponent(rel)
        let new = try Data(contentsOf: url)
        #expect(new.prefix(4) == Data("BFX3".utf8))
        try (Data("BFX2".utf8) + new.dropFirst(4)).write(to: url)
        var built = 0
        try b.run(isCancelled: { false }, progress: { _ in built += 1 }, roomDone: { _ in })
        let again = try Data(contentsOf: url)
        #expect(built == 1 && again == new)
    }

    /// The model only ever sees bucketed sizes, whatever the crop or the art.
    @Test func modelSeesBucketedShapes() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        let rec = ShapeRecorder()
        try PixelPackBuilder(game: g, root: root, factor: 2, upscaler: rec, rooms: ["CE11", "CRYM"], monitors: ["CRYM", "PIMM"], textureLimit: 20)
            .run(isCancelled: { false }, progress: { _ in }, roomDone: { _ in }, monitorDone: { _ in })
        let widths = Set(stride(from: 32, through: 320, by: 32)), heights = Set(Array(stride(from: 32, through: 192, by: 32)) + [200])
        #expect(rec.shapes.count > 3)
        for s in rec.shapes { #expect(widths.contains(s[0]) && heights.contains(s[1]), Comment(rawValue: "\(s[0])x\(s[1])")) }
    }

    /// Above the memory limit the build stops before its next frame.
    @Test func memoryGuardStopsTheBuild() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        let b = PixelPackBuilder(game: g, root: root, factor: 2, upscaler: NearestUpscaler(), rooms: ["CE11"], monitors: [], textureLimit: 3, memoryLimit: 1)
        #expect(throws: FormatError.self) { try b.run(isCancelled: { false }, progress: { _ in }, roomDone: { _ in }) }
        #expect(!FileManager.default.fileExists(atPath: root.path))
    }

    /// A pack finished before the monitor pass (an empty marker) is offered again, and a run builds only what it lacks.
    @Test func oldMarkerCountsAsIncomplete() throws {
        let g = try requireGame()
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let marker = root.appendingPathComponent("complete")
        #expect(!PixelPackBuilder.isComplete(root: root))
        try Data().write(to: marker)
        #expect(!PixelPackBuilder.isComplete(root: root), "version 1: an empty marker")
        try Data("2\n".utf8).write(to: marker)
        #expect(!PixelPackBuilder.isComplete(root: root), "version 2: blocky outlines")
        try Data("3\n".utf8).write(to: marker)
        #expect(PixelPackBuilder.isComplete(root: root))

        try Data().write(to: marker)
        var built = 0
        try Self.builder(g, root, monitors: ["BLNK"]).run(isCancelled: { false }, progress: { _ in built += 1 }, roomDone: { _ in })
        #expect(built == (try Self.expected(g, "BLNK")).count && built > 0 && PixelPackBuilder.isComplete(root: root))
    }
}

#if canImport(CoreML)
/// Opt-in: BIOFORGE_HD_MODEL (HDCube.mlmodelc) and BIOFORGE_HD_REFERENCE (a pack made by re/tools/pixel_pack.py at 2x) both set.
@Suite(.enabled(if: game != nil && ProcessInfo.processInfo.environment["BIOFORGE_HD_MODEL"] != nil && ProcessInfo.processInfo.environment["BIOFORGE_HD_REFERENCE"] != nil,
                "BIOFORGE_HD_MODEL and BIOFORGE_HD_REFERENCE are not set"))
struct PixelPackParityTests {
    @Test func coreMLMatchesTorchReference() throws {
        let env = ProcessInfo.processInfo.environment
        let g = try requireGame()
        let reference = URL(fileURLWithPath: env["BIOFORGE_HD_REFERENCE"]!, isDirectory: true)
        let root = PixelPackTests.tempDir()
        defer { try? FileManager.default.removeItem(at: root) }
        let up = try CoreMLUpscaler(modelURL: URL(fileURLWithPath: env["BIOFORGE_HD_MODEL"]!))
        let start = Date()
        try PixelPackBuilder(game: g, root: root, factor: 2, upscaler: up, rooms: ["CE11"], monitors: [], textureLimit: 0).run(isCancelled: { false }, progress: { _ in }, roomDone: { _ in })
        let seconds = Date().timeIntervalSince(start)
        var differ = 0, total = 0, frames = 0
        let dir = root.appendingPathComponent("rooms/CE11")
        for name in try FileManager.default.contentsOfDirectory(atPath: dir.path) {
            let mine = try #require(HiResPack.decode(Data(contentsOf: dir.appendingPathComponent(name))))
            let ref = try #require(HiResPack.decode(Data(contentsOf: reference.appendingPathComponent("rooms/CE11/\(name)"))), Comment(rawValue: name))
            #expect(mine.width == ref.width && mine.height == ref.height && mine.mask == ref.mask, Comment(rawValue: name))
            differ += zip(mine.pixels, ref.pixels).filter { $0 != $1 }.count
            total += mine.pixels.count; frames += 1
        }
        let percent = 100 * Double(differ) / Double(total)
        print("PixelPack parity CE11: \(frames) frames, \(differ) of \(total) pixels differ (\(percent)%), built in \(seconds) s")
        #expect(frames > 0 && percent < 1)
    }
}

/// Opt-in: BIOFORGE_HD_MODEL set. Many calls in one loop with no autorelease pool around it, as the builder's block runs.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["BIOFORGE_HD_MODEL"] != nil, "BIOFORGE_HD_MODEL is not set"))
struct CoreMLMemoryTests {
    @Test func footprintStaysFlatOverManyCalls() throws {
        let up = try CoreMLUpscaler(modelURL: URL(fileURLWithPath: ProcessInfo.processInfo.environment["BIOFORGE_HD_MODEL"]!))
        let shapes = [(320, 200), (64, 32), (96, 160), (32, 192), (256, 64), (128, 128), (192, 96)]
        func call(_ i: Int) throws { let (w, h) = shapes[i % shapes.count]; _ = try up.upscale([UInt8](repeating: UInt8(i & 255), count: 3 * w * h), width: w, height: h) }
        for i in 0..<shapes.count { try call(i) }               // loads the model and plans each shape once
        let before = PixelPackBuilder.footprint()
        var samples = [Int]()                                    // averages, so one call's working buffers don't decide it
        for i in 1...200 { try call(i); samples.append(PixelPackBuilder.footprint() - before) }
        let early = samples[..<100].reduce(0, +) / 100, late = samples[100...].reduce(0, +) / 100
        print("footprint over 200 calls: mean \(early >> 20) MB then \(late >> 20) MB, peak \(samples.max()! >> 20) MB")
        #expect(late - early < 50 << 20 && samples.max()! < 1 << 30)
    }
}
#endif
