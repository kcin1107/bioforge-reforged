// The movement fixes (re/NOTES.md "Movement fixes") against re/interp/test_movement.py, with the same cases and the same numbers:
// A rising motions (MANTLE_*, ladders) commit their root z at each wrap and at their end, with the loop rule from the header event list;
// C a GO ends within its radius with no snap; D a LOADLEVEL inside step() drops the PHYS cache; E `support` has no LAND_REVERT clause (so the
// LANDPAD jetson tube is walkable). B (FREEZE, DIE then GET_UP) is in PlaythroughTests / PlaythroughBaseTests / MechanicsTests.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct MovementTests {
    static let floor = -3000

    /// The synthetic ROOM space (floor z -3000) of CollisionResponseTests, with Lex standing in it.
    struct Rig {
        let w: World, vm: ScriptVM, proc: ScriptProcess, lex: Figure, stand: Double, room: Phys
    }

    private func rig() throws -> Rig {
        let res = try #require(worldResources)
        let w = try World(resources: res, level: "CHAOS")
        let vm = ScriptVM(engine: w, defs: try ScriptDefs(game: requireGame()))
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        let stand = Double(Self.floor + lex.assets.footOffset)
        let room = box("ROOM", 0, (-9000, -9000, Self.floor), (9000, 9000, 6000))
        return Rig(w: w, vm: vm, proc: p, lex: lex, stand: stand, room: room)
    }

    private func box(_ name: String, _ state: Int, _ lo: (Int, Int, Int), _ hi: (Int, Int, Int), flags: UInt8 = 0, material: String = "STONE") -> Phys {
        var raw = [UInt8](repeating: 0, count: 64)
        raw[21] = flags
        for (i, b) in material.utf8.enumerated() { raw[45 + i] = b }
        raw[63] = UInt8(state)
        return Phys(name: name, lo: V3(Double(lo.0), Double(lo.1), Double(lo.2)), hi: V3(Double(hi.0), Double(hi.1), Double(hi.2)), state: state, raw: raw)
    }

    private func world(_ r: Rig, _ boxes: Phys...) {
        r.w.data.phys = [r.room] + boxes
        r.w.boxes = nil
        for b in boxes { r.vm.globals["_" + b.name.lowercased() + "_space"] = .int(b.state) }     // bound PHYS join the area's members
        r.lex.pos = V3(2000, 0, r.stand)
        r.lex.setMotion("STAND", loop: true)
        r.lex.area = nil
        _ = r.w.updateArea(r.lex, at: r.lex.pos!)
        r.lex.vz = 0
    }

    private func step(_ r: Rig, _ n: Int = 1) { for _ in 0..<n { r.w.step() } }

    // MARK: A: rising motions

    @Test func theHeaderFlagAndEventListGiveRisesAndTheLoopRule() throws {
        let r = try rig()
        let a = r.lex.assets
        for name in ["CLIMB_SHUTTLE", "CLIMB_UP", "DOWN_LADDER", "ENTER_IRIS1", "MANTLE_3", "MANTLE_6", "MANTLE_9", "OFF_LADDER", "ON_LADDER"] {
            #expect((a.motion(name)?.flags ?? 0) & 2 != 0, Comment(rawValue: name))               // +0x1e8 = header flags & 2 (1098.c:274)
        }
        for name in ["WALK", "STAND", "ATK_H1", "TAUNT1", "DIE"] { #expect((a.motion(name)?.flags ?? 0) & 2 == 0, Comment(rawValue: name)) }
        let names = ["WALK", "RUN", "STAND", "ATK_STAND", "TURN_LEFT", "SIDESTEP_LEFT", "FALLING", "CLIMB_UP", "DOWN_LADDER",
                     "TAUNT1", "ATK_H1", "MANTLE_3", "PUSH_BUTTON", "ON_LADDER", "CLIMB_SHUTTLE"]
        let looping = names.filter { a.motion($0)?.loops == true }
        #expect(looping == ["WALK", "RUN", "STAND", "ATK_STAND", "TURN_LEFT", "SIDESTEP_LEFT", "FALLING", "CLIMB_UP", "DOWN_LADDER"])   // 0xfe (1088:1854)
        #expect(a.motion("STAND")?.loops == true && a.motion("TAUNT1")?.loops == false)
        r.w.cmdMotion(r.lex, "CLIMB_UP", ["CONTINUE"], r.proc)
        #expect(r.lex.loop)
        r.w.cmdMotion(r.lex, "PUSH_BUTTON", ["CONTINUE"], r.proc)
        #expect(!r.lex.loop)
    }

    /// R3, closed by inspection: neither motion's event list holds the 0xfe marker (1088:1854), so `MOTION ... CONTINUE` plays once.
    @Test func motionContinueOfPutBatteryAndTwrVictoryDoesNotLoop() throws {
        let r = try rig()
        for name in ["PUT_BATTERY", "TWR_VICTORY"] {
            let m = try #require(r.lex.assets.motion(name), Comment(rawValue: name))
            #expect(m.loops == false, Comment(rawValue: name))
        }
    }

    @Test func theLastRootZOfTheRisingMotions() throws {
        let r = try rig()
        let a = r.lex.assets
        func last(_ n: String) -> [Int] { let p = a.motion(n)!.frames.last!.pos; return [p.x, p.y, p.z] }
        #expect(["MANTLE_3", "MANTLE_6", "MANTLE_9"].map(last) == [[42, -1078, 1275], [419, -1010, 3083], [-548, -97, 2792]])
        #expect(last("CLIMB_UP") == [0, -13, 1121] && last("DOWN_LADDER") == [0, -20, -1142])
    }

    @Test func mantle3LiftsLexOntoTheLedgeAndHeStays() throws {
        let r = try rig()
        world(r, box("LEDGE", 1, (1000, -3000, Self.floor), (3000, -1000, Self.floor + 1200), flags: 2, material: "METAL"))
        r.lex.pos = V3(2000, 0, r.stand)
        r.lex.heading = 0
        r.w.setPlayerInput(forward: 1)
        var motions: [String] = []
        for _ in 0..<120 {
            step(r)
            if r.lex.motion == "MANTLE_3" { r.w.setPlayerInput() }                       // released at the bump
            if motions.last != r.lex.motion { motions.append(r.lex.motion ?? "") }
        }
        #expect(motions == ["WALK", "MANTLE_3", "STAND"])                                  // no re-mantle: he stands on the ledge
        let p = r.lex.pos!
        let at: [Double] = [p.x, p.y, p.z]
        #expect(at == [2049, -1674, 512])
        #expect(p.z == Double(Self.floor + 1200 + r.lex.assets.footOffset))               // pos.z == ledge top + F
        let q = r.w.queryHull(r.lex)
        #expect(q.sup == Self.floor + 1200 && q.lo.z == Self.floor + 1200)
    }

    @Test func climbUpAndDownLadderCommitTheirLastRootZPerWrap() throws {
        for (name, per) in [("CLIMB_UP", 1121), ("DOWN_LADDER", -1142)] {
            let r = try rig()
            world(r)
            let z0 = r.lex.pos!.z
            r.w.cmdMotion(r.lex, name, ["CONTINUE"], r.proc)
            var wraps = 0, prev = r.lex.idx
            while wraps < 2 {
                step(r)
                if r.lex.idx < prev { wraps += 1 }
                prev = r.lex.idx
            }
            #expect(wraps == 2 && r.lex.pos!.z - z0 == Double(2 * per), Comment(rawValue: name))   // no stand on the support, no fall: gravity is skipped
        }
    }

    @Test func stopmotionOfARisingMotionCommitsTheCurrentRootZ() throws {
        let r = try rig()
        world(r)
        let z0 = r.lex.pos!.z
        r.w.cmdMotion(r.lex, "CLIMB_UP", ["CONTINUE"], r.proc)
        step(r, 60)
        #expect(r.lex.idx == 6)
        #expect(r.lex.pos!.z - z0 == 1121)                                                 // one wrap committed so far
        _ = r.w.call(.stmt, "STOPMOTION", [], r.proc)
        let held = r.lex.frames![0].pos
        #expect(r.lex.pos!.z - z0 == 1121 + 360 && [held.x, held.y, held.z] as [Int] == [189, 183, 0])   // + R of frame 6; the pose carries none
        #expect(!r.lex.rises && r.lex.teeter)                                              // FUN_1098_0789 clears +0x1e8: with no next motion he comes down
        step(r, 10)
        #expect(r.lex.pos!.z - z0 < 1481)
    }

    // MARK: F: a motion's first update applies frame 0's root
    /// Lex starts `motion` at a fixed spot, heading 0; his x, y displacement after each of n updates.
    private func firstUpdates(_ r: Rig, _ motion: String, _ n: Int) -> [[Double]] {
        world(r)
        r.lex.pos = V3(2000, 0, r.stand)
        r.lex.heading = 0
        r.w.cmdMotion(r.lex, motion, ["CONTINUE"], r.proc)
        let p0 = r.lex.pos!
        var out: [[Double]] = []
        for _ in 0..<n {
            step(r)
            out.append([r.lex.pos!.x - p0.x, r.lex.pos!.y - p0.y])
        }
        return out
    }

    @Test func aMotionsFirstUpdateMovesLexByFrame0sRoot() throws {
        let r = try rig()
        let f0 = try #require(r.lex.assets.motion("WALK_BACK")?.frames[0].pos)
        #expect(f0.x == 7 && f0.y == 241)
        #expect(firstUpdates(r, "WALK_BACK", 2) == [[7, 241], [13, 236]])          // then frame 1's own root (13, 236)
    }

    @Test func whoahBackwardGoesOutByFrame0AndFrame1BringsItBack() throws {
        let r = try rig()
        let fr = try #require(r.lex.assets.motion("WHOAH_BACKWARD")?.frames)
        #expect(fr[0].pos.x == -69 && fr[0].pos.y == -259 && fr[1].pos.x == 0 && fr[1].pos.y == 0)
        #expect(firstUpdates(r, "WHOAH_BACKWARD", 2) == [[-69, -259], [0, 0]])
    }

    // MARK: B: FREEZE

    @Test func onlyContinueSkipsTheWaitAndFreezeHoldsTheLastPose() throws {
        let r = try rig()
        world(r)
        let lex = r.lex
        r.w.cmdMotion(lex, "WALK", ["CONTINUE"], r.proc)
        #expect(r.proc.waitPred == nil)
        r.w.cmdMotion(lex, "WAKE_UP", ["FREEZE"], r.proc)
        let wait = try #require(r.proc.waitPred)
        #expect(lex.motion == "WAKE_UP" && !lex.frozen && lex.noIdle)
        #expect(!wait())
        var ticks = 0
        while !lex.finished { step(r); ticks += 1 }
        #expect(ticks == 93 && lex.idx == lex.frames!.count - 1 && wait())
        step(r, 60)
        #expect(lex.motion == "WAKE_UP" && lex.idx == lex.frames!.count - 1 && lex.finished)       // held: no fallback to STAND
        r.w.cmdMotion(lex, "STAND", ["CONTINUE"], r.proc)
        #expect(lex.motion == "STAND" && !lex.noIdle && lex.loop)
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let q = ScriptProcess(vm: r.vm, handle: 1, block: block, code: r.vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        r.w.cmdMotion(lex, "WAKE_UP", ["FREEZE", "CONTINUE"], q)                           // CONTINUE: no wait, and it still animates
        #expect(q.waitPred == nil)
        step(r, 10)
        #expect(lex.noIdle && lex.idx > 0)
    }

    // MARK: C: GO arrival

    @Test func aNumericGosFourthNumberIsTheArrivalRadiusInCm() throws {
        let r = try rig()
        world(r)
        let cases: [([ScriptValue], Int)] = [
            ([.int(10), .int(0), .int(-12), .str("WALK")], 614), ([.int(10), .int(0), .int(-12), .int(0), .str("WALK")], 614),
            ([.int(10), .int(0), .int(-12), .int(50), .str("WALK")], 1024), ([.int(10), .int(0), .int(-12), .int(100), .str("WALK")], 2048)]
        for (args, radius) in cases {
            r.w.cmdGo(r.lex, args, r.proc)
            #expect(r.lex.go?.radius == radius)                                             // N * 2048 / 100, else 0x266 (1098:11c0)
        }
    }

    @Test func aGravityOffGosArrivalKeepsItsHeight() throws {
        let r = try rig()
        world(r)
        r.lex.gravity = false
        let z0 = r.lex.pos!.z
        r.w.cmdGo(r.lex, [.int(20), .int(0), .int(5), .str("WALK")], r.proc)               // target z 5 << 8 = 1280, 2048 above Lex
        var ticks = 0
        while r.lex.go != nil && ticks < 200 { step(r); ticks += 1 }
        let p = r.lex.pos!
        #expect(ticks == 34 && r.lex.motion == "STAND")
        #expect(abs(p.x - 4633) < 0.001 && abs(p.y + 28) < 0.001 && p.z == z0)              // 488 short of (5120, 0), no snap
        #expect(hypot(5120 - p.x, 0 - p.y) < Double(World.goRadius))
    }

    // MARK: D, E

    @Test func aLoadlevelInsideStepDropsTheOldLevelsPhysCache() throws {
        let res = try #require(worldResources)
        let w = try World(resources: res, level: "CHAOS")
        w.boxes = w.physBoxes()                                                            // what step() holds for the frame
        try w.loadObjects("PLATFORM")
        #expect(w.boxes == nil)
        #expect(w.physBoxes().count == 20)
        #expect(w.pointFloor(8553, -116895, 3000, 3000) == -1492)                          // FRMZEROG's floor, the PLATFORM top
    }

    @Test func spaceNeedsTheHullOnTheBox() throws {
        // Live, CRYO_BTN (box edge x -13939): nothing with Lex at x -13567 (hull edge -13935), the button works at -13575 (-13943)
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        for (x, touching) in [(-13567.0, false), (-13575.0, true)] {
            let at = V3(x, -79300, -5133)
            lex.pos = at
            _ = w.updateArea(lex, at: at)
            #expect(w.usableObjects(lex).contains("CRYO_BTN") == touching)
        }
        lex.pos = V3(-13575, -79300, -9133)                                              // the test is on height too: under the box
        #expect(!w.usableObjects(lex).contains("CRYO_BTN"))
    }

    @Test func aWalkKeyBreaksAScriptedMotion() throws {
        // 10a8:0541 tests only the 1098:12bd gate for walk and run keys: a fresh press ends a taunt, but not a RECOIL. A turn key asks only from stand (1098:13e1)
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        lex.pos = V3(-9000, -19500, -5133); lex.manualControl = false
        func press(_ key: Int, _ motion: String) -> String? {
            lex.setMotion("STAND", loop: true)
            w.step()
            w.cmdMotion(lex, motion, ["CONTINUE"], p)
            w.keyDown(key)
            w.step()
            let got = lex.motion
            w.keyUp(key, mods: 0)
            w.step()
            return got
        }
        #expect(press(0x48, "TAUNT1") == "WALK")
        #expect(press(0x4b, "TAUNT1") == "TAUNT1")
        #expect(press(0x48, "RECOIL_TL") == "RECOIL_TL")
    }

    @Test func aHeldTurnKeySteersAWalk() throws {
        // Live: Up + Left stays in walk at 113-117 degrees/s (2 per clock tick here); Left alone plays TURN_LEFT at about 45
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        lex.pos = V3(-9000, -19500, -5133); lex.manualControl = true
        func rate(_ keys: [Int]) -> (String?, Double) {
            lex.heading = 0
            lex.setMotion("STAND", loop: true)
            for k in keys { w.keyDown(k) }
            for _ in 0..<10 { w.step() }
            let h = lex.heading, motion = lex.motion
            for _ in 0..<60 { w.step() }
            let degrees = (lex.heading - h) / 2
            for k in keys { w.keyUp(k, mods: 0) }
            w.step()
            return (motion, degrees)
        }
        let a = rate([0x48, 0x4b]), b = rate([0x4b, 0x48]), c = rate([0x4b])
        #expect(a.0 == "WALK" && a.1 == -120)
        #expect(b.0 == "WALK" && b.1 == -120)                                            // whichever key went down first
        #expect(c.0 == "TURN_LEFT" && abs(c.1 + 45) <= 5)
    }

    @Test func endingARisingMotionMarksTheTeeter() throws {
        // FUN_1098_0789 sets +0x146, so the landing plays no whoah. Live: teeter 0 until ON_LADDER and ENTER_IRIS1 end, 1 at the ladder top
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        lex.pos = V3(-13000, -79300, -5133)
        lex.setMotion("WALK", loop: true)
        lex.setMotion("STAND", loop: true)
        #expect(!lex.teeter)
        lex.setMotion("MANTLE_6", loop: false)
        #expect(!lex.teeter)
        lex.setMotion("STAND", loop: true)
        #expect(lex.teeter)
        lex.teeter = false
        lex.setMotion("CLIMB_UP", loop: true)
        lex.stopMotion()
        #expect(lex.teeter && !lex.rises)
    }

    @Test func aRootMoveRoundsDownOnEveryUpdate() throws {
        // Live moves from CLIMB_UP at heading 87 (FUN_1088_0581): the matrix product is shifted down per axis, not rounded
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        lex.heading = 87
        #expect(w.rootStep(lex, 22, -1) == V2(0, -22))
        #expect(w.rootStep(lex, 0, 5) == V2(4, 0))
        #expect(w.rootStep(lex, -2, 0) == V2(-1, 1))
        #expect(w.rootStep(lex, 0, 5, 2) == V2(3, 0))                                    // spread over two updates, (0, 2) then (0, 3)
    }

    @Test func aLevelArrivalPlacesThePlayerAsGoDoes() throws {
        // Live, the ladder through the iris: gravity off, TO_TANKS arrives at ENTR_TNK's low z as is; gravity on, TO_CRYO_USE arrives at the floor
        // under BTM_LDR + F, far below the box, and CLIMB_UP's -34 stop then falls on the live frame
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        lex.gravity = false
        lex.rootStart = false
        let root = Double(w.rootZ(lex))
        w.cmdLoadLevel([.str("TANKS"), .str("ENTR_TNK")], p)
        #expect(lex.pos == V3(29013, -29002, -3584 - root))
        lex.gravity = true
        for n in 1...5 { vm.globals["_qpit\(n)_space"] = .int(0) }                          // the open iris
        w.cmdLoadLevel([.str("CHAOS"), .str("BTM_LDR")], p)
        #expect(lex.pos == V3(-11380, -74066, -13996 + 2312))
    }

    @Test func supportOffersATallSolidsTopWithNoLandRevertClause() throws {
        let r = try rig()
        world(r, box("WALL", 1, (1000, -3000, Self.floor), (3000, -200, Self.floor + 6000)))     // overlaps Lex's hull in y by 168
        r.lex.pos = V3(2000, 0, r.stand)
        let h = r.w.hull(r.lex)
        #expect(h.lo == SIMD3(1632, -368, -3021) && h.hi == SIMD3(2368, 368, 459))
        #expect(r.w.support(h.lo, h.hi) == 3000)                                           // the wall's top (the old clause: its bottom, -3000)
    }

    @Test func lexWalksIntoTheOpenJetsonTube() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "LANDPAD")
        let w = s.world, vm = s.vm
        w.fireEvent("LANDPAD_LOAD")
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        vm.globals["_jetson1_space"] = .int(0)
        vm.globals["_jetson2_space"] = .int(0)
        w.setPos(lex, V3(27200, -100600, -5623), raw: true)
        lex.heading = 0
        lex.manualControl = false
        w.setPlayerInput(forward: 1)
        s.run(60)
        w.setPlayerInput()
        let q = lex.pos!
        let got: [Int] = [Int(q.x), Int(q.y), Int(q.z)]
        #expect(got == [27218, -103817, -5628])     // inside the tube; PAD_UP's AI OFF stops him there (FUN_1098_0789)
    }
}
