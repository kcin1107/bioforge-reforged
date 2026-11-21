// Parity tests against the Python prototype (re/tools/native_fixtures.py -> Fixtures/fixtures.json).
// The fixtures hold only derived data (counts, geometry, SHA-256); the game files come from $BIOFORGE_DATA.
import Foundation
import Testing
@testable import BioForgeCore

typealias JSON = [String: Any]

nonisolated(unsafe) let fixtures: JSON = {
    let url = Bundle.module.url(forResource: "fixtures", withExtension: "json")!
    return try! JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! JSON
}()
let game = GameFolder.fromEnvironment()

func sha(_ b: [UInt8]) -> String { Sha256.hex(b) }

/// The suite is skipped (with a message) when BIOFORGE_DATA is unset; a set but wrong folder fails.
func requireGame() throws -> GameFolder {
    guard let g = game, g.isValid else { throw FormatError("BIOFORGE_DATA is not a BioForge folder (BIOFORGE.EXE + ROOMS/)") }
    return g
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct OracleTests {
    @Test func camFixtures() throws {
        let g = try requireGame()
        var frames = 0
        for (path, any) in fixtures["cams"] as! JSON {
            let fx = any as! JSON
            let cam = try CAMFile(data: g.read(path))
            #expect(cam.flex.entries.count == fx["entries"] as! Int, "\(path) entry count")
            #expect(cam.flex.entries.map(\.name) == fx["names"] as! [String], "\(path) names")
            #expect(sha(cam.palette) == fx["palette"] as! String, "\(path) palette")
            let images = fx["images"] as! [JSON]
            #expect(cam.images.count == images.count, "\(path) image count")
            for (e, ix) in zip(cam.images, images) {
                #expect(e.index == ix["index"] as! Int && e.name == ix["name"] as! String && e.size == ix["size"] as! Int)
                let fr = try cam.frames(of: e), fxf = ix["frames"] as! [JSON]
                #expect(fr.count == fxf.count, "\(path) \(e.name) frame count")
                for (f, x) in zip(fr, fxf) {
                    let tag = "\(path) \(e.name)"
                    #expect(f.width == x["w"] as! Int && f.height == x["h"] as! Int, "\(tag) size")
                    #expect(f.hotX == x["hotx"] as! Int && f.hotY == x["hoty"] as! Int, "\(tag) hotspot")
                    #expect(sha(f.pixels) == x["pixels"] as! String, "\(tag) pixels")
                    #expect(sha(f.mask) == x["mask"] as! String, "\(tag) mask")
                    frames += 1
                }
            }
        }
        print("camFixtures: \((fixtures["cams"] as! JSON).count) files, \(frames) frames matched")
    }

    @Test func flexFixtures() throws {
        let g = try requireGame()
        for (path, any) in fixtures["flex"] as! JSON {
            let fx = any as! JSON
            let flex = try Flex(data: g.read(path))
            #expect(flex.entries.count == fx["count"] as! Int, "\(path) count")
            let list = fx["entries"] as! [[Any]]
            for (e, x) in zip(flex.entries, list) {
                #expect(e.offset == x[0] as! Int && e.size == x[1] as! Int && e.name == x[2] as! String, "\(path)[\(e.index)]")
            }
            let depths = fx["depths"] as! [String: Int]
            let mine = Dictionary(flex.entries.compactMap { e in e.depth.map { (e.name.uppercased(), $0) } }, uniquingKeysWith: { $1 })
            #expect(mine == depths, "\(path) depths")
        }
    }

    @Test func levelFixtures() throws {
        let g = try requireGame()
        for (path, any) in fixtures["levels"] as! JSON where path != "iff_top" {
            let fx = any as! JSON
            let objs = try LevelObjects.load(g.read(path))
            var counts: [String: Int] = [:]
            for o in objs { counts[o.tag, default: 0] += 1 }
            #expect(counts == fx["counts"] as! [String: Int], "\(path) counts")
            let names = (fx["names"] as! [[String]]).map { $0[0] + "/" + $0[1] }
            #expect(objs.map { $0.tag + "/" + $0.name } == names, "\(path) names")
            let p2 = fx["pos2"] as! [[Int]]
            #expect(Array(objs.compactMap(\.pos2).prefix(p2.count)) == p2, "\(path) pos2")
            let cams = fx["cameras"] as! [JSON]
            let mine = objs.filter { $0.tag == "CAMR" }
            #expect(mine.count == cams.count, "\(path) CAMR count")
            for (o, c) in zip(mine, cams) {
                #expect(o.name == c["name"] as! String && o.pos == (c["pos"] as! [Int]) && o.flag == c["flag"] as? Int, "\(path) \(o.name)")
                #expect(o.rotation == (c["rot"] as! [Int]) && o.vec == (c["vec"] as! [Int]) && o.extra == (c["extra"] as! [Int]), "\(path) \(o.name) matrix")
            }
        }
        let top = (fixtures["levels"] as! JSON)["iff_top"] as! JSON
        let d = try g.read("INITGAME/CHAOS.IFF")
        let form = try IFF.parse(d)[0]
        #expect(form.type == top["type"] as? String)
        let kids = (top["kids"] as! [[Any]]).map { "\($0[0] as! String)/\($0[1] as! Int)" }
        #expect(Array(form.children!.map { "\($0.id)/\($0.size)" }.prefix(kids.count)) == kids)
    }

    /// check_cams.py: 8446 frames ok over ROOMS + MONITORS (5887 + 2559).
    @Test func decodesEveryFrame() throws {
        let g = try requireGame()
        var total = 0
        for (dir, key) in [("ROOMS", "rooms_total_frames"), ("MONITORS", "monitors_total_frames")] {
            var n = 0
            for name in g.list(dir, ext: "CAM") {
                let cam = try CAMFile(data: g.read("\(dir)/\(name)"))
                for e in cam.images { n += try cam.frames(of: e).count }
            }
            #expect(n == fixtures[key] as! Int, "\(dir) frame count")
            total += n
        }
        #expect(total == 8446)
        print("decodesEveryFrame: \(total) frames decoded")
    }
}

@Suite struct SyntheticTests {
    @Test func caseInsensitiveLookup() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("bf-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("ROOMS"), withIntermediateDirectories: true)
        try Data([1]).write(to: dir.appendingPathComponent("ROOMS/AIR1.CAM"))
        defer { try? FileManager.default.removeItem(at: dir) }
        #expect(GameFolder(dir).resolve("rooms/air1.cam") != nil)
        #expect(GameFolder(dir).resolve("rooms/none.cam") == nil)
    }

    @Test func rleFrameAndBlit() throws {
        // 4x1 rle frame, hotspot (1,0): skip 1, run of 3x7 (n = 3<<1|1), row ends at x == 4.
        var f: [UInt8] = [1, 0, 4, 0, 1, 0, 1, 0, 0, 0, 0, 0]
        f[10] = 2; f[11] = 0                       // rowoff[0] = 2 (relative to its own position)
        f += [1, 7, 7]
        let fr = try CAMImage.decodeFrame(f, at: 0)
        #expect(fr.pixels == [0, 7, 7, 7] && fr.mask == [0, 1, 1, 1] && fr.hotX == 1)
        var fb = Framebuffer()
        fb.blit(fr, x: 10, y: 3)
        #expect(fb.pixels[3 * 320 + 10] == 7 && fb.pixels[3 * 320 + 11] == 7 && fb.pixels[3 * 320 + 9] == 0)
    }
}
