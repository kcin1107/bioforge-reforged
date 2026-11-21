import Testing
@testable import BioForgeCore

/// View > Readable Text: letter spacing, a drop shadow and a brighter colour, off by default.
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ReadableTextTests {
    private func render(_ monitor: MonitorScreen, readable: Bool) -> Framebuffer {
        monitor.readableText = readable
        var fb = Framebuffer()
        monitor.render(into: &fb)
        return fb
    }

    /// The positions of `colour` pixels.
    private func ink(_ fb: Framebuffer, _ colour: UInt8) -> [Int] { fb.pixels.indices.filter { fb.pixels[$0] == colour } }

    /// The first element of `kind` in `cam`: its first style colour (a text colour index) and its bounds, as MonitorScreen.Element reads them.
    private func element(_ cam: String, kind: Character) throws -> (name: String, colour: UInt8, palette: [UInt8]) {
        let file = try CAMFile(data: requireGame().read("MONITORS/\(cam).CAM"))
        for entry in file.images where entry.name.count > 3 && entry.name.uppercased().dropFirst(3).first == kind {
            let frames = try file.frames(of: entry)
            if let first = frames.dropFirst().first(where: { $0.width > 1 }), first.pixels.count > 6 { return (entry.name.uppercased(), first.pixels[0], file.palette) }
        }
        throw FormatError("no \(kind) element in \(cam)")
    }

    @Test func shadowIsTheDarkestEntryAndBrighteningNeverDarkens() throws {
        for cam in ["PIMM", "OPTS", "MLBT"] {
            let palette = try CAMFile(data: requireGame().read("MONITORS/\(cam).CAM")).palette
            func luma(_ i: Int) -> Int { 299 * Int(palette[3 * i]) + 587 * Int(palette[3 * i + 1]) + 114 * Int(palette[3 * i + 2]) }
            let shadow = Int(MonitorScreen.darkestIndex(palette))
            #expect((0..<256).allSatisfy { luma(shadow) <= luma($0) && ($0 >= shadow || luma(shadow) < luma($0)) }, "\(cam) shadow")
            for i in 0..<256 { #expect(luma(Int(MonitorScreen.brighterIndex(UInt8(i), in: palette))) >= luma(i), "\(cam) \(i)") }
        }
    }

    @Test func inventoryMonitorChangesAndStaysParityAcrossScales() throws {
        let resources = try #require(worldResources)
        let inventory = try GameSession(resources: resources, level: "CHAOS")
        #expect(inventory.vm.fire("GIVELEXSTARTINGBATT") != nil)
        inventory.tick()
        #expect(inventory.vm.fire("PIMM_MONITOR") != nil)
        inventory.tick()
        let button = try #require(inventory.world.monitor?.buttonCenter("INVB"))
        inventory.world.monitorPointerMove(x: button.x, y: button.y)
        inventory.world.monitorMouseDown(); inventory.world.monitorMouseUp()
        for _ in 0..<12 { inventory.tick() }
        #expect(inventory.world.monitor?.listKeys("INMT") == ["MONBAT"])
        var off = Framebuffer()
        inventory.world.renderPresentation(into: &off)
        inventory.world.readableText = true
        var on = Framebuffer()
        inventory.world.renderPresentation(into: &on)
        #expect(on.pixels != off.pixels)
        for k in [2, 4] {
            let hi = try #require(inventory.world.hiResFrame(indexed: on, pack: HiResFrameTests.noPack(k)))
            #expect(hi.pixels == HiResFrameTests.enlarged(on, k), "readable inventory \(k)x")
        }
        inventory.world.readableText = false
        var back = Framebuffer()
        inventory.world.renderPresentation(into: &back)
        #expect(back.pixels == off.pixels)
    }

    @Test func labelTooWideForSpacingKeepsTheOriginalSpacing() throws {
        let g = try requireGame()
        let (name, colour, palette) = try element("PIMM", kind: "L")
        let bright = MonitorScreen.brighterIndex(colour, in: palette)
        try #require(bright != colour)
        let monitor = try MonitorScreen(name: "PIMM", game: g)
        monitor.defineText(name, "i")
        // A longer and longer text: while spaced text fits the label its glyphs move; from some length on they sit where they always did.
        var moves: [Bool] = []
        for n in 1...80 {
            monitor.defineText(name, String(repeating: "i", count: n))
            let off = ink(render(monitor, readable: false), colour), on = ink(render(monitor, readable: true), bright)
            moves.append(on != off)
        }
        let boundary = try #require(moves.indices.dropFirst().first { !moves[$0] }, "the spacing never falls back")
        #expect(boundary > 1 && moves[1..<boundary].allSatisfy { $0 } && moves[boundary...].allSatisfy { !$0 })
    }

    @Test func listKeepsTheOriginalWrapOnlyWhenTheSpacedTextWouldScroll() throws {
        let g = try requireGame()
        let (name, colour, palette) = try element("PIMM", kind: "T")
        let bright = MonitorScreen.brighterIndex(colour, in: palette)
        try #require(bright != colour)
        let monitor = try MonitorScreen(name: "PIMM", game: g)
        var fallbacks = 0
        for n in 1...120 {
            monitor.hideAll()
            monitor.setTextArea(name, Array(repeating: "the", count: n).joined(separator: " "))
            let off = ink(render(monitor, readable: false), colour), on = ink(render(monitor, readable: true), bright)
            let expected = monitor.listFits(name, spacing: 0) && !monitor.listFits(name, spacing: 1)
            #expect((on == off) == expected, "\(n) words")
            if expected { fallbacks += 1 }
        }
        #expect(fallbacks > 0)
    }

    /// Readable subtitles and captions: a darker box and a brighter colour of the same hue (a colour already at full brightness stays), and
    /// every scale still the 1x picture enlarged.
    @Test func subtitlesGetADarkerBoxAndABrighterColour() throws {
        let r = try Run(level: "CHAOS")
        r.world.figures = r.world.figures.filtering { _ in false }; r.world.items = r.world.items.filtering { _ in false }      // the room alone, as in HiResScreensTests
        func luma(_ fb: Framebuffer, _ i: Int) -> Int { let p = 3 * Int(fb.pixels[i]); return 299 * Int(fb.palette[p]) + 587 * Int(fb.palette[p + 1]) + 114 * Int(fb.palette[p + 2]) }
        for colour in [0x75, 127, 199, 249] {
            r.world.subtitleLog = [SubtitleEvent(tick: 0, handle: 1, colour: colour, text: "A line that is a bit longer~and a second line", end: 100)]
            r.world.readableText = false
            var off = Framebuffer(); r.world.renderPresentation(into: &off)
            r.world.readableText = true
            var on = Framebuffer(); r.world.renderPresentation(into: &on)
            let boxEdge = 198 * Framebuffer.width + 6                       // inside the box, left of any text
            #expect(luma(on, boxEdge) < luma(off, boxEdge) || luma(off, boxEdge) == 0, "box \(colour)")
            for k in [2, 4] {
                let hi = try #require(r.world.hiResFrame(indexed: on, pack: HiResFrameTests.noPack(k)))
                #expect(hi.pixels == HiResFrameTests.enlarged(on, k), "readable caption \(colour) \(k)x")
            }
        }
        r.world.readableText = false
        var plain = Framebuffer(); r.world.renderPresentation(into: &plain)
        #expect(MonitorScreen.brighterIndex(127, in: plain.palette) == 127, "Lex's cyan is at full brightness already")
        #expect(MonitorScreen.brighterIndex(199, in: plain.palette) != 199, "the mid-tone green brightens")
    }
}
