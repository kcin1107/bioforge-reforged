import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

@MainActor
private final class FakeHost: SettingsScreenHost {
    var sets: [String] = []
    var fullScreen = false { didSet { sets.append("fullScreen \(fullScreen)") } }
    var correctAspect = true { didSet { sets.append("correctAspect \(correctAspect)") } }
    var music: MusicArrangement? = .adlib { didSet { sets.append("music \(music?.rawValue ?? "off")") } }
    var musicNote: String?
    var muted = false { didSet { sets.append("muted \(muted)") } }
    var language = "E" { didSet { sets.append("language \(language)") } }
    var readableText = false { didSet { sets.append("readableText \(readableText)") } }
    var keyBindings = KeyBindings() { didSet { sets.append("keyBindings") } }
    var padBindings = PadBindings() { didSet { sets.append("padBindings") } }
    func keyName(_ usage: UInt16) -> String { "K\(usage)" }
    func padLabel(_ b: PadButton) -> String { b.title }
}

@MainActor
private func screen(_ host: FakeHost = FakeHost()) -> (SettingsScreen, FakeHost) {
    let s = SettingsScreen(host: host)
    s.open()
    return (s, host)
}

@MainActor
struct SettingsScreenTests {
    private func go(_ s: SettingsScreen, to row: Int) { for _ in 0..<row { s.handle(.down) } }

    @Test func navigationWrapsAround() {
        let (s, _) = screen()
        #expect(s.isOpen && s.page == .main && s.cursor == 0)
        s.handle(.up)
        #expect(s.cursor == SettingsScreen.mainRows.count - 1)
        s.handle(.down)
        #expect(s.cursor == 0)
    }

    @Test func everyMainRowReachesTheHost() {
        let (s, h) = screen()
        s.handle(.right); #expect(h.fullScreen)
        s.handle(.left); #expect(!h.fullScreen)
        s.handle(.down); s.handle(.activate); #expect(!h.correctAspect)
        s.handle(.down); s.handle(.right); #expect(h.music == nil)
        s.handle(.right); #expect(h.music == .generalMIDI)
        s.handle(.right); #expect(h.music == .adlib)
        s.handle(.left); #expect(h.music == .generalMIDI)
        s.handle(.left); #expect(h.music == nil)
        s.handle(.left); #expect(h.music == .adlib)
        s.handle(.down); s.handle(.activate); #expect(h.muted)
        s.handle(.down); s.handle(.right); #expect(h.language == "G")
        s.handle(.right); #expect(h.language == "F")
        s.handle(.right); #expect(h.language == "E")
        s.handle(.left); #expect(h.language == "F")
        s.handle(.down); s.handle(.right); #expect(h.readableText)
        #expect(s.cursor == 5)
    }

    @Test func rowsOpenPagesAndDoneCloses() {
        let (s, _) = screen()
        go(s, to: 6); s.handle(.activate)
        #expect(s.page == .keys && s.cursor == 0)
        s.handle(.back)
        #expect(s.page == .main && s.cursor == 6)
        s.handle(.down); s.handle(.activate)
        #expect(s.page == .pad)
        s.handle(.back)
        s.handle(.down); s.handle(.activate)
        #expect(!s.isOpen)
        s.open(); s.handle(.back)
        #expect(!s.isOpen)
    }

    @Test func theKeysPageScrollsToTheCursor() {
        let (s, _) = screen()
        go(s, to: 6); s.handle(.activate)
        #expect(s.rowCount == KeyBindings.controls.count + 2 && s.top == 0)
        for _ in 0..<(s.capacity + 3) { s.handle(.down) }
        #expect(s.cursor == s.capacity + 3 && s.top == 4)          // the cursor is the last row shown
        s.handle(.up)
        #expect(s.top == 4)
        for _ in 0..<10 { s.handle(.up) }
        #expect(s.cursor == 4 && s.top == 4)
        s.handle(.up)
        #expect(s.cursor == 3 && s.top == 3)
        for _ in 0..<3 { s.handle(.up) }
        s.handle(.up)                                              // wraps to the last row, which scrolls into view
        #expect(s.cursor == s.rowCount - 1 && s.top == s.rowCount - s.capacity)
        s.handle(.down)
        #expect(s.cursor == 0 && s.top == 0)
    }

    @Test func capturingAKeyBindsIt() {
        let (s, h) = screen()
        go(s, to: 6); s.handle(.activate)
        s.handle(.right); s.handle(.activate)                   // Walk Forward, second slot
        #expect(s.capturing == .key("forward", 1))
        s.captureKey(0x05)                                       // B
        #expect(s.capturing == nil && h.keyBindings.key("forward", slot: 1) == 0x05 && h.keyBindings.key("forward", slot: 0) == 0x52)
    }

    @Test func escapeCancelsAndRefusedKeysKeepTheCapture() {
        let (s, h) = screen()
        go(s, to: 6); s.handle(.activate); s.handle(.activate)
        for refused: UInt16 in [0x39, 0xE3, 0x3A, 0x44, 0] {       // Caps Lock, GUI, F1, F11, no usage
            s.captureKey(refused)
            #expect(s.capturing == .key("forward", 0) && s.message != nil)
        }
        #expect(h.keyBindings == KeyBindings())
        s.captureKey(0x29)
        #expect(s.capturing == nil && h.keyBindings == KeyBindings())
    }

    @Test func aDuplicateKeyMovesFromItsOldControl() {
        let (s, h) = screen()
        go(s, to: 6); s.handle(.activate)
        s.handle(.down); s.handle(.activate)                    // Walk Back
        s.captureKey(0x52)                                       // the up arrow, Walk Forward's
        #expect(h.keyBindings.key("back", slot: 0) == 0x52 && h.keyBindings.key("forward", slot: 0) == nil)
    }

    @Test func clearUnbindsTheSelectedSlot() {
        let (s, h) = screen()
        go(s, to: 6); s.handle(.activate)
        s.handle(.clear)
        #expect(h.keyBindings.key("forward", slot: 0) == nil && h.keyBindings.key("forward", slot: 1) == 0x60)
        s.handle(.right); s.handle(.clear)
        #expect(h.keyBindings.key("forward", slot: 1) == nil)
    }

    @Test func resetToDefaultsRestoresTheBindings() {
        let (s, h) = screen()
        go(s, to: 6); s.handle(.activate)
        s.handle(.clear)
        #expect(h.keyBindings != KeyBindings())
        s.handle(.up); s.handle(.up)                             // wraps to Reset to Defaults
        #expect(s.cursor == s.rowCount - 2)
        s.handle(.activate)
        #expect(h.keyBindings == KeyBindings() && s.page == .keys)
    }

    @Test func thePadPageHasNoDirectionsAndCapturesButtons() {
        let (s, h) = screen()
        go(s, to: 7); s.handle(.activate)
        #expect(s.page == .pad && s.rowCount == SettingsScreen.padControls.count + 2)
        #expect(SettingsScreen.padControls.allSatisfy { !PadBindings.directions.contains($0.id) })
        let id = SettingsScreen.padControls[0].id
        s.handle(.activate)
        #expect(s.capturing == .pad(id))
        s.capturePad(.leftTrigger)
        #expect(s.capturing == nil && h.padBindings.button(id) == .leftTrigger)
        s.handle(.activate); s.handle(.up)                      // a direction cancels
        #expect(s.capturing == nil && h.padBindings.button(id) == .leftTrigger)
        s.handle(.clear)
        #expect(h.padBindings.button(id) == nil)
        s.handle(.up); s.handle(.up); s.handle(.activate)
        #expect(h.padBindings == PadBindings())
    }

    // MARK: drawing

    private func gray() -> [UInt8] { (0..<320 * 200).flatMap { _ in [200, 200, 200, 255] as [UInt8] } }

    private var font: CaptionFont? {
        guard let game = hostGame else { return nil }
        return try? CaptionFont(game.read(SettingsScreen.fontFile))
    }

    @Test(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
    func drawingDimsThePictureAndWritesText() throws {
        let font = try #require(font)
        let (s, _) = screen()
        var rgba = gray()
        s.render(into: &rgba, font: font)
        #expect(rgba.count == 320 * 200 * 4)
        #expect(rgba[(190 * 320 + 300) * 4] == 50 && rgba[3] == 255)                // far from the list: the picture at a quarter
        let title = (0..<font.height + 6).flatMap { y in (0..<100).map { rgba[(y * 320 + $0) * 4] } }
        #expect(title.contains(255))                                                   // the title's glyphs
        var hash: UInt64 = 0xcbf29ce484222325
        for b in rgba { hash = (hash ^ UInt64(b)) &* 0x100000001b3 }
        #expect(String(hash, radix: 16) == "c5855835f880f32a")
    }

    @Test(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
    func theMusicNoteShowsOnlyOnTheMusicRow() throws {
        let font = try #require(font)
        let (s, h) = screen()
        func drawn() -> [UInt8] { var rgba = gray(); s.render(into: &rgba, font: font); return rgba }
        let plain = drawn()                                        // cursor on row 0
        h.musicNote = "No SoundFont (.sf2) found: AdLib plays. See the log."
        for scalar in SettingsScreen.fontScalars(h.musicNote!, font) { #expect(font.glyph(scalar) != nil, "\(scalar)") }
        #expect(drawn() == plain)
        go(s, to: 2)
        let onMusic = drawn()
        h.musicNote = nil
        #expect(drawn() != onMusic)
    }

    @Test(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
    func theAccentedNamesHaveGlyphsForEveryLetter() throws {
        let font = try #require(font)
        for name in ["Français", "Deutsch", "Straße", "Überlauf"] {
            for scalar in SettingsScreen.fontScalars(name, font) { #expect(font.glyph(scalar) != nil, "\(name): \(scalar)") }
        }
        let full = try CaptionFont(try #require(hostGame).read("DATA/1.FNT"))          // a font with the accents is indexed by CP437
        #expect(SettingsScreen.fontScalars("ç", full).first?.value == 0x87 && SettingsScreen.fontScalars("ç", font).first?.value == 0x63)
    }
}
