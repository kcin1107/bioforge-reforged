import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation
import Testing
@testable import BioForgeSDLShell

/// A virtual controller SDL sees as a gamepad. Every change is followed by an update and a pump, so the shell's next poll sees it.
@MainActor
private final class VirtualPad {
    let shell: SDLShell
    let id: SDL_JoystickID
    private var joystick: OpaquePointer?

    init(_ shell: SDLShell) {
        self.shell = shell
        var desc = SDL_VirtualJoystickDesc()
        desc.version = UInt32(MemoryLayout<SDL_VirtualJoystickDesc>.size)          // SDL_INIT_INTERFACE is a macro
        desc.type = UInt16(SDL_JOYSTICK_TYPE_GAMEPAD.rawValue)
        desc.naxes = UInt16(SDL_GAMEPAD_AXIS_COUNT.rawValue)
        desc.nbuttons = UInt16(SDL_GAMEPAD_BUTTON_COUNT.rawValue)
        desc.button_mask = (1 << UInt32(SDL_GAMEPAD_BUTTON_COUNT.rawValue)) - 1
        desc.axis_mask = (1 << UInt32(SDL_GAMEPAD_AXIS_COUNT.rawValue)) - 1
        id = SDL_AttachVirtualJoystick(&desc)
        joystick = SDL_OpenJoystick(id)
        sync()
    }

    private func sync() {
        SDL_UpdateJoysticks()
        shell.pumpEvents()
        SDL_UpdateJoysticks()
    }

    func press(_ b: SDL_GamepadButton, _ down: Bool = true) {
        SDL_SetJoystickVirtualButton(joystick, Int32(b.rawValue), down)
        sync()
    }

    func axis(_ a: SDL_GamepadAxis, _ value: Int16) {
        SDL_SetJoystickVirtualAxis(joystick, Int32(a.rawValue), value)
        sync()
    }

    func detach() {
        SDL_CloseJoystick(joystick)
        joystick = nil
        SDL_DetachVirtualJoystick(id)
        sync()
    }
}

@MainActor
@Suite(.enabled(if: dataFolder != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct SDLGamepadTests {
    private func awake(_ rig: Rig) throws -> SDLShell {
        try #require(sdlReady, "SDL_Init failed: \(String(cString: SDL_GetError()))")
        let shell = rig.shell()
        shell.start()
        guard shell.leaveTitle() else { shell.shutdown(); Issue.record("never left TITLE"); throw CancellationError() }
        return shell
    }

    /// `n` polls: frames of 1/60 s.
    private func polls(_ shell: SDLShell, _ n: Int) { for _ in 0..<n { shell.frame(dt: 1 / 60.0 + 1e-9) } }

    private func position(_ w: World) throws -> (x: Double, y: Double) {
        let p = try #require(w.player?.pos)
        return (Double(p.x), Double(p.y))
    }

    @Test func aGamepadAttachedLaterIsOpened() throws {
        try #require(sdlReady)
        let rig = Rig(); defer { rig.clean() }
        let shell = rig.shell(); defer { shell.shutdown() }
        shell.start()
        #expect(shell.pad.id == nil)
        let pad = VirtualPad(shell)
        #expect(shell.pad.id == pad.id)
        pad.detach()
        #expect(shell.pad.id == nil)
    }

    @Test func theControllerPlaysAndDrivesTheDialog() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try awake(rig); defer { shell.shutdown() }
        let w = try #require(shell.session?.world)
        let pad = VirtualPad(shell)
        defer { pad.detach() }

        pad.press(SDL_GAMEPAD_BUTTON_START); shell.run(3); pad.press(SDL_GAMEPAD_BUTTON_START, false); shell.run(5)
        #expect(w.isOptionsOpen)

        let before = shell.input.pointerPosition
        pad.axis(SDL_GAMEPAD_AXIS_LEFTX, 32767); polls(shell, 15); pad.axis(SDL_GAMEPAD_AXIS_LEFTX, 0)
        #expect(shell.input.pointerPosition.x == before.x + 60 && shell.input.pointerPosition.y == before.y)
        pad.axis(SDL_GAMEPAD_AXIS_LEFTX, 32767); polls(shell, 120); pad.axis(SDL_GAMEPAD_AXIS_LEFTX, 0)
        #expect(shell.input.pointerPosition.x == 319)

        pad.press(SDL_GAMEPAD_BUTTON_SOUTH); polls(shell, 2)
        #expect(shell.input.pointerHeld)
        pad.press(SDL_GAMEPAD_BUTTON_SOUTH, false); polls(shell, 2)
        #expect(!shell.input.pointerHeld)
        shell.run(30)                          // the dialog ignores keys while the pointer's press animation runs

        pad.press(SDL_GAMEPAD_BUTTON_EAST); shell.run(3); pad.press(SDL_GAMEPAD_BUTTON_EAST, false); shell.run(5)
        #expect(!w.isOptionsOpen)

        let start = try position(w)
        pad.axis(SDL_GAMEPAD_AXIS_LEFTY, -32767); shell.run(20)
        let walked = try position(w)
        #expect(hypot(walked.x - start.x, walked.y - start.y) > 100)
        pad.axis(SDL_GAMEPAD_AXIS_LEFTY, 0); shell.run(30)
        let stopped = try position(w)
        shell.run(30)
        let later = try position(w)
        #expect(hypot(later.x - stopped.x, later.y - stopped.y) < 1)
    }

    @Test func detachingLetsGoOfARun() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try awake(rig); defer { shell.shutdown() }
        let pad = VirtualPad(shell)
        pad.axis(SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, 32767); polls(shell, 3)
        #expect(shell.input.padMods != 0)
        pad.detach(); polls(shell, 2)
        #expect(shell.input.padMods == 0)
    }
}
