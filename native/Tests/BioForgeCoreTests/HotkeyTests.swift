import Foundation
import Testing
@testable import BioForgeCore

// O / R / S / L / Alt+X open the options dialog through the FUN_10a8_02cc guard (mirrors re/interp/test_keys.py HotkeyTests).
@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct HotkeyTests {
    /// A running opening past the keyboard capture: Lex exists and is alive, another figure (the nurse) is available.
    func running() throws -> (session: GameSession, world: World, other: Figure) {
        let session = try GameSession.newGame(resources: try #require(worldResources), inControlAfterOldTicks: 1_000)
        let w = session.world
        let lex = try #require(w.player)
        session.vm.setObject(w.objectKey(lex.name), [.int(100)] + Array(repeating: .int(0), count: 9))
        let other = try #require(w.figures["FIRSTBOT"])          // the nurse: visible from Lex's cell cameras (CE31-33),
                                                                   // unlike CHAOS's other placed figures, which are hidden
                                                                   // this early (off camera)
        w.options?.closed = true
        return (session, w, other)
    }

    func press(_ w: World, _ scan: Int, _ mods: Int = 0) { w.keyDown(scan, mods: mods); w.keyUp(scan, mods: mods) }
    func opened(_ w: World) -> (String?, Int)? { w.options.flatMap { $0.closed ? nil : ($0.screen, $0.flags) } }
    /// CANNOT_SAVE runs (its MINORSUBTITLE call; the caption itself yields to a live one).
    func disabledSubtitles(_ w: World) -> Int { w.log.filter { $0.name == "MINORSUBTITLE" && $0.block == "CANNOT_SAVE" }.count }
    func setHP(_ s: GameSession, _ w: World, _ f: Figure, _ hp: Int) {
        s.vm.setObject(w.objectKey(f.name), [.int(hp)] + Array(repeating: .int(0), count: 9))
    }

    @Test func eachKeyOpensItsScreenWithItsFlags() throws {
        let (s, w, _) = try running()
        defer { withExtendedLifetime(s) {} }
        for (scan, mods, screen, flags) in [(0x18, 0, "main", 1), (0x13, 0, "credits", 0x10), (0x1f, 0, "save", 8),
                                            (0x26, 0, "load", 4), (0x2d, Keys.alt, "confirm", 0x400)] {
            press(w, scan, mods)
            let o = opened(w)
            #expect(o?.0 == screen && o?.1 == flags, "scan \(scan)")
            w.options?.closed = true
        }
        press(w, 0x1f, Keys.alt); #expect(opened(w) == nil, "Alt+S is ignored")
        press(w, 0x2d); #expect(opened(w) == nil, "X alone does nothing")
    }

    @Test func loadConditions() throws {
        let (s, w, _) = try running()
        let lex = try #require(w.player)
        setHP(s, w, lex, 0)
        press(w, 0x26); #expect(opened(w) == nil, "dead player")
        setHP(s, w, lex, 5)
        w.saveBusy = true
        press(w, 0x26); press(w, 0x2d, Keys.alt); #expect(opened(w) == nil, "save or load in progress")
        w.saveBusy = false
        w.monitor = try MonitorScreen(name: "PIMM", game: requireGame())
        press(w, 0x1f); #expect(opened(w) == nil, "player-handler keys ignored while a monitor runs")
        press(w, 0x26); #expect(opened(w) == nil, "L needs Alt with a monitor open")
        press(w, 0x26, Keys.alt); #expect(opened(w)?.0 == "load")
    }

    @Test func invulnerableVisibleLivingFigureRefusesSave() throws {
        let (s, w, other) = try running()
        other.invulnerable = true
        setHP(s, w, other, 10)
        let before = disabledSubtitles(w)
        press(w, 0x1f)
        #expect(opened(w) == nil && disabledSubtitles(w) == before + 1)
        press(w, 0x18)
        #expect(opened(w)?.0 == "main" && opened(w)?.1 == (1 | Options.noSave))
        #expect(w.options?.buttonState("SAVX") == 5)
        #expect(w.optionActivate("SAVX") == nil && w.options?.screen == "main")
        w.optionActivate("LODX")
        #expect(w.options?.screen == "load")
        w.options?.closed = true
        press(w, 0x13)
        #expect(opened(w)?.1 == (0x10 | Options.noSave))
    }

    @Test func hiddenOrDeadInvulnerableFigureDoesNotBlock() throws {
        let (s, w, other) = try running()
        other.invulnerable = true; other.hidden = true
        setHP(s, w, other, 10)
        #expect(w.saveSafe)
        other.hidden = false
        setHP(s, w, other, 0)
        #expect(w.saveSafe)
        let before = disabledSubtitles(w)
        press(w, 0x1f)
        #expect(opened(w)?.0 == "save" && disabledSubtitles(w) == before)
    }

    @Test func capturedKeyboardAndForcedReloadBlockSaving() throws {
        let (s, w, _) = try running()
        defer { withExtendedLifetime(s) {} }
        let before = disabledSubtitles(w)
        w.keyboardCaptured = true
        #expect(!w.saveSafe)
        press(w, 0x1f); #expect(opened(w) == nil && disabledSubtitles(w) == before + 1)
        press(w, 0x18); #expect(opened(w) == nil, "the player handler ignores the other keys")
        w.keyboardCaptured = false
        #expect(w.saveSafe)
        w.forcingReload = true
        press(w, 0x1f); #expect(opened(w) == nil)
        w.forcingReload = false
        press(w, 0x1f); #expect(opened(w)?.0 == "save")
    }

    @Test func altVShowsTheVersionSubtitleOnce() throws {
        let (s, _) = try itemWorld()                          // a quiet world: no running scripts, so no other subtitle competes
        let w = s.world
        defer { withExtendedLifetime(s) {} }
        press(w, 0x2f, Keys.alt)
        #expect(w.subtitleLog.map(\.text) == ["BioForge  ver f1.01~(C) 1994, 1995 Origin Systems"])
        press(w, 0x2f, Keys.alt)                              // refused while the caption is still showing
        #expect(w.subtitleLog.count == 1)
        #expect(opened(w) == nil, "not an options action")
    }

    @Test func altVWithoutAltDoesNothing() throws {
        let (s, _) = try itemWorld()
        let w = s.world
        defer { withExtendedLifetime(s) {} }
        press(w, 0x2f)
        #expect(w.subtitleLog.isEmpty)
    }

    @Test func monCodeAndStatementsGoThroughTheGuard() throws {
        let (s, w, other) = try running()
        s.vm.globals["_isexitmonrunning"] = .int(1)
        w.openOptions(Options.defaultFlag); #expect(opened(w) == nil)
        s.vm.globals["_isexitmonrunning"] = .int(0)
        other.invulnerable = true
        setHP(s, w, other, 10)
        w.openOptions(Options.save); #expect(opened(w) == nil)
        w.openOptions(Options.defaultFlag); #expect(opened(w)?.1 == (1 | Options.noSave))
        w.openOptions(Options.audio); #expect(opened(w)?.0 == "main", "a dialog is already up")
    }
}
