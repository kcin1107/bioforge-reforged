// BioForge saved-game state: GAMEDAT/ (the native play directory) and the .IM1 save container, mirrors re/formats/savegame.py.
// Byte-exact: every piece parses and re-encodes to the identical bytes (unknown bytes and stale padding are kept).
//
// Files (all written by FUN_1148_0076, the save action; read back by FUN_1148_0490 / FUN_1148_18d3):
//   MISC.DAT     449 bytes, raw field dump                              -> Misc
//   SCRIPT.DAT   Flex archive of the kernel task table (FUN_1148_1523)  -> ScriptDat (SaveScript.swift)
//   LISTS.FLX    Flex archive of the log lists (FUN_1278_13ec)          -> Lists
//   VARS.DEF / SOUNDS.DEF  text (FUN_1118_4c7f)                         -> DefFile
//   <LEVEL>.IFF  FORM OBJS of the level objects (FUN_1148_1404)         -> LevelIff
import Foundation

extension Array where Element == UInt8 {
    /// Little-endian bytes of `v` (low `n` bytes).
    static func le(_ v: Int, _ n: Int) -> [UInt8] { (0..<n).map { UInt8(truncatingIfNeeded: v >> (8 * $0)) } }
    mutating func put(_ v: Int, at o: Int, _ n: Int) { replaceSubrange(o..<(o + n), with: Self.le(v, n)) }
    /// NUL-terminated Latin-1 string at the start of the array (Python `cstr`).
    var cstr: String { cString(0, count) }
    /// Python `bytes.ljust(n, b'\0')[:n]`.
    func padded(_ n: Int) -> [UInt8] { count >= n ? Array(self[0..<n]) : self + [UInt8](repeating: 0, count: n - count) }
}

// ---------------------------------------------------------------------------------------------------------- Flex
public struct SaveFlexEntry: Sendable, Equatable {
    public var data: [UInt8] = []
    /// Entry record bytes after (offset, size): names etc.
    public var tail: [UInt8] = []
    public init(data: [UInt8] = [], tail: [UInt8] = []) { self.data = data; self.tail = tail }
}

/// Origin Flex archive as the engine writes it (FUN_1200_0018 create, FUN_11f8_1355 header, FUN_11f8_1479 checksum).
///
/// Header (0x80 bytes): char comment[0x50] NUL padded; 0x50 magic 00 1A A1 A1; 0x54 u32 entry count; 0x58 u16 version 6; 0x5A u16 0;
/// 0x60 u32 entry size; 0x64 u16 checksum; 0x66 u16 stale (uninitialised memory in the native files, kept verbatim). checksum = sum
/// of the u16 at offsets 0, 4, 8 .. 0x7C without the checksum itself, mod 2**16. Entry i is at 0x80 + i*size: u32 offset, u32 size,
/// then `size - 8` bytes (`tail`). Data follows the table, entries in index order, no padding; an empty entry is (0, 0).
public struct SaveFlex: Sendable {
    public static let magic: [UInt8] = [0x00, 0x1a, 0xa1, 0xa1]
    public var hdr: [UInt8], entries: [SaveFlexEntry], esz: Int
    /// Entry indices in data order; .IM1 stores entry 0 (the thumbnail) after the files. nil/empty = non-empty entries in order.
    public var order: [Int]?

    public init(hdr: [UInt8], entries: [SaveFlexEntry], esz: Int, order: [Int]? = nil) {
        self.hdr = hdr; self.entries = entries; self.esz = esz; self.order = order
    }

    public static func checksum(_ hdr: [UInt8]) throws -> Int {
        var s = 0
        for o in stride(from: 0, to: 0x80, by: 4) { s += try hdr.u16(o) }
        return (s - (try hdr.u16(0x64))) & 0xFFFF
    }

    public static func parse(_ d: [UInt8]) throws -> SaveFlex {
        if d.slice(0x50, 0x54) != magic { throw FormatError("not a Flex archive (magic)") }
        let count = try d.u32(0x54), esz = try d.u32(0x60)
        if try d.u16(0x64) != checksum(d.slice(0, 0x80)) { throw FormatError("Flex header checksum mismatch") }
        var entries: [SaveFlexEntry] = [], spans: [(off: Int, size: Int, i: Int)] = []
        for i in 0..<count {
            let p = 0x80 + i * esz
            let off = try d.u32(p), size = try d.u32(p + 4)
            entries.append(SaveFlexEntry(data: size > 0 ? d.slice(off, off + size) : [], tail: d.slice(p + 8, p + esz)))
            if size > 0 { spans.append((off, size, i)) }
        }
        spans.sort { ($0.off, $0.size, $0.i) < ($1.off, $1.size, $1.i) }
        var pos = 0x80 + count * esz
        for s in spans {
            if s.off != pos { throw FormatError("entry \(s.i): data not contiguous (\(s.off) != \(pos))") }
            pos += s.size
        }
        if pos != d.count { throw FormatError("trailing bytes after the last Flex entry") }
        let order = spans.map(\.i)
        return SaveFlex(hdr: d.slice(0, 0x80), entries: entries, esz: esz, order: order != order.sorted() ? order : nil)
    }

    public static func new(comment: [UInt8], esz: Int, entries: [SaveFlexEntry]) -> SaveFlex {
        var hdr = [UInt8](repeating: 0, count: 0x80)
        hdr.replaceSubrange(0..<comment.count, with: comment)
        hdr.replaceSubrange(0x50..<0x54, with: magic)
        hdr.put(6, at: 0x58, 2)
        return SaveFlex(hdr: hdr, entries: entries, esz: esz)
    }

    public func encode() throws -> [UInt8] {
        var hdr = self.hdr
        let n = entries.count
        let ord = (order?.isEmpty ?? true) ? entries.indices.filter { !entries[$0].data.isEmpty } : order!
        var offs: [Int: Int] = [:], data: [UInt8] = []
        let base = 0x80 + n * esz
        for i in ord { offs[i] = base + data.count; data += entries[i].data }
        var table: [UInt8] = []
        for (i, e) in entries.enumerated() {
            table += [UInt8].le(offs[i] ?? 0, 4) + [UInt8].le(e.data.count, 4) + e.tail.padded(esz - 8)
        }
        hdr.put(n, at: 0x54, 4)
        hdr.put(esz, at: 0x60, 4)
        hdr.put(try Self.checksum(hdr), at: 0x64, 2)
        return hdr + table + data
    }
}

// ---------------------------------------------------------------------------------------------------------- MISC.DAT
/// MISC.DAT (FUN_1148_0076 writes with FUN_11e8_0605(stream, ptr, len); FUN_1148_0490 reads). The field list and sizes come from
/// the push sequence of the 0605 calls (sizes 0xd, 0xd, 9, 1, 1, 2, 2, 4, 0x190, 2, 2):
///   0   char[13] save file name  (GAME1.IM1)      uninitialised bytes after the NUL are kept (`raw`)
///   13  char[13] level file      ([63ce] -> CHAOS.IFF)
///   26  char[9]  current camera  ([63e1], CE33)
///   35  u8  [50bd]   36 u8 [63da] = automatic camera flag (1)
///   37  u16 0   39 u16 0     (both written as constant 0)
///   41  u32 [2ed0]  next task serial number (FUN_10b8_0aa7 `serial = [2ed0]++`)
///   45  u32[100] [2ed4]  serial of the task in each kernel slot (task+0x38, verified against SCRIPT.DAT); stale entries stay
///   445 u16, 447 u16   ids of two global objects (DAT_1290_716c/19fc, each +2); ASSUMPTION: 4 and 5 are object ids
public struct Misc: Sendable {
    public static let size = 449
    static let strings = [(0, 13), (13, 13), (26, 9)]

    public var raw: [UInt8]
    public var saveName: String, level: String, camera: String
    public var flag50bd: Int, autoCamera: Int, zero1: Int, zero2: Int
    public var nextSerial: Int
    public var serials: [Int]
    public var objA: Int, objB: Int

    public init(_ raw: [UInt8]) throws {
        if raw.count != Self.size { throw FormatError("MISC.DAT must be 449 bytes") }
        self.raw = raw
        saveName = raw.slice(0, 13).cstr; level = raw.slice(13, 26).cstr; camera = raw.slice(26, 35).cstr
        flag50bd = try raw.u8(35); autoCamera = try raw.u8(36); zero1 = try raw.u16(37); zero2 = try raw.u16(39)
        nextSerial = try raw.u32(41)
        serials = try (0..<100).map { try raw.u32(45 + 4 * $0) }
        objA = try raw.u16(445); objB = try raw.u16(447)
    }

    public static func new(saveName: String = "", level: String = "CHAOS.IFF", camera: String = "") -> Misc {
        var m = try! Misc([UInt8](repeating: 0, count: size))
        m.saveName = saveName; m.level = level; m.camera = camera
        return m
    }

    public func encode() -> [UInt8] {
        var b = raw
        for ((o, n), v) in zip(Self.strings, [saveName, level, camera]) where raw.slice(o, o + n).cstr != v {   // unchanged strings keep their stale bytes
            b.replaceSubrange(o..<(o + n), with: Array(latin1Bytes(v).prefix(n - 1)).padded(n))
        }
        b.put(flag50bd, at: 35, 1); b.put(autoCamera, at: 36, 1); b.put(zero1, at: 37, 2); b.put(zero2, at: 39, 2)
        b.put(nextSerial, at: 41, 4)
        for (i, s) in serials.prefix(100).enumerated() { b.put(s, at: 45 + 4 * i, 4) }
        b.put(objA, at: 445, 2); b.put(objB, at: 447, 2)
        return b
    }
}

// ---------------------------------------------------------------------------------------------------------- text files
/// Saved VARS.DEF / SOUNDS.DEF (FUN_1118_4c7f): head text (string 0xf5 / 0xf6 of the resource table, which contains the *literal*
/// characters backslash-r-backslash-n), then "{ Vars\r\n" / "{ Sounds\r\n", one "\t%s = %d\r\n" per entry in table order, "}\r\n".
public struct DefFile: Sendable {
    public var head: [UInt8], kind: String
    public var items: [(name: String, value: Int)]

    public init(head: [UInt8], kind: String, items: [(name: String, value: Int)]) { self.head = head; self.kind = kind; self.items = items }

    public static func parse(_ d: [UInt8]) throws -> DefFile {
        let ws: Set<UInt8> = [0x20, 9, 10, 11, 12, 13]
        func word(_ c: UInt8) -> Bool { c == 0x5f || (0x30...0x39).contains(c) || (0x41...0x5a).contains(c) || (0x61...0x7a).contains(c) }
        // regex ^(head.*?)\{ (kind\w+)\r\n(\t\S+ = -?\d+\r\n)*\}\r\n$ : earliest "{ " whose rest matches
        func rest(_ start: Int) -> (kind: String, items: [(name: String, value: Int)])? {
            var p = start
            while p < d.count && word(d[p]) { p += 1 }
            if p == start || d.slice(p, p + 2) != [13, 10] { return nil }
            let kind = latin1String(d[start..<p]); p += 2
            var items: [(name: String, value: Int)] = []
            while p < d.count && d[p] == 9 {
                var q = p + 1
                while q < d.count && !ws.contains(d[q]) { q += 1 }
                if q == p + 1 || d.slice(q, q + 3) != Array(" = ".utf8) { return nil }
                let name = latin1String(d[(p + 1)..<q]); q += 3
                let v = q
                if q < d.count && d[q] == 0x2d { q += 1 }
                let digits = q
                while q < d.count && (0x30...0x39).contains(d[q]) { q += 1 }
                if q == digits || d.slice(q, q + 2) != [13, 10] { return nil }
                guard let value = Int(latin1String(d[v..<q])) else { return nil }
                items.append((name, value)); p = q + 2
            }
            guard d.slice(p, p + 3) == [0x7d, 13, 10], p + 3 == d.count else { return nil }
            return (kind, items)
        }
        var i = 0
        while i + 1 < d.count {
            if d[i] == 0x7b && d[i + 1] == 0x20, let r = rest(i + 2) { return DefFile(head: Array(d[0..<i]), kind: r.kind, items: r.items) }
            i += 1
        }
        throw FormatError("not a saved .DEF file")
    }

    public func encode() -> [UInt8] {
        head + Array("{ \(kind)\r\n".utf8) + items.flatMap { latin1Bytes("\t\($0.name) = \($0.value)\r\n") } + Array("}\r\n".utf8)
    }

    public func values() -> [String: Int] { Dictionary(items.map { ($0.name, $0.value) }, uniquingKeysWith: { $1 }) }
}

/// Initial variable values from the shipped SCRIPT/VARS.DEF (names upper-cased, in table order; `_x` without '=' is 0).
public func defaultVars(_ game: GameFolder) throws -> [(name: String, value: Int)] {
    let d = try game.read("SCRIPT/VARS.DEF")
    let ws: Set<UInt8> = [0x20, 9, 10, 11, 12, 13]
    var out: [(name: String, value: Int)] = [], line: [UInt8] = []
    func word(_ c: UInt8) -> Bool { c == 0x5f || (0x30...0x39).contains(c) || (0x41...0x5a).contains(c) || (0x61...0x7a).contains(c) }
    func take(_ l: [UInt8]) {
        var i = 0
        while i < l.count && ws.contains(l[i]) { i += 1 }
        guard i < l.count, l[i] == 0x5f else { return }
        let s = i
        while i < l.count && word(l[i]) { i += 1 }
        let name = latin1String(l[s..<i]).uppercased()
        while i < l.count && ws.contains(l[i]) { i += 1 }
        var value = 0
        if i < l.count && l[i] == 0x3d {
            i += 1
            while i < l.count && ws.contains(l[i]) { i += 1 }
            let v = i
            if i < l.count && l[i] == 0x2d { i += 1 }
            let digits = i
            while i < l.count && (0x30...0x39).contains(l[i]) { i += 1 }
            if i > digits { value = Int(latin1String(l[v..<i])) ?? 0 }
        }
        out.append((name, value))
    }
    var i = 0
    while i < d.count {                       // str.splitlines
        let c = d[i]
        if [10, 11, 12, 13, 0x1c, 0x1d, 0x1e, 0x85].contains(c) {
            take(line); line = []
            if c == 13 && i + 1 < d.count && d[i + 1] == 10 { i += 1 }
        } else { line.append(c) }
        i += 1
    }
    if !line.isEmpty { take(line) }
    return out
}

public struct LogItem: Sendable, Equatable {
    public var key: String, stamp: Int
    public init(key: String, stamp: Int) { self.key = key; self.stamp = stamp }
}
public struct LogList: Sendable, Equatable {
    public var name: String, items: [LogItem]
    public init(name: String, items: [LogItem]) { self.name = name; self.items = items }
}

/// LISTS.FLX (FUN_1278_13ec): a Flex archive with 21-byte entries (offset, size, char name[13]); every entry is the text of one
/// monitor log list as "KEY,VALUE " items (VALUE = engine clock stamp of the award, the `%time%` source).
public struct Lists: Sendable {
    public var flex: SaveFlex
    public init(flex: SaveFlex) { self.flex = flex }

    public static func parse(_ d: [UInt8]) throws -> Lists { Lists(flex: try SaveFlex.parse(d)) }

    /// Lists in file order.
    public func lists() throws -> [LogList] {
        try flex.entries.map { e in
            let items = try latin1String(e.data).split(whereSeparator: { " \t\n\r\u{0b}\u{0c}".contains($0) }).map { it -> LogItem in
                guard let c = it.lastIndex(of: ","), let v = Int(it[it.index(after: c)...]) else { throw FormatError("bad list item \(it)") }
                return LogItem(key: String(it[..<c]), stamp: v)
            }
            return LogList(name: e.tail.slice(0, 13).cstr, items: items)
        }
    }

    public static func fromLists(_ lists: [LogList], template: Lists? = nil) -> Lists {
        let ents = lists.map { l in
            SaveFlexEntry(data: latin1Bytes(l.items.map { "\($0.key),\($0.stamp) " }.joined()), tail: latin1Bytes(l.name).padded(13))
        }
        if let t = template { return Lists(flex: SaveFlex(hdr: t.flex.hdr, entries: ents, esz: 21)) }
        return Lists(flex: .new(comment: Array("(C) 1994 Origin Systems Inc.".utf8), esz: 21, entries: ents))
    }

    public func encode() throws -> [UInt8] { try flex.encode() }
}

// ---------------------------------------------------------------------------------------------------------- level IFF
/// <LEVEL>.IFF as the save writes it (FUN_1148_1404 -> 1232): FORM OBJS { VERS, then one chunk per level object }. Chunk pad bytes
/// and trailing bytes are kept. The writer's FORM size counts the pad byte of the last chunk even though the file is one byte short
/// when that chunk has odd size (BEACH, CONTROL, DIGSITE, TANKS in the sample): `shortPad`. The decoded FIGR/ITEM/PLAY view is
/// `ObjRec` (SaveObjRec.swift).
public struct LevelIff: Sendable {
    public struct Chunk: Sendable, Equatable {
        public var id: String, data: [UInt8], pad: [UInt8]
        public init(id: String, data: [UInt8], pad: [UInt8]) { self.id = id; self.data = data; self.pad = pad }
    }
    /// One level object (every chunk but VERS); object ids are 1-based indexes into the list.
    public struct Object: Sendable {
        public let tag: String, name: String, raw: [UInt8]
    }
    public var formType: [UInt8], chunks: [Chunk], trailer: [UInt8], shortPad: Bool

    public init(formType: [UInt8], chunks: [Chunk], trailer: [UInt8] = [], shortPad: Bool = false) {
        self.formType = formType; self.chunks = chunks; self.trailer = trailer; self.shortPad = shortPad
    }

    public static func parse(_ d: [UInt8]) throws -> LevelIff {
        if d.slice(0, 4) != Array("FORM".utf8) { throw FormatError("not an IFF FORM") }
        let size = try d.u32be(4)
        var chunks: [Chunk] = [], p = 12, end = 8 + size
        let short = end == d.count + 1
        if short { end -= 1 }
        while p + 8 <= end {
            let csize = try d.u32be(p + 4)
            chunks.append(Chunk(id: latin1String(d.slice(p, p + 4)), data: d.slice(p + 8, p + 8 + csize),
                                pad: d.slice(p + 8 + csize, p + 8 + csize + (csize & 1))))
            p += 8 + csize + (csize & 1)
        }
        if p != end + (short ? 1 : 0) { throw FormatError("malformed IFF chunk sizes") }
        return LevelIff(formType: d.slice(8, 12), chunks: chunks, trailer: d.slice(end, d.count), shortPad: short)
    }

    public func encode() -> [UInt8] {
        let body = formType + chunks.flatMap { latin1Bytes($0.id) + [UInt8].be32($0.data.count) + $0.data + $0.pad }
        return Array("FORM".utf8) + [UInt8].be32(body.count + (shortPad ? 1 : 0)) + body + trailer
    }

    /// Objects without VERS, in file order = object ids 1.. (verified: process object ids).
    public func objects() -> [Object] {
        chunks.filter { $0.id != "VERS" }.map { Object(tag: $0.id, name: $0.data.cString(0, 9), raw: $0.data) }
    }

    /// objects() plus the decoded FIGR / ITEM / PLAY view.
    public func records() throws -> [(object: Object, rec: ObjRec?)] {
        try objects().map { o in (o, ObjRec.tags.contains(o.tag) ? try ObjRec(tag: o.tag, raw: o.raw) : nil) }
    }
}

extension Array where Element == UInt8 {
    static func be32(_ v: Int) -> [UInt8] { [24, 16, 8, 0].map { UInt8(truncatingIfNeeded: v >> $0) } }
}

// ---------------------------------------------------------------------------------------------------------- whole directory
/// All files of a native GAMEDAT directory, decoded.
public struct SaveState: Sendable {
    public var misc: Misc, script: ScriptDat, lists: Lists, vars: DefFile, sounds: DefFile
    /// Level IFFs by name without extension (BEACH, CHAOS ...).
    public var levels: [String: LevelIff]

    public init(misc: Misc, script: ScriptDat, lists: Lists, vars: DefFile, sounds: DefFile, levels: [String: LevelIff]) {
        self.misc = misc; self.script = script; self.lists = lists; self.vars = vars; self.sounds = sounds; self.levels = levels
    }

    /// Load a play directory (file names matched case-insensitively). `classNames` fills `Slot.className`.
    public static func load(directory: URL, classNames: ClassNames? = nil) throws -> SaveState {
        let names = try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted()
        func rd(_ n: String) throws -> [UInt8] {
            guard let hit = names.first(where: { $0.caseInsensitiveCompare(n) == .orderedSame }) else { throw FormatError("\(n) not found in \(directory.path)") }
            return [UInt8](try Data(contentsOf: directory.appendingPathComponent(hit)))
        }
        var levels: [String: LevelIff] = [:]
        for n in names where n.uppercased().hasSuffix(".IFF") { levels[String(n.dropLast(4))] = try LevelIff.parse(rd(n)) }
        return SaveState(misc: try Misc(rd("MISC.DAT")), script: try ScriptDat.parse(rd("SCRIPT.DAT"), classNames: classNames),
                         lists: try Lists.parse(rd("LISTS.FLX")), vars: try DefFile.parse(rd("VARS.DEF")),
                         sounds: try DefFile.parse(rd("SOUNDS.DEF")), levels: levels)
    }

    /// {file name: encoded bytes}
    public func files() throws -> [String: [UInt8]] {
        var out = ["MISC.DAT": misc.encode(), "SCRIPT.DAT": try script.encode(), "LISTS.FLX": try lists.encode(),
                   "VARS.DEF": vars.encode(), "SOUNDS.DEF": sounds.encode()]
        for (n, lv) in levels { out[n + ".IFF"] = lv.encode() }
        return out
    }

    public func write(to directory: URL) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        for (n, b) in try files() { try Data(b).write(to: directory.appendingPathComponent(n)) }
    }

    /// Objects of the current level (ids are 1-based indexes into this list).
    public func levelObjects() -> [LevelIff.Object] {
        levels[misc.level.uppercased().replacingOccurrences(of: ".IFF", with: "")]?.objects() ?? []
    }

    public func describeObj(_ oid: Int) -> String {
        let objs = levelObjects()
        if oid > 0 && oid <= objs.count { return "\(objs[oid - 1].tag) \(objs[oid - 1].name)" }
        return oid != 0 ? String(oid) : "-"
    }
}

// ---------------------------------------------------------------------------------------------------------- .IM1
public struct Im1Entry: Sendable {
    public let name: String, flag: Int, originalSize: Int, data: [UInt8]
}

/// The save container `gameN.im1`: a Flex archive of the play directory (FUN_1140_134f called by FUN_1148_0076 with the file name,
/// the directory, the optional thumbnail and its size; class "DirPack" FUN_11f8_0859, packing FUN_11f8_09ee, extraction FUN_11f8_0f03).
///
/// Layout: header 0x80 bytes as Flex. Comment = "BioForge ver f1.01 savegame (C) 1994, 1995 Origin Systems Inc." when a thumbnail is
/// stored (copied to 80 bytes, '_' -> ' '); otherwise the default "(C) 1994 Origin Systems Inc.". Count = number of files + 1. Entry
/// size = longest file name + 14. Entry 0 is reserved for the thumbnail blob ((offset, size) only, empty name). Entries 1.. in
/// alphabetical order, each: u32 offset, u32 stored size, u32 original size, u8 flag (1 = compressed; the save passes 0), char
/// name[maxlen + 1] NUL padded. The table is followed by the file bodies back to back, then the thumbnail. Extraction skips entries
/// with an empty name (the thumbnail) and refuses flag 1 (the 11c8:0837 decompressor is not implemented).
public enum Im1 {
    public static let comment = Array("BioForge ver f1.01 savegame (C) 1994, 1995 Origin Systems Inc.".utf8)

    public static func pack(files: [String: [UInt8]], thumbnail: [UInt8]? = nil) throws -> [UInt8] {
        let names = files.keys.sorted { $0.utf8.lexicographicallyPrecedes($1.utf8) }
        let esz = (names.map(\.utf8.count).max() ?? 0) + 14
        var ents = [SaveFlexEntry()], buf = [UInt8](repeating: 0, count: esz - 13)
        for n in names {        // one reused name buffer: bytes after the NUL keep earlier, longer names (native files do)
            let body = files[n]!, b = latin1Bytes(n) + [0]
            buf.replaceSubrange(0..<b.count, with: b)
            ents.append(SaveFlexEntry(data: body, tail: [UInt8].le(body.count, 4) + [0] + buf))
        }
        let thumb = !(thumbnail?.isEmpty ?? true)
        if thumb { ents[0] = SaveFlexEntry(data: thumbnail!) }
        let hdrComment = thumb ? comment.map { $0 == 0x5f ? 0x20 : $0 } : Array("(C) 1994 Origin Systems Inc.".utf8)
        var f = SaveFlex.new(comment: hdrComment, esz: esz, entries: ents)
        f.order = Array(1..<ents.count) + (thumb ? [0] : [])      // thumbnail written last (1200:02a9)
        return try f.encode()
    }

    /// Pack every regular file of a directory (Python `Im1.pack(src_dir, ...)`).
    public static func pack(directory: URL, thumbnail: [UInt8]? = nil) throws -> [UInt8] {
        var files: [String: [UInt8]] = [:]
        for n in try FileManager.default.contentsOfDirectory(atPath: directory.path) {
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: directory.appendingPathComponent(n).path, isDirectory: &isDir), !isDir.boolValue {
                files[n] = [UInt8](try Data(contentsOf: directory.appendingPathComponent(n)))
            }
        }
        return try pack(files: files, thumbnail: thumbnail)
    }

    /// Entries 1.. plus the thumbnail (entry 0 data) and the parsed archive.
    public static func entries(_ data: [UInt8]) throws -> (entries: [Im1Entry], thumbnail: [UInt8], flex: SaveFlex) {
        let f = try SaveFlex.parse(data)
        guard let first = f.entries.first else { throw FormatError("empty .IM1") }
        let ents = try f.entries.dropFirst().map {
            Im1Entry(name: $0.tail.slice(5, $0.tail.count).cstr, flag: try $0.tail.u8(4), originalSize: try $0.tail.u32(0), data: $0.data)
        }
        return (ents, first.data, f)
    }

    /// The member files by name (in archive order in `names`) and the thumbnail blob.
    public static func unpack(_ data: [UInt8]) throws -> (files: [String: [UInt8]], names: [String], thumbnail: [UInt8]) {
        let (ents, thumb, _) = try entries(data)
        var files: [String: [UInt8]] = [:], names: [String] = []
        for e in ents where !e.name.isEmpty {
            if e.flag != 0 { throw FormatError("compressed .IM1 member (codec 11c8:0837 not implemented)") }
            if e.data.count != e.originalSize { throw FormatError("\(e.name): stored size \(e.data.count) != original size \(e.originalSize)") }
            files[e.name] = e.data; names.append(e.name)
        }
        return (files, names, thumb)
    }

    /// Extract into a directory; returns the member names and the thumbnail blob.
    @discardableResult
    public static func unpack(_ data: [UInt8], to directory: URL) throws -> (names: [String], thumbnail: [UInt8]) {
        let r = try unpack(data)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        for (n, b) in r.files { try Data(b).write(to: directory.appendingPathComponent(n)) }
        return (r.names, r.thumbnail)
    }
}
