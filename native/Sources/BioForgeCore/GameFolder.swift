// The user's BioForge folder (contains BIOFORGE.EXE, ROOMS/, DATA/ ...). Game data is never bundled.
// DOS names are upper case; lookups are case-insensitive, per path component.
import Foundation

public struct GameFolder: Sendable {
    public let url: URL
    public init(_ url: URL) { self.url = url }

    /// BIOFORGE_DATA environment variable (development / tests), or nil.
    public static func fromEnvironment() -> GameFolder? {
        guard let p = ProcessInfo.processInfo.environment["BIOFORGE_DATA"], !p.isEmpty else { return nil }
        return GameFolder(URL(fileURLWithPath: p, isDirectory: true))
    }

    /// True if the folder looks like a game folder (has BIOFORGE.EXE and ROOMS/).
    public var isValid: Bool { resolve("BIOFORGE.EXE") != nil && resolve("ROOMS") != nil }

    /// The native play directory GAMEDAT: a sibling of the game folder (game/app/GAMEDAT next to game/app/Bioforge), nil if absent.
    public var gamedat: URL? { GameFolder(url.standardizedFileURL.deletingLastPathComponent()).resolve("GAMEDAT") }

    /// The shipped initial level objects (INITGAME/ inside the game folder), nil if absent.
    public var initgame: URL? { resolve("INITGAME") }

    /// Resolve "ROOMS/ce11.cam" (any case, '/'-separated) to an existing file URL.
    public func resolve(_ path: String) -> URL? {
        var cur = url
        for comp in path.split(separator: "/") {
            guard let names = try? FileManager.default.contentsOfDirectory(atPath: cur.path),
                  let hit = names.first(where: { $0.caseInsensitiveCompare(String(comp)) == .orderedSame })
            else { return nil }
            cur.appendPathComponent(hit)
        }
        return cur
    }

    public func read(_ path: String) throws -> [UInt8] {
        guard let u = resolve(path) else { throw FormatError("\(path) not found in \(url.path)") }
        return [UInt8](try Data(contentsOf: u))
    }

    /// Sorted file names in a sub-folder (e.g. "ROOMS"), optionally filtered by extension (case-insensitive).
    public func list(_ dir: String, ext: String? = nil) -> [String] {
        guard let d = resolve(dir), let names = try? FileManager.default.contentsOfDirectory(atPath: d.path) else { return [] }
        return names.filter { ext == nil || ($0 as NSString).pathExtension.caseInsensitiveCompare(ext!) == .orderedSame }.sorted()
    }
}
