// Help > BioForge Help (HIG "The menu bar": the app's help is the first Help menu item; "Offering help": describe this app's own tasks,
// not how standard controls work). One scrolling page, rebuilt each time it opens, so the controls section shows the keys the player has
// bound in Settings > Controls. Not a Help Book: the app is built by build-app.sh without an asset or help catalog, so there is no
// Help menu search field.
import AppKit
import BioForgeCore
import BioForgeHost
import BioForgeHost

@MainActor
final class HelpWindowController: NSWindowController {
    private let textView = NSTextView()

    init() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 640),
                              styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "BioForge Help"
        window.minSize = NSSize(width: 420, height: 320)
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("BioForgeHelp")
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.borderType = .noBorder
        textView.isEditable = false
        textView.isSelectable = true
        textView.drawsBackground = true
        textView.backgroundColor = .textBackgroundColor
        textView.textContainerInset = NSSize(width: 20, height: 18)
        textView.isVerticallyResizable = true
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        scroll.documentView = textView
        window.contentView = scroll
        super.init(window: window)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    func show(bindings: KeyBindings) {
        textView.textStorage?.setAttributedString(Self.page(bindings: bindings))
        textView.scrollToBeginningOfDocument(nil)
        if window?.isVisible != true { window?.center() }
        showWindow(nil)
    }

    // MARK: content

    static func page(bindings: KeyBindings) -> NSAttributedString {
        let out = NSMutableAttributedString()
        let body = NSFont.systemFont(ofSize: NSFont.systemFontSize)
        let paragraph = NSMutableParagraphStyle()
        paragraph.paragraphSpacing = 6
        func heading(_ s: String, size: CGFloat = 15) {
            let p = NSMutableParagraphStyle()
            p.paragraphSpacingBefore = out.length == 0 ? 0 : 12
            p.paragraphSpacing = 4
            out.append(NSAttributedString(string: s + "\n", attributes: [.font: NSFont.boldSystemFont(ofSize: size), .foregroundColor: NSColor.labelColor,
                                                                          .paragraphStyle: p]))
        }
        func text(_ s: String) {
            out.append(NSAttributedString(string: s + "\n", attributes: [.font: body, .foregroundColor: NSColor.labelColor, .paragraphStyle: paragraph]))
        }
        func row(_ title: String, _ keys: String) {
            let p = NSMutableParagraphStyle()
            p.tabStops = [NSTextTab(textAlignment: .left, location: 290)]
            p.headIndent = 290
            out.append(NSAttributedString(string: "\(title)\t\(keys)\n", attributes: [.font: body, .foregroundColor: NSColor.labelColor, .paragraphStyle: p]))
        }

        heading("BioForge Help", size: 20)
        text("This app plays the 1995 game BioForge from your own copy of the game. It does not include the game’s files.")

        heading("Getting started")
        text("Choose File > Open Game Folder… and pick the folder that contains BIOFORGE.EXE and a ROOMS folder. In a GOG installation that is the Bioforge folder inside the app folder; picking a folder above it also works. The app remembers the folder.")
        text("Choose Game > New Game (⌘N) to start from the beginning.")

        heading("Controls")
        text("These are your current keys. To change them, choose BioForge > Settings… (⌘,).")
        var group = ""
        for control in KeyBindings.controls {
            if control.group != group {
                group = control.group
                let p = NSMutableParagraphStyle()
                p.paragraphSpacingBefore = 8
                p.paragraphSpacing = 2
                out.append(NSAttributedString(string: group + "\n", attributes: [.font: NSFont.boldSystemFont(ofSize: NSFont.systemFontSize),
                                                                                 .foregroundColor: NSColor.secondaryLabelColor, .paragraphStyle: p]))
            }
            let keys = (0..<KeyBindings.slots).compactMap { bindings.key(control.id, slot: $0) }.map(ControlsWindowController.name)
            row(control.title, keys.isEmpty ? "Not set" : keys.joined(separator: " or "))
        }
        text("Escape pauses the game by opening the options dialog, closes the game’s screens and monitors, and skips the intro and the scenes the original lets you skip.")

        heading("Game controllers")
        text("Connect a controller in System Settings > Bluetooth or by cable; BioForge finds it by itself, and the keyboard keeps working. The left stick and directional pad are the eight directions. On the game’s screens they move the pointer, A clicks and B goes back. To change the buttons, choose BioForge > Settings… (⌘,).")

        heading("Fighting")
        text("Press the Combat Mode key to raise your fists. In combat mode the movement keys become attacks: hold the Kicks or Punches key with a direction for other attacks. Lex turns to face an enemy who is close. With a gun in hand, Shoot fires it.")
        text("To heal, open Diagnostics and switch on repair; it uses your battery. Medical kits from the inventory heal too.")

        heading("Saving and loading")
        text("Save and Load open the game’s own options dialog, with nine slots. Saves are kept in ~/Library/Application Support/BioForge/Saves and use the original game’s file format, so they can be copied to and from the DOS game. BioForge also autosaves when you enter a new level (the newest five are kept); File > Open Autosave… continues from one.")

        heading("Sound and picture")
        text("Game > Mute (⌥⌘M) silences everything. Game > Music Device chooses General MIDI or the original AdLib music. Game > Language switches the voices and text between English, Deutsch and Français. View > Correct Aspect Ratio shows the picture at the shape of a 1995 monitor; Enter Full Screen is ⌃⌘F. The game pauses while the app is in the background.")
        text("View > High-Resolution Art draws the picture at twice or four times the original resolution: choose 2x or 4x. The art is generated on this Mac from your game files by an AI-guided filter that keeps the game’s own colours; it isn’t hand-drawn. The first time, it builds in the background while you play, and rooms switch to the new art as they’re ready. Movies and monitors appear as in 1995.")

        heading("If something goes wrong")
        text("To report a bug, choose Help > Report a Bug… at the moment it happens. BioForge makes a zip file with where you are, a recent log and a save of that moment, and shows it in the Finder. Nothing is sent anywhere: attach the file yourself. After a crash, open BioForge again: it offers to make a report, which includes the crash report, the end of the last session’s log and a recording of that game.")
        text("If the app says the folder isn’t a BioForge game folder, choose the folder that contains BIOFORGE.EXE. This is a beta: some things still differ from the original game.")
        text("BioForge is a trademark of Electronic Arts Inc. This is an unofficial fan port; it is not affiliated with, endorsed or sponsored by Electronic Arts, Origin Systems or GOG. It includes no game data: you need your own copy of BioForge.")
        return out
    }
}
