// Exact replay of a SessionRecorder folder, headless: the session is rebuilt the way it began (a new game, or the copied save), the RNG and
// the flags are restored, and the recorded input calls are applied before the frame they arrived at. The game is a pure function of that input
// (the tick is fixed at 30 Hz, the RNG seeded), so the state matches frame for frame; `stateDigest` checks it at each recorded checkpoint.
// Not reproduced: the player's saves folder. A replay saves into an empty scratch folder, so a slot's "used" state in the options dialog can differ.
import Foundation

public enum SessionReplay {
    public enum Failure: Error { case unreadable(String), unsupported(Int) }

    /// Replays `folder` up to frame `until` (default: the last recorded line) -> the session and a message for every checkpoint that differs.
    public static func replay(folder: URL, resources: GameResources, until: Int? = nil) throws -> (session: GameSession, mismatches: [String]) {
        let text = try String(contentsOf: folder.appendingPathComponent(SessionRecorder.fileName), encoding: .utf8)
        let dec = JSONDecoder()
        var lines = text.split(separator: "\n").map { Data($0.utf8) }
        guard !lines.isEmpty, let header = try? dec.decode(SessionRecorder.Header.self, from: lines.removeFirst()) else { throw Failure.unreadable("no header") }
        guard header.version == SessionRecorder.version else { throw Failure.unsupported(header.version) }
        let s = header.start == "save"
            ? try GameSession.fromNativeState(resources: resources, directory: folder.appendingPathComponent(SessionRecorder.startFolder, isDirectory: true))
            : try GameSession.newGame(resources: resources)
        s.world.recordLog = false
        let saves = FileManager.default.temporaryDirectory.appendingPathComponent("BioForgeReplay-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: saves, withIntermediateDirectories: true)
        s.world.savesDir = saves
        s.world.configureSettings(Settings(sound: header.sound, music: header.music, gamma: header.gamma, subtitles: header.subtitles, language: header.language ?? "E"))
        s.world.rng.state = header.rng
        s.autoDifficulty = header.autoDifficulty
        let events = lines.compactMap { try? dec.decode(SessionRecorder.Line.self, from: $0) }       // a line cut short by a crash is dropped
        var mismatches: [String] = []
        func run(to t: Int) { while s.world.frames < t { s.tick() } }
        for e in events {
            guard let t = e.t else { continue }
            if let until, t > until { break }
            run(to: t)
            if let digest = e.digest {
                let now = s.world.stateDigest()
                if now != digest { mismatches.append("frame \(t): recorded \(digest), replayed \(now)") }
            } else if let name = e.e { apply(name, e.a ?? [], e.s ?? "", s.world) }
        }
        if let until { run(to: until) }
        return (s, mismatches)
    }

    private static func apply(_ name: String, _ a: [Int], _ s: String, _ w: World) {
        switch name {
        case "keyDown": w.keyDown(a[0], mods: a[1])
        case "keyUp": w.keyUp(a[0], mods: a.count > 1 ? a[1] : nil)
        case "setKeyMods": w.setKeyMods(a[0])
        case "releaseKeys": w.releaseKeys()
        case "setGodMode": w.setGodMode(a[0] != 0)
        case "refillHealth": w.refillHealth()
        case "keyEvent": w.keyEvent(scan: a[0], mods: a[1])
        case "setPlayerInput": w.setPlayerInput(forward: a[0], turn: a[1], run: a[2] != 0, attack: a[3] != 0)
        case "monitorPointerMove": w.monitorPointerMove(x: a[0], y: a[1])
        case "monitorMouseDown": w.monitorMouseDown()
        case "monitorMouseUp": w.monitorMouseUp()
        case "monitorKey": w.monitorKey(s)
        case "monitorRightClick": w.monitorRightClick()
        case "optionRightClick": w.optionRightClick()
        case "optionMouseDown": w.optionMouseDown()
        case "optionMouseUp": w.optionMouseUp()
        case "optionKey": w.optionKey(s)
        case "optionActivate": w.optionActivate(s)
        case "optionClick": w.optionClick(x: a[0], y: a[1])
        case "optionPointerMove": w.optionPointerMove(x: a[0], y: a[1])
        default: break
        }
    }
}

extension World {
    /// SHA-256 over the state a replay must reproduce: tick, level, camera, RNG, every figure and item, the script globals, object locals and
    /// running processes, each in a fixed order.
    public func stateDigest() -> String {
        var out = "frames \(frames) tick \(tick) level \(level) camera \(camera ?? "-") player \(playerName ?? "-") rng \(rng.state.index) \(rng.state.mt)\(godMode ? " god" : "")\n"
        for f in figures.values {
            out += "F \(f.name) \(f.type) \(f.pos.map { "\($0)" } ?? "-") \(f.heading) \(f.motion ?? "-") \(f.idx) \(f.phase) \(f.loop) "
            out += "\(f.combat) \(f.spar) \(f.invulnerable) \(f.hidden) \(f.gravity) \(f.bouncy) \(f.finished) \(f.frozen) \(f.falling) \(f.hold) "
            out += "\(f.vx) \(f.vy) \(f.vz) \(f.step) \(f.enemy ?? "-")\n"
        }
        for i in items.values {
            out += "I \(i.key) \(i.type) \(i.owner ?? "-") \(i.slot ?? "-") \(i.pos.map { "\($0)" } ?? "-") \(i.hidden) \(i.vel)\n"
        }
        if let vm {
            for k in vm.globals.keys.sorted() { out += "G \(k) \(vm.globals[k]!)\n" }
            for k in vm.objectKeys.sorted() { out += "O \(k) \(vm.objectRecord(k))\n" }
            for p in vm.processes { out += "P \(p.handle) \(p.block.name) \(p.pc) \(p.wake) \(p.locals)\n" }
        }
        return Sha256.hex(Data(out.utf8))
    }
}
