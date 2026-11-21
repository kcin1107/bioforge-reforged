@testable import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

struct BugReportTextTests {
    @Test func appLineIsPinned() {
        #expect(BugReport.appLine(buildStamp: "0.1 (build 3, abc)", system: "macOS Version 15", gameFolder: "Bioforge", language: "E", dataReport: nil)
                == "App 0.1 (build 3, abc), macOS Version 15, game folder “Bioforge”, language E")
        #expect(BugReport.appLine(buildStamp: "development build", system: "macOS Version 15", gameFolder: nil, language: "G", dataReport: nil)
                == "App development build, macOS Version 15, game folder “none”, language G")
        let report = GameDataReport(missing: ["A.DAT"], unknown: ["B.DAT"])
        #expect(BugReport.appLine(buildStamp: "x", system: "s", gameFolder: "g", language: "F", dataReport: report)
                == "App x, s, game folder “g”, language F\n" + report.lines.joined(separator: "\n"))
    }

    @Test func folderNameHasNoColons() {
        #expect(BugReport.folderName(now: Date(timeIntervalSince1970: 1_800_000_000)) == "BioForge Report 2027-01-15T08.00.00Z")
    }

    @Test func keepCrashedRecordingMovesSessionAndReplacesAnOldOne() throws {
        let logs = try tempDir("logs")
        defer { try? FileManager.default.removeItem(at: logs) }
        let fm = FileManager.default
        BugReport.keepCrashedRecording(logs: logs)                // nothing to keep: no error
        for (name, text) in [("Session", "new"), ("Session.crashed", "old")] {
            let d = logs.appendingPathComponent(name, isDirectory: true)
            try fm.createDirectory(at: d, withIntermediateDirectories: true)
            try Data(text.utf8).write(to: d.appendingPathComponent("session.jsonl"))
        }
        BugReport.keepCrashedRecording(logs: logs)
        #expect(!fm.fileExists(atPath: logs.appendingPathComponent("Session").path))
        #expect(try String(contentsOf: logs.appendingPathComponent("Session.crashed/session.jsonl"), encoding: .utf8) == "new")
    }
}

@Suite(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct BugReportAssembleTests {
    private func session(_ logs: URL, _ name: String, daysOld: Double? = nil) throws {
        let d = logs.appendingPathComponent(name, isDirectory: true)
        try FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        try Data(name.utf8).write(to: d.appendingPathComponent("session.jsonl"))
        if let daysOld { try FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(-daysOld * 86400)], ofItemAtPath: d.path) }
    }

    @Test func assemblesSaveRecordingsCrashReportsAndText() throws {
        let s = try GameSession.newGame(resources: try #require(hostResources)), w = s.world
        let logs = try tempDir("report-logs"), folder = try tempDir("report-folder"), crashDir = try tempDir("report-crash")
        defer { for d in [logs, folder, crashDir] { try? FileManager.default.removeItem(at: d) } }
        let fm = FileManager.default
        try session(logs, "Session"); try session(logs, "Session.previous"); try session(logs, "Session.crashed", daysOld: 8)
        let crash = crashDir.appendingPathComponent("BioForge-2027.ips")
        try Data("crash".utf8).write(to: crash)
        let previous = URL(fileURLWithPath: "/previous")
        w.savesDir = previous
        let log = PlayLog(file: nil)
        try BugReport.assemble(in: folder, world: w, playLog: log, app: "App test line", comment: "it broke", logs: logs, crashReports: [crash])
        #expect(w.savesDir == previous)
        #expect(fm.fileExists(atPath: folder.appendingPathComponent("GAME1.IM1").path))
        #expect(fm.fileExists(atPath: folder.appendingPathComponent("Session/session.jsonl").path))
        #expect(fm.fileExists(atPath: folder.appendingPathComponent("Session.previous/session.jsonl").path))
        #expect(!fm.fileExists(atPath: folder.appendingPathComponent("Session.crashed").path), "a crashed recording over a week old is left out")
        #expect(fm.fileExists(atPath: folder.appendingPathComponent("BioForge-2027.ips").path))
        let text = try String(contentsOf: folder.appendingPathComponent("report.txt"), encoding: .utf8)
        #expect(text.contains("App test line") && text.contains("it broke"))

        try session(logs, "Session.crashed", daysOld: 1)
        let second = try tempDir("report-folder2")
        defer { try? fm.removeItem(at: second) }
        try BugReport.assemble(in: second, world: nil, playLog: log, app: "App", comment: "", logs: logs, crashReports: [])
        #expect(fm.fileExists(atPath: second.appendingPathComponent("Session.crashed/session.jsonl").path))
        #expect(try String(contentsOf: second.appendingPathComponent("report.txt"), encoding: .utf8).contains("No game was running."))
    }
}
