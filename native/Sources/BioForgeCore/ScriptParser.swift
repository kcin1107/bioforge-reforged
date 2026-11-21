// Script parser: decoded script text -> AST, mirroring re/interp/parse.py (the prototype's parser, bug for bug).
// Format summary: a file is a list of blocks `{ NAME ... }` (routines) and `[ NAME ... ]` (timelines, statements may carry a
// MM:SS timestamp), `<NAME = v, v>` data tables, labels `:NAME`, SWITCH/CASE/DEFAULT/BREAK, IF ... THEN / ELSE, and
// engine statements (keyword + space/comma separated arguments). Expressions: numbers, "strings", names, `_VARS`/`_CONSTS`,
// locals `~0`..`~9`, member locals `CURFIG.~3`, function calls `NAME(args)` / `NAME arg arg`, + - * / %, comparisons,
// AND/OR, IN/NOTIN. A "definition id" numbers every `[`, named `{` and `:` of a file (the target of `JUMP #id`).
// Text is Latin-1 bytes (see ScriptDetokenizer); Python's `\s`/`\w` classes are reproduced by isPySpace/isWord.
import Foundation

public struct ScriptParseError: Error { public let message: String }

/// Dynamic script value (Python int / str / list).
public indirect enum ScriptValue: Equatable, Sendable {
    case int(Int), str(String), list([ScriptValue])
}

/// Expression tree (the prototype's tuples).
public indirect enum ScriptExpr: Sendable {
    case num(Int), str(String), name(String), variable(String), const(Int), local(Int), mlocal(String, Int)
    case unary(String, ScriptExpr)
    case binary(String, ScriptExpr, ScriptExpr)
    case within(negated: Bool, ScriptExpr, list: ScriptExpr)
    case call(String, [ScriptExpr], id: Int)     // id: identity of the node (blocked CALLs are resumed by it)
    case list([ScriptExpr])
    case defid(Int)
}

public final class ScriptStmt {
    public let op: String                        // keyword, or LABEL ASSIGN EXPR CASE DEFAULT BLOCK
    public var args: [ScriptExpr]                // LABEL: [.name(label)]; ASSIGN: [target, value]
    public let line: Int
    public var ts: Int?                          // timeline timestamp in ticks
    public var aop = ""                          // ASSIGN operator
    public var then: [ScriptStmt]?, els: [ScriptStmt]?
    public var braced = false                    // IF: THEN is a { } block (ScriptCode: a dangling ELSE after a braceless IF chain)
    public var defid: Int?, idx: Int?
    public var col: Int?                         // decoded source column of the first token
    public var initial: ScriptExpr?              // LOCALVAR ~n = value
    init(_ op: String, _ args: [ScriptExpr] = [], line: Int, ts: Int?, col: Int?) {
        self.op = op; self.args = args; self.line = line; self.ts = ts; self.col = col
    }
}

public final class ScriptBlock {
    public let name: String, kind: String, line: Int, defid: Int?
    public var body: [ScriptStmt] = []
    public var tables: [ScriptTable] = []
    public var file: ScriptFile?                 // strong: a running process may outlive its unloaded file
    init(_ name: String, _ kind: String, _ line: Int, _ defid: Int?) { self.name = name; self.kind = kind; self.line = line; self.defid = defid }
}

public struct ScriptTable: Sendable { public let name: String?, values: [ScriptValue], line: Int }

public final class ScriptFile {
    public let name: String
    public var blocks: [ScriptBlock] = [], tables: [ScriptTable] = []
    public var defs: [Int: ScriptBlock] = [:]    // definition id -> owning block
    public var failures: [(line: Int, text: String, message: String)] = []
    public var defCount = 0, defClaimed = 0
    var source: DecodedScript?
    private var cached: [(offset: Int, stmt: ScriptStmt, block: ScriptBlock)]?
    init(name: String) { self.name = name }

    /// Every statement in source order with its byte offset in the original .SCP: the start of its first token, where the
    /// engine's script cursor (`pc` of a saved process) sits. The decoded column maps back through the detokenizer's
    /// token-boundary column map.
    public func positions() -> [(offset: Int, stmt: ScriptStmt, block: ScriptBlock)] {
        if let cached { return cached }
        guard let src = source else { return [] }
        var out: [(offset: Int, stmt: ScriptStmt, block: ScriptBlock)] = []
        for b in blocks {
            for st in ScriptFile.walk(b.body) {
                guard let col = st.col, st.line - 1 < src.columns.count, !src.columns[st.line - 1].isEmpty else { continue }
                let pairs = src.columns[st.line - 1]
                let (r, d) = pairs.first(where: { $0.decoded == col }).map { ($0.raw, $0.decoded) }
                    ?? pairs.filter { $0.decoded <= col }.map { ($0.raw, $0.decoded) }.max(by: { $0 < $1 }) ?? (col, col)
                out.append((src.lineStarts[st.line - 1] + r + col - d, st, b))
            }
        }
        let sorted = out.enumerated().sorted { ($0.element.offset, $0.offset) < ($1.element.offset, $1.offset) }.map(\.element)
        cached = sorted
        return sorted
    }

    /// Statements from the first one that starts at or after raw .SCP byte `offset`, in source order.
    public func statements(from offset: Int) -> [(stmt: ScriptStmt, block: ScriptBlock)] {
        let pos = positions()
        let lo = pos.firstIndex(where: { $0.offset >= offset }) ?? pos.count
        return pos[lo...].map { ($0.stmt, $0.block) }
    }

    public static func walk(_ stmts: [ScriptStmt]) -> [ScriptStmt] {
        var out: [ScriptStmt] = []
        for s in stmts {
            out.append(s)
            for sub in [s.then, s.els] { if let sub, !sub.isEmpty { out += walk(sub) } }
        }
        return out
    }
}

/// Globals (VARS.DEF) and constants (DEFINES.DEF), keyed by lower-cased name.
public final class ScriptDefs {
    public var consts: [String: Int] = [:], vars: [String: Int] = [:]
    var nextCallID = 0

    public init() {}
    public init(game: GameFolder) throws {
        func lines(_ f: String) throws -> [[UInt8]] { try game.read("SCRIPT/" + f).split(separator: 0x0a, omittingEmptySubsequences: false).map { Array($0) } }
        func name(_ l: [UInt8], _ q: inout Int) -> String? {      // \s*(_\w+)
            q = 0
            while q < l.count, isPySpace(l[q]) { q += 1 }
            guard q + 1 < l.count, l[q] == 0x5f, isWord(l[q + 1]) else { return nil }
            let s = q
            while q < l.count, isWord(l[q]) { q += 1 }
            return latin1String(l[s..<q]).lowercased()
        }
        for l in try lines("DEFINES.DEF") {
            var q = 0
            guard let n = name(l, &q), q < l.count, isPySpace(l[q]) else { continue }
            while q < l.count, isPySpace(l[q]) { q += 1 }
            let s = q
            if q < l.count, l[q] == 0x2d { q += 1 }
            let d = q
            while q < l.count, isDigit(l[q]) { q += 1 }
            if q > d { consts[n] = Int(latin1String(l[s..<q])) }
        }
        for l in try lines("VARS.DEF") {
            var q = 0
            guard let n = name(l, &q) else { continue }
            while q < l.count, isPySpace(l[q]) { q += 1 }
            guard q < l.count, l[q] == 0x3d else { continue }
            q += 1
            while q < l.count, isPySpace(l[q]) { q += 1 }
            let s = q
            while q < l.count, !isPySpace(l[q]) { q += 1 }
            guard q > s else { continue }
            let v = latin1String(l[s..<q])
            vars[n] = pyInt(v) ?? consts[v.lowercased()] ?? 0
        }
    }
}

/// `-?\d+` as an Int (Python re.fullmatch + int()).
func pyInt(_ s: String) -> Int? {
    let d = s.hasPrefix("-") ? s.dropFirst() : Substring(s)
    return !d.isEmpty && d.utf8.allSatisfy(isDigit) ? Int(s) : nil
}

enum ScriptSyntax {
    static let statements = Set(ScriptTokens.statements.map(\.name))
    static let functions = Set(ScriptTokens.functions.map(\.name))
    /// raw statement-token bytes left in the decoded text: "I" -> IF, "J" -> JUMP, "\u{1a}" -> STOPSOUND ...
    static let tokenByte: [String: String] = Dictionary(ScriptTokens.statements.map { (String(UnicodeScalar(UInt8($0.byte))), $0.name) }, uniquingKeysWith: { $1 })
    static let reserved: Set<String> = ["AND", "OR", "THEN", "IN", "NOTIN", "ELSE"]
    static let comparisons: Set<String> = ["=", "==", "!=", "<", ">", "<=", ">=", "=<", "=>"]
    static let assignOps: Set<String> = ["=", "+=", "-=", "*=", "/=", "++", "--"]
    static let namesOnly: Set<String> = ["MOTION"]   // statements whose bare-name arguments are never function calls
}

// MARK: lexing

struct Tok: Equatable {
    enum Kind { case num, str, ident, op, end }
    var kind: Kind, s: String, n = 0, sp = false, pos = 0
    static let end = Tok(kind: .end, s: "")
    func isOp(_ v: String) -> Bool { kind == .op && s == v }
    var repr: String { kind == .num ? String(n) : pyRepr(s) }       // Python `!r` of the token value
}

/// Python repr() of a str.
func pyRepr(_ s: String) -> String {
    let q = s.contains("'") && !s.contains("\"") ? "\"" : "'"
    var out = q
    for u in s.unicodeScalars {
        switch u {
        case "\\": out += "\\\\"
        case "\n": out += "\\n"
        case "\r": out += "\\r"
        case "\t": out += "\\t"
        case _ where String(u) == q: out += "\\" + q
        case _ where u.value < 0x20 || u.value == 0x7f || (0x80..<0xa1).contains(u.value) || u.value == 0xad: out += String(format: "\\x%02x", u.value)
        default: out.unicodeScalars.append(u)
        }
    }
    return out + q
}

func tokenise(_ t: [UInt8], base: Int = 0) -> [Tok] {
    var out: [Tok] = [], pos = 0
    let n = t.count
    while pos < n {
        var q = pos
        while q < n, isPySpace(t[q]) { q += 1 }
        if q == n {          // only blanks left: the pattern backtracks and `.` takes the last blank
            out.append(Tok(kind: .op, s: latin1String([t[n - 1]]), sp: n - 1 > pos, pos: base + n - 1))
            break
        }
        let c = t[q], sp = q > pos, at = base + q
        var tok: Tok, end = q + 1
        if c == 0x22, let close = t[(q + 1)...].firstIndex(of: 0x22) {
            tok = Tok(kind: .str, s: latin1String(t[(q + 1)..<close])); end = close + 1
        } else if isWord(c) {
            while end < n, isWord(t[end]) { end += 1 }
            if end + 2 < n, t[end] == 0x2e, t[end + 1] == 0x7e, isDigit(t[end + 2]) {     // NAME.~d
                end += 3
                tok = Tok(kind: .ident, s: latin1String(t[q..<end]))
            } else if t[q..<end].allSatisfy(isDigit) {
                tok = Tok(kind: .num, s: latin1String(t[q..<end]), n: Int(latin1String(t[q..<end])) ?? 0)
            } else { tok = Tok(kind: .ident, s: latin1String(t[q..<end])) }
        } else if c == 0x7e, q + 1 < n, isDigit(t[q + 1]) {
            end = q + 2
            tok = Tok(kind: .ident, s: latin1String(t[q..<end]))
        } else if c == 0x21, q + 2 < n, t[q + 1] == 0x49, t[q + 2] == 0x4e, q + 3 == n || !isWord(t[q + 3]) {   // !IN\b
            end = q + 3
            tok = Tok(kind: .ident, s: "NOTIN")
        } else {
            let two = q + 1 < n ? latin1String(t[q...q + 1]) : ""
            if ["++", "--", "+=", "-=", "*=", "/=", "==", "!=", "<=", ">=", "=<", "=>", "&&", "||"].contains(two) { end = q + 2; tok = Tok(kind: .op, s: two) }
            else { tok = Tok(kind: .op, s: latin1String([c])) }
        }
        tok.sp = sp; tok.pos = at
        out.append(tok)
        pos = end
    }
    return out
}

// MARK: logical lines

struct Line {
    let no: Int, text: [UInt8], defid: Int?, col0: Int      // col0: column of text[0] in the source line
    var str: String { latin1String(text) }
}

func pyStrip(_ s: ArraySlice<UInt8>) -> ArraySlice<UInt8> {
    var s = s
    while let f = s.first, isPySpace(f) { s.removeFirst() }
    while let l = s.last, isPySpace(l) { s.removeLast() }
    return s
}

/// Strip comments, join multi-line strings, number definition sites (each `[`, each `{` followed by a name, each `:` not
/// followed by a digit). -> (lines, total_defs)
func logicalLines(_ src: [UInt8]) -> (lines: [Line], defs: Int) {
    var lines: [Line] = [], ndef = 0
    var pend: [UInt8]?, pno = 0
    for (i, piece) in src.split(separator: 0x0a, omittingEmptySubsequences: false).enumerated() {
        var raw = Array(piece), no = i + 1
        if let p = pend { raw = p + [0x0a] + raw; no = pno }
        var instr = false, cut = raw.count
        for (k, ch) in raw.enumerated() {
            if ch == 0x22 { instr.toggle() }
            else if ch == 0x2f, !instr, k + 1 < raw.count, raw[k + 1] == 0x2f { cut = k; break }
        }
        if instr { pend = raw; pno = no; continue }      // unterminated string: continues on the next line
        pend = nil
        var text = Array(raw[..<cut])
        while let l = text.last, isPySpace(l) { text.removeLast() }
        while text.last == 0x3b { text.removeLast() }
        while let l = text.last, isPySpace(l) { text.removeLast() }
        if pyStrip(text[...]).isEmpty { continue }
        var bare: [UInt8] = [], k = 0                   // strings reduced to ""
        while k < text.count {
            if text[k] == 0x22, let close = text[(k + 1)...].firstIndex(of: 0x22) { bare += [0x22, 0x22]; k = close + 1 }
            else { bare.append(text[k]); k += 1 }
        }
        var n = 0
        for (k, ch) in bare.enumerated() {
            if ch == 0x5b { n += 1 }
            else if ch == 0x3a, !(k + 1 < bare.count && isDigit(bare[k + 1])) { n += 1 }
            else if ch == 0x7b {
                var q = k + 1
                while q < bare.count, isPySpace(bare[q]) { q += 1 }
                if q < bare.count, isASCIIAlpha(bare[q]) { n += 1 }
            }
        }
        let stripped = Array(pyStrip(text[...]))
        lines.append(Line(no: no, text: stripped, defid: n > 0 ? ndef : nil, col0: text.count - Array(text.drop { isPySpace($0) }).count))
        ndef += n
    }
    return (lines, ndef)
}

// MARK: expressions

final class ExprParser {
    let t: [Tok], defs: ScriptDefs, calls: Bool
    var p = 0, sym = 0
    init(_ toks: [Tok], _ defs: ScriptDefs, calls: Bool = true) { t = toks; self.defs = defs; self.calls = calls }

    func peek(_ k: Int = 0) -> Tok { p + k < t.count ? t[p + k] : .end }
    func isOp(_ ops: String...) -> Bool { let x = peek(); return x.kind == .op && ops.contains(x.s) }
    func isOp(in ops: Set<String>) -> Bool { let x = peek(); return x.kind == .op && ops.contains(x.s) }
    func isWord(_ ws: String...) -> Bool { let x = peek(); return x.kind == .ident && ws.contains(x.s.uppercased()) }

    func startable() -> Bool {
        let x = peek()
        switch x.kind {
        case .num, .str: return true
        case .ident: return !ScriptSyntax.reserved.contains(x.s.uppercased())
        case .op:
            if x.s == "(" { return true }
            if x.s == "+" || x.s == "-" {         // sign glued to the next token, separated from the previous
                let n = peek(1)
                return x.sp && !n.sp && (n.kind == .num || n.kind == .ident || n.s == "(")
            }
            return false
        case .end: return false
        }
    }

    func full() throws -> ScriptExpr {            // or-level expression
        var a = try and()
        while isWord("OR") || isOp("||") { p += 1; a = .binary("OR", a, try and()) }
        return a
    }
    func and() throws -> ScriptExpr {
        var a = try cmp()
        while isWord("AND") || isOp("&&") { p += 1; a = .binary("AND", a, try cmp()) }
        return a
    }
    func cmp() throws -> ScriptExpr {
        var a = try add()
        while true {
            if isOp(in: ScriptSyntax.comparisons) {
                let op = peek().s
                p += 1
                a = .binary(["=": "==", "=<": "<=", "=>": ">="][op] ?? op, a, try add())
            } else if isWord("IN", "NOTIN") {
                let neg = peek().s.uppercased() == "NOTIN"
                p += 1
                a = .within(negated: neg, a, list: try inList())
            } else { return a }
        }
    }
    func inList() throws -> ScriptExpr {
        var items = [try add()]
        if case .list = items[0] { return items[0] }
        while isOp(",") { p += 1; items.append(try add()) }
        return .list(items)
    }
    func binaryOK() -> Bool { sym == 0 || peek().sp == peek(1).sp }   // `a - b` / `a-b` binary, `a -b` = two args
    func add() throws -> ScriptExpr {
        var a = try mul()
        while isOp("+", "-"), binaryOK() { let op = peek().s; p += 1; a = .binary(op, a, try mul()) }
        return a
    }
    func mul() throws -> ScriptExpr {
        var a = try unary()
        while isOp("*", "/", "%") { let op = peek().s; p += 1; a = .binary(op, a, try unary()) }
        return a
    }
    func unary() throws -> ScriptExpr {
        if isOp("-", "+") {
            let op = peek().s
            p += 1
            let a = try unary()
            if op == "+" { return a }
            if case .num(let v) = a { return .num(-v) }
            return .unary("-", a)
        }
        return try atom()
    }

    /// After '(' : items separated by optional commas, up to ')' (a missing ')' is tolerated).
    func groupItems() throws -> [ScriptExpr] {
        p += 1
        var items: [ScriptExpr] = []
        sym += 1
        while peek().kind != .end, !isOp(")") {
            if isOp(",") { p += 1; continue }
            items.append(try full())
        }
        sym -= 1
        if isOp(")") { p += 1 }
        return items
    }
    /// Space/comma separated arguments (no parentheses) while an argument can start.
    func argSeq() throws -> [ScriptExpr] {
        var items: [ScriptExpr] = []
        sym += 1
        while true {
            if !items.isEmpty, isOp(","), p + 1 < t.count { p += 1 }
            if !startable() { break }
            items.append(try add())
        }
        sym -= 1
        return items
    }

    func atom() throws -> ScriptExpr {
        let x = peek()
        if x.kind == .end { throw ScriptParseError(message: "unexpected end of expression") }
        p += 1
        switch x.kind {
        case .num: return .num(x.n)
        case .str: return .str(x.s)
        case .op where x.s == "(":
            p -= 1
            let items = try groupItems()
            return items.count == 1 ? items[0] : .list(items)
        case .ident: return try ident(x.s)
        default: throw ScriptParseError(message: "unexpected \(x.repr)")
        }
    }

    func ident(_ v: String) throws -> ScriptExpr {
        if let r = v.range(of: ".~") { return .mlocal(String(v[..<r.lowerBound]).uppercased(), Int(v[r.upperBound...]) ?? 0) }
        if v.hasPrefix("~") { return .local(Int(v.dropFirst()) ?? 0) }
        let up = v.uppercased()
        if calls, ScriptSyntax.functions.contains(up) {
            defs.nextCallID += 1
            let id = defs.nextCallID
            return .call(up, isOp("(") ? try groupItems() : try argSeq(), id: id)
        }
        let lo = v.lowercased()
        if v.hasPrefix("_") {
            if let c = defs.consts[lo] { return .const(c) }
            if defs.vars[lo] != nil { return .variable(lo) }
        }
        return .name(v)
    }
}

// MARK: statements

public final class ScriptParser {
    let defs: ScriptDefs, file: ScriptFile, lines: [Line]
    var i = 0, block: ScriptBlock?, nswitch = 0, claimed = 0

    init(name: String, text: [UInt8], defs: ScriptDefs) {
        self.defs = defs
        file = ScriptFile(name: name)
        lines = logicalLines(text).lines
    }

    /// Parse a decoded script (as ScriptDetokenizer.decode produced it).
    public static func parse(_ script: DecodedScript, defs: ScriptDefs) -> ScriptFile {
        let p = ScriptParser(name: script.name, text: script.text, defs: defs)
        let f = p.parse()
        f.source = script
        f.defCount = logicalLines(script.text).defs
        f.defClaimed = p.claimed
        return f
    }

    func fail(_ line: Line, _ msg: String) { file.failures.append((line.no, line.str, msg)) }

    @discardableResult func claim(_ line: Line) -> Int? {
        if let d = line.defid { claimed += 1; file.defs[d] = block }
        return line.defid
    }

    func parse() -> ScriptFile {
        while i < lines.count {
            let line = lines[i]
            if let (open, rest) = header(line.text), rest != Array("{".utf8), rest != Array("[".utf8) {
                parseBlock(line, open, rest)
            } else if line.text.first == 0x3c {
                i += 1
                table(line, &file.tables)
            } else {
                i += 1
                fail(line, "outside_block")
            }
        }
        return file
    }

    /// `([{\[])\s*([^\s].*)$`: opener and the rest of the line (no line break inside).
    func header(_ t: [UInt8]) -> (UInt8, [UInt8])? {
        guard let o = t.first, o == 0x7b || o == 0x5b else { return nil }
        var q = 1
        while q < t.count, isPySpace(t[q]) { q += 1 }
        guard q < t.count, !t[q...].contains(0x0a) else { return nil }
        return (o, Array(t[q...]))
    }

    func parseBlock(_ line: Line, _ open: UInt8, _ rest: [UInt8]) {
        let name = latin1String(rest.prefix { !isPySpace($0) })
        let b = ScriptBlock(name, open == 0x5b ? "timeline" : "routine", line.no, line.defid)
        b.file = file
        file.blocks.append(b)
        block = b                        // nswitch runs on through the file: the engine numbers switches per file (FUN_10c0_01cc)
        claim(line)
        i += 1
        b.body = stmts(top: true)
        block = nil
    }

    func table(_ line: Line, _ dest: inout [ScriptTable]) {
        var inner = pyStrip(line.text[...])
        while inner.first == 0x3c { inner.removeFirst() }
        while let l = inner.last, isPySpace(l) { inner.removeLast() }
        while inner.last == 0x3e { inner.removeLast() }
        inner = pyStrip(inner)
        // (\S+)\s*=\s*(.*)$ : the longest non-blank run that is followed by (blanks and) '='
        let word = inner.prefix { !isPySpace($0) }
        var nameEnd: Int?, restStart = 0
        var q = word.endIndex
        while q < inner.endIndex, isPySpace(inner[q]) { q += 1 }
        if q < inner.endIndex, inner[q] == 0x3d, word.count >= 1 { nameEnd = word.endIndex; restStart = q + 1 }
        else if let e = word.indices.reversed().first(where: { $0 > inner.startIndex && inner[$0] == 0x3d }) { nameEnd = e; restStart = e + 1 }
        var name: String?, rest = inner
        if let nameEnd {
            name = latin1String(inner[inner.startIndex..<nameEnd])
            rest = inner[restStart...]
            while let f = rest.first, isPySpace(f) { rest.removeFirst() }
        }
        var vals: [ScriptValue] = [], k = rest.startIndex
        while k < rest.endIndex {                       // "[^"]*"|[^\s,()]+
            if rest[k] == 0x22, let close = rest[(k + 1)...].firstIndex(of: 0x22) {
                vals.append(.str(latin1String(rest[(k + 1)..<close]))); k = close + 1
            } else if !isPySpace(rest[k]), rest[k] != 0x2c, rest[k] != 0x28, rest[k] != 0x29 {
                var e = k
                while e < rest.endIndex, !isPySpace(rest[e]), rest[e] != 0x2c, rest[e] != 0x28, rest[e] != 0x29 { e += 1 }
                let x = Array(rest[k..<e]), s = latin1String(x)
                if let v = pyInt(s) { vals.append(.int(v)) }
                else if x.first == 0x22 { vals.append(.str(latin1String(x.dropFirst().dropLast()))) }
                else { vals.append(.str(s)) }
                k = e
            } else { k += 1 }
        }
        dest.append(ScriptTable(name: name, values: vals, line: line.no))
    }

    /// Statements until a closing `}`/`]` (consumed) -- or, at block level, the next block header.
    func stmts(top: Bool = false) -> [ScriptStmt] {
        var out: [ScriptStmt] = []
        while i < lines.count {
            let line = lines[i], t = line.text
            if t == [0x7d] || t == [0x5d] { i += 1; return out }
            if top, startsBlock(t), !startsBlock(t, strict: true) { return out }
            if t.first == 0x3c {
                i += 1
                if let b = block { table(line, &b.tables) } else { table(line, &file.tables) }
                continue
            }
            let start = i
            do { out.append(try stmt()) } catch let e as ScriptParseError {
                fail(line, e.message)
                i = max(i, start + 1)
            } catch { fatalError("\(error)") }
        }
        return out
    }

    /// `[{\[]\s*\S` (strict: `[{\[]\s*[{\[]`)
    func startsBlock(_ t: [UInt8], strict: Bool = false) -> Bool {
        guard let o = t.first, o == 0x7b || o == 0x5b else { return false }
        var q = 1
        while q < t.count, isPySpace(t[q]) { q += 1 }
        guard q < t.count else { return false }
        return strict ? t[q] == 0x7b || t[q] == 0x5b : true
    }

    func stmt() throws -> ScriptStmt {
        let line = lines[i]
        i += 1
        let t = line.text
        var q = 0
        while q < t.count, isDigit(t[q]) { q += 1 }
        if q > 0, q < t.count, t[q] == 0x3a {           // MM:SS timestamp
            var e = q + 1
            while e < t.count, isDigit(t[e]) { e += 1 }
            if e > q + 1, e == t.count || isPySpace(t[e]) {
                let ts = (Int(latin1String(t[..<q])) ?? 0) * 30 + (Int(latin1String(t[(q + 1)..<e])) ?? 0)
                var s = e
                while s < t.count, isPySpace(t[s]) { s += 1 }
                if s >= t.count {                       // timestamp alone: applies to the next line's statement
                    let st = try stmt()
                    st.ts = st.ts ?? ts
                    return st
                }
                return try stmtToks(tokenise(Array(t[s...]), base: s), line, ts)
            }
        }
        return try stmtToks(tokenise(t), line, nil)
    }

    /// IF/ELSE body on following lines: `{ ... }` or one statement.
    func body() throws -> [ScriptStmt] {
        guard i < lines.count else { throw ScriptParseError(message: "missing body") }
        if lines[i].text == [0x7b] { i += 1; return stmts() }
        if lines[i].text == [0x7d] || lines[i].text == [0x5d] { throw ScriptParseError(message: "missing body") }
        return [try stmt()]
    }

    func unexpected(_ e: ExprParser, _ what: String) -> ScriptParseError { ScriptParseError(message: "unexpected \(e.peek().repr) \(what)") }
    /// trailing tokens other than one final ')'
    func leftover(_ e: ExprParser) -> Bool { e.p < e.t.count && !(e.p == e.t.count - 1 && e.isOp(")")) }

    func stmtToks(_ tokens: [Tok], _ line: Line, _ ts: Int?) throws -> ScriptStmt {
        guard !tokens.isEmpty else { throw ScriptParseError(message: "empty statement") }
        var toks = tokens
        func mk(_ op: String, _ args: [ScriptExpr] = []) -> ScriptStmt { ScriptStmt(op, args, line: line.no, ts: ts, col: line.col0 + toks[0].pos) }
        if toks[0].isOp(":") {                          // label (`:NAME` or `: NAME`)
            guard toks.count == 2, toks[1].kind == .ident else { throw ScriptParseError(message: "bad label") }
            let s = mk("LABEL", [.name(toks[1].s)])
            s.defid = claim(line)
            return s
        }
        if toks[0].isOp("{"), toks.count == 1 {         // bare `{ ... }` (e.g. CASE body)
            let s = mk("BLOCK")
            s.then = stmts()
            return s
        }
        toks = fixElse(toks)
        let up = toks[0].kind == .ident ? toks[0].s.uppercased() : nil
        if up == "IF" { return try ifStmt(toks, line, ts) }
        if up == "ELSE" { throw ScriptParseError(message: "ELSE without IF") }
        if up == "SWITCH" {
            let cond = try ExprParser(Array(toks[1...]), defs).full()
            let idx = nswitch
            nswitch += 1
            guard i < lines.count, lines[i].text == [0x7b] else { throw ScriptParseError(message: "SWITCH without {") }
            i += 1
            let s = mk("SWITCH", [cond])
            s.then = stmts(); s.idx = idx
            return s
        }
        if up == "CASE" || up == "DEFAULT" {
            let e = ExprParser(Array(toks[1...]), defs)
            let args = up == "CASE" ? [try e.full()] : []
            let claimedID = toks.contains(where: { $0.isOp(":") }) ? claim(line) : nil
            if e.isOp(":") { e.p += 1 }
            let s = mk(up!, args)
            s.defid = claimedID
            if e.p < e.t.count {                        // body on the same line
                let b = mk("BLOCK")
                b.then = [s, try stmtToks(Array(e.t[e.p...]), line, nil)]
                return b
            }
            return s
        }
        if let up, ScriptSyntax.statements.contains(up) {
            let e = ExprParser(Array(toks[1...]), defs, calls: !ScriptSyntax.namesOnly.contains(up))
            if up == "JUMP", e.isOp("#") {              // JUMP #<definition id>
                let n = e.peek(1)
                guard n.kind == .num else { throw ScriptParseError(message: "bad JUMP #id") }
                return mk("JUMP", [.defid(n.n)])
            }
            if up == "LOCALVAR", toks.count > 3, toks[2].isOp("=") {   // GUESS: `LOCALVAR ~0 = 0` declares and initialises
                guard toks[1].kind != .num else { throw ScriptParseError(message: "bad LOCALVAR") }
                let s = mk("LOCALVAR", [try e.ident(toks[1].s)])
                s.initial = try ExprParser(Array(toks[3...]), defs).full()
                return s
            }
            var a = try e.argSeq()
            if a.count == 1, case .list(let items) = a[0] { a = items }
            if e.isOp("="), up == "SETFLAG" { e.p += 1; a.append(try e.full()) }   // GUESS: `SETFLAG (v, bit) = 1`
            if leftover(e) { throw unexpected(e, "in arguments") }
            return mk(up, a)
        }
        if let up, ScriptSyntax.functions.contains(up) {
            let e = ExprParser(toks, defs)
            let call = try e.atom()
            if leftover(e) { throw unexpected(e, "after call") }
            return mk("EXPR", [call])
        }
        let v = toks[0].s
        if toks[0].kind == .ident, v.hasPrefix("~") || v.contains(".~") || v.hasPrefix("_") {
            let e = ExprParser(toks, defs)
            let tgt = try e.ident(v)
            e.p = 1
            let op = e.peek().kind == .op ? e.peek().s : nil
            var isTarget = false
            switch tgt { case .variable, .local, .mlocal, .name: isTarget = true; default: break }
            if isTarget, let op, ScriptSyntax.assignOps.contains(op) {
                e.p += 1
                var ex = e
                if op != "++", op != "--", e.p >= e.t.count {    // value continues on the next line
                    guard i < lines.count else { throw ScriptParseError(message: "missing value") }
                    ex = ExprParser(tokenise(lines[i].text), defs)
                    i += 1
                }
                let val: ScriptExpr = op == "++" || op == "--" ? .num(1) : try ex.full()
                if ex.p < ex.t.count { throw unexpected(ex, "after assignment") }
                let s = mk("ASSIGN", [tgt, val])
                s.aop = op
                return s
            }
        }
        throw ScriptParseError(message: "unrecognised statement")
    }

    func isElse(_ l: Line) -> Bool {
        let t = l.text
        return t.count >= 4 && latin1String(t[0..<4]).uppercased() == "ELSE" && (t.count == 4 || !isWord(t[4]))
    }

    func ifStmt(_ toks: [Tok], _ line: Line, _ ts: Int?) throws -> ScriptStmt {
        let j = toks.firstIndex(where: { $0.kind == .ident && $0.s.uppercased() == "THEN" }) ?? toks.count
        let e = ExprParser(Array(toks[1..<j]), defs)
        let cond = try e.full()
        if e.p < e.t.count, !e.t[e.p...].allSatisfy({ $0.isOp(")") }) { throw unexpected(e, "in condition") }
        var rest = j + 1 < toks.count ? Array(toks[(j + 1)...]) : []
        while let l = rest.last, l.isOp(")"), rest.filter({ $0.s == "(" }).count < rest.filter({ $0.s == ")" }).count { rest.removeLast() }
        let s = ScriptStmt("IF", [cond], line: line.no, ts: ts, col: line.col0 + toks[0].pos)
        if rest.count == 1, rest[0].isOp("{") { s.then = stmts(); s.braced = true }
        else if !rest.isEmpty { s.then = [try stmtToks(rest, line, nil)] }
        else if i < lines.count, isElse(lines[i]) { s.then = [] }        // empty THEN body directly followed by ELSE
        else { s.braced = i < lines.count && lines[i].text == [0x7b]; s.then = try body() }
        if i < lines.count, isElse(lines[i]) {
            let eline = lines[i]
            i += 1
            let etoks = fixElse(Array(tokenise(eline.text).dropFirst()))
            s.els = etoks.isEmpty ? try body() : [try stmtToks(etoks, eline, nil)]
        }
        return s
    }

    /// Defensive: raw statement-token bytes after ELSE (`ELSE I (..)`, `ELSE J X`, `ELSE !`).
    func fixElse(_ toks: [Tok]) -> [Tok] {
        guard let f = toks.first, f.kind == .ident || f.kind == .op, toks.count > 1, let kw = ScriptSyntax.tokenByte[f.s],
              f.kind == .ident || f.s == "!" || f.s.unicodeScalars.first!.value < 32 else { return toks }
        var r = toks
        r[0] = Tok(kind: .ident, s: kw, sp: f.sp, pos: f.pos)
        return r
    }
}
