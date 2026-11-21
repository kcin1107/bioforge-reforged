// Player key mapping of the original handler FUN_10a8_0541, mirrors re/interp/keys.py.
//
// action(scan:mods:combat:playing:) maps a PC scan code (arrows/Home/End/PgUp/PgDn and the numpad share codes: the original told
// them apart only by combat mode), the modifier flags (0x0c Shift, 0x30 Ctrl, 0xc0 Alt) and the name of the motion the player is
// playing (only used by the combat M4/M6 rule) to a KeyAction. The host layer's KeyBindings turn key usages into these scan codes; on a Mac
// keyboard Fn+Left/Right/Up/Down already arrive as Home/End/PgUp/PgDn, which the game treats like the keypad 7/1/9/3 keys.
import Foundation

public enum KeyAction: Equatable, Sendable {
    case motion(String)               // lasts while the key is held (walk, run, turn_*, sidestep_*, atk_M*)
    case oneshot(String)              // started once (shoot, atk_shoot, atk_F*, atk_H*)
    case use, combatToggle, pickup
    case pimm(String)                 // "INVENTORY", "" (main), "DIAGNOSTICS", "JOURNAL"
    case options, credits, save, load, exit, version
    case gamma(Int)

    /// (action, detail) as logged by the prototype's key_log.
    public var name: String {
        switch self {
        case .motion: return "motion"
        case .oneshot: return "oneshot"
        case .use: return "use"
        case .combatToggle: return "combat_toggle"
        case .pickup: return "pickup"
        case .pimm: return "pimm"
        case .save: return "save"
        case .options: return "options"
        case .credits: return "credits"
        case .load: return "load"
        case .exit: return "exit"
        case .version: return "version"
        case .gamma: return "gamma"
        }
    }
    public var detail: String? {
        switch self {
        case .motion(let m), .oneshot(let m), .pimm(let m): return m
        case .gamma(let g): return String(g)
        default: return nil
        }
    }
}

public enum Keys {
    public static let shift = 0x0c, ctrl = 0x30, alt = 0xc0       // ASSUMPTION (NOTES: "probably"; Alt+V = version)

    static let walkKeys: Set<Int> = [0x48, 0x47, 0x49]            // up, Home, PgUp (also numpad 8 / 7 / 9)
    static let moves: [Int: String] = [0x4b: "turn_left", 0x4d: "turn_right", 0x50: "walk_back", 0x4f: "sidestep_left", 0x51: "sidestep_right"]
    static let fast = ["turn_left": "turn_left_fast", "turn_right": "turn_right_fast"]
    static let combatPad: [Int: Int] = [0x47: 7, 0x48: 8, 0x49: 9, 0x4b: 4, 0x4d: 6, 0x4f: 1, 0x50: 2, 0x51: 3]
    /// M4/M6 only start when none of these is playing (the key's own motion may continue).
    static let m46Busy: Set<String> = ["atk_m1", "atk_m2", "atk_m3", "atk_m4", "atk_m6", "atk_m7", "atk_m8", "run", "atk_m9"]
    static let pimm: [Int: String] = [0x17: "INVENTORY", 0x19: "", 0x20: "DIAGNOSTICS", 0x24: "JOURNAL"]
    static let gamma: [Int: Int] = [0x33: -10, 0x34: 10, 0x4a: -10, 0x4e: 10]            // , . numpad- numpad+

    public static func action(scan: Int, mods: Int, combat: Bool, playing: String? = nil) -> KeyAction? {
        let playing = (playing ?? "").lowercased()
        if let screen = pimm[scan] { return mods == 0 ? .pimm(screen) : nil }
        if let g = gamma[scan] { return mods & (shift | alt) != 0 ? .gamma(g) : nil }
        if scan == 0x2f { return mods & alt != 0 ? .version : nil }
        switch scan {
        case 0x2e: return .combatToggle
        case 0x39: return .use
        case 0x1f: return mods & alt == 0 ? .save : nil         // S: ignored with Alt (FUN_10a8_0541)
        case 0x2d: return mods & alt != 0 ? .exit : nil         // Alt+X (global hook FUN_1128_0f7f)
        case 0x13: return .credits
        case 0x18: return .options
        case 0x26: return .load
        case 0x1c: return .pickup
        default: break
        }
        if combat {
            if scan == 0x48 && mods & shift != 0 { return .motion("run") }
            if scan == 0x4c { return .oneshot("atk_shoot") }
            guard let pad = combatPad[scan] else { return nil }
            let kind = mods & ctrl != 0 ? "F" : mods & alt != 0 ? "H" : "M"
            let name = "atk_\(kind)\(pad)"
            if (scan == 0x4b || scan == 0x4d) && kind == "M" && m46Busy.contains(playing) && playing != name.lowercased() { return nil }
            return kind == "M" ? .motion(name) : .oneshot(name)
        }
        if walkKeys.contains(scan) { return .motion(mods & shift != 0 ? "run" : "walk") }
        if let name = moves[scan] { return .motion(mods & shift != 0 ? fast[name] ?? name : name) }
        if scan == 0x4c { return .oneshot("shoot") }
        return nil
    }
}
