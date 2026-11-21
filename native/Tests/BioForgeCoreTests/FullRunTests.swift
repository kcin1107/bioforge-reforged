// Replays the Python full run (re/tools/full_run_transcript.py) in the Swift port, from a new game to EXIT: every call the harness made into
// the engine, every state it edited directly, and a checkpoint of the world every 200 ticks.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct FullRunTests {
    private typealias JSON = [String: Any]

    /// `save_check`: save the session, unpack and load it back, and compare the loaded state's digest with Python's (re/tools/resume_digest.py).
    /// The session itself goes on untouched. SAVE_CHECK_LINES=<leg> prints the loaded state's lines, to diff with Python's (same variable).
    private func saveCheck(_ op: [Any], _ s: GameSession) throws -> String? {
        let name = op[2] as! String, dir = tempDir(), saves = s.world.savesDir
        defer { try? FileManager.default.removeItem(at: dir); s.world.savesDir = saves }
        s.world.savesDir = dir
        let unpacked = dir.appendingPathComponent("GAME1.d")
        try Im1.unpack(try fileBytes(try #require(s.world.saveNative(slot: 1))), to: unpacked)
        let lines = stateLines(try GameSession.fromNativeState(resources: try #require(worldResources), directory: unpacked))
        if ProcessInfo.processInfo.environment["SAVE_CHECK_LINES"] == name { print(lines.joined(separator: "\n")) }
        let got = digest(lines)
        return got.count == op[3] as! Int && got.sha == op[4] as! String ? nil : "\(name): swift \(got.count) lines \(got.sha.prefix(12)), python \(op[3]) lines \((op[4] as! String).prefix(12))"
    }

    /// Applies one op; a `save_check` that does not match gives its description.
    private func apply(_ op: [Any], _ s: GameSession, _ saveChecks: inout [String]) throws {
        try FullRunReplay.apply(op, s) { if let mismatch = try saveCheck($0, s) { saveChecks.append(mismatch) } }
    }

    private func differences(_ c: JSON, _ s: GameSession) -> [String] {
        let w = s.world, vm = s.vm, lex = w.player
        var out: [String] = []
        func check(_ name: String, _ got: Any?, _ want: Any?) {
            if "\(got ?? "nil")" != "\(want ?? "nil")" { out.append("\(name): swift \(got ?? "nil"), python \(want ?? "nil")") }
        }
        check("level", w.level, c["level"])
        check("next handle", vm.nextHandle, c["handle"])
        check("camera", w.currentCamera, c["camera"] is NSNull ? nil : c["camera"])
        check("motion", lex?.motion, c["motion"] is NSNull ? nil : c["motion"])
        check("monitor", w.monitor?.name, c["monitor"] is NSNull ? nil : c["monitor"])
        let figures = c["figures"] as! JSON
        check("figures", w.figures.keys.sorted(), figures.keys.sorted())
        for (name, value) in figures {
            guard let f = w.figures[name] else { continue }
            let want = value as? [Any], p = f.pos
            let got = p.map { "\(Int($0.x)),\(Int($0.y)),\(Int($0.z)),\(f.motion ?? "nil")" }
            let expected = want.map { "\($0[0]),\($0[1]),\($0[2]),\($0[3] is NSNull ? "nil" : "\($0[3])")" }
            check(name, got, expected)
        }
        if let want = c["lex"] as? [Double], let p = lex?.pos {
            if abs(p.x - want[0]) > 0.001 || abs(p.y - want[1]) > 0.001 || abs(p.z - want[2]) > 0.001 { out.append("lex: swift \(p), python \(want)") }
        } else if !(c["lex"] is NSNull) || lex?.pos != nil { out.append("lex: swift \(String(describing: lex?.pos)), python \(String(describing: c["lex"]))") }
        if let want = c["heading"] as? Double, let h = lex?.heading, abs(h - want) > 0.001 { out.append("heading: swift \(h), python \(want)") }
        if let want = c["hp"] as? Int, let name = w.playerName, case .int(let hp)? = vm.objectRecord(name).first, hp != want { out.append("hp: swift \(hp), python \(want)") }
        let text = vm.globals.filter { !$0.key.hasPrefix("_time") }.sorted { $0.key < $1.key }.map { "\($0.key)=\(pyRepr($0.value))" }.joined(separator: "\n")
        check("globals", String(sha256(text).prefix(12)), c["globals"])
        return out
    }

    private func line(_ s: GameSession) -> String {
        let f = String(format: "%.3f", s.world.player?.heading ?? 0), p = s.world.player?.pos
        let other = s.world.figures[s.world.resolve(s.world.follow)]
        let followed = other?.pos.map { " \(Int($0.x)),\(Int($0.y)),\(Int($0.z)) \(String(format: "%.3f", other!.heading)) \(other!.motion ?? "-") \(other!.idx)" } ?? ""
        return "\(s.vm.tick) \(s.world.level) \(s.world.currentCamera ?? "-") \(s.world.player?.motion ?? "-") \(p.map { "\(Int($0.x)),\(Int($0.y)),\(Int($0.z))" } ?? "-") \(f) \(s.world.monitor?.name ?? "-") \(s.world.follow)\(followed) h \(s.vm.nextHandle) \(s.vm.processes.filter { !$0.done }.suffix(3).map { "'\($0.block.name)'" })"
    }

    @Test func theWholeGameRunsAsInPython() throws {
        let url = try #require(Bundle.module.url(forResource: "full_run", withExtension: "json"))
        let data = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? JSON)
        let ops = data["ops"] as! [[Any]], checkpoints = data["checkpoints"] as! [JSON]
        let s = try GameSession.newGame(resources: try #require(worldResources))
        s.world.recordLog = false
        // FULL_RUN_TRACE=a-b prints these ticks, to diff with `re/tools/full_run_transcript.py --trace a b`
        let bounds = (ProcessInfo.processInfo.environment["FULL_RUN_TRACE"] ?? "1-0").split(separator: "-").map { Int($0)! }
        let trace = bounds[0]..<(max(bounds[0], bounds[1] + 1))
        var next = 0, at = 0, saveChecks: [String] = []
        while ops.indices.contains(next), ops[next][0] as! Int == -1 { next += 1 }              // newGame itself makes these
        for c in checkpoints {
            let tick = c["tick"] as! Int
            while s.vm.tick < tick {
                while next < ops.count, ops[next][0] as! Int == s.vm.tick { try apply(ops[next], s, &saveChecks); next += 1 }
                s.tick()
                if trace.contains(s.vm.tick) { print("TR", line(s)) }
                if s.vm.tick == bounds[1] { for (k, v) in s.vm.globals.sorted(by: { $0.key < $1.key }) { print("TG", "\(k)=\(pyRepr(v))") } }
            }
            let diff = differences(c, s)
            if !diff.isEmpty {
                let text = diff.joined(separator: "\n")
                Issue.record("first difference by tick \(tick) (the checkpoint before it was \(at)):\n\(text)")
                return
            }
            at = tick
        }
        while next < ops.count { try apply(ops[next], s, &saveChecks); next += 1 }
        let checked = ops.filter { $0[1] as! String == "save_check" }.count
        #expect(saveChecks.isEmpty, "\(saveChecks.count) of \(checked) save points resume differently from Python:\n\(saveChecks.joined(separator: "\n"))")
        #expect(s.world.exitRequested)
    }

    /// Milestone 6's performance check, opt-in (FULL_RUN_PERF=1, best in a release build: `swift test -c release --filter frameTimes`): the whole
    /// recorded run, each tick followed by the frame the app draws (World.renderPresentation + applyPresentation, as AppDelegate.redrawGame),
    /// timed against the 33.3 ms a 30 Hz tick allows. Metal's upload of the 320x200 image is not included. Only a level load may take longer
    /// (re/NOTES.md "Performance over the whole game").
    @Test(.enabled(if: ProcessInfo.processInfo.environment["FULL_RUN_PERF"] != nil))
    func frameTimes() throws {
        let url = try #require(Bundle.module.url(forResource: "full_run", withExtension: "json"))
        let data = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? JSON)
        let ops = data["ops"] as! [[Any]], checkpoints = data["checkpoints"] as! [JSON]
        let s = try GameSession.newGame(resources: try #require(worldResources))
        s.world.recordLog = false
        var next = 0, saveChecks: [String] = [], frame = Framebuffer(), times: [Double] = [], slowest: [(Double, Int, String)] = [], seenCameras = Set<String>()
        while ops.indices.contains(next), ops[next][0] as! Int == -1 { next += 1 }
        let end = checkpoints.last!["tick"] as! Int
        let clock = ContinuousClock()
        while s.vm.tick < end {
            while next < ops.count, ops[next][0] as! Int == s.vm.tick {
                if ops[next][1] as! String != "save_check" { try apply(ops[next], s, &saveChecks) }
                next += 1
            }
            let level0 = s.world.level, cam0 = s.world.currentCamera
            let t0 = clock.now
            s.tick()
            s.world.renderPresentation(into: &frame)
            var shown = frame
            s.world.applyPresentation(to: &shown)
            let ms = Double((clock.now - t0).components.attoseconds) / 1e15 + Double((clock.now - t0).components.seconds) * 1000
            times.append(ms)
            let what = s.world.level != level0 ? "level load \(level0) -> \(s.world.level)"
                : s.world.currentCamera != cam0 ? (seenCameras.contains(s.world.currentCamera ?? "") ? "camera switch" : "first visit to camera") : "steady"
            if let c = s.world.currentCamera { seenCameras.insert(c) }
            if ms > 10 { slowest.append((ms, s.vm.tick, "\(s.world.currentCamera ?? s.world.monitorName ?? "-"), \(what)")) }
        }
        let sorted = times.sorted()
        func pct(_ p: Double) -> Double { sorted[min(sorted.count - 1, Int(Double(sorted.count) * p))] }
        let budget = 1000.0 / 30
        let over = times.filter { $0 > budget }.count
        let overInLevel = slowest.filter { $0.0 > budget && !$0.2.contains("level load") }
        print(String(format: "PERF ticks %d  mean %.2f ms  median %.2f  p99 %.2f  p99.9 %.2f  max %.2f  over 33.3 ms: %d", times.count,
                     times.reduce(0, +) / Double(times.count), pct(0.5), pct(0.99), pct(0.999), sorted.last ?? 0, over))
        for (ms, tick, cam) in slowest.sorted(by: { $0.0 > $1.0 }).prefix(14) { print(String(format: "PERF slow %.2f ms at tick %d (%@)", ms, tick, cam)) }
        #expect(overInLevel.isEmpty, "\(overInLevel.count) ticks inside a level took longer than a 30 Hz frame: \(overInLevel)")     // a level load may drop a frame or three
    }
}
