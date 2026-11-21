// Origin Flex archive (BioForge .FLX / .CAM), mirrors re/formats/flex.py.
//
// Layout (little-endian):
//   0x00  char[0x50]  copyright text, NUL padded
//   0x50  u32         magic/flags (0xA1A11A00 seen)
//   0x54  u32         entry count
//   0x58  u32         version (6 for most, 1 for MUSIC.FLX)
//   0x60  u32         entry size: 8 = (off,size); 21 = (off,size,name[9],s32 depth)
//   0x80  entries
// Version 1 (MUSIC.FLX) has no entry-size field: entries are always 8 bytes.
import Foundation

public struct FlexEntry: Sendable, Equatable {
    public let index: Int, offset: Int, size: Int
    /// NUL-terminated text after the 8-byte (off,size) header ("" for 8-byte entries).
    public let name: String
    /// Room-file sprite depth (s32 at entry offset 17; 0 -> 99999); nil unless 21-byte entries.
    public let depth: Int?
}

public struct Flex: Sendable {
    public let data: [UInt8]
    public let entries: [FlexEntry]

    public init(data: [UInt8]) throws {
        self.data = data
        let count = try data.u32(0x54), version = try data.u32(0x58)
        let esz = version != 6 ? 8 : try data.u32(0x60)
        var out: [FlexEntry] = []
        for i in 0..<count {
            let p = 0x80 + i * esz
            var depth: Int?
            if esz == 21 { let z = try data.s32(p + 17); depth = z == 0 ? 99999 : z }
            out.append(FlexEntry(index: i, offset: try data.u32(p), size: try data.u32(p + 4),
                                 name: esz > 8 ? data.cString(p + 8, p + esz) : "", depth: depth))
        }
        entries = out
    }

    /// Payload bytes of an entry (clamped to the file like a Python slice).
    public func bytes(_ e: FlexEntry) -> [UInt8] { data.slice(e.offset, e.offset + e.size) }
}
