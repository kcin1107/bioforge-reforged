// Script-driven monitor screens (.CAM art plus MON_* state).  This intentionally implements
// the small common subset used by PIMM.  Lists and inventory use TEXT.FLX records.
import Foundation

public final class MonitorScreen {
    private enum State: Int { case invisible = 0, normal, highlight, selected, selectedHighlight, disabled }

    private final class Element {
        let name: String
        let frames: [CAMFrame]
        let kind: Character
        var active = false
        var state = State.normal
        var frame = 0
        var gauge = false
        var mode = 0
        var text = ""
        var raw: String?                         // the unfiltered define text, to filter again when the language changes
        var sourceName: String?                  // the TEXT.FLX record of a list
        var source: [(key: String, text: String)] = []
        var entries: [(key: String, text: String)] = []
        var entryTimes: [Int?] = []
        var items: [String] = []
        var scale: [Int: Int] = [:]
        var selected = 0
        var top = 0
        var selectable = false
        /// +0x42: the letter key that clicks a button. FUN_1278_0894 (button vtable slot 0x20) stores tolower(text[0]), but no script statement reaches it
        /// with text (MON_DEFINEBUTTON 10d0:540a -> 1258:08b4 -> 1270:0ffa sets a label), so it stays nil.
        var shortcut: Character?
        let x: Int, y: Int, width: Int, height: Int
        let style: ([UInt8], Int)?

        init(name: String, frames: [CAMFrame]) {
            self.name = name.uppercased()
            self.frames = frames
            kind = self.name.count > 3 ? Character(String(self.name.dropFirst(3).prefix(1))) : "?"
            let real = frames.dropFirst().filter { $0.width > 1 }
            if let first = real.first {
                x = -first.hotX; y = -first.hotY
                width = real.map(\.width).max() ?? 0
                height = real.map(\.height).max() ?? 0
                if (kind == "L" || kind == "T"), first.pixels.count > 6 { style = (Array(first.pixels.prefix(5)), Int(first.pixels[5])) }
                else { style = nil }
            } else {
                x = 0; y = 0; width = 0; height = 0; style = nil
            }
        }

        func hit(_ px: Int, _ py: Int) -> Bool {
            frames.dropFirst().contains { frame in
                frame.width > 1 && px >= -frame.hotX && px < -frame.hotX + frame.width && py >= -frame.hotY && py < -frame.hotY + frame.height
            }
        }
    }

    public let name: String
    private let palette: [UInt8]
    private let background: CAMFrame?
    private var elements: [String: Element] = [:]
    private var order: [String] = []
    private let game: GameFolder
    private var fonts: [Int: CaptionFont] = [:]
    /// The pointer CAM (monitor.py pointer_frames): MONITORS/POINTER.CAM's HAND until MON_SETPTR picks a per-form hand (pcayhand ...).
    private var pointerFrames: [CAMFrame] = []
    private var pointerEntry = "", pointerCAM = "POINTER"
    private var pointer = (x: 160, y: 100)
    /// The pointer's press animation (FUN_1270_01ec / 0263 / 02ef, monitor.py Monitor.update): frame +10, state +0x30 (0 idle, 1 pressing,
    /// 2 holding, -1 releasing), start +0x43, interval +0x3f, releasePending +0x49, and its own 60 Hz clock: the port has no never-paused
    /// 60 Hz count (the show clock only runs while a flic plays and the options dialog stops the world), so `update()` advances it by
    /// `clockPerTick` once per tick (INFERRED equal to [8334] for the pointer's use).
    private(set) var pointerFrame = 1, pointerState = 0
    private var pointerStart = 0, pointerInterval = 0, pointerClock = 0
    private var releasePending = false
    static let clockPerTick = 2
    /// FUN_1250_12f6 / 13f1: what the pointer's press and release do; the options dialog replaces them.
    var pressAction: (() -> Bool)?
    var releaseAction: (() -> Bool)?
    /// SET_PTR_PRESS_TIME: press / hold / release in 60 Hz ticks (VARS.DEF _PTR_*_TIME).
    public var pointerPressTime = (press: 14, hold: 5, release: 14)
    /// SET_PTR_MOVEMENT: P+0x73 (dead data) and P+0x5f (rewritten to 2 at each glide start); stored only.
    public var pointerMovement = (maxPixelsPerSecond: 0x140, acceleration: 2)
    /// VARS.DEF _PTR_X_HOT / _PTR_Y_HOT, read by the pointer object (FUN_1270_0000): a pointer frame sits at its CAM hotspot in a 320x200
    /// canvas (the hand at about 109,11) and this canvas point, the fingertip, is the pointer position. See monitor.py PTR_HOT.
    static let pointerHot = (x: 122, y: 13)
    /// _ptr_left / right / top / bottom_margin (FUN_1270_0151 clamps to them): "hand ptrs do not reach to top of screen".
    static let pointerMargins = (left: 0, right: 319, top: 14, bottom: 199)
    /// +0x120, set by FUN_1250_0415 (MON_ENABLEINPUT; the pointer clears it when a press starts and sets it on the release): while it is
    /// off the monitor's event handler (FUN_1250_0cf9) drops mouse moves, mouse downs and keys; only the mouse up (FUN_1250_0c4c) gets through.
    private(set) var inputEnabled = true
    /// Turning input on puts the DOS mouse on the pointer (INT 33h AX=4, FUN_11d8_0e91); the app moves the Mac mouse there.
    var mouseWarp: (x: Int, y: Int)?
    private var hovered: String?
    /// The pointer's glide (FUN_1270_0536 start, 064f step; monitor.py Monitor.glide): start / target / delta / rounding / distance / half /
    /// travelled / speed / acceleration / phase.
    private struct Glide {
        var start: (x: Int, y: Int), target: (x: Int, y: Int), delta: (x: Int, y: Int), rounding: (x: Int, y: Int)
        var dist: Int, half: Int, t = 0, s = 0, a = 2, p = 2
    }
    private var glide: Glide?
    /// DAT_9fea: set by the update while the pointer is off its target, cleared by the next one after the arrival.
    private(set) var gliding = false
    /// FUN_1270_0891: max(1, [83a4] >> 7), [83a4] the 8.8 frame time (512 at 30 fps).
    static let glideDT = 4
    /// +0x112: the focused button (Tab moves it at once, the pointer crossing a button too).
    var focus: String?
    /// [9dca] & 2: set by a mouse move (FUN_1250_1a21), cleared by a key's glide (FUN_1250_15ef); the options dialog's defaults (Options.button).
    var mouseMoved = false
    /// +0x122: the button a letter shortcut is gliding to; the arrival clicks it (FUN_1250_1acf).
    private var shortcut: String?
    /// The keys the keyboard holds (PC scan codes, DAT_1290_7bbe) and +0x11e: the key whose release ends a press (0x1c for Return and Space, 1 for Escape).
    private var keysDown: Set<Int> = []
    private var heldKey = 0
    /// The options dialog lists its X controls as the focusable buttons and tracks the control under the pointer itself.
    var buttonsProvider: (() -> [String])?
    var hoverOverride: (() -> Void)?
    private var captured: String?
    private var pressed = ""
    private var released = ""
    private var repeatState = 0
    private var clickPending = false
    private var highlightPending = ""
    private var texts: [String: String]?
    /// "E", "G" or "F": the language segment of define texts and the text file (TEXT.FLX, GTEXT.FLX, FTEXT.FLX). Changing it filters what is
    /// shown again.
    public var language = "E" {
        didSet { if language != oldValue { texts = nil; relocalize() } }
    }
    private var resolveVariable: ((String) -> String?)?
    private var formatTime: ((Int) -> String)?
    private var currentTime: (() -> String)?
    private var viewport: (element: String, camera: String)?
    private var viewportFrame: ((String) -> Framebuffer?)?
    /// Element kinds drawn by FUN_1270_185b, translucent over the screen (the options dialog sets "X"; monitor.py translucent).
    var translucentKinds: Set<Character> = []
    private let greyRamp: [UInt8]
    /// View > Readable Text (off: the original look): +1 px letter spacing, a 1 px dark drop shadow and a brighter text colour,
    /// all in 320x200 game pixels so every scale draws the same picture.
    public var readableText = false
    private lazy var shadowColour = Self.darkestIndex(palette)
    private var brighterColours: [UInt8: UInt8] = [:]

    public init(name: String, game: GameFolder) throws {
        self.name = name.uppercased()
        self.game = game
        let cam = try CAMFile(data: game.read("MONITORS/\(self.name).CAM"))
        palette = cam.palette
        var foundBackground: CAMFrame?
        for entry in cam.images {
            let frames = try cam.frames(of: entry)
            if entry.name.caseInsensitiveCompare(self.name) == .orderedSame && foundBackground == nil {
                foundBackground = frames.first
            } else {
                let element = Element(name: entry.name, frames: frames)
                elements[element.name] = element
                order.append(element.name)
            }
        }
        background = foundBackground
        greyRamp = Self.greyRamp(palette)
        setPointer("")
    }

    /// MON_SETPTR: the pointer is the first entry of MONITORS/<name>.CAM ("" is POINTER.CAM); a missing file leaves no frames.
    func setPointer(_ name: String) {
        var stem = name.isEmpty ? "POINTER" : name.uppercased()
        if stem.hasSuffix(".CAM") { stem.removeLast(4) }
        pointerCAM = stem
        if let cam = try? CAMFile(data: game.read("MONITORS/\(stem).CAM")), let entry = cam.images.first {
            pointerFrames = (try? cam.frames(of: entry)) ?? []
            pointerEntry = entry.name.uppercased()
        } else {
            pointerFrames = []; pointerEntry = ""
        }
    }

    /// MON_SETPTRFRAME (0 hides the pointer) and MON_SETPTRPOS (set directly, as monitor.py does).
    func setPointerFrame(_ frame: Int) { pointerFrame = frame }
    func placePointer(x: Int, y: Int) { glide = nil; pointer = (x, y) }       // FUN_1270_08ef: the jump ends a glide

    /// FUN_1250_0415 (MON_ENABLEINPUT): store +0x120; turning input on with a mouse present moves the mouse to the pointer.
    func setInput(_ on: Bool) {
        inputEnabled = on
        if on { mouseWarp = pointer }
    }

    private func element(_ name: String) -> Element? { elements[name.uppercased()] }

    /// INDIVIDUALIZE re-keyed an item: every inventory entry that held the old key follows it.
    func renameItemKey(_ old: String, to new: String) {
        for e in elements.values { e.items = e.items.map { $0 == old ? new : $0 } }
    }
    private func label(for button: Element) -> Element? { elements[String(button.name.prefix(3)) + "L"] }
    private func selectableButton(at x: Int, _ y: Int) -> Element? {
        for name in order.reversed() {
            guard let e = elements[name], e.kind == "B", e.active, e.state != .disabled, e.hit(x, y) else { continue }
            return e
        }
        return nil
    }

    private func list(at x: Int, _ y: Int) -> Element? {
        for name in order.reversed() {
            guard let e = elements[name], e.kind == "T", e.active, e.selectable,
                  x >= e.x, x < e.x + e.width, y >= e.y, y < e.y + e.height else { continue }
            return e
        }
        return nil
    }

    public func hideAll() {
        for e in elements.values {
            e.active = false; e.frame = 0; e.text = ""; e.raw = nil; e.state = .normal
            e.entries = []; e.entryTimes = []; e.items = []; e.scale = [:]; e.selected = 0; e.top = 0; e.selectable = false
        }
        hovered = nil
        highlightPending = ""
        viewport = nil
    }

    /// Class Q (1270:09db): the draw 1270:0a64 blits frames 1..n together, a backdrop and then the bars.
    public func setGauge(_ name: String, _ frame: Int) {
        guard let e = element(name) else { return }
        e.active = true; e.frame = frame; e.gauge = true
    }

    public func setFrame(_ name: String, _ frame: Int) {
        guard let e = element(name) else { return }
        e.active = true; e.frame = frame
    }

    /// A panel button in `state` (1 normal, 2 highlight, 3 selected: the frame a button draws is its state).
    func setButtonState(_ name: String, _ state: Int) {
        guard let e = element(name) else { return }
        e.active = true; e.frame = 1; e.state = State(rawValue: state) ?? .normal
    }

    public func defineText(_ name: String, _ text: String, state: Int = 0) {
        guard let e = element(name) else { return }
        let rawState = state == 0 ? State.normal.rawValue : state - 1
        e.active = true; e.state = State(rawValue: max(0, min(5, rawState))) ?? .normal; e.text = localize(text); e.raw = text
    }

    public func defineButton(_ name: String, _ text: String, state: Int = 0, mode: Int = 0) {
        guard let e = element(name) else { return }
        let rawState = state == 0 ? State.normal.rawValue : state - 1
        e.active = true; e.state = State(rawValue: max(0, min(5, rawState))) ?? .normal; e.mode = mode
        if !text.isEmpty { e.text = localize(text); e.raw = text }                 // empty text = null = unchanged (ASSUMPTION)
        if let label = label(for: e) { label.active = e.state != .invisible; label.state = e.state; label.text = e.text }
    }

    private func textRecords(_ name: String) -> String? {
        if texts == nil {
            guard let flex = try? Flex(data: game.read("MONITORS/\(language == "E" ? "" : language)TEXT.FLX")) else { texts = [:]; return nil }
            texts = Dictionary(uniqueKeysWithValues: flex.entries.map { ($0.name.uppercased(), String(bytes: flex.bytes($0), encoding: .isoLatin1) ?? "") })
        }
        return texts?[name.uppercased()]
    }

    /// The language changed: filter the define texts again and take the list entries from the new text file (the n-th entry of a key stays the n-th).
    private func relocalize() {
        for e in elements.values {
            if let raw = e.raw {
                e.text = localize(raw)
                if e.kind == "B", let label = label(for: e) { label.text = e.text }
            }
            guard let name = e.sourceName else { continue }
            let fresh = entries(textRecords(name) ?? "")
            var seen: [String: Int] = [:]
            e.entries = e.entries.map { old in
                let n = seen[old.key, default: 0]; seen[old.key] = n + 1
                let same = fresh.filter { $0.key == old.key }
                return same.indices.contains(n) ? same[n] : same.last ?? old
            }
            e.source = fresh
        }
    }

    private func entries(_ raw: String) -> [(key: String, text: String)] {
        var out: [(String, String)] = []
        var cursor = raw.startIndex
        while let open = raw[cursor...].firstIndex(of: "["), let close = raw[open...].firstIndex(of: "]") {
            let next = raw.index(after: close)
            let end = raw[next...].range(of: "\n[")?.lowerBound ?? raw.endIndex
            let key = raw[raw.index(after: open)..<close].trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
            let text = raw[next..<end].trimmingCharacters(in: .whitespacesAndNewlines)
            out.append((key, text))
            cursor = end < raw.endIndex ? raw.index(after: end) : raw.endIndex
        }
        return out
    }

    public func defineList(_ name: String, _ source: String) {
        defineList(name, source, keys: [], times: [])
    }

    public func defineList(_ name: String, _ source: String, keys: [String], times: [Int]) {
        guard let e = element(name) else { return }
        e.active = true; e.sourceName = source; e.source = entries(textRecords(source) ?? ""); e.entries = []; e.entryTimes = []; e.items = []
        e.selected = 0; e.top = 0; e.selectable = false
        // The list's first update (FUN_1268_10c5) adds the record's unkeyed "[]" entries in authored order, then (FUN_1268_1213)
        // the ADDLOGENTRY store's keys: Caynan's, Dane's and Escher's logs need no ADDENTRY (monitor.py set_list_entries).
        e.entries = e.source.filter { $0.key.isEmpty }
        e.entryTimes = Array(repeating: nil, count: e.entries.count)
        for (index, key) in keys.enumerated() {
            let match = key.hasPrefix("*") ? String(key.dropFirst()) : key
            let found = e.source.filter { $0.key == match.uppercased() }
            let selected = key.hasPrefix("*") ? found : Array(found.prefix(1))
            e.entries += selected
            let stamp = times.indices.contains(index) ? times[index] : nil
            e.entryTimes += Array(repeating: stamp, count: selected.count)
        }
    }

    /// `key` is the item's World.items key (several rows of one name are fine).
    public func makeInventory(_ name: String, _ items: [(name: String, type: String, key: String)]) {
        guard let e = element(name) else { return }
        let keys = Set(e.source.map(\.key))
        e.entries = []; e.entryTimes = []; e.items = []; e.selected = 0; e.top = 0; e.selectable = true
        for item in items {
            let key = keys.contains(item.name.uppercased()) ? item.name.uppercased() : keys.contains(item.type.uppercased()) ? item.type.uppercased() : nil
            if let key, let entry = e.source.first(where: { $0.key == key }) { e.entries.append(entry); e.entryTimes.append(nil); e.items.append(item.key) }
        }
        if let first = e.entries.first, !first.key.isEmpty { highlightPending = first.key }
    }

    public func addEntry(_ name: String, _ key: String) {
        guard let e = element(name), let entry = e.source.first(where: { $0.key == key.uppercased() }) else { return }
        e.entries.append(entry); e.entryTimes.append(nil)
    }

    public func removeEntry(_ name: String, _ key: String) {
        guard let e = element(name) else { return }
        let key = key.uppercased()
        if key.hasPrefix("*") {
            e.entries = []; e.entryTimes = []; e.items = []; e.selected = 0; e.top = 0
            if key.hasPrefix("*+") { addEntry(name, String(key.dropFirst(2))) }
        } else {
            let kept = zip(e.entries, e.entryTimes).filter { $0.0.key != key }
            e.entries = kept.map(\.0); e.entryTimes = kept.map(\.1)
            e.selected = min(e.selected, max(e.entries.count - 1, 0))
        }
    }

    public func scrollList(_ name: String, _ code: Int) {
        guard let e = element(name), !e.entries.isEmpty else { return }
        if code == 43 || code == 45 {
            let new = max(0, min(e.entries.count - 1, e.selected + (code == 43 ? 1 : -1)))
            if new != e.selected { e.selected = new; highlightPending = e.entries[new].key }
        } else if [200, 208, 201, 209].contains(code), let style = e.style, let font = font(style.1) {
            let step = [201, 209].contains(code) ? max(e.height / max(font.height, 1) - 1, 1) : 1
            e.top = max(0, e.top + ([208, 209].contains(code) ? step : -step))
        }
    }

    public func setScale(_ name: String, _ percent: Int, _ index: Int) {
        guard let e = element(name) else { return }
        e.active = true; e.scale[index] = max(0, min(100, percent))
    }

    public func defineViewport(_ name: String, _ camera: String) {
        guard let e = element(name) else { return }
        e.active = true
        viewport = (e.name, camera.uppercased())
    }

    func setViewportRenderer(_ renderer: @escaping (String) -> Framebuffer?) { viewportFrame = renderer }

    public func setVariableResolver(_ resolve: @escaping (String) -> String?, formatTime: @escaping (Int) -> String,
                                    currentTime: @escaping () -> String) {
        resolveVariable = resolve; self.formatTime = formatTime; self.currentTime = currentTime
    }

    public func selectedItem(_ name: String) -> String? {
        guard let e = element(name), e.items.indices.contains(e.selected) else { return nil }
        return e.items[e.selected]
    }

    public func selectedIndex(_ name: String) -> Int { element(name)?.selected ?? 0 }
    func listKeys(_ name: String) -> [String] { element(name)?.entries.map(\.key) ?? [] }
    func listText(_ name: String) -> [String] { element(name)?.entries.map(\.text) ?? [] }
    func viewportCamera() -> String? { viewport?.camera }
    // Options dialog (Options.swift): raw TEXT.FLX record, active-element hit test and a one-entry text area.
    func rawText(_ name: String) -> String? { textRecords(name) }
    func elementText(_ name: String) -> String? { element(name)?.text }
    func setElementText(_ name: String, _ text: String) { element(name)?.text = text; element(name)?.raw = nil }
    func elementActive(_ name: String) -> Bool { element(name)?.active ?? false }
    func elementFrame(_ name: String) -> Int? { element(name)?.frame }
    /// Button vtable +0x20 (FUN_1278_0894) for an options control: the state is the frame it draws and its label's text colour.
    func setControlState(_ name: String, _ state: Int) {
        guard let e = element(name) else { return }
        e.frame = state; e.state = State(rawValue: state) ?? .normal
        if let label = label(for: e), label.active { label.state = e.state }
    }
    func hitsActive(_ name: String, _ x: Int, _ y: Int) -> Bool { element(name).map { $0.active && $0.hit(x, y) } ?? false }
    func setTextArea(_ name: String, _ text: String) {
        guard let e = element(name) else { return }
        e.active = true; e.entries = [("", text)]; e.entryTimes = []; e.top = 0
    }

    /// FUN_1270_0463: the position changes only while the pointer is idle (state 0), clamped to the margins (FUN_1270_0151). -> true if it moved.
    @discardableResult func setPointerPos(x: Int, y: Int) -> Bool {
        glide = nil                                                      // a mouse move also ends a glide (FUN_1270_08ef: target := position)
        guard pointerState == 0 else { return false }
        let m = Self.pointerMargins
        pointer = (max(m.left, min(m.right, x)), max(m.top, min(m.bottom, y)))
        return true
    }
    var pointerPosition: (x: Int, y: Int) { pointer }

    /// Dropped while input is off: "PROHIBIT PTR MOVEMENT OF PTR BY DISABLING MONITOR INPUT" (CHAOSMON.scr).
    public func pointerMove(x: Int, y: Int) {
        pollHeld()
        guard inputEnabled, setPointerPos(x: x, y: y) else { return }
        updateHover()
    }

    private func updateHover() {
        if let hoverOverride { hoverOverride(); return }
        let next = selectableButton(at: pointer.x, pointer.y)?.name
        guard next != hovered else { return }
        if let old = hovered, let e = element(old), (e.state == .highlight || e.state == .selectedHighlight) {
            e.state = e.state == .highlight ? .normal : .selected
            if let label = label(for: e), label.active { label.state = e.state }
        }
        hovered = next
        if let next, let e = element(next) {
            focus = next
            highlightPending = next                                  // monitor.py hover: the next MON_JUMP runs <button>_HIGHLIGHT
            if e.state == .normal { e.state = .highlight }
            else if e.state == .selected { e.state = .selectedHighlight }
            if let label = label(for: e), label.active { label.state = e.state }
        }
    }

    // MARK: the pointer's glide (monitor.py glide_to / _glide_step)

    /// FUN_1270_0536: clamp the target to the margins; the distance is |dx| or |dy| on an axis and else ceil(sqrt(|dx|*|dy|)) from a 16-bit signed
    /// product (one that wraps to <= 0 gives 0: the first step snaps to the target).
    func glideTo(x: Int, y: Int) {
        let m = Self.pointerMargins
        let target = (x: max(m.left, min(m.right, x)), y: max(m.top, min(m.bottom, y)))
        let dx = target.x - pointer.x, dy = target.y - pointer.y
        var dist: Int
        if dx == 0 { dist = abs(dy) }
        else if dy == 0 { dist = abs(dx) }
        else {
            var prod = Int(Int16(truncatingIfNeeded: abs(dx) * abs(dy)))
            dist = 0
            var odd = -1
            while prod > 0 { dist += 1; prod += odd; odd -= 2 }
        }
        glide = Glide(start: pointer, target: target, delta: (dx, dy), rounding: (dx < 0 ? -50 : 50, dy < 0 ? -50 : 50), dist: dist, half: dist / 2)
    }

    /// FUN_1270_064f: accelerate by `a` up to half the distance, coast one step, decelerate; the position is the percentage of the way.
    private func glideStep(_ dt: Int) {
        guard var g = glide else { return }
        if g.p == 0 { g.p = -g.a } else if g.p > 0 && g.half <= g.t { g.p = 0 }
        g.s += g.p * dt
        let travelled = UInt32(truncatingIfNeeded: g.s * dt + 30) / 60            // an unsigned long division into a 16-bit int
        g.t = Int(Int16(truncatingIfNeeded: g.t + Int(travelled)))
        if g.t < g.dist && (g.s > 0 || g.p >= 0) {
            let pct = g.t * 100 / g.dist
            pointer = ((g.delta.x * pct + g.rounding.x) / 100 + g.start.x, (g.delta.y * pct + g.rounding.y) / 100 + g.start.y)   // Swift / truncates, as C
        } else {
            pointer = g.target
        }
        glide = g
        arrived()
    }

    /// FUN_1250_1acf after each step: the button under the pointer is highlighted, and a letter shortcut's button is clicked once the pointer sits
    /// on its centre (FUN_1250_1a92: mouse down and up, the shortcut cleared).
    private func arrived() {
        updateHover()
        if let name = shortcut, focus == name, let c = buttonCenter(name), c == pointer {
            shortcut = nil
            pointerDown()
            mouseUp()
        }
    }

    func buttonCenter(_ name: String) -> (x: Int, y: Int)? {
        guard let e = element(name), e.kind == "B", e.active else { return nil }
        return (e.x + e.width / 2, e.y + e.height / 2)
    }

    func buttonState(_ name: String) -> Int? { element(name)?.state.rawValue }

    // MARK: the pointer's press animation (monitor.py mouse_down / mouse_up / update)

    private var pointerCount: Int { pointerFrames.count - 1 }

    /// FUN_1270_01ae: restart the phase clock; the interval is (time + (count + 1) / 2) / (count + 1) 60 Hz units.
    private func startPhase(_ time: Int) {
        let n = pointerCount + 1
        pointerStart = pointerClock; pointerInterval = (time + n / 2) / n
    }

    /// The pointer's button went down. Frame 1 starts the press animation (the button is pressed when it reaches the last frame, `update`);
    /// a press while it runs is dropped (the original sets +0x47 and never reads it); with the last frame held the button is pressed at once.
    /// -> true if a selectable button is under the pointer and the press was taken.
    @discardableResult public func mouseDown() -> Bool {
        pollHeld()
        guard inputEnabled else { return false }                                  // FUN_1250_0cf9 drops the event
        return pointerDown()
    }

    /// FUN_1270_01ec: the press animation starts (the shortcut's click calls it without the event handler's input check).
    @discardableResult private func pointerDown() -> Bool {
        if pointerCount < 1 { return (pressAction ?? pressButton)() }          // ASSUMPTION: a pointer without animation frames presses at once
        guard pointerFrame > 0, pointerState == 0 else { return false }
        if pointerFrame == pointerCount { return (pressAction ?? pressButton)() }     // FUN_1250_185d: only when a button is under the pointer
        pointerFrame = 1; pointerState = 1
        startPhase(pointerPressTime.press)
        setInput(false)                                                           // FUN_1250_0415(...,0): input stays off until the release
        return selectableButton(at: pointer.x, pointer.y) != nil
    }

    /// Test driver (not the original; monitor.py settle_pointer): the animation has run its course and the hand is idle on its last frame, as a
    /// held mouse leaves it; the next mouse down presses at once and the next mouse up releases at once.
    func settlePointer() {
        pointerState = 0; releasePending = false
        if pointerCount >= 1 { pointerFrame = pointerCount }
    }

    /// The pointer's button went up: the release runs at once when idle, else when the press animation has ended (`update`).
    public func mouseUp() {
        pollHeld()
        if pointerCount < 1 { _ = (releaseAction ?? releaseButton)(); return }
        guard pointerFrame > 0 else { return }
        if pointerState == 0 { startRelease() } else { releasePending = true }
    }

    private func startRelease() {
        setInput(true)                                                            // FUN_1250_0415(...,1), before the release action
        _ = (releaseAction ?? releaseButton)()
        releasePending = false; pointerState = -1
        startPhase(pointerPressTime.release)
    }

    /// FUN_1270_02ef, once per tick: the press / hold / release phases and the frame step. The blocks fall through within one call.
    public func update() {
        pointerClock += Self.clockPerTick
        if let g = glide, pointer != g.target {                                   // FUN_1270_0891: step while off the target
            glideStep(Self.glideDT)
            gliding = true
        } else {
            gliding = false
        }
        let now = pointerClock, count = pointerCount
        var step = 0
        if pointerState == 1 {
            if pointerFrame == count {
                if !gliding { _ = (pressAction ?? pressButton)() }      // FUN_1270_02ef: skipped while the pointer glides (DAT_9fea); hold and release still run
                pointerState = 2
                startPhase(pointerPressTime.hold)
            } else if now - pointerStart >= pointerInterval {
                pointerStart = now; step = 1
            }
        }
        if pointerState == 2, now - pointerStart >= pointerInterval {
            pointerState = 0
            if releasePending { startRelease(); step = -1 }
        }
        if pointerState == -1 {
            if pointerFrame == 1 { step = 0; pointerState = 0 }
            else if now - pointerStart >= pointerInterval { pointerStart = now; step = -1 }
        }
        pointerFrame += step
    }

    /// FUN_1250_12f6: capture and press the button below the pointer (a list row selects instead).
    private func pressButton() -> Bool {
        if let list = list(at: pointer.x, pointer.y), let style = list.style, let font = font(style.1) {
            let row = list.top + (pointer.y - list.y) / max(font.height + 1, 1)
            if list.entries.indices.contains(row), row != list.selected { list.selected = row; highlightPending = list.entries[row].key }
            return false
        }
        guard let e = selectableButton(at: pointer.x, pointer.y) else { return false }
        captured = e.name
        press(e.name)
        return true
    }

    /// FUN_1250_13f1: release the button captured by the matching press.
    private func releaseButton() -> Bool {
        guard let name = captured, let e = element(name) else { captured = nil; return false }
        captured = nil
        if e.mode == 0 && (e.state == .selected || e.state == .selectedHighlight) { e.state = .normal }
        if let label = label(for: e), label.active { label.state = e.state }
        released = name
        if !pressed.isEmpty && repeatState == 0 { clickPending = true }
        return true
    }

    // MARK: keys (FUN_1250_0cf9 and the focus helpers 0449, 0544, 05bf, 0638, 15ef, 1166; monitor.py key_event)

    /// The key handler's extended keys (PC scan | 0x80): up to three directions of the focus search FUN_1250_0638 (0 up, 1 down, 2 right, 3 left,
    /// 4 up-right, 5 down-right, 6 down-left, 7 up-left, 8 nearest in either axis); the first that moves the focus wins, else the previous (1250:05bf)
    /// or next (1250:0544) button (jump table 1250:112e).
    private static let keyTries: [Int: (dirs: [Int], next: Bool)] = [
        0xc7: ([7, 3, 0], false), 0xc8: ([0, 7, 4], false), 0xc9: ([4, 2, 0], true), 0xcb: ([3, 6, 7], false), 0xcc: ([8], false),
        0xcd: ([2, 5, 4], true), 0xcf: ([6, 3, 1], false), 0xd0: ([1, 6, 5], true), 0xd1: ([5, 2, 1], true)]
    public static let keyTab = 0x09, keyBackTab = 0x8f, keyReturn = 0x0d, keyEscape = 0x1b, keySpace = 0x20
    private static let scanReturn = 0x1c, scanEscape = 0x01
    private static let ascii: [Int: Character] = {
        var m: [Int: Character] = [:]
        for (i, c) in "qwertyuiop".enumerated() { m[0x10 + i] = c }
        for (i, c) in "asdfghjkl".enumerated() { m[0x1e + i] = c }
        for (i, c) in "zxcvbnm".enumerated() { m[0x2c + i] = c }
        for (i, c) in "1234567890".enumerated() { m[0x02 + i] = c }
        return m
    }()

    /// The event's key byte for a PC scan code: the ASCII byte when the key has one, else the scan code | 0x80; Shift+Tab 0x8f. nil for keys the
    /// monitor ignores.
    public static func keyCode(scan: Int, shift: Bool = false) -> Int? {
        switch scan {
        case 0x0f: return shift ? keyBackTab : keyTab
        case 0x1c: return keyReturn
        case 0x01: return keyEscape
        case 0x39: return keySpace
        default:
            if let c = ascii[scan] { return Int(c.asciiValue!) }
            return keyTries[scan | 0x80] != nil ? scan | 0x80 : nil
        }
    }

    private func focusables() -> [String] {
        if let buttonsProvider { return buttonsProvider() }
        return order.compactMap { elements[$0] }.filter { $0.kind == "B" && $0.active && $0.state != .disabled }.map(\.name)
    }

    /// FUN_1250_0449: the selectable buttons. The focus (+0x112) starts on the first button of the monitor and moves to the first selectable one when
    /// it is not selectable itself.
    private func focusButtons() -> [String] {
        let buttons = focusables()
        if !buttons.isEmpty, focus.map({ !buttons.contains($0) }) ?? true {
            var first: String?
            if focus == nil && buttonsProvider == nil { first = order.first { elements[$0]?.kind == "B" } }
            focus = first.flatMap { buttons.contains($0) ? $0 : nil } ?? buttons[0]
        }
        return buttons
    }

    func centre(_ name: String) -> (x: Int, y: Int) {
        guard let e = element(name) else { return (0, 0) }
        return (e.x + e.width / 2, e.y + e.height / 2)
    }

    /// FUN_1250_0638: the button nearest the focus in direction `d` (the focus when there is none). A button counts when it is not the focus, in the
    /// direction's half-plane without overlapping the focus's span on the other axis (0-3 need the focus's centre inside its span), and
    /// 0 < distance < the best so far (the first of equals wins); the distance is along the axis, or |dx| + |dy| of the centres.
    private func direction(_ d: Int, _ buttons: [String]) -> String {
        guard let cur = focus else { return "" }
        let c = centre(cur)
        var best = 0x7fff, found = cur
        for name in buttons where name != cur {
            guard let e = element(name) else { continue }
            let p = centre(name)
            let inY = e.y < c.y && c.y < e.y + e.height, inX = e.x < c.x && c.x < e.x + e.width
            let ok: Bool
            switch d {
            case 0, 1: ok = inX
            case 2, 3: ok = inY
            case 8: ok = !inY && !inX
            case 4: ok = !inY && !inX && p.x > c.x && p.y <= c.y
            case 5: ok = !inY && !inX && p.x > c.x && p.y > c.y
            case 6: ok = !inY && !inX && p.x <= c.x && p.y > c.y
            default: ok = !inY && !inX && p.x <= c.x && p.y <= c.y
            }
            guard ok else { continue }
            let dist: Int
            switch d {
            case 0: dist = c.y - p.y
            case 1: dist = p.y - c.y
            case 2: dist = p.x - c.x
            case 3: dist = c.x - p.x
            default: dist = abs(p.x - c.x) + abs(p.y - c.y)
            }
            if dist > 0 && dist < best { best = dist; found = name }
        }
        return found
    }

    /// FUN_1250_0544 (+1) / 05bf (-1): the next / previous selectable button, wrapping.
    private func step(_ buttons: [String], _ delta: Int) -> String {
        let i = buttons.firstIndex(of: focus ?? "") ?? 0
        return buttons[((i + delta) % buttons.count + buttons.count) % buttons.count]
    }

    /// The focus moves at once (+0x112) and FUN_1250_15ef glides the pointer to its centre (and clears [9dca] & 2).
    private func focusTo(_ name: String) {
        focus = name
        mouseMoved = false
        let c = centre(name)
        glideTo(x: c.x, y: c.y)
    }

    /// FUN_1250_0fe2 (MON_SIMULATE _KB_TAB): focus the next selectable button and glide the pointer there; the highlight comes as it crosses.
    func tab() {
        let buttons = focusButtons()
        guard !buttons.isEmpty else { return }
        focusTo(step(buttons, 1))
    }

    /// FUN_1250_0c4c, first in every event: a held Return / Space press ends, with a mouse up, once the key it follows is up and the hand is past its
    /// first frame (Space follows the Return key's state, as the original reads scan 0x1c); an Escape ends with ESCAPE released.
    private func pollHeld() {
        guard heldKey != 0, !keysDown.contains(heldKey) else { return }
        if heldKey == Self.scanReturn {
            if pointerFrame > 1 { heldKey = 0; mouseUp() }
        } else {
            released = "ESCAPE"; heldKey = 0
        }
    }

    /// A key press reaches the event handler (FUN_1250_0cf9): `code` is the ASCII byte, or the PC scan code | 0x80 for the extended keys (0x8f is
    /// Shift+Tab), `scan` the key's scan code (the keyboard state 0c4c reads), `force` the input switch MON_SIMULATE turns on for the call
    /// (FUN_1258_017f). -> true when the key was used.
    @discardableResult public func keyEvent(_ code: Int, scan: Int? = nil, force: Bool = false) -> Bool {
        pollHeld()
        if let scan { keysDown.insert(scan) }
        guard inputEnabled || force else { return false }
        if code == Self.keyReturn || code == Self.keySpace {      // FUN_1250_10c3: +0x11e = 0x1c, the pointer's mouse down
            heldKey = Self.scanReturn
            pointerDown()
            return true
        }
        if code == Self.keyEscape {                               // FUN_1250_10e4: +0x11e = 1, "ESCAPE" pressed (the key is not consumed)
            heldKey = Self.scanEscape
            pressed = "ESCAPE"; repeatState = 0
            return false
        }
        let buttons = focusButtons()
        if code == Self.keyTab || code == Self.keyBackTab {
            if !buttons.isEmpty { focusTo(step(buttons, code == Self.keyTab ? 1 : -1)) }
            return true
        }
        var tries = Self.keyTries[code]
        if tries == nil, code < 0x80, Character(UnicodeScalar(UInt8(code))).uppercased() == "L" { tries = ([8], false) }
        if let tries {
            if !buttons.isEmpty {
                let moved = tries.dirs.map { direction($0, buttons) }.first { $0 != focus }
                focusTo(moved ?? step(buttons, tries.next ? 1 : -1))
            }
            return true
        }
        return code < 0x80 ? letterKey(Character(UnicodeScalar(UInt8(code)))) : false
    }

    /// A right mouse button down (event type 1 with flag 2, FUN_1250_0cf9): "ESCAPE" pressed through FUN_1258_0f8b, as the Escape key does; the event
    /// is not consumed and nothing holds it (no release label). Dropped while input is off.
    public func rightClick() {
        pollHeld()
        if inputEnabled { pressed = "ESCAPE"; repeatState = 0 }
    }

    /// A key went up: the keyboard state changes and the event ends a held press (FUN_1250_0c4c).
    public func keyRelease(_ scan: Int) {
        keysDown.remove(scan)
        pollHeld()
    }

    /// FUN_1250_1166: a letter / digit / punctuation key (above '/' and below '{') clicks the selectable button whose shortcut is that character:
    /// the pointer on its centre with the button focused clicks at once (FUN_1250_1a92: mouse down and up), else it glides there and the arrival
    /// clicks (`arrived`). -> true when a button matched.
    func setShortcut(_ name: String, _ ch: Character) { element(name)?.shortcut = ch }       // test hook: what FUN_1278_0894 would store

    @discardableResult func letterKey(_ ch: Character) -> Bool {
        guard !focusButtons().isEmpty, let a = ch.asciiValue, a > 0x2f, a < 0x7b else { return false }
        let lower = Character(ch.lowercased())
        guard let name = focusables().first(where: { element($0)?.shortcut == lower }) else { shortcut = nil; return false }
        shortcut = name
        let c = centre(name)
        if focus == name && pointer == c {
            shortcut = nil
            pointerDown(); mouseUp()
        } else {
            glideTo(x: c.x, y: c.y)
        }
        return true
    }

    /// A named button pressed and released without the pointer (monitor.py press / release, the prototype's test driver).
    func press(_ name: String) {
        guard let e = element(name), e.kind == "B", e.active else { return }
        if e.state == .highlight || e.state == .selectedHighlight { hovered = nil }
        e.state = e.mode != 0 && (e.state == .selected || e.state == .selectedHighlight) ? .normal : .selected      // ASSUMPTION: a toggle button flips selected <-> normal
        if let label = label(for: e), label.active { label.state = e.state }
        pressed = e.name; repeatState = 0
    }

    func release(_ name: String) {
        guard let e = element(name), e.kind == "B", e.active else { return }
        if e.mode == 0 && (e.state == .selected || e.state == .selectedHighlight) { e.state = .normal }
        if let label = label(for: e), label.active { label.state = e.state }
        released = e.name
    }

    /// A key press that scripts map to <name>_BUTTON; dropped while input is off (FUN_1250_0cf9).
    public func key(_ name: String) { guard inputEnabled else { return }; pressed = name.uppercased(); repeatState = 0 }

    /// MON_JUMP: label to jump to and ticks to wait (0 immediately loops, 1 yields a tick, 10 is hold-repeat delay).
    public func poll() -> (label: String?, wait: Int) {
        if !highlightPending.isEmpty { let key = highlightPending; highlightPending = ""; return (key + "_HIGHLIGHT", 0) }
        if clickPending { clickPending = false; repeatState = 1; return (pressed + "_BUTTON", 1) }
        if !released.isEmpty { let name = released; released = ""; pressed = ""; repeatState = 0; return (name + "_RELEASED", 0) }
        if repeatState > 0 {
            if repeatState > 1 { return (pressed + "_REPEAT", 1) }
            repeatState = 2
            return (nil, 10)
        }
        if !pressed.isEmpty { repeatState = 1; return (pressed + "_BUTTON", 1) }
        return (nil, 0)
    }

    /// `underlay`: the picture already on screen (a CAMERA SHOW picture, World.shownPicture), dimmed onto the dark grey range where the
    /// background is transparent (monitor.py render / dark_grey; matches a VGA dump of the original's reload dialog).
    public func render(into framebuffer: inout Framebuffer, underlay: Framebuffer? = nil) {
        framebuffer.palette = palette
        framebuffer.clear()
        if let underlay { for i in framebuffer.pixels.indices { framebuffer.pixels[i] = Self.darkGrey(underlay, Int(underlay.pixels[i])) } }
        if let background { framebuffer.blit(background) }
        // Observed on CELL monitor 1: a V element is a live 320x200 room view
        // stretched into its authored bounds; normal monitor controls draw over it.
        for name in order {
            guard let e = elements[name], e.active, e.kind == "V", viewport?.element == e.name,
                  let camera = viewport?.camera else { continue }
            drawViewport(camera, in: e, into: &framebuffer)
        }
        for name in order {
            guard let e = elements[name], e.active else { continue }
            if e.kind == "V" { continue }
            if e.kind == "B" {
                guard e.state != .invisible else { continue }
                let i = e.state == .disabled && e.frames.count <= 5 ? 1 : min(e.state.rawValue, e.frames.count - 1)
                if i > 0 && i < e.frames.count { framebuffer.blit(e.frames[i]) }
            } else if e.kind == "S" {
                for index in e.scale.keys.sorted() where e.frames.indices.contains(index) { blitClipped(e.frames[index], percent: e.scale[index] ?? 0, into: &framebuffer) }
            } else if e.gauge {
                for i in 1..<max(1, min(e.frame + 1, e.frames.count)) { framebuffer.blit(e.frames[i]) }
            } else if e.kind != "L", e.frame > 0, e.frame < e.frames.count {
                if translucentKinds.contains(e.kind) { framebuffer.blitTranslucent(e.frames[e.frame]) } else { framebuffer.blit(e.frames[e.frame]) }
            }
        }
        for name in order {
            guard let e = elements[name], e.active, e.kind == "L", !e.text.isEmpty, e.state != .invisible else { continue }
            draw(e.text, in: e) { framebuffer.drawGlyph($0, left: $1, top: $2, colour: $3) }
        }
        for name in order {
            guard let e = elements[name], e.active, e.kind == "T", !e.entries.isEmpty else { continue }
            drawList(e) { framebuffer.drawGlyph($0, left: $1, top: $2, colour: $3) }
        }
        if pointerFrame > 0, pointerFrames.indices.contains(pointerFrame) {
            framebuffer.blit(pointerFrames[pointerFrame], x: pointer.x - Self.pointerHot.x, y: pointer.y - Self.pointerHot.y)
        }
    }

    /// The same picture on a High-Resolution Art frame (HiResFrame.swift), in the same order and with the same rules as `render(into:)`: each
    /// frame from the pack (monitors/<CAM>/<ENTRY>.<frame>) where it has one of s x its size, else the original enlarged; bars and gauges clipped
    /// at s x the bounds; a viewport is the 1x result enlarged (the live feed is only that big); text through HDText.scaledGlyph at s x the
    /// positions. With an empty pack it is the 1x picture enlarged exactly.
    /// `underlayHi`: the same picture as `underlay` at this scale (its pixels are indices into `underlay`'s palette); dimmed in place of
    /// the 1x picture enlarged.
    public func render(into hi: inout HiResFrame, pack: HiResPack, underlay: Framebuffer? = nil, underlayHi: HiResFrame? = nil) {
        let s = hi.scale
        func path(_ entry: String, _ frame: Int) -> String { "monitors/\(name)/\(entry).\(frame)" }
        hi = HiResFrame(scale: s)
        if let underlay {                                            // the dimmed picture: at this scale when given, else the 1x one enlarged
            if let big = underlayHi, big.scale == s {
                hi = big
                for i in hi.pixels.indices { hi.pixels[i] = Self.darkGrey(underlay, Int(big.pixels[i])) }
            } else {
                var grey = Framebuffer()
                for i in grey.pixels.indices { grey.pixels[i] = Self.darkGrey(underlay, Int(underlay.pixels[i])) }
                hi = HiResFrame(enlarging: grey, scale: s)
            }
        }
        if let background { hi.place(background, x: -background.hotX, y: -background.hotY, path: path(name, 0), pack: pack) }
        for name in order {
            guard let e = elements[name], e.active, e.kind == "V", viewport?.element == e.name,
                  let camera = viewport?.camera else { continue }
            var live = Framebuffer()                                 // the viewport as the 1x render draws it, enlarged into the element's rectangle
            guard drawViewport(camera, in: e, into: &live) else { continue }
            let x0 = max(e.x, 0), y0 = max(e.y, 0), x1 = min(e.x + e.width, Framebuffer.width), y1 = min(e.y + e.height, Framebuffer.height)
            for Y in (s * y0)..<(s * y1) { for X in (s * x0)..<(s * x1) { hi.pixels[Y * hi.width + X] = live.pixels[Y / s * Framebuffer.width + X / s] } }
        }
        func put(_ e: Element, _ i: Int, columns: Int = .max) {                 // elements (buttons, arrows, digits, gauges) are plain-enlarged
            let f = e.frames[i]                                                  // like the text, not taken from the pack: the AI-guided art
            hi.place(f, x: -f.hotX, y: -f.hotY, path: nil, pack: pack, columns: columns, translucent: translucentKinds.contains(e.kind))   // smeared them
        }
        for name in order {
            guard let e = elements[name], e.active else { continue }
            if e.kind == "V" { continue }
            if e.kind == "B" {
                guard e.state != .invisible else { continue }
                let i = e.state == .disabled && e.frames.count <= 5 ? 1 : min(e.state.rawValue, e.frames.count - 1)
                if i > 0 && i < e.frames.count { put(e, i) }
            } else if e.kind == "S" {
                for index in e.scale.keys.sorted() where e.frames.indices.contains(index) {
                    put(e, index, columns: s * (e.frames[index].width * (e.scale[index] ?? 0) / 100))
                }
            } else if e.gauge {
                for i in 1..<max(1, min(e.frame + 1, e.frames.count)) { put(e, i) }
            } else if e.kind != "L", e.frame > 0, e.frame < e.frames.count {
                put(e, e.frame)
            }
        }
        for name in order {
            guard let e = elements[name], e.active, e.kind == "L", !e.text.isEmpty, e.state != .invisible else { continue }
            draw(e.text, in: e) { hi.drawGlyph($0.rows, left: $1, top: $2, colour: $3) }
        }
        for name in order {
            guard let e = elements[name], e.active, e.kind == "T", !e.entries.isEmpty else { continue }
            drawList(e) { hi.drawGlyph($0.rows, left: $1, top: $2, colour: $3) }
        }
        if pointerFrame > 0, pointerFrames.indices.contains(pointerFrame) {
            let f = pointerFrames[pointerFrame]
            hi.place(f, x: pointer.x - Self.pointerHot.x - f.hotX, y: pointer.y - Self.pointerHot.y - f.hotY, path: "monitors/\(pointerCAM)/\(pointerEntry).\(pointerFrame)", pack: pack)
        }
    }

    private static func greyRamp(_ palette: [UInt8]) -> [UInt8] {
        var best: [UInt8] = [], start: Int?
        for i in 0...256 {
            let grey = i < 256 && palette[3 * i] == palette[3 * i + 1] && palette[3 * i] == palette[3 * i + 2]
            if grey && start == nil { start = i }
            if !grey, let first = start {
                if i - first >= 16 { best = Array(first..<i).map(UInt8.init) }
                start = nil
            }
        }
        return Array(best.suffix(32))
    }

    /// False when it drew nothing.
    @discardableResult
    private func drawViewport(_ camera: String, in e: Element, into framebuffer: inout Framebuffer) -> Bool {
        guard let source = viewportFrame?(camera), !greyRamp.isEmpty else { return false }
        let x0 = max(e.x, 0), y0 = max(e.y, 0)
        let x1 = min(e.x + e.width, Framebuffer.width), y1 = min(e.y + e.height, Framebuffer.height)
        guard x1 > x0, y1 > y0 else { return false }
        for y in y0..<y1 {
            let sy = min((y - e.y) * Framebuffer.height / e.height, Framebuffer.height - 1)
            for x in x0..<x1 {
                let sx = min((x - e.x) * Framebuffer.width / e.width, Framebuffer.width - 1)
                framebuffer.pixels[y * Framebuffer.width + x] = greyIndex(source, Int(source.pixels[sy * Framebuffer.width + sx]))
            }
        }
        return true
    }

    /// monitor.py dark_grey: a pixel of `source` (palette index `index`, 8-bit c * 255 / 63) on the dark grey range 128...145,
    /// 128 + max6 * 18 / 64 with max6 its largest 6-bit channel (FUN_1108_0d83 / 0cfc, applied by FUN_1138_1d0a).
    static func darkGrey(_ source: Framebuffer, _ index: Int) -> UInt8 {
        let i = index * 3
        let max8 = Int(Swift.max(source.palette[i], source.palette[i + 1], source.palette[i + 2]))
        return UInt8(128 + (max8 * 63 + 254) / 255 * 18 / 64)
    }

    /// A pixel of `source` (palette index `index`) on the grey ramp: Rec.601 luma mapped linearly (fitted, monitor.py to_grey_ramp).
    private func greyIndex(_ source: Framebuffer, _ index: Int) -> UInt8 {
        let i = index * 3
        let luma = 0.299 * Double(source.palette[i]) + 0.587 * Double(source.palette[i + 1]) + 0.114 * Double(source.palette[i + 2])
        return greyRamp[max(0, min(greyRamp.count - 1, Int((luma / 255 * Double(greyRamp.count - 1)).rounded(.toNearestOrEven))))]
    }

    private func localize(_ text: String) -> String {
        for tag in ["/" + language, "/E"] {
            if let r = text.range(of: tag) { return String(text[r.upperBound...].split(separator: "/", maxSplits: 1).first ?? "") }
        }
        if text.hasPrefix("/") { return String(text.dropFirst(2).split(separator: "/", maxSplits: 1).first ?? "") }
        return String(text.split(separator: "/", maxSplits: 1).first ?? "")
    }

    private func font(_ number: Int) -> CaptionFont? {
        let n = number >= 0x80 ? 0 : number
        if let font = fonts[n] { return font }
        guard let font = try? CaptionFont(game.read("DATA/\(n).FNT")) else { return nil }
        fonts[n] = font
        return font
    }

    /// The palette index with the lowest Rec.601 luma (ties: the lowest index).
    static func darkestIndex(_ palette: [UInt8]) -> UInt8 {
        var best = 0
        for i in 1..<(palette.count / 3) where luma(palette, i) < luma(palette, best) { best = i }
        return UInt8(best)
    }

    /// `index` itself when its largest channel is 250 or more (it is bright already; this keeps speaker colours apart). Else `index` scaled
    /// so its largest channel is 250, as the nearest palette entry (squared RGB distance, ties: the lowest index) among those
    /// brighter than `index` (Rec.601 luma, and a largest channel at least as high) that keep its hue (each channel's share of the entry's largest channel within 0.2 of the
    /// original's); `index` itself when there is none.
    static func brighterIndex(_ index: UInt8, in palette: [UInt8]) -> UInt8 {
        let i = Int(index), rgb = (0..<3).map { Int(palette[3 * i + $0]) }
        guard let top = rgb.max(), top > 0, top < 250 else { return index }
        let target = rgb.map { ($0 * 250 + top / 2) / top }
        var best = i, bestDistance = Int.max
        for j in 0..<(palette.count / 3) where luma(palette, j) > luma(palette, i) {
            let entry = (0..<3).map { Int(palette[3 * j + $0]) }
            guard let peak = entry.max(), peak >= top, (0..<3).allSatisfy({ abs(entry[$0] * 1000 / peak - rgb[$0] * 1000 / top) <= 200 }) else { continue }
            let distance = (0..<3).reduce(0) { $0 + (entry[$1] - target[$1]) * (entry[$1] - target[$1]) }
            if distance < bestDistance { best = j; bestDistance = distance }
        }
        return UInt8(best)
    }

    private static func luma(_ palette: [UInt8], _ i: Int) -> Int { 299 * Int(palette[3 * i]) + 587 * Int(palette[3 * i + 1]) + 114 * Int(palette[3 * i + 2]) }

    private func brighter(_ index: UInt8) -> UInt8 {
        if let known = brighterColours[index] { return known }
        let found = Self.brighterIndex(index, in: palette)
        brighterColours[index] = found
        return found
    }

    /// Glyph placements of one element: with readable text the shadow of every glyph first (so it never covers a neighbouring letter), then the
    /// glyphs in the brighter colour.
    private func emit(_ placed: [(glyph: CaptionFont.Glyph, x: Int, y: Int, colour: UInt8)], put: (CaptionFont.Glyph, Int, Int, UInt8) -> Void) {
        if readableText { for p in placed { put(p.glyph, p.x + 1, p.y + 1, shadowColour) } }
        for p in placed { put(p.glyph, p.x, p.y, readableText ? brighter(p.colour) : p.colour) }
    }

    /// The width of `text` in `font`, `spacing` px after each glyph but the last.
    private func width(_ text: String, _ font: CaptionFont, spacing: Int = 0) -> Int {
        text.unicodeScalars.reduce(0) { $0 + (font.glyph($1)?.width ?? 0) } + spacing * max(text.unicodeScalars.count - 1, 0)
    }

    /// Calls `put(glyph, left, top, colour)` for each glyph of a label's text, centred in its element (320x200 coordinates).
    private func draw(_ text: String, in e: Element, put: (CaptionFont.Glyph, Int, Int, UInt8) -> Void) {
        guard let style = e.style, let font = font(style.1) else { return }
        let colour = style.0[max(0, min(4, e.state.rawValue - 1))]
        let spacing = readableText && width(text, font, spacing: 1) <= e.width ? 1 : 0       // a label too wide for it keeps the original spacing
        let textWidth = width(text, font, spacing: spacing)
        var x = e.x + Int((Double(e.width - textWidth) / 2).rounded(.down))     // floor, as Python's // when the text is wider than the label
        let baseline = e.y + (e.height + font.height) / 2 - (font.height.isMultiple(of: 2) ? 1 : 0)
        var placed: [(glyph: CaptionFont.Glyph, x: Int, y: Int, colour: UInt8)] = []
        for scalar in text.unicodeScalars {
            if let glyph = font.glyph(scalar) { placed.append((glyph, x - glyph.xOrigin, baseline - glyph.baseline, colour)) }
            x += (font.glyph(scalar)?.width ?? 0) + spacing
        }
        emit(placed, put: put)
    }

    private func wrappedRows(_ e: Element, _ font: CaptionFont, spacing: Int) -> [(text: String, state: State)] {
        var rows: [(text: String, state: State)] = []
        for (index, entry) in e.entries.enumerated() {
            let state = e.selectable && index == e.selected ? State.highlight : State.normal
            let stamp = e.entryTimes.indices.contains(index) ? e.entryTimes[index] : nil
            rows += wrap(expand(entry.text, stamp: stamp), font: font, width: e.width, spacing: spacing).map { ($0, state) }
        }
        return rows
    }

    /// Whether every wrapped row of list `name` at `spacing` is in its visible area (tests).
    func listFits(_ name: String, spacing: Int) -> Bool {
        guard let e = element(name), let style = e.style, let font = font(style.1) else { return false }
        return (wrappedRows(e, font, spacing: spacing).count - 1) * (font.height + 1) < e.height
    }

    private func drawList(_ e: Element, put: (CaptionFont.Glyph, Int, Int, UInt8) -> Void) {
        guard let style = e.style, let font = font(style.1) else { return }
        let lineHeight = font.height + 1, lineBase = font.glyphs.map(\.baseline).max() ?? font.height     // monitor.py: y + Font.baseline
        var spacing = readableText ? 1 : 0
        var rows = wrappedRows(e, font, spacing: spacing)
        if spacing > 0, (rows.count - 1) * lineHeight >= e.height {      // the spaced text needs scrolling: keep the original wrapping if that fitted
            let original = wrappedRows(e, font, spacing: 0)
            if (original.count - 1) * lineHeight < e.height { spacing = 0; rows = original }
        }
        var placed: [(glyph: CaptionFont.Glyph, x: Int, y: Int, colour: UInt8)] = []
        for (row, entry) in rows.dropFirst(e.top).enumerated() {
            guard row * lineHeight < e.height else { break }
            let colour = style.0[max(0, min(4, entry.state.rawValue - 1))]
            var x = e.x
            let baseline = e.y + row * lineHeight + lineBase
            for scalar in entry.text.unicodeScalars {
                if let glyph = font.glyph(scalar) {
                    placed.append((glyph, x - glyph.xOrigin, baseline - glyph.baseline, colour))
                    x += glyph.width
                }
                x += spacing
            }
        }
        emit(placed, put: put)
    }

    private func wrap(_ text: String, font: CaptionFont, width limit: Int, spacing: Int = 0) -> [String] {
        var output: [String] = []
        for paragraph in text.replacingOccurrences(of: "\t", with: "  ").split(separator: "\n", omittingEmptySubsequences: false) {
            var current = ""
            for word in paragraph.split(separator: " ", omittingEmptySubsequences: false) {
                let candidate = current.isEmpty ? String(word) : current + " " + word
                if !current.isEmpty && width(candidate, font, spacing: spacing) > limit {
                    output.append(current); current = String(word)
                } else { current = candidate }
            }
            output.append(current)
        }
        return output
    }

    func expand(_ text: String, stamp: Int? = nil) -> String {
        var output = "", index = text.startIndex
        while index < text.endIndex {
            guard text[index] == "%" else { output.append(text[index]); index = text.index(after: index); continue }
            let next = text.index(after: index)
            if next < text.endIndex, text[next] == "%" { output.append("%"); index = text.index(after: next); continue }
            guard let end = text[next...].firstIndex(of: "%") else { output += text[index...]; break }
            let name = String(text[next..<end])
            let value = name.lowercased() == "time" ? stamp.flatMap { formatTime?($0) } ?? currentTime?() : resolveVariable?(name)
            output += value ?? String(text[index...end])
            index = text.index(after: end)
        }
        return output
    }

    private func blitClipped(_ frame: CAMFrame, percent: Int, into framebuffer: inout Framebuffer) {
        let width = frame.width * percent / 100, ox = -frame.hotX, oy = -frame.hotY
        for y in 0..<frame.height where (0..<Framebuffer.height).contains(oy + y) {
            for x in 0..<width where (0..<Framebuffer.width).contains(ox + x) && frame.mask[y * frame.width + x] != 0 {
                framebuffer.pixels[(oy + y) * Framebuffer.width + ox + x] = frame.pixels[y * frame.width + x]
            }
        }
    }
}
