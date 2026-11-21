import Testing
@testable import BioForgeCore

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct SubtitleTests {
    @Test func captionFontGeometry() throws {
        let g = try requireGame()
        let font = try CaptionFont(g.read("DATA/1.FNT"))
        let a = try #require(font.glyph("A".unicodeScalars.first!))
        #expect(font.height == 7)
        #expect(font.maxWidth == 11)
        #expect(font.glyphs.count == 226)
        #expect(a.width == 6 && a.height == 11 && a.xOrigin == 0 && a.baseline == 8)
        #expect(a.rows.flatMap { $0 }.contains { $0 != 0 })
        #expect(font.textWidth("AB") == 14)
        #expect(font.textWidth("A😀B") == 15, "a missing glyph still consumes caption spacing")
    }

    @Test func captionLayoutAndPaletteShade() throws {
        let g = try requireGame()
        let font = try CaptionFont(g.read("DATA/1.FNT"))
        var fb = Framebuffer()
        for i in 0..<256 { fb.palette[3 * i] = UInt8(i); fb.palette[3 * i + 1] = UInt8(i); fb.palette[3 * i + 2] = UInt8(i) }
        fb.pixels = [UInt8](repeating: 200, count: fb.pixels.count)
        let event = SubtitleEvent(tick: 0, handle: 1, colour: 77, text: "A~B", end: 10)
        SubtitleRenderer.render(event, font: font, into: &fb)

        #expect(fb.pixels[184 * Framebuffer.width + 5] == 100, "two lines shade from y=175 through y=198")
        #expect(fb.pixels[174 * Framebuffer.width + 5] == 200, "pixels above the shade box stay untouched")
        let aX = ((300 - font.textWidth("A")) >> 1) + 10
        let a = try #require(font.glyph("A".unicodeScalars.first!))
        let glyphPixels = a.rows.enumerated().flatMap { row, values in
            values.enumerated().compactMap { column, value in value == 0 ? nil : (row, column) }
        }
        let glyphPixel = try #require(glyphPixels.first)
        #expect(fb.pixels[(184 - a.baseline + glyphPixel.0) * Framebuffer.width + aX + glyphPixel.1] == 77)
        #expect(fb.pixels.contains(0), "the shadow contributes black pixels")
        #expect(fb.pixels[0] == 200, "pixels outside the subtitle box stay untouched")
    }
}

@Suite struct CaptionFontValidationTests {
    @Test func rejectsTruncatedFont() {
        #expect(throws: FormatError.self) { try CaptionFont([0, 0, 0, 0, 1, 0]) }
    }
}
