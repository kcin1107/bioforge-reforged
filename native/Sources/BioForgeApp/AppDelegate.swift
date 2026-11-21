// App shell: window + menu bar (HIG: standard App/File/View/Window/Help menus, Cmd shortcuts, full screen, window title).
// Game data is never bundled: the folder comes from BIOFORGE_DATA, else the path remembered in UserDefaults, else
// File > Open Game Folder... (the app is unsandboxed, so a plain path is enough). Picking a folder above the game folder (a GOG
// install's top folder, or its app folder) finds the game folder inside. A remembered folder that has gone, a wrong pick and data
// that can't be read are explained in the window or an alert sheet.
// Keys: BioForge > Settings... (ControlsWindow) remaps them; KeyBindings turns Mac key codes into the original's scan codes and
// Shift / Ctrl / Alt flags. The game pauses while the app is in the background or the window is minimized.
// Stage 3b: the app runs the game. "New Game" boots the original opening (GameSession.newGame: TITLE, block GAME, the LOADLEVEL
// chain to the CHAOS wake-up) at 30 Hz; every tick the World is drawn through its current camera by the software compositor and
// presented by Metal. Keys go through the recovered mapping (Keys): arrows/Home/End/PgUp/PgDn/keypad, Shift run, C combat, Space use;
// Fn+Left/Right/Up/Down arrive as Home/End/PgUp/PgDn. The camera viewer of stages 1-2 (every ROOMS camera with its level's
// animated figures, Left/Right arrows switch cameras) stays available under Debug > Camera Viewer.
// Stage 4: sound effects and XMIDI music play live through SoundOutput; Game > Mute (Option-Cmd-M). Game > Music Device picks
// General MIDI or AdLib (the original's choice comes from INSTALL.OPT's MusicCardId; the player's pick is kept in UserDefaults).
// Game > Language switches speech and text between English, German and French (INSTALL.OPT's language= seeds it; kept in UserDefaults).
// Saves: the options dialog's Save / Load write and read ~/Library/Application Support/BioForge/Saves/GAME<n>.IM1 (the DOS game's own
// container, so files can be copied to and from it); BIOFORGE_LOAD=<GAMEn.IM1 or GAMEDAT folder> boots a save directly (debug aid).
// Rolling autosave (Autosave.swift): a save per level change in ~/Library/Application Support/BioForge/Autosaves, File > Open Autosave….
// Debug aids: BIOFORGE_CRASH_AFTER=<seconds> traps (fatalError) that many seconds into a game, to try the crash report offer
// (BugReport.swift) with the log's "quit" line missing. BIOFORGE_SHOT=<file.png> with BIOFORGE_SHOT_AFTER=<seconds> (default 5) writes
// Debug > Save Frame as PNG's picture that many seconds into a game and quits (screenshots for the website, with BIOFORGE_LOAD);
// BIOFORGE_SHOT_KEYS=<hex PC scan codes, comma-separated> presses those keys 4 seconds before (18 = O for the options dialog, 24 = J).
// Stage 5: the player-facing frame draws subtitles or a running PIMM monitor; pointer events map through the game image rectangle.
// Debug > Show Editor Mouse Cursor draws the MOUSE.SHP arrow at the pointer over every screen, as BIOFORGE.EXE -e does (normal play
// never shows it).
import AppKit
import OSLog
import QuartzCore
import BioForgeCore
import BioForgeHost

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuItemValidation {
    static let defaultsKey = "GameFolderPath", mutedKey = "Muted", aspectKey = "CorrectAspect", highResKey = "HighResolutionArt", artScaleKey = "ArtScale", readableKey = "ReadableText", artOfferedKey = "ArtOffered", dataNoticeKey = "DataNoticeShown"
    static let padBindingsKey = "PadBindings"
    var window: NSWindow!
    private let view = FramebufferView()
    private let emptyState = NSStackView()
    private let emptyProblem = NSTextField(wrappingLabelWithString: "")
    private let input = InputRouter()           // where keys, the controller and the pointer go (BioForgeHost)
    private let gamepad = GamepadInput()
    private var controlsWindow: ControlsWindowController?
    private var helpWindow: HelpWindowController?
    var suspended = false                    // in the background or minimized: no ticks, no sound
    var game: GameFolder?
    var dataReport: GameDataReport?                  // GameData.check of the open folder, for the bug report
    private var cams: [String] = []          // ROOMS/*.CAM file names
    private var current = 0
    private var framebuffer = Framebuffer()
    private var levels: LevelIndex?
    private var assets: [String: FigureAssets] = [:]      // figure types loaded so far
    private var stages: [String: Stage] = [:]             // per level
    private var room: (compositor: Compositor, camera: Camera?, stage: Stage?)?
    private var link: CADisplayLink?
    private var animTime = 0.0, lastStamp = 0.0, paused = false
    private let pauseItem = NSMenuItem(title: "Pause Animation", action: #selector(togglePause), keyEquivalent: " ")
    private static let tickRate = 30.0
    private enum Mode { case game, viewer }
    private var mode = Mode.game
    private var resources: GameResources?
    var session: GameSession? {
        get { host.session }
        set { host.session = newValue }
    }
    /// Audio levels, gamma and subtitles: INSTALL.OPT of the game folder, then what the player changed (UserDefaults wins).
    var settings = Settings()
    private var titleCamera: String?, loggedKeys = 0
    private var showTick = ProcessInfo.processInfo.environment["BIOFORGE_TICK_TITLE"] != nil      // development: tick in the title
    private let viewerItem = NSMenuItem(title: "Camera Viewer", action: #selector(showCameraViewer), keyEquivalent: "v")
    private let tickItem = NSMenuItem(title: "Show Tick in Title", action: #selector(toggleTickTitle), keyEquivalent: "")
    private let godItem = NSMenuItem(title: "God Mode", action: #selector(toggleGodMode), keyEquivalent: "")
    private let editorCursorItem = NSMenuItem(title: "Show Editor Mouse Cursor", action: #selector(toggleEditorCursor), keyEquivalent: "")
    private var mouseShapes: MouseShapes?
    private var lastMouse: NSPoint?                 // the mouse position syncPointer last handed the game
    private var macPointerHidden = false            // NSCursor.hide() is counted: one hide per unhide
    private let audio = SoundOutput()
    /// The running game and its tick loop (BioForgeHost); this class is its platform.
    private lazy var host = GameHost(input: input, audio: audio, playLog: playLog, autosaves: Self.hostPaths.autosaves, log: OSLogHostLog())
    private let muteItem = NSMenuItem(title: "Mute", action: #selector(toggleMute), keyEquivalent: "m")
    private let gmItem = NSMenuItem(title: "General MIDI", action: #selector(chooseMusicDevice(_:)), keyEquivalent: "")
    private let adlibItem = NSMenuItem(title: "AdLib", action: #selector(chooseMusicDevice(_:)), keyEquivalent: "")
    private let languageItems = [("E", "English"), ("G", "Deutsch"), ("F", "Français")].map { code, title in
        let item = NSMenuItem(title: title, action: #selector(chooseLanguage(_:)), keyEquivalent: ""); item.representedObject = code; return item
    }
    private let keyLog = Logger(subsystem: "BioForge", category: "keys")
    private let gameLog = Logger(subsystem: "BioForge", category: "game")
    /// ~/Library/Logs/BioForge/BioForge.log; Help > Report a Bug packs its tail with a save (BugReport.swift).
    /// Where saves, autosaves, art packs, logs and reports live.
    static let hostPaths = HostPaths.macOS
    let playLog = PlayLog(file: hostPaths.logFile)
    private let aspectItem = NSMenuItem(title: "Correct Aspect Ratio", action: #selector(toggleAspect), keyEquivalent: "")
    private let readableItem = NSMenuItem(title: "Readable Text", action: #selector(toggleReadableText), keyEquivalent: "")
    private let artItems = [(0, "Off"), (2, "2x"), (4, "4x")].map { scale, title in
        let item = NSMenuItem(title: title, action: #selector(chooseArtScale(_:)), keyEquivalent: ""); item.tag = scale; return item
    }
    private let buildStatusItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let stopBuildItem = NSMenuItem(title: "Stop Building", action: #selector(stopBuilding), keyEquivalent: "")
    /// The art packs are built here: BIOFORGE_HD_PACK, else ~/Library/Application Support/BioForge/HD, one folder per scale.
    private static let hiResBase = ProcessInfo.processInfo.environment["BIOFORGE_HD_PACK"].map { URL(fileURLWithPath: $0) } ?? hostPaths.hiRes
    private let hiResPacks = [2, 4].map { HiResPack(root: hiResBase.appendingPathComponent("\($0)x"), scale: $0) }
    private var build: (scale: Int, cancel: CancelFlag)?
    private let showBuildItem = NSMenuItem(title: "Show Build Progress", action: #selector(showBuildSheet), keyEquivalent: "")
    /// The build progress sheet (an alert with a bar) while it is up: the game waits behind it, like behind Settings.
    private var buildSheet: (alert: NSAlert, bar: NSProgressIndicator, label: NSTextField)?
    private var buildSheetOpen = false
    private var preparing = false                    // the build is loading the model (about 2 minutes the first time)
    private var buildPercent = 0

    func applicationDidFinishLaunching(_ note: Notification) {
        host.platform = self
        playLog.note("BioForge \(Self.buildStamp)")
        if playLog.previousEndedUnexpectedly { keepCrashedRecording() }
        Self.migrateHiResPack()
        input.setBindings(BindingsMigration.load(UserDefaults.standard), world: nil)
        if let saved = UserDefaults.standard.dictionary(forKey: Self.padBindingsKey) as? [String: String] {
            input.setPadBindings(PadBindings(propertyList: saved), world: nil)
        }
        input.onPlayKeyDown = { [weak self] in MainActor.assumeIsolated { self?.logNewKeys() } }      // the router runs on the main thread here
        input.onOptionsAction = { [weak self] in MainActor.assumeIsolated { self?.quitIfRequested() } }
        gamepad.onEvent = { [weak self] in self?.handlePad($0) }
        gamepad.onStick = { [weak self] in self?.movePointerWithPad($0, $1) }
        gamepad.start()
        buildMenu()
        buildWindow()
        let savedPath = UserDefaults.standard.string(forKey: Self.defaultsKey)
        if let g = GameFolder.fromEnvironment() ?? savedPath.map({ GameFolder(URL(fileURLWithPath: $0)) }), g.isValid { open(g) }
        else if let savedPath {
            showEmptyState(problem: HostText.folderGone(path: savedPath))
        } else { showEmptyState() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate()
        if playLog.previousEndedUnexpectedly { DispatchQueue.main.async { [self] in offerCrashReport() } }      // after open()'s own async start of the game
    }

    func applicationWillTerminate(_ note: Notification) { playLog.quit() }

    func applicationDidResignActive(_ note: Notification) { setSuspended(true) }
    func applicationDidBecomeActive(_ note: Notification) { updateSuspended() }
    func windowDidMiniaturize(_ note: Notification) { setSuspended(true) }
    func windowDidDeminiaturize(_ note: Notification) { updateSuspended() }

    /// The Settings window is open: the game waits behind it, as in the background (a remap while Lex walks into a fight helps nobody).
    private var settingsOpen = false
    /// The Report a Bug sheet is up (BugReport.swift).
    var reportOpen = false

    func updateSuspended() { setSuspended(!NSApp.isActive || window.isMiniaturized || settingsOpen || reportOpen || buildSheetOpen) }

    /// Stop the clock and the sound while nobody is looking; the game carries on where it was (HIG: games pause in the background).
    func setSuspended(_ s: Bool) {
        guard s != suspended else { return }
        suspended = s
        host.setSuspended(s, inGame: mode == .game)
        link?.isPaused = s || paused
        lastStamp = 0
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    // MARK: window

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 720),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.collectionBehavior = [.fullScreenPrimary]
        if UserDefaults.standard.object(forKey: Self.aspectKey) != nil { view.correctAspect = UserDefaults.standard.bool(forKey: Self.aspectKey) }
        updateWindowAspect()
        window.delegate = self
        view.onKey = { [weak self] in self?.handleKey($0) }
        view.onPointer = { [weak self] x, y, phase in self?.handlePointer(x: x, y: y, phase: phase) }
        window.acceptsMouseMovedEvents = true
        window.center()
        window.setFrameAutosaveName("MainWindow")

        let label = NSTextField(labelWithString: "Choose your BioForge game folder")
        label.font = .preferredFont(forTextStyle: .title2)
        let hint = NSTextField(labelWithString: "The folder that contains BIOFORGE.EXE and ROOMS. Game data is never bundled with the app.")
        hint.textColor = .secondaryLabelColor
        emptyProblem.alignment = .center
        emptyProblem.preferredMaxLayoutWidth = 520
        emptyProblem.isHidden = true
        let button = NSButton(title: "Open Game Folder…", target: self, action: #selector(openGameFolder))
        button.bezelStyle = .rounded
        button.keyEquivalent = "\r"
        emptyState.orientation = .vertical
        emptyState.spacing = 12
        emptyState.setViews([label, hint, emptyProblem, button], in: .center)
        emptyState.translatesAutoresizingMaskIntoConstraints = false

        let container = NSView()
        view.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(view)
        container.addSubview(emptyState)
        NSLayoutConstraint.activate([
            view.leadingAnchor.constraint(equalTo: container.leadingAnchor), view.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            view.topAnchor.constraint(equalTo: container.topAnchor), view.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            emptyState.centerXAnchor.constraint(equalTo: container.centerXAnchor), emptyState.centerYAnchor.constraint(equalTo: container.centerYAnchor),
        ])
        window.contentView = container
        window.title = "BioForge"
    }

    private func showEmptyState(problem: String? = nil) {
        emptyProblem.stringValue = problem ?? ""
        emptyProblem.isHidden = problem == nil
        emptyState.isHidden = false
        view.isHidden = true
        window.title = "BioForge"
    }

    // MARK: menu

    private func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let item = NSMenuItem(); main.addItem(item)
            let menu = NSMenu(title: title); item.submenu = menu
            items.forEach(menu.addItem)
            return menu
        }
        func item(_ title: String, _ action: Selector?, _ key: String = "", _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        let name = "BioForge"
        _ = add(name, [
            { let a = item("About \(name)", #selector(showAbout)); a.target = self; return a }(), .separator(),
            { let s = item("Settings…", #selector(showSettings), ","); s.target = self; return s }(), .separator(),
            item("Hide \(name)", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:))), .separator(),
            item("Quit \(name)", #selector(NSApplication.terminate(_:)), "q"),
        ])
        let open = item("Open Game Folder…", #selector(openGameFolder), "o"); open.target = self
        let autosave = item("Open Autosave…", #selector(openAutosave)); autosave.target = self
        _ = add("File", [open, autosave, .separator(), item("Close Window", #selector(NSWindow.performClose(_:)), "w")])
        let new = item("New Game", #selector(newGame), "n"); new.target = self
        muteItem.target = self
        muteItem.keyEquivalentModifierMask = [.command, .option]
        audio.muted = UserDefaults.standard.bool(forKey: Self.mutedKey)
        muteItem.state = audio.muted ? .on : .off
        let deviceItem = NSMenuItem(title: "Music Device", action: nil, keyEquivalent: "")
        deviceItem.submenu = NSMenu(title: "Music Device")
        for d in [gmItem, adlibItem] { d.target = self; deviceItem.submenu?.addItem(d) }
        let languageMenuItem = NSMenuItem(title: "Language", action: nil, keyEquivalent: "")
        languageMenuItem.submenu = NSMenu(title: "Language")
        for l in languageItems { l.target = self; languageMenuItem.submenu?.addItem(l) }
        _ = add("Game", [new, .separator(), muteItem, deviceItem, languageMenuItem])

        aspectItem.target = self
        aspectItem.state = view.correctAspect ? .on : .off
        readableItem.target = self
        readableItem.state = readableText ? .on : .off
        let defaults = UserDefaults.standard
        view.artScale = defaults.object(forKey: Self.artScaleKey) as? Int ?? (defaults.bool(forKey: Self.highResKey) || ProcessInfo.processInfo.environment["BIOFORGE_HD"] != nil ? 2 : 0)
        let artItem = NSMenuItem(title: "High-Resolution Art", action: nil, keyEquivalent: "")
        artItem.submenu = NSMenu(title: "High-Resolution Art")
        for i in artItems { i.target = self; artItem.submenu?.addItem(i) }
        stopBuildItem.target = self
        showBuildItem.target = self
        for i in [buildStatusItem, showBuildItem, stopBuildItem] { i.isHidden = true; artItem.submenu?.addItem(i) }
        updateArtItems()
        let left = String(UnicodeScalar(NSLeftArrowFunctionKey)!), right = String(UnicodeScalar(NSRightArrowFunctionKey)!)
        let prev = item("Previous Camera", #selector(previousCamera), left, []); prev.target = self
        let next = item("Next Camera", #selector(nextCamera), right, []); next.target = self
        pauseItem.target = self
        pauseItem.keyEquivalentModifierMask = []
        _ = add("View", [aspectItem, artItem, readableItem, pauseItem, .separator(), prev, next, .separator(),
                         item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control])])

        viewerItem.target = self
        viewerItem.keyEquivalentModifierMask = [.command, .option]
        tickItem.target = self
        tickItem.state = showTick ? .on : .off
        editorCursorItem.target = self
        godItem.target = self
        let refill = item("Refill Health", #selector(refillHealth)); refill.target = self
        let openSave = item("Open Save File…", #selector(openSaveFile)); openSave.target = self
        let saveFrame = item("Save Frame as PNG…", #selector(saveFrame)); saveFrame.target = self
        _ = add("Debug", [viewerItem, tickItem, editorCursorItem, .separator(), godItem, refill, openSave, .separator(), saveFrame])

        NSApp.windowsMenu = add("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))), .separator(),
            item("Bring All to Front", #selector(NSApplication.arrangeInFront(_:))),
        ])
        let help = item("\(name) Help", #selector(showHelp), "?"); help.target = self
        let keys = item("Keyboard Controls…", #selector(showSettings)); keys.target = self
        let report = item("Report a Bug…", #selector(reportBug)); report.target = self
        NSApp.helpMenu = add("Help", [help, .separator(), keys, report])
        NSApp.mainMenu = main
    }

    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        switch item.action {
        case #selector(previousCamera), #selector(nextCamera): return mode == .viewer && cams.count > 1
        case #selector(togglePause): return mode == .viewer          // in the game Space is the Use key
        case #selector(newGame), #selector(openSaveFile): return resources != nil
        case #selector(toggleGodMode), #selector(refillHealth): return mode == .game && session != nil
        case #selector(showCameraViewer): return game != nil
        default: return true
        }
    }

    // MARK: actions

    @objc private func openGameFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.prompt = "Choose"
        panel.message = "Choose your BioForge game folder, the one that contains BIOFORGE.EXE and ROOMS."
        panel.beginSheetModal(for: window) { [self] response in
            guard response == .OK, let url = panel.url else { return }
            guard let g = GameFolder.find(in: url) else {
                let text = HostText.notAGameFolder(name: url.lastPathComponent)
                showAlert(text.message, text.info)
                return
            }
            UserDefaults.standard.set(g.url.path, forKey: Self.defaultsKey)
            open(g)
        }
    }

    /// A save or load from the options dialog failed: say so (the dialog itself shows nothing, so a failed save looked like a good one).
    func reportFileError(_ w: World) {
        guard let e = w.takeFileError() else { return }
        let text = HostText.fileError(load: e.load, slot: e.slot, reason: e.reason)
        showAlert(text.message, text.info)
    }

    /// A warning sheet on the game window (HIG: say what happened and what to do, with one OK button).
    func showAlert(_ message: String, _ info: String) {
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = message
        a.informativeText = info
        if let window, window.attachedSheet == nil { a.beginSheetModal(for: window) } else { a.runModal() }
    }

    @objc private func showSettings() {
        if controlsWindow == nil {
            controlsWindow = ControlsWindowController(bindings: input.bindings, padBindings: input.padBindings, gamepad: gamepad, onChange: { [weak self] b in
                guard let self else { return }
                input.setBindings(b, world: session?.world)
                UserDefaults.standard.set(b.propertyList, forKey: BindingsMigration.key)
            }, onPadChange: { [weak self] b in
                guard let self else { return }
                input.setPadBindings(b, world: session?.world)
                UserDefaults.standard.set(b.propertyList, forKey: Self.padBindingsKey)
            })
            NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: controlsWindow?.window, queue: .main) { [weak self] _ in
                self?.settingsOpen = false
                self?.updateSuspended()
            }
        }
        settingsOpen = true
        updateSuspended()
        controlsWindow?.showWindow(nil)
    }

    @objc private func showHelp() {
        if helpWindow == nil { helpWindow = HelpWindowController() }
        helpWindow?.show(bindings: input.bindings)
    }

    @objc private func toggleMute() {
        audio.muted.toggle()
        muteItem.state = audio.muted ? .on : .off
        UserDefaults.standard.set(audio.muted, forKey: Self.mutedKey)
    }

    @objc private func chooseMusicDevice(_ sender: NSMenuItem) {
        settings.musicDevice = sender === adlibItem ? .adlib : .generalMIDI
        settings.persist()
        updateMusicDeviceItems()
        audio.setMusicDevice(settings.musicDevice, world: session?.world)
    }

    private func updateMusicDeviceItems() {
        gmItem.state = settings.musicDevice == .generalMIDI ? .on : .off
        adlibItem.state = settings.musicDevice == .adlib ? .on : .off
    }

    /// Speech and text together, like the original's `language=`; the intro movie follows on the next new game.
    @objc private func chooseLanguage(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String else { return }
        if let w = session?.world { w.setLanguage(code) } else { settings.language = code; settings.persist() }
        playLog.note("language \(code)")
        updateLanguageItems()
    }

    private func updateLanguageItems() {
        for l in languageItems { l.state = (l.representedObject as? String) == settings.language ? .on : .off }
    }

    @objc private func chooseArtScale(_ sender: NSMenuItem) {
        setArtScale(sender.tag)
        if sender.tag != 0 { offerBuild(scale: sender.tag) }
    }

    private func setArtScale(_ scale: Int) {
        view.artScale = scale
        UserDefaults.standard.set(scale, forKey: Self.artScaleKey)
        updateArtItems()
        redrawGame()
    }

    /// Once per Mac, after a game has started: the art is the biggest thing the app can do, so say so (HIG: onboarding offers, then gets out of the way).
    private func offerArtBuild() {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: Self.artOfferedKey) == nil, Self.modelURL != nil, build == nil, game != nil, !playLog.previousEndedUnexpectedly,
              ProcessInfo.processInfo.environment["BIOFORGE_NO_ART_OFFER"] == nil, window.attachedSheet == nil,
              ![2, 4].contains(where: { PixelPackBuilder.isComplete(root: hiResRoot($0)) }) else { return }
        defaults.set(true, forKey: Self.artOfferedKey)
        let a = NSAlert()
        a.messageText = "Build high-resolution art?"
        a.informativeText = "BioForge can repaint the rooms and characters at 2x or 4x on this Mac from your game files, keeping the original pixel-art look. It takes about 12 minutes on an Apple M4 Pro (longer on older Macs, plus about 2 minutes the first time to prepare) and about 115 MB (2x) or 300 MB (4x). You can play while it builds; rooms switch to the new art as they’re ready. You can also do this later in View > High-Resolution Art."
        a.addButton(withTitle: "Build 2x")
        a.addButton(withTitle: "Build 4x")
        a.addButton(withTitle: "Not Now")
        a.beginSheetModal(for: window) { [self] r in
            guard r == .alertFirstButtonReturn || r == .alertSecondButtonReturn else { return }
            let scale = r == .alertFirstButtonReturn ? 2 : 4
            setArtScale(scale)
            startBuild(scale: scale)
        }
    }

    private func updateArtItems() {
        for i in artItems { i.state = i.tag == view.artScale ? .on : .off }
    }

    private func hiResRoot(_ scale: Int) -> URL { Self.hiResBase.appendingPathComponent("\(scale)x") }

    /// Packs made before there were two scales sat directly in the base folder: they are the 2x pack.
    private static func migrateHiResPack() {
        let fm = FileManager.default, two = hiResBase.appendingPathComponent("2x")
        guard !fm.fileExists(atPath: two.path) else { return }
        let old = ["rooms", "tex"].map { hiResBase.appendingPathComponent($0) }.filter { fm.fileExists(atPath: $0.path) }
        guard !old.isEmpty, (try? fm.createDirectory(at: two, withIntermediateDirectories: true)) != nil else { return }
        for url in old { try? fm.moveItem(at: url, to: two.appendingPathComponent(url.lastPathComponent)) }
    }

    /// The model: inside the app bundle, or BIOFORGE_HD_MODEL (a path) for `swift run`.
    private static var modelURL: URL? {
        ProcessInfo.processInfo.environment["BIOFORGE_HD_MODEL"].map { URL(fileURLWithPath: $0) }
            ?? Bundle.main.url(forResource: "HDCube", withExtension: "mlmodelc")
    }

    /// Asks before the long first build (HIG: say what will happen and let the player decide); the scale is already in use either way.
    private func offerBuild(scale: Int) {
        guard build == nil, game != nil, !PixelPackBuilder.isComplete(root: hiResRoot(scale)) else { return }
        let a = NSAlert()
        if Self.modelURL == nil {
            a.messageText = "This copy of BioForge can’t build \(scale)x art."
            a.informativeText = "This build was made without the art model (README “High-resolution art”). Rooms you haven’t built art for appear enlarged from the original."
            a.addButton(withTitle: "OK")
        } else if FileManager.default.fileExists(atPath: hiResRoot(scale).appendingPathComponent("complete").path) {
            // Finished by an older version of the builder.
            a.messageText = "Update the \(scale)x art?"
            a.informativeText = "This version of BioForge makes smoother edges and adds monitor art. It rebuilds the \(scale)x art on this Mac in about 10 minutes; you can keep playing while it builds."
            a.addButton(withTitle: "Build")
            a.addButton(withTitle: "Not Now")
        } else {
            a.messageText = "Build \(scale)x art?"
            a.informativeText = "The art is made on this Mac from your game files. You can keep playing while it builds, and rooms switch to the new art as they’re ready. It takes about 12 minutes on an Apple M4 Pro, longer on older Macs, and about \(scale == 2 ? 115 : 300) MB of disk space."
            a.addButton(withTitle: "Build")
            a.addButton(withTitle: "Not Now")
        }
        let respond: (NSApplication.ModalResponse) -> Void = { [self] r in if r == .alertFirstButtonReturn { startBuild(scale: scale) } }
        if let window, window.attachedSheet == nil { a.beginSheetModal(for: window, completionHandler: respond) } else { respond(a.runModal()) }
    }

    /// Builds on a utility-priority thread; the room and progress callbacks hop to the main thread, and Stop Building flips the flag it polls.
    private func startBuild(scale: Int) {
        guard build == nil, let game, let url = Self.modelURL else { return }
        let cancel = CancelFlag(), pack = hiResPacks[scale / 2 - 1], root = hiResRoot(scale), first = session?.world.level
        build = (scale, cancel)
        preparing = true
        playLog.note("art build \(scale)x started")
        showBuildProgress(0)
        DispatchQueue.main.async { [self] in showBuildSheet() }      // after the alert that started it has left the window
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var failure: Error?
            do {
                let started = Date()
                let upscaler = try CoreMLUpscaler(modelURL: url)
                DispatchQueue.main.async { MainActor.assumeIsolated {
                    guard let self else { return }
                    self.preparing = false
                    self.playLog.note("art build \(scale)x: model ready after \(Int(Date().timeIntervalSince(started))) s")
                    self.showBuildProgress(self.buildPercent)
                } }
                let builder = PixelPackBuilder(game: game, root: root, factor: scale, upscaler: upscaler, firstLevel: first)
                var percent = -1
                try builder.run(isCancelled: { cancel.isSet }, progress: { p in
                    guard Int(p * 100) != percent else { return }
                    percent = Int(p * 100)
                    let shown = percent
                    DispatchQueue.main.async { MainActor.assumeIsolated { self?.showBuildProgress(shown) } }
                }, roomDone: { room in DispatchQueue.main.async { pack.forget(room: room) } },
                               monitorDone: { monitor in DispatchQueue.main.async { pack.forget(monitor: monitor) } })
            } catch { failure = error }
            let error = failure
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.buildFinished(scale: scale, error: error) } }
        }
    }

    private func showBuildProgress(_ percent: Int) {
        guard let build else { return }
        buildStatusItem.title = preparing ? "Preparing \(build.scale)x Art…" : "Building \(build.scale)x Art… \(percent)%"
        buildStatusItem.isHidden = false
        showBuildItem.isHidden = false
        stopBuildItem.isHidden = false
        buildPercent = percent
        buildSheet?.bar.isIndeterminate = preparing
        if preparing { buildSheet?.bar.startAnimation(nil) } else { buildSheet?.bar.stopAnimation(nil) }
        buildSheet?.bar.doubleValue = Double(percent)
        buildSheet?.label.stringValue = buildDetail
        buildSheet?.alert.messageText = preparing ? "Preparing \(build.scale)x Art" : "Building \(build.scale)x Art"
    }

    /// The line under the sheet's bar. Preparing says what's happening and how long it takes, so the wait doesn't look like a hang.
    private var buildDetail: String {
        preparing ? "Getting the Neural Engine ready for upscaling. This takes about 2 minutes, only the first time." : "\(buildPercent)%"
    }

    /// The build's progress; the game waits behind it, as behind Settings. Play Now closes it and the build carries on.
    @objc private func showBuildSheet() {
        guard let build, buildSheet == nil, window.attachedSheet == nil else { return }
        let a = NSAlert()
        a.messageText = preparing ? "Preparing \(build.scale)x Art" : "Building \(build.scale)x Art"
        a.informativeText = "The art is made on this Mac’s Neural Engine, so the game stays smooth while it builds. Play now and it carries on in the background; rooms switch to the new art as they’re ready."
        a.addButton(withTitle: "Play Now")
        // NSAlert places the accessory 4 pt left of its text and as wide as the text plus 8, so a 4 pt inset lines the bar up with the text.
        let bar = NSProgressIndicator(frame: NSRect(x: 4, y: 32, width: 312, height: 20))
        let label = NSTextField(wrappingLabelWithString: buildDetail)
        label.frame = NSRect(x: 4, y: 0, width: 312, height: 28)
        label.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        label.textColor = .secondaryLabelColor
        bar.isIndeterminate = preparing
        if preparing { bar.startAnimation(nil) }
        bar.minValue = 0; bar.maxValue = 100; bar.doubleValue = Double(buildPercent)
        let box = NSView(frame: NSRect(x: 0, y: 0, width: 320, height: 52))
        box.addSubview(bar)
        box.addSubview(label)
        a.accessoryView = box
        buildSheet = (a, bar, label)
        buildSheetOpen = true
        updateSuspended()
        a.beginSheetModal(for: window) { [self] _ in
            buildSheet = nil
            buildSheetOpen = false
            updateSuspended()
        }
    }

    private func buildFinished(scale: Int, error: Error?) {
        let stopped = build?.cancel.isSet ?? false
        build = nil
        preparing = false
        buildStatusItem.isHidden = true
        showBuildItem.isHidden = true
        stopBuildItem.isHidden = true
        if let sheet = buildSheet { window.endSheet(sheet.alert.window) }
        if let error { playLog.note("art build \(scale)x failed: \(error.localizedDescription)") }
        else if stopped { playLog.note("art build \(scale)x stopped at \(buildPercent)%") }
        else { playLog.note("art build \(scale)x finished") }
        if let error { showAlert("Couldn’t build \(scale)x art.", error.localizedDescription) }
    }

    @objc private func stopBuilding() { build?.cancel.set() }

    private var readableText: Bool { UserDefaults.standard.bool(forKey: Self.readableKey) }

    @objc private func toggleReadableText() {
        UserDefaults.standard.set(!readableText, forKey: Self.readableKey)
        readableItem.state = readableText ? .on : .off
        session?.world.readableText = readableText
    }

    @objc private func toggleAspect() {
        view.correctAspect.toggle()
        aspectItem.state = view.correctAspect ? .on : .off
        UserDefaults.standard.set(view.correctAspect, forKey: Self.aspectKey)
        updateWindowAspect()
    }

    /// The window keeps the picture's shape: 4:3 with the CRT's tall pixels, else 320:200.
    private func updateWindowAspect() {
        let size = view.correctAspect ? NSSize(width: 4, height: 3) : NSSize(width: 16, height: 10)
        window.contentAspectRatio = size
        window.contentMinSize = NSSize(width: 640, height: 640 * size.height / size.width)
        guard !window.styleMask.contains(.fullScreen) else { return }
        var frame = window.contentRect(forFrameRect: window.frame)
        let height = frame.width * size.height / size.width
        frame.origin.y += frame.height - height
        frame.size.height = height
        window.setFrame(window.frameRect(forContentRect: frame), display: true)
    }

    @objc private func togglePause() {
        paused.toggle()
        pauseItem.title = paused ? "Resume Animation" : "Pause Animation"
        link?.isPaused = paused
        lastStamp = 0
    }

    @objc private func previousCamera() { step(-1) }
    @objc private func nextCamera() { step(1) }

    private func step(_ d: Int) {
        guard !cams.isEmpty else { return }
        current = (current + d + cams.count) % cams.count
        showCurrent()
    }

    // MARK: game

    private func open(_ g: GameFolder) {
        let report = GameData.check(g)
        playLog.note(report.summary)
        guard report.missing.isEmpty else {
            if game == nil { showEmptyState(problem: HostText.incompleteEmptyState(folder: g.url.lastPathComponent, missing: report.missing)) }
            else { let text = HostText.incompleteAlert(folder: g.url.lastPathComponent, missing: report.missing); showAlert(text.message, text.info) }
            return
        }
        dataReport = report
        game = g
        cams = g.list("ROOMS", ext: "CAM")
        levels = try? LevelIndex(game: g)
        assets = [:]; stages = [:]
        settings = Settings.load(game: g)
        mouseShapes = try? MouseShapes(g.read("DATA/MOUSE.SHP"))
        settings.apply(defaults: UserDefaults.standard)
        settings.onChange = { [weak settings] in settings?.save(to: UserDefaults.standard) }
        updateMusicDeviceItems()
        updateLanguageItems()
        // BIOFORGE_CAMERA=CE33 starts on that camera (development convenience, like BIOFORGE_DATA).
        let start = ProcessInfo.processInfo.environment["BIOFORGE_CAMERA"]?.uppercased()
        current = cams.firstIndex { ($0 as NSString).deletingPathExtension.uppercased() == start } ?? 0
        emptyState.isHidden = true
        view.isHidden = false
        resources = nil; session = nil
        window.title = "BioForge — Loading…"
        // The script library takes a moment to decode; let the window appear first. BIOFORGE_CAMERA starts the camera viewer.
        DispatchQueue.main.async { [self] in
            do { resources = try GameResources(game: g) } catch {
                gameLog.error("game data: \(String(describing: error), privacy: .public)")
                if start == nil {
                    showEmptyState(problem: HostText.unreadableData(folder: g.url.lastPathComponent))
                    let text = HostText.unreadableAlert(error: error.localizedDescription, folderPath: g.url.path)
                    showAlert(text.message, text.info)
                    return
                }
            }
            if start != nil || resources == nil { showCameraViewer() }
            else if let path = ProcessInfo.processInfo.environment["BIOFORGE_LOAD"], !path.isEmpty { loadSave(at: URL(fileURLWithPath: path)) }
            else { newGame() }
            offerUnknownDataNotice(report, folder: g)
        }
    }

    /// Files that differ from the GOG release the port was tested with: the game runs anyway, so say so once per folder and file list (HIG "Alerts").
    private func offerUnknownDataNotice(_ report: GameDataReport, folder g: GameFolder) {
        guard !report.unknown.isEmpty else { return }
        let fingerprint = HostText.unknownDataFingerprint(folderPath: g.url.path, unknown: report.unknown)
        guard UserDefaults.standard.string(forKey: Self.dataNoticeKey) != fingerprint else { return }
        UserDefaults.standard.set(fingerprint, forKey: Self.dataNoticeKey)
        let text = HostText.unknownDataNotice(unknown: report.unknown)
        reportOpen = true
        updateSuspended()
        let a = NSAlert()
        a.messageText = text.message
        a.informativeText = text.info
        a.addButton(withTitle: "OK")
        a.beginSheetModal(for: window) { [self] _ in
            reportOpen = false
            updateSuspended()
        }
    }

    // MARK: new game

    @objc private func newGame() {
        guard let resources else { NSSound.beep(); return }
        do { start(try GameSession.newGame(resources: resources)) } catch {
            gameLog.error("new game: \(String(describing: error), privacy: .public)")
            showAlert("A new game couldn’t be started.", error.localizedDescription)
        }
    }

    /// Where the options dialog saves and loads (created on demand).
    private var savesDirectory: URL? {
        let dir = Self.hostPaths.saves
        do { try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) } catch { return nil }
        return dir
    }

    /// BIOFORGE_LOAD: boot a native save, a GAMEn.IM1 container (unpacked next to the saves) or a play directory such as GAMEDAT.
    func loadSave(at url: URL, fallBackToNewGame: Bool = true) {
        guard let resources else { return }
        do {
            var dir = url
            if !url.hasDirectoryPath, (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) != true {
                dir = (savesDirectory ?? FileManager.default.temporaryDirectory).deletingLastPathComponent()
                    .appendingPathComponent("Debug/\(url.deletingPathExtension().lastPathComponent).d", isDirectory: true)
                try Im1.unpack([UInt8](try Data(contentsOf: url)), to: dir)
            }
            start(try GameSession.fromNativeState(resources: resources, directory: dir))
            gameLog.info("loaded \(url.path, privacy: .public)")
        } catch {
            gameLog.error("BIOFORGE_LOAD \(url.path, privacy: .public): \(error.localizedDescription, privacy: .public)")
            if fallBackToNewGame { newGame() } else { showAlert("The save couldn’t be opened.", error.localizedDescription) }
        }
    }

    /// Make `s` the running game (a new game, a resumed save or a confirmed load dialog).
    private func start(_ s: GameSession) {
        guard let resources else { return }
        s.world.recordLog = false
        s.world.configureSettings(settings)
        s.world.savesDir = savesDirectory
        s.world.readableText = readableText
        s.autoDifficulty = false          // the player picks the difficulty in the options dialog
        s.world.recorder = try? SessionRecorder(directory: Self.hostPaths.sessions, session: s)      // the inputs, for an exact replay (Help > Report a Bug)
        session = s
        godItem.state = .off                             // tester aids start off in every game (World.godMode)
        s.world.autosavedLevel = s.world.level           // a level change is what autosaves, not the start
        if let shot = ProcessInfo.processInfo.environment["BIOFORGE_SHOT"], !shot.isEmpty {
            let after = ProcessInfo.processInfo.environment["BIOFORGE_SHOT_AFTER"].flatMap(Double.init) ?? 5
            let keys = (ProcessInfo.processInfo.environment["BIOFORGE_SHOT_KEYS"] ?? "").split(separator: ",").compactMap { Int($0, radix: 16) }
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0, after - 2)) { [weak self, weak s] in
                for k in keys { s?.world.keyDown(k, mods: 0); s?.world.keyUp(k, mods: 0) }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0, after - 1)) { [weak self] in
                self?.handlePointer(x: 319, y: 199, phase: .up)      // a release turns a monitor's pointer input on (MonitorScreen.inputEnabled),
                self?.handlePointer(x: 319, y: 199, phase: .move)    // then the hand pointer goes out of the way, to the bottom right corner
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + after) { [weak self] in
                if let png = self?.view.framePNG() { try? png.write(to: URL(fileURLWithPath: shot)) }
                NSApp.terminate(nil)
            }
        }
        if let after = ProcessInfo.processInfo.environment["BIOFORGE_CRASH_AFTER"].flatMap(Double.init) {
            DispatchQueue.main.asyncAfter(deadline: .now() + after) { [weak self, weak s] in
                if let s, self?.session === s { fatalError("BIOFORGE_CRASH_AFTER") }
            }
        }
        playLog.restart()
        playLog.note("game started: level \(s.world.level)")
        audio.newGame(game: resources.game, musicLevel: s.world.musicInitial, device: settings.musicDevice)
        mode = .game
        host.gameStarted(); titleCamera = nil; loggedKeys = 0
        viewerItem.state = .off
        pauseItem.title = "Pause Animation"
        paused = false
        view.onKey = { [weak self] in self?.handleKey($0) }
        window.makeFirstResponder(view)
        redrawGame()
        startAnimation()
        link?.isPaused = false
        lastStamp = 0
        DispatchQueue.main.async { [self] in offerArtBuild() }
    }

    /// A confirmed Load dialog leaves its session in `pendingLoad`: swap to it.
    private func swapIfPendingLoad() {
        if let p = session?.world.pendingLoad { start(p) }
    }

    @objc private func showCameraViewer() {
        mode = .viewer
        session = nil
        audio.setPaused(true)
        viewerItem.state = .on
        view.onKey = nil
        paused = false
        pauseItem.title = "Pause Animation"
        showCurrent()
        link?.isPaused = false
        lastStamp = 0
    }

    @objc private func toggleTickTitle() {
        showTick.toggle()
        tickItem.state = showTick ? .on : .off
        titleCamera = nil
        updateGameTitle()
    }

    /// Debug > God Mode: Lex takes no damage (World.setGodMode, recorded for replay); the report says so.
    @objc private func toggleGodMode() {
        guard let w = session?.world else { return }
        let on = !w.godMode
        w.setGodMode(on)
        godItem.state = on ? .on : .off
        playLog.note("debug: god mode \(on ? "on" : "off")")
    }

    /// Debug > Save Frame as PNG…: the picture as shown (art scale and aspect included), without the window, for screenshots.
    @objc private func saveFrame() {
        guard let png = view.framePNG(), let window else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.png]
        let level = session?.world.level ?? "BioForge"
        panel.nameFieldStringValue = "\(level) \(Date().formatted(.iso8601.year().month().day().time(includingFractionalSeconds: false).timeSeparator(.omitted))).png"
        panel.beginSheetModal(for: window) { answer in
            guard answer == .OK, let url = panel.url else { return }
            do { try png.write(to: url) } catch { NSAlert(error: error).beginSheetModal(for: window) }
        }
    }

    @objc private func refillHealth() {
        guard let w = session?.world else { return }
        w.refillHealth()
        playLog.note("debug: refill health")
    }

    @objc private func toggleEditorCursor() {
        editorCursorItem.state = editorCursorItem.state == .on ? .off : .on
        redrawGame()
    }

    /// Window title = current camera (HIG: the title names what the window shows); optionally the tick for debugging.
    private func updateGameTitle() {
        guard let w = session?.world else { return }
        let cam = w.monitorName ?? w.currentCamera ?? "—"
        let title = showTick ? "BioForge — \(cam) · tick \(session!.vm.tick)" : "BioForge — \(cam)"
        if window.title != title { window.title = title }
    }

    func redrawGame() {
        guard let s = session else { return }
        s.world.renderPresentation(into: &framebuffer)       // an open flic replaces the world here (World.render)
        if editorCursorItem.state == .on && !s.world.flicOpen {
            mouseShapes?.draw(MouseShapes.arrow, x: input.pointerPosition.x, y: input.pointerPosition.y, into: &framebuffer)
        }
        var shown = framebuffer
        // The arrow is drawn into the 320x200 picture, so with it on the picture stays that one.
        let artScale = editorCursorItem.state == .on ? 0 : view.fittingArtScale
        var hiRes = artScale != 0 ? s.world.hiResFrame(indexed: framebuffer, pack: hiResPacks[artScale / 2 - 1]) : nil
        s.world.applyPresentation(to: &shown, hiRes: &hiRes)  // RUMBLE, gamma, CHANGEPALETTE, FADE
        view.present(shown, hiRes: hiRes)
        updateGameTitle()
    }

    /// The pointer screens follow the real mouse, not only its moves: mouse-moved events reach the view only while the window is
    /// active and over the picture, so after entering the window, activating it or opening a screen the hand sat where the mouse
    /// last was. A position that hasn't changed since the last frame is left alone, so the controller can still move the pointer.
    /// The game draws its own hand there, so the Mac pointer is hidden while it is over the picture (it comes back outside it).
    private func syncPointer(_ w: World) {
        let warp = w.takeMouseWarp()
        guard window.isKeyWindow, InputRouter.padDrivesPointer(w) else { lastMouse = nil; hideMacPointer(false); return }
        var m = window.mouseLocationOutsideOfEventStream
        if let warp, view.gamePoint(window: m) != nil, let target = view.windowPoint(game: warp.x, warp.y) {
            m = warpMouse(to: target)                // the release put the DOS mouse on the hand (FUN_1250_0415): the hand doesn't jump
            lastMouse = m
        }
        let p = view.gamePoint(window: m)
        hideMacPointer(p != nil)
        guard m != lastMouse else { return }
        lastMouse = m
        if let p { input.handlePointer(x: p.0, y: p.1, phase: .move, world: w) }
    }

    /// Move the Mac mouse to a window point; -> that point.
    private func warpMouse(to point: NSPoint) -> NSPoint {
        let screen = window.convertPoint(toScreen: point)
        let top = NSScreen.screens.first?.frame.maxY ?? 0           // Quartz measures from the top of the main display
        CGWarpMouseCursorPosition(CGPoint(x: screen.x, y: top - screen.y))
        CGAssociateMouseAndMouseCursorPosition(1)                    // no quarter-second pause of the mouse after the move
        return point
    }

    private func hideMacPointer(_ hide: Bool) {
        guard hide != macPointerHidden else { return }
        macPointerHidden = hide
        if hide { NSCursor.hide() } else { NSCursor.unhide() }
    }

    /// Run, kicks and punches on Shift, Control or Option stay held only while macOS says that modifier is down (see InputRouter.dropReleasedModifiers).
    private func dropReleasedModifiers(_ w: World) {
        let flags = NSEvent.modifierFlags
        input.dropReleasedModifiers(down: [0xE1: flags.contains(.shift), 0xE5: flags.contains(.shift), 0xE0: flags.contains(.control),
                                           0xE4: flags.contains(.control), 0xE2: flags.contains(.option), 0xE6: flags.contains(.option)], world: w)
    }

    /// An NSEvent as the router's KeyEvent.
    private func handleKey(_ e: NSEvent) {
        let kind: KeyEvent.Kind = e.type == .keyDown ? .down : e.type == .keyUp ? .up : .modifiers
        let key = KeyEvent(usage: MacKeyCodes.usage(forKeyCode: e.keyCode) ?? 0, kind: kind, isRepeat: kind != .modifiers && e.isARepeat,      // isARepeat raises on flagsChanged
                           command: e.modifierFlags.contains(.command),
                           modifierDown: MacKeys.deviceBits[e.keyCode].map { e.modifierFlags.rawValue & $0 != 0 })
        if e.type == .keyDown, !key.command, session != nil { NSCursor.setHiddenUntilMouseMoves(true) }
        input.handleKey(key, world: session?.world)
    }

    private func handlePad(_ event: PadTracker.Event) {
        if case .button(let b, down: true) = event, controlsWindow?.capturePad(b) == true { return }
        guard mode == .game, !suspended, window.isKeyWindow, let w = session?.world else { return }
        input.handlePad(event, world: w)
    }

    /// On a pointer screen the stick moves the pointer, up to 240 pixels a second.
    private func movePointerWithPad(_ x: Double, _ y: Double) {
        guard mode == .game, !suspended, window.isKeyWindow, let w = session?.world else { return }
        input.movePointerWithPad(x, y, world: w)
    }

    private func handlePointer(x: Int?, y: Int?, phase: PointerPhase) { input.handlePointer(x: x, y: y, phase: phase, world: session?.world) }

    /// The play keys the world has logged since the last one (os.Logger "keys").
    private func logNewKeys() {
        guard let w = session?.world else { return }
        for k in w.keyLog.dropFirst(loggedKeys) { keyLog.info("key \(k.action, privacy: .public) \(String(describing: k.detail), privacy: .public)") }
        loggedKeys = w.keyLog.count
    }

    /// "EXIT TO DOS? YES" in the options dialog quits the app.
    private func quitIfRequested() {
        if session?.world.exitRequested == true { NSApp.terminate(nil) }
        if let w = session?.world { reportFileError(w) }
        if session?.world.newGameRequested == true { newGame(); return }
        swapIfPendingLoad()
    }

    func windowWillClose(_ note: Notification) { audio.stop() }

    func windowDidResignKey(_ note: Notification) {
        input.releaseAll(world: session?.world); hideMacPointer(false)
        input.releasePointer(world: session?.world)      // see InputRouter.releasePointer
    }

    private func showCurrent() {
        guard let g = game, cams.indices.contains(current) else { return }
        let file = cams[current], base = (file as NSString).deletingPathExtension
        do {
            let compositor = try Compositor(room: CAMFile(data: g.read("ROOMS/\(file)")))
            let level = levels?.cameraLevel[base.uppercased()].flatMap { levels?.levels[$0] }
            var stage = level.flatMap { stages[$0.name] }
            if stage == nil, let level {
                stage = try? Stage(level: level, game: g, cache: &assets)
                stages[level.name] = stage
            }
            room = (compositor, level?.cameras[base.uppercased()], stage)
        } catch {
            room = nil
            framebuffer.clear()
            NSSound.beep()
        }
        redraw()
        window.title = "BioForge — \(base)"
        startAnimation()
    }

    /// Composites the current camera at the current game tick and presents it.
    private func redraw() {
        if let r = room {
            let figures = r.camera.flatMap { cam in r.stage?.figures(for: cam, tick: Int(animTime * Self.tickRate)) } ?? []
            r.compositor.render(camera: r.camera, figures: figures, into: &framebuffer)
        }
        view.present(framebuffer)
    }

    private func startAnimation() {
        guard link == nil else { return }
        link = view.displayLink(target: self, selector: #selector(displayTick(_:)))
        link?.add(to: .main, forMode: .common)
        link?.isPaused = paused
    }

    @objc private func displayTick(_ l: CADisplayLink) {
        defer { lastStamp = l.timestamp }
        guard !paused, lastStamp > 0 else { return }
        if mode == .game {
            host.advance(dt: min(l.timestamp - lastStamp, 0.25))
            return
        }
        let before = Int(animTime * Self.tickRate)
        animTime += min(l.timestamp - lastStamp, 0.25)
        if Int(animTime * Self.tickRate) != before { redraw() }
    }
}

/// Set from the main thread, read by the art builder's thread.
private final class CancelFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false
    var isSet: Bool { lock.lock(); defer { lock.unlock() }; return value }
    func set() { lock.lock(); value = true; lock.unlock() }
}


extension AppDelegate: HostPlatform {
    func terminate() { NSApp.terminate(nil) }
    func startNewGame() { newGame() }
    func startPendingLoad() { swapIfPendingLoad() }
    func afterTicks(_ w: World) {
        dropReleasedModifiers(w)
        syncPointer(w)
    }
    func now() -> Double { CACurrentMediaTime() }
}
