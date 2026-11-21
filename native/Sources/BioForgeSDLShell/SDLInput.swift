// SDL's keys and mouse as the calls the game takes: events become `KeyEvent`s and pointer phases for InputRouter (BioForgeHost), which decides
// where everything goes. What stays here is what SDL does differently from the Mac: the cursor, warping the mouse, the modifier state.
import BioForgeHost
import BioForgeCore
import CSDL3
import Foundation

struct MousePoint: Equatable { var x: Float, y: Float }

enum SDLInput {
    /// An SDL key event as the router's KeyEvent. An SDL scancode is the USB HID usage; one the router has no use for (unknown, or past 16 bits) becomes 0.
    /// Modifier keys arrive as ordinary downs and ups; the router tracks them by usage.
    static func keyEvent(scancode: Int, repeat isRepeat: Bool, mod: SDL_Keymod, down: Bool) -> KeyEvent {
        KeyEvent(usage: UInt16(exactly: scancode) ?? 0, kind: down ? .down : .up, isRepeat: isRepeat, command: mod & BF_KMOD_GUI != 0)
    }
}

extension SDLShell {
    /// The picture's place in the output (the render target's pixels).
    var layout: PictureLayout {
        var w: Int32 = 0, h: Int32 = 0
        SDL_GetCurrentRenderOutputSize(renderer, &w, &h)
        return PictureLayout(width: Double(w), height: Double(h), correctAspect: correctAspect)
    }

    /// The 320x200 pixel under a window point (SDL's mouse coordinates), nil outside the picture.
    func gamePoint(window p: MousePoint) -> (x: Int, y: Int)? {
        var x: Float = 0, y: Float = 0
        SDL_RenderCoordinatesFromWindow(renderer, p.x, p.y, &x, &y)
        return layout.gamePoint(x: Double(x), y: Double(y))
    }

    /// The window point at the middle of a 320x200 pixel.
    func windowPoint(game x: Int, _ y: Int) -> MousePoint? {
        guard let p = layout.windowPoint(game: x, y) else { return nil }
        var wx: Float = 0, wy: Float = 0
        SDL_RenderCoordinatesToWindow(renderer, Float(p.x), Float(p.y), &wx, &wy)
        return MousePoint(x: wx, y: wy)
    }

    // MARK: keys

    func handleKey(_ e: SDL_KeyboardEvent, down: Bool) {
        let key = SDLInput.keyEvent(scancode: Int(e.scancode.rawValue), repeat: e.`repeat`, mod: e.mod, down: down)
        if screen.isOpen { screenKey(key); return }
        if down, !key.isRepeat {
            if key.usage == 0x3A, session != nil { openSettings(); return }          // F1
            if key.usage == 0x44 || (key.usage == 0x28 && e.mod & BF_KMOD_ALT != 0) { setFullScreen(!fullScreen); return }      // F11, Alt+Enter
        }
        if down, !key.command, session != nil { keyHidden = true; updateCursor() }        // until the mouse moves
        input.handleKey(key, world: session?.world)
    }

    // MARK: mouse

    func handleButton(_ e: SDL_MouseButtonEvent, down: Bool) {
        let phase: PointerPhase
        switch (e.button, down) {
        case (1, true): phase = .down              // SDL_BUTTON_LEFT
        case (1, false): phase = .up
        case (3, true): phase = .rightDown         // SDL_BUTTON_RIGHT: Escape on a monitor or the dialog
        default: return
        }
        handlePointer(window: (e.x, e.y), phase: phase)
    }

    /// A mouse event at a window point; outside the picture the position is nil, so a release there still lets go.
    func handlePointer(window p: (x: Float, y: Float), phase: PointerPhase) {
        mouseSeen = true
        if phase == .move { keyHidden = false; updateCursor() }
        if screen.isOpen { return }          // the settings screen takes keys and the controller only
        let g = gamePoint(window: MousePoint(x: p.x, y: p.y))
        input.handlePointer(x: g?.x, y: g?.y, phase: phase, world: session?.world)
    }

    // MARK: after the ticks

    /// Run, kicks and punches on Shift, Control or Alt stay held only while the system says that modifier is down (see InputRouter.dropReleasedModifiers).
    func dropReleasedModifiers(_ w: World) {
        let m = SDL_GetModState()
        input.dropReleasedModifiers(down: [0xE1: m & BF_KMOD_LSHIFT != 0, 0xE5: m & BF_KMOD_RSHIFT != 0, 0xE0: m & BF_KMOD_LCTRL != 0,
                                           0xE4: m & BF_KMOD_RCTRL != 0, 0xE2: m & BF_KMOD_LALT != 0, 0xE6: m & BF_KMOD_RALT != 0], world: w)
    }

    /// The pointer screens follow the real mouse, not only its moves: after the window gets focus or a screen opens, the hand sat where the mouse
    /// last was. A position that hasn't changed since the last frame is left alone, so the controller can still move the pointer.
    /// The game draws its own hand there, so the system cursor is hidden while it is over the picture (it comes back outside it).
    func syncPointer(_ w: World) {
        let warp = w.takeMouseWarp()
        guard focused, InputRouter.padDrivesPointer(w) else { lastMouse = nil; pointerHidden = false; updateCursor(); return }
        guard mouseSeen else { return }        // no mouse yet (a controller only, as on the Steam Deck): SDL's (0, 0) is no position, the hand stays where the game put it
        var x: Float = 0, y: Float = 0
        SDL_GetMouseState(&x, &y)
        var m = MousePoint(x: x, y: y)
        if let warp, gamePoint(window: m) != nil, let target = windowPoint(game: warp.x, warp.y) {
            SDL_WarpMouseInWindow(window, target.x, target.y)         // the release put the DOS mouse on the hand (FUN_1250_0415): the hand doesn't jump
            m = target
            lastMouse = m
        }
        let p = gamePoint(window: m)
        pointerHidden = p != nil
        updateCursor()
        guard m != lastMouse else { return }
        lastMouse = m
        if let p { input.handlePointer(x: p.x, y: p.y, phase: .move, world: w) }
    }

    /// Show or hide the system cursor when what the rules above want changes.
    func updateCursor() {
        let hide = keyHidden || pointerHidden
        guard hide != cursorHidden else { return }
        cursorHidden = hide
        if hide { SDL_HideCursor() } else { SDL_ShowCursor() }
    }
}
