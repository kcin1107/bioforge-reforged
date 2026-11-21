import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

let hostGame = GameFolder.fromEnvironment()
nonisolated(unsafe) let hostResources: GameResources? = hostGame.flatMap { try? GameResources(game: $0) }

/// A new game ticked until the level autosave is due (the opening has to run first).
func gameWithAutosaveDue() throws -> GameSession {
    let s = try GameSession.newGame(resources: try #require(hostResources))
    var n = 0
    while !s.world.levelAutosaveDue && n < 60_000 { s.tick(); n += 1 }
    try #require(s.world.levelAutosaveDue, "the opening never reached a state where S is accepted")
    return s
}

func tempDir(_ name: String) throws -> URL {
    let dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("\(name)-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    return dir
}

@Suite(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct AutosaveTests {
    @Test func savesPrunesToFiveAndSavesOncePerLevel() throws {
        let s = try gameWithAutosaveDue(), w = s.world
        let dir = try tempDir("autosave")
        defer { try? FileManager.default.removeItem(at: dir) }
        for i in 1...6 { try Data("old".utf8).write(to: dir.appendingPathComponent("2020-01-0\(i) 10.00.00 OLD.IM1")) }
        try Data("keep".utf8).write(to: dir.appendingPathComponent("notes.txt"))
        let previousDir = URL(fileURLWithPath: "/previous")
        w.savesDir = previousDir
        var lines: [String] = []
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd HH.mm.ss"
        let name = "\(formatter.string(from: now)) \(w.level).IM1"
        Autosave.saveIfDue(w, directory: dir, log: { lines.append($0) }, now: now)
        let im1 = try FileManager.default.contentsOfDirectory(atPath: dir.path).filter { $0.hasSuffix(".IM1") }.sorted()
        #expect(im1.count == 5 && im1.contains(name))
        #expect(im1.first == "2020-01-03 10.00.00 OLD.IM1")      // the oldest three of six went
        #expect(try String(contentsOf: dir.appendingPathComponent("notes.txt"), encoding: .utf8) == "keep")
        #expect(w.savesDir == previousDir)
        #expect(w.autosavedLevel == w.level)
        #expect(lines == ["autosave \(name)"])
        Autosave.saveIfDue(w, directory: dir, log: { lines.append($0) }, now: now)
        #expect(lines.count == 1)                                  // the same level is not saved twice
    }

    @Test func aFailedSaveIsLoggedAndSwallowed() throws {
        let s = try gameWithAutosaveDue(), w = s.world
        let dir = try tempDir("autosave-fail")
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent("file")
        try Data("x".utf8).write(to: file)
        var lines: [String] = []
        Autosave.saveIfDue(w, directory: file.appendingPathComponent("sub", isDirectory: true), log: { lines.append($0) })
        #expect(lines.count == 1 && lines[0].hasPrefix("autosave failed: "))
        #expect(w.takeFileError() == nil)
        #expect(w.autosavedLevel == w.level)
    }
}
