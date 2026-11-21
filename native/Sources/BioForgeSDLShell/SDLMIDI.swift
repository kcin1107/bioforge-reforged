// General MIDI for the SDL shell: TinySoundFont (CTinySoundFont) as the MIDISynth the AudioScheduler sends to, and where to look for a SoundFont.
import BioForgeCore
import BioForgeHost
import CSDL3
import CTinySoundFont
import Foundation

/// General MIDI through TinySoundFont, 44100 Hz stereo float, for SDLAudio's third stream. Like OPL2Stream: the main thread queues,
/// SDL's audio thread renders under the same lock, splitting each block at the messages' samples.
final class GMStream: MIDISynth, @unchecked Sendable {
    static let rate = 44_100
    static let gainDB: Float = 0
    private struct Message { let sample: Int; let status, data1, data2: UInt8 }      // plain values: no ARC on the audio thread
    private let lock = NSLock()
    private var synth: OpaquePointer?                  // tsf*; nil = no SoundFont (messages dropped, render is silence)
    private var queue: [Message] = []
    private var head = 0, clock = 0, last = 0          // clock = frames rendered (the playhead); last = the newest queued sample

    deinit { if let synth { tsf_close(synth) } }

    var isLoaded: Bool { lock.withLock { synth != nil } }

    /// Parses outside the lock, sets up all 16 channels, then swaps it in. Returns the preset count, or nil if it isn't a usable SF2.
    func load(_ data: Data) -> Int? {
        guard data.count > 12, data.prefix(4).elementsEqual("RIFF".utf8), data.dropFirst(8).prefix(4).elementsEqual("sfbk".utf8) else { return nil }
        let loaded: OpaquePointer? = data.withUnsafeBytes { tsf_load_memory($0.baseAddress, Int32($0.count)) }
        guard let loaded else { return nil }
        let presets = Int(tsf_get_presetcount(loaded))
        guard presets > 0 else { tsf_close(loaded); return nil }
        tsf_set_output(loaded, TSF_STEREO_INTERLEAVED, Int32(Self.rate), Self.gainDB)
        _ = tsf_set_max_voices(loaded, 128)
        Self.setUpChannels(loaded)
        let old = lock.withLock { () -> OpaquePointer? in
            let old = synth
            synth = loaded; queue.removeAll(); head = 0; last = clock
            return old
        }
        if let old { tsf_close(old) }
        return presets
    }

    /// Every channel needs a preset before its first note (tsf ignores the others); this also allocates the channel table off the audio thread.
    private static func setUpChannels(_ f: OpaquePointer) {
        for ch in 0..<16 { _ = tsf_channel_set_presetnumber(f, Int32(ch), 0, ch == 9 ? 1 : 0) }
    }

    /// MIDISynth: `seconds` after the playhead, never before the message queued before it (FIFO).
    func send(_ bytes: [UInt8], after seconds: Double) {
        lock.lock(); defer { lock.unlock() }
        guard synth != nil, let status = bytes.first else { return }
        let at = max(last, clock + Int((max(0, seconds) * Double(Self.rate)).rounded()))
        queue.append(Message(sample: at, status: status, data1: bytes.count > 1 ? bytes[1] : 0, data2: bytes.count > 2 ? bytes[2] : 0))
        last = at
    }

    /// The next `frames` stereo frames (2 * frames floats) for SDL's audio thread.
    func render(into out: UnsafeMutablePointer<Float>, frames: Int) {
        lock.lock(); defer { lock.unlock() }
        guard let synth else { out.update(repeating: 0, count: 2 * frames); clock += frames; return }
        var done = 0
        while done < frames {
            while head < queue.count && queue[head].sample <= clock { apply(queue[head], synth); head += 1 }
            let n = head < queue.count ? min(frames - done, queue[head].sample - clock) : frames - done
            tsf_render_float(synth, out + 2 * done, Int32(n), 0)
            done += n; clock += n
        }
        if head > 1024 { queue.removeFirst(head); head = 0 }
    }

    /// Stop: voices cut, queue dropped (tsf_reset frees the channel table, so the channels are set up again).
    func reset() {
        lock.withLock {
            if let synth { tsf_reset(synth); Self.setUpChannels(synth) }
            queue.removeAll(); head = 0; last = clock
        }
    }

    /// XMIDISong passes channel messages only.
    private func apply(_ m: Message, _ f: OpaquePointer) {
        let ch = Int32(m.status & 0x0F), a = Int32(m.data1), b = Int32(m.data2)
        switch m.status & 0xF0 {
        case 0x80: tsf_channel_note_off(f, ch, a)
        case 0x90: if b == 0 { tsf_channel_note_off(f, ch, a) } else { _ = tsf_channel_note_on(f, ch, a, Float(b) / 127) }
        case 0xB0: _ = tsf_channel_midi_control(f, ch, a, b)
        case 0xC0: _ = tsf_channel_set_presetnumber(f, ch, a, ch == 9 ? 1 : 0)
        case 0xE0: _ = tsf_channel_set_pitchwheel(f, ch, a | b << 7)
        default: break
        }
    }
}

/// Where a SoundFont (.sf2) may be: the "SoundFont" setting, the per-user folder, the program's folders, the system's files.
struct SoundFontSearch {
    static let settingKey = "SoundFont"
    var programFolders: [URL]
    var system: [String]

    static var standard: SoundFontSearch {
        var folders: [URL] = []
        if let base = SDL_GetBasePath().map({ URL(fileURLWithPath: String(cString: $0), isDirectory: true) }) {
            folders += [base, base.appendingPathComponent("../share/BioForge", isDirectory: true).standardizedFileURL]
        }
        if let image = ProcessInfo.processInfo.environment["APPIMAGE"], !image.isEmpty {
            folders.append(URL(fileURLWithPath: image).deletingLastPathComponent())
        }
        var system: [String] = []
        #if os(Linux)
        system = ["/usr/share/soundfonts/default.sf2", "/usr/share/sounds/sf2/default-GM.sf2", "/usr/share/sounds/sf2/FluidR3_GM.sf2",
                  "/usr/share/soundfonts/FluidR3_GM.sf2", "/usr/share/sounds/sf2/TimGM6mb.sf2"]
        #endif
        return SoundFontSearch(programFolders: folders, system: system)
    }

    static let none = SoundFontSearch(programFolders: [], system: [])

    /// The first match: the setting (a file path), the first *.sf2 (by name) in the support folder, then in each program folder, then the first system file.
    func find(store: SettingsStore, support: URL) -> URL? {
        let fm = FileManager.default
        if let path = store.string(forKey: Self.settingKey), !path.isEmpty, fm.fileExists(atPath: path) { return URL(fileURLWithPath: path) }
        for folder in [support] + programFolders {
            let names = (try? fm.contentsOfDirectory(atPath: folder.path)) ?? []
            if let name = names.sorted().first(where: { $0.lowercased().hasSuffix(".sf2") }) { return folder.appendingPathComponent(name) }
        }
        return system.first { fm.fileExists(atPath: $0) }.map { URL(fileURLWithPath: $0) }
    }
}
