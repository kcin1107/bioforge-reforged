// Session recording and exact replay: the inputs of a played session, replayed headless, end in the same state (World.stateDigest), from a new
// game and from a loaded save. REPLAY=<recording folder, or a bug report's Session folder> replays that folder and checks its recorded checkpoints.

import Foundation
import Testing
@testable import BioForgeCore

@Suite struct ReplayTests {
    /// Real inputs through the World's input methods: walking, turning, running, a key press, the options dialog with pointer moves and clicks.
    private func drive(_ s: GameSession, ticks: Int, recorder: SessionRecorder?, checkpoints: Int = 4) {
        let w = s.world
        for n in 0..<ticks {
            switch n % 150 {
            case 0: w.keyDown(0x48, mods: 0)                  // up: walk
            case 40: w.keyDown(0x4b, mods: 0)                 // left: turn while walking
            case 70: w.keyUp(0x4b)
            case 75: w.setKeyMods(1); w.keyDown(0x4d, mods: 1)
            case 95: w.keyUp(0x4d, mods: 0); w.keyUp(0x48)
            case 100: w.keyEvent(scan: 0x39, mods: 0)         // space: use
            case 110: w.keyDown(0x50, mods: 0)                // down: walk back
            case 125: w.releaseKeys()
            case 130: w.keyEvent(scan: 0x18, mods: 0)         // O: the options dialog
            case 132: w.optionPointerMove(x: 160, y: 100); w.optionMouseDown()
            case 134: w.optionMouseUp(); w.optionPointerMove(x: 40, y: 20)
            case 140: w.keyEvent(scan: 1, mods: 0)            // Escape closes it
            default: break
            }
            s.tick()
            if let recorder, n % (ticks / checkpoints) == 0 { recorder.checkpoint(w) }
        }
    }

    private func replayMatches(_ s: GameSession, folder: URL) throws {
        let res = try #require(worldResources)
        let (replayed, mismatches) = try SessionReplay.replay(folder: folder, resources: res, until: s.world.frames)
        #expect(mismatches.isEmpty, "\(mismatches)")
        #expect(replayed.world.frames == s.world.frames)
        #expect(replayed.world.stateDigest() == s.world.stateDigest())
    }

    @Test func recordingReplaysToTheSameState() throws {
        let res = try #require(worldResources)
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession.newGame(resources: res)
        s.world.recordLog = false
        let rec = try SessionRecorder(directory: dir.appendingPathComponent("Session"), session: s)
        s.world.recorder = rec
        drive(s, ticks: 1500, recorder: rec)
        #expect(s.world.frames > s.vm.tick)                // the options dialog paused the clock while frames went on
        let start = s.world.stateDigest()
        try replayMatches(s, folder: rec.directory)
        #expect(start == s.world.stateDigest())
        // a second recording keeps the first as the previous one
        rec.close()
        let again = try SessionRecorder(directory: dir.appendingPathComponent("Session"), session: s)
        #expect(FileManager.default.fileExists(atPath: again.previousDirectory.appendingPathComponent("session.jsonl").path))
    }

    @Test func aGodModeToggleAndARefillReplayToTheSameState() throws {
        let res = try #require(worldResources)
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession.newGame(resources: res)
        s.world.recordLog = false
        let rec = try SessionRecorder(directory: dir.appendingPathComponent("Session"), session: s)
        s.world.recorder = rec
        for n in 0..<300 {
            if n == 50 { s.world.setGodMode(true) }
            if n == 150 { rec.checkpoint(s.world) }                                   // taken while god mode is on: the digest says so
            if n == 200 { s.world.refillHealth(); s.world.setGodMode(false) }
            s.tick()
        }
        rec.checkpoint(s.world)
        let text = try String(contentsOf: rec.directory.appendingPathComponent("session.jsonl"), encoding: .utf8)
        #expect(text.contains("setGodMode") && text.contains("refillHealth"))
        try replayMatches(s, folder: rec.directory)
        #expect(!s.world.stateDigest().isEmpty && !s.world.godMode)
    }

    @Test func aRecordingWithAnInputMissingDoesNotMatch() throws {
        let res = try #require(worldResources)
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession.newGame(resources: res)
        let rec = try SessionRecorder(directory: dir.appendingPathComponent("Session"), session: s)
        s.world.recorder = rec
        drive(s, ticks: 400, recorder: rec)
        let file = rec.directory.appendingPathComponent("session.jsonl")
        let lines = try String(contentsOf: file, encoding: .utf8).split(separator: "\n")
        let kept = lines.filter { !$0.contains("\"keyDown\"") }
        #expect(kept.count < lines.count)
        try kept.joined(separator: "\n").appending("\n").write(to: file, atomically: true, encoding: .utf8)
        let (_, mismatches) = try SessionReplay.replay(folder: rec.directory, resources: res)
        #expect(!mismatches.isEmpty)
    }

    @Test func recordingFromALoadedSaveReplaysToTheSameState() throws {
        let res = try #require(worldResources)
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let first = try GameSession(resources: res, level: "CHAOS")
        for _ in 0..<60 { first.tick() }
        first.world.savesDir = dir
        let im1 = try #require(first.world.saveNative(slot: 1))
        let saved = dir.appendingPathComponent("GAME1.d")
        try Im1.unpack([UInt8](try Data(contentsOf: im1)), to: saved)
        let s = try GameSession.fromNativeState(resources: res, directory: saved)
        s.world.recordLog = false
        let rec = try SessionRecorder(directory: dir.appendingPathComponent("Session"), session: s)
        s.world.recorder = rec
        #expect(FileManager.default.fileExists(atPath: rec.directory.appendingPathComponent("start.d").path))
        drive(s, ticks: 750, recorder: rec)
        try replayMatches(s, folder: rec.directory)
    }

    @Test(.enabled(if: !(ProcessInfo.processInfo.environment["REPLAY"] ?? "").isEmpty))
    func aRecordedFolderReplaysToItsCheckpoints() throws {
        let path = ProcessInfo.processInfo.environment["REPLAY"] ?? ""
        var folder = URL(fileURLWithPath: path)
        if !FileManager.default.fileExists(atPath: folder.appendingPathComponent("session.jsonl").path) { folder.appendPathComponent("Session") }
        let (s, mismatches) = try SessionReplay.replay(folder: folder, resources: try #require(worldResources))
        print("replayed \(folder.path) to tick \(s.vm.tick), level \(s.world.level)")
        #expect(mismatches.isEmpty, "\(mismatches)")
    }
}
