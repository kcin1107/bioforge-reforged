// Recognising the game data: every file the port needs is looked up by size and the MD5 of its first 5000 bytes (ScummVM's detection
// convention) in KnownData (GOG 2.1.0.14, English). Missing files stop the game; files that differ still run but are reported.
// Foundation only, so the MD5 (RFC 1321) is written out here.
import Foundation

public struct GameDataReport: Sendable, Equatable {
    /// Required files not found (paths as in KnownData).
    public var missing: [String]
    /// Files found whose size or partial MD5 differs from the known release.
    public var unknown: [String]
    public var isKnownRelease: Bool { missing.isEmpty && unknown.isEmpty }

    /// One line for the play log and the bug report.
    public var summary: String {
        if isKnownRelease { return "game data: recognised as \(KnownData.release)" }
        func part(_ label: String, _ names: [String]) -> String? {
            names.isEmpty ? nil : "\(names.count) \(label) (\(names.prefix(5).joined(separator: ", "))\(names.count > 5 ? ", ..." : ""))"
        }
        return "game data: not \(KnownData.release): " + [part("missing", missing), part("unknown", unknown)].compactMap { $0 }.joined(separator: ", ")
    }

    /// The summary and every file named, for the bug report.
    public var lines: [String] { [summary] + missing.map { "  missing: \($0)" } + unknown.map { "  unknown: \($0)" } }
}

public enum GameData {
    public static let prefixLength = 5000

    public static func check(_ folder: GameFolder) -> GameDataReport {
        var listings: [String: [String: String]] = [:]      // directory path -> upper-case name -> actual name
        func names(in dir: URL) -> [String: String] {
            if let hit = listings[dir.path] { return hit }
            let list = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
            let map = Dictionary(list.map { ($0.uppercased(), $0) }, uniquingKeysWith: { a, _ in a })
            listings[dir.path] = map
            return map
        }
        var report = GameDataReport(missing: [], unknown: [])
        for known in KnownData.files {
            var url = folder.url
            var found = true
            for comp in known.path.split(separator: "/") {
                guard let name = names(in: url)[String(comp)] else { found = false; break }
                url.appendPathComponent(name)
            }
            guard found else { report.missing.append(known.path); continue }
            guard let (size, head) = readHead(url), size == known.size, MD5.hex(head) == known.md5 else { report.unknown.append(known.path); continue }
        }
        return report
    }

    /// The file's size and its first `prefixLength` bytes, nil if it can't be read.
    private static func readHead(_ url: URL) -> (Int, [UInt8])? {
        guard let h = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? h.close() }
        guard let end = try? h.seekToEnd(), (try? h.seek(toOffset: 0)) != nil, let data = try? h.read(upToCount: prefixLength) else { return nil }
        return (Int(end), [UInt8](data))
    }
}

/// MD5 (RFC 1321).
public enum MD5 {
    private static let s: [UInt32] = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21]
    private static let k: [UInt32] = (0..<64).map { UInt32(truncatingIfNeeded: Int64(abs(sin(Double($0 + 1))) * 4294967296.0)) }

    public static func hex(_ message: [UInt8]) -> String {
        var a0: UInt32 = 0x67452301, b0: UInt32 = 0xefcdab89, c0: UInt32 = 0x98badcfe, d0: UInt32 = 0x10325476
        var data = message
        data.append(0x80)
        while data.count % 64 != 56 { data.append(0) }
        let bits = UInt64(message.count) &* 8
        for i in 0..<8 { data.append(UInt8(truncatingIfNeeded: bits >> (8 * UInt64(i)))) }
        for chunk in stride(from: 0, to: data.count, by: 64) {
            let m = (0..<16).map { i -> UInt32 in
                let o = chunk + 4 * i
                return UInt32(data[o]) | UInt32(data[o + 1]) << 8 | UInt32(data[o + 2]) << 16 | UInt32(data[o + 3]) << 24
            }
            var a = a0, b = b0, c = c0, d = d0
            for i in 0..<64 {
                var f: UInt32, g: Int
                switch i / 16 {
                case 0: f = (b & c) | (~b & d); g = i
                case 1: f = (d & b) | (~d & c); g = (5 * i + 1) % 16
                case 2: f = b ^ c ^ d; g = (3 * i + 5) % 16
                default: f = c ^ (b | ~d); g = (7 * i) % 16
                }
                f = f &+ a &+ k[i] &+ m[g]
                a = d; d = c; c = b
                let r = s[(i / 16) * 4 + i % 4]
                b = b &+ (f << r | f >> (32 - r))
            }
            a0 = a0 &+ a; b0 = b0 &+ b; c0 = c0 &+ c; d0 = d0 &+ d
        }
        return [a0, b0, c0, d0].flatMap { v in (0..<4).map { String(format: "%02x", (v >> (8 * UInt32($0))) & 0xff) } }.joined()
    }
}
