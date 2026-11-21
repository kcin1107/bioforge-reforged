// Persistent velocity parity with re/interp/test_world.py `PersistentVelocity`: velocityStep, the 3D mover and its step scaling, the
// per-frame move, the generic bounce (candidate order, ELASTICITY loss, fallback aliasing) and SETVELOCITY / STOPVELOCITY / VELOCITYX /
// LEAP, on synthetic PHYS boxes (a ROOM space with floor z -3000 and solid walls); Lex's hull is 736 x 736 x 3480 at the origin.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct VelocityTests {
    private struct Scene {
        let w: World, vm: ScriptVM, p: ScriptProcess, lex: Figure
        let room = Phys(name: "ROOM", lo: V3(-5000, -5000, -3000), hi: V3(5000, 5000, 12000), state: 0)
        let wallX = Phys(name: "WALL_X", lo: V3(1000, -5000, -3000), hi: V3(1200, 5000, 12000), state: 1)
        let wallY = Phys(name: "WALL_Y", lo: V3(-5000, 1000, -3000), hi: V3(5000, 1200, 12000), state: 1)

        func world(_ boxes: Phys...) { w.data.phys = [room] + boxes; w.boxes = nil }
        /// One frame of the move: the frame start is recorded the way the tick does.
        func frame() { lex.prevPos = lex.pos; w.frameMove(lex) }
        func cmd(_ name: String, _ args: ScriptValue...) { _ = w.call(.stmt, name, args, p) }
        func read(_ name: String, _ ref: String = "CURFIG") -> ScriptValue { w.call(.function, name, [.str(ref)], p) }
    }

    private func make() throws -> Scene {
        let res = try #require(worldResources)
        let world = try World(resources: res, level: "CHAOS")
        let vm = ScriptVM(engine: world, defs: try ScriptDefs(game: requireGame()))
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = world.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(world.player)
        lex.pos = V3(0, 0, 0)
        lex.gravity = false
        lex.prevPos = lex.pos
        vm.globals["_wall_x_space"] = .int(1); vm.globals["_wall_y_space"] = .int(1)
        return Scene(w: world, vm: vm, p: p, lex: lex)
    }

    @Test func stepScalingByFrameTime() {
        let v = [100, -100, 5]
        #expect(velocityStep(v) == [100, -100, 5])                 // 30 fps ([83a0] = 512): step == v
        #expect(velocityStep(v, dt8: 256) == [50, -50, 2])         // 60 fps: scale 128; 5 * 128 >> 8 = 2
        #expect(velocityStep(v, dt8: 768) == [150, -150, 7])       // 20 fps: scale 384
        #expect(velocityStep(v, dt8: 600) == [119, -120, 5])       // 0x3c00 // 600 = 25 whole fps, scale 307; 0c42 floors
        #expect(velocityStep(v, dt8: 0) == [0, 0, 0])              // 0 -> 1: 0x3c00 fps, scale 0
        #expect(velocityStep([1], dt8: 0x4000) == [0x1e0000 >> 8]) // slower than 1 fps: fps clamps to 1, scale 0x1e0000
    }

    @Test func blockedStepScalingTruncatesTowardZero() throws {
        #expect(scaleStep([7, -7, 0, 10], 1, 3) == [2, -2, 0, 3])
        #expect(scaleStep([3000, -3001, 0], 2, 4) == [1500, -1500, 0])
        let s = try make()
        s.world(s.wallX)
        s.lex.step = [3000, 0, 0]
        #expect(!s.w.mover(s.lex, V3(3000, 0, 0)))                 // n = 4 steps of 750: the first touches the wall
        #expect(s.lex.pos?.x == 750)
        #expect(s.lex.step == [750, 0, 0])
    }

    @Test func moverLengthAndStepsIncludeZ() throws {
        #expect(moveSteps(0, 0, 8000, 736) == 10)
        let s = try make()
        s.world(Phys(name: "CEIL", lo: V3(-5000, -5000, 2000), hi: V3(5000, 5000, 2100), state: 1))
        s.vm.globals["_ceil_space"] = .int(1)
        // the final hull (z 5667..9147) clears the thin ceiling box, only the 3D steps (800 each) see it: step 2 (z 1600) is blocked
        s.lex.step = [0, 0, 8000]
        #expect(!s.w.mover(s.lex, V3(0, 0, 8000)))
        #expect(s.lex.pos?.z == 1600)
        #expect(s.lex.step == [0, 0, 1600])
    }

    @Test func horizontalVelocityCarriesWithoutFriction() throws {
        let s = try make()
        s.world()
        s.lex.vx = 300; s.lex.vy = -200
        for i in 1...5 {
            s.frame()
            #expect(s.lex.pos == V3(Double(300 * i), Double(-200 * i), 0))
            #expect((s.lex.vx, s.lex.vy, s.lex.vz) == (300, -200, 0))
        }
        #expect(s.lex.step == [300, -200, 0])
        #expect(!s.lex.gravity)                                    // a figure without the gravity flag moves too
    }

    @Test func nonBouncyCollisionZeroesTheVelocity() throws {
        let s = try make()
        s.world(s.wallX)
        s.lex.vx = 300
        for _ in 0..<4 { s.frame() }
        #expect((s.lex.vx, s.lex.vy, s.lex.vz) == (0, 0, 0))
        #expect(s.lex.pos!.x < 1000 - 368)                         // stopped short of the wall
        let before = s.lex.pos
        s.frame()
        #expect(s.lex.pos == before)
    }

    private func rebound(_ s: Scene, _ e: Int, _ v: (Int, Int), _ wall: Phys) {
        s.world(wall)
        s.lex.bouncy = true
        s.lex.elasticity = e
        s.lex.vx = v.0; s.lex.vy = v.1
        for _ in 0..<3 {
            s.frame()
            if s.lex.vx != v.0 || s.lex.vy != v.1 { break }
        }
    }

    @Test func bouncyReboundNegatesTheCandidateAxesAndLosesEnergy() throws {
        // E: ((vx, vy), step) after the rebound, v -= floor(v * E / 256) on both (E 0 = lossless)
        let expected: [Int: ((Int, Int), [Int])] = [0: ((-300, 200), [300, 200, 0]), 50: ((-241, 161), [242, 161, 0]), 200: ((-65, 44), [66, 44, 0])]
        for (e, want) in expected {
            let s = try make()
            rebound(s, e, (300, 200), s.wallX)
            // frames: x 300, 600, then 900 hits the wall (hull edge 1268 > 1000); step = (300, 200, 0); candidate X (600, y) is free
            #expect(s.lex.pos == V3(600, 600, 0), "E \(e)")
            #expect((s.lex.vx, s.lex.vy, s.lex.vz) == (want.0.0, want.0.1, 0), "E \(e)")     // only x negated
            #expect(s.lex.step == want.1, "E \(e)")
        }
    }

    @Test func bounceTriesYAfterX() throws {
        let s = try make()
        rebound(s, 0, (200, 300), s.wallY)          // the wall is in y: X (prev x, blocked y) is blocked, Y is free
        #expect(s.lex.pos == V3(600, 600, 0))
        #expect((s.lex.vx, s.lex.vy, s.lex.vz) == (200, -300, 0))
    }

    @Test func bounceFallsBackToWhereTheYZAttemptLeftTheFigure() throws {
        // every candidate fails inside a solid box: the fallback mover call does not return to the last good position
        let s = try make()
        s.world(Phys(name: "BLOCK", lo: V3(-3000, -3000, -3000), hi: V3(3000, 3000, 12000), state: 1))
        s.vm.globals["_block_space"] = .int(1)
        let lex = s.lex
        lex.bouncy = true
        lex.elasticity = 0
        lex.pos = V3(500, 500, 0); lex.prevPos = V3(200, 300, 0)
        lex.vx = 300; lex.vy = 200; lex.vz = 0
        s.w.bounceCollision(lex, start: lex.prevPos!)
        #expect(lex.pos == V3(500, 300, 0))                        // YZ = (P.x, prev.y, prev.z)
        #expect((lex.vx, lex.vy, lex.vz) == (-300, -200, 0))
    }

    @Test func bounceOffTheFloorNegatesZAndKeepsRising() throws {
        let s = try make()
        s.world(Phys(name: "FLOOR", lo: V3(-5000, -5000, -3000), hi: V3(5000, 5000, -2400), state: 1))
        s.vm.globals["_floor_space"] = .int(1)
        let lex = s.lex
        lex.bouncy = true; lex.elasticity = 50; lex.falling = true; lex.vz = -300
        s.frame()                                    // z -300: the hull bottom (-2633) is under the floor top (-2400)
        // step z = -300; X and Y candidates are P itself (blocked); Z goes back up to z 0, strictly above the support
        #expect(lex.pos == V3(0, 0, 0))
        #expect(lex.vz == 300 - 58)                  // -(-300), then v -= floor(300 * 50 / 256)
        #expect(lex.step == [0, 0, -300 + 59])       // the step -300 loses floor(-300 * 50 / 256) = -59
        #expect(!lex.falling)
        s.frame()                                    // not falling any more: gravity is off and vz keeps its value
        s.frame()
        #expect(lex.pos?.z == Double(2 * 242) && lex.vz == 242)
    }

    @Test func setStopAndReadVelocityRoundTrip() throws {
        let s = try make()
        let lex = s.lex
        s.cmd("SETVELOCITY", .str("CURFIG"), .int(100), .int(-200), .int(300))
        #expect((lex.vx, lex.vy, lex.vz) == (100, -200, 300))
        #expect([s.read("VELOCITYX"), s.read("VELOCITYY"), s.read("VELOCITYZ")] == [.int(100), .int(-200), .int(300)])
        s.cmd("SETVELOCITY", .str("CURFIG"), s.read("VELOCITYX"), s.read("VELOCITYY"), .int(0))        // the TUNZEROG idiom
        #expect((lex.vx, lex.vy, lex.vz) == (100, -200, 0))
        s.cmd("SETVELOCITY", .str("PLAYER"), .int(70000), .int(-70000), .int(Int(Int32.max)))          // raw s32; the function returns the low 16 bits
        #expect((lex.vx, lex.vy, lex.vz) == (70000, -70000, Int(Int32.max)))
        #expect([s.read("VELOCITYX"), s.read("VELOCITYY"), s.read("VELOCITYZ")] == [.int(4464), .int(-4464), .int(-1)])
        lex.step = [1, 2, 3]
        s.cmd("STOPVELOCITY", .str("CURFIG"))
        #expect((lex.vx, lex.vy, lex.vz) == (0, 0, 0) && lex.step == [0, 0, 0])
        #expect(s.read("VELOCITYX", "NO_SUCH_FIGURE") == .int(0))
    }

    @Test func leapAddsAlongRowOneScaledBySpeed() throws {
        let s = try make()
        let lex = s.lex
        // row 1 = backward = (sin h, cos h); k = (3 << 11) / 100 = 61
        for (heading, expect) in [(0.0, (0, 61, 0)), (90.0, (61, 0, 0))] {
            lex.heading = heading; lex.vx = 0; lex.vy = 0; lex.vz = 0
            s.cmd("LEAP", .str("CURFIG"), .int(0), .int(3))
            #expect((lex.vx, lex.vy, lex.vz) == expect)
        }
        lex.heading = 0; lex.vx = 0; lex.vy = 0; lex.vz = 0
        s.cmd("LEAP", .str("CURFIG"), .int(0), .int(-4))           // negative speed leaps forward (-y at heading 0): k = -81
        #expect((lex.vx, lex.vy, lex.vz) == (0, -81, 0))
        s.cmd("STOPVELOCITY", .str("CURFIG"))
        s.cmd("LEAP", .str("CURFIG"), .int(45), .int(-3))          // the pitch tilts row 1 up: a forward leap with negative speed goes down
        #expect(lex.vz < 0)
        #expect(abs(lex.vz - lex.vy) <= 1)
        s.cmd("STOPVELOCITY", .str("CURFIG"))
        s.w.data.points["GRAVPT"] = V3(1000, 0, 0)
        s.cmd("LEAP", .str("CURFIG"), .str("GRAVPT"), .int(0), .int(2))        // toward the target: k = 40
        #expect((lex.vx, lex.vy, lex.vz) == (40, 0, 0))
        s.w.data.points["GRAVPT"] = V3(0, 0, 1000)
        s.cmd("LEAP", .str("CURFIG"), .str("GRAVPT"), .int(0), .int(2))
        #expect((lex.vx, lex.vy, lex.vz) == (40, 0, 40))
    }

    @Test func knockbackRowIsBackward() throws {
        let s = try make()
        for (heading, row1) in [(0.0, [0, 256, 0]), (90.0, [256, 0, 0]), (180.0, [0, -256, 0])] {
            s.lex.heading = heading
            #expect(s.w.orientation(s.lex)[1] == row1)
        }
    }

    @Test func terminalFallSpeed() throws {
        let s = try make()
        s.lex.gravity = true
        s.w.data.phys = [Phys(name: "ROOM", lo: V3(-5000, -5000, -30000), hi: V3(5000, 5000, 40000), state: 0)]
        s.w.boxes = nil
        s.lex.pos = V3(0, 0, 20000)
        var seen: [Int] = []
        for _ in 0..<18 {
            s.lex.prevPos = s.lex.pos
            s.w.settle(s.lex)
            seen.append(s.lex.vz)
        }
        #expect(Array(seen[0..<3]) == [-102, -204, -306])
        #expect(Array(seen[11..<13]) == [-1224, -1326])            // applied while vz > -1280, so it stops at -1326
        #expect(Set(seen[12...]) == [-1326])
        #expect(World.fallVMin == -0x500)
    }
}
