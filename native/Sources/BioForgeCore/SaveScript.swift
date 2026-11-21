// SCRIPT.DAT (the kernel task table) of a saved game, mirrors the SCRIPT.DAT part of re/formats/savegame.py.
import Foundation

/// Class-name strings of the task table. The slot's name pointer (SCRIPT.DAT entry 7) is an offset into the executable's data
/// segment; the strings are static data, so they are read from the user's BIOFORGE.EXE at DGROUP's file offset (Python reads the
/// derived re/dgroup.bin). Nothing is bundled; an executable other than the shipped one yields nil.
public struct ClassNames: Sendable {
    /// File offset of DGROUP offset 0 in the shipped BIOFORGE.EXE (1123344 bytes).
    static let dgroupBase = 0xFD800
    let exe: [UInt8]

    /// nil unless the image has the "StdIntHandler" string at DGROUP:0x9a98 (slot 0 of every save).
    public init?(exe: [UInt8]) {
        if exe.cString(Self.dgroupBase + 0x9a98, Self.dgroupBase + 0x9a98 + 40) != "StdIntHandler" { return nil }
        self.exe = exe
    }

    public init?(game: GameFolder) {
        guard let exe = try? game.read("BIOFORGE.EXE") else { return nil }
        self.init(exe: exe)
    }

    /// NUL-terminated string at DGROUP offset `ptr` (at most 40 bytes, like Python's `dgroup[o:o+40]`).
    public func name(at ptr: Int) -> String { exe.cString(Self.dgroupBase + ptr, Self.dgroupBase + ptr + 40) }
}

/// Definition names of <name> (.SCP) in compiler order: label index n (1-based) of a process is entry n-1.
/// Same counter as formats/script.py (FUN_1118_07dc).
public func scriptBlocks(_ name: String, in game: GameFolder) -> [String] {
    guard let d = try? game.read("SCRIPT/" + name) else { return [] }
    let re = try! NSRegularExpression(pattern: #""[^"]*"|//[^\n]*|\[[ \t]*(\w*)|\{[ \t]*(\w+)|(?<!\d):(?!\d)[ \t]*(\w*)"#)
    let text = latin1String(d) as NSString
    var out: [String] = []
    for m in re.matches(in: text as String, range: NSRange(location: 0, length: text.length)) {
        let first = text.substring(with: NSRange(location: m.range.location, length: 1))
        if first == "\"" || first == "/" { continue }
        let g = (1...3).map { m.range(at: $0).location == NSNotFound ? "" : text.substring(with: m.range(at: $0)) }
        out.append(g.first { !$0.isEmpty } ?? "#\(out.count)")
    }
    return out
}

/// Serialised form of a script process, class vtable 0x3031 / 0x307f (writer FUN_10c0_4ef4 -> FUN_10b8_0d0b -> FUN_1238_147b;
/// reader FUN_10c0_4a91). The "B" entry of the slot is, in order (u16 unless noted):
///   list1 ids (count = u16 at object+0x18; tasks this one waits for)
///   list2 ids (count = u16 at object+0x22; 0x2000|id = I wait for id, 0x4000|id = id waits for me, 0x408 terminator; count includes it)
///   owner     slot id of the task at object+0x3c (0 = none)
///   objA, objB, curObj  object ids (1-based index into the level IFF objects, negative = persistent table, 0 = none)
///             from object+0xe7b/0xe7f/0xe83 (the constructor FUN_10c0_0bb3 params; curObj starts as objA else objB)
///   waitSlot  slot id of the task at object+0x71 (the caller of a CALL child), 0 = none
///   block     1-based definition index of the running block in the script file (FUN_1128_0f21; CHAOSBLK.SCP #29 = CELLONEBARS)
///   scriptRaw char[13] script file name (the 13 bytes at object+0xe87 -> file record +0xd)
///   label2    u16 (object+0xe8f -> FUN_1128_0f21, 0 here)
///   fileIdx   u16 index in the script file table (0xe8b; 1000 = table size = "not found", always 1000 here)
///   pc, pc0   u32 object+0xe9b / +0xe97: byte offsets into the .SCP text (pc0 = start of the current statement, pc = resume point)
///   locals    object+0x70 (u8, in the raw object) 32-bit values, 4 bytes at +0x19 of each 29-byte local record
///   objs      u16 count + that many object ids (FUN_10c0_56f1 list: cameras that watch the process; ids are CAMR objects)
public struct Proc: Sendable, Equatable {
    public var l1: [Int], l2: [Int], owner: Int, objA: Int, objB: Int, curObj: Int, waitSlot: Int, block: Int
    public var scriptRaw: [UInt8]
    public var label2: Int, fileIdx: Int, pc: Int, pc0: Int, locals: [Int], objs: [Int]

    public static func parse(a: [UInt8], b: [UInt8]) throws -> Proc {
        let c1 = try a.u16(0x18), c2 = try a.u16(0x22)
        var p = 0
        func u16s(_ n: Int) throws -> [Int] { defer { p += 2 * n }; return try (0..<n).map { try b.u16(p + 2 * $0) } }
        func u16() throws -> Int { try u16s(1)[0] }
        func u32() throws -> Int { defer { p += 4 }; return try b.u32(p) }
        let l1 = try u16s(c1), l2 = try u16s(c2)
        let owner = try u16(), objA = try u16(), objB = try u16(), cur = try u16(), wait = try u16(), block = try u16()
        let script = b.slice(p, p + 13); p += 13
        let label2 = try u16(), fileIdx = try u16(), pc = try u32(), pc0 = try u32()
        let n = try a.u8(0x70)
        let loc = try (0..<n).map { _ in try u32() }
        let objs = try u16s(try u16())
        if p != b.count { throw FormatError("process record has \(b.count - p) undecoded bytes") }
        return Proc(l1: l1, l2: l2, owner: owner, objA: objA, objB: objB, curObj: cur, waitSlot: wait, block: block, scriptRaw: script,
                    label2: label2, fileIdx: fileIdx, pc: pc, pc0: pc0, locals: loc, objs: objs)
    }

    public var script: String { scriptRaw.cstr }

    public func encode() -> [UInt8] {
        func u16s(_ v: [Int]) -> [UInt8] { v.flatMap { [UInt8].le($0, 2) } }
        return u16s(l1) + u16s(l2) + u16s([owner, objA, objB, curObj, waitSlot, block]) + scriptRaw + u16s([label2, fileIdx])
            + [UInt8].le(pc, 4) + [UInt8].le(pc0, 4) + locals.flatMap { [UInt8].le($0, 4) } + [UInt8].le(objs.count, 2) + u16s(objs)
    }

    public func blockName(in game: GameFolder) -> String? {
        let names = scriptBlocks(script, in: game)
        return block > 0 && block <= names.count ? names[block - 1] : nil
    }
}

public enum SlotKind: String, Sendable { case handler, task, proc, unknown }

/// vtable offset (data segment) -> (kind, note). Kinds: handler (no B entry), task (B = two lists + owner), proc.
let slotClasses: [Int: (kind: SlotKind, note: String)] = [
    0x9aa6: (.handler, "StdIntHandler (FUN_1240_099f, 72 bytes)"),
    0x9a46: (.handler, "BiosTimer (64 bytes)"),
    0x8373: (.handler, "device handler (56 bytes)"), 0x8347: (.handler, "device handler (56 bytes)"),
    0x1a3a: (.handler, "device handler (56 bytes)"), 0x7381: (.handler, "Music handler (56 bytes)"),
    0x6677: (.task, "Wait task (68 bytes, type 0x102); owner = awaited task"),
    0x2ea0: (.task, "task type 0x10e (85 bytes)"),
    0x46f5: (.task, "task type 0x108 (77 bytes)"),
    0x47a9: (.task, "missile task (86 bytes, type 0x10c, FUN_10e0_0440); B = lists, owner, the owner figure and missile item ids"),
    0x3031: (.proc, "script process (3746 bytes, type 0x10a, FUN_10c0_0840)"),
    0x307f: (.proc, "script process subclass (3754 bytes, type 0x10a)"),
]

/// One kernel task slot: A = raw object memory (FUN_1230_2208 writes `[988c][slot]` bytes at the task pointer, entry 10+2*slot) and
/// B = the virtual serialiser output (entry 11+2*slot). Common task header in A (FUN_1238_164b, 04ac):
///   0 u16 vtable (data segment offset), 2 u16 slot id, 4 u16 group id, 6 u16 type, 8 u8 scheduling class (& 0x1f), 0xe u16 flags
///   (0x300 = task base), 0x10 u16 flags2 (bit0 = serialisable), 0x16/0x20 MLIST sub-objects (list1, list2: u16 vtable, u16
///   count ...), 0x38 u32 serial (MISC.DAT table, tasks of the 0x10b8 class only). Wait tasks keep the remaining ticks at +0x40
///   (total at +0x42); the other task types are not decoded beyond A/B.
public struct Slot: Sendable {
    public var index: Int, a: [UInt8], b: [UInt8], className: String?

    public init(index: Int, a: [UInt8], b: [UInt8], className: String? = nil) {
        self.index = index; self.a = a; self.b = b; self.className = className
    }

    public var vtable: Int { (try? a.u16(0)) ?? 0 }
    public var kind: SlotKind { slotClasses[vtable]?.kind ?? .unknown }
    public var note: String { slotClasses[vtable]?.note ?? "unknown class 0x\(String(vtable, radix: 16))" }
    public var type: Int { (try? a.u16(6)) ?? 0 }
    public var group: Int { (try? a.u16(4)) ?? 0 }
    public var serial: Int { (try? a.u32(0x38)) ?? 0 }

    /// (list1, list2, owner) for kinds task and proc.
    public func task() throws -> (l1: [Int], l2: [Int], owner: Int) {
        let c1 = try a.u16(0x18), c2 = try a.u16(0x22)
        return (try (0..<c1).map { try b.u16(2 * $0) }, try (0..<c2).map { try b.u16(2 * (c1 + $0)) }, try b.u16(2 * (c1 + c2)))
    }

    public func proc() throws -> Proc? { kind == .proc ? try Proc.parse(a: a, b: b) : nil }
}

/// SCRIPT.DAT: Flex archive (8-byte entries), 210 entries = 10 kernel entries + 2 per task slot (100 slots), written by the kernel
/// serializer FUN_1230_2208 (reader FUN_1230_1d7c):
///   0  text   sprintf("Defines=%x Id=%s", 0x77e, "Kernel Ver. 1.00 - T. Zurovec") + NUL     (checked on load)
///   1  153 B  raw memory DS:0x9888..0x9921, the kernel globals: far pointers (stale), slot count 100 (0x9896), live task count
///             (0x9898), the PIT divisor and tick accumulator ([98c2], [98c4]), the active-list MLIST object (0x98c8)
///   2  u16[] ids of the MLIST at DS:0x98c8 (count*2 bytes, includes the 0x408 sentinel): tasks 1, 3, 4, 5
///   3  u16[100] object size per slot ([988c]); 0 = empty slot
///   4  1152 B bitmap indexed by task id (bit set = the id is the group/owner of a task, FUN_1230_2ea2)       [9914]
///   5  9216 B byte per id, bit (type & 7) | 0x10 flags (FUN_1230_2f91)                                          [9918]
///   6  u16[32] number of live tasks per scheduling class [98ae] (class 1: 22, class 31: 3)
///   7  far-pointer[100] [98be]: per slot offset of its class-name string in the data segment + runtime segment 0x040F
///   8, 9 never written (empty)
///   10+2s  A: raw object of slot s     11+2s  B: virtual serialisation (see Slot / Proc)
public struct ScriptDat: Sendable {
    public static let nSlots = 100
    /// entry 1 = DS:0x9888..0x9921 (153 bytes): (offset, name) of the u16 fields with known meaning
    static let kernelFields = [(0x0e, "slot_count"), (0x10, "live_tasks"), (0x12, "scan_cursor"), (0x3a, "pit_divisor"),
                               (0x3c, "tick_accum"), (0x42, "active_list_count")]

    public var flex: SaveFlex
    public var ident: String
    public var kernel: [UInt8]
    public var activeList: [Int]
    public var sizes: [Int]
    public var bitmap: [UInt8], idFlags: [UInt8]
    public var classCounts: [Int]
    public var namePtrs: [(Int, Int)]
    public var slots: [Slot]

    public init(flex: SaveFlex, classNames: ClassNames? = nil) throws {
        self.flex = flex
        let e = flex.entries.map(\.data)
        if e.count < 210 { throw FormatError("unexpected SCRIPT.DAT geometry") }
        ident = e[0].cstr
        kernel = e[1]
        activeList = try (0..<(e[2].count / 2)).map { try e[2].u16(2 * $0) }
        sizes = try (0..<Self.nSlots).map { try e[3].u16(2 * $0) }
        bitmap = e[4]; idFlags = e[5]
        classCounts = try (0..<32).map { try e[6].u16(2 * $0) }
        namePtrs = try (0..<Self.nSlots).map { (try e[7].u16(4 * $0), try e[7].u16(4 * $0 + 2)) }
        slots = []
        for s in 0..<Self.nSlots {
            let a = e[10 + 2 * s], b = e[11 + 2 * s]
            if a.count != sizes[s] { throw FormatError("slot \(s): size table \(sizes[s]) != object \(a.count)") }
            if !a.isEmpty { slots.append(Slot(index: s, a: a, b: b, className: classNames?.name(at: namePtrs[s].0))) }
        }
    }

    public static func parse(_ d: [UInt8], classNames: ClassNames? = nil) throws -> ScriptDat {
        let f = try SaveFlex.parse(d)
        if f.esz != 8 || f.entries.count != 210 { throw FormatError("unexpected SCRIPT.DAT geometry") }
        return try ScriptDat(flex: f, classNames: classNames)
    }

    public func kernelFields() -> [String: Int] {
        Dictionary(uniqueKeysWithValues: Self.kernelFields.map { o, n in (n, (try? kernel.u16(o)) ?? 0) })
    }

    /// (Defines value, Id text) of the ident string.
    public var defines: (Int, String)? {
        guard ident.hasPrefix("Defines="), let r = ident.range(of: " Id=") else { return nil }
        guard let v = Int(ident[ident.index(ident.startIndex, offsetBy: 8)..<r.lowerBound], radix: 16) else { return nil }
        return (v, String(ident[r.upperBound...]))
    }

    public func slot(_ i: Int) -> Slot? { slots.first { $0.index == i } }

    public func encode() throws -> [UInt8] {
        var ents = [SaveFlexEntry](repeating: SaveFlexEntry(), count: 210)
        ents[0].data = latin1Bytes(ident) + [0]
        ents[1].data = kernel
        ents[2].data = activeList.flatMap { [UInt8].le($0, 2) }
        let by = Dictionary(slots.map { ($0.index, $0) }, uniquingKeysWith: { $1 })
        ents[3].data = (0..<Self.nSlots).flatMap { [UInt8].le(by[$0]?.a.count ?? 0, 2) }
        ents[4].data = bitmap; ents[5].data = idFlags
        ents[6].data = classCounts.flatMap { [UInt8].le($0, 2) }
        ents[7].data = namePtrs.flatMap { [UInt8].le($0.0, 2) + [UInt8].le($0.1, 2) }
        for (i, s) in by { ents[10 + 2 * i].data = s.a; ents[11 + 2 * i].data = s.b }
        return try SaveFlex(hdr: flex.hdr, entries: ents, esz: 8).encode()
    }
}
