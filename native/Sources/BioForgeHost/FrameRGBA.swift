// The framebuffer as 32-bit pixels for a texture upload (SDL_PIXELFORMAT_RGBA32: bytes R, G, B, A).
import BioForgeCore
import Foundation

public enum FrameRGBA {
    /// 320x200x4 bytes of `fb` through its palette, alpha 255; `out` is resized when its count is wrong.
    public static func convert(_ fb: Framebuffer, into out: inout [UInt8]) {
        let count = Framebuffer.width * Framebuffer.height
        if out.count != count * 4 { out = [UInt8](repeating: 0, count: count * 4) }
        var lut = [UInt32](repeating: 0, count: 256)       // one word per index, holding the bytes R, G, B, A (little-endian)
        fb.palette.withUnsafeBufferPointer { pal in
            for i in 0..<256 {
                lut[i] = UInt32(pal[i * 3]) | UInt32(pal[i * 3 + 1]) << 8 | UInt32(pal[i * 3 + 2]) << 16 | 0xff00_0000
            }
        }
        lut.withUnsafeBufferPointer { lut in
            fb.pixels.withUnsafeBufferPointer { src in
                out.withUnsafeMutableBytes { raw in
                    let dst = raw.baseAddress!
                    for i in 0..<count { dst.storeBytes(of: lut[Int(src[i])].littleEndian, toByteOffset: i * 4, as: UInt32.self) }
                }
            }
        }
    }
}
