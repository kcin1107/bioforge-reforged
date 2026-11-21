// The settings screen of the shells without a menu bar (the Mac's menus and Settings window): a small list drawn over the frozen game picture,
// driven by the arrows and Return or the controller's D-pad and A. It holds no settings itself: the host (the shell) has the values, applies a
// change and saves it. Pages: the main list, the keyboard bindings and the controller bindings. The game's own options dialog keeps
// volume, gamma, subtitles and the difficulty.
import BioForgeCore
import Foundation

@MainActor
public protocol SettingsScreenHost: AnyObject {
    var fullScreen: Bool { get set }
    var correctAspect: Bool { get set }
    var music: MusicArrangement? { get set }      // General MIDI, AdLib or Off (nil)
    /// Shown on the prompt line while the cursor is on the Music row (e.g. that General MIDI plays as AdLib for want of a SoundFont).
    var musicNote: String? { get }
    var muted: Bool { get set }
    var language: String { get set }              // "E", "G" or "F"
    var readableText: Bool { get set }
    var keyBindings: KeyBindings { get set }
    var padBindings: PadBindings { get set }
    func keyName(_ usage: UInt16) -> String
    func padLabel(_ b: PadButton) -> String
}

@MainActor
public final class SettingsScreen {
    public enum Action { case up, down, left, right, activate, back, clear }
    public enum Page { case main, keys, pad }
    public enum Capture: Equatable { case key(String, Int), pad(String) }

    private let host: SettingsScreenHost
    private let shellKeys: Set<UInt16>
    public private(set) var isOpen = false
    public private(set) var page = Page.main
    public private(set) var cursor = 0
    public private(set) var top = 0                  // the first row shown
    public private(set) var slot = 0                 // the keys page's column
    public private(set) var capturing: Capture?
    public private(set) var message: String?
    /// The last input came from a controller: the footer names its buttons.
    public var lastInputWasPad = false
    /// Rows that fit on the screen; render sets it from the font.
    var capacity = 12

    /// The font it is drawn in (the game folder's DATA/SMALL.FNT: 1.FNT's letters are too wide for the footer line).
    public static let fontFile = "DATA/SMALL.FNT"

    static let languages = ["E", "G", "F"]
    static let languageNames = ["E": "English", "G": "Deutsch", "F": "Français"]
    static let mainRows = ["Full Screen", "Aspect Ratio", "Music", "Mute", "Language", "Readable Text", "Keyboard Controls…", "Controller…", "Done"]
    /// The controls the controller can rebind: not the eight directions, which are the stick and the D-pad.
    public static let padControls = KeyBindings.controls.filter { !PadBindings.directions.contains($0.id) }

    /// `shellKeys`: keys the shell keeps for itself (F1, F11), which can't be bound.
    public init(host: SettingsScreenHost, shellKeys: Set<UInt16> = [0x3A, 0x44]) { self.host = host; self.shellKeys = shellKeys }

    public func open() { isOpen = true; go(.main); capturing = nil }
    public func close() { isOpen = false; capturing = nil; message = nil }

    private func go(_ p: Page, cursor c: Int = 0) { page = p; cursor = c; top = 0; slot = 0; message = nil; ensureVisible() }

    public var rowCount: Int {
        switch page {
        case .main: Self.mainRows.count
        case .keys: KeyBindings.controls.count + 2
        case .pad: Self.padControls.count + 2
        }
    }

    /// The control a keys or pad page row stands for, nil on Reset to Defaults and Back.
    public func control(at row: Int) -> KeyBindings.Control? {
        switch page {
        case .main: nil
        case .keys: KeyBindings.controls.indices.contains(row) ? KeyBindings.controls[row] : nil
        case .pad: Self.padControls.indices.contains(row) ? Self.padControls[row] : nil
        }
    }

    private func ensureVisible() {
        if cursor < top { top = cursor }
        if cursor >= top + capacity { top = cursor - capacity + 1 }
        top = max(0, min(top, max(0, rowCount - capacity)))
    }

    // MARK: input

    public func handle(_ a: Action) {
        guard isOpen else { return }
        message = nil
        switch capturing {
        case .key?: if a == .back { capturing = nil }; return
        case .pad?: if a != .activate && a != .clear { capturing = nil }; return
        case nil: break
        }
        switch a {
        case .up: cursor = (cursor + rowCount - 1) % rowCount; ensureVisible()
        case .down: cursor = (cursor + 1) % rowCount; ensureVisible()
        case .back: if page == .main { close() } else { go(.main, cursor: page == .keys ? 6 : 7) }
        case .left, .right, .activate, .clear:
            switch page {
            case .main: mainAction(a)
            case .keys: keysAction(a)
            case .pad: padAction(a)
            }
        }
    }

    private func mainAction(_ a: Action) {
        guard a != .clear else { return }
        let step = a == .left ? -1 : 1
        switch cursor {
        case 0: host.fullScreen.toggle()
        case 1: host.correctAspect.toggle()
        case 2:
            let choices: [MusicArrangement?] = [.generalMIDI, .adlib, nil]
            let i = choices.firstIndex { $0 == host.music } ?? 0
            host.music = choices[(i + step + choices.count) % choices.count]
        case 3: host.muted.toggle()
        case 4:
            let i = Self.languages.firstIndex(of: host.language) ?? 0
            host.language = Self.languages[(i + step + Self.languages.count) % Self.languages.count]
        case 5: host.readableText.toggle()
        case 6: if a == .activate { go(.keys) }
        case 7: if a == .activate { go(.pad) }
        default: if a == .activate { close() }
        }
    }

    private func keysAction(_ a: Action) {
        guard let c = control(at: cursor) else {
            if a == .activate { if cursor == rowCount - 2 { host.keyBindings = KeyBindings() } else { go(.main, cursor: 6) } }
            return
        }
        switch a {
        case .left: slot = max(0, slot - 1)
        case .right: slot = min(KeyBindings.slots - 1, slot + 1)
        case .activate: capturing = .key(c.id, slot)
        case .clear:
            var b = host.keyBindings
            b.bind(nil, to: c.id, slot: slot)
            host.keyBindings = b
        default: break
        }
    }

    private func padAction(_ a: Action) {
        guard let c = control(at: cursor) else {
            if a == .activate { if cursor == rowCount - 2 { host.padBindings = PadBindings() } else { go(.main, cursor: 7) } }
            return
        }
        switch a {
        case .activate: capturing = .pad(c.id)
        case .left, .clear:
            var b = host.padBindings
            b.bind(nil, to: c.id)
            host.padBindings = b
        default: break
        }
    }

    /// The next key down while a key cell waits. Escape cancels; a key that can't be bound keeps the capture and says so.
    public func captureKey(_ usage: UInt16) {
        guard case .key(let id, let slot)? = capturing else { return }
        if usage == 0x29 { capturing = nil; message = nil; return }
        guard usage != 0, !KeyBindings.reserved.contains(usage), !shellKeys.contains(usage) else {
            message = "That key can’t be used."
            return
        }
        var b = host.keyBindings
        b.bind(usage, to: id, slot: slot)
        host.keyBindings = b
        capturing = nil
        message = nil
    }

    /// The next controller button while a button cell waits.
    public func capturePad(_ button: PadButton) {
        guard case .pad(let id)? = capturing else { return }
        var b = host.padBindings
        b.bind(button, to: id)
        host.padBindings = b
        capturing = nil
        message = nil
    }

    // MARK: values

    private func onOff(_ v: Bool) -> String { v ? "On" : "Off" }

    /// The value shown right of a main row.
    func mainValue(_ row: Int) -> String? {
        switch row {
        case 0: onOff(host.fullScreen)
        case 1: host.correctAspect ? "4:3" : "Square Pixels"
        case 2: host.music == .generalMIDI ? "General MIDI" : host.music == .adlib ? "AdLib" : "Off"
        case 3: onOff(host.muted)
        case 4: Self.languageNames[host.language] ?? host.language
        case 5: onOff(host.readableText)
        default: nil
        }
    }

    func keyValue(_ id: String, slot: Int) -> String {
        if capturing == .key(id, slot) { return "..." }
        return host.keyBindings.key(id, slot: slot).map(host.keyName) ?? "-"
    }

    func padValue(_ id: String) -> String {
        if capturing == .pad(id) { return "..." }
        return host.padBindings.button(id).map(host.padLabel) ?? "-"
    }

    // MARK: drawing

    /// CP437 codes of the accented letters the captions' fonts have (the fonts are indexed by CP437, not Unicode).
    static let cp437: [Unicode.Scalar: Unicode.Scalar] = {
        let map: [(Character, UInt8)] = [("é", 0x82), ("ä", 0x84), ("ç", 0x87), ("ö", 0x94), ("ü", 0x81), ("Ä", 0x8E), ("Ö", 0x99), ("Ü", 0x9A),
                                         ("ß", 0xE1), ("à", 0x85), ("è", 0x8A), ("â", 0x83), ("ê", 0x88), ("ô", 0x93)]
        return Dictionary(uniqueKeysWithValues: map.map { ($0.0.unicodeScalars.first!, Unicode.Scalar($0.1)) })
    }()

    private static let plain: [Unicode.Scalar: Unicode.Scalar] = Dictionary(uniqueKeysWithValues: zip("éäçöüÄÖÜßàèâêô", "eacouAOUsaeaeo").map { ($0.unicodeScalars.first!, $1.unicodeScalars.first!) })

    /// The characters as the font indexes them: CP437 for the accents (the plain letter where the font has no accented ones, as SMALL.FNT),
    /// three dots for an ellipsis.
    static func fontScalars(_ text: String, _ font: CaptionFont) -> [Unicode.Scalar] {
        text.replacingOccurrences(of: "…", with: "...").unicodeScalars.map { s in
            guard let accented = cp437[s] else { return s }
            return font.glyph(accented) != nil ? accented : plain[s] ?? s
        }
    }

    static func width(_ text: String, _ font: CaptionFont) -> Int { fontScalars(text, font).reduce(0) { $0 + font.advance($1) } }

    static func fit(_ text: String, _ width: Int, _ font: CaptionFont) -> String {
        var t = text
        while !t.isEmpty && Self.width(t, font) > width { t.removeLast() }
        return t
    }

    private typealias Colour = (r: UInt8, g: UInt8, b: UInt8)

    /// The settings drawn over `rgba` (320x200, FrameRGBA's layout): the picture dimmed to a quarter, then the list.
    public func render(into rgba: inout [UInt8], font: CaptionFont) {
        let bright: Colour = (255, 255, 255), normal: Colour = (176, 184, 200), bar: Colour = (28, 48, 104), cell: Colour = (60, 92, 168)
        let w = Framebuffer.width, h = Framebuffer.height
        guard rgba.count == w * h * 4 else { return }
        for i in stride(from: 0, to: rgba.count, by: 4) { rgba[i] >>= 2; rgba[i + 1] >>= 2; rgba[i + 2] >>= 2 }
        func fill(_ x: Int, _ y: Int, _ width: Int, _ height: Int, _ c: Colour) {
            for yy in max(0, y)..<min(h, y + height) { for xx in max(0, x)..<min(w, x + width) {
                let o = (yy * w + xx) * 4
                rgba[o] = c.r; rgba[o + 1] = c.g; rgba[o + 2] = c.b
            } }
        }
        func text(_ s: String, x: Int, baseline: Int, _ c: Colour) {
            var pen = x
            for scalar in Self.fontScalars(s, font) {
                if let g = font.glyph(scalar) {
                    let left = pen - g.xOrigin, topY = baseline - g.baseline
                    for (ry, row) in g.rows.enumerated() { for (rx, p) in row.enumerated() where p != 0 {
                        let px = left + rx, py = topY + ry
                        guard px >= 0, px < w, py >= 0, py < h else { continue }
                        let o = (py * w + px) * 4
                        rgba[o] = c.r; rgba[o + 1] = c.g; rgba[o + 2] = c.b
                    } }
                }
                pen += font.advance(scalar)
            }
        }
        func right(_ s: String, edge: Int, baseline: Int, _ c: Colour) { text(s, x: edge - Self.width(s, font), baseline: baseline, c) }

        let lh = font.height + 3
        let titleBase = font.height + 4, rowsTop = titleBase + 8
        capacity = max(1, (h - 2 * lh - 2 - rowsTop) / lh)
        ensureVisible()
        text(["Settings", "Keyboard Controls", "Controller"][page == .main ? 0 : page == .keys ? 1 : 2], x: 12, baseline: titleBase, bright)
        let last = min(rowCount, top + capacity)
        for row in top..<last {
            let y = rowsTop + (row - top) * lh, base = y + font.height - 2, selected = row == cursor
            if selected { fill(8, y, w - 16, lh, bar) }
            let c = selected ? bright : normal
            switch page {
            case .main:
                text(Self.mainRows[row], x: 24, baseline: base, c)
                if let v = mainValue(row) { right(v, edge: w - 24, baseline: base, c) }
            case .keys:
                guard let ctl = control(at: row) else { text(row == rowCount - 2 ? "Reset to Defaults" : "Back", x: 12, baseline: base, c); break }
                text(Self.fit(ctl.title, 160, font), x: 12, baseline: base, c)
                for s in 0..<KeyBindings.slots {
                    let edge = 240 + s * 70
                    if selected && s == slot { fill(edge - 66, y, 68, lh, cell) }
                    right(Self.fit(keyValue(ctl.id, slot: s), 64, font), edge: edge, baseline: base, selected && s == slot ? bright : c)
                }
            case .pad:
                guard let ctl = control(at: row) else { text(row == rowCount - 2 ? "Reset to Defaults" : "Back", x: 12, baseline: base, c); break }
                text(Self.fit(ctl.title, 190, font), x: 12, baseline: base, c)
                right(Self.fit(padValue(ctl.id), 100, font), edge: w - 12, baseline: base, c)
            }
        }
        let promptBase = h - lh - 2 + font.height - 2
        if let c = capturing {
            switch c {
            case .key(let id, let s): text("Press a key for \(KeyBindings.control(id)?.title ?? id)\(KeyBindings.slots > 1 ? " (\(s + 1))" : "") - Escape cancels", x: 12, baseline: promptBase, bright)
            case .pad(let id): text("Press a button for \(KeyBindings.control(id)?.title ?? id) - D-pad cancels", x: 12, baseline: promptBase, bright)
            }
        } else if let message { text(message, x: 12, baseline: promptBase, bright) }
        else if page == .main, cursor == 2, let note = host.musicNote { text(Self.fit(note, w - 24, font), x: 12, baseline: promptBase, normal) }
        text(lastInputWasPad ? "D-pad: choose   A: select   B: back" : "Arrows: choose and change   Enter: select   Esc: back", x: 12, baseline: h - 3, normal)
    }
}
