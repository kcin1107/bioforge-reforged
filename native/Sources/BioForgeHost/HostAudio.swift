// What a shell's audio output offers the game loop: the Mac app implements it over AVAudioEngine, another shell over its own device.
// The scheduling (what plays when) is AudioScheduler; an output only turns its mixer and OPL2 stream into sound and plays the MIDI.
import BioForgeCore
import Foundation

@MainActor
public protocol HostAudio: AnyObject {
    var muted: Bool { get set }
    /// A new World starts: drop the old voices and (re)start the output. `device` nil = no music (INSTALL.OPT MUSIC=OFF).
    func newGame(game: GameFolder, musicLevel: Int, device: MusicArrangement?)
    func setMusicDevice(_ device: MusicArrangement?, world: World?)
    /// Once per game tick, after it.
    func sync(_ world: World)
    func setPaused(_ paused: Bool)
    func stop()
}

/// A General MIDI synth: `bytes` is a status byte plus one or two data bytes, to sound `seconds` from now (a sample-accurate schedule, so
/// each message keeps its place on the 120 Hz music timeline instead of landing on the 30 Hz tick).
public protocol MIDISynth: AnyObject {
    func send(_ bytes: [UInt8], after seconds: Double)
}
