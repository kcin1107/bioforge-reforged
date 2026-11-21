// Opt-in randomized "monkey" soft-lock test (MONKEY=1): at each of the full run's 30 save points, mash keys the way a human does (quick double
// presses of I/P/D/J/Space/O/Escape, held modifiers, clicks in monitors), let go of everything, and check that Lex can be made to move again.
// Keys and clicks go through the app's own routing (BioForgeHost's InputRouter, with the default bindings), as the keys a player presses.
// Best in a release build: `MONKEY=1 swift test -c release --filter MonkeyTests`.
//   MONKEY_TRIALS=<n> trials per leg (40); MONKEY_LEG=<leg> only that leg; MONKEY_TRIAL=<i> only that trial;
//   MONKEY_LOG=1 prints the event log of the trial(s) that run. Outcomes go to re/out/monkey/<leg>.jsonl; the saves are cached in
//   re/out/monkey_saves/<leg>/ (delete that folder after the engine's save format changes).
import Foundation
import Testing
@testable import BioForgeCore
import BioForgeHost

private let env = ProcessInfo.processInfo.environment
private let outDir = repoRoot.appendingPathComponent("re/out")

/// The legs (names of the full run's `save_check` ops), in run order.
private let monkeyLegs: [String] = {
    guard let url = Bundle.module.url(forResource: "full_run", withExtension: "json"),
          let data = try? JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any], let ops = data["ops"] as? [[Any]] else { return [] }
    let names = ops.filter { $0[1] as? String == "save_check" }.map { $0[2] as! String }
    return env["MONKEY_LEG"].map { leg in names.filter { $0 == leg } } ?? names
}()

/// The 30 saves (one unpacked save folder per leg), made once by replaying the full run; a lazily initialised global is thread safe.
private let monkeySaves: Result<[String: URL], MonkeyError> = {
    do {
        let fm = FileManager.default, root = outDir.appendingPathComponent("monkey_saves")
        let url = try #require(Bundle.module.url(forResource: "full_run", withExtension: "json"))
        let data = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let ops = data["ops"] as! [[Any]], end = (data["checkpoints"] as! [[String: Any]]).last!["tick"] as! Int
        let legs = ops.filter { $0[1] as! String == "save_check" }.map { $0[2] as! String }
        var saves = Dictionary(uniqueKeysWithValues: legs.map { ($0, root.appendingPathComponent($0)) })
        if saves.values.allSatisfy({ fm.fileExists(atPath: $0.path) }) { return .success(saves) }
        let s = try GameSession.newGame(resources: try #require(worldResources))
        s.world.recordLog = false
        var next = 0
        while ops.indices.contains(next), ops[next][0] as! Int == -1 { next += 1 }
        func apply(_ op: [Any]) throws {
            try FullRunReplay.apply(op, s) { op in
                let leg = op[2] as! String, dir = tempDir()
                defer { try? fm.removeItem(at: dir) }
                guard let target = saves[leg], !fm.fileExists(atPath: target.path) else { return }
                s.world.savesDir = dir
                defer { s.world.savesDir = nil }
                let file = try #require(s.world.saveNative(slot: 1))
                let part = root.appendingPathComponent(leg + ".part")
                try? fm.removeItem(at: part)
                try fm.createDirectory(at: root, withIntermediateDirectories: true)
                try Im1.unpack(try fileBytes(file), to: part)
                try fm.moveItem(at: part, to: target)
            }
        }
        while s.vm.tick < end {
            while next < ops.count, ops[next][0] as! Int == s.vm.tick { try apply(ops[next]); next += 1 }
            s.tick()
        }
        while next < ops.count { try apply(ops[next]); next += 1 }
        return .success(saves)
    } catch { return .failure(MonkeyError(text: "\(error)")) }
}()

private struct MonkeyError: Error { let text: String }

/// Key scans the monkey presses (0x01 is Escape as the app routes it).
private let monkeyKeys = [0x48, 0x50, 0x4b, 0x4d, 0x47, 0x49, 0x4f, 0x51, 0x4c, 0x17, 0x19, 0x20, 0x24, 0x1f, 0x18, 0x01, 0x1c, 0x39, 0x2e, 0x13]
private let doubleKeys = [0x17, 0x19, 0x20, 0x24, 0x39, 0x18, 0x01]
/// Modifier keys (shift, ctrl, alt) and the PC flags they raise.
private let modifierFlags = [0x2a: Keys.shift, 0x1d: Keys.ctrl, 0x38: Keys.alt]
/// The key (HID usage) a player presses for each scan, with the default bindings: the control's primary key, Escape for 0x01, and the
/// left Shift / Control / Option keys for the modifiers (Control, not A: a modifier key arrives as a modifier change, as on the Mac).
private let monkeyUsages: [Int: UInt16] = {
    var u: [Int: UInt16] = [0x01: 0x29, 0x2a: 0xE1, 0x1d: 0xE0, 0x38: 0xE2]
    let b = KeyBindings()
    for c in KeyBindings.controls { if case .scan(let scan) = c.output, u[scan] == nil, let k = b.key(c.id, slot: 0) { u[scan] = k } }
    return u
}()

/// One trial: a session loaded from a save and the monkey's input, routed like the app's.
private final class Monkey {
    let w: World, s: GameSession
    let input = InputRouter()                              // the app's routing, default bindings
    var held: [Int] = []                                   // keys and modifier keys the monkey holds down (as scans)
    var events: [String] = []
    var tick = 0
    init(_ s: GameSession) { self.s = s; w = s.world }

    func advance(_ n: Int = 1) {
        for _ in 0..<n {
            s.tick(); tick += 1
            // MONKEY_TRACE=a-b prints the player each tick of that range (with MONKEY_LEG / MONKEY_TRIAL), to follow a stuck trial.
            if let r = Self.trace, r.contains(tick), let p = w.player {
                print("TR \(tick) \(w.level) \(p.pos.map { "\(Int($0.x)),\(Int($0.y)),\(Int($0.z))" } ?? "-") falling \(p.falling) vz \(p.vz) noCollide \(p.noCollide) gravity \(p.gravity) hold \(p.hold) \(p.motion ?? "-")")
            }
        }
    }
    static let trace: ClosedRange<Int>? = ProcessInfo.processInfo.environment["MONKEY_TRACE"].flatMap { v in
        let b = v.split(separator: "-").compactMap { Int($0) }
        return b.count == 2 ? b[0]...b[1] : nil
    }

    /// A key event as the app routes it: the scan's key (monkeyUsages) through InputRouter.handleKey; a modifier key as a modifier change.
    func route(_ scan: Int, down: Bool) {
        if down { if !held.contains(scan) { held.append(scan) } } else { held.removeAll { $0 == scan } }
        events.append("t\(tick) \(down ? "down" : "up") 0x\(String(scan, radix: 16))\(w.keyboardCaptured ? " (captured)" : w.flicOpen ? " (flic)" : w.isOptionsOpen ? " (options)" : w.isMonitorRunning ? " (monitor)" : "")")
        guard let usage = monkeyUsages[scan] else { return }
        let key = modifierFlags[scan] != nil ? KeyEvent(usage: usage, kind: .modifiers, modifierDown: down) : KeyEvent(usage: usage, kind: down ? .down : .up)
        input.handleKey(key, world: w)
    }

    /// A click (down, then up later) at a game pixel, as the app routes the mouse.
    func pointer(_ phase: PointerPhase, x: Int? = nil, y: Int? = nil) { input.handlePointer(x: x, y: y, phase: phase, world: w) }

    func press(_ scan: Int, ticks: Int) { route(scan, down: true); advance(ticks); route(scan, down: false) }

    var player: Figure? { w.player }
    var hitPoints: Int {
        guard let p = player, case .int(let hp)? = s.vm.objectRecord(w.objectKey(p.name)).first else { return 1 }
        return hp
    }
    var died: Bool { hitPoints < 0 }
    /// Lex is free: no dialog, monitor or flic is up and he is not held by a script (AI OFF), falling or moving vertically. A captured keyboard
    /// does not count against it (the zero-G room captures it by design); `ok_captured` marks that state.
    var free: Bool {
        !w.isOptionsOpen && !w.isMonitorRunning && !w.flicOpen && (player.map { $0.hold == 0 && !$0.falling && $0.vz == 0 } ?? true)
    }
    var state: String {
        let p = player
        return "hold \(p?.hold ?? 0) monitor \(w.monitor?.name ?? "-") options \(w.isOptionsOpen) flic \(w.flicOpen) captured \(w.keyboardCaptured) falling \(p?.falling ?? false) vz \(p?.vz ?? 0) "
            + "pos \(p?.pos.map { "\(Int($0.x)),\(Int($0.y)),\(Int($0.z))" } ?? "-") gravity \(p?.gravity ?? false) area \(p?.area.map(String.init) ?? "-") "
            + "motion \(p?.motion ?? "-") level \(w.level) camera \(w.currentCamera ?? "-") scripts \(s.vm.processes.filter { !$0.done }.map { $0.block.name })"
            + (ProcessInfo.processInfo.environment["MONKEY_PROCS"] != nil ? " " + s.vm.processes.filter { !$0.done }.map { "\($0.block.name) pc \($0.pc) wake \($0.wake) susp \($0.suspended) origin \($0.origin.map(String.init) ?? "-") waitPred \($0.waitPred != nil) waitOn \($0.waitOn?.block.name ?? "-") cur \($0.curFig ?? "-")" }.joined(separator: "; ") + " tick \(s.vm.tick) coordz \(w.player.flatMap { $0.pos }.map { cmFromUnits(Int($0.z)) } ?? 0)" : "")
    }
}

private struct Outcome {
    var leg: String, trial: Int, seed: Int, outcome: String, detail = "", events: [String] = []
}

/// Future input: a key (or modifier) going down or up, or the mouse button going up.
private enum Scheduled { case down(Int), up(Int), mouseUp }

private func runTrial(leg: String, trial: Int, saves: [String: URL]) throws -> Outcome {
    var h: UInt64 = 14695981039346656037
    for b in leg.utf8 { h = (h ^ UInt64(b)) &* 1099511628211 }
    let seed = Int(h % 1_000_000) * 100 + trial
    var rng = PyRandom(seed: seed)
    let dir = tempDir()
    defer { try? FileManager.default.removeItem(at: dir) }
    let m = Monkey(try GameSession.fromNativeState(resources: try #require(worldResources), directory: try #require(saves[leg])))
    m.w.savesDir = dir
    m.w.recordLog = false
    func result(_ outcome: String, _ detail: String = "") -> Outcome {
        Outcome(leg: leg, trial: trial, seed: seed, outcome: outcome, detail: detail, events: outcome == "ok" ? [] : m.events)
    }

    // Trials 0 and 1 of every leg kill Lex first, so the reload dialog's path is always covered: hit points 0, then the game's own KILLLEX
    // block (AI_LEX.scr, what DAMAGE_LEX_IMPACT/ENERGY start with PROCESS once the hit points are gone) as the player: RELEASEKEYBOARD,
    // EXITMONITOR, a wait, CAMERA SHOW STITLE, FORCERELOAD.
    if trial < 2, let p = m.player {
        var rec = m.s.vm.objectRecord(m.w.objectKey(p.name))
        rec[0] = .int(0)
        m.s.vm.setObject(m.w.objectKey(p.name), rec)
        m.s.vm.spawn("KILLLEX", ctx: ScriptContext(curFig: p.name, curItem: nil))
        m.events.append("t0 KILLLEX")
    }

    // The reload dialog after a death (FORCERELOAD): 300 ticks of random Escapes and clicks inside it, as the app routes pointer events
    // (InputRouter.handlePointer). It must stay open (or have started a load, a new game or the exit); closed without any of those is `reload_closed`.
    func reloadMash() -> Outcome {
        var up = -1
        for _ in 0..<300 {
            if m.w.pendingLoad != nil || m.w.newGameRequested || m.w.exitRequested { break }
            if m.tick == up { m.events.append("t\(m.tick) dialog mouse up"); m.pointer(.up) }
            if rng.randbelow(100) < 30 {
                if rng.randbelow(100) < 30 { m.press(0x01, ticks: 0) } else if m.w.isOptionsOpen {
                    let x = rng.randint(0, 319), y = rng.randint(0, 199)
                    m.events.append("t\(m.tick) dialog mouse down \(x),\(y)")
                    m.pointer(.down, x: x, y: y)
                    up = m.tick + rng.randint(1, 5)
                }
            }
            m.advance()
        }
        if up >= m.tick { m.pointer(.up); m.advance(2) }
        let open = m.w.isOptionsOpen || m.w.pendingLoad != nil || m.w.newGameRequested || m.w.exitRequested
        return result(open ? "died" : "reload_closed", open ? "" : m.state)
    }

    // 1. Burst: random input for 200-400 ticks.
    var queue: [(tick: Int, what: Scheduled)] = []
    for _ in 0..<rng.randint(200, 400) {
        for item in queue.filter({ $0.tick <= m.tick }) {
            switch item.what {
            case .down(let k): if !m.held.contains(k) { m.route(k, down: true) }
            case .up(let k): if m.held.contains(k) { m.route(k, down: false) }
            case .mouseUp: m.events.append("t\(m.tick) mouse up"); m.pointer(.up)
            }
        }
        queue.removeAll { $0.tick <= m.tick }
        if rng.randbelow(100) < 35 {
            let roll = rng.randbelow(100), t = m.tick
            if roll < 50 {                                                  // a key, held 1-40 ticks, with whatever modifiers are down
                let k = monkeyKeys[rng.randbelow(monkeyKeys.count)]
                if !m.held.contains(k) { m.route(k, down: true); queue.append((t + rng.randint(1, 40), .up(k))) }
            } else if roll < 65 {                                           // a quick double press
                let k = doubleKeys[rng.randbelow(doubleKeys.count)], gap = rng.randint(1, 4)
                queue += [(t, .down(k)), (t + rng.randint(1, 2), .up(k)), (t + gap + 2, .down(k)), (t + gap + rng.randint(3, 6), .up(k))]
            } else if roll < 75 {                                           // a modifier goes down or up
                let k = Array(modifierFlags.keys.sorted())[rng.randbelow(3)]
                if m.held.contains(k) { m.route(k, down: false) } else { m.route(k, down: true); queue.append((t + rng.randint(1, 40), .up(k))) }
            } else if roll < 85, let k = m.held.first {                     // an early key up
                m.route(k, down: false)
            } else if m.w.isMonitorRunning && !m.w.isOptionsOpen {         // a click somewhere (never in the options dialog)
                let x = rng.randint(0, 319), y = rng.randint(0, 199)
                m.events.append("t\(t) mouse down \(x),\(y) in \(m.w.monitor?.name ?? "-")")
                m.pointer(.down, x: x, y: y)
                queue.append((t + rng.randint(1, 6), .mouseUp))
            }
        }
        m.advance()
        if m.died { break }
    }

    // 2. Release everything, the app's way, and the modifiers for good.
    for k in m.held { m.route(k, down: false) }
    m.events.append("t\(m.tick) release all")
    m.input.releasePointer(world: m.w)                          // a click still down is let go, as when the window loses focus
    m.w.setKeyMods(0)

    // 3. Recovery: what a player does to get going again: Escape closes a dialog or monitor, or leaves a script's keyboard hook that holds Lex
    // (the tower gun); scripts run out. A death (FORCERELOAD) goes on to the reload dialog mash.
    func recover() -> Outcome? {
        for i in 0...1800 {
            if m.died { return reloadMash() }
            if m.free { return nil }
            if i == 1800 { return result("stuck", m.state) }
            if i % 30 == 0 && (m.w.isOptionsOpen || m.w.isMonitorRunning || (m.w.keyboardCaptured && (m.player?.hold ?? 0) != 0)) { m.press(0x01, ticks: 1) } else { m.advance() }
        }
        return nil
    }
    if let o = recover() { return o }

    // 4. Idle: with no keys Lex must not walk, run or turn by himself.
    m.advance(60)
    if m.died { return reloadMash() }
    if let motion = m.player?.motion?.lowercased(), ["walk", "run", "turn", "sidestep"].contains(where: motion.hasPrefix) {
        return result("drifts", m.state)
    }

    if m.w.keyboardCaptured { return result("ok_captured") }       // a script owns the keys (zero-G room): Up is not a step there

    // 5. Move: Up must move him; if not, turn left a little and try again. Out of combat first (C), where Up is an attack, not a step.
    if m.player?.combat == true { m.press(0x2e, ticks: 2) }
    var blocked: Outcome?                                          // the recovery before a move attempt ended the trial (stuck, died)
    func moved(_ ticks: Int) -> Bool {
        if let o = recover() { blocked = o; return true }           // a script (an earthquake, a console) may have taken Lex since: wait it out
        let before = m.player?.pos
        m.press(0x48, ticks: ticks)
        guard let a = before, let b = m.player?.pos else { return false }
        return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z) > 1
    }
    if !moved(45) {
        m.press(0x4b, ticks: 20)
        if !moved(45), blocked == nil {
            m.advance(300)                                          // a use animation (the medic kit) may simply take longer than the attempts: one last try
            if !moved(45), blocked == nil { return m.died ? reloadMash() : result("cannot_move", m.state) }
        }
    }
    return blocked ?? result("ok")
}

@Suite(.enabled(if: game != nil && env["MONKEY"] == "1", "set BIOFORGE_DATA and MONKEY=1 to run the monkey test"))
struct MonkeyTests {
    @Test(arguments: monkeyLegs)
    func monkeyCannotSoftLockTheGame(leg: String) throws {
        let saves: [String: URL]
        switch monkeySaves {
        case .success(let s): saves = s
        case .failure(let e): Issue.record("could not make the saves: \(e.text)"); return
        }
        let trials = Int(env["MONKEY_TRIALS"] ?? "") ?? 40
        var outcomes: [Outcome] = []
        for trial in 0..<trials where env["MONKEY_TRIAL"].map({ Int($0) == trial }) ?? true {
            print("RUN \(leg) \(trial)"); fflush(nil)                 // if Swift traps, this line names the trial
            let o = try runTrial(leg: leg, trial: trial, saves: saves)
            print("\(o.leg) \(o.trial) \(o.seed) \(o.outcome) \(o.detail)"); fflush(nil)
            if env["MONKEY_LOG"] == "1" && env["MONKEY_LEG"] == leg { print(o.events.joined(separator: "\n")) }
            outcomes.append(o)
            if ["stuck", "cannot_move", "drifts", "reload_closed"].contains(o.outcome) { Issue.record("\(leg) trial \(trial) seed \(o.seed): \(o.outcome): \(o.detail)") }
        }
        let counts = Dictionary(grouping: outcomes, by: \.outcome).mapValues(\.count).sorted { $0.key < $1.key }.map { "\($0.key) \($0.value)" }
        print("SUMMARY \(leg): " + counts.joined(separator: ", ")); fflush(nil)
        let lines = try outcomes.map { o -> String in
            let json: [String: Any] = ["leg": o.leg, "trial": o.trial, "seed": o.seed, "outcome": o.outcome, "detail": o.detail, "events": o.events]
            return String(decoding: try JSONSerialization.data(withJSONObject: json, options: [.sortedKeys]), as: UTF8.self)
        }
        let folder = outDir.appendingPathComponent("monkey")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try (lines.joined(separator: "\n") + "\n").write(to: folder.appendingPathComponent("\(leg).jsonl"), atomically: true, encoding: .utf8)
    }
}
