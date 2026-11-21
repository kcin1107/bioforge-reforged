// The engine fixes the base / ending playthrough needed (re/playthrough/base.md) against re/interp/test_playthrough_base.py, with the
// same cases and the same numbers: LOADLEVEL callers and destinations, object-local selectors and renames, CALL argument lists, refused
// MOTIONs, FIGR AI names, and use blocks that take Lex. The harness segments are Python only.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct PlaythroughBaseTests {
    /// `name` at its INITGAME state with its `<LEVEL>_LOAD` event fired.
    private func level(_ name: String) throws -> GameSession {
        let s = try GameSession(resources: try #require(worldResources), level: name)
        s.world.fireEvent(name + "_LOAD")
        return s
    }

    private func proc(_ vm: ScriptVM, _ fig: String = "PLAYER") -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: fig))
    }

    private func script(_ vm: ScriptVM, _ text: String) {
        vm.load(DecodedScript(name: "SYN_PLAYTHROUGH.scr", text: Array(text.utf8), lineStarts: [], columns: [], unresolved: []))
    }

    /// CREATEFIGURE LEX PLAYER, placed on the floor of `arrival`.
    private func lexAt(_ s: GameSession, _ arrival: String) throws -> Figure {
        let w = s.world
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], proc(s.vm))
        let t = try #require(w.arrivalPoint(arrival))
        let lex = try #require(w.player)
        w.setPos(lex, V3(t.xy.x, t.xy.y, t.z + Double(w.foot(lex))), raw: true)
        return lex
    }

    private func ints(_ v: V3) -> [Int] { [v.x, v.y, v.z].map { Int($0) } }

    private func running(_ s: GameSession, _ block: String) -> Bool { s.vm.processes.contains { $0.block.name == block } }

    // MARK: LOADLEVEL callers (10b0:13fb spares the caller's CALL chain; 10d0:4d46 ends the caller only if its script file is not in the new level)

    @Test func toFinalGoesOnAfterItsLoadlevel() throws {
        let s = try level("TUNROOM"), w = s.world
        let lex = try lexAt(s, "GFROMFIN")
        w.spawnFor(lex, "TO_FINAL")
        s.run(100)
        #expect(w.level == "PLATFORM")
        let p = try #require(w.player?.pos)
        // GO FRMZEROG, then GO WALKHERE WALK: the walk ends within 614 units of WALKHERE (8553, -124063) and does not snap onto it
        #expect(ints(p).prefix(2) == [8589, -123501])
        let walkhere = try #require(w.arrivalPoint("WALKHERE"))
        #expect(hypot(p.x - walkhere.xy.x, p.y - walkhere.xy.y) < Double(World.goRadius))
        #expect(w.log.filter { $0.block == "TO_FINAL" }.map(\.name).suffix(4) == ["FACE", "GO", "MOTION", "AI"])
    }

    @Test func aCallerWhoseFileIsNotInTheNewLevelEnds() throws {
        let s = try level("BEACH"), w = s.world
        _ = try lexAt(s, "FROM_PAD")
        s.vm.fire("TO_PAD")                                                       // BCHTOLAN.scr:15 LOADLEVEL LANDPAD FROM_BCH, then SUSPEND
        s.run(3)
        #expect(w.level == "LANDPAD")
        #expect(!running(s, "TO_PAD"))
    }

    @Test func theElevatorRideRunsItsTailAndArrivesAtTheDestinationWord() throws {
        let s = try level("LANDPAD"), w = s.world
        _ = try lexAt(s, "ELV")
        s.vm.fire("SWITCHTOCONTROLLEVEL")                                         // LOADLEVEL CONTROL ELV ELC _sfx_5 (ELEVATOR.scr:304)
        for _ in 0..<400 {
            s.tick()
            if w.level == "CONTROL" && !running(s, "SWITCHTOCONTROLLEVEL") { break }
        }
        let last = try #require(w.levelLoads.last)
        #expect(last.level == "CONTROL" && last.arrival == "ELC")
        let p = try #require(w.player?.pos)
        #expect(ints(p) == [-38574, -71176, -5099])         // the centre of ELC, not the garage PHYS ELV
        #expect(s.vm.tick == 222)                                      // each CALL return goes on in the next walk (1238:077f)
        #expect(w.log.contains { $0.block == "EXITSTASIS" })
    }

    // MARK: object locals (10c0:24e1: selector 1 = CURITEM (+0xe7f), 2 = CURFIG (+0xe7b); INDIVIDUALIZE keeps an object's locals (+0x92))

    @Test func selectorsDecodeAsTheEngineReadsThem() throws {
        let lib = try requireLibrary()
        let scp = try #require(lib.scripts.first { $0.name.lowercased() == "conmach.scr" })
        let text = String(decoding: scp.text, as: UTF8.self)
        #expect(text.contains("IF CURITEM.~0             >= 375 THEN"))
        #expect(text.contains("CURITEM.~2                  = _ABAT_500"))
    }

    @Test func curitemWithoutAnItemIsNotTheFigure() throws {
        let s = try level("CHAOS")
        let p = ScriptProcess(vm: s.vm, handle: 0, block: ScriptBlock("TEST", "routine", 0, nil), code: s.vm.code(ScriptBlock("TEST", "routine", 0, nil)),
                              ctx: ScriptContext(curFig: "LEX", curItem: nil))
        #expect(s.vm.objectName(p, "CURFIG") == "LEX" && s.vm.objectName(p, "CURITEM") == "CURITEM")
    }

    @Test func individualizeKeepsAnItemsLocals() throws {
        let s = try level("CONTROL"), w = s.world
        let lex = try lexAt(s, "ELC")
        script(s.vm, """
        { RENAME_BATTERY
        \tSETCURRENTITEM ORIGBIKEBAT
        \tCURITEM.~0 = 150
        \tCURITEM.~1 = 500
        \tCURITEM.~2 = _ABAT_500
        \tINDIVIDUALIZE CURITEM ABAT_500
        }
        """)
        w.spawnFor(lex, "RENAME_BATTERY")
        #expect(w.items.keys.filter { $0.contains("BAT") }.sorted() == ["ABAT_500", "DANEBAT"])
        #expect(Array(s.vm.objectRecord("ABAT_500").prefix(3)) == [.int(150), .int(500), .int(3)])
        #expect(!s.vm.objectKeys.contains("ORIGBIKEBAT"))
    }

    @Test func individualizeKeepsAFiguresLocals() throws {
        let s = try level("CHAOS"), w = s.world
        let guardFig = try #require(w.figure("GUARD1"))
        var rec = s.vm.objectRecord("GUARD1")
        rec[3] = .int(7)
        s.vm.setObject("GUARD1", rec)
        _ = w.call(.stmt, "INDIVIDUALIZE", [.str("CURFIG"), .str("GRD1B")], proc(s.vm, "GUARD1"))
        #expect(guardFig.name == "GRD1B" && s.vm.objectRecord("GRD1B")[3] == .int(7) && !s.vm.objectKeys.contains("GUARD1"))
    }

    // MARK: CALL / PROCESS argument lists, refused MOTIONs

    @Test func callWithAParenthesisedArgumentList() throws {
        let vm = ScriptVM(engine: RecordingEngine(), defs: try ScriptDefs(game: requireGame()))
        script(vm, """
        { T2 _A _B
        \tRETURN ~0 + ~1 * 100
        }
        { MAIN
        \t_r1 = CALL ( T2( 3 , 4 ) )
        \t_r2 = CALL T2 3 4
        \tPROCESS ( T2( 5 , 6 ) )
        }
        """)
        vm.fire("MAIN")
        vm.tickOnce()
        #expect(vm.globals["_r1"] == .int(403) && vm.globals["_r2"] == .int(403))
    }

    @Test func aRefusedMotionDoesNotBlock() throws {
        let s = try level("CHAOS"), w = s.world
        let lex = try lexAt(s, "PLAYLOC")
        let p = proc(s.vm, "LEX")
        w.cmdMotion(lex, "DIE", ["FREEZE", "CONTINUE"], p)
        w.cmdMotion(lex, "GET_UP_FORWARD", [], p)                                 // 1098:0394 refuses while DIE is current and unfinished: handle 0
        #expect(lex.motion == "DIE" && p.waitPred == nil)
        w.cmdMotion(lex, "GET_UP_FORWARD", ["SNAP_TO"], p)                        // 1098:0394 has no SNAP_TO exception: refused too (REVIVELEX runs after the blocking MOTION DIE)
        #expect(lex.motion == "DIE" && p.waitPred == nil)
    }

    /// OPRSCENE (MASTABA.scr:310): `MOTION DIE FREEZE CONTINUE`, later `MOTION GET_UP_FORWARD`. The guard refuses only while DIE is the current,
    /// unfinished motion; FREEZE keeps the last pose with no idle fallback, and GET_UP_FORWARD then plays.
    @Test func dieThenGetUpOnceDieHasFinished() throws {
        let s = try level("CHAOS"), w = s.world
        let lex = try lexAt(s, "PLAYLOC")
        let p = proc(s.vm, "LEX")
        w.cmdMotion(lex, "DIE", ["FREEZE", "CONTINUE"], p)
        s.run(5)
        w.cmdMotion(lex, "GET_UP_FORWARD", [], p)
        #expect(lex.motion == "DIE")                                              // still falling
        s.run(120)
        #expect(lex.motion == "DIE" && lex.finished && lex.noIdle && lex.idx == lex.frames!.count - 1)   // held, not STAND
        w.cmdMotion(lex, "GET_UP_FORWARD", [], p)
        #expect(lex.motion == "GET_UP_FORWARD" && !lex.noIdle)
        #expect(p.waitPred != nil)
    }

    // MARK: FIGR AI names

    @Test func aLevelFigureTakesItsAINameFromTheRecord() throws {
        var s = try level("PLATFORM")
        #expect(s.world.figure("ELITE")?.aiType == "ELITE")                       // +0x178; 1088:33d4 runs ELITE_AI after AI ON
        s = try level("LANDPAD")
        #expect(s.world.figure("AIRMECHO")?.aiType == "AIRMECHO" && s.world.figure("MARINE4")?.aiType == "INE4")
    }

    // MARK: use blocks that take Lex

    @Test func aUseBlockThatWalksLexKeepsItsWalk() throws {
        let s = try level("CONTROL"), w = s.world
        let lex = try lexAt(s, "ELC")
        w.setPos(lex, V3(51789.0, -45129.0, Double(-165153 + w.foot(lex))), raw: true)     // the garage floor at the bike
        w.keyDown(0x39)
        s.tick()
        w.keyUp(0x39)
        #expect(lex.motion == "WALK" && lex.go != nil)                            // BIKE_USE: GO HOOD WALK (CONMACH.scr:46)
        s.run(30)
        let p = try #require(lex.pos)
        #expect(hypot(p.x - 51533, p.y - -44747) < Double(World.goRadius))        // the GO ends within 614 of the hood, no snap
        #expect(lex.go == nil)
    }
}
