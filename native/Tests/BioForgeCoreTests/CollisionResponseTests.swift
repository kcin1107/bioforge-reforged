// FUN_10a0_0ead (World.collisionResponse / verticalResponse in WorldPlay.swift) against re/interp/test_world.py `CollisionResponse`:
// step-up, the vz branches, landing, FUN_1130_1a2d's unstick, the mantle and the BONK sound, on a synthetic ROOM space (floor z -3000)
// with solid boxes.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct CollisionResponseTests {
    static let floor = -3000

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

    private func hullBottom(_ r: Rig) -> Int { r.w.queryHull(r.lex).lo.z }

    @Test func aPitIsTheSupportOnlyWhenTheWholeHullFitsInIt() throws {
        let r = try rig()
        world(r, box("QPIT", 0, (1000, -2000, Self.floor - 2000), (3000, 2000, Self.floor + 5000)))
        _ = r.w.updateArea(r.lex, at: r.lex.pos!)
        #expect(r.w.queryHull(r.lex).sup == Self.floor - 2000)           // (2000, 0): inside
        r.lex.pos = V3(900, 0, r.stand)                                  // straddles the edge: FUN_1058_1a1b's score is positive there
        _ = r.w.updateArea(r.lex, at: r.lex.pos!)
        #expect(r.w.queryHull(r.lex).sup == Self.floor)
    }

    @Test func stepUpLiftsALowSupportBeforeTheSlide() throws {
        let r = try rig()
        world(r, box("STEP", 1, (1000, -3000, Self.floor), (3000, -1000, Self.floor + 300)))
        let z0 = r.lex.pos!.z
        let blocked = V3(2000, -700, z0)                      // overlaps STEP by 68 units
        r.lex.pos = blocked
        let q = r.w.queryHull(r.lex)
        #expect(q.sup == Self.floor + 300)
        let k = (q.hi.z - q.lo.z) / 4, root = r.w.rootZ(r.lex)
        #expect(q.lo.z < q.sup && q.sup < q.lo.z + k - root)      // k = hull dz / 4, R = the frame's root z
        r.w.collisionResponse(r.lex, start: V3(2000, 0, z0), blocked: blocked, good: V3(2000, 0, z0))
        #expect(r.lex.pos!.x == blocked.x && r.lex.pos!.y == blocked.y)         // no slide: the blocked x, y stay
        #expect(r.lex.pos!.z == z0 + Double(q.sup - q.lo.z))
        #expect(hullBottom(r) == q.sup)
    }

    @Test func stepTallerThanKMinusRSlidesInstead() throws {
        let r = try rig()
        world(r, box("STEP", 1, (1000, -3000, Self.floor), (3000, -1000, Self.floor + 1500)))
        let z0 = r.lex.pos!.z
        let blocked = V3(2000, -700, z0)
        r.lex.pos = blocked
        let q = r.w.queryHull(r.lex)
        #expect(q.sup >= q.lo.z + (q.hi.z - q.lo.z) / 4 - r.w.rootZ(r.lex))
        r.w.collisionResponse(r.lex, start: V3(2000, 0, z0), blocked: blocked, good: V3(2000, 0, z0))
        #expect(r.lex.pos! == V3(2000, 0, z0))                // kept the blocked x, start y
    }

    @Test func zeroVectorLastGoodSkipsTheSlide() throws {
        let r = try rig()
        world(r, box("WALL", 1, (-9000, 1000, Self.floor), (9000, 1200, 2000)))
        let z0 = r.lex.pos!.z
        let start = V3(0, 0, z0), blocked = V3(150, 1100, z0)
        for (good, expect) in [(V3(0, 0, 1), V3(150, 0, z0)), (V3(0, 0, 0), V3(150, 1100, z0))] {
            r.lex.pos = start
            r.w.collisionResponse(r.lex, start: start, blocked: blocked, good: good)
            #expect(r.lex.pos! == expect)
        }
    }

    @Test func zVelocityWithoutAFallReturnsToTheLastGoodPosition() throws {
        let r = try rig()
        world(r)
        let good = V3(500, 0, r.stand)
        r.lex.vz = -300; r.lex.vx = 5; r.lex.falling = false
        r.w.collisionResponse(r.lex, start: good, blocked: V3(900, 0, r.stand - 40), good: good)
        #expect(r.lex.pos! == good)
        #expect((r.lex.vx, r.lex.vy, r.lex.vz, r.lex.motion) == (0, 0, 0, "STAND"))
    }

    @Test func landingMotionThresholds() {
        #expect([-0x300, -0x280, -0x27f, -0x140, -0x13f, 0].map(World.landingMotion)
                == ["LAND_HARD", "LAND_HARD", "LAND_MEDIUM", "LAND_MEDIUM", "LAND_SOFT", "LAND_SOFT"])
    }

    /// A falling figure whose hull bottom is `drop` units below the floor -> (start, good, bottom0).
    private func fall(_ r: Rig, _ fig: Figure, drop: Double = 100) -> (V3, V3, Int) {
        let start = V3(2000, 0, r.stand + 2000)
        fig.pos = V3(2000, 0, r.stand - drop)
        fig.vz = -500; fig.falling = true; fig.hold = 1
        return (start, start, r.w.queryHull(fig).lo.z)
    }

    @Test func landingPutsTheHullOnTheSupportAndPlaysLandSoft() throws {
        let r = try rig()
        world(r)
        let (start, good, bottom0) = fall(r, r.lex)
        r.w.verticalResponse(r.lex, start: start, good: good, bottom0: bottom0)
        #expect((r.lex.falling, r.lex.vz, r.lex.hold, r.lex.motion) == (false, 0, 0, "LAND_SOFT"))
        #expect(r.lex.pos!.x == 2000 && r.lex.pos!.y == 0)
        #expect(r.lex.pos!.z == r.stand)                      // unstick's SetPos stands it on the floor
    }

    @Test func supportOver0x1000AboveTheEntryBottomRestoresThePreviousPosition() throws {
        let r = try rig()
        world(r)
        var (start, good, bottom0) = fall(r, r.lex, drop: Double(World.landRevert + 600))
        start.x = 2500; start.y = 300
        good = start
        r.w.verticalResponse(r.lex, start: start, good: good, bottom0: bottom0)
        #expect(r.lex.pos!.x == 2500 && r.lex.pos!.y == 300)      // x, y from the previous position, then snapped to the floor
        #expect(r.lex.pos!.z == r.stand)
        #expect(r.lex.motion == "LAND_SOFT")
    }

    @Test func playerKeepsFallingStraightDownWhenThePreviousXYIsFree() throws {
        let r = try rig()
        world(r)
        var (start, good, bottom0) = fall(r, r.lex, drop: -500)       // still above the floor, hull free
        start.x = 1500; start.y = 100
        good = start
        r.lex.vx = 7
        r.w.verticalResponse(r.lex, start: start, good: good, bottom0: bottom0)
        #expect(r.lex.falling)
        #expect((r.lex.vx, r.lex.vy, r.lex.vz) == (0, 0, -500))
        #expect(r.lex.pos!.x == 1500 && r.lex.pos!.y == 100)
        #expect(r.lex.pos!.z == r.stand + 500)
    }

    @Test func otherFiguresLandWithoutThePlayerRule() throws {
        let r = try rig()
        world(r)
        _ = r.w.call(.stmt, "CREATEFIGURE", [.str("NURSEBOT"), .str("NURSE")], r.proc)
        let nurse = try #require(r.w.figures["NURSE"])
        nurse.setMotion("STAND", loop: true)
        var (start, good, bottom0) = fall(r, nurse, drop: -500)
        start.x = 1500; start.y = 100
        good = start
        r.w.verticalResponse(nurse, start: start, good: good, bottom0: bottom0)
        #expect(!nurse.falling)                               // (NURSEBOT has no LAND_SOFT motion to play)
        #expect(nurse.vz == 0)
        #expect(nurse.assets.motion("LAND_SOFT") == nil)
    }

    @Test func unstickNudgesAreBoundedAndFollowTheBytePattern() throws {
        let r = try rig()
        // a solid filling the room keeps the global PHYS score positive: the loop runs to its bound
        world(r, box("FILL", 1, (-9000, -9000, Self.floor), (9000, 9000, 6000)))
        r.w.setPosTrace = []
        let p0 = V3(2000, 0, r.stand)
        r.lex.pos = p0
        r.w.unstick(r.lex)
        let calls = try #require(r.w.setPosTrace)
        #expect(calls.count == 1 + 40 + 1)                    // the first SetPos, 40 nudges, the final SetPos(p0)
        for (i, q) in calls[1..<41].enumerated() {
            #expect(q == p0 + (i & 3 == 0 || i & 3 == 2 ? V3(Double(i << 8), 0, 0) : V3(0, -Double(i << 8), 0)))
        }
        #expect(calls.last! == p0)
        #expect(r.lex.pos!.x == p0.x && r.lex.pos!.y == p0.y)
        world(r)                                              // clear and already on the floor: no nudge at all
        r.w.setPosTrace = []
        r.lex.pos = V3(2000, 0, r.stand)
        r.w.unstick(r.lex)
        #expect(r.w.setPosTrace?.count == 1)
    }

    private func mantleWorld(_ r: Rig, top: Int = 1500, flags: UInt8 = 2, material: String = "METAL") -> (V3, V3) {
        world(r, box("LEDGE", 1, (1000, -3000, Self.floor), (3000, -1000, Self.floor + top), flags: flags, material: material))
        r.lex.setMotion("WALK", loop: true, engine: true)
        r.lex.heading = 7
        let z0 = r.lex.pos!.z
        return (V3(2000, 0, z0), V3(2000, -700, z0))
    }

    private func bump(_ r: Rig, _ start: V3, _ blocked: V3) {
        r.lex.pos = blocked
        r.w.collisionResponse(r.lex, start: start, blocked: blocked, good: start)
    }

    @Test func mantleSnapsTheHeadingAndPicksByHeight() throws {
        for (top, name) in [(1500, "MANTLE_3"), (3000, "MANTLE_6")] {
            let r = try rig()
            let (start, blocked) = mantleWorld(r, top: top)
            bump(r, start, blocked)
            #expect(r.lex.motion == name && r.lex.heading == 0 && r.lex.engineRequest, "\(top)")
        }
    }

    @Test func mantleHeightBoundaries() throws {
        let r = try rig()
        _ = mantleWorld(r)
        var got: [String] = []
        for h in [0x7ff, 0x800, 0xfff, 0x1000] {
            r.lex.setMotion("WALK", loop: true)
            r.w.mantle(r.lex, h)
            got.append(r.lex.motion ?? "")
        }
        #expect(got == ["MANTLE_3", "MANTLE_6", "MANTLE_6", "MANTLE_9"])
    }

    @Test func mantleNeedsFlagWalkRequestAxisAndReach() throws {
        func walks(_ r: Rig) -> Bool { r.lex.motion == "WALK" }
        var r = try rig()
        var (start, blocked) = mantleWorld(r, flags: 0)
        bump(r, start, blocked)
        #expect(walks(r))                                     // collider flag 0x02 clear
        r = try rig()
        (start, blocked) = mantleWorld(r)
        r.lex.setMotion("WALK", loop: true)                   // a script's WALK is not the engine's "walk"
        bump(r, start, blocked)
        #expect(walks(r))
        r = try rig()
        (start, blocked) = mantleWorld(r)
        r.lex.heading = 45
        bump(r, start, blocked)
        #expect(walks(r))                                     // not within 15 degrees of an axis
        r = try rig()
        (start, blocked) = mantleWorld(r, top: 4500)          // support more than 0x1000 below the top
        bump(r, start, blocked)
        #expect(walks(r))
        r = try rig()
        (start, blocked) = mantleWorld(r)
        start.x = 1100; blocked.x = 1100                      // hull not inside the box shrunk by 0x266
        bump(r, start, blocked)
        #expect(walks(r))
    }

    @Test func mantleAxisSnapsForEachQuadrant() throws {
        let r = try rig()
        _ = mantleWorld(r)
        let plo = SIMD3<Int>(1000, -3000, Self.floor), phi = SIMD3<Int>(3000, 3000, Self.floor + 1500)
        r.lex.pos = V3(2000, 0, r.stand)
        for (heading, expect) in [(10.0, 0.0), (-10, 0), (80, 90), (100, 90), (-80, -90), (170, 180), (-170, 180)] {
            r.lex.heading = heading
            #expect(r.w.mantleFits(r.lex, plo, phi), "\(heading)")
            func wrap(_ v: Double) -> Double { (v.truncatingRemainder(dividingBy: 360) + 360).truncatingRemainder(dividingBy: 360) }
            #expect(wrap(r.lex.heading) == wrap(expect), "\(heading)")      // -180 and 180 are the same facing
        }
        r.lex.heading = 45
        #expect(!r.w.mantleFits(r.lex, plo, phi))
    }

    @Test func bonkSoundNameIsLookedUpAndSilentWhenMissing() throws {
        let r = try rig()
        var names: [String] = []
        var (start, blocked) = mantleWorld(r, flags: 0)           // no mantle: the motion stays WALK for the name
        r.w.soundNameProbe = { names.append($0); return nil }
        bump(r, start, blocked)
        #expect(names == ["_LEX_BONK_WALK_METAL", "_LEX_BONK_WALK", "_LEX_BONK", "_LEX"])     // 1118:0044 cuts the name at each `_`
        #expect(r.w.soundLog.isEmpty)
        (start, blocked) = mantleWorld(r, flags: 0)
        r.w.soundNameProbe = { _ in 3 }
        bump(r, start, blocked)
        #expect(r.w.soundLog.count == 1 && r.w.soundLog[0].index == 3)
    }
}
