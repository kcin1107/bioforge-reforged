import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation
import Testing
@testable import BioForgeSDLShell

@MainActor
@Suite(.enabled(if: dataFolder != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct SDLAudioTests {
    /// The shell's frame loop in real time, as run() does.
    private func realtime(_ shell: SDLShell, seconds: Double) {
        let end = Date().addingTimeInterval(seconds)
        var last = Date()
        while Date() < end {
            SDL_Delay(10)
            let now = Date()
            shell.frame(dt: now.timeIntervalSince(last))
            last = now
        }
    }

    private func started(_ rig: Rig) throws -> SDLShell {
        try #require(sdlReady, "SDL_Init failed: \(String(cString: SDL_GetError()))")
        let shell = rig.shell()
        shell.start()
        try #require(shell.audio.isOpen, "no audio device")
        return shell
    }

    @Test func aNewGamePlaysItsMusicAndEffects() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try started(rig)
        realtime(shell, seconds: 4)
        let effects = shell.audio.effectFrames, music = shell.audio.musicFrames, peak = shell.audio.musicPeak
        shell.shutdown()
        #expect(effects > 22_050 * 3 && music > 49_716 * 3)          // the streams ran in real time
        #expect(peak > 0)                                             // General MIDI plays as AdLib: the chip sounds
        let bytes = try Data(contentsOf: audioOutput)
        #expect(bytes.count > 44_100 * 4 * 2 && bytes.contains { $0 != 0 })
    }

    /// A SoundFont file in the rig's folder, named by the "SoundFont" setting, and General MIDI as the music device.
    private func withSoundFont(_ rig: Rig) throws -> SDLShell {
        let file = rig.home.appendingPathComponent("test.sf2")
        try FileManager.default.createDirectory(at: rig.home, withIntermediateDirectories: true)
        try sineSoundFont().write(to: file)
        rig.store.set(file.path, forKey: SoundFontSearch.settingKey)
        rig.store.set(MusicArrangement.generalMIDI.rawValue, forKey: "MusicDevice")
        return try started(rig)
    }

    @Test func generalMIDIPlaysWithASoundFont() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try withSoundFont(rig)
        realtime(shell, seconds: 4)
        let frames = shell.audio.midiFrames, peak = shell.audio.midiPeak, chip = shell.audio.musicPeak
        shell.shutdown()
        #expect(shell.audio.generalMIDIAvailable)
        #expect(frames > 44_100 * 3)                                  // the third stream ran in real time
        #expect(peak > 0)
        #expect(chip == 0)                                            // and the chip stayed silent
        #expect(shell.playLog.lines.contains { $0.contains("General MIDI: SoundFont ") && $0.contains("(2 presets)") })
    }

    @Test func withoutASoundFontGeneralMIDIPlaysAdLib() throws {
        let rig = Rig(); defer { rig.clean() }
        rig.store.set(MusicArrangement.generalMIDI.rawValue, forKey: "MusicDevice")
        let shell = try started(rig)
        realtime(shell, seconds: 3)
        let chip = shell.audio.musicPeak, midi = shell.audio.midiPeak
        let available = shell.audio.generalMIDIAvailable
        shell.shutdown()
        #expect(!available)
        #expect(chip > 0 && midi == 0)
        #expect(shell.playLog.lines.contains { $0.contains("General MIDI: no SoundFont (.sf2) found, playing AdLib") })
    }

    @Test func aFileThatIsNotASoundFontPlaysAdLib() throws {
        let rig = Rig(); defer { rig.clean() }
        try FileManager.default.createDirectory(at: rig.home, withIntermediateDirectories: true)
        let file = rig.home.appendingPathComponent("bad.sf2")
        try Data("not a SoundFont".utf8).write(to: file)
        rig.store.set(file.path, forKey: SoundFontSearch.settingKey)
        rig.store.set(MusicArrangement.generalMIDI.rawValue, forKey: "MusicDevice")
        let shell = try started(rig)
        realtime(shell, seconds: 2)
        let chip = shell.audio.musicPeak
        shell.shutdown()
        #expect(chip > 0)
        #expect(shell.playLog.lines.contains { $0.contains("is not a SoundFont 2 file, playing AdLib") })
    }

    @Test func switchingTheMusicDeviceAtRuntime() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try withSoundFont(rig); defer { shell.shutdown() }
        realtime(shell, seconds: 2)
        #expect(shell.audio.midiPeak > 0 && shell.audio.musicPeak == 0)
        shell.settings.musicDevice = .adlib
        shell.audio.setMusicDevice(.adlib, world: shell.session?.world)
        realtime(shell, seconds: 2)
        #expect(shell.audio.musicPeak > 0)                            // the chip sounds after the switch
        let before = shell.audio.midiFrames
        shell.audio.setMusicDevice(.generalMIDI, world: shell.session?.world)
        realtime(shell, seconds: 1)
        #expect(shell.audio.midiFrames > before)
        #expect(shell.audio.generalMIDIAvailable)
    }

    @Test func withMusicOffTheEffectsStillRenderAndTheChipStaysSilent() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try started(rig); defer { shell.shutdown() }
        let game = try #require(shell.game)
        shell.audio.newGame(game: game, musicLevel: 100, device: nil)
        let before = shell.audio.effectFrames
        realtime(shell, seconds: 1.5)
        #expect(shell.audio.effectFrames > before)
        #expect(shell.audio.musicPeak == 0)
    }

    @Test func pausingStopsTheStreamsAndResumingStartsThem() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try started(rig); defer { shell.shutdown() }
        realtime(shell, seconds: 0.5)
        shell.audio.setPaused(true)
        SDL_Delay(100)
        let paused = shell.audio.effectFrames
        SDL_Delay(300)
        #expect(shell.audio.effectFrames == paused)
        shell.audio.setPaused(false)
        SDL_Delay(300)
        #expect(shell.audio.effectFrames > paused)
    }

    @Test func muteSilencesTheOutputNotThePlayhead() throws {
        let rig = Rig(); defer { rig.clean() }
        rig.store.set(true, forKey: "Muted")
        let shell = try started(rig); defer { shell.shutdown() }
        #expect(shell.audio.muted)
        let before = shell.audio.effectFrames
        SDL_Delay(300)
        #expect(shell.audio.effectFrames > before)
    }
}
