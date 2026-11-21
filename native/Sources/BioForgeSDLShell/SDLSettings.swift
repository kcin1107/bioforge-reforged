// The settings screen in the SDL shell (BioForgeHost's SettingsScreen draws and navigates; this applies and saves what it changes, and feeds
// it the keys and the controller while it is open). F1, or Back / View in the game's options dialog, opens it: the game stops, the picture freezes.
import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation

@MainActor
final class SettingsAdapter: SettingsScreenHost {
    private unowned let shell: SDLShell
    init(_ shell: SDLShell) { self.shell = shell }

    var fullScreen: Bool { get { shell.fullScreen } set { shell.setFullScreen(newValue) } }

    var correctAspect: Bool {
        get { shell.correctAspect }
        set {
            shell.store.set(newValue, forKey: SDLShell.aspectKey)
            shell.applyAspect()
            shell.redrawGame()
        }
    }

    var music: MusicArrangement? {
        get { shell.settings.musicDevice }
        set {
            shell.settings.musicDevice = newValue
            shell.settings.persist()
            shell.audio.setMusicDevice(newValue, world: shell.session?.world)
        }
    }

    /// Only while General MIDI is chosen without a SoundFont to play it (the log names the folders).
    var musicNote: String? { shell.settings.musicDevice == .generalMIDI && !shell.audio.generalMIDIAvailable ? "No SoundFont (.sf2) found: AdLib plays. See the log." : nil }

    var muted: Bool {
        get { shell.audio.muted }
        set { shell.audio.muted = newValue; shell.store.set(newValue, forKey: SDLShell.mutedKey) }
    }

    var language: String {
        get { shell.settings.language }
        set {
            if let w = shell.session?.world { w.setLanguage(newValue) } else { shell.settings.language = newValue; shell.settings.persist() }
            shell.playLog.note("language \(newValue)")
        }
    }

    var readableText: Bool {
        get { shell.store.bool(forKey: SDLShell.readableKey) }
        set { shell.store.set(newValue, forKey: SDLShell.readableKey); shell.session?.world.readableText = newValue }
    }

    var keyBindings: KeyBindings {
        get { shell.input.bindings }
        set {
            shell.input.setBindings(newValue, world: shell.session?.world)
            shell.store.set(newValue.propertyList, forKey: BindingsMigration.key)
        }
    }

    var padBindings: PadBindings {
        get { shell.input.padBindings }
        set {
            shell.input.setPadBindings(newValue, world: shell.session?.world)
            shell.store.set(newValue.propertyList, forKey: SDLShell.padBindingsKey)
        }
    }

    func keyName(_ usage: UInt16) -> String {
        let scancode = SDL_Scancode(rawValue: UInt32(usage))
        let name = String(cString: SDL_GetKeyName(SDL_GetKeyFromScancode(scancode, 0, false)))
        if !name.isEmpty { return name }
        let fallback = String(cString: SDL_GetScancodeName(scancode))
        return fallback.isEmpty ? "Key 0x\(String(usage, radix: 16))" : fallback
    }

    func padLabel(_ b: PadButton) -> String { shell.pad.label(b) }
}

extension SDLShell {
    /// F1 or Back / View: the game stops (keys and pointer let go, the sound pauses) and the screen goes over its last picture.
    func openSettings() {
        guard session != nil, font != nil else { return }
        input.releaseAll(world: session?.world)
        input.releasePointer(world: session?.world)
        host.setSuspended(true, inGame: true)
        screen.open()
        redrawGame()
    }

    func closeSettings() {
        screen.close()
        if !suspended { host.setSuspended(false, inGame: true) }
        redrawGame()
    }

    /// After every input the screen took: closed by Done or Back, or drawn again.
    private func screenChanged() {
        if screen.isOpen { redrawGame() } else { closeSettings() }
    }

    /// A key while the screen is open: arrows move and change, Return, keypad Enter and Space select, Escape backs out, Backspace and Delete clear, F1 closes.
    func screenKey(_ key: KeyEvent) {
        guard key.kind == .down, !key.isRepeat || screen.capturing == nil else { return }
        screen.lastInputWasPad = false
        if key.usage == 0x3A, screen.capturing == nil { closeSettings(); return }
        if case .key? = screen.capturing { screen.captureKey(key.usage); screenChanged(); return }
        switch key.usage {
        case 0x52: screen.handle(.up)
        case 0x51: screen.handle(.down)
        case 0x50: screen.handle(.left)
        case 0x4F: screen.handle(.right)
        case 0x28, 0x58, 0x2C: screen.handle(.activate)
        case 0x29: screen.handle(.back)
        case 0x2A, 0x4C: screen.handle(.clear)
        default: return
        }
        screenChanged()
    }

    /// A controller event while the screen is open: the D-pad and stick move, A selects, B backs out, Back / View closes; while a button
    /// cell waits, the next button binds it and a direction cancels.
    func screenPad(_ e: PadTracker.Event) {
        screen.lastInputWasPad = true
        switch e {
        case .button(let b, down: true):
            if case .pad? = screen.capturing { screen.capturePad(b) }
            else if b == .a { screen.handle(.activate) }
            else if b == .b { screen.handle(.back) }
            else if b == .options { closeSettings(); return }
            else { return }
        case .direction(_, let to?):
            switch to {
            case "forward": screen.handle(.up)
            case "back": screen.handle(.down)
            case "turnLeft": screen.handle(.left)
            case "turnRight": screen.handle(.right)
            default: return                       // the diagonals
            }
        default: return
        }
        screenChanged()
    }
}
