// Live audio output for the Host's AudioScheduler (BioForgeHost: what plays when, fed once per game tick by `sync`): one AVAudioSourceNode renders the SoundMixer (parity-tested against the Python prototype) at 22050 Hz mono;
// the music plays through Apple's MIDI synth (General MIDI arrangement) or the AdLib driver port and OPL2 model (AdLib arrangement;
// a second source node at 49716 Hz, OPL2Stream) in the same AVAudioEngine; `setMusicDevice` switches between them. The audio thread pulls blocks;
// the scheduling, the timeline (tick 0 starts `pad` frames after the playhead) and the music feed live in AudioScheduler. Pausing the game
// (options dialog) pauses the engine, so the playhead and the game clock stay in step; Mute only silences the output. Development: BIOFORGE_AUDIO_TAP=file.wav
// records the engine output (BIOFORGE_AUDIO_TAP_SECONDS, default 45); BIOFORGE_MUSIC_TAP records the synth alone.
import AVFoundation
import AudioToolbox
import OSLog
import BioForgeCore
import BioForgeHost

@MainActor
final class SoundOutput: HostAudio {
    private let engine = AVAudioEngine()
    private let instrument = AVAudioUnitMIDIInstrument(audioComponentDescription: AudioComponentDescription(
        componentType: kAudioUnitType_MusicDevice, componentSubType: kAudioUnitSubType_MIDISynth,
        componentManufacturer: kAudioUnitManufacturer_Apple, componentFlags: 0, componentFlagsMask: 0))
    private let log = Logger(subsystem: "BioForge", category: "audio")
    private let scheduler: AudioScheduler
    private var wanted = false
    private var tap: TapFile?
    private var musicTap: TapFile?

    var muted = false { didSet { engine.mainMixerNode.outputVolume = muted ? 0 : 1 } }

    init() {
        scheduler = AudioScheduler(synth: DLSSynth(instrument), log: OSLogHostLog())
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(SoundMixer.rate), channels: 1, interleaved: false)!
        let node = Self.makeNode(scheduler.mixer, format)
        engine.attach(node)
        engine.attach(instrument)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        engine.connect(instrument, to: engine.mainMixerNode, format: nil)
        let oplFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(OPL2.rate), channels: 1, interleaved: false)!
        let oplNode = Self.makeOPLNode(scheduler.opl, oplFormat)
        engine.attach(oplNode)
        engine.connect(oplNode, to: engine.mainMixerNode, format: oplFormat)
        var bank = URL(fileURLWithPath: "/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls") as CFURL
        var status: OSStatus = -1
        withUnsafePointer(to: &bank) { pointer in
            status = AudioUnitSetProperty(instrument.audioUnit, AudioUnitPropertyID(kMusicDeviceProperty_SoundBankURL),
                                          AudioUnitScope(kAudioUnitScope_Global), 0, pointer, UInt32(MemoryLayout<CFURL>.size))
        }
        if status != noErr { log.error("music sound bank load failed: \(status)") }
        if let path = ProcessInfo.processInfo.environment["BIOFORGE_MUSIC_TAP"] {
            let format = instrument.outputFormat(forBus: 0)
            let seconds = Double(ProcessInfo.processInfo.environment["BIOFORGE_AUDIO_TAP_SECONDS"] ?? "") ?? 45
            if let file = try? AVAudioFile(forWriting: URL(fileURLWithPath: path), settings: format.settings) {
                let box = TapFile(file, limit: Int(seconds * format.sampleRate))
                musicTap = box
                Self.tapNode(instrument, format, box)
            }
        }
        NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.resume() }          // output device changed: the engine stopped itself
        }
        if let path = ProcessInfo.processInfo.environment["BIOFORGE_AUDIO_TAP"] { installTap(path) }
    }

    /// The render callback runs on the audio thread, so it must not inherit the main-actor isolation of this class.
    private nonisolated static func makeNode(_ mixer: SoundMixer, _ format: AVAudioFormat) -> AVAudioSourceNode {
        AVAudioSourceNode(format: format) { _, _, frames, list in
            let out = UnsafeMutableAudioBufferListPointer(list)[0]
            guard let dst = out.mData?.assumingMemoryBound(to: Float.self) else { return noErr }
            withUnsafeTemporaryAllocation(of: Int16.self, capacity: Int(frames)) { pcm in
                mixer.render(into: pcm)
                for i in 0..<Int(frames) { dst[i] = Float(pcm[i]) / 32768 }
            }
            return noErr
        }
    }

    private nonisolated static func makeOPLNode(_ opl: OPL2Stream, _ format: AVAudioFormat) -> AVAudioSourceNode {
        AVAudioSourceNode(format: format) { _, _, frames, list in
            let out = UnsafeMutableAudioBufferListPointer(list)[0]
            guard let dst = out.mData?.assumingMemoryBound(to: Float.self) else { return noErr }
            opl.render(into: dst, count: Int(frames))
            return noErr
        }
    }

    /// A new World starts: drop the old voices and (re)start the engine. `device` nil = no music (INSTALL.OPT MUSIC=OFF).
    func newGame(game: GameFolder, musicLevel: Int, device: MusicArrangement?) {
        scheduler.newGame(game: game, musicLevel: musicLevel, device: device)
        wanted = true
        resume()
    }

    func setMusicDevice(_ device: MusicArrangement?, world: World?) { scheduler.setMusicDevice(device, world: world) }

    func sync(_ world: World) { scheduler.sync(world) }

    func setPaused(_ paused: Bool) {
        guard wanted != !paused else { return }
        wanted = !paused
        if paused { engine.pause(); log.info("engine paused") } else { resume() }
    }

    func stop() {
        scheduler.stop()
        wanted = false
        engine.stop()
        log.info("engine stopped")
    }

    private func resume() {
        guard wanted, !engine.isRunning else { return }
        do {
            try engine.start()
            log.info("engine running \(self.engine.isRunning) output \(self.engine.outputNode.outputFormat(forBus: 0).sampleRate) Hz")
        } catch { log.error("engine start failed: \(error.localizedDescription, privacy: .public)") }
    }

    private func installTap(_ path: String) {
        let format = engine.mainMixerNode.outputFormat(forBus: 0)
        let seconds = Double(ProcessInfo.processInfo.environment["BIOFORGE_AUDIO_TAP_SECONDS"] ?? "") ?? 45
        guard let file = try? AVAudioFile(forWriting: URL(fileURLWithPath: path), settings: format.settings) else { return }
        let box = TapFile(file, limit: Int(seconds * format.sampleRate))
        tap = box
        Self.tapNode(engine.mainMixerNode, format, box)
    }

    private nonisolated static func tapNode(_ node: AVAudioNode, _ format: AVAudioFormat, _ box: TapFile) {
        node.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in box.write(buffer) }
    }
}

/// The recording file; closes itself after `limit` frames.
final class TapFile: @unchecked Sendable {
    private var file: AVAudioFile?
    private var left: Int
    init(_ file: AVAudioFile, limit: Int) { self.file = file; left = limit }
    func write(_ buffer: AVAudioPCMBuffer) {
        guard let f = file else { return }
        try? f.write(from: buffer)
        left -= Int(buffer.frameLength)
        if left <= 0 { file = nil }
    }
}

/// The MIDI instrument as the scheduler's General MIDI synth: each message goes into the audio unit's event schedule `seconds` ahead of its
/// render time (AUEventSampleTimeImmediate plus an offset in the unit's output frames), so it starts on its own sample.
private final class DLSSynth: MIDISynth {
    private let instrument: AVAudioUnitMIDIInstrument
    init(_ instrument: AVAudioUnitMIDIInstrument) { self.instrument = instrument }
    func send(_ bytes: [UInt8], after seconds: Double) {
        guard let schedule = instrument.auAudioUnit.scheduleMIDIEventBlock else {
            instrument.sendMIDIEvent(bytes[0], data1: bytes[1], data2: bytes.count > 2 ? bytes[2] : 0)
            return
        }
        let offset = AUEventSampleTime((max(0, seconds) * instrument.outputFormat(forBus: 0).sampleRate).rounded())
        bytes.withUnsafeBufferPointer { schedule(AUEventSampleTimeImmediate + offset, 0, bytes.count, $0.baseAddress!) }
    }
}
