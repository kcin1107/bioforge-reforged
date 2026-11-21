// The input routing every shell shares: key events (as HID usages) and controller events in, the calls the game's World takes out, in the
// order the Mac app's key handler always used. The shell turns its own events into `KeyEvent`s and pointer phases and keeps what is
// platform-specific (hiding the cursor, the Mac's modifier flags, dialogs); everything that decides where a key goes lives here.
import BioForgeCore
import Foundation

/// The part of World the routing calls (signatures as World declares them), so tests can record the calls.
public protocol GameInput: AnyObject {
    var keyboardCaptured: Bool { get }
    var isOptionsOpen: Bool { get }
    var isMonitorRunning: Bool { get }
    var flicOpen: Bool { get }
    func keyDown(_ scan: Int, mods: Int)
    func keyUp(_ scan: Int, mods: Int?)
    func keyEvent(scan: Int, mods: Int)
    func setKeyMods(_ mods: Int)
    func releaseKeys()
    func optionKey(_ name: String) -> String?
    func optionPointerMove(x: Int, y: Int) -> String?
    func optionMouseDown()
    func optionMouseUp()
    func optionRightClick() -> String?
    func monitorKey(_ name: String)
    func monitorPointerMove(x: Int, y: Int)
    func monitorMouseDown()
    func monitorMouseUp()
    func monitorRightClick()
}

extension World: GameInput {}

public enum PointerPhase: Sendable { case move, down, up, rightDown }

public struct KeyEvent: Sendable {
    public enum Kind: Sendable { case down, up, modifiers }
    public var usage: UInt16            // 0: the key has no HID usage
    public var kind: Kind
    public var isRepeat: Bool
    public var command: Bool            // Command (GUI) is held
    public var modifierDown: Bool?      // .modifiers only: whether this modifier key is now down (nil: not one the host tracks)

    public init(usage: UInt16, kind: Kind, isRepeat: Bool = false, command: Bool = false, modifierDown: Bool? = nil) {
        self.usage = usage; self.kind = kind; self.isRepeat = isRepeat; self.command = command; self.modifierDown = modifierDown
    }
}

public final class InputRouter {
    public private(set) var bindings = KeyBindings()
    public private(set) var padBindings = PadBindings()
    public private(set) var heldKeys = Set<UInt16>()            // keys (HID usages) down now, for the bound modifiers
    public var padMods = 0                                       // modifier flags held on the controller
    public var pointerPosition = (x: 160, y: 100)                // the engine centres the mouse at start-up (FUN_1058_066d(0xa0, 100))
    /// The mouse went down on a pointer screen and has not come up yet (releasePointer lets go of it).
    public var pointerHeld = false
    public var pointerRemainder = (x: 0.0, y: 0.0)
    /// Called right after a play key-down reached the world (the Mac logs the key there).
    public var onPlayKeyDown: (() -> Void)?
    /// Called after an options-dialog action that may ask the app to quit, start a new game or load a save.
    public var onOptionsAction: (() -> Void)?

    public init() {}

    /// PC modifier flags of the key handler (0x0c Shift, 0x30 Ctrl, 0xc0 Alt), from the held keys bound to Run, kicks and punches.
    public var pcMods: Int { bindings.mods(held: heldKeys) | padMods }

    /// A new set of key bindings: the keys held under the old ones are let go.
    public func setBindings(_ b: KeyBindings, world: GameInput?) {
        bindings = b
        heldKeys.removeAll()
        world?.releaseKeys()
    }

    public func setPadBindings(_ b: PadBindings, world: GameInput?) {
        padBindings = b
        padMods = 0
        world?.releaseKeys()
    }

    /// Everything held is let go (the game is suspended, or the window lost the keyboard).
    public func releaseAll(world: GameInput?) {
        heldKeys.removeAll()
        padMods = 0
        world?.releaseKeys()
    }

    /// Run, kicks and punches on Shift, Control or Option stay held only while the system says that modifier is down: a release the
    /// window never sees (a Cmd+Shift+4 screenshot takes the key-up) left Lex running until the key was pressed again.
    public func dropReleasedModifiers(down: [UInt16: Bool], world w: GameInput) {
        let stale = heldKeys.filter { down[$0] == false }
        guard !stale.isEmpty else { return }
        heldKeys.subtract(stale)
        w.setKeyMods(pcMods)
    }

    /// Let go of every held key that isn't Shift, Control or Option (their own flags still arrive while Command is down).
    private func releaseKeysForCommand(_ world: GameInput?) {
        let keys = heldKeys.filter { !KeyBindings.modifierUsages.contains($0) }
        guard !keys.isEmpty else { return }
        heldKeys.subtract(keys)
        guard let w = world else { return }
        for k in keys { if let scan = bindings.scan(for: k) ?? bindings.capturedScan(for: k) { w.keyUp(scan, mods: pcMods) } }
        w.setKeyMods(pcMods)
    }

    private func trackHeld(_ e: KeyEvent) {
        switch e.kind {
        case .down: heldKeys.insert(e.usage)
        case .up: heldKeys.remove(e.usage)
        case .modifiers:
            guard let down = e.modifierDown else { break }
            if down { heldKeys.insert(e.usage) } else { heldKeys.remove(e.usage) }
        }
    }

    public func handleKey(_ e: KeyEvent, world: GameInput?) {
        let usage = e.usage
        // macOS sends no key-up for a key released while Command is down, nor for a key pressed with it: such a key (a letter bound to
        // walking, or a modifier control on a letter such as Kick on A) stayed held until pressed again. A key pressed with Command is a
        // shortcut, not a game key, and Command going down lets go of every held key that isn't a modifier.
        if e.command {
            if e.kind == .down { return }
            if e.kind == .modifiers { releaseKeysForCommand(world) }
        }
        trackHeld(e)
        guard let w = world else { return }
        // Every key-up reaches the world, whichever screen is up: a key released during a flic, a monitor or the dialog must not stay
        // held afterwards (Lex walked on by himself after a cutscene). keyUp only forgets the key.
        if e.kind == .up, let scan = bindings.scan(for: usage) { w.keyUp(scan, mods: pcMods) }
        if e.kind == .up, w.isMonitorRunning || w.isOptionsOpen, let scan = MonitorKeys.scan(forUsage: usage) { w.keyUp(scan, mods: pcMods) }     // ends a held Return / Escape press
        // A monitor or the dialog takes the keys before a script's keyboard hook: the original's dispatcher (FUN_10e8_11e3) gives them to
        // the monitor (FUN_1100_0769) while one is up and only otherwise to the player handler, where the hook lives. In the zero-G room
        // (ZEROG_KEYBOARD) Escape could not close the PIMM or the dialog.
        if w.keyboardCaptured && !w.isOptionsOpen && !w.isMonitorRunning {
            // A script holds the keyboard (CAPTUREKEYBOARD): every key press runs its hook block; the normal handler is bypassed.
            guard let scan = bindings.capturedScan(for: usage) else { return }
            if e.kind == .down && !e.isRepeat { w.keyEvent(scan: scan, mods: pcMods) }
            else if e.kind == .up { w.keyUp(scan, mods: pcMods) }
            return
        }
        if w.isOptionsOpen {
            // The dialog owns the keyboard: Escape backs out. It can sit on a flic (the ending's credits roll), so it comes before the flic test.
            if e.kind == .down, usage == 0x29, !e.isRepeat {
                _ = w.optionKey("ESCAPE")
                onOptionsAction?()
            } else if e.kind == .down, !e.isRepeat, let scan = MonitorKeys.scan(forUsage: usage), usage != 0x29 {
                w.keyDown(scan, mods: pcMods)             // the dialog's own event handler falls back to the monitor's keys (FUN_1250_0cf9): Tab, arrows, Return, letters
            }
            return
        }
        if w.flicOpen { return }          // an open flic ignores the keyboard (10a8:02cc)
        if w.isMonitorRunning {
            // Every key reaches the monitor's event handler (FUN_10e8_11e3 -> FUN_1250_0cf9): Tab, the arrows, Return and Space, Escape, L and the
            // shortcut letters. The global hook (FUN_1128_0f7f) still answers L (with Alt) and Alt+X while a monitor runs; keyDown does both.
            if e.kind == .down && !e.isRepeat {
                let hook = bindings.scan(for: usage).flatMap { $0 == 0x26 || $0 == 0x2d ? $0 : nil }
                if let scan = hook ?? MonitorKeys.scan(forUsage: usage) { w.keyDown(scan, mods: pcMods) }
            } else if e.kind == .up, let scan = bindings.scan(for: usage), scan == 0x26 || scan == 0x2d { w.keyUp(scan, mods: pcMods) }
            return
        }
        if usage == 0x29 {
            // Escape in play opens the options dialog, the game's pause (like O); Escape closes it again. The original does nothing
            // with Escape here (it is not in FUN_10a8_0541's cases), so this is the port's addition.
            if e.kind == .down && !e.isRepeat { w.keyDown(0x18, mods: 0); w.keyUp(0x18, mods: 0) }     // a press: Escape's own key up never reaches O
            return
        }
        let mods = pcMods
        if e.kind == .modifiers || bindings.isModifier(usage) { w.setKeyMods(mods); return }
        switch e.kind {
        case .down:
            guard !e.isRepeat, let scan = bindings.scan(for: usage) else { return }
            w.keyDown(scan, mods: mods)
            onPlayKeyDown?()
        case .up:
            if let scan = bindings.scan(for: usage) { w.keyUp(scan, mods: mods) }
        case .modifiers: break
        }
    }

    // MARK: controller

    /// True while the game shows a screen driven by the pointer rather than Lex (the options dialog, a monitor).
    public static func padDrivesPointer(_ w: GameInput) -> Bool { !w.flicOpen && (w.isOptionsOpen || w.isMonitorRunning) }

    public func handlePad(_ event: PadTracker.Event, world w: GameInput) {
        let ui = Self.padDrivesPointer(w)
        switch event {
        case .button(let b, let down):
            if ui {                                      // HIG "Game controls": outside gameplay A activates and B goes back
                if b == .a { handlePointer(x: pointerPosition.x, y: pointerPosition.y, phase: down ? .down : .up, world: w) }
                if b == .b && down {
                    if w.isOptionsOpen { _ = w.optionKey("ESCAPE"); onOptionsAction?() } else { w.monitorKey("ESCAPE") }
                }
                // A button held into the screen is still let go: a Run, Kick or Punch modifier released here stayed on afterwards.
                if !down, let id = padBindings.control(for: b), let c = KeyBindings.control(id) { padControl(c, down: false, w) }
            } else if let id = padBindings.control(for: b), let c = KeyBindings.control(id) {
                padControl(c, down: down, w)
            }
        case .direction(let from, let to):
            if let c = from.flatMap(KeyBindings.control) { padControl(c, down: false, w) }
            guard !ui else { return }
            if let c = to.flatMap(KeyBindings.control) { padControl(c, down: true, w) }
        }
    }

    /// The controller's route to the engine, in the order of handleKey.
    private func padControl(_ c: KeyBindings.Control, down: Bool, _ w: GameInput) {
        switch c.output {
        case .modifier(let flag):
            if down { padMods |= flag } else { padMods &= ~flag }
            w.setKeyMods(pcMods)
        case .scan(let scan):
            if w.keyboardCaptured {
                if down { w.keyEvent(scan: scan, mods: pcMods) } else { w.keyUp(scan, mods: pcMods) }
            } else if !w.flicOpen || !down {
                if down { w.keyDown(scan, mods: pcMods) } else { w.keyUp(scan, mods: pcMods) }
            }
        }
    }

    /// On a pointer screen the stick moves the pointer, up to 240 pixels a second.
    public func movePointerWithPad(_ x: Double, _ y: Double, world w: GameInput) {
        guard Self.padDrivesPointer(w), hypot(x, y) >= PadBindings.deadZone else { return }
        pointerRemainder.x += x * 4
        pointerRemainder.y -= y * 4
        let dx = Int(pointerRemainder.x), dy = Int(pointerRemainder.y)
        pointerRemainder.x -= Double(dx)
        pointerRemainder.y -= Double(dy)
        handlePointer(x: max(0, min(319, pointerPosition.x + dx)), y: max(0, min(199, pointerPosition.y + dy)), phase: .move, world: w)
    }

    // MARK: pointer

    public func handlePointer(x: Int?, y: Int?, phase: PointerPhase, world: GameInput?) {
        switch phase { case .down: pointerHeld = true; case .up: pointerHeld = false; case .move, .rightDown: break }
        guard let w = world else { return }
        if let x, let y { pointerPosition = (x, y) }
        if w.isOptionsOpen {
            // As in play.py: the pointer's press animation presses the control under it, and its release activates it (a later tick,
            // GameHost.advance) only if the pointer is still over it.
            switch phase {
            case .move: if let x, let y { _ = w.optionPointerMove(x: x, y: y) }
            case .down:
                if let x, let y {
                    _ = w.optionPointerMove(x: x, y: y)
                    w.optionMouseDown()
                }
            case .up: w.optionMouseUp()
            case .rightDown: _ = w.optionRightClick(); onOptionsAction?()       // the right button is Escape (FUN_1250_0cf9)
            }
            return
        }
        guard w.isMonitorRunning else { return }
        switch phase {
        case .move:
            if let x, let y { w.monitorPointerMove(x: x, y: y) }
        case .down:
            if let x, let y {
                w.monitorPointerMove(x: x, y: y)
                w.monitorMouseDown()
            }
        case .up: w.monitorMouseUp()
        case .rightDown: w.monitorRightClick()
        }
    }

    /// A press on a monitor or the dialog turns its input off until the release (FUN_1250_0415); a release that goes to another app
    /// would leave every key, Escape included, ignored there.
    public func releasePointer(world: GameInput?) {
        if pointerHeld { handlePointer(x: nil, y: nil, phase: .up, world: world) }
    }
}
