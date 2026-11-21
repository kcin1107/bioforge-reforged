// BioForge room/monitor images (.CAM = Flex archive), mirrors re/formats/cam.py.
//
// Entry 0 = 768-byte 6-bit VGA palette (scaled c*255/63 -> 8 bit).
// Image entry: u16 w, u16 h, u16 nframes, then nframes * (u32 off, u16 size).
// Frame (at off): u16 rle, u16 w, u16 h, s16 hotx, s16 hoty, u16 rowoff[h].
// rowoff[y] is relative to its own position. Row = repeat { u8 skip; if x>=w stop;
// u8 n; if rle: (n&1 ? run of n>>1 copies of next byte : n>>1 literal bytes)
//                           else: n literal bytes }
// until x>=w (no trailing skip byte when the last span ends the row).
import Foundation

public struct CAMFrame: Sendable {
    public let width: Int, height: Int, hotX: Int, hotY: Int
    /// Palette indices, width*height, row-major; `mask[i] == 1` where the frame is opaque.
    public let pixels: [UInt8], mask: [UInt8]
}

public enum CAMImage {
    /// 256 RGB triplets (768 bytes) from a 6-bit VGA palette entry.
    public static func palette(_ b: [UInt8]) -> [UInt8] {
        b.prefix(768).map { UInt8(Swift.min(255, Int($0) * 255 / 63)) }
    }

    /// Frame offsets of an image entry (header at 0).
    public static func frameOffsets(_ b: [UInt8]) throws -> [Int] {
        try (0..<(try b.u16(4))).map { try b.u32(6 + 6 * $0) }
    }

    public static func decodeFrame(_ b: [UInt8], at off: Int) throws -> CAMFrame {
        let rle = try b.u16(off) != 0
        let w = try b.u16(off + 2), h = try b.u16(off + 4)
        let hx = try b.s16(off + 6), hy = try b.s16(off + 8)
        let tab = off + 10
        var px = [UInt8](repeating: 0, count: w * h), mask = px
        func put(_ i: Int, _ v: UInt8) throws {
            if i >= px.count { throw FormatError("span past end of frame") }
            px[i] = v; mask[i] = 1
        }
        for y in 0..<h {
            var p = tab + 2 * y + (try b.u16(tab + 2 * y)), x = 0
            while x < w {
                x += try b.u8(p); p += 1
                if x >= w { break }
                let n = try b.u8(p); p += 1
                let cnt = rle ? n >> 1 : n
                if rle && n & 1 == 1 {
                    let c = UInt8(try b.u8(p)); p += 1
                    for i in 0..<cnt { try put(y * w + x + i, c) }
                } else {
                    for i in 0..<cnt { try put(y * w + x + i, UInt8(try b.u8(p + i))) }
                    p += cnt
                }
                x += cnt
            }
        }
        return CAMFrame(width: w, height: h, hotX: hx, hotY: hy, pixels: px, mask: mask)
    }

    /// Inverse of `decodeFrame` -> frame bytes. `mask` (optional, 1 = opaque) makes the rest skip bytes; a row ends right after
    /// its last span. RLE: runs of >= minRun equal pixels become (count<<1|1, byte), the rest literals (count<<1); counts are
    /// capped at 127 (rle) / 255 (raw) per span. minRun 4 reproduces the native save thumbnail byte for byte.
    public static func encodeFrame(width w: Int, height h: Int, pixels: [UInt8], hotX: Int = 0, hotY: Int = 0, rle: Bool = true,
                                   mask: [UInt8]? = nil, minRun: Int = 4) throws -> [UInt8] {
        var rows: [[UInt8]] = []
        let cap = rle ? 127 : 255
        for y in 0..<h {
            var row: [UInt8] = [], x = 0
            let line = Array(pixels[(y * w)..<((y + 1) * w)])
            let ok: [Bool] = mask.map { Array($0[(y * w)..<((y + 1) * w)]).map { $0 != 0 } } ?? [Bool](repeating: true, count: w)
            while x < w {
                var s = x
                while x < w && !ok[x] { x += 1 }
                while x - s > 255 { row += [255, 0]; s += 255 }            // skip bytes are u8: a zero-length span continues
                if x >= w { row.append(UInt8(x - s)); break }
                row.append(UInt8(x - s))
                var e = x, first = true
                while e < w && ok[e] { e += 1 }                            // opaque span [x, e)
                while x < e {
                    if !first { row.append(0) }                            // every span is preceded by a skip byte
                    first = false
                    var r = x + 1
                    while r < e && line[r] == line[x] { r += 1 }
                    if rle && r - x >= minRun {
                        let n = Swift.min(r - x, cap); row += [UInt8(n << 1 | 1), line[x]]; x += n
                        continue
                    }
                    var q = x
                    while q < e && q - x < cap && !(rle && q + minRun <= e && Set(line[q..<(q + minRun)]).count == 1) { q += 1 }
                    q = Swift.max(q, x + 1)
                    row.append(UInt8(rle ? (q - x) << 1 : q - x)); row += line[x..<q]; x = q
                }
            }
            rows.append(row)
        }
        var out: [UInt8] = [], pos = 0
        for v in [rle ? 1 : 0, w, h, hotX, hotY] { out += [UInt8(truncatingIfNeeded: v), UInt8(truncatingIfNeeded: v >> 8)] }
        for y in 0..<h {
            let off = 2 * h - 2 * y + pos
            if off > 0xFFFF { throw FormatError("row offset \(off) does not fit a u16") }
            out += [UInt8(off & 0xFF), UInt8(off >> 8)]; pos += rows[y].count
        }
        for r in rows { out += r }
        return out
    }

    /// All frames of an image entry.
    public static func frames(_ b: [UInt8]) throws -> [CAMFrame] {
        try frameOffsets(b).map { try decodeFrame(b, at: $0) }
    }
}

/// A parsed .CAM file: palette + named image entries (decoded lazily).
public struct CAMFile: Sendable {
    public let flex: Flex
    public let palette: [UInt8]
    /// Non-empty entries after the palette.
    public let images: [FlexEntry]

    public init(data: [UInt8]) throws {
        flex = try Flex(data: data)
        guard let pal = flex.entries.first else { throw FormatError("CAM without palette entry") }
        palette = CAMImage.palette(flex.bytes(pal))
        images = flex.entries.dropFirst().filter { $0.size > 0 }
    }

    public func frames(of e: FlexEntry) throws -> [CAMFrame] { try CAMImage.frames(flex.bytes(e)) }

    /// The room background: the entry named `name` (case-insensitive), else the largest image entry.
    public func background(named name: String) -> FlexEntry? {
        images.first { $0.name.caseInsensitiveCompare(name) == .orderedSame } ?? images.max { $0.size < $1.size }
    }
}
