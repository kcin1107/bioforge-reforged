import BioForgeCore
import Testing
@testable import BioForgeHost

/// Records every call the router makes, as text.
final class RecordingInput: GameInput {
    var keyboardCaptured = false, isOptionsOpen = false, isMonitorRunning = false, flicOpen = false
    var calls: [String] = []
    private func hex(_ n: Int) -> String { "0x" + String(n, radix: 16) }
    func keyDown(_ scan: Int, mods: Int) { calls.append("keyDown \(hex(scan)) mods \(hex(mods))") }
    func keyUp(_ scan: Int, mods: Int?) { calls.append("keyUp \(hex(scan)) mods \(mods.map(hex) ?? "nil")") }
    func keyEvent(scan: Int, mods: Int) { calls.append("keyEvent \(hex(scan)) mods \(hex(mods))") }
    func setKeyMods(_ mods: Int) { calls.append("setKeyMods \(hex(mods))") }
    func releaseKeys() { calls.append("releaseKeys") }
    func optionKey(_ name: String) -> String? { calls.append("optionKey \(name)"); return nil }
    func optionPointerMove(x: Int, y: Int) -> String? { calls.append("optionPointerMove \(x),\(y)"); return nil }
    func optionMouseDown() { calls.append("optionMouseDown") }
    func optionMouseUp() { calls.append("optionMouseUp") }
    func optionRightClick() -> String? { calls.append("optionRightClick"); return nil }
    func monitorKey(_ name: String) { calls.append("monitorKey \(name)") }
    func monitorPointerMove(x: Int, y: Int) { calls.append("monitorPointerMove \(x),\(y)") }
    func monitorMouseDown() { calls.append("monitorMouseDown") }
    func monitorMouseUp() { calls.append("monitorMouseUp") }
    func monitorRightClick() { calls.append("monitorRightClick") }
    /// The calls since the last take.
    func take() -> [String] { defer { calls = [] }; return calls }
}

private let up: UInt16 = 0x52, tab: UInt16 = 0x2B, ret: UInt16 = 0x28, escape: UInt16 = 0x29, keyL: UInt16 = 0x0F, keyA: UInt16 = 0x04
private let leftShift: UInt16 = 0xE1, space: UInt16 = 0x2C, keyQ: UInt16 = 0x14

private func down(_ u: UInt16, repeating: Bool = false, command: Bool = false) -> KeyEvent { KeyEvent(usage: u, kind: .down, isRepeat: repeating, command: command) }
private func release(_ u: UInt16) -> KeyEvent { KeyEvent(usage: u, kind: .up) }
private func modifier(_ u: UInt16, _ isDown: Bool, command: Bool = false) -> KeyEvent { KeyEvent(usage: u, kind: .modifiers, command: command, modifierDown: isDown) }

@MainActor
struct InputRouterTests {
    enum Screen: CaseIterable { case play, options, monitor, flic, captured }
    private func world(_ s: Screen) -> RecordingInput {
        let w = RecordingInput()
        switch s {
        case .play: break
        case .options: w.isOptionsOpen = true
        case .monitor: w.isMonitorRunning = true
        case .flic: w.flicOpen = true
        case .captured: w.keyboardCaptured = true
        }
        return w
    }

    @Test func everyKeyUpReachesTheWorld() {
        for s in Screen.allCases {
            let r = InputRouter(), w = world(s)
            r.handleKey(release(up), world: w)
            #expect(w.calls.contains { $0.hasPrefix("keyUp 0x48") }, "\(s)")
        }
    }

    @Test func monitorKeysEndTheirPressOnTheDialogAndMonitor() {
        for s in [Screen.options, .monitor] {
            let r = InputRouter(), w = world(s)
            r.handleKey(release(ret), world: w)
            #expect(w.calls == ["keyUp 0x1c mods 0x0", "keyUp 0x1c mods 0x0"], "\(s): the bound key-up, then the monitor table's")
        }
        let r = InputRouter(), w = world(.options)
        r.handleKey(release(tab), world: w)                    // Tab is no bound key: only the monitor table sends it
        #expect(w.take() == ["keyUp 0xf mods 0x0"])
    }

    @Test func aCapturedKeyboardGetsEveryPress() {
        let r = InputRouter(), w = world(.captured)
        r.handleKey(down(up), world: w); #expect(w.take() == ["keyEvent 0x48 mods 0x0"])
        r.handleKey(down(up, repeating: true), world: w); #expect(w.take() == [])
        r.handleKey(release(up), world: w); #expect(w.take() == ["keyUp 0x48 mods 0x0", "keyUp 0x48 mods 0x0"])   // the bound key-up, then the hook's
        r.handleKey(down(escape), world: w); #expect(w.take() == ["keyEvent 0x1 mods 0x0"])
        r.handleKey(down(0x3A), world: w); #expect(w.take() == [])          // F1: unbound
    }

    @Test func theOptionsDialogOwnsTheKeyboard() {
        var actions = 0
        let r = InputRouter(); r.onOptionsAction = { actions += 1 }
        let w = world(.options)
        r.handleKey(down(escape), world: w)
        #expect(w.take() == ["optionKey ESCAPE"] && actions == 1)
        r.handleKey(down(tab), world: w); #expect(w.take() == ["keyDown 0xf mods 0x0"])
        r.handleKey(down(tab, repeating: true), world: w); #expect(w.take() == [])
        w.flicOpen = true                                      // the dialog sits on a flic (credits roll): still the dialog
        r.handleKey(down(escape), world: w); #expect(w.take() == ["optionKey ESCAPE"])
    }

    @Test func aFlicIgnoresKeyDowns() {
        let r = InputRouter(), w = world(.flic)
        r.handleKey(down(up), world: w); #expect(w.take() == [])
        r.handleKey(release(up), world: w); #expect(w.take() == ["keyUp 0x48 mods 0x0"])
    }

    @Test func aMonitorTakesKeysThroughTheHookAndTheTable() {
        let r = InputRouter(), w = world(.monitor)
        r.handleKey(down(keyL), world: w); #expect(w.take() == ["keyDown 0x26 mods 0x0"])
        r.handleKey(down(tab), world: w); #expect(w.take() == ["keyDown 0xf mods 0x0"])
        r.handleKey(release(keyL), world: w); #expect(w.take().filter { $0 == "keyUp 0x26 mods 0x0" }.isEmpty == false)
        r.handleKey(down(0x3A), world: w); #expect(w.take() == [])          // F1 is in no table
    }

    @Test func escapeInPlayPressesO() {
        let r = InputRouter(), w = world(.play)
        r.handleKey(down(escape), world: w); #expect(w.take() == ["keyDown 0x18 mods 0x0", "keyUp 0x18 mods 0x0"])
        r.handleKey(down(escape, repeating: true), world: w); #expect(w.take() == [])
    }

    @Test func modifiersGoThroughSetKeyMods() {
        let r = InputRouter(), w = world(.play)
        r.handleKey(modifier(leftShift, true), world: w); #expect(w.take() == ["setKeyMods 0xc"])
        r.handleKey(down(keyA), world: w); #expect(w.take() == ["setKeyMods 0x3c"])          // A is bound to the kicks: a modifier, not a key
        r.handleKey(release(keyA), world: w); #expect(w.take().contains("setKeyMods 0xc"))
        r.handleKey(modifier(leftShift, false), world: w); #expect(w.take() == ["setKeyMods 0x0"])
    }

    @Test func aKickKeyAloneGivesTheCtrlFlag() {
        let r = InputRouter(), w = world(.play)
        r.handleKey(down(keyA), world: w); #expect(w.take() == ["setKeyMods 0x30"])
    }

    @Test func commandDropsPressesAndReleasesHeldKeys() {
        let r = InputRouter(), w = world(.play)
        r.handleKey(down(up, command: true), world: w)
        #expect(w.take() == [] && r.heldKeys.isEmpty)
        r.handleKey(down(up), world: w); _ = w.take()
        r.handleKey(modifier(leftShift, true), world: w); _ = w.take()
        r.handleKey(KeyEvent(usage: 0xE3, kind: .modifiers, command: true), world: w)       // Command goes down (the Mac tracks no device bit for it)
        #expect(w.take() == ["keyUp 0x48 mods 0xc", "setKeyMods 0xc", "setKeyMods 0xc"])   // the release, then the modifiers event's own
        #expect(r.heldKeys == [leftShift])
    }

    @Test func releasedModifiersAreDropped() {
        let r = InputRouter(), w = world(.play)
        r.handleKey(modifier(leftShift, true), world: w); _ = w.take()
        r.dropReleasedModifiers(down: [leftShift: true], world: w); #expect(w.take() == [])
        r.dropReleasedModifiers(down: [leftShift: false], world: w); #expect(w.take() == ["setKeyMods 0x0"] && r.heldKeys.isEmpty)
    }

    @Test func aPlayKeyDownCarriesTheModifiersAndCallsBack() {
        var presses = 0
        let r = InputRouter(); r.onPlayKeyDown = { presses += 1 }
        let w = world(.play)
        r.handleKey(down(up), world: w); #expect(w.take() == ["keyDown 0x48 mods 0x0"] && presses == 1)
        r.handleKey(release(up), world: w); _ = w.take()
        r.handleKey(modifier(leftShift, true), world: w); _ = w.take()
        r.handleKey(down(up), world: w); #expect(w.take() == ["keyDown 0x48 mods 0xc"] && presses == 2)
    }

    @Test func noWorldMeansNothingIsRouted() {
        let r = InputRouter()
        r.handleKey(down(up), world: nil)
        #expect(r.heldKeys == [up], "held keys are still tracked")
    }

    // MARK: controller

    @Test func padButtonsInPlay() {
        let r = InputRouter(), w = world(.play)
        r.handlePad(.button(.a, down: true), world: w); #expect(w.take() == ["keyDown 0x39 mods 0x0"])
        r.handlePad(.button(.a, down: false), world: w); #expect(w.take() == ["keyUp 0x39 mods 0x0"])
        r.handlePad(.button(.rightTrigger, down: true), world: w); #expect(w.take() == ["setKeyMods 0xc"] && r.padMods == 0xc)
        r.handlePad(.button(.rightTrigger, down: false), world: w); #expect(w.take() == ["setKeyMods 0x0"])
    }

    @Test func padButtonsOnAPointerScreen() {
        var actions = 0
        let r = InputRouter(); r.onOptionsAction = { actions += 1 }
        let w = world(.options)
        r.handlePad(.button(.a, down: true), world: w); #expect(w.take() == ["optionPointerMove 160,100", "optionMouseDown"])
        r.handlePad(.button(.a, down: false), world: w); #expect(w.take() == ["optionMouseUp", "keyUp 0x39 mods 0x0"])   // A is also Use: a button held into the screen is let go
        r.handlePad(.button(.b, down: true), world: w); #expect(w.take() == ["optionKey ESCAPE"] && actions == 1)
        w.isOptionsOpen = false; w.isMonitorRunning = true
        r.handlePad(.button(.b, down: true), world: w); #expect(w.take() == ["monitorKey ESCAPE"])
    }

    @Test func aModifierHeldIntoAPointerScreenIsLetGo() {
        let r = InputRouter(), w = world(.play)
        r.handlePad(.button(.rightTrigger, down: true), world: w); _ = w.take()
        w.isOptionsOpen = true
        r.handlePad(.button(.rightTrigger, down: false), world: w); #expect(w.take() == ["setKeyMods 0x0"] && r.padMods == 0)
    }

    @Test func theStickDirectionsMoveLexExceptOnAPointerScreen() {
        let r = InputRouter(), w = world(.play)
        r.handlePad(.direction(from: nil, to: "forward"), world: w); #expect(w.take() == ["keyDown 0x48 mods 0x0"])
        r.handlePad(.direction(from: "forward", to: "back"), world: w); #expect(w.take() == ["keyUp 0x48 mods 0x0", "keyDown 0x50 mods 0x0"])
        w.isMonitorRunning = true
        r.handlePad(.direction(from: "back", to: "forward"), world: w); #expect(w.take() == ["keyUp 0x50 mods 0x0"])
    }

    @Test func padScansOnACapturedKeyboardAndAFlic() {
        let r = InputRouter(), w = world(.captured)
        r.handlePad(.button(.a, down: true), world: w); #expect(w.take() == ["keyEvent 0x39 mods 0x0"])
        r.handlePad(.button(.a, down: false), world: w); #expect(w.take() == ["keyUp 0x39 mods 0x0"])
        let f = world(.flic)
        r.handlePad(.button(.a, down: true), world: f); #expect(f.take() == [])
        r.handlePad(.button(.a, down: false), world: f); #expect(f.take() == ["keyUp 0x39 mods 0x0"])
    }

    @Test func theStickMovesThePointerOnPointerScreens() {
        let r = InputRouter(), w = world(.options)
        r.movePointerWithPad(0.1, 0.1, world: w); #expect(w.take() == [])                      // dead zone
        r.movePointerWithPad(1, 0, world: w); #expect(w.take() == ["optionPointerMove 164,100"])
        r.movePointerWithPad(0, 1, world: w); #expect(w.take() == ["optionPointerMove 164,96"]) // up is y decreasing
        r.movePointerWithPad(0.9, 0, world: w); #expect(w.take() == ["optionPointerMove 167,96"])   // 3.6 px: the fraction stays
        r.movePointerWithPad(0.9, 0, world: w); #expect(w.take() == ["optionPointerMove 171,96"])   // 0.6 + 3.6 = 4.2
        for _ in 0..<200 { r.movePointerWithPad(-1, 1, world: w) }
        #expect(r.pointerPosition.x == 0 && r.pointerPosition.y == 0)
        for _ in 0..<200 { r.movePointerWithPad(1, -1, world: w) }
        #expect(r.pointerPosition.x == 319 && r.pointerPosition.y == 199)
        let p = world(.play)
        r.movePointerWithPad(1, 0, world: p); #expect(p.take() == [])
    }

    // MARK: pointer

    @Test func pointerOnTheOptionsDialog() {
        var actions = 0
        let r = InputRouter(); r.onOptionsAction = { actions += 1 }
        let w = world(.options)
        r.handlePointer(x: 10, y: 20, phase: .move, world: w); #expect(w.take() == ["optionPointerMove 10,20"])
        r.handlePointer(x: 11, y: 21, phase: .down, world: w); #expect(w.take() == ["optionPointerMove 11,21", "optionMouseDown"] && r.pointerHeld)
        r.handlePointer(x: nil, y: nil, phase: .up, world: w); #expect(w.take() == ["optionMouseUp"] && !r.pointerHeld)
        #expect(r.pointerPosition.x == 11 && r.pointerPosition.y == 21, "nil keeps the position")
        r.handlePointer(x: 1, y: 2, phase: .rightDown, world: w); #expect(w.take() == ["optionRightClick"] && actions == 1)
    }

    @Test func pointerOnAMonitor() {
        let r = InputRouter(), w = world(.monitor)
        r.handlePointer(x: 10, y: 20, phase: .move, world: w); #expect(w.take() == ["monitorPointerMove 10,20"])
        r.handlePointer(x: 11, y: 21, phase: .down, world: w); #expect(w.take() == ["monitorPointerMove 11,21", "monitorMouseDown"])
        r.handlePointer(x: nil, y: nil, phase: .up, world: w); #expect(w.take() == ["monitorMouseUp"])
        r.handlePointer(x: 1, y: 2, phase: .rightDown, world: w); #expect(w.take() == ["monitorRightClick"])
    }

    @Test func pointerInPlayRoutesNothingAndReleaseOnlyWhileHeld() {
        let r = InputRouter(), p = world(.play)
        r.handlePointer(x: 10, y: 20, phase: .down, world: p); #expect(p.take() == [] && r.pointerHeld)
        let w = world(.options)
        r.releasePointer(world: w); #expect(w.take() == ["optionMouseUp"] && !r.pointerHeld)
        r.releasePointer(world: w); #expect(w.take() == [])
    }

    @Test func bindingsAndReleaseAll() {
        let r = InputRouter(), w = world(.play)
        r.handleKey(down(up), world: w); r.handlePad(.button(.rightTrigger, down: true), world: w); _ = w.take()
        r.setBindings(KeyBindings(), world: w)
        #expect(r.heldKeys.isEmpty && r.padMods == 0xc && w.take() == ["releaseKeys"])
        r.setPadBindings(PadBindings(), world: w)
        #expect(r.padMods == 0 && w.take() == ["releaseKeys"])
        r.handleKey(down(up), world: w); r.handlePad(.button(.rightTrigger, down: true), world: w); _ = w.take()
        r.releaseAll(world: w)
        #expect(r.heldKeys.isEmpty && r.padMods == 0 && w.take() == ["releaseKeys"])
    }
}
