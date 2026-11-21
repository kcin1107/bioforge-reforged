// Script VM: cooperative scheduler (30 Hz), processes and expression evaluator, mirroring re/interp/vm.py.
// Format summary: a block's statements compile to a flat instruction list (IF -> JZ/JMP, SWITCH/CASE/BREAK -> jump tables,
// labels -> indices); every process runs it until a WAIT/SUSPEND/blocked CALL yields. One tick = 1/30 s. Statements and
// functions the VM does not implement itself (everything except control flow, CALL/PROCESS, flags, process control) are
// delegated to the ScriptEngine (the prototype's Engine): call(kind, name, args, proc) -> value.
// GUESSES (not established from the executable) are marked "GUESS", as in the prototype.
import Foundation

public enum CallKind: String, Sendable { case stmt, function = "func" }

/// What the VM needs from the game world. Optional hooks have defaults (the prototype probes them with getattr).
public protocol ScriptEngine: AnyObject {
    func call(_ kind: CallKind, _ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) -> ScriptValue
    /// Called when the engine is installed in a VM.
    func attach(_ vm: ScriptVM)
    /// True while the options dialog is open: the scheduler and its clock stand still (FUN_10b0_136b).
    var paused: Bool { get }
    /// Maps CURFIG/CURITEM/PLAYER ... record names (PLAYER -> the flagged player figure).
    func objectKey(_ name: String) -> String
    /// ENEMY = the previous current figure's enemy.
    func enemy(of figure: String?) -> String?
    /// 10c8:081b step 2: a RUNFLIC scene process lives while a flic is open and not finished.
    var sceneAlive: Bool { get }
}

public extension ScriptEngine {
    var sceneAlive: Bool { true }
    func attach(_ vm: ScriptVM) {}
    var paused: Bool { false }
    func objectKey(_ name: String) -> String { name }
    func enemy(of figure: String?) -> String? { nil }
}

/// Logs (tick, process block name, kind, name, args); returns 0 unless `returns[name]` is set.
open class RecordingEngine: ScriptEngine {
    public struct Entry: Equatable, Sendable {
        public let tick: Int, block: String, kind: CallKind, name: String, args: [ScriptValue]
    }
    public var log: [Entry] = []
    public var returns: [String: ScriptValue]
    public weak var vm: ScriptVM?
    public var paused = false

    public init(returns: [String: ScriptValue] = [:]) { self.returns = returns }
    open func attach(_ vm: ScriptVM) { self.vm = vm }
    open func objectKey(_ name: String) -> String { name }
    /// +0xe83: the object a newly spawned process is bound to (killed with it); the world resolves CURFIG / CURITEM.
    open func processReferent(_ p: ScriptProcess) -> AnyObject? { nil }
    open func enemy(of figure: String?) -> String? { nil }
    open var sceneAlive: Bool { true }
    /// At the end of each walk (World: an idle requested in an earlier walk starts, World.startPendingIdles).
    open func endOfWalk() {}
    open func call(_ kind: CallKind, _ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) -> ScriptValue {
        log.append(Entry(tick: vm?.tick ?? 0, block: proc.block.name, kind: kind, name: name, args: args))
        return returns[name] ?? .int(0)
    }
}

/// Raised inside expression evaluation when the process must wait (CALL) and re-run the statement.
struct Blocked: Error {}

// MARK: Python-flavoured value helpers

func truth(_ v: ScriptValue) -> Bool {
    switch v {
    case .int(let i): return i != 0
    case .str(let s): return !s.isEmpty
    case .list(let l): return !l.isEmpty
    }
}
func num(_ v: ScriptValue) -> Int { if case .int(let i) = v { return i }; return 0 }
func idiv(_ a: Int, _ b: Int) -> Int { b == 0 ? 0 : a.dividedReportingOverflow(by: b).partialValue }
/// Python str(value)
public func pyStr(_ v: ScriptValue) -> String {
    switch v {
    case .int(let i): return String(i)
    case .str(let s): return s
    case .list: return pyRepr(v)
    }
}
/// Python repr(value)
public func pyRepr(_ v: ScriptValue) -> String {
    switch v {
    case .int(let i): return String(i)
    case .str(let s): return pyRepr(s)
    case .list(let l): return "[" + l.map(pyRepr).joined(separator: ", ") + "]"
    }
}
/// Python repr() of an expression tuple (only used in diagnostics).
func pyRepr(_ e: ScriptExpr) -> String {
    switch e {
    case .num(let n): return "('num', \(n))"
    case .str(let s): return "('str', \(pyRepr(s)))"
    case .name(let s): return "('name', \(pyRepr(s)))"
    case .variable(let s): return "('var', \(pyRepr(s)))"
    case .const(let n): return "('const', \(n))"
    case .local(let i): return "('local', \(i))"
    case .mlocal(let s, let i): return "('mlocal', \(pyRepr(s)), \(i))"
    case .unary(let op, let a): return "('un', \(pyRepr(op)), \(pyRepr(a)))"
    case .binary(let op, let a, let b): return "('bin', \(pyRepr(op)), \(pyRepr(a)), \(pyRepr(b)))"
    case .within(let neg, let a, let l): return "('in', \(neg ? "True" : "False"), \(pyRepr(a)), \(pyRepr(l)))"
    case .call(let f, let a, _): return "('call', \(pyRepr(f)), [\(a.map(pyRepr).joined(separator: ", "))])"
    case .list(let l): return "('list', [\(l.map(pyRepr).joined(separator: ", "))])"
    case .defid(let n): return "('defid', \(n))"
    }
}

// MARK: code generation

final class SwitchCtx {
    let idx: Int
    var cases: [(ScriptExpr, Int)] = [], breaks: [Int] = []
    var defaultTarget: Int?, end = 0
    init(_ idx: Int) { self.idx = idx }
}

final class Ins {
    enum Op { case end, jz, jmp, `switch`, `break`, stmt }
    let op: Op
    var expr: ScriptExpr?            // JZ condition, SWITCH subject, BREAK argument
    var target = 0                   // JZ / JMP / BREAK destination
    var sw: SwitchCtx?               // SWITCH table; BREAK: the innermost switch it leaves
    let stmt: ScriptStmt?
    let ts: Int?, line: Int
    init(_ op: Op, _ expr: ScriptExpr? = nil, _ stmt: ScriptStmt? = nil) {
        self.op = op; self.expr = expr; self.stmt = stmt; ts = stmt?.ts; line = stmt?.line ?? 0
    }
}

public final class ScriptCode {
    public let block: ScriptBlock
    let ins: [Ins]
    let labels: [String: Int]
    let defidx: [Int: Int]

    init(_ block: ScriptBlock) {
        self.block = block
        var ins: [Ins] = [], labels: [String: Int] = [:], defidx: [Int: Int] = [:]
        var elseAt: [ObjectIdentifier: Int] = [:]      // IF -> where a false test of it (or of an IF wrapping it braceless) goes
        @discardableResult func emit(_ i: Ins) -> Int { ins.append(i); return ins.count - 1 }
        func gen(_ stmts: [ScriptStmt], _ sw: [SwitchCtx]) {
            for s in stmts {
                let here = ins.count
                switch s.op {
                case "LABEL":
                    let name = { if case .name(let n) = s.args[0] { return n.uppercased() }; return "" }()
                    if labels[name] == nil { labels[name] = here }
                    if let d = s.defid { defidx[d] = here }
                case "BLOCK": gen(s.then ?? [], sw)
                case "IF":
                    let jz = emit(Ins(.jz, s.args[0], s))
                    gen(s.then ?? [], sw)
                    if let els = s.els {
                        let jmp = emit(Ins(.jmp))
                        ins[jz].target = ins.count
                        elseAt[ObjectIdentifier(s)] = ins.count
                        gen(els, sw)
                        ins[jmp].target = ins.count
                    } else {
                        // a false IF skips one statement (10c0:0f78), and a nested IF is skipped without its ELSE; ELSE (10d0:27f9)
                        // runs iff the depth's last IF was false: `IF a THEN IF b THEN x ELSE y` runs y when a is false. See vm.py Code
                        let then = s.then ?? []
                        if then.count == 1, then[0].op == "IF", !s.braced, let target = elseAt[ObjectIdentifier(then[0])] {
                            ins[jz].target = target
                            elseAt[ObjectIdentifier(s)] = target
                        } else { ins[jz].target = ins.count }
                    }
                case "SWITCH":
                    let ctx = SwitchCtx(s.idx ?? 0)
                    let si = emit(Ins(.switch, s.args[0], s))
                    ins[si].sw = ctx
                    gen(s.then ?? [], sw + [ctx])
                    ctx.end = ins.count
                    if ctx.defaultTarget == nil { ctx.defaultTarget = ctx.end }
                    for i in ctx.breaks { ins[i].target = ctx.end }
                case "CASE", "DEFAULT":
                    guard let ctx = sw.last else { continue }
                    if s.op == "CASE" { ctx.cases.append((s.args[0], here)) } else { ctx.defaultTarget = here }
                    if let d = s.defid { defidx[d] = here }
                case "BREAK":
                    guard let ctx = sw.last else { continue }
                    let b = Ins(.break, s.args.first, s)
                    b.sw = ctx
                    ctx.breaks.append(emit(b))
                default: emit(Ins(.stmt, nil, s))
                }
            }
        }
        gen(block.body, [])
        ins.append(Ins(.end))
        self.ins = ins; self.labels = labels; self.defidx = defidx
    }
}

// MARK: processes

/// Context a new process inherits from its creator.
public struct ScriptContext {
    public var curFig: String?, curItem: String?, owner = "level"
    public init(curFig: String? = nil, curItem: String? = nil, owner: String = "level") { self.curFig = curFig; self.curItem = curItem; self.owner = owner }
}

public final class ScriptProcess {
    public unowned let vm: ScriptVM
    public let handle: Int
    public internal(set) var block: ScriptBlock
    var code: ScriptCode
    public internal(set) var pc = 0
    public var locals: [ScriptValue] = Array(repeating: .int(0), count: 10)
    public var curFig: String?, curItem: String?
    /// FINDFIRSTFIGURE / FINDNEXTFIGURE's position in the engine figure list (+0x42)
    var figIndex = 0
    /// 'global' (boot chain) or 'level': a label only, LOADLEVEL kills both
    public var owner = "level"
    /// Engine-installed predicate (blocking MOTION): the process sleeps until it is true.
    public var waitPred: (() -> Bool)?
    /// Engine-requested jump to a label of the current block (MON_JUMP).
    public var goto: String?
    /// Set by LOADLEVEL for a level-owned caller: finish after the current statement.
    public var ended = false
    /// the statement just run ends this slice
    var yieldNow = false
    /// +0xe83: the object whose destruction kills this process (SETREFERENT), set by the engine at spawn
    public var referent: AnyObject?
    public internal(set) var wake: Int
    public internal(set) var suspended = false, done = false
    public internal(set) var retval: ScriptValue = .int(0)
    var waitOn: ScriptProcess?
    var waiters: [ScriptProcess] = []
    var pending: [Int: ScriptProcess] = [:]        // CALL node id -> child process (blocked-in-expression CALLs)
    var loops: [ObjectIdentifier: Int] = [:]
    public internal(set) var origin: Int?          // timeline clock origin (tick), nil = not started
    var gen: (() -> Int?)?                         // native (VM-internal) process: ticks to sleep, nil when finished
    /// a MODIFYVAREVERYNTH ramp's state (the saved game's ramp task): the variable's current value, step, end, start, period
    var ramp: (value: () -> Int, step: Int, end: Int, start: Int, period: Int)?
    var jumpOn: (key: String, code: ScriptCode, pc: Int)?     // JUMPON watch (10d0:4024): the global variable and the label's place
    var scene = false                              // a RUNFLIC scene process (10c8:081b): dies when the flic is gone
    var hold: Int?                                 // tick in which a wake-up came during the walk (1230:177a, flag 0x40): skipped for that walk
    public internal(set) var cameras: [String] = []   // LINKMETOCAMERAS (10d0:4c72): every camera switch sets `suspended` unless the new camera is listed (10c0:5688)

    init(vm: ScriptVM, handle: Int, block: ScriptBlock, code: ScriptCode, ctx: ScriptContext?) {
        self.vm = vm; self.handle = handle; self.block = block; self.code = code
        if let ctx { curFig = ctx.curFig; curItem = ctx.curItem; owner = ctx.owner }
        wake = vm.tick
    }
    var context: ScriptContext { ScriptContext(curFig: curFig, curItem: curItem, owner: owner) }
    public var isWaiting: Bool { waitOn != nil }
}

/// Processes by handle in creation order (Python OrderedDict).
struct ProcessTable {
    private var map: [Int: ScriptProcess] = [:]
    private var order: [Int] = []
    subscript(h: Int) -> ScriptProcess? { map[h] }
    var values: [ScriptProcess] { order.compactMap { map[$0] } }
    mutating func add(_ p: ScriptProcess) { if map.updateValue(p, forKey: p.handle) == nil { order.append(p.handle) } }
    mutating func remove(_ h: Int) { if map.removeValue(forKey: h) != nil { order.removeAll { $0 == h } } }
}

enum Step { case next, yield, end, jump(ScriptCode, Int) }

// MARK: VM

public final class ScriptVM {
    public static let ticksPerSecond = 30
    static let forever = 1_000_000_000      // a native handle's sleep: it never runs again, only the engine finishes it
    static let sliceBudget = 100_000        // statements per slice before a runaway loop is forced to yield

    public let defs: ScriptDefs
    public let engine: ScriptEngine
    public var globals: [String: ScriptValue]
    public private(set) var objects: [String: [ScriptValue]] = [:]
    public private(set) var blocks: [String: ScriptBlock] = [:]
    public private(set) var files: [ScriptFile] = []
    var codes: [ObjectIdentifier: ScriptCode] = [:]
    var procs = ProcessTable()
    public private(set) var nextHandle = 1, tick = 0
    var walking = false                                              // a scheduler walk is under way ([989f])
    public private(set) var changes: [(tick: Int, name: String, old: ScriptValue, new: ScriptValue)] = []
    public private(set) var warnings: [String] = []
    public private(set) var duplicates: [(name: String, file: String, line: Int)] = []
    private var warned = Set<String>()

    public init(engine: ScriptEngine? = nil, defs: ScriptDefs) {
        self.defs = defs
        self.engine = engine ?? RecordingEngine()
        globals = defs.vars.mapValues { .int($0) }
        self.engine.attach(self)
    }

    public var processes: [ScriptProcess] { procs.values }
    public func process(_ handle: Int) -> ScriptProcess? { procs[handle] }
    public func stop(_ process: ScriptProcess) { finish(process) }
    public var objectKeys: [String] { Array(objects.keys) }
    public func objectRecord(_ key: String) -> [ScriptValue] { objects[key] ?? Array(repeating: .int(0), count: 10) }
    /// `key.~index += delta` (the engine's DAMAGE); a non-integer slot counts as 0.
    public func addToObject(_ key: String, _ index: Int, _ delta: Int) {
        var rec = objectRecord(key)
        rec[index] = .int(num(rec[index]) &+ delta)
        objects[key] = godGuarded(key, rec)
    }

    /// The object whose hit points (~0) may not fall (World.godMode: the player), or nil. Every write of an object record goes through `godGuarded`.
    var godKey: String?

    /// `rec` as it is to be stored under `key`: for the protected object a lower ~0 keeps the stored value (the other locals still change).
    private func godGuarded(_ key: String, _ rec: [ScriptValue]) -> [ScriptValue] {
        guard key == godKey, let old = objects[key], case .int(let was) = old[0], case .int(let now) = rec[0], now < was else { return rec }
        var kept = rec
        kept[0] = old[0]
        return kept
    }

    // ---- loading
    @discardableResult public func load(_ script: DecodedScript) -> ScriptFile {
        let f = ScriptParser.parse(script, defs: defs)
        files.append(f)
        for b in f.blocks {
            var k = b.name.uppercased()      // `{ FIRSTBOT_STIMULUS( _DAMAGE )` (no space) parses with the '(' in the name
            while k.hasSuffix("(") { k.removeLast() }
            if blocks[k] != nil { duplicates.append((k, f.name, b.line)) }      // GUESS: the first definition wins
            else { blocks[k] = b }
        }
        return f
    }

    /// Load the scripts listed in SCRIPT/<LEVEL>.LVL.
    @discardableResult public func loadLevel(_ level: String, library: ScriptLibrary) throws -> [ScriptFile] {
        var loaded: [ScriptFile] = []
        for w in try library.levelScripts(level) {
            if let s = library.script(named: w) { loaded.append(load(s)) } else { warn("\(w): not found in <scripts>") }
        }
        return loaded
    }

    /// Forget every loaded script file/block (level change). Globals and object state persist; running processes keep
    /// their own code, so they can still finish.
    public func unloadScripts() { blocks = [:]; files = []; codes = [:]; duplicates = [] }

    /// `p` and the processes CALLing it, innermost first (the context's +0x71 caller links).
    func callChain(_ p: ScriptProcess) -> [ScriptProcess] {
        var chain = [p]
        while let up = procs.values.first(where: { q in q.pending.values.contains { $0 === chain.last! } }),
              !chain.contains(where: { $0 === up }) {
            chain.append(up)
        }
        return chain
    }

    /// LOADLEVEL: stop every process except `caller` and its CALL chain (FUN_10b0_13fb, 10b0.c:1103-1160, run by 1148:14a3 with the
    /// caller: it kills every kernel task but the caller and the contexts on its +0x71 links, and a class-0x110 sound manager the ports
    /// do not model). There is no exemption for the boot chain: a process fired with owner 'global' dies like any other. `keep` is the
    /// sound handle LOADLEVEL's voice stop (FUN_1028_12d2) leaves playing: a voice is not a kernel task, so its handle process survives
    /// the walk. Killed processes are dropped without resuming their waiters. -> number killed. The caller's fate is decided after the
    /// load: `endUnloaded`.
    @discardableResult public func killLevelOwned(caller: ScriptProcess? = nil, keep: Int? = nil) -> Int {
        let spared = caller.map(callChain) ?? []
        var n = 0
        for q in procs.values where !spared.contains(where: { $0 === q }) && q.handle != keep {
            q.done = true; q.waiters = []; procs.remove(q.handle); n += 1
        }
        return n
    }

    /// The tail of LOADLEVEL (10d0:4d46 after 1148:15c7): the caller ends (vtable +8, return 2) when its script file record (context
    /// +0xe87, found by name through 1118:434d) has no loaded code (+0xd/+0xf), i.e. its file is not in the new level's .LVL; otherwise it
    /// continues after LOADLEVEL (ELEVATOR.scr:280 → EXITSTASIS, ENDGAME.scr:4 in TITLE). ASSUMPTION: a level-owned CALL ancestor whose
    /// file is gone is dropped the same way.
    public func endUnloaded(_ caller: ScriptProcess) {
        let loaded = Set(files.map { $0.name.uppercased() })
        for q in callChain(caller) where q.owner == "level" {
            guard let file = q.block.file, !loaded.contains(file.name.uppercased()) else { continue }
            if q === caller { q.ended = true }
            else { q.done = true; q.waiters = []; procs.remove(q.handle) }
        }
    }

    func code(_ block: ScriptBlock) -> ScriptCode {
        if let c = codes[ObjectIdentifier(block)] { return c }
        let c = ScriptCode(block)
        codes[ObjectIdentifier(block)] = c
        return c
    }
    /// Instruction count of a block's compiled code (diagnostics / tests).
    public func instructionCount(_ block: ScriptBlock) -> Int { code(block).ins.count }

    func warn(_ msg: String) {
        if warned.insert(msg).inserted { warnings.append("tick \(tick): \(msg)") }
    }

    // ---- processes
    @discardableResult public func spawn(_ name: ScriptValue, args: [ScriptValue] = [], ctx: ScriptContext? = nil, run: Bool = true,
                                         owner: String? = nil) -> ScriptProcess? {
        guard let b = blocks[pyStr(name).uppercased()] else { warn("unknown block \(pyRepr(name))"); return nil }
        let p = ScriptProcess(vm: self, handle: nextHandle, block: b, code: code(b), ctx: ctx)
        nextHandle += 1
        p.referent = (engine as? RecordingEngine)?.processReferent(p)
        if let owner, !owner.isEmpty { p.owner = owner }
        for (i, v) in args.prefix(10).enumerated() { if case .int = v { p.locals[i] = v } }   // args -> callee locals ~0..
        procs.add(p)
        if run { self.run(p) }                                          // first slice immediately
        return p
    }
    @discardableResult public func spawn(_ name: String, args: [ScriptValue] = [], ctx: ScriptContext? = nil, run: Bool = true,
                                         owner: String? = nil) -> ScriptProcess? {
        spawn(.str(name), args: args, ctx: ctx, run: run, owner: owner)
    }

    /// (Code, instruction index) of the first statement of `block` that starts at or after byte `offset` of its tokenized .SCP
    /// source (a saved process's pc); the END instruction when the block has none left.
    public func locate(_ block: ScriptBlock, offset: Int) -> Int {
        let code = self.code(block)
        var first: [ObjectIdentifier: Int] = [:]
        for (k, i) in code.ins.enumerated() { if let s = i.stmt, first[ObjectIdentifier(s)] == nil { first[ObjectIdentifier(s)] = k } }
        for (st, b) in block.file?.statements(from: offset) ?? [] {
            if b !== block { break }
            if let k = first[ObjectIdentifier(st)] { return k }       // labels / CASE markers emit no instruction: fall through
        }
        return code.ins.count - 1
    }

    /// Register a process with an explicit handle (restored from a save: handles are task serials) positioned at instruction
    /// `index`; it does not run until the next tick. Later handles continue above it.
    @discardableResult public func adopt(_ block: ScriptBlock, index: Int, handle: Int, ctx: ScriptContext? = nil) -> ScriptProcess {
        let p = ScriptProcess(vm: self, handle: handle, block: block, code: code(block), ctx: ctx)
        p.pc = index
        procs.add(p)
        nextHandle = max(nextHandle, handle + 1)
        return p
    }

    // ---- resume of a saved game (Resume.swift)

    func setObject(_ key: String, _ rec: [ScriptValue]) { objects[key] = godGuarded(key, rec) }
    /// Later handles continue at or above `next` (MISC.DAT's next task serial).
    func reserveHandles(upTo next: Int) { nextHandle = max(nextHandle, next) }

    /// A saved MODIFYVAREVERYNTH task (resume.py `_ramp`): the variable `target` currently holds `value`; the next step comes after
    /// `left` ticks, then every `period` ticks, until it reaches `end`.
    @discardableResult
    func adoptRamp(handle: Int, target: ScriptExpr, value: Int, left: Int, step: Int, end: Int, period: Int) -> ScriptProcess {
        let b = ScriptBlock("MODIFYVAREVERYNTH", "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: handle, block: b, code: ScriptCode(b), ctx: nil)
        var v = value, wait = left, first = true
        c.gen = { [unowned self, unowned c] in
            if !first { wait = period; v &+= step; assign(c, target, .int(v)) }
            first = false
            return v != end && (v &- end) &* step < 0 ? max(wait, 1) : nil
        }
        procs.add(c)
        run(c)
        return c
    }

    /// A saved TIMED native process (resume.py `_timed`): a subtitle / sound handle under the task's serial, valid for `ticks` more ticks.
    func adoptTimed(handle: Int, ticks: Int) -> ScriptProcess {
        let b = ScriptBlock("TIMED", "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: handle, block: b, code: ScriptCode(b), ctx: nil)
        var fired = false
        c.gen = { if fired { return nil }; fired = true; return max(ticks, 1) }
        procs.add(c)
        run(c)
        return c
    }

    /// Engine event: start block `name` as a detached process if it exists. -> handle or nil. `owner` is a label only ('global' marks the
    /// boot chain, which everything it CALLs/PROCESSes inherits); LOADLEVEL kills both alike.
    @discardableResult public func fire(_ name: String, owner: String = "level") -> Int? { spawn(name, owner: owner)?.handle }

    /// Start block `name` at `label` (engine-dispatched entry such as HIT_PLAYER_ATK_SYRINGE).
    @discardableResult public func spawnAt(_ name: String, label: String, args: [ScriptValue] = [], ctx: ScriptContext? = nil,
                                           owner: String? = nil) -> ScriptProcess? {
        guard let b = blocks[name.uppercased()], let target = code(b).labels[label.uppercased()],
              let p = spawn(name, args: args, ctx: ctx, run: false, owner: owner) else { return nil }
        p.pc = target
        run(p)
        return p
    }

    func finish(_ p: ScriptProcess) {
        if p.done { return }
        p.done = true
        procs.remove(p.handle)
        let ws = p.waiters
        p.waiters = []
        for w in ws where w.waitOn === p && !w.done {                // 1238:077f clears the waiter's wait list; nothing runs it here
            w.waitOn = nil
            if walking { w.hold = tick }                             // 1230:177a: a task woken during a walk sits it out (flag 0x40); one
        }                                                            // already passed would not be reached again either -> next walk
    }

    public func tickOnce() {
        if engine.paused { return }                                  // options dialog: scheduler and clock stand still
        walking = true                                               // [989f] (1230:0259)
        for p in procs.values {
            if p.done || p.suspended || p.hold == tick { continue }  // hold: 0x40, tested before the task's update (1230.c:173)
            if p.scene && !engine.sceneAlive { finish(p); continue }   // 10c8:081b: no flic (or a finished one): ends before running anything
            if p.jumpOn != nil && watchFires(p) { run(p); continue }   // 10c0:2626: polled at every update, also while waiting
            if p.waitOn != nil || p.wake > tick { continue }
            if let pred = p.waitPred {
                if !pred() { continue }
                p.waitPred = nil
            }
            run(p)
        }
        (engine as? RecordingEngine)?.endOfWalk()                    // idle motion tasks made in the last walk run in this one (World.requestIdle)
        walking = false
        tick += 1
    }

    public func runTicks(_ n: Int) { for _ in 0..<n { tickOnce() } }

    /// The JUMPON poll (10c0:2626): when the watched global is non-zero the registration is cleared (one-shot), a pending wait is cancelled (also
    /// the waited-on process's waiters entry) and the process continues at the label. Level-triggered; the variable is not reset. -> true if it jumped.
    func watchFires(_ p: ScriptProcess) -> Bool {
        guard let w = p.jumpOn, truth(globals[w.key] ?? .int(0)) else { return false }
        p.jumpOn = nil
        if let t = p.waitOn { t.waiters.removeAll { $0 === p }; p.waitOn = nil }
        p.waitPred = nil
        p.code = w.code; p.pc = w.pc; p.block = w.code.block; p.wake = tick
        return true
    }

    /// `JUMPON <VAR> <LABEL>` (10d0:4024): watch global `_VAR`, jump to LABEL of the current block. A later one replaces it. Warnings (registration
    /// cleared): no label (0x29), no variable (6), unknown variable (0x17), unknown label (0x11).
    func jumpOn(_ p: ScriptProcess, _ args: [ScriptValue]) {
        var words: [String] = []
        for case .str(let w) in args { words.append(w) }
        let v = words.first ?? "", label = words.count > 1 ? words[1] : ""
        let key = "_" + v.lowercased()
        p.jumpOn = nil
        if label.isEmpty { warn("JUMPON: needs a label (error 0x29)") }
        else if v.isEmpty { warn("JUMPON: needs a variable (error 6)") }
        else if globals[key] == nil { warn("JUMPON \(v): unknown variable (error 0x17)") }
        else if let pc = p.code.labels[label.uppercased()] { p.jumpOn = (key, p.code, pc) }
        else { warn("JUMPON \(v) \(label): unknown label (error 0x11)") }
    }

    func run(_ p: ScriptProcess) {
        if let gen = p.gen {
            if let t = gen() { p.wake = tick + t } else { finish(p) }
            return
        }
        var budget = Self.sliceBudget
        while !p.done {
            if p.jumpOn != nil { _ = watchFires(p) }                 // ... and before every statement
            budget -= 1
            if budget == 0 {
                warn("\(p.block.name): statement budget exhausted (runaway loop?), forcing a yield")
                p.wake = tick + 1
                return
            }
            let ins = p.code.ins[p.pc]
            if let ts = ins.ts {                                     // timeline: wait for the local clock
                if p.origin == nil { p.origin = tick }               // GUESS: clock starts at the first timed line / after RESETREALTIME
                if tick - p.origin! < ts { p.wake = p.origin! + ts; return }
            }
            let r: Step
            do { r = try step(p, ins) } catch { return }             // Blocked
            switch r {
            case .yield: return
            case .end: finish(p); return
            default: break
            }
        }
    }

    // ---- execution
    func step(_ p: ScriptProcess, _ ins: Ins) throws -> Step {
        var nxt = p.pc + 1
        switch ins.op {
        case .end: return .end
        case .jz: if !truth(try eval(p, ins.expr!)) { nxt = ins.target }
        case .jmp: nxt = ins.target
        case .switch:
            let v = try eval(p, ins.expr!)
            nxt = ins.sw!.defaultTarget!
            for (e, idx) in ins.sw!.cases {
                if try eval(p, e) == v { nxt = idx; break }
            }
        case .break:
            // FUN_10d0_0b77: BREAK n jumps past the file's n-th SWITCH, the number the compiler wrote in, always the innermost one
            // (FUN_10c0_01cc). An inline `IF ... THEN BREAK` never got a number (the compiler only reads a line's first statement),
            // and an empty operand is ERR_BREAK_NOT_PREPROCESSED: the statement does nothing and the next one runs.
            if let n = ins.expr {
                if try eval(p, n) != .int(ins.sw!.idx) {
                    warn("\(p.block.name):\(ins.line): BREAK \(pyStr(try eval(p, n))) != innermost switch index \(ins.sw!.idx)")
                }
                nxt = ins.target
            }
        case .stmt:
            let r = try stmt(p, ins.stmt!, ins)
            switch r {
            case .jump(let c, let pc):
                p.code = c; p.pc = pc
                if c.block !== p.block { p.block = c.block }
                if p.waitPred != nil {                               // jump and yield (MON_JUMP on a button event)
                    p.wake = tick + 1
                    return .yield
                }
                return .next
            case .end: return .end
            default:
                p.pc = nxt
                return r
            }
        }
        p.pc = nxt
        return .next
    }

    func stmt(_ p: ScriptProcess, _ s: ScriptStmt, _ ins: Ins) throws -> Step {
        let a = s.args
        switch s.op {
        case "ASSIGN":
            var v = try eval(p, a[1])
            if s.aop != "=" {
                let cur = num(try eval(p, a[0])), r = num(v)
                switch s.aop {
                case "+=", "++": v = .int(cur &+ r)
                case "-=", "--": v = .int(cur &- r)
                case "*=": v = .int(cur &* r)
                default: v = .int(idiv(cur, r))                  // "/="
                }
            }
            assign(p, a[0], v)
        case "EXPR": _ = try eval(p, a[0])
        case "WAIT":
            var n = num(try eval(p, a[0]))
            if a.count > 1, case .name(let unit) = a[1], ["SECOND", "SECONDS"].contains(unit.uppercased()) { n &*= Self.ticksPerSecond }
            p.wake = tick + max(n, 1)
            return .yield
        case "SUSPEND":
            p.wake = tick + 1
            return .yield
        case "SUSPENDWHILE":
            if case .int(let h) = try eval(p, a[0]), let t = procs[h], !t.done {
                p.waitOn = t
                t.waiters.append(p)
                p.pc += 1                                       // resume after the statement
                throw Blocked()
            }
        case "RETURN":
            p.retval = a.isEmpty ? .int(0) : try eval(p, a[0])
            return .end
        case "JUMP":
            if let (c, pc) = jump(p, a[0], ins) { return .jump(c, pc) }
        case "LOOP":
            if a.count < 2 { if let (c, pc) = jump(p, a[0], ins) { return .jump(c, pc) }; return .next }   // GUESS: LOOP without count = jump
            let n = num(try eval(p, a[1]))
            let key = ObjectIdentifier(ins)
            let c = (p.loops[key] ?? 0) + 1
            if c < n {
                p.loops[key] = c
                if let (code, pc) = jump(p, a[0], ins) { return .jump(code, pc) }
            } else { p.loops[key] = nil }                       // GUESS: counter resets when the loop completes
        case "LOCALVAR":
            if let i = s.initial { assign(p, a[0], try eval(p, i)) }   // GUESS: `LOCALVAR ~0 = v` initialises
        case "KILLPROCESS":
            if case .int(let h) = try eval(p, a[0]), let t = procs[h] { finish(t) }
        case "SUSPENDPROCESS", "RESUMEPROCESS":
            if case .int(let h) = try eval(p, a[0]), let t = procs[h] { t.suspended = s.op == "SUSPENDPROCESS" }
        case "JUMPON":
            let args = try a.map { x -> ScriptValue in if case .name(let n) = x { return .str(n) }; return try eval(p, x) }
            _ = engine.call(.stmt, s.op, args, p)               // logged like every statement; the watch itself is the VM's
            jumpOn(p, args)
        case "RESETREALTIME": p.origin = nil
        case "SETFLAG", "CLEARFLAG", "TOGGLEFLAG":
            // GUESS: flag bit n of a variable is 1 << n; `SETFLAG (v, bit) = 1` extra value ignored
            let cur = num(try eval(p, a[0])), bit = 1 << num(try eval(p, a[1]))
            assign(p, a[0], .int(s.op == "SETFLAG" ? cur | bit : s.op == "CLEARFLAG" ? cur & ~bit : cur ^ bit))
        default:
            _ = engine.call(.stmt, s.op, try a.map { try eval(p, $0) }, p)
            if p.ended { return .end }
            if p.yieldNow {                                     // AI OFF on the process's own figure (10d0:04b3 returns 1)
                p.yieldNow = false
                return .yield
            }
            let label = p.goto
            p.goto = nil
            if let label, let target = p.code.labels[label] { return .jump(p.code, target) }
            if p.waitPred != nil {                              // engine asked to block this process
                p.wake = tick + 1
                return .yield
            }
        }
        return .next
    }

    /// Same block first; then block names; then labels of other blocks in the file.
    func jump(_ p: ScriptProcess, _ node: ScriptExpr, _ ins: Ins) -> (ScriptCode, Int)? {
        let here = "\(p.block.name):\(ins.line)"
        if case .defid(let id) = node {
            guard let owner = p.code.block.file?.defs[id] else { warn("\(here): JUMP #\(id) unresolved; ignored"); return nil }
            let c = code(owner)
            return (c, c.defidx[id] ?? 0)
        }
        var name: String?
        if case .name(let n) = node { name = n.uppercased() }
        if let name {
            if let l = p.code.labels[name] { return (p.code, l) }
            if name == p.code.block.name.uppercased() { return (p.code, 0) }
            if let b = blocks[name] {
                warn("\(here): JUMP \(name) targets another block")
                return (code(b), 0)
            }
            for b in p.code.block.file?.blocks ?? [] {
                let c = code(b)
                if let l = c.labels[name] {
                    warn("\(here): JUMP \(name) targets a label in block \(b.name)")
                    return (c, l)
                }
            }
        }
        warn("\(here): JUMP \(pyRepr(secondItem(node))) unresolved; ignored")
        return nil
    }

    /// `node[1]` of the prototype's expression tuple.
    private func secondItem(_ e: ScriptExpr) -> ScriptValue {
        switch e {
        case .num(let n), .const(let n), .local(let n), .defid(let n): return .int(n)
        case .str(let s), .name(let s), .variable(let s), .mlocal(let s, _), .unary(let s, _), .binary(let s, _, _), .call(let s, _, _): return .str(s)
        case .within(let neg, _, _): return .int(neg ? 1 : 0)
        case .list(let l): return .list(l.map(secondItem))
        }
    }

    // ---- variables
    /// Key into `objects` for `CURFIG.~n` / `CURITEM.~n` / `NAME.~n` (FUN_10c0_24e1). An unset CURFIG / CURITEM is error 0x6f in the
    /// engine; here it falls to a placeholder record named after the selector. The engine may map names further (PLAYER -> the
    /// flagged player figure) with objectKey().
    func objectName(_ p: ScriptProcess, _ sel: String) -> String {
        var n: String? = sel
        if sel == "CURFIG" { n = p.curFig }
        else if sel == "CURITEM" { n = p.curItem }
        return engine.objectKey(n.flatMap { $0.isEmpty ? nil : $0 } ?? sel)
    }

    /// INDIVIDUALIZE: an object's locals live in the object itself (10c0:24e1 addresses them at +0x92 + 4n), so its record follows the
    /// new name (a record already under `new` is replaced).
    public func renameObject(_ old: String, to new: String) {
        if let rec = objects.removeValue(forKey: old) { objects[new] = rec }
        else { objects.removeValue(forKey: new) }             // the item had no locals yet: it must not inherit a dead item's record
    }

    /// A new object starts with zeroed locals, not those of a destroyed one.
    func removeObject(_ key: String) { objects.removeValue(forKey: key) }

    /// Every live script process (INDIVIDUALIZE re-points their CURITEM).
    var allProcesses: [ScriptProcess] { procs.values }

    func assign(_ p: ScriptProcess, _ tgt: ScriptExpr, _ v: ScriptValue) {
        switch tgt {
        case .local(let i): p.locals[i] = v
        case .mlocal(let sel, let i):
            let key = objectName(p, sel)
            var rec = objects[key] ?? Array(repeating: .int(0), count: 10)
            rec[i] = v
            objects[key] = godGuarded(key, rec)
        case .variable(let n), .name(let n):
            let name = n.lowercased()
            let old = globals[name] ?? .int(0)
            globals[name] = v
            if old != v { changes.append((tick, name, old, v)) }
        default: warn("\(p.block.name): cannot assign to \(pyRepr(tgt))")
        }
    }

    // ---- expressions
    func eval(_ p: ScriptProcess, _ e: ScriptExpr) throws -> ScriptValue {
        switch e {
        case .num(let n), .const(let n): return .int(n)
        case .str(let s), .name(let s): return .str(s)
        case .variable(let n): return globals[n] ?? .int(0)
        case .local(let i): return p.locals[i]
        case .mlocal(let sel, let i):
            let key = objectName(p, sel)
            if objects[key] == nil { objects[key] = Array(repeating: .int(0), count: 10) }
            return objects[key]![i]
        case .list(let items): return .list(try items.map { try eval(p, $0) })
        case .unary(_, let a): return .int(0 &- num(try eval(p, a)))
        case .within(let neg, let a, let l):
            let v = try eval(p, a)
            var lst = try eval(p, l)
            if case .list = lst {} else { lst = .list([lst]) }
            guard case .list(let items) = lst else { return .int(0) }
            // `x IN lo, hi` is an inclusive range in every use in the corpus (angles, COMPASS); other list lengths:
            // GUESS plain membership
            var r: Bool
            if items.count == 2, case .int(let lo) = items[0], case .int(let hi) = items[1] { r = lo <= num(v) && num(v) <= hi }
            else { r = items.contains(v) }
            return .int(r != neg ? 1 : 0)
        case .binary(let op, let l, let r):
            if op == "OR" { return try .int(truth(eval(p, l)) || truth(eval(p, r)) ? 1 : 0) }
            if op == "AND" { return try .int(truth(eval(p, l)) && truth(eval(p, r)) ? 1 : 0) }
            let x = try eval(p, l), y = try eval(p, r)
            if op == "==" { return .int(x == y ? 1 : 0) }
            if op == "!=" { return .int(x != y ? 1 : 0) }
            let a = num(x), b = num(y)
            switch op {
            case "<": return .int(a < b ? 1 : 0)
            case ">": return .int(a > b ? 1 : 0)
            case "<=": return .int(a <= b ? 1 : 0)
            case ">=": return .int(a >= b ? 1 : 0)
            case "+": return .int(a &+ b)
            case "-": return .int(a &- b)
            case "*": return .int(a &* b)
            case "/": return .int(idiv(a, b))
            default: return .int(b != 0 ? a &- b &* idiv(a, b) : 0)       // "%"
            }
        case .call(let name, let a, let id): return try call(p, name, a, id)
        case .defid: fatalError("bad expression \(e)")
        }
    }

    func call(_ p: ScriptProcess, _ name: String, _ a: [ScriptExpr], _ id: Int) throws -> ScriptValue {
        switch name {
        case "CALL", "PROCESS":
            guard let first = a.first else { return .int(0) }
            var bname: ScriptValue
            if case .name(let n) = first { bname = .str(n) } else { bname = try eval(p, first) }
            var rest = Array(a.dropFirst())
            if rest.count == 1, case .list(let items) = rest[0] { rest = items }  // `CALL ( NAME( a, b ) )`: the list is the argument list
            if name == "PROCESS" {
                // FUN_10c0_37e9 (10c0.c:2962-3027) runs the child's first slice only when the caller's block is a `{` routine; from a `[`
                // timeline block the child waits for the scheduler (CALL, 10c0:3968, always runs it). The task constructor (1238.c:154,
                // 1230:177a) holds a task created during a walk for the rest of it, so the child first runs in the next walk, as here.
                let c = spawn(bname, args: try rest.map { try eval(p, $0) }, ctx: p.context, run: p.block.kind == "routine")
                return .int(c?.handle ?? 0)
            }
            var c = p.pending[id]                               // resumed after blocking?
            if c == nil {
                c = spawn(bname, args: try rest.map { try eval(p, $0) }, ctx: p.context, run: false)
                if c == nil { return .int(0) }
                p.pending[id] = c                               // the +0x71 link exists before the child's first slice: a LOADLEVEL in it spares the caller
                run(c!)
            }
            if let c, !c.done {
                p.pending[id] = c
                p.waitOn = c
                c.waiters.append(p)
                throw Blocked()
            }
            p.pending[id] = nil
            return c!.retval
        case "ISPROCESSVALID":
            let h = a.isEmpty ? ScriptValue.int(0) : try eval(p, a[0])
            if case .int(let i) = h { return .int(procs[i] != nil ? 1 : 0) }
            return .int(0)
        case "MODIFYVAREVERYNTH": return try modifyVar(p, a)
        case "GETFLAG":
            guard a.count >= 2 else { return .int(0) }
            return .int((num(try eval(p, a[0])) >> num(try eval(p, a[1]))) & 1)      // GUESS: bit n = 1 << n
        default: break
        }
        var args: [ScriptValue] = try a.map { x in if case .name(let n) = x { return .str(n) }; return try eval(p, x) }
        // RUNFLIC's optional third argument is a live script variable, not a value snapshot.
        if name == "RUNFLIC", a.count >= 3, case .variable(let variable) = a[2], engine is World { args.append(.str(variable)) }
        let prev = p.curFig
        if name == "SETCURRENTFIGURE", let f = args.first {
            p.curFig = pyStr(f).uppercased()
            if p.curFig == "ENEMY", let e = engine.enemy(of: prev), !e.isEmpty { p.curFig = e }   // ENEMY = the previous figure's enemy
        } else if name == "SETCURRENTITEM", let f = args.first, !(engine is World) {
            p.curItem = pyStr(f).uppercased()           // a stub engine: the literal; an engine that models 10c0:3fd9 decides itself
        }
        return engine.call(.function, name, args, p)
    }

    /// A native process that stays valid for `ticks` ticks (SUBTITLE / sound handles). -> handle
    public func timedHandle(ticks: Int, owner: String = "level") -> Int {
        let b = ScriptBlock("TIMED", "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: nextHandle, block: b, code: ScriptCode(b), ctx: nil)
        c.owner = owner
        nextHandle += 1
        var fired = false
        c.gen = { if fired { return nil }; fired = true; return max(ticks, 1) }
        procs.add(c)
        run(c)
        return c.handle
    }

    /// A native process that stays valid until the engine finishes it (a missile's handle: the original task serial, valid until the
    /// task is destroyed). Finishing it wakes the SUSPENDWHILE waiters like any process. -> handle
    public func nativeHandle(_ name: String, owner: String = "level") -> Int {
        let b = ScriptBlock(name, "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: nextHandle, block: b, code: ScriptCode(b), ctx: nil)
        c.owner = owner
        nextHandle += 1
        var fired = false
        c.gen = { if fired { return nil }; fired = true; return Self.forever }
        procs.add(c)
        run(c)
        return c.handle
    }

    /// A native process under `handle` that never runs again (a missile's handle restored from a save, as nativeHandle makes it).
    func adoptNative(_ name: String, handle: Int) -> ScriptProcess {
        let b = ScriptBlock(name, "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: handle, block: b, code: ScriptCode(b), ctx: nil)
        c.owner = "level"
        var fired = false
        c.gen = { if fired { return nil }; fired = true; return Self.forever }
        procs.add(c)
        run(c)
        return c
    }

    /// A native process driven by `gen` (ticks to sleep, nil when finished): the OVERTIME ramps. -> handle
    public func nativeGenerator(_ name: String, owner: String = "level", _ gen: @escaping () -> Int?) -> Int {
        let b = ScriptBlock(name, "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: nextHandle, block: b, code: ScriptCode(b), ctx: nil)
        c.owner = owner
        nextHandle += 1
        c.gen = gen
        procs.add(c)
        run(c)
        return c.handle
    }

    /// An engine write of a script global (as `assign`).
    func setGlobal(_ name: String, _ v: ScriptValue) {
        let name = name.lowercased()
        let old = globals[name] ?? .int(0)
        globals[name] = v
        if old != v { changes.append((tick, name, old, v)) }
    }

    /// MODIFYVAREVERYNTH(var, step, start, end, n): native process. GUESS: var = start now, then var += step every n ticks until
    /// var == end.
    func modifyVar(_ p: ScriptProcess, _ a: [ScriptExpr]) throws -> ScriptValue {
        guard a.count >= 5 else { return .int(0) }
        let tgt = a[0]
        let vals = try a[1..<5].map { num(try eval(p, $0)) }
        let (step, start, end, n) = (vals[0], vals[1], vals[2], vals[3])
        let b = ScriptBlock("MODIFYVAREVERYNTH", "native", 0, nil)
        let c = ScriptProcess(vm: self, handle: nextHandle, block: b, code: ScriptCode(b), ctx: p.context)
        nextHandle += 1
        var v = start, started = false
        c.gen = { [unowned self] in
            if started { v &+= step } else { started = true }
            assign(p, tgt, .int(v))
            return v != end && (v &- end) &* step < 0 ? max(n, 1) : nil
        }
        c.ramp = ({ v }, step, end, start, n)
        procs.add(c)
        run(c)
        return .int(c.handle)
    }
}
