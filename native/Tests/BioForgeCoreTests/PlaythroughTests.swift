// Twins of re/interp/test_playthrough_prison.py `PlayerInput`: the input fixes the prison playthrough needed.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct PlaythroughTests {
    /// test_items.py `make`: CHAOS at its INITGAME state, Lex created by CREATEFIGURE and placed.
    private func make(lex: (Double, Double), heading: Double = 0) throws -> (GameSession, Figure) {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        _ = s.world.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], proc(s))
        let fig = try #require(s.world.player)
        fig.pos = V3(lex.0, lex.1, -5000)
        fig.heading = heading
        s.world.settle(fig)
        return (s, fig)
    }

    private func proc(_ s: GameSession) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    @Test func spaceNamesHeldItemBlocksAfterTheInstance() throws {
        let (s, lex) = try make(lex: (-10186, -33568))
        let w = s.world
        w.items = OrderedMap<Item>()
        let log = Item(name: "DANELOG", type: "LOGBOOK", owner: "LEX")
        log.slot = "INVENTORY"
        w.items[log.name] = log
        #expect(w.placeItem(lex, log, "CARRY"))
        #expect(w.playerUse(lex) == "DANELOG_USE")
    }

    @Test func aUseBlocksGoIsNotReplacedByStand() throws {
        // (starts about 1270 units from PRY_HERE, with the hull on PRY_DR's box: a GO ends within 614 units of its target, so the old start 535 units away arrived at once)
        let (s, lex) = try make(lex: (7000, -20200), heading: 180)
        let w = s.world
        w.items = OrderedMap<Item>()
        w.keyDown(0x39)
        s.run(1)
        w.keyUp(0x39)
        #expect(lex.motion == "WALK" && lex.go != nil)
        let start = lex.pos!
        s.run(10)
        #expect(lex.motion == "WALK" && Int(hypot(lex.pos!.x - start.x, lex.pos!.y - start.y)) > 200)   // towards PRY_HERE's centre
        #expect(w.keyLog.last!.action == "use")
        if case .str(let b) = w.keyLog.last!.detail { #expect(b == "PRY_DR_USE") } else { Issue.record("no use block logged") }
    }

    @Test func freezeAndUnwaitedScriptMotionsYieldToKeys() throws {
        let (s, lex) = try make(lex: (0, -20000))
        let w = s.world
        // a FREEZE'd LOOK_AT_MON, CHAOSHAL's `PUSH_BUTTON CONTINUE FREEZE` and a looping CONTINUE (ATK_STAND: its header event list holds 0xfe)
        for (motion, flags) in [("LOOK_AT_MON", ["FREEZE"]), ("PUSH_BUTTON", ["CONTINUE", "FREEZE"]), ("ATK_STAND", ["CONTINUE"])] {
            w.cmdMotion(lex, motion, flags, proc(s))
            s.run(3)
            w.setPlayerInput(forward: 1)
            s.run(2)
            #expect(lex.motion == "WALK", Comment(rawValue: "\(motion) \(flags)"))
            w.setPlayerInput()
            s.run(10)
        }
        let waiting = proc(s)
        w.cmdMotion(lex, "PUSH_BUTTON", [], waiting)
        w.setPlayerInput(forward: 1)
        s.run(2)
        #expect(lex.motion == "PUSH_BUTTON")
    }
}
