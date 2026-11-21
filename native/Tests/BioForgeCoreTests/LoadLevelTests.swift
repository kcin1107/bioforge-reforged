// What LOADLEVEL does to processes and voices (10d0:4d46), PROCESS from a timeline, and the camera distance (1110:1a95); twins of
// re/interp/test_world.py LevelChange (test_call_chain_survives_loadlevel_and_other_global_processes_do_not,
// test_loadlevel_keeps_only_the_named_sound_handle, test_process_from_a_timeline_waits_for_the_scheduler) and AutoCamera
// (test_distance_is_the_engines_approximate_length).
import Foundation
import Testing
@testable import BioForgeCore

private let blocks = """
    { LLSUB
    \tLOADLEVEL CHAOS
    \t_door_frame = 77
    }
    { LLBOOT
    \tCALL LLSUB
    \t_door_frame = 78
    }
    { LLBYST
    \tWAIT 100
    \t_door_frame = 99
    }
    { LLSND
    \tLOADLEVEL CHAOS _door_frame
    }
    { LLNOSND
    \tLOADLEVEL CHAOS
    }
    { PRCCHILD
    \t_door_frame = 5
    }
    { PRCROUTINE
    \tPROCESS PRCCHILD
    \t_door_frame = _door_frame + 100
    }
    [ PRCTIMELINE
    \t00:00 PROCESS PRCCHILD
    \t00:00 _door_frame = _door_frame + 100
    ]

    """

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct LoadLevelTests {
    private func make() throws -> (GameSession, World) {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        s.vm.load(DecodedScript(name: "SYN_LOADLEVEL.scr", text: Array(blocks.utf8), lineStarts: [], columns: [], unresolved: []))
        s.vm.globals["_door_frame"] = .int(0)
        _ = s.world.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], proc(s))
        return (s, s.world)
    }

    private func proc(_ s: GameSession) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    private func frame(_ s: GameSession) -> Int { if case .int(let v)? = s.vm.globals["_door_frame"] { return v }; return -1 }

    @Test func theCallChainSurvivesLoadLevelAndOtherGlobalProcessesDoNot() throws {
        let (s, _) = try make()
        let bystander = try #require(s.vm.fire("LLBYST", owner: "global"))
        s.vm.fire("LLBOOT", owner: "global")
        #expect(frame(s) == 78)                                     // the caller's CALL chain (+0x71 links) survives, even when LOADLEVEL runs in the child's first slice
        #expect(s.vm.process(bystander) == nil)                     // 10b0:13fb has no exemption for the boot chain
        for _ in 0..<200 { s.vm.tickOnce() }
        #expect(frame(s) == 78)                                     // the killed process never ran its tail
    }

    @Test func loadLevelKeepsOnlyTheNamedSoundHandle() throws {
        let (s, w) = try make()
        let keep = w.playSound(0, volume: 255, loop: true), other = w.playSound(1, volume: 255, loop: true), short = w.playSound(2)
        let sub = w.subtitle([.str(""), .int(0x75), .str("hello")], minor: false)
        s.vm.globals["_door_frame"] = .int(keep)                    // LLSND: LOADLEVEL CHAOS _door_frame
        w.soundStops.removeAll()
        let tick = s.vm.tick
        s.vm.fire("LLSND")
        #expect(s.vm.process(keep) != nil)                          // ISHANDLEPLAYING 1
        #expect(!w.soundStops.contains { $0.handle == keep })
        #expect(Dictionary(uniqueKeysWithValues: w.soundStops.map { ($0.handle, $0.tick) }) == [other: tick, short: tick])   // every other voice ends in the mix at the load tick (FUN_1028_12d2)
        #expect(s.vm.process(sub) == nil)                           // a subtitle is no voice: the kill walk ends it
        s.vm.load(DecodedScript(name: "SYN_LOADLEVEL.scr", text: Array(blocks.utf8), lineStarts: [], columns: [], unresolved: []))      // the load dropped the blocks
        s.vm.fire("LLNOSND")                                        // without a numeric argument nothing is kept
        #expect(w.soundStops.contains { $0.handle == keep })
    }

    @Test func processFromATimelineWaitsForTheScheduler() throws {
        let (s, _) = try make()
        s.vm.fire("PRCROUTINE")
        #expect(frame(s) == 105)                                    // a `{` caller runs the child's first slice at once (10c0:37e9)
        s.vm.globals["_door_frame"] = .int(0)
        s.vm.fire("PRCTIMELINE")
        #expect(frame(s) == 100)                                    // a `[` caller does not
        s.vm.tickOnce()
        #expect(frame(s) == 5)                                      // INFERRED: the child first runs in the next tick's walk
    }

    @Test func cameraDistanceIsTheEnginesApproximateLength() throws {
        let (_, w) = try make()
        var differs = false
        for cam in w.data.cameras.values {
            let v = V3(3000, 3000, 0)
            let (_, d) = World.accepts(cam, cam.pos + v)
            #expect(d == Double(approxLength(3000, 3000, 0)))      // 4032, not the Euclidean 4243
            differs = differs || abs(d - (v.x * v.x + v.y * v.y).squareRoot()) > 20
        }
        #expect(differs)
    }
}
