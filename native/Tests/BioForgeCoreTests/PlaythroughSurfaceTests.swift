// The engine fixes the surface playthrough needed (re/playthrough/surface.md) against re/interp/test_playthrough_surface.py, with the
// same cases and the same numbers: the dangling ELSE, GO to a trigger's centre, the shoot request's name, script loops of a player move,
// and a trigger's LOADLEVEL inside the frame. The harness segments are Python only.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct PlaythroughSurfaceTests {
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
        vm.load(DecodedScript(name: "SYN_SURFACE.scr", text: Array(text.utf8), lineStarts: [], columns: [], unresolved: []))
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

    /// test_items.run: the VM and the world, without the difficulty default.
    private func step(_ s: GameSession, _ n: Int) { for _ in 0..<n { s.vm.tickOnce(); s.world.step() } }

    private func press(_ s: GameSession, _ scan: Int, after: Int) {
        s.world.keyDown(scan)
        s.run(1)
        s.world.keyUp(scan, mods: 0)
        s.run(after)
    }

    private func ints(_ v: V3) -> [Int] { [v.x, v.y, v.z].map { Int($0) } }

    // MARK: IF / ELSE (10d0:3a6c keeps the result per brace depth; 10c0:0f78 skips a nested IF without its ELSE; 10d0:27f9)

    private let dangling = """
        { SYN_DANGLE
        \tIF _temp1 = 1 THEN
        \t\tIF _temp2 = 1 THEN
        \t\t\t_temp3 = 1
        \tELSE
        \t\t_temp3 = 2
        }
        { SYN_BRACED
        \tIF _temp1 = 1 THEN
        \t\t{
        \t\tIF _temp2 = 1 THEN
        \t\t\t_temp3 = 1
        \t\t}
        \tELSE
        \t\t_temp3 = 2
        }

        """

    private func outcomes(_ block: String) throws -> [ScriptValue?] {
        let s = try level("BEACH")
        script(s.vm, dangling)
        var out: [ScriptValue?] = []
        for (a, b) in [(0, 0), (1, 0), (1, 1)] {
            s.vm.globals["_temp1"] = .int(a); s.vm.globals["_temp2"] = .int(b); s.vm.globals["_temp3"] = .int(0)
            s.vm.spawn(block, ctx: ScriptContext())
            step(s, 2)
            out.append(s.vm.globals["_temp3"])
        }
        return out
    }

    @Test func anElseAfterABracelessIfChainAlsoRunsWhenTheOuterIfIsFalse() throws {
        #expect(try outcomes("SYN_DANGLE") == [.int(2), .int(2), .int(1)])
    }

    @Test func anElseAfterABracedThenBelongsToTheOuterIf() throws {
        #expect(try outcomes("SYN_BRACED") == [.int(2), .int(0), .int(1)])
    }

    @Test func theDroppedWarheadCountsDownToZero() throws {
        let s = try level("BEACH")
        s.vm.globals["_warhead_status"] = .int(2); s.vm.globals["_warhead_timer"] = .int(5)   // LEX_BOMB_DROP in FIREBTN2
        s.vm.spawn("WARHEAD_TIMER", ctx: ScriptContext())
        var seq: [ScriptValue?] = []
        for _ in 0..<24 {
            seq.append(s.vm.globals["_warhead_timer"])
            step(s, 1)
        }
        let want: [Int] = Array(repeating: 5, count: 5) + Array(repeating: 4, count: 4) + Array(repeating: 3, count: 4)
            + Array(repeating: 2, count: 4) + Array(repeating: 1, count: 4) + Array(repeating: 0, count: 3)
        #expect(seq == want.map { .int($0) })                                     // one step per 00:04; it used to stop at 4
    }

    // MARK: GO <name> (10d0:33c8): a figure, a waypoint, then an IMAG at its reference point (vtable +0x50: the box centre)

    @Test func aTriggerIsReachedAtItsBoxCentreAndAWaypointAtItsPosition() throws {
        let w = try level("BEACH").world
        let t = try #require(w.goTarget("TO_LNDR"))
        #expect([Int(t.xy.x), Int(t.xy.y)] == [-1137580, -1000026] && t.z == -10752 && !t.isFigure)
        let k = try #require(w.goTarget("KNEEL"))
        #expect([Int(k.xy.x), Int(k.xy.y)] == [-1105184, -1032017] && k.z == -21277)
    }

    // MARK: player input

    @Test func aSuitedLexShootsThroughTheInstanceName() throws {
        let s = try level("LANDPAD"), w = s.world
        let lex = try lexAt(s, "LEX_POS")
        _ = w.call(.stmt, "CHANGEMYFORM", [.str("HARD")], proc(s.vm))
        let blaster = Item(name: "BLASTER", type: "BLASTER", owner: "LEX")
        blaster.slot = "RTHAND"
        w.items["BLASTER"] = blaster
        s.run(10)
        press(s, 0x2e, after: 40)                                                 // C: combat
        press(s, 0x4c, after: 40)                                                 // KP5: LEX_ATK_SHOOT (there is no HARD_ATK_SHOOT)
        #expect(lex.type == "HARD" && lex.combat)
        let tail = w.keyLog.suffix(2).map { "\($0.tick) \($0.action) \($0.detail)" }
        #expect(tail == ["11 combat \(LogValue.bool(true))", "60 item \(LogValue.str("BLASTER_FIRE"))"])
    }

    @Test func aScriptLoopOfAPlayerMoveYieldsToTheKeys() throws {
        let s = try level("LANDPAD"), w = s.world
        let lex = try lexAt(s, "LEX_POS")
        s.run(10)
        lex.setMotion("ATK_M2", loop: true)                                       // AIRMECHO's death: MOTION ATK_M2 CONTINUE
        lex.manualControl = false
        let start = try #require(lex.pos)
        w.keyDown(0x48)
        s.run(1)
        #expect(lex.manualControl && lex.motion == "WALK")
        s.run(10)
        w.keyUp(0x48, mods: 0)
        let p = try #require(lex.pos)
        #expect(ints(p - start) == [18, -733, 0])
    }

    @Test func aTriggerLoadlevelDropsTheOldLevelsFiguresFromTheFrame() throws {
        let s = try level("LANDPAD"), w = s.world
        let lex = try lexAt(s, "FROM_BCH")
        _ = w.figure("LDGBOT1")
        let o = try #require(w.data.objs.first { $0.name == "TO_BCH" })
        let a = v3(o.pos), b = v3(try #require(o.pos2))
        let c = (pointwiseMin(a, b) + pointwiseMax(a, b)) / 2
        w.setPos(lex, V3(c.x, c.y, try #require(lex.pos).z), raw: true)
        s.run(4)                                                                  // TO_BCH: LOADLEVEL BEACH FROM_PAD inside the frame
        #expect(w.level == "BEACH")
        #expect(ints(try #require(lex.pos)) == [-1181989, -987717, -7874])
        #expect(w.figures.keys.sorted() == ["ACIDD", "BCHBOT1", "BCHBOT2", "BCHBOT3", "LEX", "MARINE2", "MARINE3A", "TUMOLT"])    // every FIGR of BEACH (1148:18d3)
    }
}
