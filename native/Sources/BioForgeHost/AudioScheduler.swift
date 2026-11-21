// The audio scheduling every shell shares: it feeds the world's sound and music logs to the SoundMixer (22050 Hz effects), the General MIDI
// synth or the AdLib driver port and OPL2 model (49716 Hz) once per game tick (`sync`); the output's audio thread pulls blocks from `mixer`
// and `opl`. Timeline: the World's tick 0 starts `pad` frames (~93 ms) after the playhead at New Game, which absorbs tick jitter and the
// one-tick lead of positional volume ramps. General MIDI messages are scheduled on the same timeline: each one sounds `lead` + (its time
// - the tick's time) from now, so it keeps its 120 Hz place (the XMIDI step rate) rather than the 30 Hz tick, and stays in step
// with the effects. `setMusicDevice` switches between GM and AdLib.
import BioForgeCore
import Foundation

@MainActor
public final class AudioScheduler {
    public static let pad = 2048                  // effect mixer frames between playhead and tick 0 at New Game
    static let lead = Double(pad) / Double(SoundMixer.rate)     // the same latency for the General MIDI messages, in seconds
    public let mixer = SoundMixer()
    public let opl = OPL2Stream()
    private let synth: MIDISynth
    private let log: HostLog?
    private var logged = 0
    private var musicLogged = 0
    private var musicVolLogged = 0
    private var music: MusicSequencer?
    private var adlib: AdLibSequencer?
    private var device: MusicArrangement? = .generalMIDI
    private var game: GameFolder?
    private var musicInitial = 100
    private var replayUntil: Double?             // after a device switch: the replayed past sends no notes to the GM synth

    public init(synth: MIDISynth, log: HostLog?) { self.synth = synth; self.log = log }

    /// A new World starts: drop the old voices. `device` nil = no music (INSTALL.OPT MUSIC=OFF).
    public func newGame(game: GameFolder, musicLevel: Int, device: MusicArrangement?) {
        self.game = game; musicInitial = musicLevel; self.device = device
        opl.reset(pad: Self.pad * OPL2.rate / SoundMixer.rate)
        buildMusic()
        mixer.reset(pad: Self.pad)
        logged = 0
    }

    /// Builds the sequencer (and AdLib driver) for the current device; the next `sync` feeds it the world's music log from the start.
    private func buildMusic() {
        silenceMusic()
        music = nil; adlib = nil
        musicLogged = 0; musicVolLogged = 0
        guard let game, let device else { return }
        do {
            music = MusicSequencer(library: try MusicLibrary(game: game, arrangement: device), volume: musicInitial)
            if device == .adlib { adlib = AdLibSequencer(bank: try AdLibBank(game: game)) }
        } catch { music = nil; adlib = nil; log?.error("audio", "music load failed: \(error.localizedDescription)") }
    }

    /// Game > Music Device: rebuild the music for `device` and replay the running game's music requests up to now, so the
    /// current song continues (AdLib: the driver replays every message and the chip takes the resulting state at once).
    public func setMusicDevice(_ device: MusicArrangement?, world: World?) {
        guard device != self.device else { return }
        self.device = device
        guard game != nil else { return }
        if adlib != nil { opl.push(Self.allOff()) }
        buildMusic()
        if let world { replayUntil = Double(world.vm?.tick ?? 0) / 30; sync(world) }
    }

    /// Key off on all nine OPL voices (the replayed driver state follows).
    private static func allOff() -> [AdLibSequencer.Write] { (0..<9).map { AdLibSequencer.Write(sample: 0, register: UInt8(0xb0 + $0), value: 0) } }

    /// Hands the tick's new sound events to the mixer.
    public func sync(_ world: World) {
        mixer.keepUp(tick: world.soundLog.dropFirst(logged).first?.tick ?? world.vm?.tick ?? 0, pad: Self.pad)   // the earliest new sound starts whole
        mixer.sync(world)
        for e in world.soundLog.dropFirst(logged) {
            log?.info("audio", "voice tick \(e.tick) #\(e.index) \(e.name) vol \(e.volume) pitch \(e.pitch) handle \(e.handle)")
        }
        logged = world.soundLog.count
        if let music {
            // script requests and options-dialog level changes in tick order, requests first at equal ticks (musicseq.sequence)
            let requests = Array(world.musicLog.dropFirst(musicLogged)), levels = Array(world.musicVolLog.dropFirst(musicVolLogged))
            var r = 0, l = 0
            while r < requests.count || l < levels.count {
                if r < requests.count && (l >= levels.count || requests[r].tick <= levels[l].tick) {
                    if case .int(let id) = requests[r].value { music.request(id, at: Double(requests[r].tick) / 30) }
                    r += 1
                } else {
                    music.setVolume(levels[l].music, at: Double(levels[l].tick) / 30)
                    l += 1
                }
            }
            let now = Double(world.vm?.tick ?? 0) / 30
            let events = music.advance(to: now)
            if let adlib {
                let writes = adlib.advance(events, serving: music.takeServingChanges(), through: now)
                if let first = writes.first { opl.keepUp(sample: first.sample) }      // after a stall the music keeps its rhythm
                opl.push(writes)
            }
            else {
                for event in events {
                    let bytes = event.bytes
                    guard bytes.count >= 2 else { continue }
                    if let until = replayUntil, event.time < until, bytes[0] & 0xf0 == 0x90 { continue }
                    synth.send(bytes, after: max(0, Self.lead + event.time - now))
                }
            }
            replayUntil = nil
        }
        musicLogged = world.musicLog.count
        musicVolLogged = world.musicVolLog.count
    }

    /// The game ends: silence the music and empty the OPL2 stream.
    public func stop() {
        silenceMusic()
        music = nil; adlib = nil
        opl.reset(pad: 0)
    }

    /// All notes off on the 16 MIDI channels (controller 123), after every message already scheduled (they sound at most `lead` from now).
    private func silenceMusic() {
        for channel in UInt8(0)...UInt8(15) { synth.send([0xB0 | channel, 123, 0], after: Self.lead) }
    }
}
