import BioForgeCore
import Testing
@testable import BioForgeHost

struct FrameRGBATests {
    private func frame() -> Framebuffer {
        var fb = Framebuffer()
        fb.palette[3] = 10; fb.palette[4] = 20; fb.palette[5] = 30           // index 1
        fb.palette[765] = 250; fb.palette[766] = 251; fb.palette[767] = 252    // index 255
        fb.pixels[0] = 1
        fb.pixels[1] = 255
        fb.pixels[Framebuffer.width * Framebuffer.height - 1] = 255
        return fb
    }

    @Test func writesRGBAThroughThePalette() {
        var out: [UInt8] = []
        FrameRGBA.convert(frame(), into: &out)
        #expect(out.count == 320 * 200 * 4)
        #expect(Array(out[0..<4]) == [10, 20, 30, 255])
        #expect(Array(out[4..<8]) == [250, 251, 252, 255])
        #expect(Array(out[8..<12]) == [0, 0, 0, 255])
        #expect(Array(out[(out.count - 4)...]) == [250, 251, 252, 255])
        #expect(stride(from: 3, to: out.count, by: 4).allSatisfy { out[$0] == 255 })
    }

    @Test func aWrongSizedOutputIsResized() {
        var out = [UInt8](repeating: 9, count: 5)
        FrameRGBA.convert(frame(), into: &out)
        #expect(out.count == 320 * 200 * 4 && Array(out[0..<4]) == [10, 20, 30, 255])
        FrameRGBA.convert(frame(), into: &out)          // a right-sized one is reused
        #expect(out.count == 320 * 200 * 4 && Array(out[0..<4]) == [10, 20, 30, 255])
    }
}
