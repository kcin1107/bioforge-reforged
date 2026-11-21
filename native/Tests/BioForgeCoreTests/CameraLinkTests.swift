// LINKMETOCAMERAS (re/NOTES.md "Camera-linked processes"), twin of re/interp/test_camera_links.py with the same cases and numbers:
// a link alone pauses nothing, each camera switch sets or clears the flag from the list (10c0:5688), a WAIT, a called child and a timeline's clock
// go on while paused (a timeline catches up in one slice), and the flags the original showed live on CE33.
import Foundation
import Testing
@testable import BioForgeCore

private let blocks = """
{ CAML_ANIM
\tLINKMETOCAMERAS BLK1 HAL1
\t:TOP
\t_door_frame ++
\tSUSPEND
\tJUMP TOP
}
{ CAML_WAIT
\tLINKMETOCAMERAS BLK1
\t_bak_frame = 1
\tWAIT 5
\t_bak_frame = 2
}
[ CAML_TIME
\tLINKMETOCAMERAS BLK1
\t00:05 _fnt_frame = 1
\t00:10 _fnt_frame = 2
\t00:20 _fnt_frame = 3
]
{ CAML_CHILD
\tWAIT 3
\t_bchz_frame = 1
}
{ CAML_PARENT
\tLINKMETOCAMERAS BLK1
\tCALL CAML_CHILD
\t_bchz_frame = 2
}
{ CAML_BAD
\tLINKMETOCAMERAS NOSUCH BLK1
}
{ CE12_LOAD
\tPROCESS CAML_ANIM
}

"""

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct CameraLinkTests {
    /// test_camera_links.py `Base.setUp`: CHAOS at its INITGAME state with the test blocks (CHAOS itself has no CE12_LOAD), Lex as the player, the automatic camera off.
    private func make() throws -> (GameSession, World) {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        let w = s.world
        s.vm.load(DecodedScript(name: "SYN_CAMERA_LINKS.scr", text: Array(blocks.utf8), lineStarts: [], columns: [], unresolved: []))
        for name in ["_door_frame", "_bchz_frame", "_bak_frame", "_fnt_frame"] { s.vm.globals[name] = .int(0) }
        cmd(s, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        w.setPos(try #require(w.player), V3(-11000, -12000, -5093))
        w.autoCamera = false
        return (s, w)
    }

    private func proc(_ s: GameSession) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    private func cmd(_ s: GameSession, _ name: String, _ args: ScriptValue...) { _ = s.world.call(.stmt, name, args, proc(s)) }

    private func tick(_ s: GameSession, _ n: Int = 1) { for _ in 0..<n { s.vm.tickOnce() } }

    private func global(_ s: GameSession, _ name: String) -> ScriptValue? { s.vm.globals[name] }

    @Test func aLinkIsNotACameraAndTheFirstFrameTakesTheNearestAcceptingOne() throws {
        let (s, w) = try make()
        w.autoCamera = true
        let p = try #require(s.vm.spawn("CAML_ANIM"))        // BLK1 HAL1
        tick(s)
        #expect(w.defaultCamera == nil)
        #expect(!p.suspended)                                // linking alone pauses nothing
        let lex = try #require(w.player); let pos = try #require(lex.pos)
        var nearest: (name: String, d: Double)?
        for name in w.data.cameraOrder where !w.disabled.contains(name) {
            let (ok, d) = World.accepts(w.data.cameras[name]!, pos)
            if ok && (nearest == nil || d < nearest!.d) { nearest = (name, d) }
        }
        #expect(w.camera == nil)
        w.updateCamera()
        let want = try #require(nearest).name
        #expect(w.camera == want)                            // 1130:0fa3 with [63ce] 0, at once ([63e0] 1)
        #expect(w.cameraChanges.last?.1 == nil)
        #expect(p.suspended == !p.cameras.contains(want))
    }

    @Test func aLevelLoadLeavesALinkedSurvivorAlone() throws {
        let (s, w) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        let p = try #require(s.vm.spawn("CAML_ANIM"))
        tick(s)
        w.cmdLoadLevel([.str("CHAOS")], p)                   // 1130:0048 clears [63ce], so 1148:15c7 has no camera to switch to
        #expect(w.camera == nil)
        #expect(!w.scriptAuto)                               // LOADLEVEL leaves the flag 1290:63da alone: CAMERA BLK1 set it 0
        #expect(!p.suspended)
    }

    @Test func linkingAlonePausesNothingTheNextSwitchDecides() throws {
        let (s, _) = try make()
        cmd(s, "CAMERA", .str("BLK2"))                       // not in the list
        let p = try #require(s.vm.spawn("CAML_ANIM"))
        #expect(p.cameras == ["BLK1", "HAL1"])
        #expect(!p.suspended)                                // 10c0:547d only registers
        tick(s, 3)                                           // the first slice ran at the spawn; its SUSPEND sleeps through tick 0
        #expect(global(s, "_door_frame") == .int(3))
        cmd(s, "CAMERA", .str("HAL3"))                       // 10c0:5688: not listed
        #expect(p.suspended)
        tick(s, 3)
        #expect(global(s, "_door_frame") == .int(3))
        cmd(s, "CAMERA", .str("HAL1"))                       // listed: on again where it stood
        #expect(!p.suspended)
        tick(s, 2)
        #expect(global(s, "_door_frame") == .int(5))
    }

    @Test func anUnknownNameIsAWarningAndTheRestLinks() throws {
        let (s, w) = try make()
        let p = try #require(s.vm.spawn("CAML_BAD"))
        #expect(w.warnings == ["LINKMETOCAMERAS NOSUCH: unknown camera (error 0x1e)"])
        #expect(p.done)
    }

    @Test func theListHoldsTen() throws {
        let (s, w) = try make()
        let p = try #require(s.vm.spawn("CAML_ANIM"))
        w.linkToCameras(p, ["BLK2", "BLK3", "BLK4", "BLK5", "HAL2", "HAL3", "CE11", "CE12"].map { .str($0) })
        #expect(p.cameras.count == 10)
        w.linkToCameras(p, [.str("CE21")])
        #expect(p.cameras.count == 10)
        #expect(w.warnings == ["LINKMETOCAMERAS CE21: CAML_ANIM already has 10 cameras (error 0xe1)"])
    }

    @Test func aWaitRunsOutWhilePausedAndTheProcessGoesOnWhenResumed() throws {
        let (s, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        let p = try #require(s.vm.spawn("CAML_WAIT"))
        cmd(s, "CAMERA", .str("HAL1"))
        tick(s, 20)                                          // the Wait task is another task, not flagged
        #expect(global(s, "_bak_frame") == .int(1))
        cmd(s, "CAMERA", .str("BLK1"))
        #expect(global(s, "_bak_frame") == .int(1))
        tick(s)
        #expect(global(s, "_bak_frame") == .int(2))
        #expect(p.done)
    }

    @Test func aTimelineCatchesUpInOneSlice() throws {
        let (s, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        _ = s.vm.spawn("CAML_TIME")
        tick(s, 6)
        #expect(global(s, "_fnt_frame") == .int(1))
        cmd(s, "CAMERA", .str("HAL1"))
        tick(s, 30)                                          // 10c8:03e1: the clock is [8330], origin stays
        #expect(global(s, "_fnt_frame") == .int(1))
        cmd(s, "CAMERA", .str("BLK1"))
        tick(s)
        #expect(global(s, "_fnt_frame") == .int(3))
    }

    @Test func aCalledChildRunsOnAndItsParentWaitsForTheCamera() throws {
        let (s, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        _ = s.vm.spawn("CAML_PARENT")
        cmd(s, "CAMERA", .str("HAL1"))
        tick(s, 6)
        #expect(global(s, "_bchz_frame") == .int(1))
        cmd(s, "CAMERA", .str("BLK1"))
        tick(s)
        #expect(global(s, "_bchz_frame") == .int(2))
    }

    @Test func aProcessAnEventBlockStartsIsFlaggedByTheSameSwitch() throws {
        let (s, _) = try make()
        cmd(s, "CAMERA", .str("HAL3"))
        cmd(s, "CAMERA", .str("CE12"))                       // CE12_LOAD's child links BLK1, HAL1; 10c0:5688 comes after the events
        let anim = try #require(s.vm.processes.first { $0.block.name == "CAML_ANIM" })
        #expect(anim.suspended)
        #expect(global(s, "_door_frame") == .int(1))
    }

    @Test func aSwitchOverridesSuspendProcessAndTheSameCameraIsNoSwitch() throws {
        let (s, _) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        let p = try #require(s.vm.spawn("CAML_ANIM"))
        p.suspended = true                                   // SUSPENDPROCESS: the same flag bit (10d0:7985)
        cmd(s, "CAMERA", .str("BLK1"))                       // 10d0 CAMERA: no call of 1130:0114 for the current camera
        #expect(p.suspended)
        cmd(s, "CAMERA", .str("HAL1"))
        #expect(!p.suspended)
    }

    @Test func theAutomaticCameraSwitchesToo() throws {
        let (s, w) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        let p = try #require(s.vm.spawn("CAML_ANIM"))
        w.setCamera("HAL3", "the camera manager")
        #expect(p.suspended)
    }

    /// 1130:050d-0546 pauses a hidden figure's AI, then 1130:0549 runs the links: the bot AIs (LANBOT1_AI ...) link themselves.
    @Test func afterTheShowHidePassTheListDecides() throws {
        let (s, w) = try make()
        cmd(s, "CAMERA", .str("BLK1"))
        let fig = try #require(w.figures["CAYNAN"])
        let p = try #require(s.vm.spawn("CAML_ANIM"))
        fig.aiProc = p; fig.viewCams = ["HAL1"]; fig.hidden = false
        w.updateHidden(fig, "BLK1")                          // not viewed: hidden, but BLK1 is in the AI's list
        #expect(fig.hidden)
        #expect(!p.suspended)
        fig.hidden = false
        w.updateHidden(fig, "HAL3")                          // not viewed and not listed
        #expect(p.suspended)
    }

    /// ZEROG_TURNING adds TURN on the keypad and ZEROG_GRAVITY pulls Lex to GRAVPT; outside ZEG1-4 they stand still (TUNZEROG.scr:30-75).
    @Test func theZeroGProcessesRunOnlyInTheZeroGRoom() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "TUNROOM")
        s.autoDifficulty = false
        cmd(s, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        s.world.autoCamera = false
        _ = s.vm.fire("TUNROOM_LOAD")
        let zeroG = s.vm.processes.filter { ["ZEROG_TURNING", "ZEROG_GRAVITY", "ZEROG_ROOM"].contains($0.block.name) }
        #expect(zeroG.count == 3)
        cmd(s, "CAMERA", .str("ZEG1"))
        #expect(zeroG.allSatisfy { !$0.suspended })
        cmd(s, "CAMERA", .str("TUB1"))
        #expect(zeroG.allSatisfy { $0.suspended })
        cmd(s, "CAMERA", .str("ZEG3"))
        #expect(zeroG.allSatisfy { !$0.suspended })
    }

    /// The flags the original showed on camera CE33 after a new game (dosbox_live `processes`, re/NOTES.md "Camera-linked processes").
    @Test func theCellBlockAtCE33AsSampledLive() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        cmd(s, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        s.world.autoCamera = false
        _ = s.vm.fire("CHAOS_LOAD")
        cmd(s, "CAMERA", .str("CE33"))
        let linked = Dictionary(s.vm.processes.filter { !$0.cameras.isEmpty }.map { ($0.block.name, $0) }, uniquingKeysWith: { a, _ in a })
        let want: [(String, [String], Bool)] = [
            ("CELLTWOBARS", ["BLK2", "BLK3", "CE12", "CE21", "CE22", "CE23", "CE24"], true),
            ("CELL3_MON", ["CE31", "CE32", "CE33"], false),
            ("FLICKER_LIGHT", ["BLK1", "BLK2", "BLK3", "BLK4", "BLK5"], true),
            ("BLOCK_DRIP", ["BLK1", "BLK2", "BLK3", "BLK4", "BLK5"], true),
            ("ANIMGUARD", ["GRD2"], true),
            ("ANIMCRYO", ["CRY1", "CRY2", "CRY3", "CRY4", "CRY5"], true),
        ]
        for (name, cameras, paused) in want {
            let p = try #require(linked[name], "\(name)")
            #expect(p.cameras == cameras, "\(name)")
            #expect(p.suspended == paused, "\(name)")
        }
    }
}
