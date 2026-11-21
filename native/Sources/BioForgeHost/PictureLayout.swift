// Where the 320x200 picture sits in an output of a given pixel size, and the pointer maths that goes with it. The same mapping as the Mac
// app's FramebufferView (fitScale, gamePoint, windowPoint), but with the origin at the top left, as SDL has it (the Mac view's y points up).
import BioForgeCore
import Foundation

public struct PictureLayout: Equatable, Sendable {
    public let width: Double, height: Double
    /// Pixel height relative to its width: 1.2 with the 4:3 correction (VGA mode 13h is shown on a 4:3 screen), else 1.0.
    public let aspectY: Double

    public init(width: Double, height: Double, correctAspect: Bool) {
        self.width = width; self.height = height; aspectY = correctAspect ? 1.2 : 1.0
    }

    /// Output pixels per game pixel across: the picture fills the output, keeping its shape.
    public var scale: Double { min(width / Double(Framebuffer.width), height / (Double(Framebuffer.height) * aspectY)) }

    /// The picture in output pixels, centred (bars on one axis).
    public var rect: (x: Double, y: Double, w: Double, h: Double) {
        let w = Double(Framebuffer.width) * scale, h = Double(Framebuffer.height) * aspectY * scale
        return ((width - w) / 2, (height - h) / 2, w, h)
    }

    /// The 320x200 pixel under an output point, or nil outside the picture.
    public func gamePoint(x: Double, y: Double) -> (x: Int, y: Int)? {
        let s = scale, r = rect
        guard s > 0 else { return nil }
        let px = x - r.x, py = y - r.y
        guard px >= 0, px < r.w, py >= 0, py < r.h else { return nil }
        return (Int(px / s), max(0, min(Framebuffer.height - 1, Int(py / (s * aspectY)))))
    }

    /// The inverse of `gamePoint`: the output point at the middle of 320x200 pixel (x, y).
    public func windowPoint(game x: Int, _ y: Int) -> (x: Double, y: Double)? {
        let s = scale, r = rect
        guard s > 0 else { return nil }
        return ((Double(x) + 0.5) * s + r.x, (Double(y) + 0.5) * s * aspectY + r.y)
    }
}
