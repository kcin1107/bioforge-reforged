// Where the app keeps its files, kept apart from AppKit so every shell can say where things go. The Mac app uses `.macOS`;
// other hosts build one from their own data and log folders.
import BioForgeCore
import Foundation

public struct HostPaths: Sendable {
    /// Per-user data (saves, autosaves, the High-Resolution Art packs), logs (play log, session recordings, bug reports) and the folder of the settings file.
    public let support: URL, logs: URL, config: URL
    public init(support: URL, logs: URL, config: URL? = nil) { self.support = support; self.logs = logs; self.config = config ?? support }

    public var saves: URL { support.appendingPathComponent("Saves", isDirectory: true) }
    public var autosaves: URL { support.appendingPathComponent("Autosaves", isDirectory: true) }
    public var hiRes: URL { support.appendingPathComponent("HD", isDirectory: true) }
    public var settingsFile: URL { config.appendingPathComponent("settings.json") }
    public var logFile: URL { logs.appendingPathComponent("BioForge.log") }
    public var sessions: URL { logs.appendingPathComponent("Session", isDirectory: true) }
    public var reports: URL { logs.appendingPathComponent("Reports", isDirectory: true) }

    /// ~/Library/Application Support/BioForge and ~/Library/Logs/BioForge.
    public static var macOS: HostPaths {
        let fm = FileManager.default
        return HostPaths(support: fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("BioForge", isDirectory: true),
                         logs: fm.urls(for: .libraryDirectory, in: .userDomainMask)[0].appendingPathComponent("Logs/BioForge", isDirectory: true))
    }

    /// The XDG Base Directory folders: $XDG_DATA_HOME, $XDG_STATE_HOME and $XDG_CONFIG_HOME (an empty or relative value is ignored) under BioForge.
    public static func linux(env: [String: String] = ProcessInfo.processInfo.environment, home: URL = FileManager.default.homeDirectoryForCurrentUser) -> HostPaths {
        func folder(_ variable: String, _ fallback: String) -> URL {
            let base = env[variable].flatMap { $0.hasPrefix("/") ? URL(fileURLWithPath: $0, isDirectory: true) : nil }
                ?? home.appendingPathComponent(fallback, isDirectory: true)
            return base.appendingPathComponent("BioForge", isDirectory: true)
        }
        return HostPaths(support: folder("XDG_DATA_HOME", ".local/share"), logs: folder("XDG_STATE_HOME", ".local/state"), config: folder("XDG_CONFIG_HOME", ".config"))
    }

    /// %APPDATA%\BioForge for data and settings, %APPDATA%\BioForge\Logs for logs; nil without APPDATA.
    public static func windows(env: [String: String] = ProcessInfo.processInfo.environment) -> HostPaths? {
        guard let appData = env["APPDATA"], !appData.isEmpty else { return nil }
        let root = URL(fileURLWithPath: appData, isDirectory: true).appendingPathComponent("BioForge", isDirectory: true)
        return HostPaths(support: root, logs: root.appendingPathComponent("Logs", isDirectory: true))
    }
}

extension GameFolder {
    /// The chosen folder, or a game folder up to two levels inside it (GOG: <install>/app/Bioforge).
    public static func find(in url: URL) -> GameFolder? {
        var level = [url]
        for _ in 0...2 {
            if let hit = level.lazy.map(GameFolder.init).first(where: \.isValid) { return hit }
            level = level.flatMap { dir in
                ((try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.isDirectoryKey], options: .skipsHiddenFiles)) ?? [])
                    .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            }
        }
        return nil
    }
}
