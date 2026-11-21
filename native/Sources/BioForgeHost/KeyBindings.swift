// The player's key bindings: which keys, as USB HID keyboard usages (page 7: layout-independent key positions, what SDL's scancodes are),
// stand for which original PC key (scan code) or modifier flag. The engine still sees the original's scan codes and Shift / Ctrl / Alt
// flags (Keys); this only decides which keys produce them. Each control has a primary key and an alternate. The defaults need no numpad:
// arrows and Fn+arrows (Home/End/PgUp/PgDn) move and give the eight attack directions, `/` is keypad 5 (shoot), A holds the
// Ctrl attacks (kicks, since Control+arrows are Mac Mission Control shortcuts) and Option the Alt attacks (punches); the numpad
// keys stay bound as alternates. The Mac app translates NSEvent.keyCode through MacKeyCodes, and the bindings it saved as Mac key codes
// before the host layer are converted once (BindingsMigration). Pure Foundation, so every shell and the tests share it.
import BioForgeCore
import Foundation

public struct KeyBindings: Equatable, Sendable {
    /// One bindable control: a PC scan code, or a modifier flag the engine reads with every key (Keys.shift / ctrl / alt).
    public struct Control: Sendable, Identifiable {
        public enum Output: Equatable, Sendable { case scan(Int), modifier(Int) }
        public let id: String
        public let title: String
        public let group: String
        public let output: Output
        public let defaults: [UInt16]          // [primary, alternate]
    }

    public static let slots = 2

    // HID usages, by position on an ANSI keyboard.
    public static let controls: [Control] = [
        Control(id: "forward", title: "Walk Forward / Attack 8", group: "Movement", output: .scan(0x48), defaults: [0x52, 0x60]),   // ↑, KP8
        Control(id: "back", title: "Walk Back / Attack 2", group: "Movement", output: .scan(0x50), defaults: [0x51, 0x5A]),   // ↓, KP2
        Control(id: "turnLeft", title: "Turn Left / Attack 4", group: "Movement", output: .scan(0x4b), defaults: [0x50, 0x5C]),   // ←, KP4
        Control(id: "turnRight", title: "Turn Right / Attack 6", group: "Movement", output: .scan(0x4d), defaults: [0x4F, 0x5E]),   // →, KP6
        Control(id: "forwardLeft", title: "Walk Forward (Home) / Attack 7", group: "Movement", output: .scan(0x47), defaults: [0x4A, 0x5F]),   // Home, KP7
        Control(id: "forwardRight", title: "Walk Forward (Page Up) / Attack 9", group: "Movement", output: .scan(0x49), defaults: [0x4B, 0x61]),   // Page Up, KP9
        Control(id: "sidestepLeft", title: "Sidestep Left / Attack 1", group: "Movement", output: .scan(0x4f), defaults: [0x4D, 0x59]),   // End, KP1
        Control(id: "sidestepRight", title: "Sidestep Right / Attack 3", group: "Movement", output: .scan(0x51), defaults: [0x4E, 0x5B]),   // Page Down, KP3
        Control(id: "run", title: "Run (Shift)", group: "Movement", output: .modifier(Keys.shift), defaults: [0xE1, 0xE5]),   // left, right Shift
        Control(id: "combat", title: "Combat Mode On/Off", group: "Combat", output: .scan(0x2e), defaults: [0x06]),   // C
        Control(id: "kick", title: "Kicks: Hold with a Direction (Ctrl)", group: "Combat", output: .modifier(Keys.ctrl), defaults: [0x04, 0xE0]),   // A, left Control
        Control(id: "punch", title: "Punches: Hold with a Direction (Alt)", group: "Combat", output: .modifier(Keys.alt), defaults: [0xE2, 0xE6]),   // left, right Option
        Control(id: "shoot", title: "Shoot (Keypad 5)", group: "Combat", output: .scan(0x4c), defaults: [0x38, 0x5D]),   // /, KP5
        Control(id: "use", title: "Use", group: "Items", output: .scan(0x39), defaults: [0x2C]),   // Space
        Control(id: "pickup", title: "Pick Up / Put Down", group: "Items", output: .scan(0x1c), defaults: [0x28, 0x58]),   // Return, KP Enter
        Control(id: "pimm", title: "Personal Monitor", group: "Monitor", output: .scan(0x19), defaults: [0x13]),   // P
        Control(id: "inventory", title: "Inventory", group: "Monitor", output: .scan(0x17), defaults: [0x0C]),   // I
        Control(id: "diagnostics", title: "Diagnostics", group: "Monitor", output: .scan(0x20), defaults: [0x07]),   // D
        Control(id: "journal", title: "Journal", group: "Monitor", output: .scan(0x24), defaults: [0x0D]),   // J
        Control(id: "options", title: "Options", group: "Game", output: .scan(0x18), defaults: [0x12]),   // O
        Control(id: "save", title: "Save", group: "Game", output: .scan(0x1f), defaults: [0x16]),   // S
        Control(id: "load", title: "Load", group: "Game", output: .scan(0x26), defaults: [0x0F]),   // L
        Control(id: "credits", title: "Credits", group: "Game", output: .scan(0x13), defaults: [0x15]),   // R
        Control(id: "exit", title: "Exit (with Alt)", group: "Game", output: .scan(0x2d), defaults: [0x1B]),   // X
        Control(id: "version", title: "Version (with Alt)", group: "Game", output: .scan(0x2f), defaults: [0x19]),   // V
        Control(id: "gammaDown", title: "Darker (with Shift or Alt)", group: "Game", output: .scan(0x33), defaults: [0x36, 0x56]),   // , and KP-
        Control(id: "gammaUp", title: "Brighter (with Shift or Alt)", group: "Game", output: .scan(0x34), defaults: [0x37, 0x57]),   // . and KP+
    ]

    /// The modifier keys that arrive as flag changes on the Mac (left and right Control, Shift, Alt/Option). Caps Lock and Command are not
    /// here (see `reserved`).
    public static let modifierUsages: Set<UInt16> = [0xE0, 0xE1, 0xE2, 0xE4, 0xE5, 0xE6]
    /// Keys that can't be bound: Escape (backs out of every screen), Caps Lock, Command / GUI (macOS holds back key-ups while it's down).
    /// Fn has no usage; a key with no usage is 0, which `bind` refuses too.
    public static let reserved: Set<UInt16> = [0x29, 0x39, 0xE3, 0xE7]

    /// control id -> key per slot (nil = unbound).
    public private(set) var keys: [String: [UInt16?]]

    public init() { keys = Dictionary(uniqueKeysWithValues: Self.controls.map { ($0.id, Self.padded($0.defaults)) }) }

    private static func padded(_ k: [UInt16]) -> [UInt16?] { (0..<slots).map { k.indices.contains($0) ? k[$0] : nil } }

    public static func control(_ id: String) -> Control? { controls.first { $0.id == id } }

    public func key(_ id: String, slot: Int) -> UInt16? { keys[id]?[slot] ?? nil }

    /// Bind `key` to a control's slot; any other slot holding that key loses it, so a key always means one thing.
    public mutating func bind(_ key: UInt16?, to id: String, slot: Int) {
        guard keys[id] != nil, (0..<Self.slots).contains(slot) else { return }
        if let key {
            guard key != 0, !Self.reserved.contains(key) else { return }
            for (other, ks) in keys { keys[other] = ks.map { $0 == key ? nil : $0 } }
        }
        keys[id]?[slot] = key
    }

    /// The control a key is bound to, if any.
    public func control(for key: UInt16) -> Control? {
        Self.controls.first { c in keys[c.id]?.contains(key) == true }
    }

    /// The PC scan code a key produces (nil for modifiers and unbound keys).
    public func scan(for key: UInt16) -> Int? {
        if case .scan(let s)? = control(for: key)?.output { return s }
        return nil
    }

    /// The scan code a key press hands a script that captured the keyboard (CAPTUREKEYBOARD): the bound scan code, and Escape's own 0x01
    /// even though Escape can't be bound, since COMMON's GETESCKEY hook waits for it to skip the intro, the PLT0 scene and the AWAKEN quake.
    public func capturedScan(for key: UInt16) -> Int? { key == 0x29 ? 0x01 : scan(for: key) }

    /// True if the key is bound to a modifier (Run, kicks, punches).
    public func isModifier(_ key: UInt16) -> Bool {
        if case .modifier? = control(for: key)?.output { return true }
        return false
    }

    /// The engine's modifier flags for the keys being held.
    public func mods(held: Set<UInt16>) -> Int {
        held.reduce(0) { m, k in
            if case .modifier(let f)? = control(for: k)?.output { return m | f }
            return m
        }
    }

    // MARK: persistence (the Mac app stores [id: [Int]] under UserDefaults' "KeyBindingsHID", -1 = unbound; see BindingsMigration)

    public var propertyList: [String: [Int]] { keys.mapValues { $0.map { $0.map(Int.init) ?? -1 } } }

    /// Saved bindings over the defaults: unknown ids are ignored, missing controls keep their defaults.
    public init(propertyList p: [String: [Int]]) {
        self.init()
        for c in Self.controls {
            guard let saved = p[c.id] else { continue }
            keys[c.id] = Self.padded([])
            for (slot, k) in saved.prefix(Self.slots).enumerated() where (0...Int(UInt16.max)).contains(k) { bind(UInt16(k), to: c.id, slot: slot) }
        }
    }
}

/// The keys a running monitor or the options dialog reads (FUN_1250_0cf9), by HID usage, whatever the player's bindings: the PC scan code
/// the original's keyboard gave them (MonitorScreen.keyCode turns it into the event's key byte). Tab, Return, Space, the arrows (and Fn+arrows,
/// keypad 5 and the keypad digits for the diagonals) move the focus or press; letters and digits are the buttons' shortcut letters.
public enum MonitorKeys {
    public static func scan(forUsage usage: UInt16) -> Int? { table[usage] }

    private static let table: [UInt16: Int] = {
        var t: [UInt16: Int] = [0x2B: 0x0f, 0x28: 0x1c, 0x58: 0x1c, 0x2C: 0x39, 0x29: 0x01,                      // Tab, Return, KP Enter, Space, Escape
                                0x50: 0x4b, 0x4F: 0x4d, 0x51: 0x50, 0x52: 0x48, 0x4A: 0x47, 0x4D: 0x4f, 0x4B: 0x49, 0x4E: 0x51,   // arrows, Home, End, PgUp, PgDn
                                0x5D: 0x4c, 0x5F: 0x47, 0x60: 0x48, 0x61: 0x49, 0x5C: 0x4b, 0x5E: 0x4d, 0x59: 0x4f, 0x5A: 0x50, 0x5B: 0x51]   // KP5, KP7-9, KP4, KP6, KP1-3
        // Q W E R T Y U I O P, A S D F G H J K L, Z X C V B N, 1-0 (usage, scan)
        let letters: [(UInt16, Int)] = [(0x14, 0x10), (0x1A, 0x11), (0x08, 0x12), (0x15, 0x13), (0x17, 0x14), (0x1C, 0x15), (0x18, 0x16), (0x0C, 0x17), (0x12, 0x18), (0x13, 0x19),
                                        (0x04, 0x1e), (0x16, 0x1f), (0x07, 0x20), (0x09, 0x21), (0x0A, 0x22), (0x0B, 0x23), (0x0D, 0x24), (0x0E, 0x25), (0x0F, 0x26),
                                        (0x1D, 0x2c), (0x1B, 0x2d), (0x06, 0x2e), (0x19, 0x2f), (0x05, 0x30), (0x11, 0x31), (0x10, 0x32),
                                        (0x1E, 0x02), (0x1F, 0x03), (0x20, 0x04), (0x21, 0x05), (0x22, 0x06), (0x23, 0x07), (0x24, 0x08), (0x25, 0x09), (0x26, 0x0a), (0x27, 0x0b)]
        for (k, s) in letters { t[k] = s }
        return t
    }()
}
