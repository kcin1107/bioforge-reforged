// Room events, the camera switch's show / hide pass and the default AI (re/NOTES.md "Room events and the default AI") against
// re/interp/test_room_events.py, with the same cases and the same numbers:
// the room / camera event order (1130:0307-044f), ISCURRENTCAMERA's room name, CAMERA <cam> LOAD, the FIGR records' AI-off counter,
// the level loader's figures, and the AI counter (AI ON / OFF, NO_STOP_MOTION, the process that yields on its own OFF).
import Foundation
import Testing
@testable import BioForgeCore

private let blocks = """
{ BLK_UNLOAD
\t_door_frame = 1
}
{ BLK1_UNLOAD
\t_door_frame = 2
}
{ CE11_LOAD
\t_bak_frame = ISCURRENTCAMERA CE11
\t_fnt_frame = ISMYFORM LEX
\t_tnkd_frame = ISCURRENTCAMERA CE1
\t_bchz_frame = ISCURRENTCAMERA BLK1
}
{ LEX_ON_IN_WALK
\tSUSPEND
\tSETCURRENTFIGURE PLAYER
\tAI ON
\tSUSPEND
\t_bak_frame = 1
}
{ LEX_ON_THEN_STOP
\tSUSPEND
\tSETCURRENTFIGURE PLAYER
\tAI ON
\tSUSPEND
\tSTOPMOTION
}
{ TESTAI_AI
\t_door_frame ++
\tAI OFF
\t_bchz_frame = 1
\tSUSPEND
\t_bchz_frame = 2
\t:TOP
\tSUSPEND
\tJUMP TOP
}

"""

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct RoomEventsTests {
    /// test_room_events.py `Base.setUp`: CHAOS at its INITGAME state with the test blocks, Lex as the player, the automatic camera off.
    private func make() throws -> (GameSession, World, Figure) {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        let w = s.world
        s.vm.load(DecodedScript(name: "SYN_ROOM_EVENTS.scr", text: Array(blocks.utf8), lineStarts: [], columns: [], unresolved: []))
        for name in ["_door_frame", "_bchz_frame", "_bak_frame", "_fnt_frame"] { s.vm.globals[name] = .int(0) }
        cmd(s, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        w.setPos(lex, V3(-11000, -12000, -5093))
        w.autoCamera = false
        return (s, w, lex)
    }

    private func proc(_ s: GameSession, _ fig: String = "PLAYER") -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: fig))
    }

    private func cmd(_ s: GameSession, _ name: String, _ args: ScriptValue..., fig: String = "PLAYER") { _ = s.world.call(.stmt, name, args, proc(s, fig)) }

    private func global(_ s: GameSession, _ name: String) -> ScriptValue? { s.vm.globals[name] }

    private func events(_ w: World) -> [String] { w.events.map(\.block) }

    private func tick(_ s: GameSession, _ n: Int = 1) { for _ in 0..<n { s.tick() } }

    // MARK: room events

    @Test func orderRoomThenCameraLoadThenUnload() throws {
        let (s, w, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        #expect(events(w) == ["BLK_LOAD", "BLK1_LOAD"])
        w.events.removeAll()
        cmd(s, "CAMERA", .str("HAL1"))                       // 1130:0307-044f
        #expect(events(w) == ["HAL_LOAD", "BLK_UNLOAD", "HAL1_LOAD", "BLK1_UNLOAD"])
        #expect(global(s, "_door_frame") == .int(2))
    }

    @Test func sameRoomRunsOnlyTheCameraEvents() throws {
        let (s, w, _) = try make()
        cmd(s, "CAMERA", .str("HAL1"))
        w.events.removeAll()
        cmd(s, "CAMERA", .str("HAL3"))
        #expect(events(w) == ["HAL3_LOAD"])
    }

    @Test func blocksRunAtOnceWithThePlayerAndSeeTheNewNames() throws {
        let (s, w, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        cmd(s, "CAMERA", .str("CE11"))
        #expect([global(s, "_bak_frame"), global(s, "_tnkd_frame"), global(s, "_bchz_frame"), global(s, "_fnt_frame")] == [.int(1), .int(1), .int(0), .int(1)])   // 10d8:2aea: [63e1] or [63e5]
        #expect(w.currentCamera == "CE11")
    }

    @Test func isCurrentCameraTakesTheRoomName() throws {
        let (s, w, _) = try make()
        cmd(s, "CAMERA", .str("HAL3"))
        func fn(_ a: String) -> ScriptValue { w.call(.function, "ISCURRENTCAMERA", [.str(a)], proc(s, "LEX")) }
        #expect([fn("HAL3"), fn("HAL"), fn("HAL1"), fn("HA")] == [.int(1), .int(1), .int(0), .int(0)])
    }

    @Test func cameraLoadFormIsSilentAndSwitchesNothing() throws {
        let (s, w, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        w.events.removeAll()
        cmd(s, "CAMERA", .str("BCHZ"), .str("LOAD"))         // FUN_1110_024a: the resource cache only
        #expect(w.currentCamera == "BLK1" && w.events.isEmpty && w.warnings.isEmpty)
    }

    @Test func aLevelLoadKeepsTheOldNames() throws {
        let (s, w, _) = try make()
        cmd(s, "CAMERA", .str("HAL1"))
        cmd(s, "LOADLEVEL", .str("TANKS"), .str("ENTR_TNK"))
        #expect(w.level == "TANKS")
        #expect(w.loadedCam == "HAL1" && w.loadedRoom == "HAL")        // 1130:0048 clears only [63e1] / [63e5]
    }

    // MARK: the records

    @Test func aiOffCounterOfTheRecords() throws {
        let g = try requireGame()
        func records(_ dir: URL?) throws -> [String: Int] {
            let file = try #require(dir.flatMap { GameFolder($0).resolve("CHAOS.IFF") })
            let objs = try LevelObjects.load([UInt8](try Data(contentsOf: file)))
            return Dictionary(uniqueKeysWithValues: objs.filter { $0.tag == "FIGR" }.map { ($0.raw.cString(33, 42), figrAIOff($0.raw)) })
        }
        #expect(try records(g.initgame) == ["USE_BOT": 0, "FIRSTBOT": 0, "FIDO": 0, "HALMECHO": 0, "CAYNAN": 0, "GUARD1": 0])
        #expect(try records(g.gamedat) == ["USE_BOT": 1, "FIDO": 0, "HALMECHO": 0, "CAYNAN": 0, "GUARD1": 0])
    }

    // MARK: default AI

    @Test func everyRecordFigureExistsAfterTheLoadInRecordOrder() throws {
        let (_, w, _) = try make()
        #expect(w.data.figDefOrder == ["USE_BOT", "FIRSTBOT", "FIDO", "HALMECHO", "CAYNAN", "GUARD1"])
        #expect(w.figures.keys.filter { $0 != "LEX" }.sorted() == ["CAYNAN", "FIDO", "FIRSTBOT", "GUARD1", "HALMECHO", "USE_BOT"])
        #expect(["USE_BOT", "HALMECHO"].allSatisfy { w.figures[$0]!.hidden })     // flag 0x04 of the records
    }

    @Test func createdFigureIsNamedAfterItselfWithAiOn() throws {
        let (s, w, _) = try make()
        cmd(s, "CREATEFIGURE", .str("NURSEBOT"), .str("TESTAI"))
        let fig = try #require(w.figures["TESTAI"])
        #expect(fig.aiType == "TESTAI" && fig.hold == 0 && fig.aiEnabled)
    }

    private func sentry(_ s: GameSession) throws -> Figure {
        let mecho = try #require(s.world.figures["HALMECHO"])
        cmd(s, "DEFINEVIEWINGCAMS", .str("HAL1"), .str("HAL2"), fig: "HALMECHO")
        return mecho
    }

    @Test func sentryStartsOnlyOnAViewingCamera() throws {
        let (s, _, _) = try make()
        let mecho = try sentry(s)
        cmd(s, "CAMERA", .str("BLK1"))
        tick(s, 3)
        #expect(mecho.aiProc == nil)
        cmd(s, "CAMERA", .str("HAL1"))
        tick(s)
        #expect(mecho.aiProc?.block.name == "HALMECHO_AI" && !mecho.hidden)
    }

    @Test func hidingPausesTheAiAndStopsTheMotionShowingResumes() throws {
        let (s, _, _) = try make()
        let mecho = try sentry(s)
        cmd(s, "CAMERA", .str("HAL1"))
        tick(s)
        let proc = try #require(mecho.aiProc), handle = proc.handle
        mecho.setMotion("WALK", loop: true)
        cmd(s, "CAMERA", .str("BLK1"))
        tick(s)
        #expect(mecho.hidden && proc.suspended && !proc.done)
        #expect(mecho.frozen && mecho.stopped && mecho.idleRequest)       // FUN_1098_0789(fig, 1, 0)
        cmd(s, "CAMERA", .str("HAL2"))
        tick(s)
        #expect(!mecho.hidden && !proc.suspended && mecho.aiProc?.handle == handle)
    }

    @Test func theFollowedFigureIsShown() throws {
        let (s, w, _) = try make()
        let mecho = try sentry(s)
        cmd(s, "CAMERA", .str("BLK1"))
        tick(s)
        #expect(mecho.hidden)
        w.follow = "HALMECHO"                                             // 1130:00c1, vtable +0x68
        tick(s)
        #expect(!mecho.hidden)
    }

    @Test func aBlockLessAiNameStartsNothingSilently() throws {
        let (s, w, _) = try make()
        let fig = try #require(w.figures["USE_BOT"])
        fig.hidden = false; fig.viewCams = nil
        tick(s, 2)
        #expect(fig.aiProc == nil && w.warnings.isEmpty && s.vm.warnings.isEmpty)
    }

    // MARK: the counter

    private func rig(_ s: GameSession) throws -> Figure {
        cmd(s, "CREATEFIGURE", .str("NURSEBOT"), .str("TESTAI"))
        let fig = try #require(s.world.figures["TESTAI"])
        s.world.setPos(fig, V3(-9000, -12000, -5000))
        var rec = s.vm.objectRecord("TESTAI")
        rec[0] = .int(50)
        s.vm.setObject("TESTAI", rec)
        return fig
    }

    @Test func offOffOnStaysOff() throws {
        let (s, _, _) = try make()
        let fig = try rig(s)
        for (word, hold) in [("OFF", 1), ("OFF", 2), ("ON", 1), ("ON", 0), ("ON", 0)] {
            cmd(s, "AI", .str(word), fig: "TESTAI")
            #expect(fig.hold == hold)
        }
        #expect(fig.aiEnabled)
    }

    @Test func ownOffYieldsAndOnResumesWhereItStopped() throws {
        let (s, _, _) = try make()
        let fig = try rig(s)
        tick(s, 2)                                           // the update starts it (run flag 0), the next slice runs it to its AI OFF
        let proc = try #require(fig.aiProc)
        #expect([global(s, "_door_frame"), global(s, "_bchz_frame")] == [.int(1), .int(0)] && proc.suspended && fig.hold == 1)
        tick(s, 3)
        #expect([global(s, "_door_frame"), global(s, "_bchz_frame")] == [.int(1), .int(0)] && !proc.done)
        cmd(s, "AI", .str("ON"), fig: "TESTAI")
        tick(s, 3)
        #expect([global(s, "_door_frame"), global(s, "_bchz_frame")] == [.int(1), .int(2)] && fig.aiProc === proc)
    }

    @Test func offStopsTheFigureOnceAndNoStopMotionKeepsIt() throws {
        let (s, w, _) = try make()
        let fig = try rig(s)
        w.autoCamera = false; fig.viewCams = nil; fig.hidden = false
        fig.setMotion("WALK", loop: true)
        cmd(s, "AI", .str("OFF"), .str("NO_STOP_MOTION"), fig: "TESTAI")
        #expect(fig.motion == "WALK" && fig.hold == 1)
        cmd(s, "AI", .str("ON"), fig: "TESTAI")
        cmd(s, "AI", .str("OFF"), fig: "TESTAI")
        #expect(fig.stopped && fig.idleRequest && fig.hold == 1)
        w.step()
        #expect(fig.motion == "STAND" && !fig.stopped)       // FUN_1098_0789 keeps the idle-fallback bit (1088:4167)
    }

    @Test func secondWordNamesTheFigure() throws {
        let (s, _, lex) = try make()
        let fig = try rig(s)
        cmd(s, "AI", .str("OFF"), .str("TESTAI"), fig: "LEX")
        #expect(fig.hold == 1 && lex.hold == 0)
    }

    @Test func onRefusedWithoutHitPoints() throws {
        let (s, _, _) = try make()
        let fig = try rig(s)
        cmd(s, "AI", .str("OFF"), fig: "TESTAI")
        var rec = s.vm.objectRecord("TESTAI")
        rec[0] = .int(0)
        s.vm.setObject("TESTAI", rec)
        cmd(s, "AI", .str("ON"), fig: "TESTAI")
        #expect(fig.hold == 1)                               // 10d0:04b3, message 0xea
    }

    @Test func playerOnRequestsTheIdleAndKeysWaitForTheCounter() throws {
        let (s, w, lex) = try make()
        lex.setMotion("WALK", loop: true)
        cmd(s, "AI", .str("OFF"), fig: "LEX")
        #expect(w.call(.function, "ISAION", [], proc(s, "LEX")) == .int(0))
        cmd(s, "AI", .str("ON"), fig: "LEX")
        #expect(lex.motion == "STAND" && lex.hold == 0)      // 10a8:1f2e
    }

    private func lexOffWalking(_ s: GameSession, _ lex: Figure) {
        lex.setMotion("WALK", loop: true)
        cmd(s, "AI", .str("OFF"), .str("NO_STOP_MOTION"), fig: "LEX")
    }

    /// 1098:0745 -> 0e49(fig, name, 1, 0) makes the motion task without running it; made in a walk it first runs in the next one.
    @Test func playerOnInAWalkStartsTheIdleInTheNext() throws {
        let (s, _, lex) = try make()
        lexOffWalking(s, lex)
        s.vm.fire("LEX_ON_IN_WALK")
        tick(s)                                           // the fire's own slice suspends
        tick(s)                                           // AI ON in this walk: the update after it keeps WALK
        #expect(lex.hold == 0 && lex.motion == "WALK" && lex.pendingIdle?.name == "STAND" && lex.pendingIdle?.tick == s.vm.tick - 1)
        tick(s)                                           // the task's first run starts it, the update applies it
        #expect(lex.motion == "STAND" && lex.pendingIdle == nil)
    }

    /// TO_0G_USE's case (re/NOTES.md "Lex's height in the zero-g room"): STOPMOTION ends the motion task before its first run.
    @Test func stopmotionBeforeTheTaskRunsDropsTheIdle() throws {
        let (s, _, lex) = try make()
        lexOffWalking(s, lex)
        s.vm.fire("LEX_ON_THEN_STOP")
        tick(s, 3)
        #expect(lex.pendingIdle == nil && lex.motion != "STAND")
    }
}
