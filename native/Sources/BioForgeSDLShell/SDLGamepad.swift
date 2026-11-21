// A game controller through SDL_Gamepad: the first one found, polled 60 times a second into PadTracker events as the Mac's GamepadInput does.
// InputRouter decides what the events do; SDL's own button layout means the same on an Xbox, a PlayStation or a Steam Deck pad.
import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation

@MainActor
final class SDLGamepad {
    static let pollRate = 60.0
    static let maxPollsPerFrame = 4                 // after a hitch; the pointer's 4 px a poll stays 240 px a second at any frame rate
    private var pad: OpaquePointer?
    private var tracker = PadTracker()
    private var owed = 0.0

    var id: SDL_JoystickID? { pad.map { SDL_GetGamepadID($0) } }

    /// Open the first gamepad found, when none is open.
    func openFirst() {
        guard pad == nil else { return }
        var count: Int32 = 0
        guard let ids = SDL_GetGamepads(&count) else { return }
        defer { SDL_free(ids) }
        if count > 0 { pad = SDL_OpenGamepad(ids[0]) }
    }

    func close() {
        if let pad { SDL_CloseGamepad(pad) }
        pad = nil
    }

    /// The polls that `dt` seconds owe (none with no pad open): each a list of events and the stick, y up.
    func polls(dt: Double) -> [(events: [PadTracker.Event], x: Double, y: Double)] {
        owed += dt
        var out: [(events: [PadTracker.Event], x: Double, y: Double)] = []
        while owed >= 1 / Self.pollRate - 1e-9 {
            owed -= 1 / Self.pollRate
            if out.count < Self.maxPollsPerFrame { out.append(poll()) }
        }
        return out
    }

    /// One poll: what is pressed now, or nothing with the stick centred when there is no pad (so the releases come out).
    func poll() -> (events: [PadTracker.Event], x: Double, y: Double) {
        var pressed = Set<PadButton>(), x = 0.0, y = 0.0
        if let pad {
            pressed = Set(PadButton.allCases.filter { isDown($0, pad) })
            let dpad = [SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_DOWN, SDL_GAMEPAD_BUTTON_DPAD_LEFT, SDL_GAMEPAD_BUTTON_DPAD_RIGHT].map { SDL_GetGamepadButton(pad, $0) }
            if dpad.contains(true) {
                x = (dpad[3] ? 1 : 0) - (dpad[2] ? 1 : 0)
                y = (dpad[0] ? 1 : 0) - (dpad[1] ? 1 : 0)
            } else {
                x = Self.stick(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTX))
                y = -Self.stick(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTY))      // SDL's y points down
            }
        }
        return (tracker.update(pressed: pressed, x: x, y: y), x, y)
    }

    private static func stick(_ axis: Int16) -> Double { max(-1, min(1, Double(axis) / 32767)) }

    private func isDown(_ b: PadButton, _ pad: OpaquePointer) -> Bool {
        switch b {
        case .a: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_SOUTH)
        case .b: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_EAST)
        case .x: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_WEST)
        case .y: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_NORTH)
        case .leftShoulder: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER)
        case .rightShoulder: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER)
        case .leftTrigger: SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) > 16384
        case .rightTrigger: SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) > 16384
        case .leftStick: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_LEFT_STICK)
        case .rightStick: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_RIGHT_STICK)
        case .menu: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_START)
        case .options: SDL_GetGamepadButton(pad, SDL_GAMEPAD_BUTTON_BACK)
        }
    }

    /// The connected controller's own name for a button (A/B/X/Y or Cross/Circle/Square/Triangle on the face); the generic name otherwise.
    func label(_ b: PadButton) -> String {
        guard let pad else { return b.title }
        let face: SDL_GamepadButton
        switch b {
        case .a: face = SDL_GAMEPAD_BUTTON_SOUTH
        case .b: face = SDL_GAMEPAD_BUTTON_EAST
        case .x: face = SDL_GAMEPAD_BUTTON_WEST
        case .y: face = SDL_GAMEPAD_BUTTON_NORTH
        default: return b.title
        }
        switch SDL_GetGamepadButtonLabel(pad, face) {
        case SDL_GAMEPAD_BUTTON_LABEL_A: return "A"
        case SDL_GAMEPAD_BUTTON_LABEL_B: return "B"
        case SDL_GAMEPAD_BUTTON_LABEL_X: return "X"
        case SDL_GAMEPAD_BUTTON_LABEL_Y: return "Y"
        case SDL_GAMEPAD_BUTTON_LABEL_CROSS: return "Cross"
        case SDL_GAMEPAD_BUTTON_LABEL_CIRCLE: return "Circle"
        case SDL_GAMEPAD_BUTTON_LABEL_SQUARE: return "Square"
        case SDL_GAMEPAD_BUTTON_LABEL_TRIANGLE: return "Triangle"
        default: return b.title
        }
    }
}

extension SDLShell {
    /// The polls `dt` owes, to the game. The tracker follows the pad whatever the shell is doing, so a button held across a focus change doesn't fire later;
    /// only a running, unsuspended game in the focused window hears it (as the Mac's handlePad and movePointerWithPad).
    func pollPad(dt: Double) {
        for p in pad.polls(dt: dt) { route(p) }
    }

    private func route(_ p: (events: [PadTracker.Event], x: Double, y: Double)) {
        guard !suspended, focused, let w = session?.world else { return }
        if screen.isOpen { for e in p.events { screenPad(e) }; return }
        for e in p.events {
            if case .button(.options, down: true) = e, w.isOptionsOpen { openSettings(); return }      // Back / View opens the settings screen from the dialog
            input.handlePad(e, world: w)
        }
        input.movePointerWithPad(p.x, p.y, world: w)
    }

    /// The open controller went away: a poll with nothing pressed first, so a held Run, Kick or Punch is let go; then the next controller, if any.
    func padRemoved(_ id: SDL_JoystickID) {
        guard pad.id == id else { return }
        pad.close()
        route(pad.poll())
        pad.openFirst()
    }
}
