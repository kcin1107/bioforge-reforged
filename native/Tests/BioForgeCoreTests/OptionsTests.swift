import Foundation
import Testing
@testable import BioForgeCore

// Expected hashes come from the Python prototype's Options (re/interp/options.py) run with the same steps.
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct OptionsTests {
    static let palette = "42b45ba9bf9b133fbb36e16b92aba13e846418fa8a6f71dce724013ae5d8440a"

    func options(_ flags: Int) throws -> Options {
        let o = try Options(game: requireGame())
        o.open(flags)
        return o
    }

    func check(_ o: Options, _ pixels: String, _ what: String) {
        var fb = Framebuffer()
        o.render(into: &fb)
        #expect(sha(fb.palette) == Self.palette, "\(what) palette")
        #expect(sha(fb.pixels) == pixels, "\(what) pixels")
    }

    @Test func screensMatchThePythonPrototype() throws {
        check(try options(Options.difficulty), "381d1f0b87ebf6aab5eb4a8d566553d8327b16256e857f964e8095630a1cdf60", "difficulty")
        check(try options(1), "31f277d8d8aa29b05560a94a48a6058497a524944e156be3b9ab4903d6a451e4", "main")
        let hover = try options(1)
        #expect(hover.pointerMove(x: 40, y: 140) == "EXTX")
        check(hover, "80860a5c936721ec9f56fd33d3e99170e072318ff59a755ff883d81f921fcbbb", "main with pointer over EXIT")
        let audio = try options(Options.audio)
        #expect(audio.activate("SFX-") == "audio:90,100")
        check(audio, "73a70528511b1a0c8fc3e7ac714a128ac113f0dd47bec00da20cf60f5e525e48", "audio")
        check(try options(Options.audio), "a4fd5cc552fa79f1d4fcb8d490c0354f12a3be167a3d9fe1564a0a634b85f7f3", "audio panel as opened")
        let toggled = try options(Options.audio)
        #expect(toggled.activate("SFXX") == "audio:0,100")
        check(toggled, "7461c1d23f9d277e0b5822dcf7c8c6c631d3d2325983f22da92284142f844ae7", "audio after the SFXX toggle")
        let silent = try Options(game: requireGame(), settings: Settings(sound: 0, music: 0, subtitles: false))
        silent.open(Options.audio)
        check(silent, "79fced19f03ddd43695cf100a384025c4209ecec551c78a8f4ee75ee32ac0a74", "audio panel with silent settings")
        let gamma = try Options(game: requireGame(), settings: Settings(gamma: 50))
        gamma.open(1)
        #expect(gamma.activate("GMAX") == nil && gamma.screen == "gamma")
        check(gamma, "681edee6598000f6b39d2afd165a53389728194ac04c75eb821b4ac276112bf7", "gamma panel at 50")
        #expect(gamma.activate("GMPX") == "gamma:60")
        check(gamma, "b1103f055b4da7521e27f21e78927d0d43ed6333e8a8aa7e7396cf9e3a3aeb97", "gamma panel after GMPX")
        check(try options(Options.credits), "23a9fbf26b4c3d5d93fb15691cd0ac5faee5d391ea80cf8af98ec42a088964bd", "credits (no dialog art: the World draws the roll over the scene)")
        let save = try options(Options.save)
        save.activate("RIGHT"); save.activate("RIGHT")
        check(save, "6084ff9017a52aae0628c386a31e21316ba75ae01a238d0d130383c05ffc79ad", "save")
        check(try options(Options.load), "6cceb6e90145050f0cc243f157b0f1e6b310d4d481156bafb6e47ed1daf97c7f", "load")
        let confirm = try options(1)
        confirm.activate("LOAD")
        #expect(confirm.activate("OK") == nil)
        check(confirm, "268cf5039f8e1fa5d11d2b04e26d0b33c52ab01957811b1ade41a210b7a4b5b4", "confirm after LOAD, OK")
        check(try options(Options.exit), "f597c5f79ea5392540c8dcf85789973c8b577a9daf049d6426d966573558074b", "exit confirm")
    }

    /// Pixels (index -> colour) that the label texts draw: a render against the same screen with every label's text cleared.
    func textPixels(_ o: Options, labels: [String]) throws -> [Int: UInt8] {
        var with = Framebuffer()
        o.render(into: &with)
        let saved = labels.map { o.elementText($0) ?? "" }
        for l in labels { o.setLabelText(l, "") }
        var without = Framebuffer()
        o.render(into: &without)
        for (l, t) in zip(labels, saved) { o.setLabelText(l, t) }
        return Dictionary(uniqueKeysWithValues: with.pixels.indices.filter { with.pixels[$0] != without.pixels[$0] }.map { ($0, with.pixels[$0]) })
    }

    static let labelNames = ["CRDL", "GMAL", "AOKL", "ACAL", "EZYL", "MEDL", "HRDL", "LOKL", "LCAL", "LNWL", "YESL", "NOOL", "QSTL", "CAPL"]

    @Test func pimmStringsLabelTheMainScreenOnlyWhereTheArtHasALabel() throws {
        let o = try options(1)
        o.pointerMove(x: 319, y: 199)       // the hand hangs right and below its fingertip (pointer - 122,13): park it off the labels
        #expect(o.elementText("GMAL") == "GAMMA" && o.elementText("CRDL") == "CREDITS")
        #expect(o.elementText("DETX") == nil, "OPTS.CAM has no DETX")
        let changed = try textPixels(o, labels: Self.labelNames)
        #expect(Set(changed.keys.map { $0 / 320 }).allSatisfy { (166..<175).contains($0) }, "text only in the label band of the bottom bars")
        for (x, y, w) in [(79, 166, 30), (216, 166, 30)] {
            let inside = changed.filter { ($0.key / 320 >= y && $0.key / 320 < y + 7) && abs($0.key % 320 - (x + w / 2)) < 40 }
            #expect(!inside.isEmpty && Set(inside.values) == [148], "label at \(x),\(y) draws in the label colour")
        }
        for (x, y, w, h) in [(37, 137, 40, 20), (92, 137, 40, 20), (145, 137, 40, 20), (198, 137, 40, 20), (251, 137, 40, 20)] {
            #expect(!changed.keys.contains { $0 / 320 >= y && $0 / 320 < y + h && $0 % 320 >= x && $0 % 320 < x + w }, "no text over the icon at \(x),\(y)")
        }
    }

    @Test func labelsOfTheOtherScreensShowThePimmText() throws {
        let diff = try options(Options.difficulty)
        #expect(["EZYL", "MEDL", "HRDL"].map { diff.elementText($0) } == ["EASY COMBAT", "MEDIUM COMBAT", "HARD COMBAT"])
        #expect(try !textPixels(diff, labels: Self.labelNames).isEmpty)
        let audio = try options(Options.audio)
        #expect(audio.elementText("AOKL") == "SAVE SETTINGS" && audio.elementText("ACAL") == "CANCEL")
        #expect(audio.elementText("SFXX") == "SFX" && audio.elementText("MSCX") == "MUSIC" && audio.elementText("SFPX") == "")
        #expect(try !textPixels(audio, labels: Self.labelNames).isEmpty)
        let gamma = try options(1)
        gamma.activate("GMAX")
        #expect(gamma.screen == "gamma" && gamma.elementText("AOKL") == "SAVE SETTINGS" && gamma.elementText("ACAL") == "CANCEL")
        let load = try options(Options.load)
        #expect(["LOKL", "LCAL", "LNWL"].map { load.elementText($0) } == ["LOAD", "CANCEL", "NEW"])
        #expect(try !textPixels(load, labels: Self.labelNames).isEmpty)
        let save = try options(Options.save)
        #expect(["LOKL", "LCAL", "LNWL"].map { save.elementText($0) } == ["SAVE", "CANCEL", ""] && !save.elementActive("LNWX"))
    }

    @Test func confirmPromptsFollowTheMode() throws {
        let exit = try options(Options.exit)
        #expect(["QSTL", "YESL", "NOOL"].map { exit.elementText($0) } == ["Do you really want to quit?", "YES", "NO"])
        #expect(try !textPixels(exit, labels: Self.labelNames).isEmpty)
        let load = try options(Options.load)
        load.activate("LOKX")
        #expect(load.elementText("QSTL") == "Load this game?" && load.elementFrame("SELG") == 0xf)
        load.activate("NOOX"); load.activate("LNWX")
        #expect(load.elementText("QSTL") == "Begin New Game?" && load.elementFrame("SELG") == 0)
        let o = try Options(game: requireGame(), slotUsed: { $0 == 2 })
        o.open(Options.save); o.activate("LOKX")
        #expect(o.elementText("QSTL") == "Save this game?" && o.elementFrame("SELG") == 0)
        o.activate("NOOX"); o.activate("SE2X"); o.activate("LOKX")
        #expect(o.elementText("QSTL") == "Save over this game?" && o.elementFrame("SELG") == 0xf)
        #expect(o.activate("YESX") == "save:2")
    }

    @Test func rightClickClosesTheDialogLikeEscape() throws {
        let main = try options(1)
        #expect(main.rightClick() == "return" && main.closed)         // FUN_1250_0cf9 presses "ESCAPE" for the right button, as the key does
        #expect(main.rightClick() == nil)
        let difficulty = try options(Options.difficulty)
        #expect(difficulty.rightClick() == nil && !difficulty.closed, "the difficulty choice cannot be dismissed")
    }

    @Test func stateMachineActions() throws {
        let main = try options(1)
        #expect(main.activate("DETAIL") == nil && main.screen == "main" && !main.closed, "DETAIL does nothing: the original has no DETX branch")
        #expect(main.activate("EXIT") == nil && main.screen == "confirm")
        #expect(main.key("ESCAPE") == "cancel" && main.closed)

        #expect(try options(1).key("ESCAPE") == "return")
        let difficulty = try options(Options.difficulty)
        #expect(difficulty.key("ESCAPE") == nil && !difficulty.closed, "the difficulty choice cannot be dismissed")
        let credits = try options(Options.credits)
        #expect(credits.key("ESCAPE") == nil, "[4e3b] = 0x29a: keys wait for the first update")
        _ = credits.update()
        #expect(credits.key("ESCAPE") == "return")
        #expect(try options(Options.audio).key("ESCAPE") == "cancel")
        let audio = try options(Options.audio)
        #expect(audio.activate("OK") == "audio:100,100" && audio.closed, "opened with the audio flag: OK closes the dialog")
        #expect(try options(Options.exit).activate("YES") == "exit")

        let load = try options(Options.load)
        #expect(load.activate("SLOT4") == nil)
        load.activate("OK")
        #expect(load.key("ESCAPE") == nil && load.screen == "load", "Escape on the confirm screen returns to the slots")
        load.activate("OK")
        #expect(load.activate("YES") == "load:4" && load.closed)
        let new = try options(Options.load)
        new.activate("NEW")
        #expect(new.activate("YES") == "unsupported:new")
        let save = try options(Options.save)
        #expect(save.activate("NEW") == nil, "no New Game while saving")
        #expect(save.key("ESCAPE") == "cancel")
        #expect(save.activate("SAVE") == nil, "a closed dialog ignores input")
    }

    /// After a death (FORCERELOAD: MUST_RELOAD only) no way out of a sub-screen closes the dialog: the callback turns OK, Cancel and No into
    /// Escape, which with MUST_RELOAD shows the exit prompt; Escape on that prompt goes to the main panel (1280_callbacks.c). Closing it
    /// left a dead Lex with no dialog and no key that works.
    @Test func theReloadDialogStaysOpenUntilALoad() throws {
        let o = try options(Options.mustReload)
        func check(_ step: String) { #expect(!o.closed, "\(step) closed the reload dialog") }
        #expect(o.key("ESCAPE") == nil && o.screen == "confirm"); check("Escape on the main panel")
        #expect(o.key("ESCAPE") == nil && o.screen == "main", "Escape on the exit prompt goes back to the main panel"); check("Escape on the prompt")
        o.activate("RETURN"); check("Return")
        o.activate("LOAD"); o.activate("CANCEL"); check("Load, Cancel"); #expect(o.screen == "confirm")
        o.activate("NO"); check("No on the exit prompt")
        o.key("ESCAPE"); o.activate("LOAD"); o.key("ESCAPE"); check("Load, Escape")
        o.key("ESCAPE"); o.activate("AUDIO"); o.activate("OK"); check("Audio, OK")
        o.key("ESCAPE"); o.activate("GAMMA"); o.activate("CANCEL"); check("Gamma, Cancel")
        o.key("ESCAPE"); o.activate("CREDITS"); _ = o.update(); o.key("ESCAPE"); check("Credits, Escape")
        o.key("ESCAPE"); o.activate("CREDITS"); _ = o.update(); o.activate("RETURN"); check("Credits, Return")
        o.key("ESCAPE"); o.activate("LOAD"); o.activate("OK")
        #expect(o.activate("YES") == "load:1" && o.closed, "a load closes it")
        let new = try options(Options.mustReload)
        new.activate("LOAD"); new.activate("NEW")
        #expect(new.activate("YES") == "unsupported:new", "New Game is the other way out (World.newGameRequested)")
    }

    @Test func cancelOnTheSlotsGoesBackToTheMainPanel() throws {
        let o = try options(Options.defaultFlag)
        o.activate("LOAD")
        #expect(o.activate("CANCEL") == "cancel" && o.screen == "main" && !o.closed, "LCAX with _OPTS_DEFAULT: the main panel (1280_callbacks.c)")
        o.activate("LOAD")
        #expect(o.key("ESCAPE") == "cancel" && o.closed, "Escape still closes the dialog")
    }

    /// What the dialog applied, in order.
    final class Applied { var audio: [[Int]] = [], gamma: [Int] = [] }
    final class Counter: @unchecked Sendable { var count = 0 }

    func panels(_ settings: Settings, _ flags: Int = Options.defaultFlag) throws -> (Options, Applied) {
        let applied = Applied()
        let o = try Options(game: requireGame(), settings: settings, applyAudio: { applied.audio.append([$0, $1]) }, applyGamma: { applied.gamma.append($0) })
        o.open(flags)
        return (o, applied)
    }

    @Test func audioPanelStepsTogglesAndApplies() throws {
        let settings = Settings(sound: 60, music: 30, subtitles: true)
        let (o, applied) = try panels(settings, Options.audio)
        #expect(o.screen == "audio" && o.sfx == 60 && o.music == 30)
        #expect(o.activate("SFMX") == "audio:50,30" && o.activate("MSPX") == "audio:50,40")
        #expect(applied.audio == [[50, 30], [50, 40]])
        for _ in 0..<6 { o.activate("SFPX") }
        #expect(o.sfx == 100)
        for _ in 0..<6 { o.activate("MSMX") }
        #expect(o.music == 0)
        #expect(settings.sound == 60, "nothing is persisted before OK")
        #expect(o.activate("SFXX") == "audio:0,0" && o.activate("SFXX") == "audio:100,0")
        #expect(o.activate("MSCX") == "audio:100,100")
        #expect(applied.audio.last == [100, 100])
        #expect(o.activate("SBTX") == nil)
        #expect(o.activate("AOKX") == "audio:100,100" && o.closed)
        #expect(settings.sound == 100 && settings.music == 100 && !settings.subtitles)
    }

    @Test func audioOKReturnsToMainAndCancelRestores() throws {
        let settings = Settings(sound: 60, music: 30)
        let counter = Counter()
        settings.onChange = { counter.count += 1 }
        let (o, applied) = try panels(settings)
        o.activate("AUDX"); o.activate("SFMX"); o.activate("MSCX")
        #expect(o.activate("AOKX") == "audio:50,0")
        #expect(settings.sound == 50 && settings.music == 0 && counter.count == 1)
        #expect(o.screen == "main" && !o.closed, "opened with _OPTS_DEFAULT: back to the main panel")
        o.activate("AUDX"); o.activate("SFXX"); o.activate("MSPX")
        #expect(o.activate("ACAX") == "cancel")
        #expect(applied.audio.last == [50, 0] && settings.sound == 50 && settings.music == 0 && counter.count == 1)
        #expect(o.screen == "main" && !o.closed)
        let (esc, escApplied) = try panels(Settings(), Options.audio)
        esc.activate("SFPX"); esc.activate("SFMX")
        #expect(esc.key("ESCAPE") == "cancel" && esc.closed && escApplied.audio.last == [100, 100])
    }

    @Test func silentEffectsForceSubtitlesOn() throws {
        let off = Settings(subtitles: false)
        let (o, _) = try panels(off, Options.audio)
        o.activate("SFXX")                                           // FUN_1280_0803(1): SBTX goes to state 3
        o.activate("AOKX")
        #expect(off.subtitles, "level 0 forced subtitles on")
        let (p, _) = try panels(Settings(sound: 0, subtitles: false), Options.audio)
        p.activate("AOKX")
        #expect(!p.settings.subtitles, "opening a silent panel does not change the switch")
        let toggled = Settings(subtitles: true)
        let (q, _) = try panels(toggled, Options.audio)
        q.activate("SBTX"); q.activate("AOKX")
        #expect(!toggled.subtitles)
    }

    @Test func gammaPanelStepsPersistsAndRestores() throws {
        let settings = Settings(gamma: 40)
        let (o, applied) = try panels(settings)
        o.activate("GMAX")
        #expect(o.screen == "gamma" && o.gamma == 40)
        #expect(o.activate("GMPX") == "gamma:50" && applied.gamma == [50])
        for _ in 0..<8 { o.activate("GMPX") }
        #expect(o.gamma == 100)
        for _ in 0..<11 { o.activate("GMMX") }
        #expect(o.gamma == 0 && applied.gamma.last == 0 && settings.gamma == 40)
        o.activate("GMPX"); o.activate("GMPX"); o.activate("GMPX")
        #expect(o.activate("AOKX") == "gamma:30")
        #expect(settings.gamma == 30 && applied.gamma.last == 30 && o.screen == "main" && !o.closed)
        o.activate("GMAX"); o.activate("GMPX"); o.activate("GMPX")
        #expect(applied.gamma.last == 50)
        #expect(o.activate("ACAX") == "cancel")
        #expect(settings.gamma == 30 && applied.gamma.last == 30 && o.screen == "main")
        o.activate("GMAX")
        #expect(o.key("ESCAPE") == "cancel" && o.screen == "main")
    }

    @Test func clickActivatesTheControlUnderThePointer() throws {
        let o = try options(Options.difficulty)
        #expect(o.pointerMove(x: 0, y: 0) == nil && o.hovered == nil)
        var spot: (x: Int, y: Int)?
        search: for y in 0..<200 { for x in 0..<320 where o.pointerMove(x: x, y: y) == "HRDX" { spot = (x, y); break search } }
        let hit = try #require(spot)
        #expect(o.hovered == "HRDX")
        #expect(o.click(x: hit.x, y: hit.y) == "difficulty:2" && o.closed)
    }

    private func hardSpot(_ o: Options) throws -> (x: Int, y: Int) {
        var spot: (x: Int, y: Int)?
        search: for y in 0..<200 { for x in 0..<320 where o.pointerMove(x: x, y: y) == "HRDX" { spot = (x, y); break search } }
        return try #require(spot)
    }

    @Test func theBarUnderThePointerIsDrawnHighlighted() throws {
        // FUN_1250_19bc: the control under the pointer goes to state 2 (FUN_1278_0803), a brighter bar (frame 2) and brighter label text;
        // moving to another moves the highlight, moving off every control takes it away (FUN_1278_0844). test_options.py has the same.
        let o = try options(Options.difficulty)
        o.monitor.setPointerFrame(0)                             // the hand is not drawn: only the bars differ
        let bars = ["EZYX", "MEDX", "HRDX"]
        func frames() -> [Int?] { bars.map { o.elementFrame($0) } }
        func render() -> [UInt8] { var fb = Framebuffer(); o.render(into: &fb); return fb.pixels }
        o.pointerMove(x: 0, y: 14)
        let plain = render()
        #expect(frames() == [1, 1, 1])
        let med = o.monitor.centre("MEDX")
        o.pointerMove(x: med.x, y: med.y)
        #expect(frames() == [1, 2, 1] && o.buttonState("MEDL") == 2)
        let lit = render()
        let rows = Set(lit.indices.filter { lit[$0] != plain[$0] }.map { $0 / 320 })
        #expect(!rows.isEmpty && rows.allSatisfy { abs($0 - med.y) < 10 }, "only the hovered bar changes")
        let hard = try hardSpot(o)
        o.pointerMove(x: hard.x, y: hard.y)
        #expect(frames() == [1, 1, 2])
        o.pointerMove(x: 0, y: 14)
        #expect(frames() == [1, 1, 1] && render() == plain)
    }

    @Test func aPanelOpensWithTheControlUnderThePointerHighlighted() throws {
        // FUN_1258_0512 runs FUN_1250_19bc for each button it defines. A default (state 2) takes the focus and the pointer until the mouse
        // has moved ([9dca] & 2), then starts normal.
        let o = try options(Options.defaultFlag)
        let extx = o.monitor.centre("EXTX")
        #expect(o.elementFrame("EXTX") == 2 && o.monitor.pointerPosition == extx && o.takeMouseWarp().map { $0 == extx } == true)
        o.pointerMove(x: 0, y: 14)
        #expect(o.elementFrame("EXTX") == 1)
        o.open(Options.difficulty)
        let hard = try hardSpot(o)
        o.open(Options.defaultFlag)                            // the mouse has moved: EXTX starts normal and the pointer stays
        #expect(o.elementFrame("EXTX") == 1 && o.monitor.pointerPosition == hard)
        o.open(Options.difficulty)                               // the bar under the pointer is lit at once
        #expect(["EZYX", "MEDX", "HRDX"].map { o.elementFrame($0) } == [1, 1, 2])
    }

    @Test func aSelectedToggleKeepsItsSelectionUnderTheHighlight() throws {
        // Mode 1 buttons (SFXX, MSCX, SBTX): the highlight turns 3 into 4 and taking it away gives 3 back; a plain button goes back to 1.
        let o = try Options(game: requireGame(), settings: Settings(sound: 60, music: 30, subtitles: true))
        o.open(Options.audio)
        #expect(o.elementFrame("SFXX") == 3)
        let sfx = o.monitor.centre("SFXX")
        o.pointerMove(x: sfx.x, y: sfx.y)
        #expect(o.elementFrame("SFXX") == 4 && o.elementFrame("AOKX") == 1)
        o.pointerMove(x: 0, y: 14)
        #expect(o.elementFrame("SFXX") == 3)
    }

    @Test func pointerClickThroughThePressAnimationActivatesTheControlOnTick6() throws {
        let o = try options(Options.difficulty)
        let hit = try hardSpot(o)
        o.pointerMove(x: hit.x, y: hit.y); o.mouseDown(); o.mouseUp()
        var ticks: [(Int, String)] = []
        for t in 1...12 { for a in o.update() { ticks.append((t, a)) } }
        #expect(ticks.count == 1 && ticks[0].0 == 6 && ticks[0].1 == "difficulty:2" && o.closed, "pressed on tick 5, activated by the release on tick 6")
    }

    @Test func heldMouseKeepsThePointerUntilTheRelease() throws {
        // FUN_1250_0415: input is off from the press to the release, so a held mouse can't drag the hand off the control (test_options.py)
        let o = try options(Options.difficulty)
        let hit = try hardSpot(o)
        o.pointerMove(x: hit.x, y: hit.y); o.mouseDown()
        for _ in 0..<6 { #expect(o.update().isEmpty) }          // pressed on tick 5, the hold ends on tick 6
        o.pointerMove(x: 0, y: 0)
        #expect(o.key("ESCAPE") == nil && !o.closed, "keys are dropped too")
        o.mouseUp()
        let warp = try #require(o.takeMouseWarp())
        #expect(warp == hit, "the release puts the mouse on the hand")
        var got: [String] = []
        for _ in 0..<12 { got += o.update() }
        #expect(got == ["difficulty:2"])
    }

    @Test func worldSettingsDefaultToTheEngineDefaults() throws {
        let r = try Run(level: "CHAOS")
        let w = r.world
        #expect(w.settings.sound == 100 && w.settings.music == 100 && w.settings.gamma == 30 && w.settings.subtitles)
        #expect(w.gamma == 30 && w.sfxLog.map(\.sfx) == [100] && w.musicInitial == 100 && w.musicVolLog.isEmpty)
        w.configureSettings(Settings(sound: 20, music: 0, gamma: 50))
        #expect(w.gamma == 50 && w.sfxLog.map(\.sfx) == [20] && w.musicInitial == 0)
    }

    @Test func theDialogUsesTheWorldSettings() throws {
        let r = try Run(level: "CHAOS")
        let w = r.world
        r.tick(7)
        w.optionsOpenForTest(Options.defaultFlag)
        w.optionActivate("AUDX"); w.optionActivate("SFMX"); w.optionActivate("MSMX"); w.optionActivate("AOKX")
        #expect(w.settings.sound == 90 && w.settings.music == 90)
        #expect(w.sfxLog.map { [$0.tick, $0.sfx] } == [[0, 100], [8, 90]] && w.musicVolLog.map { [$0.tick, $0.music] } == [[7, 90]])
        w.optionActivate("GMAX"); w.optionActivate("GMMX")
        #expect(w.gamma == 20)
        w.optionActivate("ACAX")
        #expect(w.gamma == 30)
        #expect(w.optionActions.suffix(3).map(\.action) == ["audio:90,90", "gamma:20", "cancel"])
        #expect(w.warnings.isEmpty)
    }

    @Test func detailDoesNothing() throws {
        let r = try Run(level: "CHAOS")
        r.world.optionsOpenForTest(Options.defaultFlag)
        #expect(r.world.optionActivate("DETX") == nil)
        #expect(r.world.options?.screen == "main" && r.world.warnings.isEmpty && r.world.optionActions.isEmpty)
    }

    @Test func silentEffectsStopEveryVoice() throws {
        let r = try Run(level: "CHAOS")
        let w = r.world
        let h = w.playSound(0, volume: 255, loop: true)
        #expect(r.vm.process(h) != nil)
        w.applyAudio(sfx: 0, music: 100)
        #expect(r.vm.process(h) == nil || r.vm.process(h)!.done)
        #expect(w.soundStops.map { [$0.tick, $0.handle] } == [[0, h]])
        #expect(w.sfxLog.map { [$0.tick, $0.sfx] } == [[0, 100], [1, 0]])
        w.applyAudio(sfx: 0, music: 100)
        #expect(w.sfxLog.count == 2, "no change: nothing is logged")
    }

    @Test func gammaKeysStepPersistAndStopAtTheLimits() throws {
        let r = try Run(level: "CHAOS")
        let w = r.world
        let counter = Counter()
        w.settings.onChange = { counter.count += 1 }
        func press(_ scan: Int, _ mods: Int) { w.keyDown(scan, mods: mods); w.keyUp(scan, mods: mods) }
        press(0x34, Keys.shift)                                       // Shift + .
        #expect(w.settings.gamma == 40 && w.gamma == 40 && counter.count == 1)
        press(0x33, Keys.alt); press(0x4a, Keys.shift)                // Alt + , and Shift + numpad -
        #expect(w.settings.gamma == 20 && w.gamma == 20)
        press(0x4e, Keys.alt)
        #expect(w.settings.gamma == 30)
        press(0x34, 0)                                                // no modifier: not a gamma key
        #expect(w.settings.gamma == 30)
        for _ in 0..<12 { press(0x34, Keys.shift) }
        #expect(w.settings.gamma == 100 && w.gamma == 100)
        for _ in 0..<12 { press(0x33, Keys.shift) }
        #expect(w.settings.gamma == 0 && w.gamma == 0)
        #expect(w.keyLog.prefix(2).map { [$0.action, String(describing: $0.detail)] } == [["gamma", "int(10)"], ["gamma", "int(-10)"]])
    }

    @Test func subtitlesSwitchHidesTheCaption() throws {
        let r = try Run(level: "CHAOS")
        let w = r.world
        w.subtitleLog.append(SubtitleEvent(tick: 0, handle: 1, colour: 5, text: "HELLO", end: 100))
        var on = Framebuffer(), off = Framebuffer()
        w.renderPresentation(into: &on)
        w.settings.subtitles = false
        w.renderPresentation(into: &off)
        #expect(on.pixels != off.pixels)
        var bare = Framebuffer()
        w.render(into: &bare)
        #expect(off.pixels == bare.pixels)
    }

    @Test func openingDifficultyDialogSetsTheLevelAndResumesTheScheduler() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources)
        session.autoDifficulty = false
        var ticks = 0
        while !(session.world.options.map { !$0.closed && $0.screen == "difficulty" } ?? false) && ticks < 40_000 { session.tick(); ticks += 1 }       // the intro plays first
        #expect(session.world.isOptionsOpen && session.world.paused)
        #expect(session.world.options?.flags == Options.difficulty)
        var frame = Framebuffer()
        session.world.renderPresentation(into: &frame)
        #expect(sha(frame.pixels) == "a37faa73f7b8d05efb42b24ad3a14574116d491a5489b854ba901e69f3121254", "the dialog is the player-facing frame, over the greyed TITLE picture (CAMERA SHOW TITLE); EASY is lit under the pointer")
        let tick = session.vm.tick
        session.tick()
        #expect(session.vm.tick == tick, "the scheduler stands still while the dialog is open")

        // EASY's element centre: scan for the control the pointer reports.
        var click: (Int, Int)?
        search: for y in 0..<200 { for x in 0..<320 where session.world.optionPointerMove(x: x, y: y) == "EZYX" { click = (x, y); break search } }
        let point = try #require(click)
        #expect(!session.pictureHoldDue(), "no hold while the dialog is up")
        #expect(session.world.optionClick(x: point.0, y: point.1) == "difficulty:0")
        #expect(session.world.optionActions.last?.action == "difficulty:0")
        #expect(session.vm.globals["_difficulty_level"] == .int(0))
        #expect(!session.world.isOptionsOpen)
        // CAMERA SHOW TITLE (10d0:115c) put the screen on the TITLE picture: it shows, undimmed, until LOADLEVEL CHAOS, and GOODMORNINGLEX's
        // FADE HIDE turns it black in the same tick (test_world.py has the same).
        var after = Framebuffer()
        session.world.renderPresentation(into: &after)
        let title = try #require(session.world.shownPictureFrame())
        #expect(session.world.shownPicture == "TITLE" && after.pixels == title.pixels && after.palette == title.palette, "the red BioForge picture")
        #expect(session.pictureHoldDue() && !session.pictureHoldDue(), "the app holds the picture once, before the tick that loads CHAOS")
        for _ in 0..<2_000 where session.world.player == nil { session.tick() }
        #expect(session.world.player != nil, "the opening carries on to create Lex")
        #expect(session.world.shownPicture == nil, "LOADLEVEL ends the picture")
    }

    @Test func aShowPictureReplacesTheRoomOnScreen() throws {
        // CAMERA SHOW <cam> switches the screen to the picture camera. WARHEAD's RTRW is one colour (121) over the whole screen: the white
        // flash BLAST_LEX shows until KILLLEX's STITLE. test_world.py has the same.
        let r = try Run(level: "CHAOS")
        let w = r.world
        var room = Framebuffer(), shown = Framebuffer()
        w.renderPresentation(into: &room)
        w.shownPicture = "RTRW"
        let flash = try #require(w.shownPictureFrame())
        #expect(Set(flash.pixels) == [121])
        w.renderPresentation(into: &shown)
        #expect(shown.pixels == flash.pixels && shown.palette == flash.palette && shown.pixels != room.pixels)
        w.shownPicture = nil
        w.renderPresentation(into: &shown)
        #expect(shown.pixels == room.pixels)
    }
}

extension World {
    /// MON_CODE <flags>: opens the dialog on the world's settings (as the script command does).
    func optionsOpenForTest(_ flags: Int) {
        options = try? Options(game: game, settings: settings, applyAudio: { [unowned self] in applyAudio(sfx: $0, music: $1) },
                               applyGamma: { [unowned self] in applyGamma($0) })
        _ = options?.open(flags)
    }
}

@Suite struct SettingsTests {
    @Test func installOptParsingIsCaseInsensitiveWithDefaults() {
        let s = Settings(installOpt: "Dir=C:\\BIOFORGE\r\nSOUNDVOL=40\r\nmusicvol = 70\r\nGamma=50\r\nSubtitles=0\r\n")
        #expect(s.sound == 40 && s.music == 70 && s.gamma == 50 && !s.subtitles)
        let d = Settings(installOpt: "Dir=C:\\BIOFORGE\r\n")
        #expect(d.sound == 100 && d.music == 100 && d.gamma == 30 && d.subtitles)
        #expect(Settings(installOpt: "soundvol=loud\r\n").sound == 100)
        #expect(Settings.parseInstallOpt("A=1\nnonsense\n b = 2 \n") == ["a": "1", "b": "2"])
    }

    @Test func theGogFileHasGamma50() throws {
        guard let g = game else { return }
        let s = Settings.load(game: g)
        #expect(s.sound == 100 && s.music == 100 && s.gamma == 50 && s.subtitles)
        #expect(Settings.load(game: GameFolder(URL(fileURLWithPath: "/nonexistent"))).gamma == 30)
    }

    @Test func userDefaultsWinWhenPresent() throws {
        let suite = "BioForgeTests-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let s = Settings(sound: 80, music: 70, gamma: 50, subtitles: true)
        s.apply(defaults: defaults)
        #expect(s.sound == 80 && s.music == 70 && s.gamma == 50 && s.subtitles, "an empty store changes nothing")
        let changed = Settings(sound: 10, music: 0, gamma: 90, subtitles: false)
        changed.save(to: defaults)
        s.apply(defaults: defaults)
        #expect(s.sound == 10 && s.music == 0 && s.gamma == 90 && !s.subtitles)
    }

    @Test func gammaOffsetIsCDivision() {
        #expect([0, 10, 30, 50, 100].map(Gamma.offset) == [-9, -6, 0, 6, 22])
    }

    @Test func gammaWorksOn6BitValuesAndClamps() {
        func expand(_ c: Int) -> Int { c * 255 / 63 }
        let up = Gamma.lut(50), down = Gamma.lut(0)                   // +6 / -9 on the 6-bit scale
        #expect([0, 10, 57, 63].map { Int(up[expand($0)]) } == [6, 16, 63, 63].map(expand))
        #expect([0, 9, 10, 63].map { Int(down[expand($0)]) } == [0, 0, expand(1), expand(54)])
        #expect((0..<64).map { Int(Gamma.lut(30)[expand($0)]) } == (0..<64).map(expand), "30 is the identity")
        var palette = [UInt8](repeating: 0, count: 768)
        palette[0] = UInt8(expand(10)); palette[767] = 255
        let shifted = Gamma.apply(to: palette, gamma: 50)
        #expect(Int(shifted[0]) == expand(16) && shifted[1] == UInt8(expand(6)) && shifted[767] == 255)
    }

    @Test func tablesMatchThePrototype() {
        #expect(sha(stride(from: 0, through: 100, by: 5).flatMap { Gamma.lut($0) }) == "ae34d7481e4f14fb27c992c31c1961c3fbc9bbb8dfa03f01695845c951ccc3c3")
        let text = [0, 1, 25, 50, 99, 100].map { MasterVolume.table($0).map(String.init).joined(separator: ",") + "\n" }.joined()
        #expect(sha(Array(text.utf8)) == "a24bcbe1577fa0354daab1c04a8d5ddaea852a2dd9d9a5839f37fc9449a794ba")
    }

    @Test func masterVolumeTable() {
        let full = MasterVolume.table(100)
        #expect(full[0] == 0 && full[128] == 127 && full[255] == 254)         // (i * 255) >> 8
        let half = MasterVolume.table(50)                                      // v = 50 * 255 / 100 = 127
        #expect(half[255] == 126 && half[200] == 99)
        #expect(MasterVolume.table(1)[255] == 1)                               // v = 2: (255 * 2) >> 8
        #expect(MasterVolume.table(0) == [Int](repeating: 0, count: 256), "sfx < 1: effects disabled")
    }
}

/// The credits roll against re/out/credits_live/SPEC.md (the original's VGA dumps) and options.py's CreditsRollTests: the same pixel facts.
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct CreditsRollTests {
    func credits() throws -> Options { let o = try Options(game: requireGame()); o.open(Options.credits); return o }

    /// The roll at `pos` over a field of 255s -> (pixels, rows with text).
    func roll(_ o: Options, _ pos: Int) -> (px: [UInt8], rows: [Int]) {
        var fb = Framebuffer()
        fb.clear(255)
        o.drawCredits(into: &fb, at: pos)
        let rows = (0..<200).filter { r in (0..<320).contains { fb.pixels[r * 320 + $0] != 255 } }
        return (fb.pixels, rows)
    }
    func colours(_ px: [UInt8], row: Int) -> Set<Int> { Set(px[row * 320..<(row + 1) * 320].filter { $0 != 255 }.map(Int.init)) }
    func columns(_ px: [UInt8], rows: ClosedRange<Int>) -> [Int] { (0..<320).filter { c in rows.contains { px[$0 * 320 + c] != 255 } } }

    @Test func lineModelAndEndPosition() throws {
        let o = try credits()
        #expect(o.creditsLines.count == 251 && Options.creditsDone(251) == 2784)
        #expect(String(decoding: o.creditsLines[18].text, as: UTF8.self) == "BIOFORGE" && o.creditsLines[18].heading)
        #expect(String(decoding: o.creditsLines[19].text, as: UTF8.self) == "A Ken Demarest Game" && !o.creditsLines[19].heading)
        let lines = Options.creditsLines(Array("X\n\nY\nZ\n\n\n\nW\u{0}".utf8)).map { String(decoding: $0.text, as: UTF8.self) }
        #expect(lines == ["X", "Y", "Z", "", "W"])
    }

    @Test func firstTextScrollsInFromTheBottom() throws {
        let o = try credits()
        let a = roll(o, 22)                                              // BIOFORGE's baseline at 8 + 12 * 18 - 22 = 202: only its top rows show
        #expect(a.rows.first == 196 && a.rows.last == 199)
        #expect(Set(a.px.filter { $0 != 255 }.map(Int.init)) == [0, 200])
        let b = roll(o, 52)
        #expect(b.rows.first == 166 && b.rows.last == 185)
        #expect((166...172).allSatisfy { colours(b.px, row: $0).isSubset(of: [0, 200]) })
    }

    @Test func endPicture() throws {
        let o = try credits()
        let e = roll(o, 2784)
        #expect(e.rows.first == 86 && e.rows.last == 130)
        #expect(colours(e.px, row: 86) == [200] && colours(e.px, row: 92) == [0, 200] && colours(e.px, row: 93) == [0])
        for baseline in [104, 116, 128] { #expect(colours(e.px, row: baseline).contains(249)) }
        #expect(columns(e.px, rows: 86...86).first == 132)
        let c = columns(e.px, rows: 116...116)
        #expect(c.first == 63 && c.last == 250)
    }

    @Test func tabFieldsStartAtTheStops() throws {
        let o = try credits()
        let t = roll(o, 8 + 12 * 148 - 100)                              // line 148 "\tFrench\tDominique Poumeyrol" on baseline 100
        let c = columns(t.px, rows: 94...100)
        #expect(c.first == 61 && c.contains(181) && !c.contains { (110..<181).contains($0) })
        #expect((94...100).allSatisfy { colours(t.px, row: $0).isSubset(of: [0, 249]) })
    }

    @Test func statesAndKeyLockout() throws {
        let o = try credits()
        let done = Options.creditsDone(o.creditsLines.count)
        #expect(o.creditsState == 0 && o.creditsPos == 0 && o.creditsLockout)
        #expect(o.key("ESCAPE") == nil)
        _ = o.update()
        #expect(o.creditsState == 1 && o.creditsPos == 1 && !o.creditsLockout)
        for _ in 0..<(done - 1) { _ = o.update() }
        #expect(o.creditsState == 1 && o.creditsPos == done, "the update that reaches the end still reports 1")
        _ = o.update(); _ = o.update()
        #expect(o.creditsState == 2 && o.creditsPos == done, "state 2 from the next update, the picture stays")
        #expect(o.key("ESCAPE") == "return")
    }
}
