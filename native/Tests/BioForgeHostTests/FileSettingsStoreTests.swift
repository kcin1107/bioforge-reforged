import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

private final class RecordingLog: HostLog, @unchecked Sendable {
    private(set) var errors: [String] = []
    func info(_ category: String, _ message: String) {}
    func error(_ category: String, _ message: String) { errors.append("\(category): \(message)") }
}

struct FileSettingsStoreTests {
    /// A fresh folder per test (not created yet), removed afterwards.
    private func withFolder(_ body: (URL) throws -> Void) throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("BioForgeTests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        try body(dir)
    }

    @Test func everyValueTypeRoundTrips() throws {
        try withFolder { dir in
            let file = dir.appendingPathComponent("settings.json")
            let a = FileSettingsStore(file: file)
            a.set(42, forKey: "i"); a.set(true, forKey: "b"); a.set("text", forKey: "s")
            a.set(["x": [1, -1, 3]], forKey: "keys"); a.set(["a": "b"], forKey: "pad")
            let b = FileSettingsStore(file: file)
            #expect(b.integer(forKey: "i") == 42 && b.bool(forKey: "b") && b.string(forKey: "s") == "text")
            #expect(b.dictionary(forKey: "keys") as? [String: [Int]] == ["x": [1, -1, 3]])
            #expect(b.dictionary(forKey: "pad") as? [String: String] == ["a": "b"])
        }
    }

    @Test func settingsSaveThenApplyOnANewStore() throws {
        try withFolder { dir in
            let file = dir.appendingPathComponent("settings.json")
            Settings(sound: 10, music: 0, gamma: 90, subtitles: false, musicDevice: .adlib, language: "G").save(to: FileSettingsStore(file: file))
            let s = Settings()
            s.apply(defaults: FileSettingsStore(file: file))
            #expect(s.sound == 10 && s.music == 0 && s.gamma == 90 && !s.subtitles)
            #expect(s.musicDevice == .adlib && s.language == "G")
        }
    }

    @Test func keyBindingsSurviveAReload() throws {
        try withFolder { dir in
            let file = dir.appendingPathComponent("settings.json")
            var bindings = KeyBindings()
            let control = try #require(KeyBindings.controls.first)
            bindings.bind(0x04, to: control.id, slot: 0)       // HID "A"
            FileSettingsStore(file: file).set(bindings.propertyList, forKey: BindingsMigration.key)
            #expect(BindingsMigration.load(FileSettingsStore(file: file)) == bindings)
        }
    }

    @Test func padBindingsSurviveAReload() throws {
        try withFolder { dir in
            let file = dir.appendingPathComponent("settings.json")
            var pad = PadBindings()
            pad.bind(.a, to: "shoot")                             // not a direction: those can't be rebound
            pad.bind(nil, to: "use")
            FileSettingsStore(file: file).set(pad.propertyList, forKey: "PadBindings")
            let saved = try #require(FileSettingsStore(file: file).dictionary(forKey: "PadBindings") as? [String: String])
            #expect(PadBindings(propertyList: saved) == pad && pad != PadBindings())
        }
    }

    @Test func boolAndIntKeepTheirTypes() throws {
        try withFolder { dir in
            let file = dir.appendingPathComponent("settings.json")
            let a = FileSettingsStore(file: file)
            a.set(true, forKey: "b"); a.set(7, forKey: "n"); a.set(1, forKey: "one")
            let b = FileSettingsStore(file: file)
            #expect(b.object(forKey: "b") is Bool && b.integer(forKey: "b") == 1)
            #expect(b.object(forKey: "n") is Int && b.bool(forKey: "n"))
            #expect(b.object(forKey: "one") is Int && !(b.object(forKey: "one") is Bool))
        }
    }

    @Test func settingNilRemovesTheKey() throws {
        try withFolder { dir in
            let file = dir.appendingPathComponent("settings.json")
            let a = FileSettingsStore(file: file)
            a.set(1, forKey: "gone"); a.set(2, forKey: "kept")
            a.set(nil, forKey: "gone")
            #expect(a.object(forKey: "gone") == nil)
            let b = FileSettingsStore(file: file)
            #expect(b.object(forKey: "gone") == nil && b.integer(forKey: "kept") == 2)
            let text = String(decoding: try Data(contentsOf: file), as: UTF8.self)
            #expect(!text.contains("gone"))
        }
    }

    @Test func aCorruptFileIsAnEmptyStoreAndLogsOnce() throws {
        try withFolder { dir in
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let file = dir.appendingPathComponent("settings.json")
            try Data("{ not json".utf8).write(to: file)
            let log = RecordingLog()
            let store = FileSettingsStore(file: file, log: log)
            #expect(store.object(forKey: "x") == nil && log.errors.count == 1 && log.errors[0].hasPrefix("settings"))
            let text = String(decoding: try Data(contentsOf: file), as: UTF8.self)
            #expect(text == "{ not json")      // left alone until a `set`
            store.set(3, forKey: "x")
            #expect(FileSettingsStore(file: file).integer(forKey: "x") == 3 && log.errors.count == 1)
        }
    }

    @Test func aMissingFileIsSilentlyEmpty() throws {
        try withFolder { dir in
            let log = RecordingLog()
            #expect(FileSettingsStore(file: dir.appendingPathComponent("settings.json"), log: log).object(forKey: "x") == nil)
            #expect(log.errors.isEmpty)
        }
    }

    @Test func theFolderIsCreatedAndNoTempFilesStayBehind() throws {
        try withFolder { dir in
            let nested = dir.appendingPathComponent("a/b", isDirectory: true)
            let store = FileSettingsStore(file: nested.appendingPathComponent("settings.json"))
            for i in 0..<5 { store.set(i, forKey: "n") }
            let names = try FileManager.default.contentsOfDirectory(atPath: nested.path)
            #expect(names == ["settings.json"])
        }
    }
}
