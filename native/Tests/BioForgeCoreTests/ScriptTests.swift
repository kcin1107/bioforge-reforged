// Stage 3a parity tests: script detokenizer, parser, code generation and VM traces against the Python prototype
// (fixtures.json "stage3", written by re/tools/native_fixtures.py). The canonical text forms hashed here (AST dump, positions,
// instruction lists, trace lines) mirror the dump helpers of that script line for line.
import Foundation
import Testing
@testable import BioForgeCore

nonisolated(unsafe) let stage3 = fixtures["stage3"] as! JSON
nonisolated(unsafe) let scriptLibrary: ScriptLibrary? = game.flatMap { try? ScriptLibrary(game: $0) }

func shaText(_ lines: [String]) -> String { sha(latin1Bytes(lines.joined(separator: "\n"))) }
func chunkHashes(_ lines: [String], _ n: Int = 100) -> [String] {
    stride(from: 0, to: lines.count, by: n).map { String(shaText(Array(lines[$0..<min($0 + n, lines.count)])).prefix(12)) }
}
/// Message locating the first differing 100-line chunk.
func firstDivergence(_ lines: [String], _ want: [String]) -> String {
    let got = chunkHashes(lines)
    guard let i = zip(got, want).enumerated().first(where: { $0.element.0 != $0.element.1 })?.offset else { return "chunk count \(got.count) vs \(want.count)" }
    return "first differing chunk \(i): line \(i * 100) = \(lines[i * 100])"
}

// MARK: canonical dumps

func qs(_ s: String) -> String {
    "\"" + s.unicodeScalars.map { (0x20..<0x7f).contains($0.value) && $0 != "\\" && $0 != "\"" ? String($0) : String(format: "\\x%02x", $0.value) }.joined() + "\""
}
func val(_ v: ScriptValue) -> String {
    switch v {
    case .int(let i): return String(i)
    case .str(let s): return qs(s)
    case .list(let l): return "[" + l.map(val).joined(separator: ",") + "]"
    }
}
func ex(_ e: ScriptExpr) -> String {
    switch e {
    case .num(let n): return String(n)
    case .str(let s): return qs(s)
    case .name(let s): return "n:" + s
    case .variable(let s): return "v:" + s
    case .const(let n): return "c:\(n)"
    case .local(let i): return "l:\(i)"
    case .mlocal(let s, let i): return "m:\(s).\(i)"
    case .unary(let op, let a): return "(un \(op) \(ex(a)))"
    case .binary(let op, let a, let b): return "(\(op) \(ex(a)) \(ex(b)))"
    case .within(let neg, let a, let l): return "(\(neg ? "notin" : "in") \(ex(a)) \(ex(l)))"
    case .call(let f, let a, _): return "(call \(f)\(a.map { " " + ex($0) }.joined()))"
    case .list(let l): return "[" + l.map(ex).joined(separator: " ") + "]"
    case .defid(let n): return "defid:\(n)"
    }
}
func stmtDump(_ stmts: [ScriptStmt], _ depth: Int, _ out: inout [String]) {
    func opt(_ v: Int?) -> String { v.map(String.init) ?? "-" }
    for s in stmts {
        let args = s.op == "ASSIGN" ? "\(ex(s.args[0])) \(s.aop) \(ex(s.args[1]))" : s.args.map(ex).joined(separator: " ")
        out.append("\(depth)|\(s.op)|\(s.line)|ts=\(opt(s.ts))|col=\(opt(s.col))|def=\(opt(s.defid))|idx=\(opt(s.idx))|init=\(s.initial.map(ex) ?? "-")|\(args)")
        for (tag, sub) in [("THEN", s.then), ("ELSE", s.els)] {
            if let sub { out.append("\(depth)|\(tag)"); stmtDump(sub, depth + 1, &out) }
        }
    }
}
func tableDump(_ tag: String, _ tables: [ScriptTable]) -> [String] {
    tables.map { "\(tag)|\($0.name ?? "-")|\($0.values.map(val).joined(separator: ","))|\($0.line)" }
}
func fileDump(_ f: ScriptFile) -> [String] {
    var out = ["FILE \(f.name) defs=\(f.defCount) claimed=\(f.defClaimed)"]
    for b in f.blocks {
        out.append("BLOCK|\(b.name)|\(b.kind)|\(b.line)|\(b.defid.map(String.init) ?? "-")")
        stmtDump(b.body, 0, &out)
        out += tableDump("BT", b.tables)
    }
    out += tableDump("FT", f.tables)
    out += f.defs.sorted { $0.key < $1.key }.map { "DEF|\($0.key)|\($0.value.name)" }
    out += f.failures.map { "FAIL|\($0.line)|\($0.message)" }
    return out
}
func codeDump(_ c: ScriptCode) -> [String] {
    var out: [String] = []
    for (n, i) in c.ins.enumerated() {
        var t = "", op = ""
        switch i.op {
        case .end: op = "END"
        case .jz: op = "JZ"; t = String(i.target)
        case .jmp: op = "JMP"; t = String(i.target)
        case .break: op = "BREAK"; t = "\(i.sw!.idx) \(i.target)"
        case .switch: op = "SWITCH"; t = "default=\(i.sw!.defaultTarget!) cases=\(i.sw!.cases.map { String($0.1) }.joined(separator: ","))"
        case .stmt: op = "STMT"; t = i.stmt!.op
        }
        out.append("\(n)|\(op)|\(t)|ts=\(i.ts.map(String.init) ?? "-")")
    }
    out.append("LABELS " + c.labels.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }.joined(separator: ","))
    out.append("DEFIDX " + c.defidx.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }.joined(separator: ","))
    return out
}

func requireLibrary() throws -> ScriptLibrary {
    _ = try requireGame()
    guard let l = scriptLibrary else { throw FormatError("could not detokenize SCRIPT/*.SCP") }
    return l
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ScriptTests {
    @Test func detokenizeEveryScript() throws {
        let lib = try requireLibrary()
        let fx = stage3["detok"] as! [String: JSON]
        #expect(lib.scripts.count == fx.count && fx.count == 107)
        var unresolved = 0
        for s in lib.scripts {
            let want = try #require(fx[s.name], "\(s.name) missing in fixtures")
            #expect(sha(s.text) == want["sha"] as! String, "\(s.name) text")
            #expect(s.text.split(separator: 0x0a, omittingEmptySubsequences: false).count == want["lines"] as! Int, "\(s.name) lines")
            #expect(s.unresolved.count == want["unresolved"] as! Int, "\(s.name) unresolved \(s.unresolved.prefix(3))")
            unresolved += s.unresolved.count
        }
        #expect(unresolved == 0)
        print("detokenizeEveryScript: \(lib.scripts.count) files matched, \(unresolved) unresolved tokens")
    }

    @Test func parseEveryScript() throws {
        let lib = try requireLibrary()
        let defs = try ScriptDefs(game: requireGame())
        let fx = stage3["parse"] as! [String: JSON]
        var statements = 0, offsets = 0
        for s in lib.scripts {
            let want = try #require(fx[s.name], "\(s.name) missing in fixtures")
            let f = ScriptParser.parse(s, defs: defs)
            let walk = f.blocks.flatMap { b in ScriptFile.walk(b.body).map { (b, $0) } }
            let blocks = (want["blocks"] as! [[Any]]).map { "\($0[0])|\($0[1])|\($0[2])" }
            #expect(f.blocks.map { "\($0.name)|\($0.kind)|\($0.line)" } == blocks, "\(s.name) blocks")
            let labels = (want["labels"] as! [[Any]]).map { "\($0[0])|\($0[1])|\($0[2])" }
            #expect(walk.filter { $0.1.op == "LABEL" }.map { b, st in
                if case .name(let n) = st.args[0] { return "\(b.name)|\(n)|\(st.defid.map(String.init) ?? "<null>")" }
                return "?" } == labels, "\(s.name) labels")
            #expect(walk.count == want["statements"] as! Int, "\(s.name) statement count")
            #expect(f.tables.count + f.blocks.reduce(0) { $0 + $1.tables.count } == want["tables"] as! Int, "\(s.name) tables")
            #expect(f.defCount == want["defs"] as! Int && f.defClaimed == want["claimed"] as! Int, "\(s.name) definition counter")
            let fails = (want["failures"] as! [[Any]]).map { "\($0[0])|\($0[1])" }
            #expect(f.failures.map { "\($0.line)|\($0.message)" } == fails, "\(s.name) failures")
            let dump = fileDump(f)
            #expect(dump.count == want["ast_lines"] as! Int, "\(s.name) AST lines")
            #expect(shaText(dump) == want["ast_sha"] as! String, "\(s.name) AST: \(firstDivergence(dump, want["chunks"] as! [String]))")
            let pos = f.positions()
            let lines = pos.map { "\($0.offset)|\($0.stmt.line)|\($0.stmt.op)|\($0.block.name)" }
            #expect(pos.count == want["pos_count"] as! Int, "\(s.name) offset count")
            #expect(shaText(lines) == want["pos_sha"] as! String, "\(s.name) statement offsets")
            #expect(Array(pos.prefix(8).map(\.offset)) == want["pos_head"] as! [Int], "\(s.name) first offsets")
            statements += walk.count; offsets += pos.count
        }
        print("parseEveryScript: \(lib.scripts.count) files, \(statements) statements, \(offsets) offsets matched")
    }

    @Test func compiledCode() throws {
        let lib = try requireLibrary()
        let vm = ScriptVM(defs: try ScriptDefs(game: requireGame()))
        for s in lib.scripts { vm.load(s) }
        var lines: [String] = []
        for f in vm.files { for b in f.blocks { lines += ["CODE \(f.name)|\(b.name)"] + codeDump(vm.code(b)) } }
        #expect(lines.count == stage3["code_lines"] as! Int)
        #expect(shaText(lines) == stage3["code_sha"] as! String)
        // saved-process positions -> instruction index
        let loc = stage3["locate"] as! [[Any]]
        for e in loc {
            let f = try #require(vm.files.first { $0.name == e[0] as! String })
            let b = try #require(f.blocks.first { $0.name == e[1] as! String })
            #expect(vm.locate(b, offset: e[2] as! Int) == e[3] as! Int, "locate \(e[0]) \(e[1]) @\(e[2])")
        }
        print("compiledCode: \(lines.count) instruction lines, \(loc.count) locate samples matched")
    }

    @Test func syntheticScripts() throws {
        let cases = stage3["synthetic"] as! [JSON]
        for fx in cases {
            let name = fx["name"] as! String
            let defs = try ScriptDefs(game: requireGame())
            for (k, v) in fx["globals"] as! [String: Int] { defs.vars[k] = v }
            for c in "abcdefghrnx" { defs.vars["_" + String(c)] = defs.vars["_" + String(c)] ?? 0 }
            let eng = RecordingEngine()
            let vm = ScriptVM(engine: eng, defs: defs)
            let text = latin1Bytes(fx["src"] as! String)
            let f = vm.load(DecodedScript(name: "SYN_\(name).scr", text: text, lineStarts: [], columns: [], unresolved: []))
            #expect(f.failures.isEmpty, "\(name) parse failures \(f.failures)")
            vm.fire(fx["block"] as! String)
            vm.runTicks(fx["ticks"] as! Int)
            #expect(eng.log.map { "\($0.tick)|\($0.block)|\($0.kind.rawValue)|\($0.name)|\(val(.list($0.args)))" } == fx["log"] as! [String], "\(name) log")
            #expect(vm.changes.map { "\($0.tick)|\($0.name)|\(val($0.old))|\(val($0.new))" } == fx["changes"] as! [String], "\(name) changes")
            let want = fx["vars"] as! [String: String]
            #expect(Dictionary(uniqueKeysWithValues: want.keys.map { ($0, val(vm.globals[$0]!)) }) == want, "\(name) variables")
            let objs = fx["objects"] as! [String: String]
            #expect(Dictionary(uniqueKeysWithValues: vm.objectKeys.map { ($0, val(.list(vm.objectRecord($0)))) }) == objs, "\(name) objects")
            #expect(vm.warnings == fx["warnings"] as! [String], "\(name) warnings")
            #expect(vm.processes.map { "\($0.handle)|\($0.block.name)|\($0.pc)|\($0.wake)" } == fx["procs"] as! [String], "\(name) processes")
            #expect(vm.tick == fx["tick"] as! Int, "\(name) tick")
        }
        print("syntheticScripts: \(cases.count) inline scripts matched")
    }

    /// test_interp `test_call_child_ending_outside_walk`: engine code (no walk under way) ends a CALL child; the caller is only woken
    /// (1238:077f) and goes on in the next walk.
    @Test func callChildEndingOutsideAWalk() throws {
        let defs = try ScriptDefs(game: requireGame())
        for c in "abcdefghrnx" { defs.vars["_" + String(c)] = defs.vars["_" + String(c)] ?? 0 }
        let vm = ScriptVM(engine: RecordingEngine(), defs: defs)
        let src = "{ MAIN\n\t_r = CALL CHILD\n\t_a = 1\n}\n{ CHILD\n\tSUSPEND\n\tJUMP CHILD\n}"
        _ = vm.load(DecodedScript(name: "SYN_outside_walk.scr", text: latin1Bytes(src), lineStarts: [], columns: [], unresolved: []))
        vm.fire("MAIN")
        vm.runTicks(2)
        vm.finish(try #require(vm.processes.first { $0.block.name == "CHILD" }))
        #expect(vm.globals["_a"] == .int(0))
        vm.runTicks(1)
        #expect(vm.changes.filter { $0.name == "_a" }.map(\.tick) == [2])
    }

    @Test func vmTraces() throws {
        let lib = try requireLibrary()
        let traces = stage3["traces"] as! [JSON]
        var entries = 0
        for fx in traces {
            let spec = fx["spec"] as! JSON, name = spec["name"] as! String
            let t = try runTrace(spec, lib)
            let log = t.log.map { "\($0.tick)|\($0.block)|\($0.kind.rawValue)|\($0.name)|\(val(.list($0.args)))" }
            #expect(log.count == fx["log_len"] as! Int, "\(name) log length")
            #expect(shaText(log) == fx["log_sha"] as! String, "\(name) log: \(firstDivergence(log, fx["log_chunks"] as! [String]))")
            let changes = t.vm.changes.map { "\($0.tick)|\($0.name)|\(val($0.old))|\(val($0.new))" }
            #expect(changes.count == fx["changes_len"] as! Int, "\(name) changes length")
            #expect(shaText(changes) == fx["changes_sha"] as! String, "\(name) changes: \(firstDivergence(changes, fx["changes_chunks"] as! [String]))")
            let globals = t.vm.globals.sorted { $0.key < $1.key }.map { "\($0.key)=\(val($0.value))" }
            #expect(shaText(globals) == fx["globals_sha"] as! String, "\(name) globals")
            let keys = t.vm.objectKeys.sorted()
            #expect(shaText(keys.map { "\($0)=\(val(.list(t.vm.objectRecord($0))))" }) == fx["objects_sha"] as! String, "\(name) objects")
            #expect(keys.count == fx["objects"] as! Int, "\(name) object count")
            let procs = t.vm.processes.map { "\($0.handle)|\($0.block.name)|\($0.pc)|\($0.wake)|\($0.suspended ? "True" : "False")|\($0.origin.map(String.init) ?? "-")" }
            #expect(procs == fx["procs"] as! [String], "\(name) processes")
            #expect(t.vm.warnings == fx["warnings"] as! [String], "\(name) warnings")
            #expect(t.vm.tick == fx["tick"] as! Int && t.vm.nextHandle == fx["next_handle"] as! Int, "\(name) tick/handles")
            #expect(t.vm.blocks.count == fx["blocks"] as! Int && t.vm.duplicates.count == fx["duplicates"] as! Int, "\(name) blocks")
            #expect(Array(log.prefix(12)) == fx["head"] as! [String], "\(name) head")
            entries += log.count
        }
        print("vmTraces: \(traces.count) traces, \(entries) engine calls matched")
    }
}

// MARK: trace driver (mirrors native_fixtures.py TraceEngine / trace_fixture)

let traceLevels: Set<String> = ["BEACH", "CHAOS", "CONTROL", "DIGSITE", "LANDPAD", "PLATFORM", "TANKS", "TITLE", "TOWER", "TUNROOM"]

final class TraceEngine: RecordingEngine {
    let library: ScriptLibrary
    var spec: [String: Any]
    var counts: [String: Int] = [:]

    init(spec: [String: Any], library: ScriptLibrary) { self.spec = spec; self.library = library; super.init() }

    override func call(_ kind: CallKind, _ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) -> ScriptValue {
        let vm = self.vm!
        log.append(Entry(tick: vm.tick, block: proc.block.name, kind: kind, name: name, args: args))
        let k = counts[name, default: 0]
        counts[name] = k + 1
        if kind == .stmt {
            if name == "LOADLEVEL", let a = args.first, traceLevels.contains(pyStr(a).uppercased()) {
                vm.killLevelOwned(caller: proc)
                vm.unloadScripts()
                try! vm.loadLevel(pyStr(a), library: library)
                vm.endUnloaded(proc)
            } else if name == "MON_JUMP" {
                let until = vm.tick + 2
                proc.waitPred = { [unowned vm] in vm.tick >= until }
            }
            return .int(0)
        }
        if ["SOUND", "GETSOUNDHANDLE", "SUBTITLE", "MINORSUBTITLE"].contains(name) { return .int(vm.timedHandle(ticks: 20 + 10 * (k % 5))) }
        let ints = args.prefix(2).compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        if name == "RANDOM", args.count >= 2, ints.count == 2 {
            return .int(ints.min()! + (7 * k + 3) % (ints.max()! - ints.min()! + 1))
        }
        let all = args.prefix(3).compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        if name == "COUNTBITS", args.count >= 3, all.count == 3 {
            return .int(all[1] <= all[2] ? (all[1]...all[2]).reduce(0) { $0 + ((all[0] >> $1) & 1) } : 0)
        }
        let returns = spec["returns"] as! [String: Any]
        let r = returns[name] ?? returns["*"] ?? 0
        if let list = r as? [Int] { return .int(list[k % list.count]) }
        return .int(r as! Int)
    }
}

func runTrace(_ spec: JSON, _ lib: ScriptLibrary) throws -> (vm: ScriptVM, log: [RecordingEngine.Entry]) {
    let eng = TraceEngine(spec: spec, library: lib)
    let vm = ScriptVM(engine: eng, defs: try ScriptDefs(game: requireGame()))
    try vm.loadLevel(spec["level"] as! String, library: lib)
    for (k, v) in (spec["globals"] as? [String: Any]) ?? [:] {
        vm.globals[k] = .int(v as? Int ?? vm.defs.consts[v as! String]!)
    }
    var fires = (spec["fires"] as! [[Any]]).sorted { ($0[0] as! Int, $0[1] as! String) < ($1[0] as! Int, $1[1] as! String) }
    let pause = spec["pause"] as? [Int]
    for i in 0..<((spec["ticks"] as! Int) + (pause.map { $0[1] - $0[0] } ?? 0)) {
        eng.paused = pause.map { $0[0] <= i && i < $0[1] } ?? false
        while let f = fires.first, (f[0] as! Int) <= vm.tick, !eng.paused {
            fires.removeFirst()
            let block = f[1] as! String, owner = f.count > 2 ? f[2] as! String : "level"
            if f.count == 4 { vm.spawnAt(block, label: f[3] as! String, ctx: ScriptContext(curFig: "LEX", owner: owner)) }
            else { vm.fire(block, owner: owner) }
        }
        vm.tickOnce()
    }
    return (vm, eng.log)
}
