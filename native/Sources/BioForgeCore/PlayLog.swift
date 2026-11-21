// The play log behind Help > Report a Bug: one line whenever the level, camera or Lex's health changes, Lex dies, the world warns or the app
// notes something, plus his position every ten seconds. Written to a file as it goes, so a crash leaves the lines before it: the next launch
// keeps that file as the previous session's log and a report includes its tail. A clean exit ends the log with a "quit" line (`quit()`); a previous
// log without one means the session ended unexpectedly (`previousEndedUnexpectedly`).
import Foundation

public final class PlayLog {
    static let positionEvery = 300                  // ticks: ten seconds at 30 Hz
    private let file: URL?
    private let previousFile: URL?
    private let capacity: Int
    private var handle: FileHandle?
    public private(set) var lines: [String] = []
    /// The previous session's log exists, has lines and does not end with the "quit" line: the app crashed or was killed.
    public let previousEndedUnexpectedly: Bool
    private var level: String?, camera: String?, hp: Int?, warnings = 0, nextPosition = 0, dead = false

    /// `file` nil keeps the log in memory only. An existing `file` becomes `<name>.previous.log`.
    public init(file: URL?, capacity: Int = 2000) {
        self.file = file
        self.capacity = capacity
        previousFile = file?.deletingPathExtension().appendingPathExtension("previous.log")
        guard let file, let previousFile else { previousEndedUnexpectedly = false; return }
        let fm = FileManager.default
        try? fm.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let last = (try? String(contentsOf: file, encoding: .utf8))?.split(separator: "\n").last
        previousEndedUnexpectedly = last.map { !$0.hasSuffix(" " + Self.quitText) } ?? false
        if fm.fileExists(atPath: file.path) {
            try? fm.removeItem(at: previousFile)
            try? fm.moveItem(at: file, to: previousFile)
        }
        fm.createFile(atPath: file.path, contents: nil)
        handle = try? FileHandle(forWritingTo: file)
    }

    static let quitText = "quit"

    /// The last line of a clean exit.
    public func quit() { note(Self.quitText) }

    public func note(_ text: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(text)"
        lines.append(line)
        if lines.count > capacity { lines.removeFirst(lines.count - capacity) }
        try? handle?.write(contentsOf: Data((line + "\n").utf8))
    }

    /// A new game or a loaded save: its tick count starts again and every field is news.
    public func restart() {
        level = nil; camera = nil; hp = nil; warnings = 0; nextPosition = 0; dead = false
    }

    /// Call once per tick.
    public func observe(_ w: World) {
        let t = w.tick
        if w.level != level { level = w.level; note("t\(t) level \(w.level)") }
        if let c = w.currentCamera, c != camera { camera = c; note("t\(t) camera \(c)") }
        for text in w.warnings.dropFirst(warnings) { note("t\(t) warning: \(text)") }
        warnings = w.warnings.count
        guard let lex = w.player else { return }
        let health = w.hitPoints(lex)
        if health != hp {
            if let hp { note("t\(t) hp \(hp) -> \(health)") }
            hp = health
        }
        if health <= 0, !dead { note("t\(t) Lex is dead (motion \(lex.motion ?? "none"))") }
        dead = health <= 0
        if t >= nextPosition, let p = lex.pos {
            nextPosition = t + Self.positionEvery
            note("t\(t) at (\(Int(p.x)), \(Int(p.y)), \(Int(p.z))) heading \(Int(lex.heading))")
        }
    }

    public func tail(_ count: Int = 400) -> String { lines.suffix(count).joined(separator: "\n") }

    /// The last lines of the session before this one, or nil when there was none.
    public func previousTail(_ count: Int = 200) -> String? {
        guard let previousFile, let text = try? String(contentsOf: previousFile, encoding: .utf8) else { return nil }
        return text.split(separator: "\n").suffix(count).joined(separator: "\n")
    }

    /// The report's text. `world` nil: no game is running.
    public func report(world: World?, app: String, comment: String = "") -> String {
        var out = ["BioForge bug report", app, "Written \(ISO8601DateFormatter().string(from: Date()))", ""]
        if !comment.isEmpty { out += ["What happened:", comment, ""] }
        out += ["WHERE YOU WERE"] + (world?.whereAmI() ?? ["No game was running."])
        out += ["", "THIS SESSION", tail()]
        if let previous = previousTail() { out += ["", "PREVIOUS SESSION (the end of it; after a crash, the lines before the crash)", previous] }
        return out.joined(separator: "\n") + "\n"
    }
}

extension World {
    /// Lines saying where the player is and what is going on, for a bug report.
    public func whereAmI() -> [String] {
        var out = ["Level \(level), camera \(currentCamera ?? "none"), tick \(tick), difficulty \(vm?.globals["_difficulty_level"].map { "\($0)" } ?? "?")"]
        if godMode { out.append("God mode: on") }
        if let lex = player {
            out.append("\(lex.name): HP \(hitPoints(lex)), motion \(lex.motion ?? "none"), combat \(lex.combat), heading \(Int(lex.heading))")
            if let p = lex.pos { out.append("Position (\(Int(p.x)), \(Int(p.y)), \(Int(p.z)))") }
            let carried = items.values.filter { $0.owner == lex.name }.map { "\($0.name) (\($0.slot ?? "?"))" }.sorted()
            out.append("Carrying: \(carried.isEmpty ? "nothing" : carried.joined(separator: ", "))")
        } else { out.append("No player figure.") }
        let others = figures.values.filter { $0 !== player && $0.pos != nil }.map { "\($0.name) HP \(hitPoints($0))" }.sorted()
        out.append("Figures: \(others.isEmpty ? "none" : others.joined(separator: ", "))")
        out.append("Scripts running: \((vm?.processes.map(\.block.name) ?? []).sorted().joined(separator: ", "))")
        out.append("Last keys: \(keyLog.suffix(30).map { "t\($0.tick) \($0.action)" }.joined(separator: ", "))")
        if !warnings.isEmpty { out.append("Warnings: \(warnings.suffix(20).joined(separator: " | "))") }
        return out
    }
}
