// The SDL shell's sound: the Host's AudioScheduler (what plays when) over three SDL_AudioStreams on one device, as the Mac's SoundOutput has
// AVAudioSourceNodes. Effects: SoundMixer, 16-bit mono at 22050 Hz. AdLib music: OPL2Stream, float mono at 49716 Hz. General MIDI: GMStream
// (TinySoundFont, SDLMIDI.swift), float stereo at 44100 Hz, only when a SoundFont (.sf2) is found; without one .generalMIDI plays as AdLib.
// SDL converts the streams to the device's format and mixes them. Each stream's get-callback runs on SDL's audio thread and renders exactly
// what the device asks for, so the playhead and AudioScheduler.pad behave as on the Mac.
// Development: SDL_AUDIO_DRIVER=disk with SDL_AUDIO_DISK_OUTPUT_FILE=<file> records the output.
import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation

/// What the audio thread renders into: a reusable block, and counters the main thread can read.
private final class Feed: @unchecked Sendable {
    let mixer: SoundMixer?, opl: OPL2Stream?, gm: GMStream?
    private let block = UnsafeMutablePointer<Float>.allocate(capacity: 4096)
    private let lock = NSLock()
    private var frames = 0, peak: Float = 0

    init(mixer: SoundMixer) { self.mixer = mixer; opl = nil; gm = nil }
    init(opl: OPL2Stream) { self.opl = opl; mixer = nil; gm = nil }
    init(gm: GMStream) { self.gm = gm; mixer = nil; opl = nil }
    deinit { block.deallocate() }

    var framesRendered: Int { lock.lock(); defer { lock.unlock() }; return frames }
    var loudest: Float { lock.lock(); defer { lock.unlock() }; return peak }

    /// Render `bytes` of the stream's own format into it, in blocks.
    func fill(_ stream: OpaquePointer?, bytes: Int) {
        let size = mixer != nil ? MemoryLayout<Int16>.size : MemoryLayout<Float>.size * (gm != nil ? 2 : 1)       // bytes per frame
        var left = bytes / size
        while left > 0 {
            let n = min(left, gm != nil ? 2048 : 4096)
            var loud: Float = 0
            if let mixer {
                block.withMemoryRebound(to: Int16.self, capacity: 4096) { pcm in
                    mixer.render(into: UnsafeMutableBufferPointer(start: pcm, count: n))
                    for i in 0..<n { loud = max(loud, abs(Float(pcm[i]))) }
                    SDL_PutAudioStreamData(stream, pcm, Int32(n * size))
                }
            } else if let opl {
                opl.render(into: block, count: n)
                for i in 0..<n { loud = max(loud, abs(block[i])) }
                SDL_PutAudioStreamData(stream, block, Int32(n * size))
            } else if let gm {
                gm.render(into: block, frames: n)
                for i in 0..<2 * n { loud = max(loud, abs(block[i])) }
                SDL_PutAudioStreamData(stream, block, Int32(n * size))
            }
            lock.lock(); frames += n; peak = max(peak, loud); lock.unlock()
            left -= n
        }
    }
}

private let feedCallback: SDL_AudioStreamCallback = { userdata, stream, additional, _ in
    guard let userdata, additional > 0 else { return }
    Unmanaged<Feed>.fromOpaque(userdata).takeUnretainedValue().fill(stream, bytes: Int(additional))
}

/// The scheduler's per-voice lines are for the Mac's debug log; only its errors reach the shell's.
private struct ErrorsOnly: HostLog {
    let log: HostLog
    func info(_ category: String, _ message: String) {}
    func error(_ category: String, _ message: String) { log.error(category, message) }
}

@MainActor
final class SDLAudio: HostAudio {
    let scheduler: AudioScheduler
    private let log: HostLog
    private var device: SDL_AudioDeviceID = 0
    private var tried = false
    private var effects: OpaquePointer?, music: OpaquePointer?, midi: OpaquePointer?
    private var effectFeed: Feed?, musicFeed: Feed?, midiFeed: Feed?
    private var wanted = false
    private let gm = GMStream()
    private let soundFont: URL?, soundFontHelp: String, note: (String) -> Void
    private var soundFontTried = false

    /// What the audio thread has rendered so far, per stream (frames, and the loudest sample).
    var effectFrames: Int { effectFeed?.framesRendered ?? 0 }
    var musicFrames: Int { musicFeed?.framesRendered ?? 0 }
    var musicPeak: Float { musicFeed?.loudest ?? 0 }
    var midiFrames: Int { midiFeed?.framesRendered ?? 0 }
    var midiPeak: Float { midiFeed?.loudest ?? 0 }
    /// A SoundFont was found and loaded (it loads the first time this or General MIDI is asked for).
    var generalMIDIAvailable: Bool { loadSoundFont() }
    var isOpen: Bool { device != 0 }

    /// Mute only silences the output; the playhead keeps running.
    var muted = false { didSet { applyGain() } }

    /// `soundFont`: the file the search found (nil = none); `soundFontHelp` ends the log line that says none was; `note` also puts the outcome in the play log.
    init(log: HostLog, soundFont: URL?, soundFontHelp: String = "", note: @escaping (String) -> Void = { _ in }) {
        self.log = log; self.soundFont = soundFont; self.soundFontHelp = soundFontHelp; self.note = note
        scheduler = AudioScheduler(synth: gm, log: ErrorsOnly(log: log))
    }

    /// Loads the SoundFont the first time General MIDI is wanted and logs the outcome once; true when General MIDI can play.
    private func loadSoundFont() -> Bool {
        if soundFontTried { return gm.isLoaded }
        soundFontTried = true
        let text: String
        if let soundFont {
            if let presets = (try? Data(contentsOf: soundFont)).flatMap({ gm.load($0) }) { text = "General MIDI: SoundFont \(soundFont.path) (\(presets) presets)" }
            else { text = "General MIDI: \(soundFont.path) is not a SoundFont 2 file, playing AdLib" }
        } else {
            text = "General MIDI: no SoundFont (.sf2) found, playing AdLib; \(soundFontHelp)"
        }
        log.info("audio", text)
        note(text)
        return gm.isLoaded
    }

    /// General MIDI plays as AdLib when there is no SoundFont.
    private func playable(_ d: MusicArrangement?) -> MusicArrangement? { d == .generalMIDI && !loadSoundFont() ? .adlib : d }

    private func applyGain() { if device != 0 { SDL_SetAudioDeviceGain(device, muted ? 0 : 1) } }

    /// The device and its three streams, once; without audio hardware this logs once and every call after it does nothing.
    private func open() {
        guard !tried else { return }
        tried = true
        device = SDL_OpenAudioDevice(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, nil)
        guard device != 0 else { log.error("audio", "no audio device, running silent: \(String(cString: SDL_GetError()))"); return }
        let fx = Feed(mixer: scheduler.mixer), fm = Feed(opl: scheduler.opl), fg = Feed(gm: gm)
        var effectSpec = SDL_AudioSpec(format: SDL_AUDIO_S16LE, channels: 1, freq: Int32(SoundMixer.rate))
        var musicSpec = SDL_AudioSpec(format: SDL_AUDIO_F32LE, channels: 1, freq: Int32(OPL2.rate))
        var midiSpec = SDL_AudioSpec(format: SDL_AUDIO_F32LE, channels: 2, freq: Int32(GMStream.rate))
        effects = SDL_CreateAudioStream(&effectSpec, nil)
        music = SDL_CreateAudioStream(&musicSpec, nil)
        midi = SDL_CreateAudioStream(&midiSpec, nil)
        guard effects != nil, music != nil, midi != nil else { log.error("audio", "no audio stream: \(String(cString: SDL_GetError()))"); close(); tried = true; return }
        effectFeed = fx; musicFeed = fm; midiFeed = fg
        SDL_SetAudioStreamGetCallback(effects, feedCallback, Unmanaged.passUnretained(fx).toOpaque())
        SDL_SetAudioStreamGetCallback(music, feedCallback, Unmanaged.passUnretained(fm).toOpaque())
        SDL_SetAudioStreamGetCallback(midi, feedCallback, Unmanaged.passUnretained(fg).toOpaque())
        if !(SDL_BindAudioStream(device, effects) && SDL_BindAudioStream(device, music) && SDL_BindAudioStream(device, midi)) {
            log.error("audio", "could not bind the audio streams: \(String(cString: SDL_GetError()))")
            close(); tried = true
            return
        }
        applyGain()
    }

    /// A new World starts: drop the old voices and (re)start the device. `device` nil = no music (INSTALL.OPT MUSIC=OFF).
    func newGame(game: GameFolder, musicLevel: Int, device: MusicArrangement?) {
        open()
        guard self.device != 0 else { return }
        scheduler.newGame(game: game, musicLevel: musicLevel, device: playable(device))
        wanted = true
        SDL_ResumeAudioDevice(self.device)
    }

    func setMusicDevice(_ device: MusicArrangement?, world: World?) {
        guard self.device != 0 else { return }
        scheduler.setMusicDevice(playable(device), world: world)
    }

    func sync(_ world: World) { if device != 0 { scheduler.sync(world) } }

    func setPaused(_ paused: Bool) {
        guard device != 0, wanted != !paused else { return }
        wanted = !paused
        if paused { SDL_PauseAudioDevice(device) } else { SDL_ResumeAudioDevice(device) }
    }

    func stop() {
        guard device != 0 else { return }
        scheduler.stop()
        gm.reset()
        wanted = false
        SDL_PauseAudioDevice(device)
    }

    /// The streams and the device go (the shell quits).
    func close() {
        if let effects { SDL_DestroyAudioStream(effects) }       // unbinds, so no callback runs after this
        if let music { SDL_DestroyAudioStream(music) }
        if let midi { SDL_DestroyAudioStream(midi) }
        effects = nil; music = nil; midi = nil
        if device != 0 { SDL_CloseAudioDevice(device) }
        device = 0
        effectFeed = nil; musicFeed = nil; midiFeed = nil
    }
}
