import Testing
import Foundation
@testable import BioForgeCore

/// View > High-Resolution Art for monitors, the options dialog and captions: with no pack files the picture is the 320x200 one enlarged exactly.
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct HiResScreensTests {
    /// `world`'s player-facing 1x frame against its hi-res one with an empty pack, at 2x and 4x.
    func checkParity(_ world: World, _ what: String) throws {
        var fb = Framebuffer()
        world.renderPresentation(into: &fb)
        for k in [2, 4] {
            let hi = try #require(world.hiResFrame(indexed: fb, pack: HiResFrameTests.noPack(k)), Comment(rawValue: what))
            #expect(hi.pixels == HiResFrameTests.enlarged(fb, k), "\(what) \(k)x")
        }
    }

    @Test func glyphScalerIsBlocky() {
        let g = HDText.scaledGlyph([[0, 7, 0], [3, 0, 0]], 2)
        #expect(g.width == 6 && g.height == 4)
        let ink = (0..<4).map { y in (0..<6).map { x in g.mask[y * 6 + x] ? "#" : "." }.joined() }
        #expect(ink == ["..##..", "..##..", "##....", "##...."])
    }

    @Test func pimmScreensMatchTheEnlarged1xPicture() throws {
        let resources = try #require(worldResources)
        let main = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        main.world.keyDown(0x19)
        for _ in 0..<80 where main.world.monitor == nil { main.run(1) }
        try checkParity(main.world, "PIMM main")
        main.world.monitorPointerMove(x: 160, y: 100)
        try checkParity(main.world, "PIMM main, pointer in the middle")

        let diagnostics = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        diagnostics.world.keyDown(0x20)
        for _ in 0..<80 where diagnostics.world.monitor == nil { diagnostics.run(1) }
        for _ in 0..<4 { diagnostics.tick() }
        try checkParity(diagnostics.world, "diagnostics (scale bars)")

        let journal = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        #expect(journal.world.addLogEntry("LEX", "PIM1"))
        journal.world.keyDown(0x24)
        for _ in 0..<80 where journal.world.monitor == nil { journal.run(1) }
        for _ in 0..<4 { journal.tick() }
        try checkParity(journal.world, "journal (text list)")

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
        try checkParity(inventory.world, "inventory")
    }

    @Test func viewportMonitorMatchesTheEnlarged1xPicture() throws {
        let resources = try #require(worldResources)
        let session = try GameSession(resources: resources, level: "CHAOS")
        #expect(session.vm.spawn("GR_CELLMONITOR", args: [.int(1), .int(0)]) != nil)
        #expect(session.world.monitor?.viewportCamera() == "CE11")
        try checkParity(session.world, "CELL viewport")
    }

    @Test func everyOptionsScreenMatchesTheEnlarged1xPicture() throws {
        let g = try requireGame()
        func screens() throws -> [(String, Options)] {
            func open(_ flags: Int) throws -> Options { let o = try Options(game: g); o.open(flags); return o }
            var out: [(String, Options)] = [("difficulty", try open(Options.difficulty)), ("main", try open(1)), ("audio", try open(Options.audio)),
                                            ("credits", try open(Options.credits)), ("save", try open(Options.save)), ("load", try open(Options.load)),
                                            ("exit", try open(Options.exit))]
            let hover = try open(1); _ = hover.pointerMove(x: 40, y: 140); out.append(("main, pointer over EXIT", hover))
            let gamma = try Options(game: g, settings: Settings(gamma: 50)); gamma.open(1); _ = gamma.activate("GMAX"); out.append(("gamma", gamma))
            let confirm = try open(1); _ = confirm.activate("LOAD"); out.append(("confirm", confirm))
            return out
        }
        for (what, o) in try screens() {
            var fb = Framebuffer()
            o.render(into: &fb)
            for k in [2, 4] {
                var hi = HiResFrame(scale: k)
                o.render(into: &hi, pack: HiResFrameTests.noPack(k))
                #expect(hi.pixels == HiResFrameTests.enlarged(fb, k), "options \(what) \(k)x")
            }
        }
    }

    @Test func captionOverARoomMatchesTheEnlarged1xPicture() throws {
        let r = try Run(level: "CHAOS")
        r.world.figures = r.world.figures.filtering { _ in false }; r.world.items = r.world.items.filtering { _ in false }                                                // textured figures and items are rasterised at the larger size, not enlarged: the room alone here
        for text in ["HELLO", "A line that is a bit longer~and a second line", "one~two~three"] {
            r.world.subtitleLog = [SubtitleEvent(tick: 0, handle: 1, colour: 0x75, text: text, end: 100)]
            try checkParity(r.world, "caption \(text)")
        }
    }

    @Test func captionOverAFlicMatchesTheEnlarged1xPicture() throws {
        let session = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = session.world, vm = session.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let proc = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "STARTFLIC", [.str("intro")], proc)
        _ = w.call(.function, "RUNFLIC", [.str("SCN"), .int(3)], proc)
        for _ in 0..<60 where w.show.flic?.frame == nil { vm.tickOnce(); w.step() }
        #expect(w.show.flic?.frame != nil)
        var fb = Framebuffer()
        w.renderPresentation(into: &fb)
        #expect(w.hiResFrame(indexed: fb, pack: HiResFrameTests.noPack()) == nil, "a flic alone keeps the 320x200 picture")
        w.subtitleLog = [SubtitleEvent(tick: w.tick, handle: 1, colour: 0x75, text: "Over the flic~two lines", end: w.tick + 1000)]
        try checkParity(w, "caption over a flic")
    }

    /// A monitor's pack background replaces the original; its elements are plain-enlarged even where the pack has a frame for them,
    /// and a scale bar stays clipped at s x its percentage.
    @Test(.enabled(if: packCodec, "High-Resolution Art packs need macOS")) func packFramesPaintMonitors() throws {
        let g = try requireGame()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("hires-\(UUID().uuidString)")
        let elementsOnly = FileManager.default.temporaryDirectory.appendingPathComponent("hires-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir); try? FileManager.default.removeItem(at: elementsOnly) }
        func write(_ rel: String, _ w: Int, _ h: Int, _ index: UInt8, in root: URL) throws {
            let file = root.appendingPathComponent(rel + ".frm")
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try PixelPackBuilder.encode(width: w, height: h, pixels: [UInt8](repeating: index, count: w * h), mask: [UInt8](repeating: 1, count: w * h)).write(to: file)
        }
        try write("monitors/PIMM/PIMM.0", 640, 400, 0x42, in: dir)
        let monitor = try MonitorScreen(name: "PIMM", game: g)
        var hi = HiResFrame(scale: 2)
        monitor.render(into: &hi, pack: HiResPack(root: dir, scale: 2))
        #expect(hi.pixels.filter { $0 == 0x42 }.count > 100_000, "the pack's background")
        var bare = HiResFrame(scale: 2)
        monitor.render(into: &bare, pack: HiResFrameTests.noPack())
        #expect(bare.pixels.filter { $0 == 0x42 }.count < 100_000)

        let diag = try MonitorScreen(name: "PIMM", game: g)
        let cam = try CAMFile(data: g.read("MONITORS/PIMM.CAM"))
        let bar = try #require(cam.images.first { $0.name.uppercased().dropFirst(3).hasPrefix("S") })
        let f = try cam.frames(of: bar)[1]
        try write("monitors/PIMM/\(bar.name.uppercased()).1", 2 * f.width, 2 * f.height, 0x99, in: elementsOnly)
        diag.pointerMove(x: 319, y: 199)       // the hand hangs right and below its fingertip: park it off the bar
        func render(_ percent: Int, _ pack: HiResPack) -> HiResFrame {
            diag.setScale(bar.name, percent, 1)
            var out = HiResFrame(scale: 2)
            diag.render(into: &out, pack: pack)
            return out
        }
        #expect(render(50, HiResPack(root: elementsOnly, scale: 2)).pixels == render(50, HiResFrameTests.noPack()).pixels, "the bar's pack frame is not used")
        let empty = render(0, HiResFrameTests.noPack()).pixels
        func span(_ percent: Int) -> Int {
            let p = render(percent, HiResFrameTests.noPack()).pixels
            let columns = Set(p.indices.filter { p[$0] != empty[$0] }.map { $0 % 640 })
            return columns.isEmpty ? 0 : columns.max()! - columns.min()! + 1
        }
        #expect(span(50) > 0 && span(50) <= 2 * f.width / 2 + 1 && span(100) > span(50), "half the bar's columns")
    }

    /// Playtest: the options dialog's arrows, slot digits and buttons looked smeared at 2x. They are plain-enlarged: pack frames for them
    /// change nothing, while the pack's background is still used.
    @Test(.enabled(if: packCodec, "High-Resolution Art packs need macOS")) func optionsElementsArePlainDoubled() throws {
        let g = try requireGame()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("hires-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let cam = try CAMFile(data: g.read("MONITORS/OPTS.CAM"))
        for name in ["LLFX", "LRTX", "SE1X", "SE5X", "LCAX"] {
            let image = try #require(cam.images.first { $0.name.uppercased() == name }, Comment(rawValue: name))
            for (i, f) in try cam.frames(of: image).enumerated() where f.width > 0 && f.height > 0 {
                let file = dir.appendingPathComponent("monitors/OPTS/\(name).\(i).frm")
                try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
                try PixelPackBuilder.encode(width: 2 * f.width, height: 2 * f.height, pixels: [UInt8](repeating: 0x99, count: 4 * f.width * f.height),
                                            mask: [UInt8](repeating: 1, count: 4 * f.width * f.height)).write(to: file)
            }
        }
        let o = try Options(game: g)
        o.open(Options.load)
        var withPack = HiResFrame(scale: 2), bare = HiResFrame(scale: 2)
        o.render(into: &withPack, pack: HiResPack(root: dir, scale: 2))
        o.render(into: &bare, pack: HiResFrameTests.noPack())
        #expect(withPack.pixels == bare.pixels, "element pack frames are not used")
    }

    /// The options dialog in play sits on the room at the pack's scale, dimmed (World.optionsUnderlayHiRes), not on the 320x200 room enlarged.
    @Test(.enabled(if: packCodec, "High-Resolution Art packs need macOS")) func optionsInPlaySitOnTheHiResRoom() throws {
        let r = try Run(level: "CHAOS")
        let w = r.world
        w.figures = w.figures.filtering { _ in false }; w.items = w.items.filtering { _ in false }  // figures are rasterised at the larger size
        let cam = try #require(w.currentCamera?.uppercased())
        let room = try CAMFile(data: try requireGame().read("ROOMS/\(cam).CAM"))
        let back = try #require(room.images.max { $0.size < $1.size })
        let f = try #require(try room.frames(of: back).first)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("hires-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent("rooms/\(cam)/\(back.name.uppercased()).0.frm")
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let n = 4 * f.width * f.height
        try PixelPackBuilder.encode(width: 2 * f.width, height: 2 * f.height, pixels: [UInt8](repeating: 0x42, count: n), mask: [UInt8](repeating: 1, count: n)).write(to: file)
        w.keyDown(0x18)
        #expect(w.isOptionsOpen)
        try checkParity(w, "options in play")
        var fb = Framebuffer()
        w.renderPresentation(into: &fb)
        let hi = try #require(w.hiResFrame(indexed: fb, pack: HiResPack(root: dir, scale: 2)))
        let under = w.optionsUnderlay()
        let grey = MonitorScreen.darkGrey(under, 0x42)
        let row = 2 * 60 * hi.width                                       // above the buttons, where only the dimmed room shows
        #expect(hi.pixels[(row + 80)..<(row + 560)].filter { $0 == grey }.count > 300, "the pack's room, dimmed")
    }
}
