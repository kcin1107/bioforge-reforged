// Missiles (WorldMissiles.swift) against re/interp/test_missiles.py: FIRE's matrix, velocity and range, the carried zip ride, figure hits,
// walls, the spawn-inside-a-solid case and the BEACH zip line, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

private let missileScript = """
{ TESTSHOT
\t< HAS_GRAVITY = 0 >
\t< IS_BOUNCY = 0 >
\t< ELASTICITY = 0 >
\t< IS_REFLECTIVE = 0 >
\t< EXTENT = ( 20, 20, 20 ) >
}
{ TESTBEAM
\t< HAS_GRAVITY = 0 >
\t< IS_BOUNCY = 0 >
\t< ELASTICITY = 0 >
\t< IS_REFLECTIVE = 1 >
\t< EXTENT = ( 20, 20, 20 ) >
}
{ TESTBEAM_HIT_WALL
\t_beam_wall = 1
}
{ TESTSHOT_HIT_TARGET1
\t_shot_hit = 1
\tCURITEM.~9 = 5
\tCURFIG.~9 = 7
}
{ TESTSHOT_HIT
\t_shot_hit = 2
}
{ TESTSHOT_HIT_WALL
\t_shot_wall = 1
\t_shot_x = COORDX (CURITEM)
}
{ ZIPPY
\t< EXTENT = ( 1, 1, 1 ) >
}
{ MMTEST
\t_mm_state = 1
\tSUSPENDWHILE MAKEMISSILE TESTSHOT GUN 10 2 (0,0,0)
\t_mm_state = 2
}
{ ZIPTEST
\t_zip_state = 1
\tSUSPENDWHILE FIRE ZIPPY LEX_POS LEX_POS2 5 0 0 0 CARRY CURFIG
\t_zip_state = 2
}

"""

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct MissileTests {
    /// A LANDPAD world with a VM that has only the test script blocks, and a stand-in process (current figure PLAYER) to issue calls.
    private func make() throws -> (World, ScriptVM, ScriptProcess) {
        let world = try World(resources: try #require(worldResources), level: "LANDPAD")
        let vm = ScriptVM(engine: world, defs: try ScriptDefs(game: requireGame()))
        vm.load(DecodedScript(name: "SYN_MISSILES.scr", text: Array(missileScript.utf8), lineStarts: [], columns: [], unresolved: []))
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return (world, vm, ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER")))
    }

    private func fire(_ w: World, _ p: ScriptProcess, _ args: ScriptValue...) -> Int {
        if case .int(let h) = w.call(.function, "FIRE", args, p) { return h }
        return -1
    }

    private func str(_ s: String) -> ScriptValue { .str(s) }

    @discardableResult private func target(_ w: World, _ p: ScriptProcess, _ name: String, _ pos: V3) -> Figure {
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str(name)], p)
        let fig = w.figures[name]!
        fig.gravity = false
        fig.pos = pos
        return fig
    }

    private func missile(_ w: World) -> Missile { w.items.values.compactMap { $0 as? Missile }.first! }
    private func run(_ w: World, _ vm: ScriptVM, _ n: Int) { for _ in 0..<n { vm.tickOnce(); w.step() } }
    private func ints(_ v: V3?) -> [Int] { [v!.x, v!.y, v!.z].map { Int($0) } }
    private func at(_ speed: Int, _ spin: [Int] = [0, 0, 0]) -> [ScriptValue] {
        [.str("TESTSHOT"), .str("PAD01"), .str("AT"), .int(427), .int(-323), .int(-6), .int(speed)] + spin.map { .int($0) }
    }

    /// A TOWERBOT (a type with a GUN limb and no motions: rest pose) in the middle of PAD01, turned 30 degrees.
    @discardableResult private func tower(_ w: World, _ p: ScriptProcess, _ name: String = "TOWER2") -> Figure {
        _ = w.call(.stmt, "CREATEFIGURE", [.str("TOWERBOT"), .str(name)], p)
        let fig = w.figures[name]!
        fig.gravity = false
        fig.pos = V3(83578, -82740, -1549)
        fig.heading = 30
        return fig
    }

    private func proc(_ vm: ScriptVM, _ fig: String, item: String? = nil) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: fig, curItem: item))
    }

    @Test func makeMissileLimbShotStartsOutsideTheOwnerAndFliesAlongTheLimb() throws {
        let (w, vm, p) = try make()
        let fig = tower(w, p)
        let q = proc(vm, "TOWER2")
        guard case .int(let h) = w.call(.function, "MAKEMISSILE", [.str("TESTSHOT"), .str("GUN"), .int(10), .int(225), .list([.int(0), .int(0), .int(0)])], q) else { Issue.record("no handle"); return }
        let m = missile(w)
        #expect(h == m.handle && vm.process(h) != nil && m.ownerFig === fig)
        #expect(m.dist == 225 * 2048 && m.vel == [-341, -592, 0] && m.spin == [0, 0, 0])
        #expect(ints(m.pos) == [82900, -83916, -2093] && m.rows == [[-222, 128, 0], [128, 222, 0], [0, 0, -256]])
        let travel = m.rows[1].map { -$0 }
        #expect(m.vel == travel.map { fixMul($0, 682) })
        let hull = w.queryHull(fig)
        func touches(_ pos: [Int]) -> Bool {
            World.boxesTouch(SIMD3(pos[0] - m.extent[0], pos[1] - m.extent[1], pos[2] - m.extent[2]),
                             SIMD3(pos[0] + m.extent[0], pos[1] + m.extent[1], pos[2] + m.extent[2]), hull.lo, hull.hi)
        }
        let pos = ints(m.pos)
        #expect(!touches(pos) && touches((0..<3).map { pos[$0] - travel[$0] }))     // pushed out of the owner's box by the last step only
        #expect(w.warnings.isEmpty)
    }

    @Test func makeMissileScriptShotExpiresAndWakesTheWaiter() throws {
        let (w, vm, p) = try make()
        let fig = tower(w, p)
        #expect(w.spawnFor(fig, "MMTEST"))
        let m = missile(w)
        #expect(m.dist == 4096 && vm.globals["_mm_state"] == .int(1) && vm.process(m.handle) != nil)
        for tick in 1..<6 {                                       // |step| = approxLength((-341, -592, 0)) = 709: dist < 0 at the 6th tick
            run(w, vm, 1)
            #expect(vm.process(m.handle) != nil && m.dist == 4096 - 709 * tick)
        }
        run(w, vm, 1)
        #expect(vm.process(m.handle) == nil && vm.globals["_mm_state"] == .int(1) && vm.globals["_shot_wall"] == .int(1) && w.items["TESTSHOT"] == nil)
        run(w, vm, 1)                                             // the waiter, woken by the expiry, goes on in the next walk (1238:077f)
        #expect(vm.globals["_mm_state"] == .int(2))
        #expect(vm.globals["_shot_hit"] == nil)                  // the owner is never the hit figure
    }

    @Test func makeMissileMissingLimbFigureOrNameGivesZeroSilently() throws {
        let (w, vm, p) = try make()
        tower(w, p)
        let list = ScriptValue.list([.int(0), .int(0), .int(0)])
        let calls: [([ScriptValue], String)] = [([.str("TESTSHOT"), .str("NOLIMB"), .int(10), .int(2), list], "TOWER2"),
                                                ([.str("TESTSHOT"), .int(10), .int(2), list], "TOWER2"),
                                                ([.str("TESTSHOT"), .str("GUN"), .int(10), .int(2), list], "NOBODY")]
        for (args, cur) in calls { #expect(w.call(.function, "MAKEMISSILE", args, proc(vm, cur)) == .int(0)) }
        #expect(!w.items.values.contains { $0 is Missile } && w.warnings.isEmpty && !w.unmodelled.contains("MAKEMISSILE: unmodelled function (ignored)"))
    }

    @Test func orientationVelocityAndRange() throws {
        let (w, vm, p) = try make()
        let h = fire(w, p, str("ZIPPY"), str("LEX_POS"), str("LEX_POS2"), .int(5), .int(0), .int(0), .int(0))
        let m = missile(w)
        #expect(h == m.handle && vm.process(h) != nil)
        #expect(ints(m.pos) == [-35584, -71047, -7366])
        #expect(m.dist == 7917)
        #expect(m.vel == [341, 0, 0])
        #expect(m.rows == [[0, 255, 26], [-256, 0, 0], [0, -26, 255]])
        #expect(m.extent == [20, 20, 20] && !m.noCollide && m.spin == [0, 0, 0])
    }

    @Test func atFormAndSpin() throws {
        let (w, vm, p) = try make()
        defer { withExtendedLifetime(vm) {} }          // the world holds its VM weakly
        _ = w.call(.function, "FIRE", at(20, [10, -3, 65538]), p)
        let m = missile(w)
        #expect(ints(m.pos) == [83578, -82740, -1549])           // the centre of the PHYS box
        #expect(m.vel == [1365, 5, 0] && m.dist == 25755 && m.spin == [10, -3, 2])
        #expect(m.extent == [409, 409, 409])
    }

    @Test func orientationTumblesWithSpinAndAimsAlongTheFlightWithout() throws {
        let (w, vm, p) = try make()
        _ = w.call(.function, "FIRE", at(20, [10, -3, 65538]), p)
        _ = w.call(.function, "FIRE", at(20), p)
        run(w, vm, 3)
        let spinning = try #require(w.items["TESTSHOT"] as? Missile), aimed = try #require(w.items["TESTSHOT_2"] as? Missile)
        #expect(spinning.rows == [[-39, 217, 129], [-250, -19, -45], [-27, -135, 217]])
        #expect(aimed.rows == [[-1, 256, 7], [-256, -1, 0], [1, -7, 256]])        // row 1 = -velocity (1365, 5, 0)
    }

    @Test func errorsReturnZero() throws {
        let (w, vm, p) = try make()
        defer { withExtendedLifetime(vm) {} }          // the world holds its VM weakly
        #expect(fire(w, p, str("ZIPPY"), str("NOWHERE"), str("LEX_POS2"), .int(5), .int(0), .int(0), .int(0)) == 0)
        #expect(fire(w, p, str("ZIPPY"), str("LEX_POS")) == 0)
        #expect(!w.items.values.contains { $0 is Missile })
        #expect(w.warnings.count == 2)
    }

    @Test func missilesGetUniqueKeysAndAreNotFloorItems() throws {
        let (w, vm, p) = try make()
        defer { withExtendedLifetime(vm) {} }          // the world holds its VM weakly
        for _ in 0..<2 { _ = w.call(.function, "FIRE", at(5), p) }
        #expect(w.items.values.filter { $0 is Missile }.map(\.name) == ["TESTSHOT", "TESTSHOT_2"])
        #expect(!w.floorItems().contains { $0 is Missile })
        let q = ScriptProcess(vm: p.vm, handle: 0, block: p.block, code: p.vm.code(p.block), ctx: ScriptContext(curFig: "PLAYER", curItem: "TESTSHOT_2"))
        #expect(w.scriptObject(q, .str("CURITEM")).item === w.items["TESTSHOT_2"])
    }

    @Test func spawnInsideASolidExpiresOnTheFirstTick() throws {
        let (w, vm, p) = try make()
        let h = fire(w, p, str("TESTSHOT"), str("OUTWAL1"), str("AT"), .int(600), .int(-323), .int(-6), .int(20), .int(0), .int(0), .int(0))
        let m = missile(w)
        #expect(m.dist == MissileRules.noRange && m.vel == [0, 0, 0] && ints(m.pos) == [30241, -104620, -3590])
        run(w, vm, 1)
        #expect(vm.process(h) == nil && w.items["TESTSHOT"] == nil && vm.globals["_shot_wall"] == .int(1) && vm.globals["_shot_x"] == .int(118))
    }

    @Test func zipRideCarriesTheRiderAndExpiresAtTheRange() throws {
        let (w, vm, p) = try make()
        let start = try #require(w.scriptPoint(p, .str("LEX_POS")))
        let rider = target(w, p, "RIDER", V3(Double(start[0]), Double(start[1]), Double(start[2])))
        rider.gravity = true
        #expect(w.spawnFor(rider, "ZIPTEST"))
        let m = missile(w)
        #expect(vm.globals["_zip_state"] == .int(1) && vm.process(m.handle) != nil && rider.carrier == "ZIPPY" && m.noCollide)
        for tick in 1..<24 {                                      // 7917 range / 341 per tick: dist < 0 at the 24th tick
            let rows = m.rows                                      // the orientation the move saw (the tick turns it afterwards)
            run(w, vm, 1)
            #expect(vm.globals["_zip_state"] == .int(1))
            #expect(ints(m.pos) == [-35584 + 341 * tick, -71047, -7366])
            // ON_ZIPPY = (0,0,0) 0 (0,0,100) on LEX: 100 cm = 2048 units along the missile's row 2 (8 * the 24.8 row)
            #expect(ints(rider.pos) == (0..<3).map { ints(m.pos)[$0] + 8 * rows[2][$0] })
            #expect(m.dist == 7917 - 341 * tick)
        }
        run(w, vm, 1)
        #expect(vm.process(m.handle) == nil && w.items["ZIPPY"] == nil && m.dead && rider.carrier == nil)
        #expect(ints(rider.pos) == [-27400, -71255, -5326])       // 268 units past LEX_POS2: range accounting is by |step|; 2048 up the row 2
        #expect(rider.vx == 0 && rider.vy == 0 && rider.vz == 0)
        #expect(vm.globals["_zip_state"] == .int(1))               // the death only woke the waiter (1238:077f) ...
        run(w, vm, 1)
        #expect(vm.globals["_zip_state"] == .int(2))               // ... it goes on in the next walk
        #expect(!w.unmodelled.contains("FIRE: unmodelled function (ignored)"))
        #expect(w.call(.function, "ISPROCESSVALID", [.int(m.handle)], p) == .int(0))
    }

    @Test func figureHitRunsTheInstanceBlockWithTheHitFigureAndTheMissile() throws {
        let (w, vm, p) = try make()
        target(w, p, "TARGET1", V3(86578, -82740, -1549))
        let h = fire(w, p, str("TESTSHOT"), str("PAD01"), str("AT"), .int(427), .int(-323), .int(-6), .int(5), .int(0), .int(0), .int(0))
        let m = missile(w)
        for tick in 1..<7 {
            run(w, vm, 1)
            #expect(vm.process(h) != nil && Int(m.pos!.x) == 83578 + 341 * tick)
        }
        run(w, vm, 1)
        #expect(vm.process(h) == nil && w.items["TESTSHOT"] == nil && ints(m.pos) == [85965, -82733, -1549])
        #expect(vm.globals["_shot_hit"] == .int(1))
        #expect(vm.objectRecord("TESTSHOT")[9] == .int(5) && vm.objectRecord("TARGET1")[9] == .int(7))   // CURITEM = the missile, CURFIG = the figure
        #expect(vm.globals["_shot_wall"] == nil)
    }

    @Test func figureWithoutAnInstanceBlockRunsTheTypeBlock() throws {
        let (w, vm, p) = try make()
        target(w, p, "OTHER", V3(86578, -82740, -1549))
        _ = w.call(.function, "FIRE", at(5), p)
        run(w, vm, 7)
        #expect(vm.globals["_shot_hit"] == .int(2) && w.items["TESTSHOT"] == nil)
    }

    @Test func hiddenFiguresAreNotHit() throws {
        let (w, vm, p) = try make()
        target(w, p, "TARGET1", V3(86578, -82740, -1549)).viewCams = ["NOCAM"]      // not in the current camera: hidden
        w.camera = w.currentCamera                                                  // (the hide pass needs a camera switched to)
        _ = w.call(.function, "FIRE", at(5), p)
        run(w, vm, 7)
        #expect(w.items["TESTSHOT"] != nil && vm.globals["_shot_hit"] == nil)
    }

    @Test func wallStopsTheMissileAndRunsHitWallInTheSameTick() throws {
        let (w, vm, p) = try make()
        let h = fire(w, p, str("TESTSHOT"), str("PAD01"), str("AT"), .int(600), .int(-323), .int(-6), .int(20), .int(0), .int(0), .int(0))
        let m = missile(w)
        #expect(m.vel == [1365, 0, 0] && m.dist == 70043)
        var tick = 0
        for t in 1..<100 {
            run(w, vm, 1)
            tick = t
            if vm.process(h) == nil { break }
        }
        #expect(tick == 23 && vm.globals["_shot_wall"] == .int(1) && m.vel == [0, 0, 0])
        #expect(ints(m.pos) == [83578 + 1365 * 22, -82740, -1549] && vm.globals["_shot_x"] == .int(443))    // the last good position
        #expect(vm.globals["_shot_hit"] == nil && w.items["TESTSHOT"] == nil)
    }

    /// Fires `kind` along +x from inside HFR at the closed solid DR18 (PHYS, state 1) with its flag byte (record byte 21) set to `flag`;
    /// -> (missile, handle, ticks until the first block, the velocity after it, whether it is still alive then).
    private func wallRun(_ w: World, _ vm: ScriptVM, _ p: ScriptProcess, _ kind: String, flag: UInt8) throws -> (Missile, Int, Int, [Int], Bool) {
        let h = fire(w, p, str(kind), str("HFR"), str("AT"), .int(600), .int(0), .int(0), .int(20), .int(0), .int(0), .int(0))
        let m = missile(w)
        m.pos = V3(-16432, -71293, -4178)
        m.vel = [1365, 0, 0]
        m.dist = 70043
        let i = try #require(w.data.phys.firstIndex { $0.name == "DR18" })
        w.data.phys[i].raw[21] = flag
        var tick = 0
        for t in 1..<100 {
            run(w, vm, 1)
            tick = t
            if vm.process(h) == nil || m.vel != [1365, 0, 0] { break }
        }
        return (m, h, tick, m.vel, vm.process(h) != nil)
    }

    @Test func reflectiveMissileReboundsOffAFlag4WallAndFliesOn() throws {
        let (w, vm, p) = try make()
        let (m, _, tick, vel, alive) = try wallRun(w, vm, p, "TESTBEAM", flag: 4)       // FUN_1070_1d8f: flag 0x20 and the collider's byte & 4
        #expect(tick == 11 && vel == [-1365, 0, 0] && alive && vm.globals["_beam_wall"] == nil)
        #expect(ints(m.pos) == [-16432 + 1365 * 10, -71293, -4178])                    // the X candidate (the move's start) is free
    }

    @Test func reflectiveMissileStopsAtAWallWithoutFlag4() throws {
        let (w, vm, p) = try make()
        let (_, _, tick, vel, alive) = try wallRun(w, vm, p, "TESTBEAM", flag: 3)
        #expect(tick == 11 && vel == [0, 0, 0] && !alive && vm.globals["_beam_wall"] == .int(1))
    }

    @Test func plainMissileStopsAtAFlag4Wall() throws {
        let (w, vm, p) = try make()
        let (_, _, tick, vel, alive) = try wallRun(w, vm, p, "TESTSHOT", flag: 4)
        #expect(tick == 11 && vel == [0, 0, 0] && !alive && vm.globals["_shot_wall"] == .int(1))
    }

    @Test func aLevelChangeDestroysTheMissileWithoutHitWallAndWakesItsWaiter() throws {
        let (w, vm, p) = try make()
        let h = fire(w, p, str("TESTSHOT"), str("PAD01"), str("AT"), .int(427), .int(-323), .int(-6), .int(20), .int(0), .int(0), .int(0))
        run(w, vm, 3)
        _ = w.call(.stmt, "LOADLEVEL", [.str("TUNROOM")], p)                 // 10d0:4d46 -> 10e0:11aa on every missile task, before anything else
        #expect(!w.items.values.contains { $0 is Missile } && vm.process(h) == nil && vm.globals["_shot_wall"] == nil)
    }

    @Test func aLevelChangeRunsTheHitBlockOfAStoredTarget() throws {
        let (w, vm, p) = try make()
        target(w, p, "TARGET1", V3(-30000, -70000, -5000))
        _ = fire(w, p, str("TESTSHOT"), str("PAD01"), str("AT"), .int(427), .int(-323), .int(-6), .int(20), .int(0), .int(0), .int(0))
        missile(w).hit = w.figures["TARGET1"]
        _ = w.call(.stmt, "LOADLEVEL", [.str("TUNROOM")], p)
        #expect(vm.globals["_shot_hit"] == .int(1) && vm.globals["_shot_wall"] == nil && !w.items.values.contains { $0 is Missile })
    }

    @Test func rangeEndsAFreeFlight() throws {
        let (w, vm, p) = try make()
        let h = fire(w, p, str("TESTSHOT"), str("PAD01"), str("AT"), .int(427), .int(-323), .int(-6), .int(20), .int(0), .int(0), .int(0))
        let m = missile(w)
        run(w, vm, 18)
        #expect(vm.process(h) != nil && m.dist == 25755 - 18 * 1366)          // |step| = approxLength((1365, 5, 0)) = 1366
        run(w, vm, 1)
        #expect(vm.process(h) == nil && vm.globals["_shot_wall"] == .int(1))
    }

    @Test func beachZipLineRide() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "BEACH")
        let w = s.world, vm = s.vm
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        let a = try #require(w.scriptPoint(p, .str("ZIP1_A"))), b = try #require(w.scriptPoint(p, .str("ZIP1_B")))
        lex.pos = V3(Double(a[0]), Double(a[1]), Double(a[2]))
        #expect(w.spawnFor(lex, "ZIP1_A_BLOCK_USE"))
        var ticks = 0
        var ran = Set<String>()
        while vm.globals["_ziptripping"] != .int(0) && ticks < 400 {      // POSTZIPMOMBO (the ride's last step) clears it
            s.tick()
            ticks += 1
            for p in vm.procs.values { ran.insert(p.block.name) }
        }
        #expect(ticks == 89 && ints(lex.pos) == [-1172509, -1016488, -19360])
        #expect(!ran.contains("BCHDETH"))                                  // the acid trigger stays clear: Lex hangs 2048 units above the line
        #expect(!w.items.values.contains { $0 is Missile })
        let d = (0..<3).map { Double(ints(lex.pos)[$0] - b[$0]) }
        #expect((d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).squareRoot() < 2300)       // the missile ends 195 units from ZIP1_B's centre; Lex is 2048 units up its row 2 (ON_ZIPPY)
        #expect(!w.unmodelled.contains("FIRE: unmodelled function (ignored)"))
    }

    @Test func heldBlasterShootsFromTheItemAlongMinusRow1AndHitsTheNurse() throws {
        let (s, lex) = try itemWorld()
        let w = s.world
        let blaster = try #require(w.items["BLASTER"])
        #expect(w.attachItem(lex, blaster))                        // right hand
        lex.setMotion("ATK_SHOOT", loop: false)
        lex.idx = 4                                                // the frame of the shoot event (0xf0)
        let nurse = try #require(w.figure("FIRSTBOT"))
        nurse.gravity = false; nurse.pos = V3(400, -32800, -5000); nurse.viewCams = nil
        let p = ScriptProcess(vm: s.vm, handle: 0, block: ScriptBlock("TEST", "routine", 0, nil), code: s.vm.code(ScriptBlock("TEST", "routine", 0, nil)),
                              ctx: ScriptContext(curFig: "LEX", curItem: "BLASTER"))
        guard case .int(let h) = w.call(.function, "MAKEMISSILE", [.str("LASER"), .int(6), .int(60), .list([.int(0), .int(0), .int(0)])], p) else { Issue.record("no handle"); return }
        let m = missile(w)
        #expect(m.type == "LASER" && m.ownerFig === lex && s.vm.process(h) != nil && m.dist == 60 * 2048 && m.vel == [12, -409, -7])
        #expect(ints(m.pos) == [398, -30538, -4817] && m.rows == [[232, 9, -108], [-8, 256, 4], [-108, 0, -232]])
        let hull = w.queryHull(lex), c = ints(m.pos)
        #expect(!World.boxesTouch(SIMD3(c[0] - 409, c[1] - 409, c[2] - 409), SIMD3(c[0] + 409, c[1] + 409, c[2] + 409), hull.lo, hull.hi))
        w.log.removeAll()
        var tick = 0
        for t in 1..<40 {
            s.run(1)
            tick = t
            if s.vm.process(h) == nil { break }
        }
        #expect(tick == 5 && ints(m.pos) == [458, -32583, -4852])
        let blocks = w.log.map(\.block)
        #expect(blocks.contains("LASER_HIT") && !blocks.contains("LASER_HIT_LEX"))      // no LASER_HIT_FIRSTBOT: the type block runs for the nurse
        #expect(s.vm.objectRecord("FIRSTBOT")[0] == .int(29))      // LASER_HIT: CURFIG.~0 (the target's health) > 0, so DAMAGE ENERGY 25
    }

    @Test func blasterInTheRightHandFiresALaserThroughTheScripts() throws {
        let (s, lex) = try itemWorld()
        let w = s.world
        #expect(w.attachItem(lex, try #require(w.items["BLASTER"])))
        #expect(w.spawnFor(lex, "LEX_ATK_SHOOT"))                  // the shoot attack: MOTION ATK_SHOOT
        #expect(lex.motion == "ATK_SHOOT")
        var frames = 0
        for f in 1..<80 {
            s.run(1)
            frames = f
            if w.items.values.contains(where: { $0 is Missile }) { break }
        }
        let m = missile(w)
        #expect(frames == 9 && lex.idx == 3)                       // 0xf0 after frame byte 3: fires while frame 3 shows
        #expect(w.keyLog.last?.tick == 9 && w.keyLog.last?.action == "item" && w.keyLog.last?.detail == .str("BLASTER_FIRE"))
        #expect(m.type == "LASER" && m.ownerFig === lex && m.dist == 60 * 2048 && m.vel == [12, -409, -7])
        #expect(ints(m.pos) == [410, -30552, -4817] && m.rows == [[-232, -9, 108], [-8, 256, 4], [-109, 0, -232]])
        #expect(!w.unmodelled.contains("MAKEMISSILE: unmodelled function (ignored)"))
    }

    @Test func withoutAWeaponTheFigureBlockRunsAndAMissingBlockIsSilent() throws {
        let (s, lex) = try itemWorld()
        let w = s.world, vm = s.vm
        let text = "{ LEX_FIRE\n\t_lex_fire = CURITEM.~9 + 1\n}\n"
        vm.load(DecodedScript(name: "SYN_FIRE.scr", text: Array(text.utf8), lineStarts: [], columns: [], unresolved: []))
        w.fireEventItem(lex)                                       // nothing held
        #expect(vm.globals["_lex_fire"] == .int(1) && w.keyLog.last?.detail == .str("LEX_FIRE"))
        let fork = Item(name: "FORK_X", type: "FORK", owner: "LEX")      // held but not a weapon (no IS_WEAPON)
        fork.slot = "RTHAND"
        w.items[fork.name] = fork
        vm.globals["_lex_fire"] = .int(0)
        w.fireEventItem(lex)
        #expect(vm.globals["_lex_fire"] == .int(1))
        let n = w.keyLog.count
        let other = try #require(w.figure("GUARD1"))
        other.pos = lex.pos
        w.fireEventItem(other)                                     // no GUARD1_FIRE block: nothing happens
        #expect(w.keyLog.count == n && !w.items.values.contains { $0 is Missile })
    }
}
