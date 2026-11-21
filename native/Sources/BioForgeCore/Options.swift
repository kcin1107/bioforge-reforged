// The options dialog (options.py): its screens and art come from MONITORS/OPTS.CAM (decompiled in 1280.c), separate from the
// script-driven MON_* UI. MON_CODE opens it (flag priority below); the World performs the actions it returns
// (difficulty:N, audio:S,M, gamma:G, return, cancel, exit, save:N, load:N, unsupported:new). The audio and gamma panels change the
// persisted Settings and apply every change at once through the callbacks the World passes in (FUN_1100_0dc2 / FUN_1100_0e6f);
// DETAIL does nothing (the original callback has no DETX branch).
// Button text comes from SCRIPT/PIMM.SCP (`< NAME = "ENGLISH/FFRENCH/GGERMAN" >`, FUN_1280_0212) and, as in the original monitor engine,
// is drawn only in the label element named with the button's first three letters + "L"; buttons without one show no text.
import Foundation

public final class Options {
    public static let defaultFlag = 1, mustReload = 2, load = 4, save = 8, credits = 16, audio = 32
    public static let level = 64, test = 128, new = 256, difficulty = 512, exit = 1024
    /// Added by World.openOptions when saving is refused: the main panel's Save button is disabled (FUN_1280_176b).
    public static let noSave = 0x800

    let monitor: MonitorScreen
    /// View > Readable Text (MonitorScreen.readableText).
    public var readableText: Bool { get { monitor.readableText } set { monitor.readableText = newValue } }
    private let creditsFont: CaptionFont?                 // DATA/1.FNT, the credits roll's font
    /// The CREDITS stream as display lines (credits_lines in options.py).
    let creditsLines: [(text: [UInt8], heading: Bool)]
    /// The roll (re/out/credits_live/SPEC.md, FUN_1280_221e / 1278:1c08): s = 12 * T - o pixels scrolled, CREDITSSTATE [9ce5] (0 none, 1
    /// scrolling, 2 done) and the key lockout [4e3b] = 0x29a that the first update clears.
    public internal(set) var creditsPos = 0
    public internal(set) var creditsState = 0
    public internal(set) var creditsLockout = false
    /// [a36c]: the dialog opened with _OPTS_CREDITS or has shown the page (FUN_1100_0ae6 acts on its close).
    public internal(set) var creditsMode = false
    /// The world was resumed for the page (FUN_1100_0716): the dialog does not pause.
    public internal(set) var resumed = false
    /// The World's 221e effects (0716 resume, 0740 song), called when the page is set up.
    var onCreditsPage: (() -> Void)?
    static let creditsStops = [60, 60, 180, 180, 180], creditsCentre = 160, creditsPitch = 12
    static let creditsColours = [249, 200], creditsShadow = 0
    private let strings: [String: String]                 // PIMM.SCP options text, English part
    private let slotUsed: (Int) -> Bool                   // a save exists in the slot (the save screen's DAT_a86d == 5 when not)
    /// The confirm prompt of each mode (FUN_1280_214c: the string at a41c + mode * 0x1e), as PIMM.SCP keys.
    private static let prompts = ["QEXITTODOSSTR", "QRETURNTOGAMESTR", "QLOADGAMESTR", "QNEWGAMESTR", "QSAVEGAMESTR", "QSAVEOVERSTR"]
    public private(set) var flags = 0
    public internal(set) var screen: String?
    public internal(set) var closed = true
    public private(set) var lastAction: String?
    public private(set) var hovered: String?
    public private(set) var difficultyChoice: Int
    public let settings: Settings
    /// The language the texts were read in; a dialog is built again when the setting differs.
    let language: String
    public private(set) var sfx: Int, music: Int          // working levels (d712 / d714)
    public private(set) var gamma: Int                    // working gamma (a364)
    private var saved: (sfx: Int, music: Int)             // the levels when the audio panel opened (d70e / d710)
    private var subtitles: Bool                           // SBTX button state > 2
    private let applyAudio: (Int, Int) -> Void
    private let applyGamma: (Int) -> Void
    private var controls: [(asset: String, semantic: String)] = []
    private var slot = 1
    private var confirmAction = "exit"
    private var pressedControl: String?                   // the control a mouse down went to (the pointer's press action)
    private var queued: [String] = []                     // actions a delayed mouse release produced, for update()'s caller

    public init(game: GameFolder, difficulty: Int = 1, settings: Settings = Settings(),
                applyAudio: @escaping (Int, Int) -> Void = { _, _ in }, applyGamma: @escaping (Int) -> Void = { _ in },
                slotUsed: @escaping (Int) -> Bool = { _ in false }) throws {
        monitor = try MonitorScreen(name: "OPTS", game: game)
        monitor.language = settings.language
        monitor.translucentKinds = ["X"]                         // the buttons blend with the screen (FUN_1270_185b)
        language = settings.language
        strings = try Self.pimmStrings(game, language)
        self.slotUsed = slotUsed
        difficultyChoice = max(0, min(2, difficulty))
        self.settings = settings; self.applyAudio = applyAudio; self.applyGamma = applyGamma
        sfx = settings.sound; music = settings.music; saved = (settings.sound, settings.music); subtitles = settings.subtitles; gamma = settings.gamma
        creditsFont = try? CaptionFont(game.read("DATA/1.FNT"))
        creditsLines = Self.creditsLines((monitor.rawText("CREDITS") ?? "").unicodeScalars.map { UInt8(truncatingIfNeeded: $0.value) })
        monitor.pressAction = { [unowned self] in pressControl() }
        monitor.buttonsProvider = { [unowned self] in controls.map(\.asset).filter { monitor.elementActive($0) } }     // the keys (MonitorScreen.keyEvent) move over its X controls
        monitor.hoverOverride = { [unowned self] in hover() }                                          // FUN_1250_19bc for the dialog
        monitor.releaseAction = { [unowned self] in releaseControl() }
    }

    /// The text in `language` of every `< KEY = "ENGLISH/FFRENCH/GGERMAN" >` define in SCRIPT/PIMM.SCP, trimmed.
    private static func pimmStrings(_ game: GameFolder, _ language: String) throws -> [String: String] {
        let source = String(String.UnicodeScalarView(try game.read("SCRIPT/PIMM.SCP").map { Unicode.Scalar($0) }))
        let pattern = try NSRegularExpression(pattern: #"<\s*(\w+)\s*=\s*"([^"]*)""#)
        var out: [String: String] = [:]
        for m in pattern.matches(in: source, range: NSRange(source.startIndex..., in: source)) {
            guard let key = Range(m.range(at: 1), in: source), let value = Range(m.range(at: 2), in: source) else { continue }
            out[String(source[key])] = Presentation.captionText(String(source[value]), language: language).trimmingCharacters(in: .whitespaces)
        }
        return out
    }

    /// State of a panel button (tests): 1 normal ... 5 disabled.
    func buttonState(_ name: String) -> Int? { monitor.buttonState(name) }

    /// Text, activity and frame of an element (tests); nil / false for an unknown element.
    func elementText(_ name: String) -> String? { monitor.elementText(name) }
    func elementActive(_ name: String) -> Bool { monitor.elementActive(name) }
    func elementFrame(_ name: String) -> Int? { monitor.elementFrame(name) }
    func setLabelText(_ name: String, _ text: String) { monitor.setElementText(name, text) }

    private func clear() { monitor.hideAll(); monitor.setFrame("FRMA", 1) }
    private func frames(_ names: String...) { for n in names { monitor.setFrame(n, 1) } }
    /// The screen is built: FUN_1258_0512 runs FUN_1250_19bc after each selectable button it defines (except a state-2 one), so the control
    /// under the pointer is highlighted at once.
    private func controlsFor(_ pairs: (String, String)...) {
        controls = pairs.map { (asset: $0.0, semantic: $0.1) }
        highlight()
    }

    private func main() {
        clear()
        // Only the buttons with a label element show text: here CRDL and GMAL. OPTS.CAM has no DETX.
        button("EXTX", 2, "EXITSTR")                                                          // FUN_1280_176b: EXTX state 2
        for (name, key) in [("CRDX", "CREDITSSTR"), ("LODX", "LOADSTR"), ("AUDX", "AUDIOSTR"), ("GMAX", "GAMMACORRECTIONSTR")] { button(name, 1, key) }
        button("SAVX", flags & (Self.mustReload | Self.noSave) != 0 ? 5 : 1, "SAVESTR")     // FUN_1280_176b: SAVX state 5 (disabled)
        button("RETX", flags & Self.mustReload != 0 ? 5 : 1, "GAMESTR")                      // and RETX for MUST_RELOAD (seen live after a death)
        controlsFor(("EXTX", "EXIT"), ("CRDX", "CREDITS"), ("LODX", "LOAD"), ("SAVX", "SAVE"), ("AUDX", "AUDIO"),
                    ("GMAX", "GAMMA"), ("RETX", "RETURN"))
        screen = "main"
    }

    private func difficultyScreen() {
        clear()
        for (name, key) in [("EZYX", "LEVELEASYSTR"), ("MEDX", "LEVELMEDSTR"), ("HRDX", "LEVELHARDSTR")] { button(name, 1, key) }
        controlsFor(("EZYX", "EASY"), ("MEDX", "MEDIUM"), ("HRDX", "HARD"))
        screen = "difficulty"
    }

    /// A panel button in `state` (1 normal, 2 default, 3 selected). `key` is a PIMM.SCP string: FUN_1258_0512 shows it only in the
    /// button's label element (first 3 letters + "L"), if there is one. A default (state 2) starts normal once the mouse has moved
    /// ([9dca] & 2); before that it takes the focus and the pointer jumps to its centre (pointer +0x1c = FUN_1270_08ef), which puts the
    /// mouse there too (FUN_1250_1a78). The port redraws a whole panel for a step the original makes on one button, and a redraw leaves
    /// the default alone (normal, the pointer stays).
    private func button(_ name: String, _ state: Int = 1, _ key: String? = nil) {
        let state = state == 2 && (monitor.mouseMoved || redraw) ? 1 : state
        monitor.setButtonState(name, state)
        monitor.setFrame(name, state)                            // the drawn frame is the state: live, EXTX shows frame 2 and a disabled button frame 5
        monitor.defineButton(name, key.flatMap { strings[$0] } ?? "", state: state + 1, mode: Self.toggles.contains(name) ? 1 : 0)
        if state == 2 {
            monitor.focus = name
            let c = monitor.centre(name)
            if monitor.setPointerPos(x: c.x, y: c.y) { monitor.mouseWarp = monitor.pointerPosition }
        }
    }

    /// FUN_1258_0512 mode 1 (+0x40; 1280.c:296, 299, 1280_callbacks.c MSCX): the highlight keeps their selection.
    private static let toggles: Set<String> = ["SFXX", "MSCX", "SBTX"]
    /// True while the audio / gamma panel is redrawn for a step (button).
    private var redraw = false

    /// FUN_1250_19bc for the dialog: the control under the pointer is highlighted and takes the focus.
    private func hover() {
        hovered = closed ? nil : control(at: monitor.pointerPosition)
        highlight()
    }

    /// Button vtable +0x18 (FUN_1260_06e2): a control in state 1...4. Its state is the frame it draws.
    private func selectable(_ name: String) -> Bool {
        guard monitor.elementActive(name), let f = monitor.elementFrame(name) else { return false }
        return f != 0 && f != 5
    }

    /// Button vtable +0x28 (FUN_1278_0844): back to normal (1); a toggle (mode 1) keeps its selection (4 -> 3, 3 stays).
    private func unhighlight(_ name: String) {
        let toggle = Self.toggles.contains(name), f = monitor.elementFrame(name)
        if f == 4 { monitor.setControlState(name, toggle ? 3 : 1) }
        else if f == 2 || !toggle { monitor.setControlState(name, 1) }
    }

    /// FUN_1250_19bc: FUN_1250_158e takes the highlight off the focus; with a selectable control under the pointer (FUN_1250_1889),
    /// FUN_1250_166b takes it off every selectable control and puts it on that one (vtable +0x24, FUN_1278_0803: 2, or 4 for a selected
    /// toggle), which becomes the focus. Off every control nothing is highlighted. A brighter bar (frame 2) and brighter label text.
    private func highlight() {
        guard !closed else { return }
        let selectable = controls.map(\.asset).filter { self.selectable($0) }
        guard let first = selectable.first else { return }                     // FUN_1250_0449: no selectable button, nothing to do
        if !selectable.contains(monitor.focus ?? "") { monitor.focus = first }  // 0449 moves a stale focus to the first selectable button
        unhighlight(monitor.focus ?? first)
        let p = monitor.pointerPosition
        guard let under = selectable.first(where: { monitor.hitsActive($0, p.x, p.y) }) else { return }
        for name in selectable { unhighlight(name) }
        let f = monitor.elementFrame(under)
        monitor.setControlState(under, Self.toggles.contains(under) && (f == 3 || f == 4) ? 4 : 2)
        monitor.focus = under
    }

    /// FUN_1280_1cc5: both levels come from the persisted settings, which are also what Cancel restores.
    private func audioScreen() {
        sfx = settings.sound; music = settings.music; saved = (settings.sound, settings.music); subtitles = settings.subtitles
        audioDraw()
    }

    private func audioDraw(redraw: Bool = false) {
        self.redraw = redraw
        defer { self.redraw = false }
        clear()
        // SFXX / MSCX show state 1 at level 0 and 3 otherwise (FUN_1280_0803 / 0884 keep them in step with the levels)
        button("SFXX", sfx == 0 ? 1 : 3, "SFXSTR")
        button("SFPX"); button("SFMX")
        button("MSCX", music == 0 ? 1 : 3, "MUSICSTR")
        button("MSPX"); button("MSMX")
        button("SBTX", subtitles ? Self.subtitlesOn : Self.subtitlesOff)
        button("AOKX", 2, "OKSTR"); button("ACAX", 1, "CANCELSTR")
        monitor.setGauge("SFXQ", Self.gauge(sfx))
        monitor.setGauge("MSCQ", Self.gauge(music))
        controlsFor(("SFXX", "SFX"), ("MSCX", "MUSIC"), ("SBTX", "SUBTITLES"), ("SFPX", "SFX+"), ("SFMX", "SFX-"), ("MSPX", "MUSIC+"),
                    ("MSMX", "MUSIC-"), ("AOKX", "OK"), ("ACAX", "CANCEL"))
        screen = "audio"
    }

    private static let subtitlesOff = 1, subtitlesOn = 3

    /// Gauge frame for a level 0...100 (frame = value / 10 + 1). ASSUMPTION: the original draws the gauge with FUN_1258_0cab
    /// (value, 2, 10); this is the mapping the prototype already used for the audio gauges.
    private static func gauge(_ value: Int) -> Int { max(1, min(11, value / 10 + 1)) }

    /// FUN_1280_1ff1 (screen mode 0x47): the working value starts at the persisted gamma.
    private func gammaPanel() {
        gamma = settings.gamma
        gammaDraw()
    }

    private func gammaDraw(redraw: Bool = false) {
        self.redraw = redraw
        defer { self.redraw = false }
        clear()
        button("GMPX"); button("GMMX")
        monitor.setGauge("GMAQ", Self.gauge(gamma))
        button("AOKX", 2, "OKSTR"); button("ACAX", 1, "CANCELSTR")      // ASSUMPTION: FUN_1280_1ff1 is not decompiled; labelled as on the audio panel
        controlsFor(("GMPX", "GAMMA+"), ("GMMX", "GAMMA-"), ("AOKX", "OK"), ("ACAX", "CANCEL"))
        screen = "gamma"
    }

    /// Leaving a sub-screen (OK / Cancel on the audio or gamma panel, LCAX, NOOX; 1280_callbacks.c): a366 = 0, then the main panel if the
    /// dialog was opened with _OPTS_DEFAULT, else the callback turns the press into Escape (LAB_1280_0e57). With MUST_RELOAD that Escape
    /// brings up the exit prompt (FUN_1280_214c(0)) instead of closing, so a dead Lex never gets back to the game without a load.
    private func leave(_ action: String) -> String {
        if flags & Self.defaultFlag != 0 { main() }
        else if flags & Self.mustReload != 0 { confirm(0) }
        else { return close(action) }
        lastAction = action
        return action
    }

    /// FUN_1248_0a5b's stream model: `\n` ends a line; `\r` also swallows the next byte; 2 marks a heading and is not stored; tab and 0x20...0xe1 are
    /// stored; any other byte (the final NUL) ends the line. After a line ends, if the next byte is a newline one more is swallowed (1248:0e09
    /// ignore(2, '\n')), so k newlines after text make ceil(k / 2) line steps.
    static func creditsLines(_ raw: [UInt8]) -> [(text: [UInt8], heading: Bool)] {
        var out: [(text: [UInt8], heading: Bool)] = []
        var i = 0
        let n = raw.count
        while i < n {
            var buf: [UInt8] = [], head = false
            while i < n {
                let c = raw[i]; i += 1
                if c == 10 { break }
                if c == 13 { if i < n { i += 1 }; break }
                if c == 2 { head = true; continue }
                if c == 9 || (0x20...0xe1).contains(c) { buf.append(c); continue }
                break
            }
            if i < n, raw[i] == 10 || raw[i] == 13 {
                i += 1
                if raw[i - 1] == 13, i < n, raw[i] == 10 { i += 1 }
            }
            out.append((buf, head))
        }
        return out
    }

    /// The scroll position the roll stops at: 12 * (lines - 2 - 18 + 1) = 2784 for the 251 lines of CREDITS.
    static func creditsDone(_ count: Int) -> Int { creditsPitch * (count - 2 - 18 + 1) }

    /// FUN_1280_221e: the roll starts at the top with the key lockout set. The page is only text over the live scene (the World draws it).
    private func creditsScreen() {
        monitor.hideAll()
        creditsMode = true
        creditsPos = 0; creditsState = 0; creditsLockout = true
        controls = []
        screen = "credits"
        onCreditsPage?()                                  // unless _forcing_reload: 0716 then 0740. Nothing pauses again when the page is left
    }

    /// 1278:1c08, once per dialog frame (one tick): at the end position state 2 and no scroll, else state 1, the lockout cleared and the picture
    /// one pixel further.
    private func creditsUpdate() {
        if creditsPos >= Self.creditsDone(creditsLines.count) { creditsState = 2 }
        else { creditsState = 1; creditsLockout = false; creditsPos += 1 }
    }

    /// The roll at scroll position `pos` (default: now) drawn into `fb`'s pixels (only the text and its shadow): lines from T = pos / 12 at
    /// baselines 8 + o + 12k, o = -(pos % 12), until the baseline passes 208; each centred about x = 160 in font 1 (spacing 1), the shadow first.
    public func drawCredits(into fb: inout Framebuffer, at pos: Int? = nil) {
        guard let font = creditsFont else { return }
        let pos = pos ?? creditsPos
        func advance(_ c: UInt8, _ x: Int) -> Int {
            if c == 9 { return Self.creditsStops.first { x < $0 }.map { $0 - x } ?? 0 }
            let index = Int(c)
            return index >= 0x20 && index < font.glyphs.count ? font.glyphs[index].width : font.glyphs[0x41].width
        }
        var y = 8 - pos % Self.creditsPitch, i = pos / Self.creditsPitch
        while i < creditsLines.count {
            let (text, heading) = creditsLines[i]
            let width = (text + [10]).reduce(0) { $0 + advance($1, 0) + 1 } - 1      // measured with x fixed at the column start
            let start = max(0, Self.creditsCentre - max(0, width) / 2)
            for (shift, colour) in [(1, Self.creditsShadow), (0, Self.creditsColours[heading ? 1 : 0])] {
                var x = start + shift
                for c in text {
                    if c != 9 && c >= 0x20, Int(c) < font.glyphs.count {
                        let glyph = font.glyphs[Int(c)]
                        let left = x - glyph.xOrigin, top = y + shift - glyph.baseline
                        for (r, row) in glyph.rows.enumerated() where top + r >= 0 && top + r < Framebuffer.height {
                            for (k, v) in row.enumerated() where v != 0 && left + k >= 0 && left + k < Framebuffer.width {
                                fb.pixels[(top + r) * Framebuffer.width + left + k] = UInt8(colour)
                            }
                        }
                    }
                    x += advance(c, x) + 1
                }
            }
            y += Self.creditsPitch
            i += 1
            if y > 208 { break }
        }
    }

    private func slots(_ mode: String) {
        clear()
        frames("LLFX", "LRTX")
        button("LOKX", 1, mode == "load" ? "LOADSTR" : "SAVESTR"); button("LCAX", 1, "CANCELSTR")
        if mode == "load" { button("LNWX", 1, "NEWSTR") }
        monitor.setFrame("SELG", slot)
        for n in 1...9 { monitor.setFrame("SE\(n)X", 1) }
        controls = (1...9).map { (asset: "SE\($0)X", semantic: "SLOT\($0)") } + [(asset: "LLFX", semantic: "LEFT"), (asset: "LRTX", semantic: "RIGHT"),
                                                                                  (asset: "LOKX", semantic: "OK"), (asset: "LCAX", semantic: "CANCEL")]
        if mode == "load" { controls.append((asset: "LNWX", semantic: "NEW")) }
        screen = mode
    }

    /// FUN_1280_214c(mode): the yes / no box; QSTL shows the prompt `prompts[mode]` (FUN_1258_07cf), modes 2 and 5 also frame SELG 0xf.
    private func confirm(_ mode: Int = 0, _ action: String = "exit") {
        clear()
        confirmAction = action
        frames("QSTY")
        monitor.defineText("QSTL", strings[Self.prompts[mode]] ?? "")
        if mode == 2 || mode == 5 { monitor.setFrame("SELG", 0xf) }
        button("YESX", 2, "YESSTR"); button("NOOX", 1, "NOSTR")
        controlsFor(("YESX", "YES"), ("NOOX", "NO"))
        screen = "confirm"
    }

    /// Open the screen selected by the native MON_CODE flag priority.
    @discardableResult public func open(_ flags: Int) -> String? {
        self.flags = flags
        closed = false; lastAction = nil; hovered = nil
        creditsMode = flags & Self.credits != 0; resumed = false
        if flags & Self.defaultFlag != 0 { main() }
        else if flags & Self.load != 0 { slots("load") }
        else if flags & Self.save != 0 { slots("save") }
        else if flags & Self.credits != 0 { creditsScreen() }
        else if flags & Self.audio != 0 { audioScreen() }
        else if flags & (Self.level | Self.test | Self.new | Self.difficulty) != 0 { difficultyScreen() }
        else if flags & Self.exit != 0 { confirm(0) }
        else { main() }
        return lastAction
    }

    /// True while `key` passes Escape on as Cancel.
    private var escaping = false

    private func close(_ action: String) -> String { closed = true; lastAction = action; return action }

    /// Activate a control by asset or semantic name; -> the observable action, nil if nothing happened.
    @discardableResult public func activate(_ button: String) -> String? {
        var name = button.uppercased()
        if name.hasSuffix("_BUTTON") { name.removeLast(7) }
        let aliases = ["EZYX": "EASY", "MEDX": "MEDIUM", "HRDX": "HARD", "AOKX": "OK", "ACAX": "CANCEL", "LCAX": "CANCEL",
                       "YESX": "YES", "NOOX": "NO", "SFPX": "SFX+", "SFMX": "SFX-", "MSPX": "MUSIC+", "MSMX": "MUSIC-", "CRDX": "CREDITS",
                       "AUDX": "AUDIO", "LODX": "LOAD", "SAVX": "SAVE", "GMAX": "GAMMA", "RETX": "RETURN", "EXTX": "EXIT", "DETX": "DETAIL",
                       "GMPX": "GAMMA+", "GMMX": "GAMMA-", "SFXX": "SFX", "MSCX": "MUSIC", "SBTX": "SUBTITLES",
                       "LLFX": "LEFT", "LRTX": "RIGHT", "LOKX": "OK", "LNWX": "NEW"]
        name = aliases[name] ?? name
        let chars = Array(name)
        if chars.count == 4, name.hasPrefix("SE"), chars[2].isASCII, chars[2].isNumber, chars[3] == "X" { name = "SLOT" + String(chars[2]) }
        lastAction = nil
        if closed { return nil }
        switch screen {
        case "main":
            switch name {
            case "CREDITS": creditsScreen()
            case "AUDIO": audioScreen()
            case "EXIT": confirm(0)
            case "RETURN": if flags & Self.mustReload == 0 { return close("return") }    // RETX disabled: a dead player cannot go back
            case "LOAD": slots("load")
            case "SAVE": if flags & (Self.mustReload | Self.noSave) == 0 { slots("save") }
            case "GAMMA": gammaPanel()
            default: break                                       // DETAIL: no DETX branch in the original callback
            }
            return lastAction
        case "load", "save":
            if name.hasPrefix("SLOT"), let number = Int(name.dropFirst(4)), name.dropFirst(4).allSatisfy(\.isASCII) {
                if (1...9).contains(number) { slot = number }
            } else if name == "LEFT" { slot = max(1, slot - 1) }
            else if name == "RIGHT" { slot = min(9, slot + 1) }
            else if name == "OK" { let mode = screen!; confirm(mode == "load" ? 2 : slotUsed(slot) ? 5 : 4, mode); return nil }
            else if name == "NEW" && screen == "load" { confirm(3, "new"); return nil }
            else if name == "CANCEL" || name == "ESCAPE" { return escaping ? close("cancel") : leave("cancel") }
            monitor.setFrame("SELG", slot)
            return nil
        case "difficulty":
            guard let choice = ["EASY": 0, "MEDIUM": 1, "HARD": 2][name] else { return nil }
            difficultyChoice = choice
            return close("difficulty:\(choice)")
        case "audio":
            switch name {
            case "SFX-": sfx = max(0, sfx - 10)
            case "SFX+": sfx = min(100, sfx + 10)
            case "SFX": sfx = sfx == 0 ? 100 : 0                 // SFXX toggles 0 <-> 100
            case "MUSIC-": music = max(0, music - 10)
            case "MUSIC+": music = min(100, music + 10)
            case "MUSIC": music = music == 0 ? 100 : 0           // MSCX toggles 0 <-> 100
            case "SUBTITLES": subtitles.toggle(); audioDraw(redraw: true); return nil
            case "OK":
                settings.subtitles = subtitles
                settings.sound = sfx; settings.music = music; saved = (sfx, music)
                settings.persist()
                applyAudio(sfx, music)
                return leave("audio:\(sfx),\(music)")
            case "CANCEL":
                (sfx, music) = saved
                applyAudio(sfx, music)
                return leave("cancel")
            default: return nil
            }
            if sfx == 0 && name.hasPrefix("SFX") { subtitles = true }       // FUN_1280_0803(1) forces SBTX to state 3 when the effects go silent
            applyAudio(sfx, music)
            audioDraw(redraw: true)
            lastAction = "audio:\(sfx),\(music)"
            return lastAction
        case "gamma":
            switch name {
            case "GAMMA-": if gamma > 9 { gamma -= 10 }
            case "GAMMA+": if gamma < 91 { gamma += 10 }
            case "OK":
                settings.gamma = gamma
                settings.persist()
                applyGamma(gamma)
                return leave("gamma:\(gamma)")
            case "CANCEL":
                gamma = settings.gamma
                applyGamma(gamma)
                return leave("cancel")
            default: return nil
            }
            applyGamma(gamma)
            gammaDraw(redraw: true)
            lastAction = "gamma:\(gamma)"
            return lastAction
        case "credits":
            if creditsLockout { return nil }
            return ["RETURN", "CANCEL", "ESCAPE"].contains(name) ? (escaping ? close("return") : leave("return")) : nil
        case "confirm":
            if name == "YES" {
                if confirmAction == "exit" { return close("exit") }
                if confirmAction == "load" || confirmAction == "save" { return close("\(confirmAction):\(slot)") }
                return close("unsupported:" + confirmAction)
            }
            if ["NO", "CANCEL", "ESCAPE"].contains(name) {
                if confirmAction == "load" || confirmAction == "save" { slots(confirmAction); return nil }
                return escaping ? close("cancel") : leave("cancel")
            }
            return nil
        default: return nil
        }
    }

    /// ESCAPE closes (or backs out of) the screen.
    @discardableResult public func key(_ name: String) -> String? {
        guard monitor.inputEnabled else { return nil }          // the dialog is the current monitor: FUN_1250_0cf9 drops keys while the pointer presses
        let name = name.uppercased()
        if screen == "credits" && creditsLockout { return nil }    // [4e3b] = 0x29a (FUN_1100_0769 acts only at 0)
        if name == "ESCAPE" && flags & Self.mustReload != 0 {
            // Escape with MUST_RELOAD (1280_callbacks.c, the end of the key path): the exit prompt, or from that prompt (a366 0x51) the main panel.
            if screen == "confirm" { main() } else { confirm(0) }
            return nil
        }
        if name == "ESCAPE" {
            // Escape otherwise goes to the monitor's own handler (FUN_1250_0cf9), which closes the dialog: not back to the main panel.
            escaping = true
            defer { escaping = false }
            return activate(screen != "main" ? "CANCEL" : "RETURN")
        }
        return nil
    }

    /// The right mouse button: the dialog's event handler hands it to the monitor's (FUN_1250_0cf9), which presses "ESCAPE" as for the key, so the dialog
    /// closes (or backs out) through its Escape path without the MUST_RELOAD special case, which tests the key byte 0x1b (1280_callbacks.c).
    @discardableResult public func rightClick() -> String? {
        guard !closed, monitor.inputEnabled else { return nil }
        escaping = true
        defer { escaping = false }
        return activate(screen != "main" ? "CANCEL" : "RETURN")
    }

    private func control(at p: (x: Int, y: Int)) -> String? {
        controls.reversed().first { monitor.hitsActive($0.asset, p.x, p.y) }?.asset
    }

    /// Move the pointer (it ignores the move while it animates); -> the active original X-control under authored screen coordinates.
    @discardableResult public func pointerMove(x: Int, y: Int) -> String? {
        guard monitor.inputEnabled else { return hovered }
        monitor.mouseMoved = true                                // FUN_1250_1a21: [9dca] |= 2, then the move and FUN_1250_19bc
        if monitor.setPointerPos(x: x, y: y) { hover() }
        return hovered
    }

    /// Hit-test then activate an original X-control at authored coordinates (immediate; the app uses mouseDown / mouseUp).
    @discardableResult public func click(x: Int, y: Int) -> String? {
        guard let asset = pointerMove(x: x, y: y), let control = controls.first(where: { $0.asset == asset }) else { return nil }
        return activate(control.semantic)
    }

    /// The mouse button went down: through the pointer's press animation (MonitorScreen.mouseDown).
    @discardableResult public func mouseDown() -> Bool { monitor.mouseDown() }

    /// Where the release put the mouse (MonitorScreen.mouseWarp), once.
    func takeMouseWarp() -> (x: Int, y: Int)? { defer { monitor.mouseWarp = nil }; return monitor.mouseWarp }

    /// The mouse button went up: the control pressed is activated, if the pointer is still over it, when the pointer releases.
    public func mouseUp() { monitor.mouseUp() }

    /// The pointer's per-tick update, also while the dialog pauses the game. -> the actions its release activated since the last call.
    public func update() -> [String] {
        monitor.update()
        if screen == "credits" && !closed { creditsUpdate() }
        defer { queued = [] }
        return queued
    }

    /// The pointer's press action: remember the control under it.
    private func pressControl() -> Bool {
        pressedControl = closed ? nil : control(at: monitor.pointerPosition)
        return pressedControl != nil
    }

    /// The pointer's release action: today's click semantics, activate the pressed control only if the pointer is still over it.
    private func releaseControl() -> Bool {
        let pressed = pressedControl
        pressedControl = nil
        guard let pressed, !closed, control(at: monitor.pointerPosition) == pressed,
              let semantic = controls.first(where: { $0.asset == pressed })?.semantic, let action = activate(semantic) else { return false }
        queued.append(action)
        return true
    }

    /// The 320x200 frame in the OPTS palette.
    /// OPTS.CAM's background is fully transparent: the dialog sits on what the screen shows (`underlay`, MonitorScreen.render).
    public func render(into fb: inout Framebuffer, underlay: Framebuffer? = nil) { monitor.render(into: &fb, underlay: underlay) }

    /// The same at High-Resolution Art's scale (MonitorScreen.render(into:pack:)).
    public func render(into hi: inout HiResFrame, pack: HiResPack, underlay: Framebuffer? = nil, underlayHi: HiResFrame? = nil) {
        monitor.render(into: &hi, pack: pack, underlay: underlay, underlayHi: underlayHi)
    }
}
