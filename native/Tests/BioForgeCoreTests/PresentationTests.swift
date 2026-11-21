// Presentation (WorldPresentation.swift) against re/interp/test_presentation.py: DEBUG / DEBUGINFO, CHANGEPALETTE, FADE, RUMBLE, CAPTION and
// SET_PTR_*, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

private let presentationScript = """
{ FADEWAIT
\t_f = 1
\tSUSPENDWHILE FADE DOWN 5
\t_f = 2
}
{ CAPWAIT
\t_c = 1
\tCAPTION "abc" PAUSE
\t_c = 2
}

"""
private let vision = "Your vision begins to blur... /FVotre vue commence... /GAlles verschwimmt..."

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct PresentationTests {
    /// A LANDPAD world with a VM that has the test script blocks; gamma 30 (offset 0) unless given.
    private func make(gamma: Int = 30) throws -> (World, ScriptVM) {
        let world = try World(resources: try #require(worldResources), level: "LANDPAD")
        let vm = ScriptVM(engine: world, defs: try ScriptDefs(game: requireGame()))
        vm.load(DecodedScript(name: "SYN_PRESENTATION.scr", text: Array(presentationScript.utf8), lineStarts: [], columns: [], unresolved: []))
        world.configureSettings(Settings(gamma: gamma))
        return (world, vm)
    }

    private func proc(_ vm: ScriptVM) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    private func stmt(_ w: World, _ vm: ScriptVM, _ name: String, _ args: ScriptValue...) { _ = w.call(.stmt, name, args, proc(vm)) }
    @discardableResult private func fade(_ w: World, _ vm: ScriptVM, _ args: ScriptValue...) -> Int {
        if case .int(let h) = w.call(.function, "FADE", args, proc(vm)) { return h }
        return -1
    }
    private func s(_ x: String) -> ScriptValue { .str(x) }
    private func six(_ v8: Int) -> Int { (v8 * 63 + 254) / 255 }
    private func eight(_ v6: Int) -> Int { v6 * 255 / 63 }

    /// The 6-bit channels the DAC shows for a source entry of 63 on every channel.
    private func shown(_ w: World) -> [Int] {
        Presentation.palette([255, 255, 255], gamma: w.gamma, cp: w.presentation.cp, fade: w.presentation.fade).map { six(Int($0)) }
    }

    private func out(_ g: Int, _ cp: [Int], _ r: Int, _ gr: Int, _ b: Int, fade: PaletteFade? = nil) -> [Int] {
        Presentation.palette([UInt8(eight(r)), UInt8(eight(gr)), UInt8(eight(b))], gamma: g, cp: cp, fade: fade).map { six(Int($0)) }
    }

    /// The statement ran inside tick T; this finishes T, so the next tickOnce is the Fade process's first step.
    private func settle(_ vm: ScriptVM) { vm.tickOnce() }

    // MARK: DEBUG

    @Test func debugAndDebuginfoAreModelledAndSilent() throws {
        let (w, vm) = try make()
        stmt(w, vm, "DEBUG", s("Cannot find Fluffy!"), s("CONTINUE"))
        stmt(w, vm, "DEBUG", s("NEVER"))
        stmt(w, vm, "DEBUG", .int(13))
        stmt(w, vm, "DEBUGINFO")
        #expect(w.unmodelled.isEmpty && w.warnings.isEmpty)
        #expect(w.log.map(\.name) == ["DEBUG", "DEBUG", "DEBUG", "DEBUGINFO"])
    }

    // MARK: palette

    @Test func withoutChangepaletteOrFadeItIsTheGammaLut() {
        let pal: [UInt8] = (0..<256).flatMap { [UInt8($0), UInt8(255 - $0), UInt8($0 / 2)] }
        for g in [0, 30, 50, 100] {
            #expect(Presentation.palette(pal, gamma: g) == Gamma.apply(to: pal, gamma: g))
        }
    }

    @Test func changepaletteNumbers() {
        #expect(out(30, [20, 20, 20], 10, 30, 50) == [30, 50, 63])
        #expect(out(30, [30, 30, 30], 63, 0, 0) == [63, 30, 30])
        #expect(out(30, [0, 0, 8], 10, 10, 10) == [10, 10, 18])
        #expect(out(30, [-1, -1, -1], 0, 1, 63) == [0, 0, 62])
        #expect(out(50, [20, 20, 20], 20, 0, 0) == [46, 26, 26])        // gamma 50 is +6
    }

    @Test func fadeScalesBeforeTheOffsetAndBlackIgnoresIt() {
        #expect(out(50, [0, 0, 0], 63, 63, 63, fade: .scale(0)) == [6, 6, 6])
        #expect(out(50, [9, 9, 9], 63, 63, 63, fade: .black) == [0, 0, 0])
        #expect(out(30, [0, 0, 0], 63, 63, 63, fade: .scale(128)) == [31, 31, 31])
    }

    // MARK: CHANGEPALETTE

    /// After each of `ticks` world steps: is a CHANGEPALETTE offset in force for the frame drawn then?
    private func tinted(_ w: World, _ ticks: Int) -> [Bool] {
        (0..<ticks).map { _ in w.step(); return w.presentation.cp != [0, 0, 0] }
    }

    @Test func aFlashShowsOneFrameAndDTicksShowDFrames() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CHANGEPALETTE", .int(20), .int(20), .int(20), .int(1))
        #expect(tinted(w, 3) == [true, false, false])
        stmt(w, vm, "CHANGEPALETTE", .int(10), .int(0), .int(0), .int(3))
        #expect(tinted(w, 5) == [true, true, true, false, false])
    }

    @Test func zeroAndNegativeArePersistentAndANewOneReplaces() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CHANGEPALETTE", .int(0), .int(0), .int(8), .int(0))
        #expect(tinted(w, 40) == [Bool](repeating: true, count: 40))
        stmt(w, vm, "CHANGEPALETTE", .int(-1), .int(-1), .int(-1), .int(-1))
        #expect(w.presentation.cp == [-1, -1, -1] && tinted(w, 40) == [Bool](repeating: true, count: 40))
        stmt(w, vm, "CHANGEPALETTE", .int(4), .int(0), .int(0), .int(999))
        #expect(w.presentation.cp == [4, 0, 0])                                  // replaced, not added
        #expect(shown(w) == [63, 63, 63])                                        // 63 + 4 clamps
        stmt(w, vm, "CHANGEPALETTE", .int(-4), .int(0), .int(0), .int(0))
        #expect(shown(w) == [59, 63, 63])
    }

    @Test func settingTheGammaCancelsIt() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CHANGEPALETTE", .int(10), .int(10), .int(10), .int(0))
        w.applyGamma(40)
        #expect(w.presentation.cp == [0, 0, 0] && tinted(w, 2) == [false, false])
    }

    // MARK: FADE

    private func ramp(_ w: World, _ vm: ScriptVM, _ ticks: Int, _ at: [Int]) -> [Int: Int] {
        var out: [Int: Int] = [:]
        for k in 1...ticks { vm.tickOnce(); if at.contains(k) { out[k] = shown(w)[0] } }
        return out
    }

    @Test func fadeUp60() throws {
        let (w, vm) = try make()
        #expect(fade(w, vm, s("HIDE")) == 0 && w.presentation.palState == 2 && shown(w) == [0, 0, 0])
        let h = fade(w, vm, s("UP"), .int(60))
        #expect(w.presentation.palState == 3 && vm.process(h) != nil)
        settle(vm)
        #expect(ramp(w, vm, 59, [1, 15, 30]) == [1: 0, 15: 15, 30: 31])
        #expect(vm.process(h) != nil)                                            // N - 1 ticks: still valid
        vm.tickOnce()
        #expect(shown(w) == [63, 63, 63] && w.presentation.palState == 0 && vm.process(h) == nil)
    }

    @Test func fadeDown65EndsOnTheOffsetOnlyPalette() throws {
        let (w, vm) = try make(gamma: 50)
        let h = fade(w, vm, s("DOWN"), .int(65))
        #expect(w.presentation.palState == 1)
        settle(vm)
        #expect(ramp(w, vm, 64, [1, 32, 64]) == [1: 63, 32: 37, 64: 6])          // gamma 50 adds +6 to 62 (clamped), 31, 0
        #expect(vm.process(h) != nil)
        vm.tickOnce()
        #expect(shown(w) == [6, 6, 6] && w.presentation.palState == 2 && vm.process(h) == nil)
        #expect(fade(w, vm, s("DOWN"), .int(5)) == 0)                            // already hidden: a no-op
        fade(w, vm, s("SHOW"))
        #expect(shown(w) == [63, 63, 63] && w.presentation.palState == 0)
    }

    @Test func fadeDown65WithGamma30() throws {
        let (w, vm) = try make()
        fade(w, vm, s("DOWN"), .int(65))
        settle(vm)
        #expect(ramp(w, vm, 64, [1, 32, 64]) == [1: 62, 32: 31, 64: 0])
    }

    @Test func noOpsDefaultLengthAndUnknownWord() throws {
        let (w, vm) = try make()
        #expect(fade(w, vm, s("UP"), .int(30)) == 0 && w.presentation.palState == 0)        // normal: UP does nothing
        let h = fade(w, vm, s("DOWN"))
        #expect(fade(w, vm, s("DOWN"), .int(30)) == 0)                           // fading down: DOWN does nothing
        settle(vm)
        for _ in 0..<19 { vm.tickOnce() }
        #expect(vm.process(h) != nil)
        vm.tickOnce()
        #expect(vm.process(h) == nil)                                            // omitted n = 20
        #expect(w.warnings.isEmpty)
        #expect(fade(w, vm, s("SIDEWAYS")) == 0 && fade(w, vm) == 0)
        #expect(w.warnings.count == 2)
    }

    @Test func onlyTheNewestProcessWrites() throws {
        let (w, vm) = try make()
        fade(w, vm, s("DOWN"), .int(10))
        fade(w, vm, s("SHOW"))
        fade(w, vm, s("DOWN"), .int(4))
        settle(vm)
        vm.tickOnce()
        #expect(w.presentation.fade == .scale(192))                              // the 4-step process: (3 << 8) / 4, not (9 << 8) / 10
    }

    @Test func suspendwhileWaitsForTheProcess() throws {
        let (w, vm) = try make()
        vm.fire("FADEWAIT")
        settle(vm)
        for _ in 0..<5 { vm.tickOnce() }
        #expect(vm.globals["_f"] == .int(1))
        vm.tickOnce()                                               // the fade ended last walk: the waiter goes on in this one (1238:077f)
        #expect(vm.globals["_f"] == .int(2))
        _ = w
    }

    // MARK: RUMBLE

    @Test func rumble3Sequence() throws {
        let (w, vm) = try make()
        stmt(w, vm, "RUMBLE", .int(3))
        var got: [[Int]] = []
        for _ in 0..<10 { w.rumbleStep(); got.append([w.presentation.rumbleX, w.presentation.rumbleY]) }
        #expect(got == [[-1, 1], [-1, 1], [-2, 2], [-1, 1], [-1, 1], [-2, 0], [-3, 0], [-4, -1], [-2, -3], [0, -5]])
    }

    @Test func rumbleForms() throws {
        let (w, vm) = try make()
        stmt(w, vm, "RUMBLE", .int(3))
        w.rumbleStep()
        stmt(w, vm, "RUMBLE", s("MOVE"), .int(0), .int(0), .int(0), .int(0))        // only the amplitude: x and y stay
        #expect(([w.presentation.rumbleAmp, w.presentation.rumbleX, w.presentation.rumbleY] as [Int]) == ([0, -1, 1] as [Int]))
        stmt(w, vm, "RUMBLE", s("MOVE"), .int(2), .int(-1), .int(300), .int(0))
        let p = w.presentation
        #expect(([p.rumbleAmp, p.rumbleX, p.rumbleY, p.rumbleXP, p.rumbleYP] as [Int]) == ([-1, 2, -1, 44, 0] as [Int]))
        w.rumbleStep()
        #expect(([w.presentation.rumbleX, w.presentation.rumbleY] as [Int]) == ([2, -1] as [Int]))         // MOVE mode never moves on its own
        stmt(w, vm, "RUMBLE", .int(5))
        #expect(w.presentation.rumbleAmp == 5)
        stmt(w, vm, "RUMBLE")
        let q = w.presentation
        #expect(([q.rumbleAmp, q.rumbleX, q.rumbleY, q.rumbleVX, q.rumbleVY] as [Int]) == ([0, 0, 0, 0, 0] as [Int]))
    }

    @Test func shiftFrame() {
        let a = (0..<24).map { UInt8($0 + 1) }
        // y = 1: row 0 revealed (fill 99); source rows 4, 2, 0 use x = 1 and rows 5, 3, 1 use xp = -1; revealed columns keep the old pixels
        let r1 = Presentation.shiftFrame(a, width: 4, height: 6, x: 1, y: 1, xp: -1, fill: 99)
        #expect(r1 == [99, 99, 99, 99, 5, 1, 2, 3, 6, 7, 8, 12, 13, 9, 10, 11, 14, 15, 16, 20, 21, 17, 18, 19])
        // y = -2: rows 4 and 5 revealed; source rows 2, 4 use x = 0 and the ones between xp = 1
        let r2 = Presentation.shiftFrame(a, width: 4, height: 6, x: 0, y: -2, xp: 1, fill: 99)
        #expect(r2 == [9, 10, 11, 12, 5, 13, 14, 15, 17, 18, 19, 20, 13, 21, 22, 23, 99, 99, 99, 99, 99, 99, 99, 99])
    }

    @Test func applyPresentationShiftsWhenRumblingAndLeavesTheStoppedFrame() throws {
        let (w, vm) = try make()
        var fb = Framebuffer()
        fb.palette[3] = 255; fb.palette[4] = 255; fb.palette[5] = 255          // index 1 white, the rest black
        for r in 0..<Framebuffer.height { fb.pixels[r * Framebuffer.width] = 1 }
        var plain = fb
        w.applyPresentation(to: &plain)
        #expect(plain.pixels == fb.pixels && plain.palette == Gamma.apply(to: fb.palette, gamma: 30))
        stmt(w, vm, "RUMBLE", s("MOVE"), .int(2), .int(0), .int(2), .int(0))
        w.applyPresentation(to: &fb)
        let row = 100 * Framebuffer.width
        #expect([fb.pixels[row], fb.pixels[row + 2], fb.pixels[row + 3]] == [1, 1, 0])      // the old column stays, the line moved by +2
    }

    // MARK: the black frame of a big palette change (10e8:1dcc; test_presentation.py PaletteCut)

    /// A frame whose 8-bit palette is `value` (6-bit) on every channel of every entry.
    private func flat(_ value: Int) -> Framebuffer {
        var fb = Framebuffer()
        fb.pixels = [UInt8](repeating: 7, count: fb.pixels.count)
        fb.palette = [UInt8](repeating: UInt8(eight(value)), count: 768)
        return fb
    }
    private func lit(_ w: World, _ fb: Framebuffer) -> Bool {
        var f = fb
        w.applyPresentation(to: &f)
        return f.palette.contains { $0 != 0 }
    }

    @Test func aBigPaletteChangePresentsOneBlackFrameThenThePicture() throws {
        let (w, _) = try make()
        #expect(lit(w, flat(10)))                      // the first palette is installed as it comes
        #expect(!lit(w, flat(20)))                     // 3 * 10 > 12: the cut frame is black
        #expect(lit(w, flat(20)))
    }

    @Test func aSmallPaletteChangeDoesNotAndEntry255IsNotCompared() throws {
        let (w, _) = try make()
        _ = lit(w, flat(10))
        #expect(lit(w, flat(14)))                      // 3 * 4 = 12 is not above 12
        var one = flat(14)
        for c in 0..<3 { one.palette[3 * 255 + c] = UInt8(eight(63)) }
        #expect(lit(w, one))
        one = flat(14)
        one.palette[15] = UInt8(eight(14 + 13))        // 13 on one entry from the installed one
        #expect(!lit(w, one))
    }

    @Test func aFadeSuppressesTheCutAndTheInstalledPaletteWaits() throws {
        let (w, _) = try make()
        _ = lit(w, flat(10))
        w.presentation.palState = 1                    // FADE DOWN running
        #expect(lit(w, flat(40)))
        w.presentation.palState = 0                    // the fade ended: the pending palette meets the old one
        #expect(!lit(w, flat(40)))
        #expect(lit(w, flat(40)))
    }

    @Test func loadLevelLeavesTheBlackPaletteInstalled() throws {
        let (w, vm) = try make()
        _ = lit(w, flat(10))
        stmt(w, vm, "LOADLEVEL", s("LANDPAD"))                 // 1130:147c: 1a9e(0, 0), an all-black pending palette
        #expect(w.presentation.installed?.allSatisfy { $0 == 0 } == true)
        #expect(!lit(w, flat(10)))                             // even a palette equal to the old one meets black
        #expect(lit(w, flat(10)))
    }

    // MARK: CAPTION

    @Test func sprintfReads16BitWords() {
        #expect(Presentation.sprintf16("Dist: %d", [7]) == "Dist: 7")
        #expect(Presentation.sprintf16("Escher Id: %d %d %d %d %d", [1, 2, 3, 4, 5]) == "Escher Id: 1 0 2 0 3")
        #expect(Presentation.sprintf16("%d %u %x %c %%", [-2, -2, 255, 65]) == "-2 65535 fffe \u{ff} %")
        #expect(Presentation.sprintf16("%ld", [-70000]) == "-70000")
        #expect(Presentation.sprintf16("[%3d][%-3d][%03d]", [5, 5, 5]) == "[  5][0  ][005]")
    }

    @Test func languageFilter() {
        #expect(Presentation.captionText(vision) == "Your vision begins to blur... ")
        #expect(Presentation.captionText("/!Caynan's id changed to 12345.") == "Caynan's id changed to 12345.")
        #expect(Presentation.captionText("Yep") == "Yep")
        #expect(Presentation.captionText("/FBonjour/EHello/GHallo") == "Hello")
    }

    @Test func lifetimeIs7PerCharacterIn60HzTicks() throws {
        var got: [String] = []
        for args in [[s(vision)], [s("abc")], [s("Dist: %d"), .int(7)]] {
            let (w, vm) = try make()
            _ = w.call(.stmt, "CAPTION", args, proc(vm))
            let e = try #require(w.subtitleLog.first)
            got.append("\(e.text)|\(e.colour)|\(e.end - e.tick)")
        }
        #expect(got == ["Your vision begins to blur... |117|105", "abc|117|11", "Dist: 7|117|25"])
    }

    @Test func aNewCaptionReplacesTheOldOne() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CAPTION", s(vision))
        vm.runTicks(10)
        stmt(w, vm, "CAPTION", s("abc"))
        let first = w.subtitleLog[0], second = w.subtitleLog[1]
        #expect(([first.end, second.tick, second.end - second.tick] as [Int]) == ([10, 10, 11] as [Int]))
        #expect(vm.process(first.handle) == nil)
    }

    @Test func aNewSubtitleStopsTheOldVoice() throws {
        // 10e8:0529 -> vtable +8 = 10e8:08a4 stops the old subtitle's sound if it is still playing
        let (w, vm) = try make()
        _ = w.subtitle([.str("_pim_beep_5"), .int(0x75), .int(0xff), .str("one two three four five six")], minor: false)
        let voice = try #require(w.subtitleVoice)
        #expect(vm.process(voice) != nil)
        _ = w.subtitle([.str("_pim_beep_5"), .int(0x75), .int(0xff), .str("next")], minor: false)
        #expect(vm.process(voice) == nil)
        #expect(vm.process(try #require(w.subtitleVoice)) != nil)
    }

    @Test func aCaptionIsMarkedToShowWithSubtitlesOff() throws {
        // 10d0:16cb -> 10b0:0f48 never reads the subtitles switch [50bc]; only SUBTITLE does (10e8:0529)
        let (w, vm) = try make()
        stmt(w, vm, "CAPTION", s("abc"))
        _ = w.subtitle([.str("_pim_beep_5"), .int(0x75), .int(0xff), .str("spoken")], minor: false)
        let caption = w.subtitleLog[0], spoken = w.subtitleLog[1]
        #expect(w.captionHandles.contains(caption.handle) && !w.captionHandles.contains(spoken.handle))
    }

    @Test func pauseBlocksTheCallerUntilItEnds() throws {
        let (w, vm) = try make()
        vm.fire("CAPWAIT")
        #expect(vm.globals["_c"] == .int(1))
        vm.runTicks(11)
        #expect(vm.globals["_c"] == .int(1))
        vm.runTicks(2)
        #expect(vm.globals["_c"] == .int(2))
        _ = w
    }

    @Test func warningsAndDrops() throws {
        let (w, vm) = try make()
        stmt(w, vm, "CAPTION")
        #expect(w.warnings.count == 1 && w.subtitleLog.count == 0)
        stmt(w, vm, "CAPTION", s(String(repeating: "x", count: 351)))
        #expect(w.subtitleLog.count == 0)
        stmt(w, vm, "CAPTION", s(String(repeating: "x", count: 350)))
        #expect(w.subtitleLog.count == 1)
        stmt(w, vm, "CAPTION", s("abc"), s("CONTINUE"))                          // a word other than PAUSE: warns, still shows, never waits
        #expect(w.warnings.count == 2 && w.subtitleLog.count == 2)
    }

    // MARK: SET_PTR_*

    @Test func setPtrIsASilentNoOpBeforeMonStartThenStored() throws {
        let (w, vm) = try make()
        stmt(w, vm, "SET_PTR_PRESS_TIME", .int(2), .int(5), .int(2))
        stmt(w, vm, "SET_PTR_MOVEMENT", .int(360), .int(1))
        #expect(w.warnings.isEmpty && w.unmodelled.isEmpty && w.monitor == nil)
        stmt(w, vm, "MON_START", s("PIMM"))
        let m = try #require(w.monitor)
        func values(_ m: MonitorScreen) -> [Int] { [m.pointerPressTime.press, m.pointerPressTime.hold, m.pointerPressTime.release, m.pointerMovement.maxPixelsPerSecond, m.pointerMovement.acceleration] }
        #expect(values(m) == [14, 5, 14, 320, 2])
        stmt(w, vm, "SET_PTR_PRESS_TIME", .int(2), .int(5), .int(2))
        stmt(w, vm, "SET_PTR_MOVEMENT", .int(360), .int(1))
        #expect(values(m) == [2, 5, 2, 360, 1])
        stmt(w, vm, "MON_START", s("PIMM"))                                      // every MON_START restarts at the defaults
        #expect(values(try #require(w.monitor)) == [14, 5, 14, 320, 2])
    }
}
