import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation
import Testing
@testable import BioForgeSDLShell

struct SDLKeyTranslationTests {
    @Test func aKeyBecomesItsHIDUsage() {
        let e = SDLInput.keyEvent(scancode: 0x52, repeat: false, mod: 0, down: true)
        #expect(e.usage == 0x52 && e.kind == .down && !e.isRepeat && !e.command && e.modifierDown == nil)
        #expect(SDLInput.keyEvent(scancode: 0x52, repeat: false, mod: 0, down: false).kind == .up)
    }

    @Test func aRepeatIsMarked() {
        #expect(SDLInput.keyEvent(scancode: 0x52, repeat: true, mod: 0, down: true).isRepeat)
    }

    @Test func aModifierKeyIsAnOrdinaryDown() {
        let e = SDLInput.keyEvent(scancode: 0xE1, repeat: false, mod: BF_KMOD_LSHIFT, down: true)
        #expect(e.usage == 0xE1 && e.kind == .down && e.modifierDown == nil && !e.command)
    }

    @Test func theGUIKeyIsCommand() {
        #expect(SDLInput.keyEvent(scancode: 0x04, repeat: false, mod: BF_KMOD_LGUI, down: true).command)
        #expect(SDLInput.keyEvent(scancode: 0x04, repeat: false, mod: BF_KMOD_RGUI, down: true).command)
        #expect(!SDLInput.keyEvent(scancode: 0x04, repeat: false, mod: BF_KMOD_LCTRL, down: true).command)
    }

    @Test func anUnknownScancodeIsZero() {
        #expect(SDLInput.keyEvent(scancode: Int(SDL_SCANCODE_UNKNOWN.rawValue), repeat: false, mod: 0, down: true).usage == 0)
        #expect(SDLInput.keyEvent(scancode: 0x1_0000, repeat: false, mod: 0, down: true).usage == 0)
    }
}

@MainActor
@Suite(.enabled(if: dataFolder != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct SDLInputTests {
    /// A started game after the wake-up, Lex free.
    private func awake(_ rig: Rig) throws -> SDLShell {
        try #require(sdlReady, "SDL_Init failed: \(String(cString: SDL_GetError()))")
        let shell = rig.shell()
        shell.start()
        guard shell.leaveTitle() else { shell.shutdown(); Issue.record("never left TITLE"); throw CancellationError() }
        return shell
    }

    private func position(_ w: World) throws -> (x: Double, y: Double) {
        let p = try #require(w.player?.pos)
        return (Double(p.x), Double(p.y))
    }

    private func distance(_ a: (x: Double, y: Double), _ b: (x: Double, y: Double)) -> Double { hypot(a.x - b.x, a.y - b.y) }

    @Test func escapeOpensAndClosesTheOptionsDialog() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try awake(rig); defer { shell.shutdown() }
        let w = try #require(shell.session?.world)
        shell.mouseSeen = false; shell.input.pointerPosition = (160, 100)     // as with a controller only: SDL's mouse state is no position yet
        shell.push(key: 0x29, down: true); shell.push(key: 0x29, down: false); shell.run(5)
        #expect(w.isOptionsOpen)
        #expect(shell.input.pointerPosition == (160, 100))                 // the hand isn't pulled to SDL's (0, 0)
        shell.push(key: 0x29, down: true); shell.push(key: 0x29, down: false); shell.run(5)
        #expect(!w.isOptionsOpen)
    }

    @Test func holdingForwardWalksAndReleasingStops() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try awake(rig); defer { shell.shutdown() }
        let w = try #require(shell.session?.world)
        let start = try position(w)
        shell.push(key: 0x52, down: true); shell.run(20)
        let walked = try position(w)
        #expect(distance(start, walked) > 100)
        shell.push(key: 0x52, down: false); shell.run(30)
        let stopped = try position(w)
        shell.run(30)
        #expect(distance(stopped, try position(w)) < 1)
    }

    @Test func aClickInsideThePictureReachesTheDialogAndOutsideDoesNot() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try awake(rig); defer { shell.shutdown() }
        let w = try #require(shell.session?.world)
        shell.push(key: 0x29, down: true); shell.push(key: 0x29, down: false); shell.run(5)
        try #require(w.isOptionsOpen)
        let audio = try #require(shell.button("AUD") ?? shell.button("CRD"))
        shell.push(mouse: SDL_EVENT_MOUSE_MOTION, game: (x: 5, y: 5)); shell.run(3)           // away from the button
        let away = shell.input.pointerPosition
        shell.push(mouse: SDL_EVENT_MOUSE_MOTION, game: audio); shell.run(3)
        #expect(shell.input.pointerPosition == audio)
        #expect(w.options?.hovered?.contains("AUD") == true || w.options?.hovered?.contains("CRD") == true)
        shell.push(mouse: SDL_EVENT_MOUSE_MOTION, window: (x: -50, y: -50)); shell.run(3)      // outside the window, so outside the picture
        #expect(shell.input.pointerPosition == audio && away != audio)
        shell.push(mouse: SDL_EVENT_MOUSE_BUTTON_DOWN, game: audio); shell.run(5)
        shell.push(mouse: SDL_EVENT_MOUSE_BUTTON_UP, game: audio); shell.run(30)
        #expect(w.options?.screen == "audio" || w.options?.screen == "credits")           // the click pressed the button
    }

    @Test func losingFocusLetsGoOfTheKeys() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try awake(rig); defer { shell.shutdown() }
        let w = try #require(shell.session?.world)
        shell.push(key: 0x52, down: true); shell.run(30)
        #expect(shell.input.heldKeys.contains(0x52))
        shell.push(window: SDL_EVENT_WINDOW_FOCUS_LOST); shell.run(30)
        #expect(shell.input.heldKeys.isEmpty)
        shell.push(window: SDL_EVENT_WINDOW_FOCUS_GAINED)
        shell.run(5)
        let stopped = try position(w)
        shell.run(30)
        #expect(distance(stopped, try position(w)) < 1)          // Lex stands, though the key was never released
    }

    @Test func f11TogglesFullScreenAndIsRemembered() throws {
        try #require(sdlReady)
        let rig = Rig(); defer { rig.clean() }
        let shell = rig.shell(); defer { shell.shutdown() }
        shell.start()
        shell.push(key: 0x44, down: true); shell.push(key: 0x44, down: false)
        #expect(shell.fullScreen && rig.store.bool(forKey: "FullScreen"))
        shell.push(key: 0x44, down: true); shell.push(key: 0x44, down: false)
        #expect(!shell.fullScreen && !rig.store.bool(forKey: "FullScreen") && rig.store.object(forKey: "FullScreen") != nil)
        shell.push(key: 0x28, down: true, mod: BF_KMOD_LALT); shell.push(key: 0x28, down: false)      // Alt+Enter
        #expect(shell.fullScreen)
    }
}
