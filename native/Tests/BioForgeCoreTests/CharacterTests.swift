// Stage 2 parity tests: meshes, skeletons/motions, posed vertices and indexed scene renders against the Python prototype
// (fixtures.json "stage2", written by re/tools/native_fixtures.py). Byte layouts hashed here mirror that script.
import Foundation
import Testing
@testable import BioForgeCore

/// Little-endian byte builder (struct.pack('<...')).
struct Pack {
    var b: [UInt8] = []
    mutating func int(_ v: Int, _ bytes: Int) { for i in 0..<bytes { b.append(UInt8(truncatingIfNeeded: v >> (8 * i))) } }
    mutating func u8(_ v: Int) { int(v, 1) }
    mutating func u16(_ v: Int) { int(v, 2) }
    mutating func i32(_ v: Int) { int(v, 4) }
    mutating func str(_ s: String) { b += s.unicodeScalars.map { UInt8($0.value) } + [0] }
}

nonisolated(unsafe) let stage2 = fixtures["stage2"] as! JSON

func meshHashes(_ m: EORMesh) -> [String: String] {
    var verts = Pack(), polys = Pack(), lines = Pack(), tex = Pack(), anim = Pack(), lvl0 = Pack()
    for v in m.verts { verts.i32(Int(v.x)); verts.i32(Int(v.y)); verts.i32(Int(v.z)) }
    for p in m.polys {
        polys.u8(p.kind); polys.u8(p.color); polys.u8(p.vi.count)
        p.vi.forEach { polys.u16($0) }
        polys.int(p.tex ?? -1, 2)
        p.uv?.forEach { polys.u16($0) }
    }
    for l in m.lines { lines.u8(l[0]); lines.u8(l[1]); lines.u16(l[2]); lines.u16(l[3]) }
    for t in m.textures { tex.str(t.name); tex.u16(t.width); tex.u16(t.height); tex.b += t.pixels }
    for (i, f) in m.frames.sorted(by: { $0.key < $1.key }) { anim.u16(i); anim.u16(f.count); f.forEach { anim.b += $0 } }
    m.lvl0.forEach { lvl0.u16($0) }
    return ["vert_sha": sha(verts.b), "poly_sha": sha(polys.b), "line_sha": sha(lines.b), "tex_sha": sha(tex.b),
            "anim_sha": sha(anim.b), "lvl0_sha": sha(lvl0.b), "attr_sha": sha(m.attr)]
}

func motionHash(_ m: Motion) -> String {
    var p = Pack()
    for f in m.frames {
        f.pos.indices.forEach { p.i32(f.pos[$0]) }
        f.rootAngle.indices.forEach { p.int(f.rootAngle[$0], 2) }
        for l in f.limbs { l.indices.forEach { p.int(l[$0], 2) } }
    }
    return sha(p.b)
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct CharacterTests {
    @Test func meshFixtures() throws {
        let g = try requireGame()
        let want = stage2["meshes"] as! [String: JSON]
        let files = g.list("BODY", ext: "EOR")
        #expect(files.count == want.count, "BODY/*.EOR count")
        for name in files {
            let m = try EORMesh(data: g.read("BODY/\(name)"))
            guard let fx = want[name] else { Issue.record("\(name) missing from fixtures"); continue }
            #expect(m.verts.count == fx["verts"] as! Int && m.polys.count == fx["polys"] as! Int && m.lines.count == fx["lines"] as! Int, "\(name) counts")
            #expect(m.textures.count == fx["textures"] as! Int && m.frames.count == fx["anim"] as! Int, "\(name) texture counts")
            #expect(m.lvl0.count == fx["lvl0"] as! Int && m.attr.count == fx["attr"] as! Int, "\(name) DETA/ATTR sizes")
            for (k, h) in meshHashes(m) { #expect(h == fx[k] as! String, "\(name) \(k)") }
        }
        print("meshFixtures: \(files.count) BODY/*.EOR meshes matched (Python: \(want.count))")
    }

    @Test func skeletonsAndMotions() throws {
        let g = try requireGame()
        var motions = 0
        for (type, any) in stage2["figures"] as! [String: JSON] {
            let fx = any, a = try FigureAssets(type: type, game: g)
            let limbs = fx["limbs"] as! [[Any]]
            #expect(a.skeleton.limbs.count == limbs.count, "\(type) limb count")
            for (l, x) in zip(a.skeleton.limbs, limbs) {
                let tag = "\(type) \(l.name)"
                #expect(l.name == x[0] as! String && l.parent == x[1] as! Int && l.length == x[4] as! Int, "\(tag)")
                #expect([l.rest.x, l.rest.y, l.rest.z] == x[2] as! [Int] && [l.angle.x, l.angle.y, l.angle.z] == x[3] as! [Int], "\(tag) rest/angle")
                #expect([l.offset.x, l.offset.y, l.offset.z] == x[5] as! [Int], "\(tag) offset")
            }
            var links = Pack()
            a.skin.links.forEach { links.u16($0) }
            #expect(a.skin.links.count == fx["links"] as! Int && sha(links.b) == fx["links_sha"] as! String, "\(type) skin")
            let want = fx["motions"] as! [String: JSON]
            #expect(Set(a.motions.map(\.name)) == Set(want.keys), "\(type) motion names")
            for m in a.motions {
                guard let x = want[m.name] else { continue }
                #expect(m.frames.count == x["frames"] as! Int, "\(type) \(m.name) frames")
                #expect(motionHash(m) == x["sha"] as! String, "\(type) \(m.name) angles")
                motions += 1
            }
        }
        print("skeletonsAndMotions: \((stage2["figures"] as! JSON).count) figures, \(motions) motions matched")
    }

    @Test func posedVertices() throws {
        let g = try requireGame()
        var cache: [String: FigureAssets] = [:], worst = 0.0
        for fx in stage2["poses"] as! [JSON] {
            let type = fx["figure"] as! String, name = fx["motion"] as! String, frame = fx["frame"] as! Int
            if cache[type] == nil { cache[type] = try FigureAssets(type: type, game: g) }
            let a = cache[type]!, v = a.pose(a.motion(name)!.frames[frame])
            let want = (fx["verts"] as! String).split(separator: " ").map { Double($0)! }
            #expect(v.count * 3 == want.count, "\(type) \(name) vertex count")
            for (i, p) in v.enumerated() {
                for c in 0..<3 { worst = max(worst, abs(p[c] - want[3 * i + c])) }
            }
        }
        #expect(worst <= 1e-3, "worst posed-vertex deviation \(worst)")
        print("posedVertices: \((stage2["poses"] as! [JSON]).count) cases, worst deviation \(worst)")
    }

    /// Indexed renders of INITGAME scenes: full-frame SHA plus 8-pixel segment fingerprints (lower bound of identical pixels).
    @Test func sceneRenders() throws {
        let g = try requireGame()
        let index = try LevelIndex(game: g)
        var assets: [String: FigureAssets] = [:]
        for fx in stage2["scenes"] as! [JSON] {
            let levelName = fx["level"] as! String, camName = fx["camera"] as! String, tick = fx["tick"] as! Int
            let tag = "\(levelName)/\(camName)@\(tick)"
            let level = try #require(index.levels[levelName])
            #expect(index.cameraLevel[camName] != nil, "\(tag) camera index")
            let camera = try #require(level.cameras[camName])
            let stage = try Stage(level: level, game: g, cache: &assets)
            let figures = stage.figures(for: camera, tick: tick)
            #expect(figures.map(\.name) == fx["figures"] as! [String], "\(tag) drawn figures")
            var fb = Framebuffer()
            try Compositor(room: CAMFile(data: g.read("ROOMS/\(camName).CAM"))).render(camera: camera, figures: figures, into: &fb)
            let rows = fx["segments"] as! [String]
            var same = 0
            for y in 0..<Framebuffer.height {
                let want = Array(rows[y])
                for s in 0..<Framebuffer.width / 8 {
                    let px = Array(fb.pixels[(y * Framebuffer.width + s * 8)..<(y * Framebuffer.width + s * 8 + 8)])
                    if Array(sha(px).prefix(4)) == Array(want[(4 * s)..<(4 * s + 4)]) { same += 8 }
                }
            }
            let pct = 100 * Double(same) / Double(Framebuffer.width * Framebuffer.height)
            let exact = sha(fb.pixels) == fx["sha"] as! String
            print("sceneRenders \(tag): \(figures.count) figures, frame SHA \(exact ? "identical" : "differs"), identical pixels >= \(String(format: "%.3f", pct))%")
            #expect(pct >= 99.5, "\(tag) identical pixels \(pct)%")
        }
    }
}
