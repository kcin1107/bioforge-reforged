// Software framebuffer: 320x200 palette indices + 256-entry RGB palette (the VGA mode 13h the game targets).
import Foundation

public struct Framebuffer: Sendable {
    public static let width = 320, height = 200
    public var pixels = [UInt8](repeating: 0, count: Framebuffer.width * Framebuffer.height)
    /// 256 RGB triplets, 8 bit per channel.
    public var palette = [UInt8](repeating: 0, count: 768)

    public init() {}

    public mutating func clear(_ index: UInt8 = 0) { for i in pixels.indices { pixels[i] = index } }

    /// FUN_1270_174b: the translucent draw's 32x32 table (monitor.py TRANSLUCENT). Element offset o in its 32-entry ramp over grey ramp
    /// offset u: o + ((31 - o) * (u * 100 / 31) + 50) / 100, capped at 31.
    static let translucent: [[UInt8]] = (0..<32).map { (o: Int) -> [UInt8] in
        (0..<32).map { (u: Int) -> UInt8 in
            let step: Int = (31 - o) * (u * 100 / 31) + 50
            return UInt8(Swift.min(31, o + step / 100))
        }
    }

    /// FUN_1270_185b: element pixel p over screen pixel d (monitor.py blit_translucent). 0xff is transparent in the element's buffer.
    static func translucent(_ p: UInt8, over d: UInt8) -> UInt8 {
        let u = Int(d) - 0x80
        guard u >= 0, u < 32, p != 0, p & 0xe0 != 0xe0 else { return p }
        return (p & 0xe0) + translucent[Int(p & 31)][u]
    }

    /// The same as `blit`, drawn through `translucent(_:over:)`.
    public mutating func blitTranslucent(_ f: CAMFrame, x: Int = 0, y: Int = 0) {
        let ox = x - f.hotX, oy = y - f.hotY
        for fy in 0..<f.height {
            let dy = oy + fy
            if dy < 0 || dy >= Self.height { continue }
            for fx in 0..<f.width {
                let dx = ox + fx, p = f.pixels[fy * f.width + fx]
                if dx < 0 || dx >= Self.width || f.mask[fy * f.width + fx] == 0 || p == 0xff { continue }
                pixels[dy * Self.width + dx] = Self.translucent(p, over: pixels[dy * Self.width + dx])
            }
        }
    }

    /// Blit a decoded frame with its hotspot at (x, y), i.e. top-left at (x - hotX, y - hotY); opaque pixels only, clipped.
    public mutating func blit(_ f: CAMFrame, x: Int = 0, y: Int = 0) {
        let ox = x - f.hotX, oy = y - f.hotY
        for fy in 0..<f.height {
            let dy = oy + fy
            if dy < 0 || dy >= Self.height { continue }
            for fx in 0..<f.width {
                let dx = ox + fx
                if dx < 0 || dx >= Self.width || f.mask[fy * f.width + fx] == 0 { continue }
                pixels[dy * Self.width + dx] = f.pixels[fy * f.width + fx]
            }
        }
    }
}
