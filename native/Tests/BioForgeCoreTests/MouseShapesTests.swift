// MOUSE.SHP parity with re/formats/mouse.py: the digest is MouseShapes.digest() of the Python decoder (test_mouse.py DIGEST),
// and the drawn arrow matches a DOSBox-X dump of BIOFORGE.EXE -e with the mouse at (160, 100).
import Testing
@testable import BioForgeCore

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct MouseShapesTests {
    @Test func shapesMatchThePythonDecoder() throws {
        let m = try MouseShapes(requireGame().read("DATA/MOUSE.SHP"))
        #expect(m.boxWidth == 11 && m.boxHeight == 14)
        #expect(m.shapes.map { [$0.width, $0.height, $0.xOrigin, $0.baseline] } == [
            [11, 12, 1, 1], [3, 7, 1, 3], [10, 14, 4, 6], [9, 8, 8, 0], [10, 8, 9, 0], [10, 8, 9, 0], [10, 8, 9, 0], [10, 8, 9, 0],
        ])
        var bytes: [UInt8] = []
        for s in m.shapes {
            for v in [s.width, s.height, s.xOrigin, s.baseline] { bytes += [UInt8(v & 0xff), UInt8((v >> 8) & 0xff)] }
            for row in s.rows { bytes += row }
        }
        #expect(sha(bytes) == "6884ae9627b61987051b0e2a00176f562f28c71e12abd6d7f47b4b3c997ac5f7")
    }

    @Test func arrowDrawsAtItsHotspotAndClips() throws {
        let m = try MouseShapes(requireGame().read("DATA/MOUSE.SHP"))
        var fb = Framebuffer()
        m.draw(MouseShapes.arrow, x: 160, y: 100, into: &fb)
        let row = { (y: Int, x: Int, n: Int) in Array(fb.pixels[(y * 320 + x)..<(y * 320 + x + n)]) }
        #expect(row(100, 160, 2) == [248, 240])
        #expect(row(101, 160, 4) == [245, 241, 240, 240])
        #expect(row(102, 160, 5) == [0, 244, 241, 241, 240])
        #expect(fb.pixels[99 * 320 + 159] == 0)

        var edge = Framebuffer()
        m.draw(MouseShapes.hourglass, x: 0, y: 0, into: &edge)
        m.draw(MouseShapes.hourglass, x: 319, y: 199, into: &edge)
        #expect(edge.pixels[0] != 0 && edge.pixels[199 * 320 + 319] != 0)
    }
}
