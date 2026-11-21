// The platform-neutral half of Help > Report a Bug: the report folder's contents (report.txt, a save of this moment, the session recordings,
// crash reports handed in by the shell). The shell adds its own crash-report lookup, the zip and the sheets.
import BioForgeCore
import Foundation

public enum BugReport {
    /// The report's second line, with the game data report's lines after it.
    public static func appLine(buildStamp: String, system: String, gameFolder: String?, language: String, dataReport: GameDataReport?) -> String {
        "App \(buildStamp), \(system), game folder “\(gameFolder ?? "none")”, language \(language)"
            + (dataReport.map { "\n" + $0.lines.joined(separator: "\n") } ?? "")
    }

    /// "BioForge Report 2026-01-02T03.04.05Z".
    public static func folderName(now: Date) -> String {
        "BioForge Report \(ISO8601DateFormatter().string(from: now).replacingOccurrences(of: ":", with: "."))"
    }

    /// After an unexpected end: keep the crashed game's recording out of the way of the next game's recorder, which would push it to
    /// Session.previous and a second game later delete it. Call before any game starts.
    public static func keepCrashedRecording(logs: URL) {
        let fm = FileManager.default
        let session = logs.appendingPathComponent("Session", isDirectory: true), crashed = logs.appendingPathComponent("Session.crashed", isDirectory: true)
        guard fm.fileExists(atPath: session.path) else { return }
        try? fm.removeItem(at: crashed)
        try? fm.moveItem(at: session, to: crashed)
    }

    /// Fills `folder` (which exists): the save of this moment, the recordings, `crashReports` as they are and report.txt.
    public static func assemble(in folder: URL, world: World?, playLog: PlayLog, app: String, comment: String, logs: URL, crashReports: [URL], now: Date = Date()) throws {
        let fm = FileManager.default
        if let world { world.recorder?.checkpoint(world) }     // before the report's save below, so the replay checks the state as played
        if let world {                                  // a save of this moment, written beside the report and not into the player's slots
            let saves = world.savesDir
            world.savesDir = folder
            world.saveNative(slot: 1)
            _ = world.takeFileError()                   // the report goes on without its save; no alert about a player slot
            world.savesDir = saves
        }
        let week = now.addingTimeInterval(-7 * 86400)   // the recording of this game and the one before it (ending in that checkpoint), and a crashed one of the last week
        for name in ["Session", "Session.previous", "Session.crashed"] {
            let dir = logs.appendingPathComponent(name, isDirectory: true)
            guard fm.fileExists(atPath: dir.path) else { continue }
            if name == "Session.crashed", (try? dir.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate).flatMap({ $0 > week }) != true { continue }
            try? fm.copyItem(at: dir, to: folder.appendingPathComponent(name, isDirectory: true))
        }
        for url in crashReports { try? fm.copyItem(at: url, to: folder.appendingPathComponent(url.lastPathComponent)) }
        try playLog.report(world: world, app: app, comment: comment).write(to: folder.appendingPathComponent("report.txt"), atomically: true, encoding: .utf8)
    }
}
