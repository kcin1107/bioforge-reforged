import BioForgeCore
import BioForgeHost
import CSDL3
import Foundation
import Testing
@testable import BioForgeSDLShell

@MainActor
@Suite(.enabled(if: dataFolder != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct SDLSettingsTests {
    private func started(_ rig: Rig) throws -> SDLShell {
        try #require(sdlReady, "SDL_Init failed: \(String(cString: SDL_GetError()))")
        let shell = rig.shell()
        shell.start()
        try #require(shell.session != nil, "no game started")
        return shell
    }

    private func tap(_ shell: SDLShell, _ usage: Int) { shell.push(key: usage, down: true); shell.push(key: usage, down: false) }

    /// BIOFORGE_TEST_SHOTS=<folder>: the screen as drawn, for a look.
    private func shot(_ shell: SDLShell, _ name: String) {
        guard let dir = ProcessInfo.processInfo.environment["BIOFORGE_TEST_SHOTS"] else { return }
        shell.saveShot(to: URL(fileURLWithPath: dir).appendingPathComponent(name).path)
    }

    @Test func f1StopsTheGameAndToggleReadableText() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try started(rig); defer { shell.shutdown() }
        let s = try #require(shell.session)
        shell.run(10)
        tap(shell, 0x3A)
        #expect(shell.screen.isOpen)
        let tick = s.vm.tick
        shell.run(30)
        #expect(s.vm.tick == tick)                                 // the game is frozen behind the screen
        shot(shell, "settings-main.bmp")
        for _ in 0..<5 { tap(shell, 0x51) }                        // Down x5: Readable Text
        tap(shell, 0x4F)                                           // Right
        #expect(s.world.readableText && rig.store.bool(forKey: "ReadableText"))
        tap(shell, 0x3A)
        #expect(!shell.screen.isOpen)
        shell.run(30)
        #expect(s.vm.tick == tick + 30)
    }

    @Test func aNewShellStartsWithTheSavedSetting() throws {
        let rig = Rig(); defer { rig.clean() }
        rig.store.set(true, forKey: "ReadableText")
        let shell = try started(rig); defer { shell.shutdown() }
        #expect(shell.session?.world.readableText == true)
    }

    @Test func aCapturedKeyIsBoundAndSaved() throws {
        let rig = Rig(); defer { rig.clean() }
        let shell = try started(rig); defer { shell.shutdown() }
        tap(shell, 0x3A)
        for _ in 0..<6 { tap(shell, 0x51) }
        tap(shell, 0x28)                                           // Keyboard Controls
        #expect(shell.screen.page == .keys)
        shot(shell, "settings-keys.bmp")
        tap(shell, 0x28)                                           // Walk Forward, first slot
        #expect(shell.screen.capturing == .key("forward", 0))
        tap(shell, 0x05)                                           // B
        #expect(shell.input.bindings.key("forward", slot: 0) == 0x05)
        let saved = rig.store.dictionary(forKey: BindingsMigration.key) as? [String: [Int]]
        #expect(saved?["forward"]?.first == 5)
        tap(shell, 0x3A)
        #expect(!shell.screen.isOpen)
    }
}
