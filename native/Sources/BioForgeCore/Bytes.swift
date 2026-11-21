// Little-endian / big-endian field access over a byte array, bounds-checked (throws like Python's IndexError/struct.error).
import Foundation

public struct FormatError: Error, CustomStringConvertible {
    public let description: String
    public init(_ description: String) { self.description = description }
}

extension Array where Element == UInt8 {
    func u8(_ o: Int) throws -> Int { try check(o, 1); return Int(self[o]) }
    func u16(_ o: Int) throws -> Int { try check(o, 2); return Int(self[o]) | Int(self[o + 1]) << 8 }
    func s8(_ o: Int) throws -> Int { Int(Int8(bitPattern: UInt8(try u8(o)))) }
    func s16(_ o: Int) throws -> Int { Int(Int16(truncatingIfNeeded: try u16(o))) }
    func u32(_ o: Int) throws -> Int {
        try check(o, 4)
        return Int(self[o]) | Int(self[o + 1]) << 8 | Int(self[o + 2]) << 16 | Int(self[o + 3]) << 24
    }
    func s32(_ o: Int) throws -> Int { Int(Int32(truncatingIfNeeded: try u32(o))) }
    func u32be(_ o: Int) throws -> Int {
        try check(o, 4)
        return Int(self[o]) << 24 | Int(self[o + 1]) << 16 | Int(self[o + 2]) << 8 | Int(self[o + 3])
    }
    /// Bytes [a, b) clamped to the array (Python slice semantics).
    func slice(_ a: Int, _ b: Int) -> [UInt8] {
        let lo = Swift.min(Swift.max(a, 0), count), hi = Swift.min(Swift.max(b, lo), count)
        return Array(self[lo..<hi])
    }
    /// NUL-terminated Latin-1 string in [a, b).
    func cString(_ a: Int, _ b: Int) -> String {
        String(String.UnicodeScalarView(slice(a, b).prefix { $0 != 0 }.map { Unicode.Scalar($0) }))
    }
    /// Offset of the first occurrence of the 4-character tag (Python bytes.find).
    func find(_ tag: String) throws -> Int {
        let t = Array(tag.utf8)
        guard count >= t.count, let i = (0...(count - t.count)).first(where: { self[$0] == t[0] && Array(self[$0..<$0 + t.count]) == t })
        else { throw FormatError("tag \(tag) not found") }
        return i
    }
    private func check(_ o: Int, _ n: Int) throws {
        if o < 0 || o + n > count { throw FormatError("read of \(n) bytes at \(o) outside \(count)-byte buffer") }
    }
}
