// The language setting (E / G / F, INSTALL.OPT `language=`) against re/interp/test_language.py: the caption and monitor text filter, GETOPTDATA("LANGUAGE"),
// the sound bank, the monitor text file, the options dialog text and the intro movie, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

struct LanguageSettingsTests {
    @Test func captionFilterFollowsTheLanguage() {
        let s = "/FBonjour/EHello/GHallo"
        #expect(["E", "G", "F"].map { Presentation.captionText(s, language: $0) } == ["Hello", "Hallo", "Bonjour"])
        #expect(Presentation.captionText("/EHello/GHallo", language: "F") == "Hello")       // no /F: the English segment
        #expect(Presentation.captionText("Yep", language: "G") == "Yep")                    // no segments: the whole string
        #expect(Presentation.captionText("/!", language: "G") == "")
    }

    @Test func installOptLanguage() {
        #expect(Settings(installOpt: "Language=G\r\n").language == "G")
        #expect(Settings(installOpt: "language=f\r\n").language == "F")
        #expect(Settings(installOpt: "Dir=C:\\BIOFORGE\r\n").language == "E")
        #expect(Settings(installOpt: "language=X\r\n").language == "E")
    }

    @Test func languageRoundTripsThroughDefaults() throws {
        let suite = "BioForgeLanguageTests"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        Settings(language: "G").save(to: defaults)
        let s = Settings(installOpt: "language=E\r\n")
        s.apply(defaults: defaults)
        #expect(s.language == "G")
        defaults.set("X", forKey: Settings.defaultsKeys.language)                          // an unknown value is ignored
        let t = Settings(language: "F")
        t.apply(defaults: defaults)
        #expect(t.language == "F")
    }
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct LanguageTests {
    @Test func getoptdataLanguageIsTheSetting() throws {
        let w = try World(resources: try #require(worldResources), level: "LANDPAD")
        w.setLanguage("G")
        #expect(["LANGUAGE", "language", "Soundvol"].map { w.installOption($0) } == [71, 71, 100] as [Int])
        w.setLanguage("F")
        #expect(w.installOption("LANGUAGE") == 70)
    }

    @Test func soundBankPerLanguage() throws {
        let res = try #require(worldResources)
        let english = res.soundBank("E"), german = res.soundBank("G")
        #expect((english.samples.count, german.samples.count) == (717, 717))
        #expect(german.samples[0].length == 11022)                 // GSAMPLES.FLX, not ESAMPLES.FLX
        #expect(english.samples[0].length == 16054)
        let w = try World(resources: res, level: "LANDPAD")
        w.setLanguage("G")
        #expect(w.soundBank.samples[0].length == 11022)
    }

    @Test func monitorTextFilePerLanguage() throws {
        let screen = try MonitorScreen(name: "OPTS", game: requireGame())
        #expect(screen.rawText("ORRESULT")?.contains("PROJECT AFA") == true)
        screen.language = "G"
        #expect(screen.rawText("ORRESULT")?.contains("Selbstmord") == true)
        screen.defineText("EZYL", "EXIT/FSORTIE/GZUR\u{9a}CK")
        #expect(screen.elementText("EZYL") == "ZUR\u{9a}CK")
        screen.language = "F"                                      // a shown text is filtered again
        #expect(screen.elementText("EZYL") == "SORTIE")
    }

    @Test func optionsTextPerLanguage() throws {
        let o = try Options(game: requireGame(), settings: Settings(language: "G"))
        o.open(Options.difficulty)
        #expect(o.elementText("EZYX") == "EINFACHER KAMPF")
        let e = try Options(game: requireGame())
        e.open(Options.difficulty)
        #expect(e.elementText("EZYX") == "EASY COMBAT")
    }

    @Test func spokenSubtitlesShowAndTimeTheLanguageText() throws {
        for (language, shown) in [("E", "Hello"), ("G", "H\u{84}llo w\u{94}rld"), ("F", "Bonjour")] {
            let w = try World(resources: try #require(worldResources), level: "LANDPAD")
            let vm = ScriptVM(engine: w, defs: try ScriptDefs(game: requireGame()))
            w.setLanguage(language)
            _ = w.subtitle([.str("_pim_beep_5"), .int(0x75), .int(0xff), .str("Hello/FBonjour/GH\u{84}llo w\u{94}rld")], minor: false)
            let e = try #require(w.subtitleLog.first)
            let bank = w.soundBank
            let n = bank.samples[try #require(bank.ids["_pim_beep_5"])].length
            withExtendedLifetime(vm) {}
            #expect(e.text == shown && e.end - e.tick == n * 30 / 11025 + shown.unicodeScalars.count)
        }
    }

    @Test func newGameStartsTheLanguageIntro() throws {
        for (language, flic) in [("E", "INTRO"), ("G", "INTROG"), ("F", "INTROF")] {
            let s = try GameSession.newGame(resources: try #require(worldResources)) { $0.world.configureSettings(Settings(language: language)) }
            var n = 0
            while s.world.show.flic == nil && n < 600 { s.tick(); n += 1 }
            #expect(s.world.show.flic?.name == flic)
        }
    }
}
