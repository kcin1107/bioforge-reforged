// Script sources (SCRIPT/*.SCP): detokenizer, mirroring re/formats/script.py.
// Format summary: CRLF Latin-1 text, tab indentation, // comments. The game's tool replaced identifiers by tokens padded with
// spaces to their original length: prefix char + 2 bytes (both >= 0x80), id = ((b0 & 0x7f) << 6) | (b1 & 0x3f):
//   ^ variable (VARS.DEF order), $ define (DEFINES.DEF), ` sound (SOUNDS.DEF then SOUNDS2.DEF), @ function (ScriptTokens),
//   ~ local register 0..9, # label ref (index into the per-file definition list counted like the engine compiler: every
//   '[', every '{' followed by an identifier char, every ':' not adjacent to a digit; strings and // comments skipped),
//   .+4 bytes member variable (CURFIG/CURITEM/PLAYER/ENEMY . ~n), BREAK followed by 2 unprefixed high bytes (6-bit id).
// A statement keyword is a single token byte (see ScriptTokens.statements) as first non-blank byte of a line (or after a
// MM:SS timeline timestamp, or after THEN), followed by a space or end of line.
// Text is handled as Latin-1 bytes throughout (decoded column == byte count), like the Python str of the prototype.
import Foundation

// MARK: Latin-1 helpers shared with the parser (Python str / re semantics on code points 0...255)

/// Python `str.isspace()` / regex `\s` for a Latin-1 code point.
@inline(__always) func isPySpace(_ b: UInt8) -> Bool { (9...13).contains(b) || (0x1c...0x20).contains(b) || b == 0x85 || b == 0xa0 }
@inline(__always) func isDigit(_ b: UInt8) -> Bool { (0x30...0x39).contains(b) }
@inline(__always) func isASCIIWord(_ b: UInt8) -> Bool { isDigit(b) || (0x41...0x5a).contains(b) || (0x61...0x7a).contains(b) || b == 0x5f }
/// Python regex `\w` (str patterns) for a Latin-1 code point: letters, digits and the Latin-1 numerics.
@inline(__always) func isWord(_ b: UInt8) -> Bool {
    isASCIIWord(b) || b == 0xaa || b == 0xb5 || b == 0xba || [0xb2, 0xb3, 0xb9, 0xbc, 0xbd, 0xbe].contains(b)
        || (b >= 0xc0 && b != 0xd7 && b != 0xf7)
}
@inline(__always) func isASCIIAlpha(_ b: UInt8) -> Bool { (0x41...0x5a).contains(b) || (0x61...0x7a).contains(b) || b == 0x5f }

func latin1String<S: Sequence>(_ b: S) -> String where S.Element == UInt8 { String(String.UnicodeScalarView(b.map { Unicode.Scalar($0) })) }
func latin1Bytes(_ s: String) -> [UInt8] { s.unicodeScalars.map { UInt8(truncatingIfNeeded: $0.value) } }

/// Python `str.splitlines()` on Latin-1 text (\n \r \r\n \v \f \x1c \x1d \x1e \x85 separate lines).
func pySplitLines(_ d: [UInt8]) -> [[UInt8]] {
    var out: [[UInt8]] = [], cur: [UInt8] = [], i = 0
    while i < d.count {
        let c = d[i]
        if [0x0a, 0x0d, 0x0b, 0x0c, 0x1c, 0x1d, 0x1e, 0x85].contains(c) {
            out.append(cur); cur = []
            if c == 0x0d, i + 1 < d.count, d[i + 1] == 0x0a { i += 1 }
        } else { cur.append(c) }
        i += 1
    }
    if !cur.isEmpty { out.append(cur) }
    return out
}

// MARK: symbols and results

/// Names of the global variables, defines and sounds (the .DEF files) plus the engine token tables.
public struct ScriptSymbols: Sendable {
    var variables: [[UInt8]], defines: [[UInt8]], sounds: [[UInt8]]
    var functions: [Int: [UInt8]] = [:], statements: [Int: [UInt8]] = [:]

    public init(game: GameFolder) throws {
        func def(_ name: String) throws -> [[UInt8]] {
            try pySplitLines(game.read("SCRIPT/" + name)).compactMap { ln in
                var q = 0
                while q < ln.count, isPySpace(ln[q]) { q += 1 }
                guard q < ln.count, isASCIIAlpha(ln[q]), !ln[q...].starts(with: Array("//".utf8)), ln[q] != 0x7b, ln[q] != 0x7d else { return nil }
                var e = q + 1
                while e < ln.count, isWord(ln[e]) { e += 1 }
                return Array(ln[q..<e])
            }
        }
        variables = try def("VARS.DEF"); defines = try def("DEFINES.DEF")
        sounds = try def("SOUNDS.DEF") + def("SOUNDS2.DEF")
        for (b, n) in ScriptTokens.statements { statements[b] = Array(n.utf8) }
        for (b, n) in ScriptTokens.functions { functions[b] = Array(n.utf8) }
    }
}

/// One detokenized script file with the raw -> decoded column map used to place saved script positions.
public struct DecodedScript: Sendable {
    public let name: String                      // "AIRHALL.scr" (decoded-file name, as written by script.py)
    public let text: [UInt8]                     // decoded Latin-1 text, LF line ends
    public let lineStarts: [Int]                 // byte offset of each line in the original .SCP
    public let columns: [[(raw: Int, decoded: Int)]]   // per line: (raw column, decoded column) at every token boundary
    public let unresolved: [String]              // "kind name:line hex" of tokens that could not be resolved
}

// MARK: detokenizer

public struct ScriptDetokenizer: Sendable {
    public let symbols: ScriptSymbols
    public init(symbols: ScriptSymbols) { self.symbols = symbols }

    public func decode(_ data: [UInt8], name: String) -> DecodedScript {
        let syms = symbols
        // '#' targets: port of the engine compiler's definition counter (FUN_1118_07dc)
        var defs: [[UInt8]] = []
        var q = 0
        let size = data.count
        func run(_ from: Int) -> Int { var e = from; while e < size, isASCIIWord(data[e]) { e += 1 }; return e }
        func blanks(_ from: Int) -> Int { var e = from; while e < size, data[e] == 0x20 || data[e] == 0x09 { e += 1 }; return e }
        while q < size {
            let c = data[q]
            if c == 0x22 {                                    // "string": skipped when closed
                q = data[(q + 1)...].firstIndex(of: 0x22).map { $0 + 1 } ?? q + 1
            } else if c == 0x2f, q + 1 < size, data[q + 1] == 0x2f {   // // comment
                q = data[q...].firstIndex(of: 0x0a) ?? size
            } else if c == 0x5b || (c == 0x3a && !(q > 0 && isDigit(data[q - 1])) && !(q + 1 < size && isDigit(data[q + 1]))) {
                let s = blanks(q + 1), e = run(s)             // '[' and ':' define a (possibly unnamed) target
                defs.append(e > s ? Array(data[s..<e]) : Array("#\(defs.count)".utf8))
                q = e
            } else if c == 0x7b {                             // '{' only when an identifier follows
                let s = blanks(q + 1), e = run(s)
                if e > s { defs.append(Array(data[s..<e])); q = e } else { q += 1 }
            } else { q += 1 }
        }

        var out: [[UInt8]] = [], cols: [[(raw: Int, decoded: Int)]] = [], bad: [String] = []
        let space = [UInt8(0x20)]
        for (ln0, rawLine) in data.split(separator: 0x0a, omittingEmptySubsequences: false).enumerated() {
            let ln = ln0 + 1
            var raw = Array(rawLine)
            while raw.last == 0x0d { raw.removeLast() }
            let n = raw.count
            var res: [[UInt8]] = [], resLen = 0, i = 0
            var lc: [(raw: Int, decoded: Int)] = []
            func add(_ p: [UInt8]) { res.append(p); resLen += p.count }
            func mark(_ k: Int) { lc.append((k, resLen)) }
            func unresolved(_ kind: String, _ at: Int) {
                bad.append("\(kind) \(name):\(ln) " + raw[at..<min(at + 3, n)].map { String(format: "%02x", $0) }.joined())
            }
            /// statement token at raw[j] -> advance i past token + padding
            @discardableResult func stmt(_ j: Int) -> Bool {
                guard j < n, let kw = syms.statements[Int(raw[j])], j + 1 == n || raw[j + 1] == 0x20 else { return false }
                add(kw)
                i = j + 1
                if i < n, raw[i] == 0x20 {
                    add(space)
                    while i < n, raw[i] == 0x20 { i += 1 }
                }
                return true
            }
            var j = 0
            while j < n, raw[j] == 0x20 || raw[j] == 0x09 { j += 1 }
            add(Array(raw[0..<j])); i = j
            var k = j                                          // timeline timestamp \d+:\d+ followed by a blank
            while k < n, isDigit(raw[k]) { k += 1 }
            if k > j, k < n, raw[k] == 0x3a {
                var e = k + 1
                while e < n, isDigit(raw[e]) { e += 1 }
                if e > k + 1, e < n, raw[e] == 0x20 || raw[e] == 0x09 {
                    add(Array(raw[j..<e]))
                    k = e
                    while k < n, raw[k] == 0x20 || raw[k] == 0x09 { k += 1 }
                    add(space); i = k; j = k
                }
            }
            mark(j)
            if !stmt(j), j < n, raw[j] >= 0x80 { unresolved("stmt", j) }
            var instr = false
            while i < n {
                mark(i)
                let c = raw[i]
                if !instr, c == 0x2f, i + 1 < n, raw[i + 1] == 0x2f { add(Array(raw[i...])); break }
                if c == 0x22 { instr.toggle() }
                let prefix = c == 0x5e || c == 0x24 || c == 0x60 || c == 0x40 || c == 0x7e   // ^ $ ` @ ~
                if !instr, prefix, i + 2 < n, raw[i + 1] >= 0x80, raw[i + 2] >= 0x80 {
                    let tid = Int(raw[i + 1] & 0x7f) << 6 | Int(raw[i + 2] & 0x3f)
                    let nm: [UInt8]?
                    switch c {
                    case 0x7e: nm = tid < 10 ? Array("~\(tid)".utf8) : nil
                    case 0x40: nm = syms.functions[tid]
                    case 0x5e: nm = tid < syms.variables.count ? syms.variables[tid] : nil
                    case 0x24: nm = tid < syms.defines.count ? syms.defines[tid] : nil
                    default: nm = tid < syms.sounds.count ? syms.sounds[tid] : nil
                    }
                    guard let nm else {
                        unresolved(String(UnicodeScalar(c)), i); add(Array(raw[i..<i + 3])); i += 3; continue
                    }
                    add(nm); i += 3
                    if i < n, raw[i] == 0x20 {
                        add(space)
                        while i < n, raw[i] == 0x20 { i += 1 }
                    }
                    continue
                }
                if !instr, c == 0x2e, i + 4 < n, raw[(i + 1)...(i + 4)].min()! >= 0x80 {   // member variable (selector 1 CURITEM +0xe7f, 2 CURFIG +0xe7b: 10c0:24e1)
                    let sel = Int(raw[i + 1] & 0x7f) << 6 | Int(raw[i + 2] & 0x3f), loc = Int(raw[i + 3] & 0x7f) << 6 | Int(raw[i + 4] & 0x3f)
                    if sel > 0, sel < 5, loc < 10 {
                        add(Array("\(["", "CURITEM", "CURFIG", "PLAYER", "ENEMY"][sel]).~\(loc)".utf8)); i += 5; continue
                    }
                    unresolved(".", i)
                }
                let lab = c == 0x23 && i + 2 < n && min(raw[i + 1], raw[i + 2]) >= 0x80
                let brk = c >= 0x80 && i + 1 < n && raw[i + 1] >= 0x80 && res.suffix(2).elementsEqual([Array("BREAK".utf8), space])
                if !instr, lab || brk {
                    let o = lab ? i + 1 : i
                    let tid = Int(raw[o] & 0x7f) << 6 | Int(raw[o + 1] & 0x3f)
                    if brk { add(Array(String(tid).utf8)) }
                    else if tid < defs.count { add(defs[tid]) }
                    else { unresolved("#", i); add(Array(raw[i..<i + 3])) }
                    i = o + 2; continue
                }
                add([c]); i += 1
                if !instr, c == 0x20, i >= 5, raw[(i - 5)..<i].elementsEqual("THEN ".utf8) {   // inline statement after THEN
                    while i < n, raw[i] == 0x20 { add(space); i += 1 }
                    mark(i)
                    stmt(i)
                }
            }
            var line = Array(res.joined())
            while line.last == 0x20 { line.removeLast() }
            out.append(line)
            cols.append(lc)
        }
        var starts = [0]
        for l in data.split(separator: 0x0a, omittingEmptySubsequences: false).dropLast() { starts.append(starts.last! + l.count + 1) }
        return DecodedScript(name: name, text: Array(out.joined(separator: [0x0a])), lineStarts: starts, columns: cols, unresolved: bad)
    }
}

/// Every SCRIPT/*.SCP of a game folder, detokenized, plus the level script lists (SCRIPT/<LEVEL>.LVL).
public final class ScriptLibrary {
    public let game: GameFolder
    public let scripts: [DecodedScript]                  // sorted by file name
    private let byName: [String: DecodedScript]          // lower-case "airhall.scr"

    public init(game: GameFolder) throws {
        self.game = game
        let tool = ScriptDetokenizer(symbols: try ScriptSymbols(game: game))
        scripts = try game.list("SCRIPT", ext: "SCP").map { f in
            tool.decode(try game.read("SCRIPT/" + f), name: (f as NSString).deletingPathExtension + ".scr")
        }
        byName = Dictionary(scripts.map { ($0.name.lowercased(), $0) }, uniquingKeysWith: { $1 })
    }

    public func script(named name: String) -> DecodedScript? { byName[name.lowercased()] }

    /// Script names listed in SCRIPT/<level>.LVL, in order.
    public func levelScripts(_ level: String) throws -> [String] {
        try game.read("SCRIPT/" + level.uppercased() + ".LVL").split(separator: 0x0a, omittingEmptySubsequences: false).compactMap { l in
            var w = Array(l)
            if let c = w.indices.dropLast().first(where: { w[$0] == 0x2f && w[$0 + 1] == 0x2f }) { w.removeSubrange(c...) }
            while let f = w.first, isPySpace(f) { w.removeFirst() }
            while let e = w.last, isPySpace(e) { w.removeLast() }
            let s = latin1String(w)
            return s.lowercased().hasSuffix(".scr") ? s : nil
        }
    }
}
