// Options settings of the original game (re/interp/settings.py; NOTES "Options settings").
//
// INSTALL.OPT is a `Key=Value` text file (CRLF, keys case-insensitive). The engine reads `Soundvol` and `Musicvol` (default 100),
// `Gamma` (default 30) and `subtitles` (default 1) at startup and the options dialog writes them back. The port reads the user's
// INSTALL.OPT for the initial values but never writes the game folder: the app keeps changed values in UserDefaults (they win when
// present) through `onChange`.
//
//   Gamma.offset(g)       FUN_1100_0e6f: (g * 32 - 960) / 100 with C truncation, added to every 6-bit palette channel
//   Gamma.apply(...)      the same step on the 8-bit palette the pipeline stores (CAMImage.palette: c * 255 / 63)
//   MasterVolume.table    FUN_1028_1da5 / FUN_1100_0dc2: the effect master-volume table at mgr + 0x12f
//   musicDevice           the music driver INSTALL.EXE installed (settings.music_device): .adlib for MusicCardId 1...3 (Adlib,
//                         Sound Blaster, SB Pro/16), .generalMIDI for 4...7 (AWE32, Wave Blaster, SCC-1, MPU-401) or a missing /
//                         unknown id, nil for MUSIC=OFF or id 0. The original never changes it in game; the app lets the player
//                         switch it (Game > Music Device) and keeps that choice in UserDefaults.
//   language              "E", "G" or "F": speech, text and the intro (INSTALL.OPT `language=`, read once at start-up, 1150.c ~369). The app
//                         lets the player switch it (Game > Language) and keeps that choice in UserDefaults.
import Foundation

/// The few key-value calls `Settings` needs, with UserDefaults' own signatures: the Mac app passes UserDefaults, other hosts a file- or memory-backed store.
public protocol SettingsStore: AnyObject {
    func object(forKey defaultName: String) -> Any?
    func integer(forKey defaultName: String) -> Int
    func bool(forKey defaultName: String) -> Bool
    func string(forKey defaultName: String) -> String?
    func dictionary(forKey defaultName: String) -> [String: Any]?
    func set(_ value: Any?, forKey defaultName: String)
}

extension UserDefaults: SettingsStore {}

public final class Settings: @unchecked Sendable {
    public var sound: Int, music: Int, gamma: Int
    public var subtitles: Bool
    public var musicDevice: MusicArrangement?
    public var language: String
    /// Called when the player persists a change (the app stores the values in UserDefaults).
    public var onChange: (@Sendable () -> Void)?

    public init(sound: Int = 100, music: Int = 100, gamma: Int = 30, subtitles: Bool = true, musicDevice: MusicArrangement? = .generalMIDI,
                language: String = "E") {
        self.sound = sound; self.music = music; self.gamma = gamma; self.subtitles = subtitles; self.musicDevice = musicDevice; self.language = language
    }

    public static let languages = ["E", "G", "F"]

    /// Parsed INSTALL.OPT -> "E", "G" or "F": the first character of `language=` (an unknown or missing one counts as English).
    public static func language(_ v: [String: String]) -> String {
        let c = v["language"].map { String($0.prefix(1)).uppercased() } ?? "E"
        return languages.contains(c) ? c : "E"
    }

    /// Parsed INSTALL.OPT -> the music device (see the header).
    public static func musicDevice(_ v: [String: String]) -> MusicArrangement? {
        if v["music"]?.uppercased() == "OFF" { return nil }
        let card = v["musiccardid"].flatMap { Int($0) } ?? 7
        if card == 0 { return nil }
        return (1...3).contains(card) ? .adlib : .generalMIDI
    }

    /// INSTALL.OPT text -> {lower-case key: value}; lines without "=" are ignored.
    public static func parseInstallOpt(_ text: String) -> [String: String] {
        var out: [String: String] = [:]
        for line in text.split(whereSeparator: \.isNewline) {
            guard let eq = line.firstIndex(of: "=") else { continue }
            out[line[..<eq].trimmingCharacters(in: .whitespaces).lowercased()] = line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces)
        }
        return out
    }

    public convenience init(installOpt text: String) {
        let v = Self.parseInstallOpt(text)
        func number(_ key: String, _ fallback: Int) -> Int { v[key].flatMap { Int($0) } ?? fallback }
        self.init(sound: number("soundvol", 100), music: number("musicvol", 100), gamma: number("gamma", 30), subtitles: number("subtitles", 1) != 0,
                  musicDevice: Self.musicDevice(v), language: Self.language(v))
    }

    /// The values of the user's INSTALL.OPT, or the engine defaults when it is missing.
    public static func load(game: GameFolder) -> Settings {
        guard let url = game.resolve("INSTALL.OPT"), let data = try? Data(contentsOf: url) else { return Settings() }
        return Settings(installOpt: String(decoding: data, as: UTF8.self))
    }

    static let defaultsKeys = (sound: "Soundvol", music: "Musicvol", gamma: "Gamma", subtitles: "Subtitles", device: "MusicDevice", language: "Language")

    /// Values the player changed earlier win over INSTALL.OPT.
    public func apply(defaults: SettingsStore) {
        let k = Self.defaultsKeys
        if defaults.object(forKey: k.sound) != nil { sound = defaults.integer(forKey: k.sound) }
        if defaults.object(forKey: k.music) != nil { music = defaults.integer(forKey: k.music) }
        if defaults.object(forKey: k.gamma) != nil { gamma = defaults.integer(forKey: k.gamma) }
        if defaults.object(forKey: k.subtitles) != nil { subtitles = defaults.bool(forKey: k.subtitles) }
        if let device = defaults.string(forKey: k.device) { musicDevice = MusicArrangement(rawValue: device) }   // "off" -> nil
        if let l = defaults.string(forKey: k.language), Self.languages.contains(l) { language = l }
    }

    public func save(to defaults: SettingsStore) {
        let k = Self.defaultsKeys
        defaults.set(sound, forKey: k.sound); defaults.set(music, forKey: k.music)
        defaults.set(gamma, forKey: k.gamma); defaults.set(subtitles, forKey: k.subtitles)
        defaults.set(musicDevice?.rawValue ?? "off", forKey: k.device); defaults.set(language, forKey: k.language)
    }

    /// The values were persisted (OK on a panel, or the gamma keys).
    public func persist() { onChange?() }
}

public enum Gamma {
    /// FUN_1100_0e6f: DAT_49be = (g * 0x20 - 0x3c0) / 100 (C division truncates toward zero): 0 -> -9, 30 -> 0, 50 -> 6, 100 -> 22.
    public static func offset(_ g: Int) -> Int { (g * 32 - 960) / 100 }

    /// 256 8-bit channel values after the gamma step (FUN_10e8_16bb): back to the 6-bit VGA value the CAM palette started from,
    /// add the offset, clamp 0...63, expand with c * 255 / 63 as CAMImage.palette does. The same offset applies to R, G and B.
    public static func lut(_ g: Int) -> [UInt8] {
        let off = offset(g)
        return (0..<256).map { UInt8(min(255, max(0, min(63, ($0 * 63 + 254) / 255 + off)) * 255 / 63)) }
    }

    /// A 768-byte 8-bit RGB palette after the gamma step (presentation only: oracle palettes and indexed frames stay as they are).
    public static func apply(to palette: [UInt8], gamma g: Int) -> [UInt8] {
        let table = lut(g)
        return palette.map { table[Int($0)] }
    }
}

public enum MasterVolume {
    /// FUN_1100_0dc2 -> FUN_1028_1da5: table[i] = (i * v) >> 8, v = min(255, sfx * 255 / 100); the final voice volume is
    /// table[script volume]. sfx < 1 disables effects (FUN_1028_08f6 stops every voice): a table of zeros.
    public static func table(_ sfx: Int) -> [Int] {
        if sfx < 1 { return [Int](repeating: 0, count: 256) }
        let v = min(255, sfx * 255 / 100)
        return (0..<256).map { ($0 * v) >> 8 }
    }
}
