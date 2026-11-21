import Testing
@testable import BioForgeCore

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct MonitorTests {
    @Test func handPointerTouchesWithItsFingertip() throws {
        // VARS.DEF _PTR_X_HOT / _PTR_Y_HOT = 122, 13 in the hand's 320x200 canvas: the fingertip is at the pointer, not 109 px right of it.
        let monitor = try MonitorScreen(name: "OPTS", game: requireGame())
        func frame(_ x: Int, _ y: Int) -> Framebuffer { monitor.pointerMove(x: x, y: y); var fb = Framebuffer(); monitor.render(into: &fb); return fb }
        let a = frame(160, 100), b = frame(60, 160)
        let top = try #require((0..<Framebuffer.width * Framebuffer.height).first { a.pixels[$0] != b.pixels[$0] })
        let (x, y) = (top % Framebuffer.width, top / Framebuffer.width)
        #expect((150...162).contains(x) && (96...100).contains(y), "the hand's highest pixel is at \(x),\(y)")
        let clamped = frame(100, 0)
        #expect(clamped.pixels == frame(100, 14).pixels, "the hand stops 14 px below the top (_ptr_top_margin)")
    }

    /// MLBT's power button with the pointer on it (monitor.py test_pointer_*).
    private func powerButton() throws -> (MonitorScreen, Int, Int) {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        monitor.defineButton("PWRB", "")
        let c = try #require(monitor.buttonCenter("PWRB"))
        monitor.pointerMove(x: c.x, y: c.y)
        return (monitor, c.x, c.y)
    }

    @Test func pointerPressAnimationFramesAndPressReleaseTicks() throws {
        // FUN_1270_01ec / 0263 / 02ef: the press fires on tick 5 (the last frame shown), the release on tick 6; intervals 4, 1, 4 units of 2 per tick.
        let (monitor, _, _) = try powerButton()
        #expect(monitor.pointerFrame == 1 && monitor.pointerState == 0)
        monitor.mouseDown()
        monitor.mouseUp()
        var frames: [Int] = [], states: [Int] = [], buttons: [Int?] = []
        for _ in 0..<11 {
            monitor.update()
            frames.append(monitor.pointerFrame); states.append(monitor.pointerState); buttons.append(monitor.buttonState("PWRB"))
        }
        #expect(frames == [1, 2, 2, 3, 3, 2, 2, 1, 1, 1, 1])
        #expect(states == [1, 1, 1, 1, 2, -1, -1, -1, 0, 0, 0])
        #expect(buttons == [2, 2, 2, 2, 3, 1, 1, 1, 1, 1, 1], "highlighted, pressed on tick 5, released on tick 6")
    }

    @Test func pointerIgnoresMovesAndASecondPressWhileAnimating() throws {
        let (monitor, x, y) = try powerButton()
        monitor.mouseDown()
        for _ in 0..<2 { monitor.update() }
        #expect(!monitor.mouseDown(), "a press during the animation is dropped")
        monitor.pointerMove(x: 10, y: 100)
        #expect(monitor.pointerPosition == (x, y), "the move is ignored while the pointer animates")
        monitor.mouseUp()
        for _ in 0..<5 { monitor.update() }
        monitor.pointerMove(x: 10, y: 100)
        #expect(monitor.pointerPosition == (x, y), "and while it releases")
        for _ in 0..<2 { monitor.update() }
        #expect(monitor.pointerFrame == 1 && monitor.pointerState == 0)
        monitor.pointerMove(x: 10, y: 100)
        #expect(monitor.pointerPosition == (10, 100))
    }

    @Test func pointerHoldsTheLastFrameUntilTheMouseGoesUp() throws {
        let (monitor, _, _) = try powerButton()
        monitor.mouseDown()
        for _ in 0..<30 { monitor.update() }
        #expect(monitor.pointerFrame == 3 && monitor.pointerState == 0 && monitor.buttonState("PWRB") == 3)
        monitor.mouseUp()                                   // idle: the release runs at once
        #expect(monitor.pointerState == -1 && monitor.buttonState("PWRB") == 1)
        for _ in 0..<8 { monitor.update() }
        #expect(monitor.pointerFrame == 1 && monitor.pointerState == 0)
    }

    @Test func inputIsOffFromThePressToTheRelease() throws {
        // FUN_1270_01ec / 0263 call FUN_1250_0415(...,0/1), MON_ENABLEINPUT's switch: moves and keys are dropped until the mouse goes up,
        // and turning input on puts the mouse on the pointer (INT 33h AX=4)
        let (monitor, x, y) = try powerButton()
        monitor.mouseDown()
        for _ in 0..<30 { monitor.update() }
        #expect(!monitor.inputEnabled && monitor.pointerState == 0 && monitor.pointerFrame == 3)
        monitor.pointerMove(x: 10, y: 100)
        monitor.key("ESCAPE")
        let labels = (0..<3).map { _ in monitor.poll().label }
        #expect(monitor.pointerPosition == (x, y) && !labels.contains("ESCAPE_BUTTON"), "the move and ESCAPE are dropped")
        monitor.mouseUp()
        #expect(monitor.inputEnabled && monitor.mouseWarp.map { $0 == (x, y) } == true)
    }

    @Test func enableInputOffDropsClicksUntilAMouseUp() throws {
        let (monitor, x, y) = try powerButton()
        monitor.setInput(false)                             // MON_ENABLEINPUT 0 ("PROHIBIT PTR MOVEMENT OF PTR BY DISABLING MONITOR INPUT")
        #expect(!monitor.mouseDown())
        monitor.pointerMove(x: 10, y: 100)
        #expect(monitor.pointerPosition == (x, y) && monitor.pointerFrame == 1)
        monitor.mouseUp()                                   // FUN_1250_0c4c passes the mouse up through: the idle pointer releases and input is back
        #expect(monitor.inputEnabled)
    }

    @Test func perFormPointerComesFromItsOwnCAM() throws {
        // MON_SETPTR ("pcayhand", CHAOSMON.scr): the first entry of MONITORS/PCAYHAND.CAM; it has one frame after the blank frame 0,
        // so it is always on its last frame and a press doesn't animate (FUN_1270_01ec presses at once)
        let monitor = try MonitorScreen(name: "OPTS", game: requireGame())
        monitor.pointerMove(x: 160, y: 100)
        func picture() -> Framebuffer { var fb = Framebuffer(); monitor.render(into: &fb); return fb }
        let hand = picture()
        monitor.setPointer("pcayhand")
        let caynan = picture()
        #expect(hand.pixels != caynan.pixels)
        monitor.mouseDown()
        #expect(monitor.pointerFrame == 1 && monitor.pointerState == 0 && monitor.inputEnabled)
        monitor.setPointerFrame(0)
        let none = try MonitorScreen(name: "OPTS", game: requireGame())
        none.pointerMove(x: 160, y: 100)
        none.setPointerFrame(0)
        var a = Framebuffer(), b = Framebuffer()
        monitor.render(into: &a); none.render(into: &b)
        #expect(a.pixels == b.pixels, "MON_SETPTRFRAME 0 hides it")
        monitor.setPointer("")
        monitor.setPointerFrame(1)
        #expect(picture().pixels == hand.pixels, "\"\" is POINTER.CAM again")
    }

    @Test func diagnosticsRepairButtonUsesRealClickAndReturnsToPolling() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        session.vm.globals["_bio_state"] = .int(1)
        session.world.keyDown(0x20)
        session.runUntilMonitor()
        for _ in 0..<4 { session.tick() }
        let center = try #require(session.world.monitor?.buttonCenter("BRSB"))
        session.world.monitorPointerMove(x: center.x, y: center.y)
        session.world.monitorMouseDown(); session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }          // the press animation: pressed on the 5th tick, released on the 6th
        #expect(session.vm.globals["_bio_state"] == .int(0))
        #expect(session.world.isMonitorRunning)

        let pfdState = session.vm.globals["_pfd_state"]
        #expect(session.world.monitor?.buttonState("PDSB") == 5, "the starting PFD action is authored as disabled")
        let pds = try #require(session.world.monitor?.buttonCenter("PDSB"))
        session.world.monitorPointerMove(x: pds.x, y: pds.y)
        session.world.monitorMouseDown(); session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }
        #expect(session.vm.globals["_pfd_state"] == pfdState)
        #expect(session.world.isMonitorRunning)
    }

    @Test func pimmCAMUsesItsPaletteAndAuthoredElements() throws {
        let g = try requireGame()
        let monitor = try MonitorScreen(name: "pimm", game: g)
        var fb = Framebuffer()
        monitor.render(into: &fb)
        let cam = try CAMFile(data: g.read("MONITORS/PIMM.CAM"))
        #expect(fb.palette == cam.palette)
        #expect(fb.pixels.contains { $0 != 0 })

        let plain = fb.pixels
        monitor.defineText("EXPL", "EXPERIMENTAL")
        monitor.defineButton("EXTB", "EXIT", state: 2)
        monitor.render(into: &fb)
        #expect(fb.pixels != plain, "authored label and button frames draw over the CAM background")

        let beforePointer = fb.pixels
        monitor.pointerMove(x: 20, y: 20)
        monitor.render(into: &fb)
        #expect(fb.pixels != beforePointer, "POINTER.CAM follows monitor pointer movement")

        let ordinary = try MonitorScreen(name: "PIMM", game: g)
        ordinary.render(into: &fb)
        ordinary.defineButton("INVB", "INVENTORY")
        #expect(ordinary.buttonState("INVB") == 1, "a state-less button uses the normal internal state")
    }

    @Test func monitorTextUsesZeroForMissingVariablesAndCurrentTime() throws {
        let g = try requireGame()
        let expanded = try MonitorScreen(name: "PIMM", game: g)
        expanded.setVariableResolver({ _ in "0" }, formatTime: { _ in "STAMP" }, currentTime: { "NOW" })
        #expect(expanded.expand("%missing% %time%") == "0 NOW")
        #expect(expanded.expand("%time%", stamp: 42) == "STAMP")
    }

    @Test func cellViewportMatchesThePythonCameraFeed() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, afterOldTicks: 950)
        let monitor = try MonitorScreen(name: "CELL", game: resources.game)
        monitor.setViewportRenderer { session.world.viewportFrame($0) }
        monitor.defineViewport("VEWV", "CE11")
        var frame = Framebuffer()
        monitor.render(into: &frame)
        #expect(sha(frame.palette) == "ee4e249f704089d891586031758cd2d60a7c3f30f474b9da538fc9a545b5dda8")
        #expect(sha(frame.pixels) == "2189227db3453a393ce39b7a24a39f8aee49dd0291973d9169843170cb441b75")
        monitor.hideAll()
        #expect(monitor.viewportCamera() == nil)
    }

    @Test func remoteViewportUsesItsOwningLevelWithoutChangingTheCamera() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, afterOldTicks: 950)
        let monitor = try MonitorScreen(name: "MLBT", game: resources.game)
        monitor.setViewportRenderer { session.world.viewportFrame($0) }
        monitor.defineViewport("CAMV", "CTR4")
        monitor.pointerMove(x: 319, y: 199)       // the hand hangs right and below its fingertip: park it off the viewport it would hide
        let camera = session.world.camera, events = session.world.events, changes = session.world.cameraChanges
        var frame = Framebuffer()
        monitor.render(into: &frame)
        #expect(frame.pixels.contains { $0 != 0 })
        #expect(sha(frame.palette) == "262e0515b24c6a61d5b37d813aa89f2ebaaa04ae3c53704c2426941a656596d5")
        #expect(sha(frame.pixels) == "4aad637767ba8216dc10c6855f61ad21f2f7956647b409769984a28e99f56fa1")
        #expect(session.world.camera == camera)
        #expect(session.world.events.map(\.block) == events.map(\.block))
        #expect(session.world.cameraChanges.map(\.to) == changes.map(\.to))

        session.vm.globals["_dr4_frame"] = .int(3)
        var changed = Framebuffer()
        monitor.render(into: &changed)
        #expect(changed.pixels != frame.pixels, "the viewport redraws the room's current sprite frame")
    }

    @Test func cellMonitorScriptDefinesItsViewportThroughWorld() throws {
        let resources = try #require(worldResources)
        let session = try GameSession(resources: resources, level: "CHAOS")
        #expect(session.vm.spawn("GR_CELLMONITOR", args: [.int(1), .int(0)]) != nil)
        #expect(session.world.monitor?.name == "CELL")
        #expect(session.world.monitor?.viewportCamera() == "CE11")
    }

    @Test func pimmEscapeStopsItsScriptMonitor() throws {
        let resources = try #require(worldResources)
        let session = try GameSession(resources: resources, level: "CHAOS")
        #expect(session.vm.fire("PIMM_MONITOR") != nil)
        #expect(session.world.monitor?.name == "PIMM")
        #expect(session.world.isMonitorRunning)
        #expect(session.world.monitor?.buttonCenter("INVB") != nil, "a state-less MON_DEFINEBUTTON defaults to normal and remains clickable")
        #expect(session.world.monitor?.buttonState("INVB") == 1)
        let bare = try MonitorScreen(name: "PIMM", game: resources.game)
        var bareFrame = Framebuffer(), scriptedFrame = Framebuffer()
        bare.render(into: &bareFrame)
        session.world.renderPresentation(into: &scriptedFrame)
        #expect(scriptedFrame.pixels != bareFrame.pixels, "PIMM_MONITOR draws its ordinary authored buttons and labels")
        #expect(sha(scriptedFrame.palette) == "bf84a2433160510439cc7ecb1d597f82ea156b9e0bc0bebeb38990e1a47cf772")
        #expect(sha(scriptedFrame.pixels) == "96c0ee071bed5a821d0e50b527a26eacf9d8560bf8d6255b64ebbf6dcccd3f80")

        session.world.monitorKey("ESCAPE")
        session.tick()
        session.tick()
        session.tick()
        #expect(!session.world.isMonitorRunning)
    }

    @Test func pimmExitButtonStopsItsScriptMonitor() throws {
        let resources = try #require(worldResources)
        let session = try GameSession(resources: resources, level: "CHAOS")
        #expect(session.vm.fire("PIMM_MONITOR") != nil)
        let centre = try #require(session.world.monitor?.buttonCenter("EXTB"))
        session.world.monitorPointerMove(x: centre.x, y: centre.y)
        session.world.monitorMouseDown()
        session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }
        #expect(!session.world.isMonitorRunning)
    }

    @Test func pimmInventoryListsStartingBatteryAndReturnsToMain() throws {
        let resources = try #require(worldResources)
        let session = try GameSession(resources: resources, level: "CHAOS")
        #expect(session.vm.fire("GIVELEXSTARTINGBATT") != nil)
        session.tick()
        #expect(session.vm.fire("PIMM_MONITOR") != nil)
        session.tick()
        let inventory = try #require(session.world.monitor?.buttonCenter("INVB"))
        session.world.monitorPointerMove(x: inventory.x, y: inventory.y)
        session.world.monitorMouseDown()
        session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }

        let monitor = try #require(session.world.monitor)
        #expect(monitor.listKeys("INMT") == ["MONBAT"])
        #expect(monitor.listText("INMT") == ["Standard Battery"])
        #expect(monitor.listKeys("DEST") == ["MONBAT"])
        session.world.monitorPointerMove(x: 160, y: 100)
        var frame = Framebuffer()
        session.world.renderPresentation(into: &frame)
        #expect(sha(frame.palette) == "bf84a2433160510439cc7ecb1d597f82ea156b9e0bc0bebeb38990e1a47cf772")
        #expect(sha(frame.pixels) == "6be557255244c77b524c3992b2a01dc0648e4d00c8089aa9cbef25b22b277c5f")

        session.world.monitorKey("ESCAPE")
        for _ in 0..<4 { session.tick() }
        #expect(session.world.monitor?.buttonCenter("INVB") != nil)
    }

    @Test func inventoryReadyAndStowMatchPythonFrames() throws {
        let fixture = fixtures["inventory"] as! JSON
        let frames = fixture["frames"] as! JSON
        let (session, lex) = try itemWorld()
        let world = session.world
        #expect(session.vm.fire("GIVELEXSTARTINGBATT") != nil)
        session.run(1)
        let fork = Item(name: "FORK_CARRIED", type: "FORK", owner: "LEX")
        fork.slot = "INVENTORY"
        world.items[fork.name] = fork
        #expect(world.spawnFor(lex, "PIMM_INVENTORY"))
        func runUntilMonitor() { for _ in 0..<80 where world.monitor == nil { session.run(1) } }     // PIMM's `MOTION LOOK_AT_PIM FREEZE` blocks until the motion has played
        runUntilMonitor()

        func checkFrame(_ name: String) {
            var frame = Framebuffer()
            world.renderPresentation(into: &frame)
            _ = FrameDigest(frame, tick: session.vm.tick, camera: nil, segments: false)
                .check(frames[name] as! JSON, "inventory \(name)")
        }
        func tap(_ name: String) throws {
            let center = try #require(world.monitor?.buttonCenter(name))
            world.monitorPointerMove(x: center.x, y: center.y)
            world.monitorMouseDown()
            session.run(2)
            world.monitorMouseUp()
            session.run(12)
            world.monitorPointerMove(x: 160, y: 100)
        }

        #expect(world.monitor?.name == "PIMM")
        checkFrame("battery")
        try tap("IPDB")
        checkFrame("fork")
        #expect(world.monitor?.selectedItem("INMT") == "FORK_CARRIED")
        try tap("RDYB")
        session.run(4)
        #expect(fork.owner == "LEX" && fork.slot == "LTHAND")
        #expect(world.monitor == nil)

        session.press(0x17)
        #expect(fork.slot == "INVENTORY" && world.monitor == nil)
        session.press(0x17)
        runUntilMonitor()
        checkFrame("stowed")
        #expect(world.monitor?.selectedIndex("INMT") == 0)
    }

    @Test func diagnosticsUsesAuthoredScalesAndReturnsToMain() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        session.world.keyDown(0x20)
        session.runUntilMonitor()
        for _ in 0..<4 { session.tick() }

        var frame = Framebuffer()
        session.world.renderPresentation(into: &frame)
        #expect(sha(frame.palette) == "bf84a2433160510439cc7ecb1d597f82ea156b9e0bc0bebeb38990e1a47cf772")
        #expect(sha(frame.pixels) == "8b390e80541513e845ea6d2a5930e9825c8acc5b02a9fd9b59be653d69e03f8a")

        let exit = try #require(session.world.monitor?.buttonCenter("DXTB"))
        session.world.monitorPointerMove(x: exit.x, y: exit.y)
        session.world.monitorMouseDown(); session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }
        #expect(!session.world.isMonitorRunning)
    }

    @Test func pimmMainRoutesDiagnosticsAndJournalButtons() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        session.world.keyDown(0x19)
        session.runUntilMonitor()

        let diagnostics = try #require(session.world.monitor?.buttonCenter("DIAB"))
        session.world.monitorPointerMove(x: diagnostics.x, y: diagnostics.y)
        session.world.monitorMouseDown(); session.world.monitorMouseUp()
        for _ in 0..<12 { session.tick() }
        #expect(session.world.monitor?.buttonCenter("DXTB") != nil)
        session.world.monitorKey("ESCAPE")
        for _ in 0..<4 { session.tick() }

        let journalSession = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        journalSession.world.keyDown(0x19)
        journalSession.runUntilMonitor()
        let journal = try #require(journalSession.world.monitor?.buttonCenter("JOUB"))
        journalSession.world.monitorPointerMove(x: journal.x, y: journal.y)
        journalSession.world.monitorMouseDown(); journalSession.world.monitorMouseUp()
        for _ in 0..<12 { journalSession.tick() }
        #expect(journalSession.world.monitor?.buttonCenter("JXTB") != nil)
    }

    @Test func journalUsesLogAwardTimeAndScrollsTextLines() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        #expect(session.world.addLogEntry("LEX", "PIM1"))
        session.world.keyDown(0x24)
        session.runUntilMonitor()
        for _ in 0..<4 { session.tick() }

        let monitor = try #require(session.world.monitor)
        #expect(monitor.listKeys("JORT") == ["PIM1"])
        var frame = Framebuffer()
        session.world.renderPresentation(into: &frame)
        #expect(sha(frame.palette) == "bf84a2433160510439cc7ecb1d597f82ea156b9e0bc0bebeb38990e1a47cf772")
        #expect(sha(frame.pixels) == "e42f9631a9dd351ab4b2cea43add498b319edc9b4880398424239606656449f2")

        monitor.scrollList("JORT", 208)
        var scrolled = Framebuffer()
        session.world.renderPresentation(into: &scrolled)
        #expect(scrolled.pixels != frame.pixels)
    }

    @Test func journalExitAwardsPIM1AfterEntriesHaveBeenSeen() throws {
        let resources = try #require(worldResources)
        let session = try GameSession.newGame(resources: resources, inControlAfterOldTicks: 1_000)
        session.vm.globals["_got_entries"] = .int(1)
        session.world.keyDown(0x24)
        session.runUntilMonitor()
        for _ in 0..<4 { session.tick() }
        session.world.monitorKey("ESCAPE")
        for _ in 0..<5 { session.tick() }
        #expect(session.world.logEntries["LEX"]?.contains("PIM1") == true)
    }

    // MARK: the pointer's glide (FUN_1270_0536 / 064f / 0891; monitor.py test_glide_*)

    private func glidePositions(_ monitor: MonitorScreen, from x: Int, by dx: Int, ticks: Int) -> [Int] {
        monitor.placePointer(x: x, y: 100)
        monitor.glideTo(x: x + dx, y: 100)
        return (0..<ticks).map { _ in monitor.update(); return monitor.pointerPosition.x }
    }

    @Test func glideFollowsTheIntegerModel() throws {
        // dx = 100 at dt 4: 14 accelerating steps (t = 56), one coasting step, then decelerating; arrives on step 22.
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        let got = glidePositions(monitor, from: 100, by: 100, ticks: 24)
        #expect(Array(got[0..<15]) == [101, 102, 104, 106, 109, 112, 116, 120, 125, 130, 136, 142, 149, 156, 163])
        #expect(Array(got[15..<22]) == [170, 176, 182, 187, 192, 196, 200])
        #expect(Array(got[22...]) == [200, 200])
        #expect(!monitor.gliding, "DAT_9fea clears one update after the arrival")
    }

    @Test func glideOverflowJumpsAtOnceAndTheTargetIsClamped() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        monitor.placePointer(x: 0, y: 14)
        monitor.glideTo(x: 247, y: 186)                       // 247 * 172 = 42484 wraps negative: distance 0
        monitor.update()
        #expect(monitor.pointerPosition == (247, 186))
        monitor.placePointer(x: 100, y: 100)
        monitor.glideTo(x: 500, y: 0)
        for _ in 0..<80 { monitor.update() }
        #expect(monitor.pointerPosition == (319, 14))
    }

    @Test func mouseMoveAndSetPtrPosCancelAGlide() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        var got = glidePositions(monitor, from: 100, by: 100, ticks: 5)
        monitor.pointerMove(x: got[4], y: 100)
        for _ in 0..<5 { monitor.update() }
        #expect(monitor.pointerPosition.x == got[4])
        got = glidePositions(monitor, from: 100, by: 100, ticks: 5)
        monitor.placePointer(x: 50, y: 60)
        for _ in 0..<5 { monitor.update() }
        #expect(monitor.pointerPosition == (50, 60))
    }

    @Test func tabGlidesAndHighlightsOnCrossing() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        monitor.defineButton("PWRB", "")
        monitor.placePointer(x: 100, y: 190)
        monitor.tab()
        #expect(monitor.buttonState("PWRB") == 1, "no highlight until the pointer arrives")
        for _ in 0..<3 { monitor.update() }
        #expect(monitor.poll().label == nil)
        for _ in 0..<40 { monitor.update() }
        let c = try #require(monitor.buttonCenter("PWRB"))
        #expect(monitor.pointerPosition == c)
        #expect(monitor.poll().label == "PWRB_HIGHLIGHT")
    }

    @Test func aClickDuringAGlideIsLost() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        var taken = 0
        monitor.pressAction = { taken += 1; return true }
        monitor.placePointer(x: 0, y: 100)
        monitor.glideTo(x: 300, y: 100)
        for _ in 0..<2 { monitor.update() }
        monitor.mouseDown()
        for _ in 0..<12 { monitor.update() }
        #expect(monitor.gliding && taken == 0)
        for _ in 0..<60 { monitor.update() }
        #expect(!monitor.gliding)
        monitor.mouseUp()
        monitor.settlePointer()
        monitor.mouseDown()
        #expect(taken == 1)
    }

    @Test func letterShortcutGlidesThenClicksOnArrivalOrAtOnce() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        monitor.defineButton("PWRB", "POWER")
        monitor.setShortcut("PWRB", "p")                       // as FUN_1278_0894 would store; no script statement does
        var presses = 0, releases = 0
        monitor.pressAction = { presses += 1; return true }
        monitor.releaseAction = { releases += 1; return true }
        monitor.placePointer(x: 100, y: 190)
        #expect(!monitor.letterKey("x"))
        #expect(monitor.letterKey("P"))
        for _ in 0..<60 { monitor.update() }
        #expect(presses == 1 && releases == 1)
        // with the pointer already on the focused button it clicks at once
        #expect(monitor.letterKey("p"))
        for _ in 0..<30 { monitor.update() }
        #expect(presses == 2 && releases == 2)
    }

    private func rowOfThree() throws -> MonitorScreen {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        for n in ["PWRB", "MANB", "AUTB"] { monitor.defineButton(n, "") }      // one row, in this order; centres x 247, 160, 74 at y 186
        return monitor
    }

    @Test func tabStartsOnTheFirstSelectableButtonAndShiftTabGoesBack() throws {
        let monitor = try rowOfThree()
        #expect(monitor.keyEvent(MonitorScreen.keyTab))
        #expect(monitor.focus == "MANB", "the focus starts on DNDB, is not selectable, moves to PWRB; Tab steps on")
        for _ in 0..<40 { monitor.update() }
        #expect(monitor.pointerPosition == (160, 186))
        monitor.keyEvent(MonitorScreen.keyBackTab)
        #expect(monitor.focus == "PWRB")
    }

    @Test func directionKeysPickTheNearestButtonThatWayOrStep() throws {
        let monitor = try rowOfThree()
        monitor.focus = "MANB"
        monitor.keyEvent(0xcd)                                 // Right
        #expect(monitor.focus == "PWRB")
        monitor.keyEvent(0xcb); monitor.keyEvent(0xcb)         // Left twice
        #expect(monitor.focus == "AUTB")
        monitor.keyEvent(0xcb)                                 // nothing further left: the previous button (the wrap)
        #expect(monitor.focus == "MANB")
        monitor.keyEvent(0xd0)                                 // Down: nothing below, the "next" fallback
        #expect(monitor.focus == "AUTB")
        monitor.keyEvent(Int(Character("L").asciiValue!))      // L: nearest outside the row and column: none, so the previous
        #expect(monitor.focus == "MANB")
    }

    @Test func returnPressesAndItsReleaseEndsThePress() throws {
        let (monitor, x, y) = try powerButton()
        var taken: [Int] = []
        monitor.pressAction = { taken.append(1); return true }
        monitor.releaseAction = { taken.append(2); return true }
        monitor.pointerMove(x: x, y: y)
        monitor.keyEvent(MonitorScreen.keyReturn, scan: 0x1c)
        #expect(monitor.pointerState == 1)
        for _ in 0..<3 { monitor.update() }
        monitor.keyRelease(0x1c)
        for _ in 0..<30 { monitor.update() }
        #expect(taken == [1, 2])
    }

    @Test func escapeIsPressedThenReleasedAsALabel() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        #expect(!monitor.keyEvent(MonitorScreen.keyEscape, scan: 1))
        #expect(monitor.poll().label == "ESCAPE_BUTTON")
        monitor.keyRelease(1)
        #expect(monitor.poll().label == "ESCAPE_RELEASED")
    }

    @Test func rightClickPressesEscapeWhileInputIsOn() throws {
        let monitor = try MonitorScreen(name: "MLBT", game: requireGame())
        monitor.rightClick()
        #expect(monitor.poll().label == "ESCAPE_BUTTON")
        let off = try MonitorScreen(name: "MLBT", game: requireGame())
        off.setInput(false)
        off.rightClick()
        #expect(off.poll().label == nil)
    }

    @Test func keysAreDroppedWhileInputIsOffExceptForMonSimulate() throws {
        let monitor = try rowOfThree()
        monitor.setInput(false)
        #expect(!monitor.keyEvent(MonitorScreen.keyTab))
        #expect(monitor.keyEvent(MonitorScreen.keyTab, force: true))
        #expect(MonitorScreen.keyCode(scan: 0x0f, shift: true) == 0x8f && MonitorScreen.keyCode(scan: 0x26) == Int(Character("l").asciiValue!)
                && MonitorScreen.keyCode(scan: 0x48) == 0xc8 && MonitorScreen.keyCode(scan: 0x3b) == nil)
    }
}

/// The list's first update (FUN_1268_10c5 / 1213) shows a record's unkeyed "[]" entries, then the ADDLOGENTRY keys (test_monitor.py MonitorScripts).
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct LogBookListTests {
    @Test func foundLogsShowTheirUnkeyedEntries() throws {
        for (language, caynan) in [("E", "d1892-1120 I can still hear Dane"), ("G", "T1892-1120 Ich kann Dane")] {
            for (source, count) in [("caynan", 43), ("dane", 19), ("eshmes", 34), ("lock", 1), ("lock2", 1)] {
                let screen = try MonitorScreen(name: "LGBK", game: requireGame())
                screen.language = language
                screen.defineList("TEXT", source)
                #expect(screen.listKeys("TEXT") == Array(repeating: "", count: count), "\(language) \(source)")
                if source == "caynan" { #expect(screen.listText("TEXT").first?.hasPrefix(caynan) == true) }
            }
        }
        let open = try MonitorScreen(name: "LGBK", game: requireGame())       // Game > Language while the log is open
        open.defineList("TEXT", "caynan")
        open.language = "G"
        #expect(open.listKeys("TEXT").count == 43 && open.listText("TEXT").first?.hasPrefix("T1892-1120 Ich kann Dane") == true)
    }

    @Test func daneLogShowsTheAccessCode() throws {
        let screen = try MonitorScreen(name: "LGBK", game: requireGame())
        let digits = ["_access_id1_to_match": "3", "_access_id2_to_match": "1", "_access_id3_to_match": "4", "_access_id4_to_match": "1", "_access_id5_to_match": "5"]
        screen.setVariableResolver({ digits[$0.lowercased()] }, formatTime: { _ in "" }, currentTime: { "" })
        screen.defineList("TEXT", "dane")
        #expect(screen.expand(screen.listText("TEXT")[11]).contains("access code number is 31415"))
    }

    @Test func mixedRecordListsUnkeyedEntriesBeforeLogKeys() throws {
        let screen = try MonitorScreen(name: "MANT", game: requireGame())
        screen.defineList("RLGT", "CMAINT")
        #expect(screen.listKeys("RLGT") == Array(repeating: "", count: 64))
        screen.defineList("RLGT", "CMAINT", keys: ["C3REP", "C1REP"], times: [5, 9])
        #expect(screen.listKeys("RLGT") == Array(repeating: "", count: 64) + ["C3REP", "C1REP"])
        screen.defineList("RLGT", "GMAINT", keys: ["C2REP"], times: [5])
        #expect(screen.listKeys("RLGT") == ["C2REP"])
    }
}
