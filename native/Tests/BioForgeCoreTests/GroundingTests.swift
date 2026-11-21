// Grounding parity with re/interp/test_world.py `Grounding`: the engine's fixed-point foot depth F, the figure hull, the PHYS support
// query, gravity-gated falling that ends in LAND_SOFT, and the wake-up height.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct GroundingTests {
    /// A CHAOS world without a VM (the PHYS states stay as stored) and a stand-in script process to issue commands (test_world.py `cmd`).
    private func makeWorld(_ level: String = "CHAOS") throws -> (World, ScriptProcess) {
        let res = try #require(worldResources)
        let world = try World(resources: res, level: level)
        world.figures = OrderedMap<Figure>()                   // test_world.py make_world: the level loader's figures are cleared
        let vm = ScriptVM(engine: RecordingEngine(), defs: try ScriptDefs(game: requireGame()))
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return (world, ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER")))
    }

    private func makeAttachedWorld(_ level: String = "CHAOS") throws -> (World, ScriptVM, ScriptProcess) {
        let res = try #require(worldResources)
        let world = try World(resources: res, level: level)
        world.figures = OrderedMap<Figure>()                   // test_world.py make_world: the level loader's figures are cleared
        let vm = ScriptVM(engine: world, defs: try ScriptDefs(game: requireGame()))
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return (world, vm, ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER")))
    }

    private func cmd(_ w: World, _ p: ScriptProcess, _ name: String, _ args: ScriptValue...) { _ = w.call(.stmt, name, args, p) }

    @Test func goSnapsToTheFloorUnderTheWaypoint() throws {
        let (w, p) = try makeWorld("LANDPAD")
        cmd(w, p, "GO", .str("LEX_POS"))
        let f = try #require(w.figures["PLAYER"]), wp = try #require(w.data.points["LEX_POS"])
        #expect(f.pos?.z == Double(w.pointFloor(Int(wp.x), Int(wp.y), Int(wp.z), Int(wp.z)) + f.assets.footOffset))
        #expect(abs(f.pos!.z - wp.z - Double(f.assets.footOffset)) < 100)
    }

    @Test func supportIsBedTopOrCellFloor() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(-10944, -7281, -5754)                     // PLAYLOC, above bed CT3
        var h = w.hull(lex)
        #expect(w.support(h.lo, h.hi) == -6052)
        lex.pos = V3(-10795, -9610, -5000)                     // in front of the bed
        h = w.hull(lex)
        #expect(w.support(h.lo, h.hi) == -7405)
    }

    @Test func footDepthMatchesEveryInitgameRecord() throws {
        let res = try #require(worldResources)
        let dir = try #require(try requireGame().initgame)
        var n = 0
        for name in try FileManager.default.contentsOfDirectory(atPath: dir.path).sorted() where name.uppercased().hasSuffix(".IFF") {
            let iff = try LevelIff.parse(try fileBytes(dir.appendingPathComponent(name)))
            for (o, r) in try iff.records() where o.tag == "FIGR" || o.tag == "PLAY" {
                let rec = try #require(r)
                let saved = try rec.buf.s32(try #require(rec.t["s88"]))
                #expect(try #require(res.asset(rec.name.uppercased())).footOffset == saved, "\(rec.name)")
                n += 1
            }
        }
        #expect(n > 40)
    }

    @Test func hullFollowsExtentAndFootDepth() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        #expect(lex.assets.footOffset == 2312)                // MAN.SKL, the engine's F
        lex.pos = V3(0, 0, 0)
        let (lo, hi) = w.hull(lex)
        let r = w.rootZ(lex), e = try #require(w.resources.extents["LEX"])
        #expect(lo == SIMD3(-hullUnits(Int(e.x)), -hullUnits(Int(e.y)), r - 2293))      // s = 112 cm
        #expect(hi.z == r + hullUnits(Int(e.z)))
    }

    @Test func movementCollisionUsesRecoveredFootHull() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(0, 0, 1)                                   // z = 1: a zero last good position skips the slide (FUN_10a0_0ead)
        let h = w.hull(lex)
        w.data.phys = [Phys(name: "FOOT_BLOCK", lo: V3(-10, -10, Double(h.lo.z)), hi: V3(10, 10, Double(h.lo.z + 10)), state: 1)]
        w.boxes = nil

        #expect(!w.figureMove(lex, V2(1, 0)))
        #expect(lex.pos == V3(0, 0, 1))
    }

    @Test func bouncinessSetsCreatedAndLoadedFigureFlags() throws {
        let (w, _, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let bot = try #require(w.figures["FIRSTBOT"])
        #expect(!bot.bouncy)                                    // FIGURES.SCP: FIRSTBOT IS_BOUNCY = 0
        cmd(w, p, "BOUNCINESS", .str("FIRSTBOT"), .str("ON"))
        #expect(bot.bouncy)
        p.curFig = "FIRSTBOT"
        cmd(w, p, "BOUNCINESS", .str("CURFIG"), .str("OFF"))
        #expect(!bot.bouncy)
        bot.vz = -102
        cmd(w, p, "STOPVELOCITY", .str("CURFIG"))
        #expect(bot.vz == 0)
        w.data.figDefs["_BOUNCY_TEST"] = (type: "LEX", pos: V3(0, 0, 0), cams: [], flags: 0x10, aiName: nil, aiOff: 0)
        #expect(try #require(w.figure("_BOUNCY_TEST")).bouncy)
    }

    @Test func nurseRearHitEnablesAuthoredBounciness() throws {
        let session = try GameSession.newGame(resources: try #require(worldResources), afterOpeningTicks: 1020)
        let w = session.world, vm = session.vm
        let lex = try #require(w.player), bot = try #require(w.figures["FIRSTBOT"])
        #expect(lex.enemy == "FIRSTBOT")                     // SPARWITHPLAYER links both target pointers
        bot.pos = V3(0, 0, 0); bot.heading = 0
        lex.pos = V3(0, 2000, 0)                               // behind the robot facing -y
        #expect(vm.spawn("FIRSTBOT_STIMULUS", args: [.int(1)], ctx: ScriptContext(curFig: "FIRSTBOT", owner: "level")) != nil)
        #expect(bot.bouncy)
        #expect(bot.motion == "START_BOUNCE")
        bot.pos = V3(-10090, -15100, -4556)                   // explicit bar-contact fixture
        var sawZap = false
        for _ in 0..<600 {
            session.tick()
            sawZap = sawZap || bot.motion == "ZAPPED"
            if w.figures["FIRSTBOT"] == nil { break }
        }
        #expect(sawZap)
        #expect(vm.globals["_bot_blown"] == .int(1))
        #expect(vm.objectRecord("FIRSTBOT")[0] == .int(-666))
        #expect(w.figures["FIRSTBOT"] == nil && w.figure("FIRSTBOT") == nil)
        let guardBlock = ScriptBlock("CHECK_REMOVED", "routine", 0, nil)
        let guardProc = ScriptProcess(vm: vm, handle: 0, block: guardBlock, code: vm.code(guardBlock), ctx: ScriptContext(curFig: "PLAYER"))
        #expect(w.call(.function, "SETCURRENTFIGURE", [.str("FIRSTBOT")], guardProc) == .int(0))
    }

    @Test func turningBounceContinueMovesAcrossMultipleCycles() throws {
        let (w, _, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let bot = try #require(w.figures["FIRSTBOT"])
        bot.pos = V3(0, 0, 0)
        bot.noCollide = true      // scaffolding: (0, 0, 0) is outside every CHAOS space, where collisions would block every move
        p.curFig = "FIRSTBOT"
        cmd(w, p, "MOTION", .str("BOUNCE"), .str("CONTINUE"))
        #expect(bot.turning)
        #expect(bot.loop)
        let ticks = (bot.frames!.count * w.motionDuration(bot) + World.clockPerTick - 1) / World.clockPerTick
        let start = bot.pos!
        for _ in 0..<ticks { w.step() }
        let first = bot.pos!
        for _ in 0..<ticks { w.step() }
        let second = bot.pos!
        #expect(hypot(first.x - start.x, first.y - start.y) > 1)
        #expect(hypot(second.x - first.x, second.y - first.y) > 1)
    }

    @Test func continueNoncycleDoesNotBlock() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "MOTION", .str("DROPSHIP_WINS"), .str("CONTINUE"))
        let lex = try #require(w.player)
        #expect(!lex.loop)
        #expect(p.waitPred == nil)
    }

    @Test func freshInputReleasesFinishedScriptedPlayerPose() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "GO", .str("LEX_POS"))
        let lex = try #require(w.player)
        lex.viewCams = nil
        lex.go = nil
        lex.pos = V3(0, 0, 0)
        #expect(lex.setMotion("DROPSHIP_WINS", loop: false))
        lex.idx = lex.frames!.count - 1; lex.finished = true
        #expect(lex.finished)
        #expect(lex.motion == "DROPSHIP_WINS")

        w.setPlayerInput(forward: 1)
        w.applyPlayerInput()
        #expect(lex.motion == "WALK")

        w.setPlayerInput()
        lex.manualControl = false
        #expect(lex.setMotion("DROPSHIP_WINS", loop: false))
        lex.idx = lex.frames!.count - 1; lex.finished = true
        w.keyDown(0x2e)                                      // C
        w.applyPlayerInput()
        #expect(lex.combat)
    }

    @Test func theCombatKeyPlaysEnterCombatThenTheCombatIdle() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(0, 0, 0)
        lex.setMotion("ENTER_COMBAT", loop: false)                       // what LEX_ENTER_COMBAT's first slice does, AI_LEX.scr:344
        lex.combat = true
        lex.idx = lex.frames!.count - 1; lex.finished = true
        w.setPlayerInput()
        #expect(w.idleMotion(lex) == "ATK_STAND")                        // FUN_1098_0745
        w.applyPlayerInput()
        #expect(lex.motion == "ENTER_COMBAT")                            // the key handler does not overwrite it
        lex.combat = false
        #expect(w.idleMotion(lex) == "STAND")
    }

    @Test func emptyNoAreaUsesPositiveHullScore() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(0, 0, 0)
        w.data.phys = []
        w.boxes = nil

        #expect(w.figureBlocked(lex, lex.pos!))
    }

    @Test func collisionScoreUsesFixedPointVolumeAndPolarity() throws {
        let (w, _) = try makeWorld()
        let unit = (lo: SIMD3<Int>(0, 0, 0), hi: SIMD3<Int>(256, 256, 256))
        let rounded = (lo: SIMD3<Int>(0, 0, 0), hi: SIMD3<Int>(257, 257, 257))
        let overflow = (lo: SIMD3<Int>(0, 0, 0), hi: SIMD3<Int>(65_536, 65_536, 65_536))
        w.data.phys = []
        w.boxes = nil
        #expect(w.collisionScore(unit, members: []) == 256)
        #expect(w.collisionScore(rounded, members: []) == 259)
        #expect(w.collisionScore(overflow, members: []) == 0)

        let space = Phys(name: "SPACE_FULL", lo: V3(0, 0, 0), hi: V3(256, 256, 256), state: 0)
        w.data.phys = [space]
        w.boxes = nil
        #expect(w.collisionScore(unit, members: [0]) == 0)
        w.data.phys.insert(Phys(name: "SOLID_HALF", lo: V3(0, 0, 0), hi: V3(128, 256, 256), state: 1), at: 0)
        w.boxes = nil
        #expect(w.collisionScore(unit, members: [0, 1]) == 128)
        w.data.phys.append(Phys(name: "SPACE_HALF", lo: V3(128, 0, 0), hi: V3(256, 256, 256), state: 0))
        w.boxes = nil
        #expect(w.collisionScore(unit, members: [0, 1, 2]) == 0)
    }

    /// test_world.py `test_area_members_are_every_phys_touching_the_grown_anchor`: FUN_1138_131c's physical_objs holds every
    /// PHYS, solids included, touching the anchor box grown by 0x1000; only spaces and bound PHYS anchor areas.
    @Test func areaMembersAreEveryPhysTouchingTheGrownAnchor() throws {
        let (w, _, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(0, 0, 0)
        w.data.phys = [
            Phys(name: "AREA", lo: V3(-1_000, -1_000, -3_000), hi: V3(1_000, 1_000, 2_000), state: 0),
            Phys(name: "NEAR", lo: V3(1_000 + 0x1000, -1_000, -3_000), hi: V3(6_000, 1_000, 2_000), state: 1),
            Phys(name: "FAR", lo: V3(1_001 + 0x1000, -1_000, -3_000), hi: V3(6_000, 1_000, 2_000), state: 1),
            Phys(name: "UNBOUND", lo: V3(-1_000, -1_000, -3_000), hi: V3(1_000, 1_000, 2_000), state: 1),
        ]
        w.boxes = nil

        #expect(w.physAreas().map(\.anchor) == [0])
        _ = w.updateArea(lex, at: lex.pos!)
        #expect(lex.area == 0)
        #expect(w.physAreas().first?.members == [0, 1, 3])
        #expect(w.figureBlocked(lex, lex.pos!))
        w.data.phys.removeLast()
        w.boxes = nil
        #expect(!w.figureBlocked(lex, lex.pos!))
    }

    @Test func movementReselectsAreaAtCollisionSubsteps() throws {
        let (w, _, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(0, 0, 0)
        w.data.phys = [
            Phys(name: "LEFT", lo: V3(-500, -500, -5_000), hi: V3(500, 500, 2_000), state: 0),
            Phys(name: "RIGHT", lo: V3(200, -500, -5_000), hi: V3(1_400, 500, 2_000), state: 0),
        ]
        w.boxes = nil

        #expect(w.figureMove(lex, V2(600, 0)))
        #expect(lex.pos == V3(600, 0, 0))
        #expect(lex.area == 1)
        try w.loadObjects("LANDPAD")
        #expect(lex.area == nil)
    }

    /// test_world.py `test_positive_door_blocks_and_open_or_neutral_passes`: the walk's root bob dips the hull below CE3's floor,
    /// which FUN_10a0_21b2 lifts back onto the support; DR3 closed or neutral blocks, open passes.
    @Test func doorStateGatesWalkingThroughDR3() throws {
        for (state, passes) in [(1, false), (0, true), (2, false)] {
            let (w, vm, p) = try makeAttachedWorld()
            cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
            cmd(w, p, "GO", .str("PLAYLOC"))
            let lex = try #require(w.player)
            let door = try #require(w.data.phys.first { $0.name == "DR3" })
            let floor = try #require(w.data.phys.first { $0.name == "CE3" }).lo.z
            lex.pos = V3(-10000, door.hi.y + 500, floor + Double(lex.assets.footOffset))
            lex.heading = 0; lex.manualControl = false
            lex.setMotion("STAND", loop: true)
            cmd(w, p, "COLLISIONS", .str("CURFIG"), .str("ON"))
            w.setPlayerInput(forward: 1)
            vm.globals["_dr3_space"] = .int(state)
            for _ in 0..<60 { w.step() }
            #expect(passes ? lex.pos!.y < door.lo.y : lex.pos!.y > door.hi.y, "state \(state)")
        }
    }

    /// test_world.py `test_mover_step_arithmetic`.
    @Test func moverStepArithmetic() {
        #expect(approxLength(3000, -4000, 0) == 4000 + 750 + 375 - 93)
        #expect(approxLength(0, 0, 0) == 0)
        #expect(fixDiv(-5000, 6 << 8) == -833)
        #expect(fixDiv(5000, 6 << 8) == 833)
        #expect(moveSteps(0, -5000, 736) == 6)
        #expect(moveSteps(736, 0, 736) == 1)
    }

    /// test_world.py `test_blocked_oblique_move_slides_along_the_wall`.
    @Test func blockedObliqueMoveSlidesAlongTheWall() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        // z = 1, not 0: FUN_10a0_0ead skips the slide when the last good position is exactly the zero vector
        lex.pos = V3(0, 0, 1)
        lex.vz = 0
        w.data.phys = [
            Phys(name: "ROOM", lo: V3(-5000, -5000, -3000), hi: V3(5000, 5000, 2000), state: 0),
            Phys(name: "WALL", lo: V3(-5000, 1000, -3000), hi: V3(5000, 1200, 2000), state: 1),
        ]
        vm.globals["_wall_space"] = .int(1)
        w.boxes = nil
        #expect(!w.figureMove(lex, V2(300, 1500)))
        #expect(lex.pos == V3(150, 0, 1))
        lex.pos = V3(0, 500, 1)
        #expect(!w.figureMove(lex, V2(100, 200)))
        #expect(lex.pos == V3(100, 500, 1))
        lex.pos = V3(0, 0, 0)
        lex.vz = -10
        #expect(!w.figureMove(lex, V2(300, 1500)))
        #expect(lex.pos == V3(0, 0, 0))
    }

    @Test func bouncyCollisionRollsBackAxesWithoutTurning() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        lex.pos = V3(0, 0, 0)
        lex.bouncy = true; lex.vz = -10; lex.heading = 47
        let room = Phys(name: "ROOM", lo: V3(-5000, -5000, -3000), hi: V3(5000, 5000, 2000), state: 0)
        let wallX = Phys(name: "WALL_X", lo: V3(1000, -5000, -3000), hi: V3(1200, 5000, 2000), state: 1)
        let wallY = Phys(name: "WALL_Y", lo: V3(-5000, 1000, -3000), hi: V3(5000, 1200, 2000), state: 1)
        vm.globals["_wall_x_space"] = .int(1); vm.globals["_wall_y_space"] = .int(1)
        w.data.phys = [room, wallX]; w.boxes = nil
        #expect(!w.figureMove(lex, V2(1500, 300)))
        #expect(lex.pos == V3(0, 150, 0))
        #expect(lex.heading == 47)
        lex.pos = V3(0, 0, 0)
        w.data.phys = [room, wallY]; w.boxes = nil
        #expect(!w.figureMove(lex, V2(300, 1500)))
        #expect(lex.pos == V3(150, 0, 0))
        lex.pos = V3(0, 0, 0)
        w.data.phys = [room, wallX, wallY]; w.boxes = nil
        #expect(!w.figureMove(lex, V2(1500, 1500)))
        #expect(lex.pos == V3(0, 0, 0))
        lex.bouncy = false
        w.data.phys = [room, wallY]; w.boxes = nil
        #expect(!w.figureMove(lex, V2(300, 1500)))
        #expect(lex.pos == V3(0, 0, 0))
    }

    /// test_world.py `test_large_delta_stops_at_positive_door_boundary`: a straight push into DR3 stays at its start.
    @Test func largeDeltaIntoClosedDoorStaysAtStart() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "GO", .str("PLAYLOC"))
        let lex = try #require(w.player)
        let door = try #require(w.data.phys.first { $0.name == "DR3" })
        let floor = try #require(w.data.phys.first { $0.name == "CE3" }).lo.z
        lex.pos = V3(-10000, door.hi.y + 500, floor + Double(lex.assets.footOffset))
        lex.setMotion("STAND", loop: true)
        cmd(w, p, "COLLISIONS", .str("CURFIG"), .str("ON"))
        vm.globals["_dr3_space"] = .int(1)
        let start = lex.pos!
        #expect(!w.figureMove(lex, V2(0, -5000)))
        #expect(lex.pos == start)
    }

    /// test_world.py `test_stopmotion_holds_the_pose_without_root_travel`.
    @Test func stopMotionHoldsThePoseWithoutRootTravel() throws {
        let (w, _, p) = try makeAttachedWorld("LANDPAD")
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "GO", .str("LEX_POS"))
        let lex = try #require(w.player)
        cmd(w, p, "MOTION", .str("WALK"), .str("CONTINUE"))
        for _ in 0..<20 { w.step() }
        let pose = lex.frames![lex.idx], pos = lex.pos!
        cmd(w, p, "STOPMOTION")
        #expect(lex.frames?.count == 1 && lex.frames?[0].limbs == pose.limbs)
        for _ in 0..<30 { w.step() }
        #expect(lex.pos!.x == pos.x && lex.pos!.y == pos.y)
        #expect(w.call(.function, "ISMYMOTION", [.str("WALK")], p) == .int(0))
        cmd(w, p, "MOTION", .str("STAND"), .str("CONTINUE"))
        #expect(lex.motion == "STAND" && !lex.frozen)
    }

    /// test_world.py `test_stopmotion_bakes_a_turning_motions_yaw_once`.
    @Test func stopMotionBakesATurningMotionsYawOnce() throws {
        let (w, _, p) = try makeAttachedWorld("LANDPAD")
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "GO", .str("LEX_POS"))
        let lex = try #require(w.player)
        cmd(w, p, "MOTION", .str("TURN_LEFT"), .str("CONTINUE"))
        let f = try #require(lex.frames)
        lex.idx = f.count / 2
        let yaw = f[lex.idx].limbs[0].z - f[0].limbs[0].z
        #expect(yaw != 0)
        let heading = lex.heading
        cmd(w, p, "STOPMOTION")
        #expect(abs(lex.heading - (heading - Double(yaw) * 45 / 32)) < 1e-9)
        cmd(w, p, "MOTION", .str("STAND"), .str("CONTINUE"))
        #expect(abs(lex.heading - (heading - Double(yaw) * 45 / 32)) < 1e-9)
    }

    @Test func gravityFlagGatesA2000UnitNormalFloorFall() throws {
        let (w, p) = try makeWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        // BLK (ceiling -799) is tall enough for the whole 2000-unit fall: in CE3 (ceiling -2583) the hull would poke out of the space,
        // which FUN_10a0_0ead treats as a collision, and land at once
        lex.pos = V3(-5000, -20000, Double(-7405 + lex.assets.footOffset + 2000))
        cmd(w, p, "GRAVITY", .str("CURFIG"), .str("OFF"))
        w.step()
        #expect(lex.pos?.z == Double(-7405 + lex.assets.footOffset + 2000))
        cmd(w, p, "GRAVITY", .str("CURFIG"), .str("ON"))      // only sets the bit; the next frames fall
        #expect(lex.pos?.z == Double(-7405 + lex.assets.footOffset + 2000))
        w.step()
        #expect(lex.falling)
        #expect(lex.vz == -World.fallDV)
        var velocities = [lex.vz]
        for _ in 0..<60 {
            w.step()
            if lex.falling { velocities.append(lex.vz) }
            if !lex.falling { break }
        }
        #expect(!lex.falling)
        #expect(lex.vz == 0)
        #expect(velocities.prefix(5) == [-102, -204, -306, -408, -510])
        #expect(lex.motion == "LAND_SOFT")                    // FUN_10a0_0ead clears vz before 0e24 classifies it
        w.step()
        #expect(lex.pos?.z == Double(-7405 + lex.assets.footOffset))
    }

    @Test func lexInBedHasTheOriginalsHeight() throws {
        let res = try #require(worldResources)
        let s = try GameSession.newGame(resources: res, afterOpeningTicks: 300)
        let lex = try #require(s.world.player)
        #expect(!lex.gravity)
        #expect(lex.motion == "WAKE_UP")
        #expect(lex.pos?.z == -5714)                                       // live: origin + R, R 0 in WAKE_UP; GO PLAYLOC's -5754 was taken with R -40 (10a0:1ff0)
        #expect(s.world.modelRootZ(lex) == 0)
        lex.frames = [lex.frames![0]]; lex.idx = 0; lex.rootStart = false
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        #expect(s.world.call(.function, "COORDZ", [.str("PLAYER")], p) == .int(-5714 >> 8))     // 10d8:104e: origin + R
    }

    @Test func newGameWakeUpEndsOnTheCellFloor() throws {
        let res = try #require(worldResources)
        let s = try GameSession.newGame(resources: res)
        s.runToChaosLoad()
        var back: [Double] = [], held: [String] = [], woke = false
        for _ in 0..<openingTicks(1200) {                                   // Lex stands from old tick 1155
            s.tick()
            woke = woke || s.world.player?.motion == "WAKE_UP_HEAD"
            if woke, let p = s.world.player, p.motion == "STAND", p.pos?.y == -7281 {   // the idle at WAKE_UP's end, in bed: live, never drawn
                held.append("\(p.heldPose?.motion ?? "-") \(p.heldPose?.idx ?? -1)")
            }
            if let p = s.world.player, p.motion == "OUT_OF_BED", p.idx >= 21, let v = s.world.posed(p) {
                back.append(v.map(\.y).reduce(0, +) / Double(v.count))      // the step off the bed: the drawn body never slides back
            }
        }
        #expect(zip(back, back.dropFirst()).map { $1 - $0 }.max()! < 20)
        #expect(held == ["WAKE_UP 30"])                                     // drawn: WAKE_UP's last frame (DOSBox-X 2026-11-12)
        let lex = try #require(s.world.player)
        #expect(lex.gravity)
        #expect(lex.pos?.z == Double(-7405 + lex.assets.footOffset))
        #expect(lex.pos!.z + Double(lex.frames![0].pos.z) == -5133)       // support + F + root z, as in the real saves
        #expect(lex.pos!.y > -9000 && lex.pos!.y < -8800)       // OUT_OF_BED carries him ~1640 units from y -7281 (frame 0's root included)
        let caynan = try #require(s.world.figures["CAYNAN"])
        #expect(caynan.aiEnabled && caynan.aiProc == nil)                  // hidden CAYNAN_AI remains pending after READY_CAYNAN
    }

    /// test_world.py `test_figure_push_arithmetic`.
    @Test func figurePushArithmetic() {
        #expect(length2d(3000, -4000) == 5000)
        #expect(length2d(3, 4) == 5)
        #expect(length2d(0, 0) == 0)
        // The original's nurse beside Lex after OUT_OF_BED (DOSBox-X): Lex lands at (-10270, -8879), as observed live.
        #expect(pushOut(target: V3(-10795, -9610, -5093), other: V3(-11394, -10445, -4515), r: 1945) == V3(-10270, -8879, -5093))
        // q = (r << 4) / |d| is an integer: an overlap below r / 16 leaves the target where it was.
        #expect(pushOut(target: V3(-10795, -9610, 0), other: V3(-10478, -11490, 0), r: 1945) == V3(-10795, -9610, 0))
    }

    /// test_world.py `test_figure_radius_and_hit_points_come_from_figures_scp`.
    @Test func figureRadiusAndHitPointsComeFromFiguresScp() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let lex = try #require(w.player), nurse = try #require(w.figures["FIRSTBOT"])
        #expect(w.personalRadius(lex) == 819)                  // LEX PERSONAL_RADIUS 40
        #expect(w.personalRadius(nurse) == 1126)               // FIRSTBOT 55
        #expect(vm.objects["FIRSTBOT"] == [50, 0, 0, 0, 0, 50, 0, 0, 0, 0].map { ScriptValue.int($0) })   // fresh: ~0 = ~5 = MAX HPS
        // Level figures take their FIGR record's locals (DOSBox-X: GUARD1 ~0 100, ~5 170).
        #expect(vm.objects["GUARD1"] == [100, 0, 0, 0, 0, 170, 0, 0, 0, 0].map { ScriptValue.int($0) })
        #expect(vm.objects["CAYNAN"].map { Array($0.prefix(6)) } == [200, 0, 0, 0, 0, 200].map { ScriptValue.int($0) })
    }

    /// FUN_1088_31fb enables AI; FUN_1088_3371 starts it only when the figure's update finds it visible and alive.
    @Test func aiStartIsDeferredUntilVisibleFigureUpdate() throws {
        let (w, vm, p) = try makeAttachedWorld()
        try vm.loadLevel("CHAOS", library: w.resources.library)
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let bot = try #require(w.figures["FIRSTBOT"])
        bot.pos = V3(0, 0, 0)
        vm.setObject("FIRSTBOT", [.int(50), .int(0), .int(0), .int(0), .int(0), .int(50), .int(0), .int(0), .int(0), .int(0)])
        p.curFig = "FIRSTBOT"
        cmd(w, p, "SETAI", .str("NURSEBOT"))
        cmd(w, p, "AI", .str("ON"))
        #expect(bot.aiEnabled && bot.aiProc == nil)
        bot.viewCams = ["VISIBLE"]
        w.camera = "HIDDEN"
        w.step()
        #expect(bot.aiProc == nil)
        w.camera = "VISIBLE"
        w.step()
        let task = try #require(bot.aiProc)
        #expect(task.block.name == "NURSEBOT_AI" && task.curFig == "FIRSTBOT")
        cmd(w, p, "AI", .str("ON"))
        #expect(bot.aiProc === task)                                       // already running: no second process
        cmd(w, p, "AI", .str("OFF"))
        #expect(!bot.aiEnabled)
        #expect(task.suspended && !task.done && bot.aiProc === task)       // FUN_1088_3196 pauses the process, it does not end it
        #expect(vm.process(task.handle) != nil)
        cmd(w, p, "AI", .str("ON"))
        #expect(!task.suspended && bot.aiProc === task)
        vm.finish(task)
        cmd(w, p, "AI", .str("OFF"))
        w.step()
        #expect(bot.aiProc?.done == true)                                  // the counter holds back a new start (FUN_1088_3371)
    }

    /// test_world.py `test_standing_figure_is_pushed_out_of_another_figures_radius`.
    @Test func standingFigureIsPushedOutOfAnotherFiguresRadius() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let lex = try #require(w.player), nurse = try #require(w.figures["FIRSTBOT"])
        w.data.phys = [Phys(name: "ROOM", lo: V3(-9000, -9000, -6000), hi: V3(9000, 9000, 6000), state: 0)]
        w.boxes = nil
        lex.pos = V3(0, 0, 0)
        lex.setMotion("STAND", loop: true)
        nurse.pos = V3(600, 0, 0)
        p.curFig = "PLAYER"
        cmd(w, p, "COLLISIONS", .str("CURFIG"), .str("ON"))
        p.curFig = "FIRSTBOT"
        cmd(w, p, "COLLISIONS", .str("CURFIG"), .str("ON"))
        let start = lex.pos!
        w.step()
        #expect(lex.pos!.x < start.x - 1000)                   // out to ~1945 from the nurse
        // A dead (~0 = 0) or hidden figure does not push.
        lex.pos = start
        var rec = vm.objectRecord("FIRSTBOT")
        rec[0] = .int(0)
        vm.setObject("FIRSTBOT", rec)
        w.step()
        #expect(lex.pos!.x == start.x && lex.pos!.y == start.y)
    }

    /// test_world.py `test_avoidance_point_list_rules`.
    @Test func avoidancePointListRules() throws {
        let (w, _, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        var names = ["AVDBAR1", "AVDBAR2", "AVDBAR3", "AVDBAR4", "WAY_PT2", "GETMEAT"].filter { w.data.points[$0] != nil }
        names += w.data.points.keys.sorted().filter { !names.contains($0) }.prefix(9 - names.count)
        cmd(w, p, "ADDAVOIDANCEPOINT", .str(names[0]), .int(110))
        cmd(w, p, "ADDAVOIDANCEPOINT", .str(names[0]), .int(50))           // already listed: radius kept
        cmd(w, p, "ADDAVOIDANCEPOINT", .str(names[1]), .int(0))            // radius must be > 0
        cmd(w, p, "ADDAVOIDANCEPOINT", .str("NO_SUCH_OBJECT"), .int(100))
        #expect(lex.avoid.map(\.name) == [names[0]] && lex.avoid.map(\.radius) == [110])
        for (i, n) in names.enumerated().dropFirst() { cmd(w, p, "ADDAVOIDANCEPOINT", .str(n), .int(100 + i)) }
        #expect(lex.avoid.map(\.name) == Array(names.prefix(8)))            // at most 8
        cmd(w, p, "REMOVEAVOIDANCEPOINT", .str(names[7]))                     // slot 7 is not scanned
        #expect(lex.avoid.count == 8)
        cmd(w, p, "REMOVEAVOIDANCEPOINT", .str(names[2]))                     // later entries shift down
        #expect(lex.avoid.map(\.name) == [names[0], names[1]] + Array(names[3..<8]))
        #expect(lex.avoid.map(\.radius) == [110, 101, 103, 104, 105, 106, 107])
        cmd(w, p, "REMOVEAVOIDANCEPOINT", .str(names[7]))                     // now in slot 6
        #expect(lex.avoid.count == 6)
    }

    /// test_world.py `test_avoidance_point_pushes_a_living_figure_with_collisions_off`.
    @Test func avoidancePointPushesALivingFigureWithCollisionsOff() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        cmd(w, p, "GO", .str("PLAYLOC"))
        let lex = try #require(w.player), point = try #require(w.data.points["AVDBAR3"])
        let start = point + V3(300, 400, 0)
        lex.pos = start
        lex.setMotion("STAND", loop: true)
        lex.noCollide = true
        #expect(!lex.collisions)
        cmd(w, p, "ADDAVOIDANCEPOINT", .str("AVDBAR3"), .int(110))          // (110 << 11) / 100 = 2252
        w.step()
        let pushed = pushOut(target: start, other: point, r: 2252)
        #expect(lex.pos!.x == pushed.x && lex.pos!.y == pushed.y)
        #expect(abs(((lex.pos!.x - point.x) * (lex.pos!.x - point.x) + (lex.pos!.y - point.y) * (lex.pos!.y - point.y)).squareRoot() - 2252) <= 2)
        // A dead figure (~0 = 0) is not pushed; a removed point no longer pushes.
        lex.pos = start
        let key = w.objectKey(lex.name)
        var rec = vm.objectRecord(key)
        rec[0] = .int(0)
        vm.setObject(key, rec)
        w.step()
        #expect(lex.pos!.x == start.x && lex.pos!.y == start.y)
        rec[0] = .int(100)
        vm.setObject(key, rec)
        cmd(w, p, "REMOVEAVOIDANCEPOINT", .str("AVDBAR3"))
        w.step()
        #expect(lex.pos!.x == start.x && lex.pos!.y == start.y)
    }

    /// test_world.py `MotionTiming`: a frame lasts MY_SPEED x the motion's frame time, adjusted by the difficulty level for other
    /// figures than the player (FUN_1098_0088, FUN_1088_1854; live Medium ATK_M7 704).
    @Test func frameDurationIsMySpeedTimesFrameTimeAdjustedByDifficulty() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let bot = try #require(w.figures["FIRSTBOT"])
        bot.pos = V3(0, 0, 0)
        #expect(bot.speed == 384)
        for (level, adjust) in [(0, 0x80), (1, -64), (2, -128)] {
            vm.globals["_difficulty_level"] = .int(level)
            for (name, frameTime) in [("ACTIVATE", 10), ("ATK_M7", 2), ("ATK_STAND", 4)] {
                bot.setMotion(name, loop: true)
                #expect(w.motionDuration(bot) == 384 * frameTime + adjust)
            }
        }
        vm.globals["_difficulty_level"] = .int(1)
        bot.setMotion("ATK_M7", loop: true)
        for _ in 0..<4 { w.step() }
        #expect(bot.idx == 2)
    }

    /// test_world.py `test_player_repeating_an_attack_slows_it`.
    @Test func playerRepeatingAnAttackSlowsIt() throws {
        let (w, vm, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        vm.globals["_difficulty_level"] = .int(2)
        lex.setMotion("ATK_H1", loop: false)
        let base = lex.speed * (lex.motionInfo?.frameTime ?? 0)
        #expect(w.motionDuration(lex) == base)
        lex.setMotion("ATK_H1", loop: false)
        #expect(w.motionDuration(lex) == base + 1 * 64 * 2 * 16)
        lex.setMotion("ATK_H1", loop: false)
        #expect(w.motionDuration(lex) == base + 2 * 64 * 2 * 16)
        lex.setMotion("STAND", loop: true)
        _ = w.motionDuration(lex)
        lex.setMotion("ATK_H1", loop: false)
        #expect(w.motionDuration(lex) == base)
    }

    /// test_world.py `MotionTiming`: FUN_10a0_1c83 adds a turning motion's root yaw to the heading at each wrap and on a change.
    @Test func turningMotionAddsItsRootYawEachCycle() throws {
        let (w, _, p) = try makeAttachedWorld()
        cmd(w, p, "CREATEFIGURE", .str("NURSEBOT"), .str("FIRSTBOT"))
        let bot = try #require(w.figures["FIRSTBOT"])
        bot.pos = V3(0, 0, 0)
        bot.heading = 150
        bot.setMotion("ATK_M7", loop: true)
        #expect(bot.turning)
        func ticks(_ frames: Int) -> Int { (frames * w.motionDuration(bot) + World.clockPerTick - 1) / World.clockPerTick }
        for _ in 0..<ticks(bot.frames!.count) { w.step() }
        #expect(bot.idx == 0 && bot.heading == 150 + 7 * 45 / 32.0)
        for _ in 0..<ticks(3) { w.step() }
        let yaw = bot.frames![bot.idx].limbs[0].z
        bot.setMotion("ATK_STAND", loop: true)
        #expect(bot.heading == 150 + Double(7 - yaw) * 45 / 32)
        bot.setMotion("STAND", loop: true)
        #expect(bot.heading == 150 + Double(7 - yaw) * 45 / 32)
    }

    /// test_world.py `NurseActivation`: DOSBox-X live, the nurse curves toward the bed during ATK_M7 to (-11380, -10462), heading 213.8.
    @Test func nurseCurvesTowardTheBedLikeTheOriginal() throws {
        let res = try #require(worldResources)
        let s = try GameSession.newGame(resources: res, afterOpeningTicks: 1020)
        let bot = try #require(s.world.figures["FIRSTBOT"])
        #expect(bot.motion == "ATK_STAND")
        #expect(hypot(bot.pos!.x + 11380, bot.pos!.y + 10462) < 100)
        #expect(abs(bot.heading - 213.8) < 2)
    }
}
