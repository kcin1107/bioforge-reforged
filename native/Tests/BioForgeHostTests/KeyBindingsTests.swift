import BioForgeCore
import Testing
@testable import BioForgeHost

/// The old fixed Mac mapping (the former Keys.macScan): kVK -> PC scan code, for the keys the game uses.
private let oldMacScan: [UInt16: Int] = [
    126: 0x48, 91: 0x48, 115: 0x47, 89: 0x47, 116: 0x49, 92: 0x49,           // up/KP8, Home/KP7, PgUp/KP9
    123: 0x4b, 86: 0x4b, 124: 0x4d, 88: 0x4d, 125: 0x50, 84: 0x50,           // left/KP4, right/KP6, down/KP2
    119: 0x4f, 83: 0x4f, 121: 0x51, 85: 0x51, 87: 0x4c,                      // End/KP1, PgDn/KP3, KP5
    8: 0x2e, 49: 0x39, 34: 0x17, 35: 0x19, 2: 0x20, 38: 0x24,                // C, Space, I, P, D, J
    1: 0x1f, 15: 0x13, 9: 0x2f, 43: 0x33, 47: 0x34, 78: 0x4a, 69: 0x4e,      // S, R, V, comma, period, KP-, KP+
    31: 0x18, 37: 0x26, 7: 0x2d, 36: 0x1c, 76: 0x1c,                         // O, L, X, Return, KP Enter
]

/// The Mac key's HID usage, for writing the tests in the Mac key codes they were first written with.
private func usage(_ kVK: UInt16) -> UInt16 { MacKeyCodes.usage(forKeyCode: kVK)! }

// The remappable keys (KeyBindings): numpad-free defaults that still produce the original's scan codes and flags.
struct KeyBindingsTests {
    static let keypad: Set<UInt16> = Set([65, 67, 69, 71, 75, 76, 78, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92].map(usage))

    @Test func defaultsReachEveryControlWithoutANumpad() {
        let b = KeyBindings()
        for c in KeyBindings.controls {
            let primary = b.key(c.id, slot: 0)
            #expect(primary != nil && !Self.keypad.contains(primary!), "\(c.id) needs a non-keypad primary key")
        }
    }

    @Test func escapeReachesACapturedKeyboard() {
        // Escape can't be bound, but a captured keyboard (the intro's GETESCKEY hook) still gets its scan code 0x01.
        var b = KeyBindings()
        b.bind(0x29, to: KeyBindings.controls[0].id, slot: 0)
        #expect(b.scan(for: 0x29) == nil)
        #expect(b.capturedScan(for: 0x29) == 0x01)
        let bound = b.key(KeyBindings.controls.first { if case .scan = $0.output { return true }; return false }!.id, slot: 0)!
        #expect(b.capturedScan(for: bound) == b.scan(for: bound))
    }

    @Test func reservedKeysAndNoUsageCantBeBound() {
        var b = KeyBindings()
        for key: UInt16 in [0, 0x29, 0x39, 0xE3, 0xE7] {
            b.bind(key, to: "use", slot: 0)
            #expect(b.key("use", slot: 0) == 0x2C, "\(key) is refused")
        }
    }

    @Test func defaultsActLikeTheOriginalMapping() {
        // Every Mac key the fixed mapping knew, through MacKeyCodes, gives the same game action through the bindings, in and out of combat.
        let b = KeyBindings()
        for (mac, scan) in oldMacScan {
            let bound = b.scan(for: usage(mac))
            #expect(bound != nil, "key \(mac) is unbound")
            for mods in [0, Keys.shift, Keys.ctrl, Keys.alt] {
                for combat in [false, true] {
                    #expect(Keys.action(scan: bound ?? -1, mods: mods, combat: combat) == Keys.action(scan: scan, mods: mods, combat: combat),
                            "key \(mac) mods \(mods) combat \(combat)")
                }
            }
        }
        #expect(b.scan(for: usage(36)) == 0x1c && b.scan(for: usage(76)) == 0x1c, "Return and keypad Enter pick up")
    }

    @Test func modifiersComeFromHeldKeys() {
        let b = KeyBindings()
        let shift = usage(56), a = usage(0), up = usage(126), option = usage(58), control = usage(59), slash = usage(44)
        #expect(b.mods(held: []) == 0)
        #expect(b.mods(held: [shift]) == Keys.shift)
        #expect(b.mods(held: [a, up]) == Keys.ctrl, "A holds the kicks")
        #expect(b.mods(held: [option, control]) == Keys.alt | Keys.ctrl)
        #expect(b.isModifier(a) && !b.isModifier(up))
        // Without a numpad, A + Up is a Ctrl attack in combat and / shoots.
        #expect(Keys.action(scan: b.scan(for: up)!, mods: b.mods(held: [a]), combat: true) == .oneshot("atk_F8"))
        #expect(Keys.action(scan: b.scan(for: slash)!, mods: 0, combat: true) == .oneshot("atk_shoot"))
    }

    @Test func bindingAKeyTakesItFromItsOldControl() {
        var b = KeyBindings()
        b.bind(usage(126), to: "use", slot: 1)
        #expect(b.key("forward", slot: 0) == nil)
        #expect(b.scan(for: usage(126)) == 0x39)
        b.bind(0x29, to: "use", slot: 0)                      // Escape is reserved
        #expect(b.key("use", slot: 0) == usage(49))
        b.bind(nil, to: "use", slot: 0)
        #expect(b.scan(for: usage(49)) == nil)
    }

    @Test func savedBindingsRoundTrip() {
        var b = KeyBindings()
        b.bind(usage(13), to: "forward", slot: 0)
        b.bind(nil, to: "shoot", slot: 1)
        let restored = KeyBindings(propertyList: b.propertyList)
        #expect(restored == b)
        #expect(KeyBindings(propertyList: ["nonsense": [1], "use": [-1, 99999]]).key("use", slot: 0) == nil)
        #expect(KeyBindings(propertyList: [:]) == KeyBindings())
    }
}
