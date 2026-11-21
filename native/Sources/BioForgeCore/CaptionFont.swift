// Decoder for the indexed bitmap caption fonts in DATA/*.FNT.
import Foundation

public struct CaptionFont: Sendable {
    public struct Glyph: Sendable {
        public let width: Int
        public let height: Int
        public let xOrigin: Int
        public let baseline: Int
        public let rows: [[UInt8]]
    }

    public let height: Int
    public let maxWidth: Int
    public let glyphs: [Glyph]

    public init(_ data: [UInt8]) throws {
        guard data.count >= 6 else { throw FormatError("FNT header is truncated") }
        height = try data.u16(0)
        maxWidth = try data.u16(2)
        let count = try data.u16(4)
        let tableEnd = 6 + count * 6
        guard tableEnd <= data.count else { throw FormatError("FNT glyph table is truncated") }

        var decoded: [Glyph] = []
        decoded.reserveCapacity(count)
        for i in 0..<count {
            let entry = 6 + i * 6
            let offset = try data.u32(entry)
            let size = try data.u16(entry + 4)
            let end = offset + size
            guard offset <= data.count, end >= offset, end <= data.count else {
                throw FormatError("FNT glyph \(i) is outside the file")
            }
            guard size >= 10 else { throw FormatError("FNT glyph \(i) header is truncated") }
            let width = try data.u16(offset + 2)
            let glyphHeight = try data.u16(offset + 4)
            let xOrigin = try data.s16(offset + 6)
            let baseline = try data.u16(offset + 8)
            var cursor = offset + 10 + glyphHeight * 2
            guard cursor <= end else { throw FormatError("FNT glyph \(i) row offsets are truncated") }

            var rows: [[UInt8]] = []
            rows.reserveCapacity(glyphHeight)
            for _ in 0..<glyphHeight {
                var x = 0
                var row = [UInt8](repeating: 0, count: width)
                while x < width {
                    guard cursor < end else { throw FormatError("FNT glyph \(i) row is truncated") }
                    x += Int(data[cursor]); cursor += 1
                    if x >= width { break }
                    guard cursor < end else { throw FormatError("FNT glyph \(i) run count is truncated") }
                    let run = Int(data[cursor]); cursor += 1
                    guard run > 0, x + run <= width, cursor + run <= end else {
                        throw FormatError("FNT glyph \(i) has an invalid run")
                    }
                    row.replaceSubrange(x..<(x + run), with: data[cursor..<(cursor + run)])
                    cursor += run
                    x += run
                }
                rows.append(row)
            }
            guard cursor == end else { throw FormatError("FNT glyph \(i) size does not match its rows") }
            decoded.append(Glyph(width: width, height: glyphHeight, xOrigin: xOrigin, baseline: baseline, rows: rows))
        }
        glyphs = decoded
    }

    public func glyph(_ scalar: Unicode.Scalar) -> Glyph? {
        let index = Int(scalar.value)
        return index >= 0x20 && index < glyphs.count ? glyphs[index] : nil
    }

    /// Caption text reserves one pixel after every character, including an unavailable glyph.
    public func advance(_ scalar: Unicode.Scalar) -> Int { (glyph(scalar)?.width ?? 0) + 1 }

    public func textWidth(_ text: String) -> Int {
        text.unicodeScalars.reduce(0) { $0 + advance($1) }
    }
}
