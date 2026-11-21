// The SDL3 shell (Windows and Linux; the Mac app is the Mac's): a window, the game folder, and GameHost's loop with the picture shown sharp
// at 4:3. It mirrors the Mac app's AppDelegate (open, start, the suspend rules, the title) over SDL; keys, mouse and controller (PR 4/5),
// sound (PR 6) and the settings screen (PR 7) follow.
//   BIOFORGE_DATA=<folder>       the game folder (else the remembered one, else a dialog asks)
//   BIOFORGE_LOAD=<path>         boots a save, as on the Mac
//   BIOFORGE_SDL_SMOKE=<n>       runs n ticks with no waiting, prints "smoke: ..." and exits (0, or 1 when no game started)
//   BIOFORGE_SDL_SHOT=<x.bmp>    with it: saves the last picture
import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation

@MainActor
public final class SDLShell: HostPlatform {
    static let mutedKey = "Muted", folderKey = "GameFolderPath", aspectKey = "CorrectAspect", readableKey = "ReadableText", dataNoticeKey = "DataNoticeShown"
    static let fullScreenKey = "FullScreen", padBindingsKey = "PadBindings"

    let paths: HostPaths
    let store: SettingsStore
    let environment: [String: String]
    let log: HostLog
    let buildStamp: String
    let input = InputRouter()
    let playLog: PlayLog
    let host: GameHost
    let audio: SDLAudio
    public private(set) var settings = Settings()
    public private(set) var game: GameFolder?
    private var dataReport: GameDataReport?
    private var resources: GameResources?
    private var framebuffer = Framebuffer()
    /// The last picture as it was uploaded (RGBA32).
    public private(set) var rgba: [UInt8] = []
    public var session: GameSession? { host.session }

    var window: OpaquePointer?
    var renderer: OpaquePointer?
    private var texture: UnsafeMutablePointer<SDL_Texture>?
    private var vsync = false
    private var quit = false
    var focused = true
    private var hidden = false
    var suspended = false
    private var needsRedraw = false
    private var titleShown = ""
    /// Full screen now (borderless, on the desktop).
    public internal(set) var fullScreen = false
    // The cursor (SDLInput.swift): hidden after a key press until the mouse moves, and over the picture on a pointer screen, where the game draws its own hand.
    var keyHidden = false, pointerHidden = false, cursorHidden = false
    lazy var screen = SettingsScreen(host: SettingsAdapter(self))      // F1 (SDLSettings.swift)
    var font: CaptionFont?                        // for the settings screen
    let pad = SDLGamepad()                        // the first controller SDL finds (SDLGamepad.swift)
    var lastMouse: MousePoint?                    // the mouse position syncPointer last handed the game
    var mouseSeen = false                         // a mouse event has arrived: until then SDL's mouse state is no real position
    var virtualNow: Double?                       // the smoke run's (and the tests') clock, so a picture hold passes in ticks and not in wall time

    init(paths: HostPaths, store: SettingsStore, environment: [String: String], log: HostLog, buildStamp: String = "dev", soundFonts: SoundFontSearch = .standard) {
        self.paths = paths; self.store = store; self.environment = environment; self.log = log; self.buildStamp = buildStamp
        let play = PlayLog(file: paths.logFile)
        playLog = play
        audio = SDLAudio(log: log, soundFont: soundFonts.find(store: store, support: paths.support),
                         soundFontHelp: "put one in \(paths.support.path) or set \"\(SoundFontSearch.settingKey)\" in \(paths.settingsFile.path)", note: { play.note($0) })
        host = GameHost(input: input, audio: audio, playLog: playLog, autosaves: paths.autosaves, log: log)
        host.platform = self
    }

    var correctAspect: Bool { store.object(forKey: Self.aspectKey) == nil ? true : store.bool(forKey: Self.aspectKey) }
    private var smokeTicks: Int? { environment["BIOFORGE_SDL_SMOKE"].flatMap { Int($0) } }

    // MARK: window

    /// The window, the renderer and the game: the folder from the environment, the store or a dialog.
    public func start() {
        playLog.note("BioForge SDL \(buildStamp)")
        if playLog.previousEndedUnexpectedly { BugReport.keepCrashedRecording(logs: paths.logs) }
        input.setBindings(BindingsMigration.load(store), world: nil)
        if let saved = store.dictionary(forKey: Self.padBindingsKey) as? [String: String] { input.setPadBindings(PadBindings(propertyList: saved), world: nil) }
        folderEventType = SDL_RegisterEvents(1)
        let flags = BF_WINDOW_RESIZABLE | BF_WINDOW_HIGH_PIXEL_DENSITY
        window = SDL_CreateWindow("BioForge", 960, 720, flags)
        renderer = window.flatMap { SDL_CreateRenderer($0, nil) ?? SDL_CreateRenderer($0, "software") }      // the software one where there is no GPU or GL (a headless run)
        guard window != nil, renderer != nil else {
            log.error("sdl", "no window: \(String(cString: SDL_GetError()))")
            shutdown()
            quit = true
            return
        }
        applyAspect()
        vsync = SDL_SetRenderVSync(renderer, 1)
        texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA32, SDL_TEXTUREACCESS_STREAMING, Int32(Framebuffer.width), Int32(Framebuffer.height))
        SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_PIXELART)
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
        SDL_RenderClear(renderer)
        SDL_RenderPresent(renderer)
        SDL_StopTextInput(window)        // no input method pops up over the game
        pad.openFirst()
        audio.muted = store.bool(forKey: Self.mutedKey)
        if store.object(forKey: Self.fullScreenKey) != nil ? store.bool(forKey: Self.fullScreenKey) : environment["SteamDeck"] == "1" { fullScreen = SDL_SetWindowFullscreen(window, true) }
        let savedPath = store.string(forKey: Self.folderKey)
        let fromEnvironment = environment["BIOFORGE_DATA"].flatMap { $0.isEmpty ? nil : GameFolder(URL(fileURLWithPath: $0, isDirectory: true)) }
        let found = fromEnvironment ?? savedPath.map { GameFolder(URL(fileURLWithPath: $0, isDirectory: true)) }
        if let found, found.isValid { if !open(found) { askForFolder(problem: nil) } }
        else { askForFolder(problem: savedPath.map { HostText.folderGone(path: $0) }) }
    }

    /// The window keeps the picture's shape (16:10 without the 4:3 correction).
    func applyAspect() {
        SDL_SetWindowMinimumSize(window, 640, correctAspect ? 480 : 400)
        let ratio: Float = correctAspect ? 4.0 / 3.0 : 1.6
        SDL_SetWindowAspectRatio(window, ratio, ratio)
    }

    /// Borderless full screen on the desktop, remembered.
    public func setFullScreen(_ on: Bool) {
        SDL_SetWindowFullscreen(window, on)
        fullScreen = on
        store.set(on, forKey: Self.fullScreenKey)
    }

    // MARK: game folder

    /// No usable folder: say so and offer the folder dialog (its answer comes back as a user event); "Quit" ends the program. Smoke runs don't ask.
    private func askForFolder(problem: String?) {
        guard smokeTicks == nil else { return }
        let text = problem ?? "BioForge needs your own copy of the game. Choose the folder that contains BIOFORGE.EXE and a ROOMS folder. In a GOG installation it’s the Bioforge folder inside the app folder."
        if Dialogs.box(text, buttons: ["Choose Folder…", "Quit"], window: window, warning: false) == 0 { Dialogs.chooseFolder(window: window) } else { quit = true }
    }

    private func folderChosen(_ path: String?) {
        guard let path else { askForFolder(problem: nil); return }
        let url = URL(fileURLWithPath: path, isDirectory: true)
        guard let g = GameFolder.find(in: url) else {
            let text = HostText.notAGameFolder(name: url.lastPathComponent)
            Dialogs.box(text.message, text.info, window: window)
            askForFolder(problem: nil)
            return
        }
        if open(g) { store.set(g.url.path, forKey: Self.folderKey) } else { askForFolder(problem: nil) }      // remembered as on the Mac: a chosen folder, not BIOFORGE_DATA
    }

    /// Check the data, load the settings, start a game. False when the folder can't be used (the player has been told).
    @discardableResult
    func open(_ g: GameFolder) -> Bool {
        let report = GameData.check(g)
        playLog.note(report.summary)
        guard report.missing.isEmpty else {
            let text = HostText.incompleteAlert(folder: g.url.lastPathComponent, missing: report.missing)
            Dialogs.box(text.message, text.info, window: window)
            return false
        }
        let loaded: GameResources
        do { loaded = try GameResources(game: g) } catch {
            log.error("game", "game data: \(String(describing: error))")
            let text = HostText.unreadableAlert(error: error.localizedDescription, folderPath: g.url.path)
            Dialogs.box(text.message, text.info, window: window)
            return false
        }
        dataReport = report
        game = g
        settings = Settings.load(game: g)
        settings.apply(defaults: store)        // General MIDI stays the setting; the audio output plays it as AdLib when there is no SoundFont
        settings.onChange = { [weak self] in
            MainActor.assumeIsolated {      // the player's changes come from the main loop
                guard let self else { return }
                self.settings.save(to: self.store)
            }
        }
        resources = loaded
        font = try? CaptionFont(g.read(SettingsScreen.fontFile))
        if let path = environment["BIOFORGE_LOAD"], !path.isEmpty { loadSave(at: URL(fileURLWithPath: path)) } else { newGame() }
        offerUnknownDataNotice(report, folder: g)
        return true
    }

    /// Files that differ from the GOG release the port was tested with: the game runs anyway, so say so once per folder and file list.
    private func offerUnknownDataNotice(_ report: GameDataReport, folder g: GameFolder) {
        guard !report.unknown.isEmpty, smokeTicks == nil else { return }
        let fingerprint = HostText.unknownDataFingerprint(folderPath: g.url.path, unknown: report.unknown)
        guard store.string(forKey: Self.dataNoticeKey) != fingerprint else { return }
        store.set(fingerprint, forKey: Self.dataNoticeKey)
        let text = HostText.unknownDataNotice(unknown: report.unknown)
        Dialogs.box(text.message, text.info, window: window, warning: false)
    }

    // MARK: game

    func newGame() {
        guard let resources else { return }
        do { start(try GameSession.newGame(resources: resources)) } catch {
            log.error("game", "new game: \(String(describing: error))")
            Dialogs.box("A new game couldn’t be started.", error.localizedDescription, window: window)
        }
    }

    /// Where the options dialog saves and loads (created on demand).
    private var savesDirectory: URL? {
        do { try FileManager.default.createDirectory(at: paths.saves, withIntermediateDirectories: true) } catch { return nil }
        return paths.saves
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
            log.info("game", "loaded \(url.path)")
        } catch {
            log.error("game", "BIOFORGE_LOAD \(url.path): \(error.localizedDescription)")
            if fallBackToNewGame { newGame() } else { Dialogs.box("The save couldn’t be opened.", error.localizedDescription, window: window) }
        }
    }

    /// Make `s` the running game (a new game, a resumed save or a confirmed load dialog).
    func start(_ s: GameSession) {
        guard let resources else { return }
        s.world.recordLog = false
        s.world.configureSettings(settings)
        s.world.savesDir = savesDirectory
        s.world.readableText = store.bool(forKey: Self.readableKey)
        s.autoDifficulty = false          // the player picks the difficulty in the options dialog
        s.world.recorder = try? SessionRecorder(directory: paths.sessions, session: s)      // the inputs, for an exact replay (a bug report)
        host.session = s
        s.world.autosavedLevel = s.world.level           // a level change is what autosaves, not the start
        playLog.restart()
        playLog.note("game started: level \(s.world.level)")
        host.audio.newGame(game: resources.game, musicLevel: s.world.musicInitial, device: settings.musicDevice)
        host.gameStarted()
        titleShown = ""
        redrawGame()
    }

    // MARK: HostPlatform

    public func terminate() { quit = true }
    public func startNewGame() { newGame() }
    public func startPendingLoad() { if let p = session?.world.pendingLoad { start(p) } }

    /// A save or load from the options dialog failed: say so (the dialog itself shows nothing).
    public func reportFileError(_ w: World) {
        guard let e = w.takeFileError() else { return }
        let text = HostText.fileError(load: e.load, slot: e.slot, reason: e.reason)
        Dialogs.box(text.message, text.info, window: window)
    }

    public func afterTicks(_ w: World) {
        dropReleasedModifiers(w)
        syncPointer(w)
    }
    public func now() -> Double { virtualNow ?? Double(SDL_GetTicksNS()) / 1e9 }

    public func redrawGame() {
        guard let s = session, let renderer, let texture else { return }
        s.world.renderPresentation(into: &framebuffer)       // an open flic replaces the world here (World.render)
        var shown = framebuffer
        var hiRes: HiResFrame?
        s.world.applyPresentation(to: &shown, hiRes: &hiRes)  // RUMBLE, gamma, CHANGEPALETTE, FADE
        FrameRGBA.convert(shown, into: &rgba)
        if screen.isOpen, let font { screen.render(into: &rgba, font: font) }
        SDL_UpdateTexture(texture, nil, rgba, Int32(Framebuffer.width * 4))
        drawPicture()
        SDL_RenderPresent(renderer)
        needsRedraw = false
        updateTitle(s.world)
    }

    /// The uploaded picture, letterboxed on black, into the back buffer.
    private func drawPicture() {
        guard let renderer, let texture else { return }
        let r = layout.rect
        var dst = SDL_FRect(x: Float(r.x), y: Float(r.y), w: Float(r.w), h: Float(r.h))
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
        SDL_RenderClear(renderer)
        SDL_RenderTexture(renderer, texture, nil, &dst)
    }

    /// Window title = current camera (or monitor).
    private func updateTitle(_ w: World) {
        let title = "BioForge — \(w.monitorName ?? w.currentCamera ?? "—")"
        if title != titleShown { titleShown = title; SDL_SetWindowTitle(window, title) }
    }

    // MARK: loop

    /// In the background or minimized: no ticks and no sound, keys let go; the game carries on where it was.
    private func updateSuspended() {
        let s = !focused || hidden
        guard s != suspended else { return }
        suspended = s
        if s || !screen.isOpen { host.setSuspended(s, inGame: session != nil) }          // the screen keeps the game paused
        if s { input.releasePointer(world: session?.world) }
    }

    func handle(_ e: inout SDL_Event) {
        if e.type == folderEventType { folderChosen(Dialogs.path(of: e)); return }
        switch SDL_EventType(rawValue: e.type) {
        case SDL_EVENT_QUIT: quit = true
        case SDL_EVENT_WINDOW_FOCUS_LOST: focused = false; updateSuspended(); keyHidden = false; pointerHidden = false; lastMouse = nil; updateCursor()      // as the Mac's windowDidResignKey
        case SDL_EVENT_WINDOW_FOCUS_GAINED: focused = true; updateSuspended()
        case SDL_EVENT_WINDOW_MINIMIZED, SDL_EVENT_WINDOW_HIDDEN: hidden = true; updateSuspended()
        case SDL_EVENT_WINDOW_RESTORED, SDL_EVENT_WINDOW_SHOWN: hidden = false; needsRedraw = true; updateSuspended()
        case SDL_EVENT_WINDOW_RESIZED, SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED, SDL_EVENT_WINDOW_EXPOSED: needsRedraw = true
        case SDL_EVENT_GAMEPAD_ADDED: pad.openFirst()
        case SDL_EVENT_GAMEPAD_REMOVED: padRemoved(e.gdevice.which)
        case SDL_EVENT_KEY_DOWN: handleKey(e.key, down: true)
        case SDL_EVENT_KEY_UP: handleKey(e.key, down: false)
        case SDL_EVENT_MOUSE_MOTION: handlePointer(window: (e.motion.x, e.motion.y), phase: .move)
        case SDL_EVENT_MOUSE_BUTTON_DOWN: handleButton(e.button, down: true)
        case SDL_EVENT_MOUSE_BUTTON_UP: handleButton(e.button, down: false)
        default: break
        }
    }

    /// Every event SDL has queued.
    func pumpEvents() {
        var e = SDL_Event()
        while SDL_PollEvent(&e) { handle(&e) }
    }

    /// One iteration of the loop: `dt` seconds since the last.
    public func frame(dt: Double) {
        pollPad(dt: dt)
        if !suspended && !screen.isOpen { host.advance(dt: min(dt, 0.25)) }
        if needsRedraw { redrawGame() }
    }

    /// Events and frames until the player leaves; the exit code.
    public func run() -> Int32 {
        defer { shutdown() }
        if let ticks = smokeTicks { return smoke(ticks: ticks) }
        var last = SDL_GetTicksNS()
        while !quit {
            pumpEvents()
            let t = SDL_GetTicksNS()
            frame(dt: Double(t - last) / 1e9)
            last = t
            SDL_Delay(vsync && !suspended ? 1 : 8)        // vsync paces only the frames that present; this keeps the others from spinning
        }
        return 0
    }

    /// BIOFORGE_SDL_SMOKE: `ticks` frames of 1/30 s with no waiting, then one line about where the game is.
    private func smoke(ticks: Int) -> Int32 {
        pumpEvents()
        guard let s = session else { log.error("smoke", "no game started"); return 1 }
        virtualNow = 0
        for _ in 0..<ticks where !quit {
            virtualNow! += 1 / 30.0
            frame(dt: 1 / 30.0 + 1e-9)
        }
        var digest: UInt64 = 0xcbf29ce484222325               // FNV-1a over the RGBA buffer
        for b in rgba { digest = (digest ^ UInt64(b)) &* 0x100000001b3 }
        print("smoke: level \(s.world.level) tick \(s.vm.tick) camera \(s.world.currentCamera ?? "-") frame \(String(digest, radix: 16))")
        if let path = environment["BIOFORGE_SDL_SHOT"], !path.isEmpty { saveShot(to: path) }
        return 0
    }

    /// The last picture as it is on screen, as a BMP.
    func saveShot(to path: String) {
        guard let renderer else { return }
        drawPicture()
        if let surface = SDL_RenderReadPixels(renderer, nil) {
            if !SDL_SaveBMP(surface, path) { log.error("shot", "could not save \(path): \(String(cString: SDL_GetError()))") }
            SDL_DestroySurface(surface)
        }
    }

    /// The window and its textures go; the log ends cleanly.
    public func shutdown() {
        guard window != nil || renderer != nil else { return }
        playLog.quit()
        audio.stop()
        audio.close()
        pad.close()
        if let texture { SDL_DestroyTexture(texture) }
        if let renderer { SDL_DestroyRenderer(renderer) }
        if let window { SDL_DestroyWindow(window) }
        texture = nil; renderer = nil; window = nil
    }
}
