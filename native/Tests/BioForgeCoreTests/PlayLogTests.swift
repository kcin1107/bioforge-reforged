import Foundation
import Testing
@testable import BioForgeCore

struct PlayLogFileTests {
    func tempLog() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("playlog-\(UUID().uuidString)/BioForge.log")
    }

    @Test func linesReachTheFileAsTheyAreWritten() throws {
        let url = tempLog()
        let log = PlayLog(file: url)
        log.note("hello")
        #expect(try String(contentsOf: url, encoding: .utf8).contains("hello"))
    }

    @Test func theLastSessionIsKeptForTheNextReport() {
        let url = tempLog()
        PlayLog(file: url).note("before the crash")
        let next = PlayLog(file: url)
        #expect(next.previousTail()?.contains("before the crash") == true)
        #expect(next.lines.isEmpty)
        #expect(next.report(world: nil, app: "test").contains("before the crash"))
    }

    @Test func memoryIsBounded() {
        let log = PlayLog(file: nil, capacity: 3)
        for i in 0..<10 { log.note("line \(i)") }
        #expect(log.lines.count == 3)
        #expect(log.tail().contains("line 9"))
    }
}

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct PlayLogWorldTests {
    @Test func aReportSaysWhereLexIsAndTheLogFollowsHim() throws {
        let session = try GameSession.newGame(resources: try #require(worldResources), afterOldTicks: 1_000)
        let w = session.world
        let lex = try #require(w.player)
        let log = PlayLog(file: nil)
        log.observe(w)
        #expect(log.tail().contains("level \(w.level)"))
        #expect(log.tail().contains("at ("))
        session.vm.setObject(w.objectKey(lex.name), [.int(0)] + Array(repeating: .int(0), count: 9))
        log.observe(w)
        #expect(log.tail().contains("Lex is dead"))
        let text = log.report(world: w, app: "test", comment: "fell through the floor")
        #expect(text.contains("Level \(w.level)"))
        #expect(text.contains("fell through the floor"))
    }

    @Test func theLevelAutosaveIsDueOncePerLevelAndChangesNothing() throws {
        let session = try GameSession.newGame(resources: try #require(worldResources), afterOldTicks: 1_000)
        let w = session.world
        #expect(w.autosavedLevel == nil)
        let due = w.levelAutosaveDue
        let digest = w.stateDigest()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("autosave-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        w.savesDir = dir
        if due { #expect(w.saveNative(slot: 1) != nil) }
        #expect(w.stateDigest() == digest)              // asking and saving leave the game as it was
        w.autosavedLevel = w.level
        #expect(!w.levelAutosaveDue)                    // the same level is not saved twice
        w.autosavedLevel = "ELSEWHERE"
        w.keyboardCaptured = true                      // a script holds the keyboard: S would say CANNOT_SAVE
        #expect(!w.levelAutosaveDue)
    }
}

struct PlayLogCrashTests {
    func tempLog() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("playlog-\(UUID().uuidString)/BioForge.log")
    }

    @Test func aLogWithoutTheQuitLineIsAnUnexpectedEnd() {
        let url = tempLog()
        let first = PlayLog(file: url)
        #expect(!first.previousEndedUnexpectedly)       // no earlier log
        first.note("level CHAOS")
        let second = PlayLog(file: url)
        #expect(second.previousEndedUnexpectedly)
        #expect(second.previousTail()?.contains("level CHAOS") == true)
    }

    @Test func aLogEndingInQuitIsClean() {
        let url = tempLog()
        let first = PlayLog(file: url)
        first.note("level CHAOS")
        first.quit()
        #expect(!PlayLog(file: url).previousEndedUnexpectedly)
    }

    @Test func anEmptyPreviousLogIsNotACrash() {
        let url = tempLog()
        _ = PlayLog(file: url)
        #expect(!PlayLog(file: url).previousEndedUnexpectedly)
    }
}
