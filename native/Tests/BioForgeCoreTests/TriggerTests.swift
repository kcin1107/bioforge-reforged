// IMAG trigger parity with re/interp/test_world.py `Triggers`: the per-frame pass (FUN_1088_51c3), the mover stop (FUN_1088_50c1),
// area trigger lists, forced cameras and AMINTRIGGER, on CHAOS's cell door DR_ZAP3.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct TriggerTests {
    private struct Rig {
        let s: GameSession, w: World, lex: Figure, proc: ScriptProcess
        let zap: Int, floor: Double

        init() throws {
            s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
            w = s.world
            let block = ScriptBlock("TEST", "routine", 0, nil)
            proc = ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "LEX"))
            lex = Figure(name: "LEX", type: "LEX", assets: try #require(w.asset("LEX")), speed: w.mySpeed("LEX", "LEX"))
            w.figures["LEX"] = lex
            w.playerName = "LEX"
            lex.viewCams = nil
            s.vm.setObject(w.objectKey("LEX"), [.int(100)] + Array(repeating: .int(0), count: 9))       // alive: a dead player fires nothing
            zap = try #require(w.data.triggers.firstIndex { $0.name == "DR_ZAP3" })
            floor = try #require(w.data.phys.first { $0.name == "CE3" }).lo.z + Double(lex.assets.footOffset)
        }

        func place(_ y: Double) {
            lex.pos = V3(-10000, y, floor)
            lex.heading = 0; lex.manualControl = false
            lex.setMotion("STAND", loop: true)
            w.updateArea(lex, at: lex.pos!)
        }

        func area(_ name: String) throws -> Int { try #require(w.data.phys.firstIndex { $0.name == name }) }
        func fired() -> Int { w.events.filter { $0.block == "DR_ZAP3" }.count }
        func cmd(_ name: String, _ args: ScriptValue...) { _ = w.call(.stmt, name, args, proc) }
        func touchesZap() -> Bool {
            let h = w.queryHull(lex), t = w.data.triggers[zap]
            return World.boxesTouch(h.lo, h.hi, t.lo, t.hi)
        }
    }

    @Test func areaListsTheTriggersTouchingItsAnchor() throws {
        let r = try Rig()
        let names = { (n: String) in r.w.areaTriggers(try r.area(n)).map { r.w.data.triggers[$0].name } }
        #expect(try names("DR3") == ["CAM_BLK1", "DR_ZAP3"])
        #expect(try names("CE3") == [])                        // the cell itself: DR_ZAP3 fires once Lex is in DR3
    }

    @Test func everyFrameTriggerFiresWhileInsideAndClearsOutside() throws {
        let r = try Rig()
        r.s.vm.globals["_zap_interrupt"] = .int(1)             // DR_ZAP3 returns at once
        r.place(-14800)                                        // in the DR3 area, hull inside DR_ZAP3
        for _ in 0..<3 { r.w.updateTriggers(r.lex) }
        #expect(r.fired() == 3)                                // flag bit 0x01 clear: every frame
        #expect(r.lex.inTrig?[r.zap] == 1)
        r.place(-12000)                                        // back in CE3, whose list lacks DR_ZAP3 (FUN_1138_1b8a)
        #expect(r.lex.inTrig?[r.zap] == 0)
        r.w.updateTriggers(r.lex)
        #expect(r.fired() == 3)
    }

    @Test func entryOnlyTriggerFiresOncePerEntry() throws {
        let r = try Rig()
        r.s.vm.globals["_zap_interrupt"] = .int(1)
        r.w.data.triggers[r.zap].once = true
        r.place(-14800)
        for _ in 0..<3 { r.w.updateTriggers(r.lex) }
        r.place(-12000)
        r.w.updateTriggers(r.lex)
        r.place(-14800)
        r.w.updateTriggers(r.lex)
        #expect(r.fired() == 2)
    }

    @Test func deadPlayerOrCollisionsOffFiresNothing() throws {
        let r = try Rig()
        r.s.vm.globals["_zap_interrupt"] = .int(1)
        r.place(-14800)
        r.s.vm.setObject(r.w.objectKey("LEX"), [.int(0)] + Array(repeating: .int(0), count: 9))
        r.w.updateTriggers(r.lex)
        r.s.vm.setObject(r.w.objectKey("LEX"), [.int(100)] + Array(repeating: .int(0), count: 9))
        r.cmd("COLLISIONS", .str("CURFIG"), .str("OFF"))
        r.w.updateTriggers(r.lex)
        #expect(r.fired() == 0)
    }

    @Test func blockRunsForThePlayerAndFigureNamedBlocksForOthers() throws {
        let r = try Rig()
        r.s.vm.globals["_zap_interrupt"] = .int(1)
        r.place(-14800)
        r.w.updateTriggers(r.lex)
        #expect(r.w.events.last?.block == "DR_ZAP3")
        let nurse = Figure(name: "FIRSTBOT", type: "LEX", assets: r.lex.assets, speed: r.w.mySpeed("FIRSTBOT", "LEX"))
        #expect(r.w.triggerBlock(r.w.data.triggers[r.zap], nurse) == "DR_ZAP3_FIRSTBOT")
        #expect(r.w.triggerHasBlock(r.w.data.triggers[r.zap]))
    }

    @Test func liveBarsShockLexInTheDoorway() throws {
        let r = try Rig()
        r.s.vm.globals["_bars3_on"] = .int(1)
        r.place(-14800)
        r.s.run(2)
        #expect(r.w.events.contains { $0.block == "DR_ZAP3" })
        #expect(r.lex.motion?.hasPrefix("SHOCK_") == true)
    }

    @Test func cameraTriggerForcesItsCameraUnlessLocked() throws {
        let r = try Rig()
        let blk6 = try #require(r.w.data.triggers.first { $0.name == "CAM_BLK6" })
        r.place(-12000)
        r.w.camera = "CE33"
        r.w.fireTrigger(blk6, r.lex)
        r.w.updateCamera()
        #expect(r.w.currentCamera == "BLK6")
        #expect(r.w.cameraChanges.last?.reason == "trigger forces BLK6")
        #expect(r.w.forcedCamera == nil)
        r.cmd("CAMERA", .str("CE33"))                          // locked: the request is dropped
        r.w.fireTrigger(blk6, r.lex)
        r.w.updateCamera()
        #expect(r.w.currentCamera == "CE33")
        #expect(r.w.forcedCamera == nil)
    }

    @Test func moverStopsOnEnteringATriggerWithABlock() throws {
        let r = try Rig()
        r.place(-12000)
        r.s.vm.globals["_dr3_space"] = .int(0)
        r.lex.inTrig = [UInt8](repeating: 0, count: r.w.data.triggers.count)
        // 6 steps of -833: the third (-14499) is still in CE3, the fourth enters DR3, whose DR_ZAP3 has a block
        #expect(!r.w.figureMove(r.lex, V2(0, -5000)))
        #expect(r.lex.pos?.y == Double(-12000 - 4 * 833))
        #expect(r.lex.area == (try r.area("DR3")))
        #expect(r.touchesZap())
        let stop = try #require(r.lex.pos).y
        r.place(-12000)
        r.lex.inTrig?[r.zap] = 1                               // already inside: no stop
        _ = r.w.figureMove(r.lex, V2(0, -5000))
        #expect(try #require(r.lex.pos).y < stop)
    }

    @Test func amInTriggerTestsTheFigureHull() throws {
        let r = try Rig()
        func am(_ obj: String, _ trig: String) -> ScriptValue { r.w.call(.function, "AMINTRIGGER", [.str(obj), .str(trig)], r.proc) }
        r.place(-14800)
        #expect(am("CURFIG", "DR_ZAP3") == .int(1))
        r.place(-12000)
        #expect(am("CURFIG", "DR_ZAP3") == .int(0))
        #expect(am("LEX", "NO_SUCH") == .int(0))
    }
}
