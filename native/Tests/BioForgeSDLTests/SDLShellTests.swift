import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation
import Testing
@testable import BioForgeSDLShell

let dataFolder = ProcessInfo.processInfo.environment["BIOFORGE_DATA"].flatMap { $0.isEmpty ? nil : $0 }

/// What the disk audio driver writes (S16LE stereo, 44.1 kHz); each opened device starts it afresh.
let audioOutput = FileManager.default.temporaryDirectory.appendingPathComponent("BioForgeSDLTests-\(UUID().uuidString).raw")

/// SDL is process-global: initialised once, headless, for the whole suite. (The Mac has no GL for the offscreen driver; its dummy one does.)
let sdlReady: Bool = {
    #if os(macOS)
    SDL_SetHint("SDL_VIDEO_DRIVER", "dummy")
    #else
    SDL_SetHint("SDL_VIDEO_DRIVER", "offscreen")
    #endif
    SDL_SetHint("SDL_AUDIO_DRIVER", "disk")                         // writes what the shell plays to audioOutput, in real time
    SDL_SetHint("SDL_AUDIO_DISK_OUTPUT_FILE", audioOutput.path)
    SDL_SetHint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")        // the headless window never has the keyboard focus
    return SDL_Init(BF_INIT_SHELL)
}()

@MainActor
struct Rig {
    let home: URL, paths: HostPaths
    let store = MemoryStore()
    init() {
        home = FileManager.default.temporaryDirectory.appendingPathComponent("BioForgeSDLTests-\(UUID().uuidString)", isDirectory: true)
        paths = HostPaths.linux(env: [:], home: home)
    }
    /// `soundFonts` is empty by default, so a SoundFont on the development machine doesn't change what a test hears.
    func shell(data: String? = dataFolder, soundFonts: SoundFontSearch = .none) -> SDLShell {
        SDLShell(paths: paths, store: store, environment: data.map { ["BIOFORGE_DATA": $0] } ?? [:], log: SDLLog(), soundFonts: soundFonts)
    }
    func clean() { try? FileManager.default.removeItem(at: home) }
}

/// Real SDL events through the queue and the shell's own handler.
extension SDLShell {
    func push(key usage: Int, down: Bool, mod: UInt16 = 0) {
        var e = SDL_Event()
        e.type = (down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP).rawValue
        e.key.scancode = SDL_Scancode(rawValue: UInt32(usage))
        e.key.mod = mod
        SDL_PushEvent(&e)
        pumpEvents()
    }

    /// A mouse event at the window point of 320x200 pixel `game` (or at a raw window point).
    func push(mouse type: SDL_EventType, game: (x: Int, y: Int)? = nil, window: (x: Float, y: Float)? = nil, button: UInt8 = 1) {
        let p = window ?? game.flatMap { windowPoint(game: $0.x, $0.y) }.map { (x: $0.x, y: $0.y) } ?? (x: 0, y: 0)
        var e = SDL_Event()
        e.type = type.rawValue
        if type == SDL_EVENT_MOUSE_MOTION { e.motion.x = p.x; e.motion.y = p.y } else { e.button.x = p.x; e.button.y = p.y; e.button.button = button }
        SDL_PushEvent(&e)
        pumpEvents()
    }

    func push(window type: SDL_EventType) {
        var e = SDL_Event()
        e.type = type.rawValue
        SDL_PushEvent(&e)
        pumpEvents()
    }

    /// Frames of 1/30 s on a clock of their own, so the picture hold after the difficulty choice passes in frames and not in wall time.
    func run(_ ticks: Int) {
        for _ in 0..<ticks {
            virtualNow = (virtualNow ?? 0) + 1 / 30.0
            frame(dt: 1 / 30.0 + 1e-9)
        }
    }

    /// The 320x200 point of a button on the screen the dialog shows now, found by hovering; its asset name has `name` in it.
    func button(_ name: String) -> (x: Int, y: Int)? {
        guard let w = session?.world else { return nil }
        for y in stride(from: 0, to: 200, by: 4) {
            for x in stride(from: 0, to: 320, by: 4) where w.optionPointerMove(x: x, y: y)?.contains(name) == true { return (x, y) }
        }
        return nil
    }

    /// The opening as a player gets through it: Escape skips the intro, a click on Medium starts the game; then until Lex stands after the wake-up.
    func leaveTitle() -> Bool {
        guard let w = session?.world else { return false }
        run(60)
        push(key: 0x29, down: true); run(3); push(key: 0x29, down: false)
        for _ in 0..<20 where !w.isOptionsOpen { run(30) }           // the difficulty screen
        guard let medium = button("MED") else { return false }
        push(mouse: SDL_EVENT_MOUSE_MOTION, game: medium); run(5)
        push(mouse: SDL_EVENT_MOUSE_BUTTON_DOWN, game: medium); run(10)
        push(mouse: SDL_EVENT_MOUSE_BUTTON_UP, game: medium)
        for _ in 0..<20 where w.level == "TITLE" { run(60) }
        for _ in 0..<40 where w.player?.motion != "STAND" { run(30) }        // the wake-up: Lex stands and is free
        return w.level != "TITLE" && w.player?.motion == "STAND"
    }
}

@MainActor
@Suite(.enabled(if: dataFolder != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct SDLShellTests {
    let frame = 1 / 30.0 + 1e-9

    @Test func aNewGameRunsAndDraws() throws {
        try #require(sdlReady, "SDL_Init failed: \(String(cString: SDL_GetError()))")
        let rig = Rig(); defer { rig.clean() }
        let shell = rig.shell()
        defer { shell.shutdown() }
        shell.start()
        let s = try #require(shell.session, "no game started")
        #expect(s.world.level == "TITLE")                        // the opening waits for a key and a click
        let tick = s.vm.tick
        shell.run(300)
        #expect(s.vm.tick == tick + 300)
        try #require(shell.leaveTitle(), "never left TITLE")
        #expect(s.world.level == "CHAOS")                        // the wake-up
        #expect(shell.rgba.count == 320 * 200 * 4)
        #expect(shell.rgba.contains { $0 != 0 && $0 != 255 })
    }

    @Test func bioforgeDataIsNotRememberedAndTheSavesFolderExists() throws {
        try #require(sdlReady)
        let rig = Rig(); defer { rig.clean() }
        let shell = rig.shell()
        defer { shell.shutdown() }
        shell.start()
        #expect(rig.store.string(forKey: "GameFolderPath") == nil)        // a development override, as on the Mac; the dialog's choice is remembered
        #expect(shell.session?.world.savesDir == rig.paths.saves)
        var isDirectory: ObjCBool = false
        #expect(FileManager.default.fileExists(atPath: rig.paths.saves.path, isDirectory: &isDirectory) && isDirectory.boolValue)
    }

    @Test func aSecondShellFindsTheFolderInTheStore() throws {
        try #require(sdlReady)
        let rig = Rig(); defer { rig.clean() }
        rig.store.set(try #require(dataFolder), forKey: "GameFolderPath")
        let second = rig.shell(data: nil)
        defer { second.shutdown() }
        second.start()
        #expect(second.session != nil)
    }
}
