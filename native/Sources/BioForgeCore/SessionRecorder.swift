// The session recording behind exact replay (SessionReplay.swift): a folder with `session.jsonl` and, for a session that began from a save,
// a copy of that save's play directory (`start.d`). The first line is the header (format version, how the session began, the RNG state, the
// flags and settings the logic reads); then one line per input call `{"t":frame,"e":method,"a":[ints],"s":text}` with the frame (World.frames, one
// per GameSession.tick) the call arrived at, so a replay applies it before the same next frame, and `{"t":frame,"digest":...}` checkpoints (World.stateDigest). Written as it goes, so a
// crash leaves everything before it. A new recorder keeps the folder it replaces as `<name>.previous`, like PlayLog.
import Foundation

public final class SessionRecorder {
    public static let version = 1
    static let fileName = "session.jsonl", startFolder = "start.d"

    struct Header: Codable {
        var version: Int
        var start: String                           // "new" or "save" (the play directory copied to start.d)
        var rng: PyRandom.State
        var autoDifficulty: Bool
        var sound: Int, music: Int, gamma: Int, subtitles: Bool
        var language: String?                       // absent in older recordings: English
    }

    /// One input call or checkpoint.
    struct Line: Codable {
        var t: Int?, e: String?, a: [Int]?, s: String?, digest: String?
    }

    public let directory: URL
    /// Where the recording this one replaced went.
    public var previousDirectory: URL { directory.deletingLastPathComponent().appendingPathComponent(directory.lastPathComponent + ".previous", isDirectory: true) }
    private var handle: FileHandle?
    /// > 0 while an input call is already being recorded (keyEvent -> keyDown) or the tick itself makes one (ADDKEY): those are not recorded again.
    var depth = 0

    /// Starts recording `session` (a new game, or loaded from `session.origin`) into `directory`; an existing `directory` becomes `<name>.previous`.
    public init(directory: URL, session: GameSession) throws {
        self.directory = directory
        let fm = FileManager.default
        try fm.createDirectory(at: directory.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fm.fileExists(atPath: directory.path) {
            try? fm.removeItem(at: previousDirectory)
            try? fm.moveItem(at: directory, to: previousDirectory)
        }
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        if let origin = session.origin { try fm.copyItem(at: origin, to: directory.appendingPathComponent(Self.startFolder, isDirectory: true)) }
        let w = session.world
        write(Header(version: Self.version, start: session.origin == nil ? "new" : "save", rng: w.rng.state, autoDifficulty: session.autoDifficulty,
                     sound: w.settings.sound, music: w.settings.music, gamma: w.settings.gamma, subtitles: w.settings.subtitles,
                     language: w.settings.language), create: true)
    }

    func enter(_ name: String, _ tick: Int, _ args: [Int] = [], _ text: String? = nil) {
        if depth == 0 { write(Line(t: tick, e: name, a: args.isEmpty ? nil : args, s: text)) }
        depth += 1
    }
    func leave() { depth -= 1 }

    /// A checkpoint: the world's digest at its current frame, which a replay checks.
    public func checkpoint(_ w: World) { write(Line(t: w.frames, digest: w.stateDigest())) }

    /// Stops recording and closes the file. Windows cannot move a folder with an open file in it, so a recorder must be closed
    /// before another one for the same `directory` turns this recording into `<name>.previous`.
    public func close() { try? handle?.close(); handle = nil }

    private func write<T: Encodable>(_ value: T, create: Bool = false) {
        let url = directory.appendingPathComponent(Self.fileName)
        if create { FileManager.default.createFile(atPath: url.path, contents: nil); handle = try? FileHandle(forWritingTo: url) }
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        guard let data = try? enc.encode(value) else { return }
        try? handle?.write(contentsOf: data + Data("\n".utf8))
    }
}
