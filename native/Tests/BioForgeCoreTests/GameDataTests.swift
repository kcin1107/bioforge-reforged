// Game data detection: MD5 against the RFC 1321 vectors; the real GOG folder is recognised; missing and changed files are named.
import Foundation
import Testing
@testable import BioForgeCore

struct MD5Tests {
    @Test func rfc1321Vectors() {
        let vectors = [("", "d41d8cd98f00b204e9800998ecf8427e"), ("a", "0cc175b9c0f1b6a831c399e269772661"), ("abc", "900150983cd24fb0d6963f7d28e17f72"),
                       ("message digest", "f96b697d7cb7938d525a2f31aaf161d0"),
                       ("abcdefghijklmnopqrstuvwxyz", "c3fcd3d76192e4007dfb496cca67e13b"),
                       ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", "d174ab98d277d9f5a5611c2c9f419d9f"),
                       ("12345678901234567890123456789012345678901234567890123456789012345678901234567890", "57edf4a22be3c955ac49da2e2107b67a")]
        for (text, digest) in vectors { #expect(MD5.hex(Array(text.utf8)) == digest, "\(text)") }
    }
}

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct GameDataTests {
    @Test func realFolderIsRecognised() throws {
        let start = Date()
        let report = GameData.check(try requireGame())
        print("GameData.check: \(Int(Date().timeIntervalSince(start) * 1000)) ms")
        #expect(report.missing.isEmpty && report.unknown.isEmpty)
        #expect(report.summary == "game data: recognised as GOG 2.1.0.14 (English)")
    }

    @Test func missingAndChangedFilesAreNamed() throws {
        let real = try requireGame()
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory.appendingPathComponent("gamedata-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: tmp) }
        for entry in KnownData.files {
            let dest = tmp.appendingPathComponent(entry.path.lowercased())          // lower case: lookups ignore case
            try fm.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            let source = try #require(real.resolve(entry.path))
            do { try fm.createSymbolicLink(at: dest, withDestinationURL: source) }
            catch { try fm.copyItem(at: source, to: dest) }                       // Windows allows symbolic links only in Developer Mode
        }
        let gone = "ROOMS/CE11.CAM", changed = "DATA/MOUSE.SHP"
        try fm.removeItem(at: tmp.appendingPathComponent(gone.lowercased()))
        let copy = tmp.appendingPathComponent(changed.lowercased())
        var bytes = [UInt8](try Data(contentsOf: copy))
        try fm.removeItem(at: copy)
        bytes[10] ^= 0xff
        try Data(bytes).write(to: copy)
        let report = GameData.check(GameFolder(tmp))
        #expect(report.missing == [gone])
        #expect(report.unknown == [changed])
        #expect(report.summary.contains("1 missing (\(gone))") && report.summary.contains("1 unknown (\(changed))"))
    }
}
