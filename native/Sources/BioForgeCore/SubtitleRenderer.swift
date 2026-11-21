// On-screen captions: the original 320x200 layout, with a palette-derived approximation of its darkening table.
import Foundation

public enum SubtitleRenderer {
    private static let baselines = [194, 184, 174]
    private static let boxTop = [0, 185, 175, 165]

    /// Where an event's text goes: the top row of its shaded box and each line's left edge and baseline; nil if it draws nothing.
    private static func layout(_ event: SubtitleEvent, font: CaptionFont) -> (top: Int, lines: [(text: String, x: Int, baseline: Int)])? {
        let lines = event.text.split(separator: "~", maxSplits: 2, omittingEmptySubsequences: false).map(String.init)
        let lineCount = min(lines.count, 3)
        guard lineCount > 0 else { return nil }
        return (boxTop[lineCount], lines.prefix(lineCount).enumerated().map { i, line in
            (line, ((300 - font.textWidth(line)) >> 1) + 10, baselines[lineCount - 1 - i])
        })
    }

    /// `readable` (View > Readable Text): the box darkened to a quarter instead of half and the text in a brighter palette entry of the same hue.
    public static func render(_ event: SubtitleEvent, font: CaptionFont, readable: Bool = false, into framebuffer: inout Framebuffer) {
        guard let layout = layout(event, font: font) else { return }
        let remap = Self.remap(framebuffer.palette, divisor: readable ? 4 : 2)
        for y in layout.top...198 {
            for x in 5...315 {
                let pixel = y * Framebuffer.width + x
                framebuffer.pixels[pixel] = remap[Int(framebuffer.pixels[pixel])]
            }
        }
        let colour = textColour(event, readable: readable, palette: framebuffer.palette)
        for line in layout.lines {
            draw(line.text, atX: line.x + 1, baseline: line.baseline + 1, font: font) { framebuffer.drawGlyph($0, left: $1, top: $2, colour: 0) }
            draw(line.text, atX: line.x, baseline: line.baseline, font: font) { framebuffer.drawGlyph($0, left: $1, top: $2, colour: colour) }
        }
    }

    /// The same caption on a High-Resolution Art picture: the box (coordinates times the scale) darkened with the same table, the shadow at
    /// (+1, +1) of the original's pixels, i.e. (+scale, +scale) here, and the text through HDText.scaledGlyph. `palette`: the picture's.
    static func render(_ event: SubtitleEvent, font: CaptionFont, palette: [UInt8], readable: Bool = false, into hi: inout HiResFrame) {
        guard let layout = layout(event, font: font) else { return }
        let s = hi.scale, remap = Self.remap(palette, divisor: readable ? 4 : 2), W = hi.width
        for y in (s * layout.top)..<(s * 199) {
            for x in (s * 5)..<(s * 316) { hi.pixels[y * W + x] = remap[Int(hi.pixels[y * W + x])] }
        }
        let colour = textColour(event, readable: readable, palette: palette)
        for line in layout.lines {
            draw(line.text, atX: line.x + 1, baseline: line.baseline + 1, font: font) { hi.drawGlyph($0.rows, left: $1, top: $2, colour: 0) }
            draw(line.text, atX: line.x, baseline: line.baseline, font: font) { hi.drawGlyph($0.rows, left: $1, top: $2, colour: colour) }
        }
    }

    private static func textColour(_ event: SubtitleEvent, readable: Bool, palette: [UInt8]) -> UInt8 {
        let colour = UInt8(truncatingIfNeeded: event.colour)
        return readable ? MonitorScreen.brighterIndex(colour, in: palette) : colour
    }

    /// Each palette index to the entry nearest its colour divided by `divisor` (2 in the original): the box's darkening.
    private static func remap(_ palette: [UInt8], divisor: Int) -> [UInt8] {
        (0..<256).map { index -> UInt8 in
            let p = index * 3
            return nearestPaletteIndex(Int(palette[p]) / divisor, Int(palette[p + 1]) / divisor, Int(palette[p + 2]) / divisor, palette: palette)
        }
    }

    private static func nearestPaletteIndex(_ r: Int, _ g: Int, _ b: Int, palette: [UInt8]) -> UInt8 {
        var best = 0, bestDistance = Int.max
        for index in 0..<256 {
            let p = index * 3
            let dr = Int(palette[p]) - r
            let dg = Int(palette[p + 1]) - g
            let db = Int(palette[p + 2]) - b
            let distance = dr * dr + dg * dg + db * db
            if distance < bestDistance { best = index; bestDistance = distance }
        }
        return UInt8(best)
    }

    /// Calls `put(glyph, left, top)` for each glyph of `text`, the pen at `startX` on `baseline` (320x200 coordinates).
    private static func draw(_ text: String, atX startX: Int, baseline: Int, font: CaptionFont, put: (CaptionFont.Glyph, Int, Int) -> Void) {
        var x = startX
        for scalar in text.unicodeScalars {
            if let glyph = font.glyph(scalar) { put(glyph, x - glyph.xOrigin, baseline - glyph.baseline) }
            x += font.advance(scalar)
        }
    }
}

extension Framebuffer {
    /// A glyph's ink painted at `colour`, its top-left at (left, top); clipped.
    mutating func drawGlyph(_ glyph: CaptionFont.Glyph, left: Int, top: Int, colour: UInt8) {
        for (rowIndex, row) in glyph.rows.enumerated() {
            let y = top + rowIndex
            guard y >= 0 && y < Framebuffer.height else { continue }
            for (column, value) in row.enumerated() where value != 0 {
                let px = left + column
                if px >= 0 && px < Framebuffer.width { pixels[y * Framebuffer.width + px] = colour }
            }
        }
    }
}
