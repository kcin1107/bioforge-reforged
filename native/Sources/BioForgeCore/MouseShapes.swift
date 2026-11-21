// Decoder for the mouse cursor shapes in DATA/MOUSE.SHP (re/formats/mouse.py): the FNT layout, where each glyph's x origin
// and baseline are the hotspot and its colours are real palette indices. The original only shows this cursor with
// BIOFORGE.EXE -e (editor mode); normal play keeps it hidden.
public struct MouseShapes: Sendable {
    public static let arrow = 0, marker = 1, hourglass = 2

    /// Header u16 0 / u16 2: the background box the engine saves under the cursor (11 wide, 14 high).
    public let boxWidth: Int
    public let boxHeight: Int
    /// Shapes in file order; xOrigin / baseline are the hotspot.
    public let shapes: [CaptionFont.Glyph]

    public init(_ data: [UInt8]) throws {
        let font = try CaptionFont(data)
        boxWidth = font.height
        boxHeight = font.maxWidth
        shapes = font.glyphs
    }

    /// Draws `shape` with its hotspot at (x, y); index 0 is transparent, pixels outside the framebuffer are clipped.
    public func draw(_ shape: Int, x: Int, y: Int, into fb: inout Framebuffer) {
        guard shapes.indices.contains(shape) else { return }
        let s = shapes[shape]
        for (r, row) in s.rows.enumerated() {
            let yy = y - s.baseline + r
            guard yy >= 0, yy < Framebuffer.height else { continue }
            for (c, v) in row.enumerated() where v != 0 {
                let xx = x - s.xOrigin + c
                if xx >= 0, xx < Framebuffer.width { fb.pixels[yy * Framebuffer.width + xx] = v }
            }
        }
    }
}
