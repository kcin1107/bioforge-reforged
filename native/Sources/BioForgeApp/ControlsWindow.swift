// Settings window (BioForge > Settings…, Cmd-,), with one pane: Controls. Every control has a key and an alternate; click one,
// then press the new key. Delete clears it, Escape cancels, Restore Defaults brings back the numpad-free set. Changes apply at
// once, with no OK button (HIG: settings windows are modeless and apply immediately). The bindings themselves are
// BioForgeHost.KeyBindings (HID usages; the Mac's key codes are translated by MacKeyCodes); key names follow the current keyboard layout.
// The last column is the game controller: click one, then press a button (PadBindings; the left stick and directional pad are always the eight directions).
import AppKit
import Carbon.HIToolbox
import BioForgeCore
import BioForgeHost

@MainActor
final class ControlsWindowController: NSWindowController, NSWindowDelegate {
    private(set) var bindings: KeyBindings
    private let onChange: (KeyBindings) -> Void
    private(set) var padBindings: PadBindings
    private let gamepad: GamepadInput
    private let onPadChange: (PadBindings) -> Void
    private static let padSlot = KeyBindings.slots
    private var buttons: [String: [NSButton]] = [:]
    private var capturing: (id: String, slot: Int)?

    init(bindings: KeyBindings, padBindings: PadBindings, gamepad: GamepadInput, onChange: @escaping (KeyBindings) -> Void, onPadChange: @escaping (PadBindings) -> Void) {
        self.bindings = bindings
        self.onChange = onChange
        self.padBindings = padBindings
        self.gamepad = gamepad
        self.onPadChange = onPadChange
        let window = CaptureWindow(contentRect: NSRect(x: 0, y: 0, width: 790, height: 640),
                              styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Controls"
        window.contentMinSize = NSSize(width: 730, height: 320)
        super.init(window: window)
        window.delegate = self
        window.intercept = { [weak self] e in self?.capture(e) ?? false }
        window.contentView = buildContent()
        window.center()
        window.setFrameAutosaveName("ControlsWindow")
        refresh()
    }

    required init?(coder: NSCoder) { fatalError() }

    // MARK: layout

    private func buildContent() -> NSView {
        let grid = NSGridView()
        grid.rowSpacing = 6
        grid.columnSpacing = 12
        var group = "", headers: [NSGridRow] = []
        grid.addRow(with: ["", "Key", "Alternate", "Controller"].map { title -> NSTextField in
            let label = NSTextField(labelWithString: title)
            label.textColor = .secondaryLabelColor
            return label
        })
        for c in KeyBindings.controls {
            if c.group != group {
                group = c.group
                let header = NSTextField(labelWithString: group)
                header.font = .boldSystemFont(ofSize: NSFont.systemFontSize)
                let row = grid.addRow(with: [header])
                row.topPadding = grid.numberOfRows > 1 ? 10 : 0
                headers.append(row)
            }
            let label = NSTextField(labelWithString: c.title)
            let slots = (0...Self.padSlot).map { slot -> NSButton in
                let b = NSButton(title: "", target: self, action: #selector(beginCapture(_:)))
                b.bezelStyle = .push
                b.tag = slot
                b.identifier = NSUserInterfaceItemIdentifier(c.id)
                b.imagePosition = .imageLeading
                b.isEnabled = slot != Self.padSlot || !PadBindings.directions.contains(c.id)
                b.widthAnchor.constraint(equalToConstant: 150).isActive = true
                return b
            }
            buttons[c.id] = slots
            grid.addRow(with: [label] + slots)
        }
        for row in headers { row.mergeCells(in: NSRange(location: 0, length: grid.numberOfColumns)) }     // once all columns exist
        grid.column(at: 0).xPlacement = .leading
        grid.translatesAutoresizingMaskIntoConstraints = false

        let document = FlippedView()
        document.translatesAutoresizingMaskIntoConstraints = false
        document.addSubview(grid)
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.drawsBackground = false
        scroll.documentView = document
        scroll.translatesAutoresizingMaskIntoConstraints = false

        let note = NSTextField(wrappingLabelWithString: "Click a key, then press the new one. Delete clears it; Escape cancels. "
            + "On a MacBook, Fn with the arrow keys gives Home, End, Page Up and Page Down. In combat, the direction keys attack; "
            + "hold the kick or punch key with a direction for the other attacks. On a controller, the left stick and directional pad "
            + "are the directions; on the game's screens they move the pointer, A clicks and B goes back.")
        note.textColor = .secondaryLabelColor
        note.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        note.translatesAutoresizingMaskIntoConstraints = false
        let restore = NSButton(title: "Restore Defaults", target: self, action: #selector(restoreDefaults))
        restore.bezelStyle = .push
        restore.translatesAutoresizingMaskIntoConstraints = false

        let content = NSView()
        for v in [scroll, note, restore] { content.addSubview(v) }
        let clip = scroll.contentView
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: content.topAnchor),
            scroll.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            document.leadingAnchor.constraint(equalTo: clip.leadingAnchor),
            document.trailingAnchor.constraint(equalTo: clip.trailingAnchor),
            document.topAnchor.constraint(equalTo: clip.topAnchor),
            grid.topAnchor.constraint(equalTo: document.topAnchor, constant: 20),
            grid.bottomAnchor.constraint(equalTo: document.bottomAnchor, constant: -12),
            grid.leadingAnchor.constraint(equalTo: document.leadingAnchor, constant: 20),
            grid.trailingAnchor.constraint(lessThanOrEqualTo: document.trailingAnchor, constant: -20),
            note.topAnchor.constraint(equalTo: scroll.bottomAnchor, constant: 12),
            note.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20),
            note.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -20),
            restore.topAnchor.constraint(equalTo: note.bottomAnchor, constant: 12),
            restore.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20),
            restore.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20),
        ])
        return content
    }

    private func refresh() {
        for (id, slots) in buttons {
            for (slot, b) in slots.enumerated() {
                let active = capturing.map { $0.id == id && $0.slot == slot } ?? false
                let pad = slot == Self.padSlot
                let label = pad ? padBindings.button(id).map(gamepad.label) : nil
                let bound = pad ? padBindings.button(id) != nil : bindings.key(id, slot: slot) != nil
                if active { b.title = pad ? "Press a Button…" : "Press a Key…" }
                else if pad && PadBindings.directions.contains(id) { b.title = "Stick / D-pad" }
                else { b.title = pad ? label?.title ?? "None" : bindings.key(id, slot: slot).map(Self.name) ?? "None" }
                b.image = active ? nil : label?.image
                b.bezelColor = active ? .controlAccentColor : nil
                b.contentTintColor = active || bound ? nil : .tertiaryLabelColor
            }
        }
    }

    // MARK: capture

    @objc private func beginCapture(_ sender: NSButton) {
        guard let id = sender.identifier?.rawValue else { return }
        capturing = (id, sender.tag)
        refresh()
    }

    /// True if the event was used to bind (or cancel); other events (Command shortcuts) go on to the menus.
    private func capture(_ e: NSEvent) -> Bool {
        guard let target = capturing, e.type == .keyDown || e.type == .flagsChanged else { return false }
        if e.type == .keyDown && e.modifierFlags.contains(.command) { return false }
        let key = e.keyCode
        if e.type == .flagsChanged {
            guard let bit = MacKeys.deviceBits[key] else { return true }        // Caps Lock, Fn, Command
            guard e.modifierFlags.rawValue & bit != 0 else { return true }            // the release of a modifier
        } else if e.isARepeat { return true }
        switch key {
        case UInt16(kVK_Escape): break
        case UInt16(kVK_Delete):
            if target.slot == Self.padSlot { bindPad(nil, target.id) } else { bind(nil, target) }
        default:
            guard let usage = MacKeyCodes.usage(forKeyCode: key), !KeyBindings.reserved.contains(usage), target.slot != Self.padSlot else { NSSound.beep(); return true }
            bind(usage, target)
        }
        endCapture()
        return true
    }

    private func bind(_ key: UInt16?, _ target: (id: String, slot: Int)) {
        bindings.bind(key, to: target.id, slot: target.slot)
        onChange(bindings)
    }

    /// A controller button while a controller cell waits for one: binds it. False when no cell is waiting.
    func capturePad(_ button: PadButton) -> Bool {
        guard let target = capturing, target.slot == Self.padSlot else { return false }
        bindPad(button, target.id)
        endCapture()
        return true
    }

    private func bindPad(_ button: PadButton?, _ id: String) {
        padBindings.bind(button, to: id)
        onPadChange(padBindings)
    }

    private func endCapture() {
        capturing = nil
        refresh()
    }

    @objc private func restoreDefaults() {
        bindings = KeyBindings()
        onChange(bindings)
        padBindings = PadBindings()
        onPadChange(padBindings)
        endCapture()
    }

    func windowDidResignKey(_ note: Notification) { if capturing != nil { endCapture() } }

    // MARK: key names

    private static let names: [Int: String] = [
        kVK_UpArrow: "↑", kVK_DownArrow: "↓", kVK_LeftArrow: "←", kVK_RightArrow: "→",
        kVK_Home: "Home (fn ←)", kVK_End: "End (fn →)", kVK_PageUp: "Page Up (fn ↑)", kVK_PageDown: "Page Down (fn ↓)",
        kVK_Space: "Space", kVK_Return: "Return", kVK_Tab: "Tab", kVK_Delete: "Delete", kVK_ForwardDelete: "Forward Delete",
        kVK_Shift: "Left Shift", kVK_RightShift: "Right Shift", kVK_Control: "Left Control", kVK_RightControl: "Right Control",
        kVK_Option: "Left Option", kVK_RightOption: "Right Option",
        kVK_ANSI_Keypad0: "Keypad 0", kVK_ANSI_Keypad1: "Keypad 1", kVK_ANSI_Keypad2: "Keypad 2", kVK_ANSI_Keypad3: "Keypad 3",
        kVK_ANSI_Keypad4: "Keypad 4", kVK_ANSI_Keypad5: "Keypad 5", kVK_ANSI_Keypad6: "Keypad 6", kVK_ANSI_Keypad7: "Keypad 7",
        kVK_ANSI_Keypad8: "Keypad 8", kVK_ANSI_Keypad9: "Keypad 9", kVK_ANSI_KeypadEnter: "Keypad Enter",
        kVK_ANSI_KeypadPlus: "Keypad +", kVK_ANSI_KeypadMinus: "Keypad −", kVK_ANSI_KeypadMultiply: "Keypad ×",
        kVK_ANSI_KeypadDivide: "Keypad ÷", kVK_ANSI_KeypadDecimal: "Keypad .", kVK_ANSI_KeypadEquals: "Keypad =",
        kVK_ANSI_KeypadClear: "Clear",
        kVK_F1: "F1", kVK_F2: "F2", kVK_F3: "F3", kVK_F4: "F4", kVK_F5: "F5", kVK_F6: "F6",
        kVK_F7: "F7", kVK_F8: "F8", kVK_F9: "F9", kVK_F10: "F10", kVK_F11: "F11", kVK_F12: "F12",
    ]

    /// What the key is called on this Mac's keyboard layout (so A on AZERTY shows as Q).
    static func name(_ usage: UInt16) -> String {
        guard let key = MacKeyCodes.keyCode(forUsage: usage) else { return "Key \(usage)" }
        if let n = names[Int(key)] { return n }
        if let c = layoutCharacter(key) { return c }
        return "Key \(key)"
    }

    private static func layoutCharacter(_ key: UInt16) -> String? {
        guard let source = TISCopyCurrentKeyboardLayoutInputSource()?.takeRetainedValue(),
              let raw = TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData) else { return nil }
        let data = Unmanaged<CFData>.fromOpaque(raw).takeUnretainedValue() as Data
        var dead: UInt32 = 0, length = 0
        var chars = [UniChar](repeating: 0, count: 4)
        let status = data.withUnsafeBytes { buf -> OSStatus in
            guard let layout = buf.bindMemory(to: UCKeyboardLayout.self).baseAddress else { return OSStatus(paramErr) }
            return UCKeyTranslate(layout, key, UInt16(kUCKeyActionDisplay), 0, UInt32(LMGetKbdType()),
                                  OptionBits(kUCKeyTranslateNoDeadKeysBit), &dead, chars.count, &length, &chars)
        }
        guard status == noErr, length > 0 else { return nil }
        let s = String(utf16CodeUnits: chars, count: length).trimmingCharacters(in: .whitespacesAndNewlines)
        return s.isEmpty ? nil : s.uppercased()
    }
}

/// Hands key events to the controller before AppKit uses them (Tab, Escape, Space on the focused button) while a key is captured.
private final class CaptureWindow: NSWindow {
    var intercept: ((NSEvent) -> Bool)?
    override func sendEvent(_ event: NSEvent) {
        if intercept?(event) == true { return }
        super.sendEvent(event)
    }
}

private final class FlippedView: NSView {
    override var isFlipped: Bool { true }
}
