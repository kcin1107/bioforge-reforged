// EA IFF-85 reader (big-endian chunk sizes) as used by BioForge, mirrors re/formats/iff.py.
//
//   chunk: char[4] id; u32be size; payload[size]; pad byte if size is odd
//   FORM / CAT / LIST: payload = char[4] type + nested chunks (size - 4 bytes)
import Foundation

public struct IFFNode: Sendable {
    public let id: String
    /// Form type for FORM/CAT/LIST containers, else nil.
    public let type: String?
    /// Payload offset into the file (after the type for containers) and payload size.
    public let offset: Int, size: Int
    public let children: [IFFNode]?
}

public enum IFF {
    static let containers: Set<String> = ["FORM", "CAT ", "LIST"]

    public static func parse(_ d: [UInt8], from start: Int = 0, to end: Int? = nil) throws -> [IFFNode] {
        let end = end ?? d.count
        var off = start, out: [IFFNode] = []
        while off + 8 <= end {
            let cid = latin1(d, off)
            let size = try d.u32be(off + 4), p = off + 8
            if containers.contains(cid) {
                out.append(IFFNode(id: cid, type: latin1(d, p), offset: p + 4, size: size - 4,
                                   children: try parse(d, from: p + 4, to: Swift.min(p + size, d.count))))
            } else {
                out.append(IFFNode(id: cid, type: nil, offset: p, size: size, children: nil))
            }
            off = p + size + (size & 1)
        }
        return out
    }

    private static func latin1(_ d: [UInt8], _ o: Int) -> String {
        String(String.UnicodeScalarView(d.slice(o, o + 4).map { Unicode.Scalar($0) }))
    }
}
