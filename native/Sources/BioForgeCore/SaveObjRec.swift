// Decoded FIGR / ITEM / PLAY records of a level IFF, mirrors ObjRec in re/formats/level.py (layout notes: re/NOTES.md "Save state").
//
// ITEM, and the 191-byte base of FIGR/PLAY: 0 char[9] type name, 9 s32[3] position, 21 u8 flags, 22 u16 holder object id,
// 24 char[9] hand name, 33 char[25] instance name, 58 s32[3] velocity, 106 s32[10] the ten script object locals (~0 = hit points),
// 146 u8 + s32[9] orientation matrix (256 = 1.0, row 1 is the facing vector COMPASS reads). FIGR and PLAY continue with the tail
// (marker words 0x75f9, enemy, task slots, current motion, InTrig flags, viewing cameras, avoidance points ...); PLAY adds 8 bytes.
// Flag bits at +21: 0x01 gravity, 0x02 collisions, 0x04 hidden, 0x08 invulnerable, 0x10 bouncy, 0x40 combat mode, 0x80 unknown.
import Foundation

/// Field views over the raw bytes, so `encode()` is byte-exact and unknown bytes are kept (stale junk after strings included).
/// Setters patch the bytes in place.
public struct ObjRec: Sendable {
    public static let tags: Set<String> = ["FIGR", "ITEM", "PLAY"]
    public static let flagGravity = 0x01, flagCollisions = 0x02, flagHidden = 0x04, flagInvulnerable = 0x08, flagBouncy = 0x10,
                      flagCombat = 0x40, flag80 = 0x80
    static let mark = 0x75f9

    public let tag: String
    public private(set) var buf: [UInt8]
    private(set) var t: [String: Int] = [:]

    public init(tag: String, raw: [UInt8]) throws {
        self.tag = tag; buf = raw
        if raw.count >= 191 && tag != "ITEM" { t = Self.parseTail(tag, raw) ?? [:] }
        if raw.count < 191 || (tag != "ITEM" && t.isEmpty) || (tag == "ITEM" && raw.count != 191) {
            throw FormatError("\(tag) record of \(raw.count) bytes does not match the decoded layout")
        }
    }

    /// Offsets of the tail fields, nil if the markers / lengths do not match.
    private static func parseTail(_ tag: String, _ buf: [UInt8]) -> [String: Int]? {
        var p = 191, t: [String: Int] = [:]
        do {
            func u16() throws -> Int { defer { p += 2 }; return try buf.u16(p) }
            var marks = [try u16() == Self.mark]
            t["type2"] = p; p += 9
            t["enemy"] = p; p += 2
            t["motion_task"] = p; p += 2
            t["ai_task"] = p; p += 2
            t["task3"] = p; p += 2
            marks.append(try u16() == Self.mark)
            t["b141"] = p; t["b146"] = p + 1; t["motion"] = p + 5
            p += 30
            t["L"] = p; let L = try u16(); t["intrig"] = p; p += L
            marks.append(try u16() == Self.mark)
            t["name2"] = p; t["b14e"] = p + 25
            p += 29
            t["ncams"] = p; let n = try u16(); t["cams"] = p; p += 9 * n
            t["u229"] = p; p += 2
            t["navoid"] = p; let na = try u16(); t["avoid"] = p; p += 32
            t["s88"] = p; p += 20
            marks.append(try u16() == Self.mark)
            t["t21"] = p; p += 21
            if tag == "PLAY" { t["play"] = p; p += 8 }
            return !marks.contains(false) && na <= 8 && p == buf.count ? t : nil
        } catch { return nil }
    }

    public func encode() -> [UInt8] { buf }

    // ---- base fields
    public var name: String { buf.cString(0, 9) }
    public var inst: String { buf.cString(33, 58) }
    public var pos: [Int] {
        get { (0..<3).map { (try? buf.s32(9 + 4 * $0)) ?? 0 } }
        set { for (i, v) in newValue.prefix(3).enumerated() { buf.put(v, at: 9 + 4 * i, 4) } }
    }
    public var flags: Int {
        get { Int(buf[21]) }
        set { buf[21] = UInt8(truncatingIfNeeded: newValue) }
    }
    public var holder: Int {
        get { (try? buf.u16(22)) ?? 0 }
        set { buf.put(newValue, at: 22, 2) }
    }
    public var hand: String { buf.cString(24, 33) }
    public var velocity: [Int] {
        get { (0..<3).map { (try? buf.s32(58 + 4 * $0)) ?? 0 } }
        set { for (i, v) in newValue.prefix(3).enumerated() { buf.put(v, at: 58 + 4 * i, 4) } }
    }
    public var locals: [Int] {
        get { (0..<10).map { (try? buf.s32(106 + 4 * $0)) ?? 0 } }
        set { for (i, v) in (newValue + [Int](repeating: 0, count: 10)).prefix(10).enumerated() { buf.put(v, at: 106 + 4 * i, 4) } }
    }
    public var matrix: [[Int]] { (0..<3).map { r in (0..<3).map { (try? buf.s32(147 + 12 * r + 4 * $0)) ?? 0 } } }
    public var hp: Int { locals[0] }

    /// COMPASS degrees (atan2(m[1][0], m[1][1])); the interpreter's Figure.heading uses the same convention.
    public var heading: Double {
        get { let m = matrix; return atan2(Double(m[1][0]), Double(m[1][1])) * (180 / .pi) }
        set {
            let r = newValue * (.pi / 180)
            let c = Int((256 * cos(r)).rounded(.toNearestOrEven)), s = Int((256 * sin(r)).rounded(.toNearestOrEven))
            for (i, v) in [c, -s, 0, s, c, 0, 0, 0, 256].enumerated() { buf.put(v, at: 147 + 4 * i, 4) }
        }
    }

    // ---- FIGR / PLAY tail
    private func u16(_ key: String, _ i: Int = 0) -> Int { (try? buf.u16((t[key] ?? 0) + 2 * i)) ?? 0 }
    public var enemy: Int {
        get { u16("enemy") }
        set { buf.put(newValue, at: t["enemy"] ?? 0, 2) }
    }
    public var motionTask: Int {
        get { u16("motion_task") }
        set { buf.put(newValue, at: t["motion_task"] ?? 0, 2) }
    }
    public var aiTask: Int {
        get { u16("ai_task") }
        set { buf.put(newValue, at: t["ai_task"] ?? 0, 2) }
    }
    /// +0x229, the AI-off counter (s16)
    public var aiOff: Int {
        get { Int(Int16(truncatingIfNeeded: u16("u229"))) }
        set { buf.put(newValue, at: t["u229"] ?? 0, 2) }
    }
    /// The setter writes the NUL-terminated name (24 characters at most) and keeps the stale bytes after it.
    public var motion: String {
        get { buf.cString(t["motion"] ?? 0, (t["motion"] ?? 0) + 25) }
        set { let m = Array(latin1Bytes(newValue).prefix(24)) + [0], p = t["motion"] ?? 0; buf.replaceSubrange(p..<(p + m.count), with: m) }
    }
    /// The setter ignores a block of another length than the record's.
    public var inTrig: [UInt8] {
        get { buf.slice(t["intrig"] ?? 0, (t["intrig"] ?? 0) + u16("L")) }
        set { if newValue.count == u16("L") { let p = t["intrig"] ?? 0; buf.replaceSubrange(p..<(p + newValue.count), with: newValue) } }
    }
    /// +0x178, the AI name (SETAI's word; the AI start runs `<it>_AI`): "" if empty or not a name, else in upper case.
    public var aiName: String {
        let n = buf.cString(t["name2"] ?? 0, (t["name2"] ?? 0) + 25)
        return !n.isEmpty && n.utf8.allSatisfy({ $0 == 0x5f || (0x30...0x39).contains($0) || (0x41...0x5a).contains($0) || (0x61...0x7a).contains($0) }) ? n.uppercased() : ""
    }
    /// Writes the name (24 characters at most) and its NUL; the stale bytes after it stay.
    public mutating func setAIName(_ name: String) {
        let a = Array(latin1Bytes(name).prefix(24)) + [0], p = t["name2"] ?? 0
        buf.replaceSubrange(p..<(p + a.count), with: a)
    }
    public var viewCams: [String] {
        let p = t["cams"] ?? 0
        return (0..<u16("ncams")).map { buf.cString(p + 9 * $0, p + 9 * $0 + 9) }
    }
    /// [(waypoint object id, radius)] of the ADDAVOIDANCEPOINT list.
    /// The setter writes the count and the pairs of at most the first 8, the rest of the list zero.
    public var avoid: [(waypoint: Int, radius: Int)] {
        get { (0..<u16("navoid")).map { (u16("avoid", 2 * $0), u16("avoid", 2 * $0 + 1)) } }
        set {
            let av = Array(newValue.prefix(8)), p = t["avoid"] ?? 0
            buf.put(av.count, at: t["navoid"] ?? 0, 2)
            for i in 0..<8 { buf.put(i < av.count ? av[i].waypoint : 0, at: p + 4 * i, 2); buf.put(i < av.count ? av[i].radius : 0, at: p + 4 * i + 2, 2) }
        }
    }
    /// F, model+0x88 (s32): the type's foot depth or a FLOATATHEIGHT override
    public var foot: Int {
        get { (try? buf.s32(t["s88"] ?? 0)) ?? 0 }
        set { buf.put(newValue, at: t["s88"] ?? 0, 4) }
    }
    /// +0x14e (s32): FLOATATHEIGHT ... MAXIMUM's z limit, 0 = none
    public var zCap: Int {
        get { (try? buf.s32(t["b14e"] ?? 0)) ?? 0 }
        set { buf.put(newValue, at: t["b14e"] ?? 0, 4) }
    }
    /// +0x146 (4 bytes, the first is the teeter flag the whoah probe sets); the setter writes [1 or 0, 0, 0, 0]
    public var teeter: Bool {
        get { buf[t["b146"] ?? 0] != 0 }
        set { let p = t["b146"] ?? 0; buf.replaceSubrange(p..<(p + 4), with: [newValue ? 1 : 0, 0, 0, 0]) }
    }
    /// PLAY: the task slot of the CAPTUREKEYBOARD hook process (DAT_1290_6530), 0 = none
    public var hookTask: Int {
        get { u16("play") }
        set { buf.put(newValue, at: t["play"] ?? 0, 2) }
    }
    public var playerClock: Int { (try? buf.u32((t["play"] ?? 0) + 2)) ?? 0 }
    public var playerTarget: Int { (try? buf.u16((t["play"] ?? 0) + 6)) ?? 0 }
}
