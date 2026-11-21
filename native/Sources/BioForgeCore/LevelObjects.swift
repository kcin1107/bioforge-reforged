// BioForge level object files (GAMEDAT/*.IFF, INITGAME/*.IFF): FORM OBJS, mirrors re/formats/level.py.
//
// Every record starts with a 45-byte base:
//   char name[9]; s32 pos[3]; u32 a; u8 b; u8 junk[7]; s32 pos2[3]
// PHYS (55) AABB corners pos/pos2; WAYP (45) pos == pos2; IMAG (54) trigger volume.
// CAMR (102): name = room image (.CAM) name; pos = eye; u8 flag at 33;
//   3x3 rotation at 34 as s32 rows, 8.8 fixed (rows = right, forward, up);
//   s32 vec[3] at 70; extra = s32 at 82, 86, 90, 94 and s16 at 98, 100.
// FIGR / ITEM / PLAY (placed characters, items, player) are kept raw for now.
import Foundation

public struct LevelObject: Sendable {
    public let tag: String
    public let name: String
    public let pos: [Int]
    public let raw: [UInt8]
    /// Second corner for records of >= 45 bytes (non-CAMR).
    public let pos2: [Int]?
    // CAMR only
    public let flag: Int?
    /// Rotation rows as raw 8.8 fixed values (divide by 256 for the matrix), 9 values.
    public let rotation: [Int]?
    public let vec: [Int]?
    public let extra: [Int]?
}

public enum LevelObjects {
    public static func load(_ d: [UInt8]) throws -> [LevelObject] {
        guard let form = try IFF.parse(d).first, let kids = form.children else { throw FormatError("not an IFF FORM") }
        var objs: [LevelObject] = []
        for k in kids where k.id != "VERS" {
            let r = d.slice(k.offset, k.offset + k.size)
            func ints(_ o: Int, _ n: Int) throws -> [Int] { try (0..<n).map { try r.s32(o + 4 * $0) } }
            let name = r.cString(0, 9), pos = try ints(9, 3)
            if k.id == "CAMR" {
                objs.append(LevelObject(tag: k.id, name: name, pos: pos, raw: r, pos2: nil, flag: try r.u8(33),
                                        rotation: try ints(34, 9), vec: try ints(70, 3),
                                        extra: try ints(82, 4) + [try r.s16(98), try r.s16(100)]))
            } else {
                objs.append(LevelObject(tag: k.id, name: name, pos: pos, raw: r, pos2: r.count >= 45 ? try ints(33, 3) : nil,
                                        flag: nil, rotation: nil, vec: nil, extra: nil))
            }
        }
        return objs
    }
}
