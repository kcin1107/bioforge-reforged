// Stage 3b parity tests: the world binding against the Python prototype (fixtures.json "stage3b", written by
// re/tools/native_fixtures.py). Each scenario (re/interp/scenarios.py: opening_escape, opening_revival, landpad_meetmech,
// beach_tunnel_beach, plus opening_keys for the key handler) and the 1100-tick new-game boot is replayed in Swift with the same
// inputs; the engine-call log, every engine-side log, checkpoint states, the final world state and indexed framebuffers must match
// exactly. The canonical line formats (row/Canon) mirror cv()/row() of the fixture script.
import Foundation
import Testing
@testable import BioForgeCore

nonisolated(unsafe) let stage3b = fixtures["stage3b"] as! JSON
nonisolated(unsafe) let worldResources: GameResources? = game.flatMap { try? GameResources(game: $0) }

// MARK: canonical text (fixture script: cv / row)

protocol Canon { var canon: String { get } }
extension Int: Canon { var canon: String { String(self) } }
extension Double: Canon { var canon: String { String(format: "%.17g", self) } }
extension Bool: Canon { var canon: String { self ? "T" : "F" } }
extension String: Canon { var canon: String { qs(self) } }
extension Optional: Canon where Wrapped: Canon { var canon: String { map(\.canon) ?? "-" } }
extension Array: Canon where Element: Canon { var canon: String { "[" + map(\.canon).joined(separator: ",") + "]" } }
extension ScriptValue: Canon { var canon: String { val(self) } }
extension LogValue: Canon {
    var canon: String {
        switch self {
        case .none: return "-"
        case .bool(let b): return b.canon
        case .int(let i): return i.canon
        case .str(let s): return s.canon
        }
    }
}
extension SIMD3: Canon where Scalar == Double { var canon: String { [x, y, z].canon } }
struct Raw: Canon { let canon: String }
func row(_ xs: Canon...) -> String { xs.map(\.canon).joined(separator: "|") }

/// Hash a line list like digest() of the fixture script and compare count, hash and chunks.
func expectDigest(_ lines: [String], _ fx: Any?, _ tag: String) {
    guard let d = fx as? JSON else { Issue.record("\(tag): no fixture"); return }
    let n = d["len"] as! Int
    if lines.count == n && shaText(lines) == d["sha"] as! String { return }
    let want = d["lines"] as! [String]
    if let i = zip(lines, want).enumerated().first(where: { $0.element.0 != $0.element.1 })?.offset, lines.count <= 100 || i < want.count {
        Issue.record("\(tag): line \(i) differs\n  swift  \(lines[i])\n  python \(want[i])")
    } else {
        Issue.record("\(tag): \(lines.count) lines vs \(n); \(firstDivergence(lines, d["chunks"] as! [String]))")
    }
}

// MARK: frames

struct FrameDigest {
    let tick: Int, camera: String?, sha: String, rows: [String], segments: [String]?
    init(_ fb: Framebuffer, tick: Int, camera: String?, segments: Bool) {
        self.tick = tick; self.camera = camera
        sha = BioForgeCoreTests.sha(fb.pixels)
        let w = Framebuffer.width
        rows = (0..<Framebuffer.height).map { String(BioForgeCoreTests.sha(Array(fb.pixels[($0 * w)..<(($0 + 1) * w)])).prefix(8)) }
        self.segments = segments ? (0..<Framebuffer.height).map { y in
            (0..<w / 8).map { s in String(BioForgeCoreTests.sha(Array(fb.pixels[(y * w + s * 8)..<(y * w + s * 8 + 8)])).prefix(4)) }.joined()
        } : nil
    }

    /// Compare with a fixture frame: exact SHA, else report the share of identical rows / 8-pixel segments.
    func check(_ fx: JSON, _ tag: String) -> Bool {
        if sha == fx["sha"] as! String && camera == fx["camera"] as? String { return true }
        let r = zip(rows, fx["rows"] as! [String]).filter { $0 == $1 }.count
        var msg = "\(tag): frame differs (camera \(camera ?? "-") vs \(fx["camera"] as? String ?? "-"), \(r)/200 rows identical"
        if let seg = segments, let want = fx["segments"] as? [String] {
            var same = 0
            for (a, b) in zip(seg, want) { for s in 0..<(a.count / 4) { if a.dropFirst(4 * s).prefix(4) == b.dropFirst(4 * s).prefix(4) { same += 8 } } }
            msg += String(format: ", identical pixels >= %.3f%%", 100 * Double(same) / 64000)
        }
        Issue.record("\(msg))")
        return false
    }
}

// MARK: new-game boots (the intro plays first)

/// The pre-intro port loaded CHAOS in the tick numbered 26 (27 ticks run). Tick counts written for it are kept as the same state after the
/// first CHAOS LOADLEVEL: `old T` = T - 27 ticks after it (scenarios.py OLD_ANCHOR_TICKS / old_ticks).
let oldAnchorTicks = 27
func oldTicks(_ count: Int) -> Int { count - oldAnchorTicks }

/// `MOTION ... FREEZE` blocks its caller until the motion ends, which delays every opening event from the nurse's ACTIVATE on by 54 ticks
/// (scenarios.py FREEZE_SHIFT / opening_ticks): STARTUPFIRSTBOT's DEACTIVATED (15) and GOODMORNINGLEX's WAKE_UP_HEAD (39).
let freezeShift = 54
let quakeTailShift = 52       // scenarios.QUAKE_TAIL_SHIFT: SMALL_QUAKE waits out its released loop
func openingTicks(_ count: Int) -> Int { oldTicks(count) + freezeShift + quakeTailShift }

extension GameSession {
    /// Ticks until the tick of the first CHAOS LOADLEVEL has completed (a new game plays the intro movie first, about 6,460 ticks).
    func runToChaosLoad(limit: Int = 40_000) {
        var n = 0
        while world.levelLoads.isEmpty && n < limit { tick(); n += 1 }
    }

    /// Ticks until a monitor is up: PIMM's `MOTION LOOK_AT_PIM FREEZE` blocks until the motion has played (about 36 ticks, 10d0:6083).
    func runUntilMonitor(limit: Int = 80) {
        var n = 0
        while world.monitor == nil && n < limit { tick(); n += 1 }
    }

    /// A new game in the state the pre-intro port had after `old` ticks.
    static func newGame(resources: GameResources, afterOldTicks old: Int) throws -> GameSession {
        let s = try newGame(resources: resources)
        s.runToChaosLoad()
        for _ in 0..<oldTicks(old) { s.tick() }
        return s
    }

    /// `afterOldTicks`, then on until Lex is out of bed: the wake-up runs with his AI off (+0x229), and FUN_10a8_0541 answers only S then.
    static func newGame(resources: GameResources, inControlAfterOldTicks old: Int) throws -> GameSession {
        let s = try newGame(resources: resources, afterOldTicks: old)
        for _ in 0..<2_000 where (s.world.player?.hold ?? 0) != 0 { s.tick() }
        return s
    }

    /// A new game `count` old ticks into the opening, for an old tick after the nurse's ACTIVATE (see `openingTicks`).
    static func newGame(resources: GameResources, afterOpeningTicks count: Int) throws -> GameSession {
        let s = try newGame(resources: resources)
        s.runToChaosLoad()
        for _ in 0..<openingTicks(count) { s.tick() }
        return s
    }
}

// MARK: a replayed run (mirrors scenario_runner / scenarios.py)

final class Run {
    let session: GameSession
    var world: World { session.world }
    var vm: ScriptVM { session.vm }
    let boot: Bool, captureBoot: Bool
    var frames: [Int: FrameDigest] = [:], checkpointFrames: [String: FrameDigest] = [:]
    var checkpoints: [[String]] = []

    /// `boot`: new-game boot, run through the intro to the end of the tick of the first CHAOS LOADLEVEL unless `toAnchor` is false (frames are
    /// then keyed by the ticks after it); `captureBoot`: the plain boot run, which also hashes frames at the ticks the fixture lists.
    init(level: String, boot: Bool = false, captureBoot: Bool = false, toAnchor: Bool = true) throws {
        let res = try #require(worldResources)
        session = boot ? try GameSession.newGame(resources: res) : try GameSession(resources: res, level: level)
        self.boot = boot; self.captureBoot = captureBoot
        if boot && toAnchor { while world.levelLoads.isEmpty && vm.tick < 40_000 { tick(1) } }
    }

    func render(_ segments: Bool) -> FrameDigest {
        var fb = Framebuffer()
        world.render(into: &fb)
        return FrameDigest(fb, tick: vm.tick, camera: world.currentCamera, segments: segments)
    }

    /// scenarios.tick(): input per tick, scripts, world, unattended difficulty choice.
    func tick(_ n: Int, controls: ((Int) -> World.PlayerInput)? = nil) {
        for i in 0..<n {
            if let c = controls?(i) { world.setPlayerInput(forward: c.forward, turn: c.turn, run: c.run, attack: c.attack) }
            session.tick()
            let rel = boot ? world.levelLoads.first.map { vm.tick - ($0.tick + 1) } : vm.tick      // boot runs: ticks after the first CHAOS load
            if let rel, rel >= 0, rel % 100 == 0 || (captureBoot && [1, 400, 700, 900, 1100].contains(rel)) { frames[rel] = render(captureBoot) }
        }
    }

    func checkpoint(_ name: String, frame: Bool = false) {
        var out = [row("CP", name, vm.tick, world.level, world.currentCamera)]
        if let p = world.player { out.append(row("P", p.name, p.pos, p.motion, p.collisions)) } else { out.append(row("P", "-")) }
        for n in world.allFigureNames.sorted() {
            let f = world.figures[n]!
            out.append(row("F", n, f.type, f.pos, f.motion, f.collisions, f.viewCams))
        }
        for n in world.itemNames.sorted() {
            let i = world.items[n]!
            out.append(row("I", n, i.type, i.owner, i.slot))
        }
        checkpoints.append(out)
        if frame { checkpointFrames[name] = render(true) }
    }

    // MARK: engine-side logs (fixture: run_lines)

    func runLines() -> [String: [String]] {
        let w = world
        var out: [String: [String]] = [:]
        out["camera_changes"] = w.cameraChanges.map { row($0.tick, $0.from, $0.to, $0.reason) }
        out["level_loads"] = w.levelLoads.map { row($0.tick, $0.level, $0.arrival, $0.position) }
        out["hits"] = w.hits.map { row($0.tick, $0.attacker, $0.target, $0.motion, $0.label) }
        out["events"] = w.events.map { row($0.tick, $0.block) }
        out["sound_log"] = w.soundLog.map { row($0.tick, $0.index, $0.name, $0.volume, $0.pitch, $0.handle) }
        out["sound_stops"] = w.soundStops.map { row($0.tick, $0.handle) }
        out["sound_releases"] = w.soundReleases.map { row($0.tick, $0.handle) }
        out["sound_drops"] = w.soundDrops.map { row($0.tick, $0.index, $0.name) }
        out["sound_volumes"] = w.soundVolumes.map { row($0.tick, $0.handle, $0.volume) }
        out["subtitle_log"] = w.subtitleLog.map { row($0.tick, $0.handle, $0.colour, $0.text, $0.end) }
        out["music_log"] = w.musicLog.map { row($0.tick, $0.value) }
        out["warnings"] = (w.warnings + vm.warnings).map { row($0) }
        out["key_log"] = w.keyLog.map { row($0.tick, $0.action, $0.detail) }
        out["option_actions"] = w.optionActions.map { row($0.tick, $0.action) }
        out["monitor_codes"] = w.monitorCodes.map { row($0.name, $0.value) }
        var wl = [row("W", w.level, w.camera, w.defaultCamera, w.currentCamera, w.scriptAuto, w.follow, w.candidate, w.selected, w.loadedCam,
                      w.playerName, w.disabled.sorted(), w.currentMusic, w.exitRequested, w.paused, vm.tick, vm.nextHandle)]
        for f in w.allFigures {
            wl.append(row("F", f.name, f.name, f.type, f.pos, f.heading, f.motion, f.idx, f.loop, f.phase, f.finished, f.frozen, f.combat,
                          f.spar, f.collisions, f.hitDone, f.manualControl, f.go != nil, f.enemy, f.aiType, f.aiProc.map { !$0.done } ?? false,
                          f.viewCams))
        }
        for n in w.itemNames { let i = w.items[n]!; wl.append(row("I", n, i.name, i.type, i.owner, i.slot)) }
        for n in w.logEntries.keys { wl.append(row("L", n, w.logEntries[n]!, w.logEntryTimes[n])) }
        out["world"] = wl
        out["globals"] = vm.globals.keys.sorted().map { row($0, vm.globals[$0]!) }
        out["objects"] = vm.objectKeys.sorted().map { row($0, vm.objectRecord($0)) }
        out["procs"] = vm.processes.map { row($0.handle, $0.block.name, $0.pc, $0.wake, $0.suspended, $0.origin) }
        return out
    }

    func engineLog() -> [String] {
        world.log.map { row($0.tick, $0.block, $0.kind.rawValue, $0.name, $0.args) }
    }

    /// Compare everything with the fixture run `name`.
    func verify(_ name: String) throws {
        let fx = (stage3b["runs"] as! [JSON]).first { $0["name"] as! String == name }!
        #expect(vm.tick == fx["ticks"] as! Int, "\(name) ticks")
        let log = engineLog()
        expectDigest(log, fx["log"], "\(name) engine log")
        var counts: [String: Int] = [:]
        for e in world.log { counts[e.name, default: 0] += 1 }
        #expect(counts == (fx["command_counts"] as! [String: Int]), "\(name) command counts")
        let logs = fx["logs"] as! JSON, mine = runLines()
        #expect(Set(mine.keys) == Set(logs.keys), "\(name) log kinds")
        for (k, lines) in mine.sorted(by: { $0.key < $1.key }) { expectDigest(lines, logs[k], "\(name) \(k)") }
        let cps = fx["checkpoints"] as! [JSON]
        #expect(checkpoints.count == cps.count, "\(name) checkpoints")
        for (i, c) in zip(checkpoints, cps).enumerated() { expectDigest(c.0, c.1, "\(name) checkpoint \(i)") }
        let fr = fx["frames"] as! JSON
        #expect(Set(frames.keys.map(String.init)) == Set(fr.keys), "\(name) frame ticks")
        var exact = 0
        for (t, d) in frames.sorted(by: { $0.key < $1.key }) { if let x = fr[String(t)] as? JSON, d.check(x, "\(name) tick \(t)") { exact += 1 } }
        let cf = fx["checkpoint_frames"] as! JSON
        #expect(Set(checkpointFrames.keys) == Set(cf.keys), "\(name) checkpoint frames")
        for (n, d) in checkpointFrames.sorted(by: { $0.key < $1.key }) { if let x = cf[n] as? JSON, d.check(x, "\(name) checkpoint \(n)") { exact += 1 } }
        var rng = world.rng
        #expect((0..<3).map { _ in rng.randint(0, 99) } == fx["rng_next"] as! [Int], "\(name) RNG state")
        print("\(name): \(vm.tick) ticks, \(log.count) engine calls, \(frames.count + checkpointFrames.count) frames (\(exact) exact), RNG, logs matched")
    }
}

extension World {
    var allFigureNames: [String] { allFigures.map(\.name) }
    var itemNames: [String] { items.keys }
}

// MARK: tests

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct WorldTests {
    @Test func iKeyInventoryExitKeepsBattery() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        session.world.keyDown(0x17)
        session.runUntilMonitor()
        for _ in 0..<4 { session.tick() }
        let monitor = try #require(session.world.monitor)
        #expect(monitor.listKeys("INMT") == ["MONBAT"])
        let exit = try #require(monitor.buttonCenter("IXTB"))
        session.world.monitorPointerMove(x: exit.x, y: exit.y)
        session.world.monitorMouseDown()
        session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }
        #expect(!session.world.isMonitorRunning, "direct inventory exits through its authored MON_STOP")
        #expect(session.world.items["MY_BATTERY"]?.slot == "INVENTORY")
    }

    @Test func keysAreIgnoredWhilePimmHoldsLex() throws {
        // FUN_10a8_0541: with +0x229 raised (PIMM_INVENTORY's AI OFF) only S is answered. A second I while the wrist rises started a
        // second PIMM_INVENTORY whose AI OFF outlived the page: Lex could not move after Escape (test_keys twin).
        let session = try GameSession.newGame(resources: try #require(worldResources), inControlAfterOldTicks: 1_000)
        let w = session.world, lex = try #require(w.player)
        w.keyDown(0x17); w.keyUp(0x17)
        for _ in 0..<5 { session.tick() }
        #expect(lex.hold == 1 && w.monitor == nil)
        w.keyDown(0x17); w.keyUp(0x17)
        session.runUntilMonitor()
        #expect(session.vm.processes.filter { $0.block.name == "PIMM_INVENTORY" }.count == 1)
        w.monitorKey("ESCAPE")
        for _ in 0..<10 { session.tick() }
        #expect(w.monitor == nil && lex.hold == 0)
    }

    @Test func escapeSkipsTheIntroMovie() throws {
        // INTRO captures the keyboard with COMMON's GETESCKEY while its movie plays; the host hands Escape over as scan 0x01 (KeyBindings
        // .capturedScan), _UserInterrupt is set and JUMPON leaves the movie, so the opening reaches its first LOADLEVEL far sooner.
        let resources = try #require(worldResources)
        func firstLoad(escape: Bool) throws -> Int {
            let session = try GameSession.newGame(resources: resources)
            while !(session.world.flicOpen && session.world.keyboardCaptured) && session.vm.tick < 5_000 { session.tick() }
            #expect(session.world.flicOpen && session.world.keyboardCaptured, "the intro movie plays with the keyboard captured")
            for _ in 0..<30 { session.tick() }
            if escape { session.world.keyEvent(scan: 0x01) }
            while session.world.levelLoads.isEmpty && session.vm.tick < 40_000 { session.tick() }
            return session.vm.tick
        }
        let played = try firstLoad(escape: false), skipped = try firstLoad(escape: true)
        print("intro: first LOADLEVEL at tick \(played) played, \(skipped) with Escape")
        #expect(skipped + 1_000 < played)
    }

    @Test func pKeyOpensAndEscapeClosesPIMM() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        #expect(session.world.player != nil)
        session.world.keyDown(0x19)
        session.runUntilMonitor()
        #expect(session.world.isMonitorRunning, "P starts the authored PIMM script")
        var frame = Framebuffer()
        session.world.renderPresentation(into: &frame)
        #expect(frame.pixels.contains { $0 != 0 }, "the player-facing frame shows PIMM art")
        session.world.monitorKey("ESCAPE")
        for _ in 0..<4 { session.tick() }
        #expect(!session.world.isMonitorRunning, "Escape runs PIMM's authored MON_STOP path")
    }

    @Test func presentationCaptionLifetime() throws {
        let res = try #require(worldResources)
        let world = try World(resources: res, level: "CHAOS", camera: "CE33")
        var scene = Framebuffer(), shown = Framebuffer(), expired = Framebuffer()
        world.render(into: &scene)
        world.subtitleLog = [SubtitleEvent(tick: 0, handle: 1, colour: 0x75, text: "A", end: 1)]
        world.renderPresentation(into: &shown)
        #expect(shown.pixels != scene.pixels, "an active caption changes the player-facing frame")
        world.subtitleLog[0].end = 0
        world.renderPresentation(into: &expired)
        #expect(expired.pixels == scene.pixels, "the caption ends at its exclusive end tick")
    }

    @Test func randomStream() {
        for fx in stage3b["rng"] as! [JSON] {
            let seed = fx["seed"] as! Int
            var r = PyRandom(seed: seed)
            #expect((0..<6).map { _ in Int(r.next32()) } == fx["raw"] as! [Int], "seed \(seed) getrandbits(32)")
            r = PyRandom(seed: seed)
            for d in fx["draws"] as! [[Int]] { #expect(r.randint(d[0], d[1]) == d[2], "seed \(seed) randint(\(d[0]), \(d[1]))") }
        }
    }

    @Test func keyMapping() {
        var lines: [String] = []
        for scan in 0..<0x59 {
            for mods in [0, Keys.shift, Keys.ctrl, Keys.alt] {
                for combat in [false, true] {
                    for playing in [nil, "ATK_M4", "RUN", "WALK"] as [String?] {
                        let a = Keys.action(scan: scan, mods: mods, combat: combat, playing: playing)
                        var parts: [Canon] = []
                        switch a {
                        case nil: parts = ["-"]
                        case .motion(let m)?: parts = ["motion", m, true]
                        case .oneshot(let m)?: parts = ["oneshot", m]
                        case .pimm(let s)?: parts = ["pimm", s]
                        case .gamma(let g)?: parts = ["gamma", g]
                        case .some(let o): parts = [o.name]
                        }
                        lines.append(row(scan, mods, combat, playing, Raw(canon: "[" + parts.map(\.canon).joined(separator: ",") + "]")))
                    }
                }
            }
        }
        expectDigest(lines, stage3b["keys"], "key mapping")
    }

    @Test func soundTableAndAssets() throws {
        let res = try #require(worldResources)
        let bank = res.sounds
        expectDigest(bank.ids.sorted { $0.key < $1.key }.map { row($0.key, $0.value) }, (stage3b["sounds"] as! JSON)["ids"], "sound ids")
        expectDigest(bank.samples.map { row($0.index, $0.name, $0.rate, $0.loopStart, $0.loopEnd, $0.length) }, (stage3b["sounds"] as! JSON)["samples"], "samples")
        let fx = stage3b["assets"] as! JSON
        for (type, any) in fx["assets"] as! [String: JSON] {
            let a = try #require(res.asset(type), "\(type)")
            #expect(String(format: "%.17g", Double(a.footOffset)) == any["foot"] as! String, "\(type) foot offset")
            let names = a.assets.motions.filter { !$0.frames.isEmpty }.map(\.name).sorted()
            let other = a.assets.motion(names[names.count / 2])!
            func bits(_ m: Motion, _ f: Int) -> String {
                var p = Pack()
                for v in a.pose(m, f) { for c in [v.x, v.y, v.z] { p.b += withUnsafeBytes(of: c.bitPattern.littleEndian) { Array($0) } } }
                return sha(p.b)
            }
            let stand = a.assets.motion("STAND") ?? a.assets.motion(names[0])!
            #expect([bits(stand, 0), bits(other, other.frames.count / 2)] == any["pose_bits"] as! [String], "\(type) posed vertices (exact bits)")
        }
        let ext = fx["extents"] as! [String: [Double]]
        #expect(Set(res.extents.keys) == Set(ext.keys), "extent types")
        for (k, v) in ext { #expect(res.extents[k].map { [$0.x, $0.y, $0.z] } == v, "\(k) extent") }
    }

    @Test func newGameBoot() throws {
        let r = try Run(level: "TITLE", boot: true, captureBoot: true)
        r.tick(1100)
        try r.verify("boot")
    }

    /// The intro movie: indexed frames at fixed ticks inside it and its sound / subtitle / music logs, handles included.
    @Test func introMovieMatchesPrototype() throws {
        let fx = stage3b["intro"] as! JSON
        let want = fx["frames"] as! JSON
        let r = try Run(level: "TITLE", boot: true, toAnchor: false)
        var frames: [Int: FrameDigest] = [:]
        while r.world.levelLoads.isEmpty && r.vm.tick < 40_000 {
            r.tick(1)
            if want[String(r.vm.tick)] != nil { frames[r.vm.tick] = r.render(false) }
        }
        #expect(r.vm.tick == fx["ticks"] as! Int, "intro ticks")
        #expect(Set(frames.keys.map(String.init)) == Set(want.keys), "intro frame ticks")
        for (t, d) in frames.sorted(by: { $0.key < $1.key }) { _ = d.check(want[String(t)] as! JSON, "intro tick \(t)") }
        let logs = fx["logs"] as! JSON, mine = r.runLines()
        for (k, any) in logs.sorted(by: { $0.key < $1.key }) { expectDigest(mine[k] ?? [], any, "intro \(k)") }
    }

    @Test func openingEscape() throws {
        let r = try Run(level: "TITLE", boot: true)
        r.tick(openingTicks(1170))            // Lex stands from old tick 1155
        r.world.scriptAuto = true
        r.world.setCamera("CE31", "scenario handoff")
        r.vm.globals["_bars3_on"] = .int(0)                    // the live cell bars would shock Lex at DR3 (trigger DR_ZAP3)
        r.checkpoint("opening-ready", frame: true)
        r.world.setPlayerInput(attack: true)
        r.tick(1)
        r.checkpoint("unarmed-space")
        r.tick(180) { _ in World.PlayerInput(forward: 1) }      // the nurse's push carries the straight walk to DR3
        r.world.setPlayerInput()
        r.tick(1)
        r.checkpoint("outside-cell", frame: true)
        try r.verify("opening_escape")
    }

    @Test func openingRevival() throws {
        let r = try Run(level: "TITLE", boot: true)
        for _ in 0..<10000 {
            r.tick(1)
            if case .int(1)? = r.vm.globals["_lexrevived"] { break }
        }
        r.checkpoint("after-revival", frame: true)
        try r.verify("opening_revival")
    }

    @Test func landpadMeetMech() throws {
        let r = try Run(level: "LANDPAD")
        r.vm.fire("MEETMECH")
        r.tick(500)
        r.checkpoint("meetmech-complete", frame: true)
        try r.verify("landpad_meetmech")
    }

    @Test func beachTunnelBeach() throws {
        let r = try Run(level: "BEACH")
        r.world.figure("PLAYER")
        r.vm.fire("TO_TPL")
        r.tick(1)
        r.checkpoint("tunnel-arrival", frame: true)
        r.vm.fire("TO_BCH")
        r.tick(1)
        r.checkpoint("beach-return", frame: true)
        try r.verify("beach_tunnel_beach")
    }

    @Test func combatKeyTwiceLowersTheFists() throws {
        let r = try Run(level: "TITLE", boot: true)
        r.tick(openingTicks(1170))
        r.world.scriptAuto = true
        let lex = try #require(r.world.player)
        r.world.keyDown(0x2e); r.world.keyUp(0x2e)                   // C: combat on (LEX_ENTER_COMBAT: ENTER_COMBAT, then atk_stand)
        r.tick(60)
        #expect(lex.combat && lex.motion == "ATK_STAND")
        r.world.keyDown(0x2e); r.world.keyUp(0x2e)                   // C: combat off; LEX_LEAVE_COMBAT plays no motion, FUN_1098_0745 asks for stand
        r.tick(5)
        #expect(!lex.combat && lex.motion == "STAND")
    }

    @Test func openingKeys() throws {
        let r = try Run(level: "TITLE", boot: true)
        r.tick(openingTicks(1170))            // Lex stands from old tick 1155
        r.world.scriptAuto = true
        r.world.setCamera("CE31", "scenario handoff")
        r.checkpoint("keys-ready", frame: true)
        r.world.keyDown(0x48)
        r.tick(90)
        r.world.keyDown(0x4b, mods: Keys.shift)
        r.tick(20)
        r.world.keyUp(0x4b)
        r.world.keyDown(0x4d)
        r.tick(10)
        r.world.keyUp(0x4d); r.world.keyUp(0x48)
        r.tick(5)
        r.checkpoint("keys-walked", frame: true)
        r.world.keyDown(0x2e); r.world.keyUp(0x2e)
        r.tick(10)
        r.world.keyDown(0x4c); r.world.keyUp(0x4c)
        r.tick(10)
        r.world.keyDown(0x48, mods: Keys.shift)
        r.tick(30)
        r.world.keyUp(0x48)
        r.world.keyDown(0x4b)
        r.tick(15)
        r.world.keyUp(0x4b)
        r.world.keyDown(0x39); r.world.keyUp(0x39)
        r.tick(5)
        r.world.keyDown(0x2e); r.world.keyUp(0x2e)
        r.tick(20)
        r.checkpoint("keys-end", frame: true)
        try r.verify("opening_keys")
    }
}
