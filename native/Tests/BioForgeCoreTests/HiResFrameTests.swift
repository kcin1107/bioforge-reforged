import Testing
import Foundation
@testable import BioForgeCore

@Suite struct HiResFrameTests {
    static func enlarged(_ fb: Framebuffer, _ k: Int = 2) -> [UInt8] {
        (0..<(Framebuffer.height * k)).flatMap { y in (0..<(Framebuffer.width * k)).map { x in fb.pixels[y / k * Framebuffer.width + x / k] } }
    }

    static func noPack(_ scale: Int = 2) -> HiResPack { HiResPack(root: URL(fileURLWithPath: "/nonexistent-bioforge-pack"), scale: scale) }

    @Test func textureKeyIsFNV1a() {
        #expect(HDArt.key([]) == 0x811c9dc5)
        #expect(HDArt.key(Array("a".utf8)) == 0xe40c292c)
    }

    /// Painting the cels at 1x gives exactly the indexed picture: same pieces, same order, same frames, same places.
    @Test func celsRepaintTheIndexedRoom() throws {
        let g = try requireGame()
        for room in ["CTR1", "TUN1", "CE11"] {
            let c = try Compositor(room: CAMFile(data: g.read("ROOMS/\(room).CAM")))
            var indexed = Framebuffer(), painted = Framebuffer()
            c.render(camera: nil, figures: [], into: &indexed)
            let cels = c.hdCels(room: room, camera: nil, figures: [], spriteFrames: [:], flats: [])
            #expect(!cels.isEmpty)
            for case .sprite(let f, let x, let y, let pack) in cels {
                #expect(pack?.hasPrefix("rooms/\(room)/") == true)
                painted.blit(f, x: x + f.hotX, y: y + f.hotY)
            }
            #expect(painted.pixels == indexed.pixels, "\(room)")
            for k in [2, 4] {
                #expect(HiResFrame(cels: cels, pack: Self.noPack(k)).pixels == Self.enlarged(indexed, k), "without a pack the room is enlarged: \(room) \(k)x")
            }
        }
    }

    #if canImport(Darwin)
    @Test func packFramesReplaceTheirPiece() throws {
        let g = try requireGame()
        let c = try Compositor(room: CAMFile(data: g.read("ROOMS/CE11.CAM")))
        let cels = c.hdCels(room: "CE11", camera: nil, figures: [], spriteFrames: [:], flats: [])
        guard case .sprite(let f, _, _, let path?) = cels[0] else { Issue.record("no room piece"); return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("hires-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent(path + ".frm")
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let w = 2 * f.width, h = 2 * f.height
        let body = [UInt8](repeating: 0x42, count: w * h) + (0..<(w * h)).map { UInt8($0 % w < w / 2 ? 1 : 0) }      // left half opaque
        let packed = try (Data(body) as NSData).compressed(using: .zlib) as Data
        try (Data("BFX2".utf8) + Data([UInt8(w & 0xff), UInt8(w >> 8), UInt8(h & 0xff), UInt8(h >> 8)]) + packed).write(to: file)
        let frame = try #require(HiResPack.decode(try Data(contentsOf: file)))
        #expect(frame.width == w && frame.pixels == Array(body[..<(w * h)]))
        let only = HiResFrame(cels: [cels[0]], pack: HiResPack(root: dir, scale: 2))
        let opaque = (0..<(w * h)).filter { body[w * h + $0] != 0 }
        #expect(!opaque.isEmpty)
        if f.hotX == 0 && f.hotY == 0 && w == only.width {
            #expect(opaque.allSatisfy { only.pixels[$0] == 0x42 })
            #expect(only.pixels[only.width - 1] == 0)
        }
    }
    #endif

    /// RUMBLE moves an enlarged picture exactly as it moves the original.
    @Test func shiftMatchesTheOriginalEnlarged() {
        var fb = Framebuffer()
        for i in fb.pixels.indices { fb.pixels[i] = UInt8(truncatingIfNeeded: i &* 2654435761 >> 7) }
        for k in [2, 4] {
            for (x, y, xp) in [(3, 2, -1), (-2, -3, 1), (0, 5, 4), (-5, 0, 2)] {
                var hi = HiResFrame(pixels: Self.enlarged(fb, k), scale: k)
                hi.shift(x: x, y: y, xp: xp, fill: 9)
                var small = fb
                small.pixels = Presentation.shiftFrame(fb.pixels, width: Framebuffer.width, height: Framebuffer.height, x: x, y: y, xp: xp, fill: 9)
                #expect(hi.pixels == Self.enlarged(small, k), "\(k)x \(x) \(y) \(xp)")
            }
        }
    }

    /// Palette effects and RUMBLE no longer fall back to the 320x200 picture; RUMBLE still advances once per frame.
    @Test func paletteEffectsKeepThe2xPicture() throws {
        let g = try requireGame()
        let r = try GameResources(game: g)
        let a = try GameSession(resources: r, level: "CHAOS", camera: "CE11"), b = try GameSession(resources: r, level: "CHAOS", camera: "CE11")
        var fb = Framebuffer()
        a.world.renderPresentation(into: &fb)
        for s in [a, b] { s.world.presentation.rumbleAmp = 4 }
        var hi = a.world.hiResFrame(indexed: fb, pack: Self.noPack())
        #expect(hi != nil)
        var fa = fb, fbb = fb
        a.world.applyPresentation(to: &fa, hiRes: &hi)
        b.world.applyPresentation(to: &fbb)
        #expect(fa.pixels == fbb.pixels && fa.palette == fbb.palette)
        #expect(a.world.presentation.rumbleX == b.world.presentation.rumbleX && a.world.presentation.rumbleY == b.world.presentation.rumbleY)
    }
}
