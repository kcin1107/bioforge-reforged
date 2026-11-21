// Show (WorldShow.swift and the JUMPON watch of ScriptVM.swift) against re/interp/test_show.py: the FLIC statements, RUNFLIC scenes, JUMPON,
// FREEZE / THAW, the CAPTUREKEYBOARD hook, ADDKEY and the front-end functions, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

private let showScript = """
[ SCN
\t00:00 _s = 1
\t300:00 _s = 2
]
[ MARK00
\t00:00 _m = 1
]
{ JWAIT
\tJUMPON USERINTERRUPT HIT
\tWAIT 90
\t_j = 1
\t:HIT
\t_n = _n + 1
\tWAIT 20
\t_j = 3
}
{ JSTART
\tJUMPON USERINTERRUPT HIT2
\t_j2 = 1
\t:HIT2
\t_j2 = 2
}
{ JBAD
\tJUMPON USERINTERRUPT NOLABEL
\tJUMPON NOSUCHVAR HIT3
\tJUMPON USERINTERRUPT
\t_jb = 1
}
{ JSUSP
\tJUMPON USERINTERRUPT HIT4
\tLOCALVAR ~0
\t~0 = PROCESS LONGWAIT
\tSUSPENDWHILE ~0
\t_js = 1
\t:HIT4
\t_js = 2
}
{ LONGWAIT
\tWAIT 500
}
{ OTHER
\tWAIT 2
\t_c = 1
}
{ LATE
\t_d = 1
}
{ FRZMAIN
\tFREEZE
\t_late = PROCESS LATE
\tWAIT 10
\tTHAW
\t_z = 1
}
{ GETKEY _KEY _MODIFIERS _MOUSE
\t_hk = ~0
\t_hm = ~1
\t_hs = ~2
}
{ GETESCKEY _KEY _MODIFIERS _MOUSE
\tIF ( ~0 == 1 ) THEN
\t\t_UserInterrupt = 1
}

"""

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ShowTests {
    private func make() throws -> (World, ScriptVM) {
        let world = try World(resources: try #require(worldResources), level: "LANDPAD")
        let vm = ScriptVM(engine: world, defs: try ScriptDefs(game: requireGame()))
        vm.load(DecodedScript(name: "SYN_SHOW.scr", text: Array(showScript.utf8), lineStarts: [], columns: [], unresolved: []))
        for k in ["_n", "_j", "_c", "_d", "_z", "_hk", "_hm", "_hs", "_s", "_m", "_j2", "_jb", "_js"] { vm.globals[k] = .int(0) }
        return (world, vm)
    }

    private func proc(_ vm: ScriptVM) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    private func stmt(_ w: World, _ vm: ScriptVM, _ name: String, _ args: ScriptValue...) { _ = w.call(.stmt, name, args, proc(vm)) }
    @discardableResult private func fn(_ w: World, _ vm: ScriptVM, _ name: String, _ args: ScriptValue...) -> Int {
        if case .int(let h) = w.call(.function, name, args, proc(vm)) { return h }
        return -1
    }
    private func s(_ x: String) -> ScriptValue { .str(x) }
    private func global(_ vm: ScriptVM, _ k: String) -> Int { if case .int(let i)? = vm.globals[k] { return i }; return -1 }

    /// RUNFLIC ran inside tick T; its render is this tick's step. -> ticks until the handle is gone.
    private func lifetime(_ w: World, _ vm: ScriptVM, _ args: ScriptValue...) -> Int {
        let h = fn2(w, vm, args)
        w.step()
        var n = 0
        while vm.process(h) != nil && n < 5000 { vm.tickOnce(); w.step(); n += 1 }
        return n
    }
    private func fn2(_ w: World, _ vm: ScriptVM, _ args: [ScriptValue]) -> Int {
        if case .int(let h) = w.call(.function, "RUNFLIC", args, proc(vm)) { return h }
        return -1
    }
    private func shown(_ w: World) -> Int { w.show.flic!.index - 1 }
    private func sum(_ w: World) -> Int { w.show.flic!.frame!.pixels.reduce(0) { $0 + Int($1) } }
    private func step(_ w: World, _ vm: ScriptVM, _ n: Int = 1) { for _ in 0..<n { vm.tickOnce(); w.step() } }

    // MARK: flic

    @Test func introSpaceSegmentIs1563TicksThenOneFrame3() throws {
        let (w, vm) = try make()
        stmt(w, vm, "STARTFLIC", s("intro"))
        stmt(w, vm, "SETFLICRATE", .int(6))
        #expect(lifetime(w, vm, s("SCN"), .int(521)) == 1563)
        #expect(shown(w) == 520 && sum(w) == 964686)
        #expect(lifetime(w, vm, s("SCN"), .int(522)) == 3)
        #expect(shown(w) == 521 && sum(w) == 3322826)
    }

    @Test func defaultIntervalIs2AndStartflicResetsIt() throws {
        let (w, vm) = try make()
        stmt(w, vm, "SETFLICRATE", .int(6))                                    // no flic open: ignored
        stmt(w, vm, "STARTFLIC", s("intro"))
        #expect(lifetime(w, vm, s("SCN"), .int(10)) == 10)
        stmt(w, vm, "SETFLICRATE", .int(6))
        stmt(w, vm, "STARTFLIC", s("intro"))
        #expect(lifetime(w, vm, s("SCN"), .int(10)) == 10)
    }

    @Test func nothingIsDrawnUntilRunflicAndTheFlicReplacesTheWorld() throws {
        let (w, vm) = try make()
        stmt(w, vm, "STARTFLIC", s("intro"))
        step(w, vm, 5)
        var fb = Framebuffer()
        w.render(into: &fb)
        #expect(w.show.flic!.index == 0 && fb.pixels.allSatisfy { $0 == 0 } && fb.palette.allSatisfy { $0 == 0 })
        fn(w, vm, "RUNFLIC", s("SCN"), .int(10))
        w.step()
        #expect(shown(w) == 0 && sum(w) == 434373)
        w.render(into: &fb)
        #expect(fb.pixels.reduce(0) { $0 + Int($1) } == 434373)
        fn(w, vm, "FADE", s("HIDE"))
        w.applyPresentation(to: &fb)
        #expect(fb.palette.allSatisfy { $0 == 0 })                             // the palette step applies to the flic
        stmt(w, vm, "STOPFLIC")
        #expect(w.show.flic == nil)
        stmt(w, vm, "STOPFLIC")                                                // safe when nothing is open
    }

    @Test func varModeFollowsTheVariableAndNeverGoesBack() throws {
        let (w, vm) = try make()
        stmt(w, vm, "STARTFLIC", s("plt0"))
        stmt(w, vm, "SETFLICRATE", .int(1))
        let h = fn2(w, vm, [s("SCN"), .int(0), .int(0), s("_plt0_frame")])
        var got: [Int] = []
        for v in [0, 3, 1, 7, 7, 5, 47, 100] {
            vm.globals["_plt0_frame"] = .int(v)
            w.step()
            got.append(shown(w))
        }
        #expect(got == [0, 3, 3, 7, 7, 7, 47, 47])
        #expect(vm.process(h) != nil)                                          // never finishes by itself
    }

    @Test func flicloopMarkAndBack() throws {
        let (w, vm) = try make()
        stmt(w, vm, "STARTFLIC", s("intro"))
        fn(w, vm, "RUNFLIC", s("SCN"), .int(0))
        w.step()
        step(w, vm, 3)
        stmt(w, vm, "FLICLOOP", s("MARK"))
        step(w, vm, 3)
        #expect(shown(w) == 6)
        stmt(w, vm, "FLICLOOP", s("BACK"))
        #expect(w.show.flic!.index == 4 && sum(w) == 437470)                   // frame 3 is on screen, 4 is next
    }

    @Test func scenesWithoutAFlicAndUnknownBlocksEndAtOnce() throws {
        let (w, vm) = try make()
        let h = fn(w, vm, "RUNFLIC", s("MARK00"), .int(0))
        #expect(vm.process(h) != nil)
        vm.tickOnce()
        #expect(vm.process(h) == nil && global(vm, "_m") == 0)
        stmt(w, vm, "STARTFLIC", s("intro"))
        let u = fn(w, vm, "RUNFLIC", s("NOSUCHBLOCK"))
        #expect(vm.process(u) != nil)
        vm.runTicks(2)                                                         // dies at its next update (the one after this tick)
        #expect(vm.process(u) == nil)
    }

    @Test func missingFileWarnsAndPlayflicIsAStub() throws {
        let (w, vm) = try make()
        stmt(w, vm, "STARTFLIC", s("nosuchshow"))
        #expect(w.show.flic == nil && w.warnings.count == 1)
        stmt(w, vm, "STARTFLIC", s("intro"))
        #expect(fn(w, vm, "PLAYFLIC") == 0 && w.show.flic!.index == 0)
    }

    // MARK: JUMPON

    @Test func aWatchCancelsTheWaitFiresOnceAndIsLevelTriggered() throws {
        let (w, vm) = try make()
        _ = w
        vm.fire("JWAIT")
        vm.runTicks(5)
        #expect(global(vm, "_n") == 0)
        vm.globals["_userinterrupt"] = .int(1)
        vm.tickOnce()
        #expect(global(vm, "_n") == 1)                                         // at once, the WAIT 90 cancelled
        vm.globals["_userinterrupt"] = .int(0)
        vm.globals["_userinterrupt"] = .int(1)                                 // one-shot: not re-armed
        vm.runTicks(3)
        #expect(global(vm, "_n") == 1)
        vm.runTicks(30)
        #expect(global(vm, "_j") == 3 && global(vm, "_userinterrupt") == 1)    // the variable is not reset
        vm.globals["_userinterrupt"] = .int(1)
        vm.fire("JSTART")                                                      // already non-zero when armed
        #expect(global(vm, "_j2") == 2)
    }

    @Test func errorsClearTheRegistration() throws {
        let (w, vm) = try make()
        _ = w
        vm.globals["_userinterrupt"] = .int(1)
        vm.fire("JBAD")
        #expect(global(vm, "_jb") == 1)
        #expect(vm.warnings.map { String($0.split(separator: "(error ").last!) } == ["0x11)", "0x17)", "0x29)"])
    }

    @Test func itRemovesTheProcessFromTheWaitersOfWhatItWaitedOn() throws {
        let (w, vm) = try make()
        _ = w
        vm.fire("JSUSP")
        let long = try #require(vm.processes.first { $0.block.name == "LONGWAIT" })
        #expect(long.waiters.count == 1)
        vm.globals["_userinterrupt"] = .int(1)
        vm.tickOnce()
        #expect(global(vm, "_js") == 2 && long.waiters.isEmpty)
    }

    // MARK: FREEZE / THAW

    @Test func freezeSuspendsTheExistingProcessesAndStopsTheWorld() throws {
        let (w, vm) = try make()
        vm.fire("OTHER")
        let native = vm.timedHandle(ticks: 3)
        vm.fire("FRZMAIN")                                                     // tick 0
        #expect(w.isFrozen)
        #expect(global(vm, "_d") == 1 && global(vm, "_z") == 0)                // a process made after FREEZE runs
        stmt(w, vm, "CHANGEPALETTE", .int(5), .int(5), .int(5), .int(2))
        step(w, vm, 5)
        #expect(w.presentation.cp == [5, 5, 5] && vm.process(native) == nil && global(vm, "_c") == 0)   // the world and its timers stand still
        #expect(w.gameTick == 0)                                               // the game clock [8330] stands still while frozen
        while global(vm, "_z") == 0 { step(w, vm) }
        #expect(vm.tick == 11 && !w.isFrozen && w.gameTick == 1)                                  // THAW at tick 10, _z the same tick
        while global(vm, "_c") == 0 { vm.tickOnce() }
        #expect(vm.tick == 13)                                                 // its WAIT 2 (due at tick 2) moved later by the 10 frozen ticks: runs in tick 12
    }

    // MARK: credits page

    @Test func creditsPageDoesNotPauseAndReportsItsState() throws {
        let (w, vm) = try make()
        #expect(fn(w, vm, "CREDITSSTATE") == 0)
        w.openOptions(Options.credits)
        let o = try #require(w.options)
        #expect(o.screen == "credits" && !w.paused && fn(w, vm, "CREDITSSTATE") == 0)
        let tick = vm.tick
        step(w, vm)
        #expect(vm.tick == tick + 1 && fn(w, vm, "CREDITSSTATE") == 1 && o.creditsPos == 1)
        let done = Options.creditsDone(o.creditsLines.count)
        step(w, vm, done + 5)
        #expect(fn(w, vm, "CREDITSSTATE") == 2 && o.creditsPos == done && vm.tick == tick + 1 + done + 5)
        #expect(w.optionKey("ESCAPE") == "return" && o.closed && fn(w, vm, "CREDITSSTATE") == 0)
    }

    @Test func monCodeCreditsOpensDuringAFlicAndWhileFrozen() throws {
        let (w, vm) = try make()
        stmt(w, vm, "STARTFLIC", s("intro"))
        stmt(w, vm, "FREEZE")
        #expect(w.isFrozen && w.flicOpen)
        step(w, vm, 2)
        let stopped = w.gameTick
        w.openOptions(Options.credits)                                          // 10a8:02cc has no flic test
        #expect(w.options?.screen == "credits" && w.creditsRolling)
        #expect(!w.isFrozen, "the page clears [50be] (1100:0716): world update, camera selection and the game clock run again")
        stmt(w, vm, "CHANGEPALETTE", .int(5), .int(5), .int(5), .int(1))
        step(w, vm, 2)
        #expect(w.presentation.cp == [0, 0, 0] && w.gameTick == stopped + 2)
        _ = w.optionKey("ESCAPE")
        step(w, vm)
        #expect(w.options?.closed == true && !w.isFrozen, "closing does not freeze it again")
        var fb = Framebuffer()
        w.renderPresentation(into: &fb)
        stmt(w, vm, "THAW")                                                     // the marks are still there
        #expect(!w.isFrozen)
    }

    @Test func creditsOpenRestartsTheDialogSongAndCloseStartsCreditsrolling() throws {
        let (w, _) = try make()
        w.currentMusic = .int(4)
        w.openOptions(Options.defaultFlag)                                      // [4e30] = 4
        w.options?.closed = true
        #expect(w.dialogSong == 4)
        w.currentMusic = .int(7)
        w.openOptions(Options.credits)
        #expect(w.musicLog.map { $0.value } == [.int(-1), .int(4)] && w.currentSong == 4)
        w.options?.closed = true
        w.openOptions(Options.credits)                                          // the same song: nothing
        #expect(w.musicLog.count == 2)
        w.dialogSong = -1                                                       // after a load: the music stops and stays off
        w.options?.closed = true
        w.openOptions(Options.credits)
        #expect(w.musicLog.count == 3 && w.currentSong == -1)
        _ = w.options?.update()
        _ = w.optionKey("ESCAPE")
        #expect(w.options?.closed == true && !w.paused)
    }

    @Test func mainPanelCreditsButtonResumesOnceAndNothingPausesAgain() throws {
        let (w, _) = try make()
        w.currentMusic = .int(4)
        w.openOptions(Options.defaultFlag)
        #expect(w.paused)
        w.currentMusic = .int(7)
        w.optionActivate("CRDX")
        #expect(w.options?.screen == "credits" && !w.paused)
        #expect(w.musicLog.map { $0.value } == [.int(-1), .int(4)])
        _ = w.options?.update()
        _ = w.optionActivate("RETURN")
        #expect(w.options?.screen == "main" && !w.paused, "nothing pauses again: the main panel stays over a running game")
        w.forcingReload = true
        w.openOptions(Options.defaultFlag)
        w.optionActivate("CRDX")
        #expect(w.paused, "a forced reload keeps the dialog paused")
    }

    @Test func creditsDuringAForcedReloadPauses() throws {
        let (w, _) = try make()
        w.forcingReload = true
        w.openOptions(Options.credits)
        #expect(w.paused, "10a8:02cc pauses it while _forcing_reload is set, and 221e does not resume it")
        w.options?.closed = true
        w.forcingReload = false
        w.openOptions(Options.credits)
        #expect(!w.paused)
    }

    // MARK: keyboard

    @Test func theHookBlockRunsPerKeyEvent() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CAPTUREKEYBOARD", s("GETKEY"))
        stmt(w, vm, "CAPTUREKEYBOARD", s("GETKEY"))
        #expect(w.warnings.count == 1)                                         // already captured (0xd1)
        w.keyEvent(scan: 0x2d, mods: 0xc0)
        #expect(["_hk", "_hm", "_hs"].map { global(vm, $0) } == [45, 192, 0] as [Int])
        w.keyEvent(scan: 0, mods: 5)
        #expect(global(vm, "_hm") == 192)                                      // scan code 0: nothing
        stmt(w, vm, "RELEASEKEYBOARD")
        w.keyEvent(scan: 0x10, mods: 7)
        #expect(global(vm, "_hk") == 45)
    }

    /// ZEROG_TURNING reads ISKEYPRESSED with the keyboard captured: the table comes from the keyboard interrupt (11d8:1561), whoever gets the press.
    @Test func aCapturedKeyIsInTheKeyTableAndNotTheNormalHandler() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CAPTUREKEYBOARD", s("GETKEY"))
        w.keyEvent(scan: 0x4b)
        #expect(w.keysCaptured == [0x4b])
        #expect(w.keysHeld.isEmpty)                                            // no walk or turn request from it
        w.keyUp(0x4b)
        #expect(w.keysCaptured.isEmpty)
    }

    @Test func escThroughGetesckeySetsTheInterruptOnlyWhileCaptured() throws {
        let (w, vm) = try make()
        w.keyEvent(scan: 1, mods: 0)
        #expect(global(vm, "_userinterrupt") == 0)
        stmt(w, vm, "CAPTUREKEYBOARD", s("GETESCKEY"))
        w.keyEvent(scan: 0x2d, mods: 0)
        #expect(global(vm, "_userinterrupt") == 0)
        w.keyEvent(scan: 1, mods: 0)
        #expect(global(vm, "_userinterrupt") == 1)
    }

    @Test func wasaltpressed() throws {
        let (w, vm) = try make()
        let got = [0xc0 | 0x80 | 0x40, 0x80, 0x40, 0, 0x0c, 0x30].map { fn(w, vm, "WASALTPRESSED", .int($0)) }
        #expect(got == [1, 1, 1, 0, 0, 0] as [Int])
    }

    @Test func addkeyIsDeliveredAtTheNextStepThroughKeyEvent() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CAPTUREKEYBOARD", s("GETKEY"))
        stmt(w, vm, "ADDKEY", .int(45), .int(128), .int(64))
        #expect(global(vm, "_hk") == 0)
        w.step()
        #expect([global(vm, "_hk"), global(vm, "_hm")] == [45, 192] as [Int])
    }

    @Test func addkeyEscReachesARunningMonitor() throws {
        let (w, vm) = try make()
        stmt(w, vm, "MON_START", s("PIMM"))
        stmt(w, vm, "ADDKEY", .int(1))
        w.step()
        #expect(w.monitor?.poll().label == "ESCAPE_BUTTON")
    }

    // MARK: front end

    @Test func getoptdataReadsInstallOpt() throws {
        let (w, vm) = try make()
        let got = ["LANGUAGE", "language", "Soundvol", "NOSUCHKEY"].map { fn(w, vm, "GETOPTDATA", .str($0)) }
        #expect(got == [69, 69, 100, 0] as [Int])
    }

    @Test func menuUnmenuCreditsstateAndExit() throws {
        let (w, vm) = try make()
        stmt(w, vm, "MENU", .int(8))
        stmt(w, vm, "UNMENU")
        #expect(fn(w, vm, "CREDITSSTATE") == 0 && !w.exitRequested && w.warnings.isEmpty)
        stmt(w, vm, "EXIT")
        #expect(w.exitRequested)
        #expect(w.unmodelled.isEmpty)
    }
}
