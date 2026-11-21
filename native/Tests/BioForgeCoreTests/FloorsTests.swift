// Floors (WorldFloors.swift) against re/interp/test_floors.py: SETFLOOROFPHYS and TELEPORTALLONPHYS on CONTROL's real PHYS data, and the
// real CONMACH garage elevator scripts (RAISE_GARAGE_ELEVATOR entered through the TAKEMEUP trigger, LOWER_GARAGE_ELEVATOR), with the same
// cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

/// Lex's z above his hull bottom: foot offset 2312 + 21 (hullUnits(s)).
private let dz = 2333

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct FloorsTests {
    /// CONTROL with Lex (gravity off, as the elevator scripts leave him) at (44000, -60000, `z`); the default z puts his hull bottom 21 below
    /// the ELV floor (the garage).
    private func control(z: Int = -165174 + dz) throws -> (GameSession, Figure) {
        let sess = try GameSession(resources: try #require(worldResources), level: "CONTROL")
        let w = sess.world
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], proc(sess.vm))
        let lex = try #require(w.player)
        lex.gravity = false
        w.setPos(lex, V3(44000, -60000, Double(z)), raw: true)
        return (sess, lex)
    }

    private func proc(_ vm: ScriptVM) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    private func phys(_ w: World, _ name: String) -> [Int] {
        let p = w.data.phys[w.findPhys(name)!]
        return [Int(p.lo.z), Int(p.hi.z)]
    }

    private func setFloor(_ s: GameSession, _ args: ScriptValue...) { _ = s.world.call(.stmt, "SETFLOOROFPHYS", args, proc(s.vm)) }
    private func teleport(_ s: GameSession, _ args: ScriptValue...) { _ = s.world.call(.stmt, "TELEPORTALLONPHYS", args, proc(s.vm)) }
    private func ints(_ v: V3?) -> [Int] { [v!.x, v!.y, v!.z].map { Int($0) } }

    @Test func aMovedAnchorKeepsTheTriggersItTouchedAtLoad() throws {
        let (s, _) = try control(), w = s.world
        let elv = try #require(w.findPhys("ELV"))
        setFloor(s, .str("ELV"), .int(-633))
        #expect(phys(w, "ELV") == [-162048, -146988])
        #expect(w.areaTriggers(elv).map { w.data.triggers[$0].name } == ["CAM_SHO5", "CAM_SHO5", "CAM_SHO5", "CAM_SHO1", "TAKEMEUP", "MSENTER"])
    }

    // MARK: area-scoped floor queries (FUN_1060_03f2 / 0871, 1060:040d-045c)

    private func stand(_ z: Int) throws -> (GameSession, Figure, (lo: SIMD3<Int>, hi: SIMD3<Int>)) {
        let (s, lex) = try control(z: z), w = s.world
        lex.gravity = true
        _ = w.updateArea(lex, at: lex.pos!)
        return (s, lex, w.hull(lex))
    }

    @Test func theGarageFloorIsElvNotTheControlRoomAboveIt() throws {
        let (s, lex, h) = try stand(-165153 + 2312), w = s.world
        #expect(w.data.phys[lex.area!].name == "ELV")
        #expect(w.physAreas().first { $0.anchor == lex.area }?.members.map { w.data.phys[$0].name } == ["ELV", "DOR", "SH1"])
        let area = w.area(of: lex)
        #expect(w.support(h.lo, h.hi, area: area) == -165153 && w.support(h.lo, h.hi) == -9302)     // scoped, global (QSF pit)
        #expect(w.queryHull(lex).sup == -165153)
        #expect(w.pointFloor(44000, -60000, h.lo.z, h.hi.z, area: area) == -165153)
        for _ in 0..<5 { s.vm.tickOnce(); s.world.step() }
        #expect(Int(lex.pos!.z) == -165153 + 2312 && !lex.falling && w.data.phys[lex.area!].name == "ELV")     // stays on ELV
    }

    @Test func theControlRoomStillGetsItsFloor() throws {
        let (s, lex, h) = try stand(-7160), w = s.world
        #expect(w.data.phys[lex.area!].name == "QSF")
        #expect(w.support(h.lo, h.hi, area: w.area(of: lex)) == -9302 && w.support(h.lo, h.hi) == -9302)
        #expect(w.pointFloor(44000, -60000, h.lo.z, h.hi.z, area: w.area(of: lex)) == -9302)
    }

    @Test func theAnchorSeedsTheResultWithoutAnXYTest() throws {
        let (s, lex, _) = try stand(-165153 + 2312), w = s.world
        let lo = SIMD3(-1000000, -1000000, -165174), hi = SIMD3(-999000, -999000, -161000)
        let area = try #require(w.area(of: lex))
        #expect(w.support(lo, hi, area: area) == -165153)                      // a space seeds lo.z
        #expect(w.support(lo, hi) == World.noFloor)
        #expect(w.pointFloor(0, 0, -165000, -165000, area: area) == -165153 && w.pointFloor(0, 0, -165000, -165000) == World.noFloor)
        // the anchor's state selects the slot: a solid seeds hi.z, a state 2 anchor seeds nothing
        for (state, seed) in [(1, -150093), (2, World.noFloor)] {
            var boxes = w.physBoxes()
            let b = boxes[area.anchor]
            boxes[area.anchor] = PhysBox(name: b.name, state: state, lo: b.lo, hi: b.hi)
            w.boxes = boxes
            #expect(w.support(lo, hi, area: area) == seed)
        }
        _ = s
    }

    @Test func aNullAreaFallsBackToTheGlobalScan() throws {
        let (s, lex, h) = try stand(-165153 + 2312), w = s.world
        lex.area = nil
        #expect(w.area(of: lex) == nil)
        #expect(w.queryHull(lex).sup == -9302)
        #expect(w.pointFloor(44000, -60000, h.lo.z, h.hi.z) == -9302)
        _ = s
    }

    // MARK: SETFLOOROFPHYS

    @Test func aSpaceSetsItsBottomAndKeepsItsHeight() throws {
        let (s, _) = try control(), w = s.world
        #expect(phys(w, "ELV") == [-165153, -150093])
        setFloor(s, .str("ELV"), .int(-642))                                  // -642 << 8
        #expect(phys(w, "ELV") == [-164352, -149292] && w.warnings.isEmpty)
        let p = w.data.phys[w.findPhys("ELV")!]
        #expect([p.lo.x, p.lo.y] == [34553, -63386])                          // x and y untouched
    }

    @Test func aSolidSetsItsTop() throws {
        let (s, _) = try control(), w = s.world
        #expect(w.physState(w.data.phys[w.findPhys("TWIN3")!]) == 1 && phys(w, "TWIN3") == [-7431, -5019])
        setFloor(s, .str("TWIN3"), .int(-10))
        #expect(phys(w, "TWIN3") == [-4972, -2560])
    }

    @Test func zeroUnknownNameAndABadStateOnlyWarn() throws {
        let (s, _) = try control(), w = s.world
        let before = w.data.phys.map { phys(w, $0.name) }
        setFloor(s, .str("ELV"), .int(0))
        setFloor(s, .str("ELV"), .int(65536))                                 // low 16 bits are 0
        setFloor(s, .str("NOSUCH"), .int(-5))
        setFloor(s, .str("WK1"), .int(-5))                                    // state 2
        setFloor(s, .str(""), .int(-5))
        #expect(w.data.phys.map { phys(w, $0.name) } == before)
        #expect(w.warnings.count == 4)                                        // the two zero forms share a message
    }

    @Test func onlyTheLow16BitsCount() throws {
        let (s, _) = try control(), w = s.world
        setFloor(s, .str("ELV"), .int(65536 - 642))
        #expect(phys(w, "ELV") == [-164352, -149292])
        setFloor(s, .str("QSF"), .int(0x10000 + 0x8000))                      // 0x8000 = -32768 << 8
        #expect(phys(w, "QSF")[0] == -32768 * 256)
    }

    @Test func theBoxCacheIsInvalidated() throws {
        let (s, lex) = try control(), w = s.world
        w.boxes = w.physBoxes()                                               // as step() holds it while a script runs
        #expect(w.pointFloor(44000, -60000, -10000, 0) == -9302)              // QSF pit
        setFloor(s, .str("QSF"), .int(-57))
        #expect(phys(w, "QSF") == [-14592, -8676])
        #expect(w.pointFloor(44000, -60000, -10000, 0) == -14592)
        #expect(w.boxes?.first { $0.name == "QSF" }?.lo.z == -14592)
        let h = w.hull(lex, at: V3(44000, -60000, -9000))
        #expect(w.support(h.lo, h.hi) == -14592)
        w.boxes = nil
        setFloor(s, .str("QSF"), .int(-37))
        #expect(w.pointFloor(44000, -60000, -10000, 0) == -9472)              // no cache: read fresh
    }

    // MARK: TELEPORTALLONPHYS

    @Test func aSelfTeleportKeepsXYAndReseatsZOnTheFloor() throws {
        let (s, lex) = try control(z: -100000), w = s.world                   // z is not tested
        lex.vx = 7
        teleport(s, .str("ELV"), .str("ELV"))
        #expect(ints(lex.pos) == [44000, -60000, -165153 + dz] && lex.vx == 0)
        setFloor(s, .str("ELV"), .int(-642))
        teleport(s, .str("ELV"), .str("ELV"))
        #expect(ints(lex.pos) == [44000, -60000, -164352 + dz])
        _ = w
    }

    @Test func theTeleportUsesTheHullFromBeforeTheFloorMoved() throws {
        let (s, lex) = try control()                                          // hull bottom 21 below ELV: 21b2 raised it onto the floor
        setFloor(s, .str("ELV"), .int(-642))                                  // 708e rebuilds no hulls; the live hull would not reach the new floor
        teleport(s, .str("ELV"), .str("ELV"))
        #expect(ints(lex.pos) == [44000, -60000, -164352 + 2312])
        #expect(lex.storedHull == nil)                                        // setPos rebuilds it
    }

    @Test func elvToQsfScalesXAndY() throws {
        let (s, lex) = try control()
        teleport(s, .str("ELV"), .str("QSF"))                                 // sx 255, sy 282
        // z' = floor + (z - hull bottom): the hull bottom is raised onto the floor under it (ELV's, 21 above it) now that support is
        // scoped to the figure's area, so the offset is the foot offset 2312 (the global support took QSF and left the bottom 21 lower)
        #expect(ints(lex.pos) == [34489 + ((9447 * 255) >> 8), -64698 + ((3386 * 282) >> 8), -9302 + 2312])
        #expect(ints(lex.pos) == [43899, -60969, -6990])
        teleport(s, .str("QSF"), .str("ELV"))                                 // sx 256, sy 232
        #expect(ints(lex.pos) == [34553 + ((9410 * 256) >> 8), -63386 + ((3729 * 232) >> 8), -165153 + dz - 21])
    }

    @Test func aHullOutsideAInXOrYIsNotMoved() throws {
        for (x, y) in [(53761 - 300, -60000), (44000, -53341 - 300), (34553 + 300, -60000), (44000, -63386 + 300)] {
            let (s, lex) = try control()
            s.world.setPos(lex, V3(Double(x), Double(y), Double(-165174 + dz)), raw: true)
            teleport(s, .str("ELV"), .str("QSF"))
            #expect(ints(lex.pos) == [x, y, -165174 + dz])
        }
    }

    @Test func unknownNamesOnlyWarn() throws {
        let (s, lex) = try control(), w = s.world
        teleport(s, .str("ELV"), .str("NOSUCH"))
        teleport(s, .str("NOSUCH"), .str("ELV"))
        teleport(s, .str("ELV"))
        #expect(ints(lex.pos) == [44000, -60000, -165174 + dz] && w.warnings.count == 2)     // the two NOSUCH forms share one
    }

    @Test func itemsMoveToo() throws {
        let (s, _) = try control(), w = s.world
        func put(_ name: String, _ x: Double, _ y: Double, _ z: Double) -> Item {
            let it = Item(name: name, type: "GRENADE", owner: nil)
            it.pos = V3(x, y, z); it.matrix = .identity; it.vel = [5, 0, 0]
            w.items[name] = it
            return it
        }
        let plain = put("PLAIN", 44000, -60000, -100000)
        let loaded = put("LOADED", 44000, -60000, -100000)
        w.loadItemPhysics(loaded)
        let held = Item(name: "HELD", type: "GRENADE", owner: "PLAYER")
        w.items["HELD"] = held
        let outside = put("OUTSIDE", 34553, -60000, -100000)                  // the point is on A's edge: not strictly inside
        let missile = Missile(name: "MISSILE", missileType: "GRENADE")
        missile.pos = V3(44000, -60000, 0); missile.extent = [50, 50, 50]
        w.items["MISSILE"] = missile
        teleport(s, .str("ELV"), .str("QSF"))
        #expect(ints(plain.pos) == [43899, -60969, -9302])                    // ASSUMPTION: no EXTENT loaded -> dz 0
        #expect(ints(loaded.pos) == [43899, -60969, -9302 + 102] && loaded.extent[2] == 102)
        #expect(ints(missile.pos) == [43899, -60969, -9302 + 50])
        #expect(plain.vel == [0, 0, 0] && plain.step == [0, 0, 0])
        #expect(held.pos == nil && ints(outside.pos) == [34553, -60000, -100000])
    }

    // MARK: the real ride

    /// Runs `ticks` frames (spawning the real script `block` first, if any) -> per frame (player z, ELV lo.z, QSF lo.z).
    private func ride(_ s: GameSession, _ lex: Figure, _ ticks: Int, _ block: String? = nil) -> [[Int]] {
        if let block { s.vm.spawn(block, ctx: ScriptContext(curFig: "PLAYER", curItem: nil, owner: "level")) }
        var out: [[Int]] = []
        for _ in 0..<ticks {
            s.vm.tickOnce(); s.world.step()
            out.append([Int(lex.pos!.z), phys(s.world, "ELV")[0], phys(s.world, "QSF")[0]])
        }
        return out
    }

    /// Lex stands on ELV (hull bottom 21 below the floor, gravity off) and enters the TAKEMEUP trigger, which runs the real
    /// CONMACH RAISE_GARAGE_ELEVATOR: z follows ELV (00:04 .. 00:16, ticks 5 .. 20), the teleport at 00:20 takes Lex to QSF (tick 21), which
    /// then rises to the control room floor, and GRAVITY ON at 02:20 (tick 81) leaves him standing on it. LOWER_GARAGE_ELEVATOR (the end of
    /// CR_HANGERMONITOR) then takes him back to the garage.
    @Test func theRealGarageElevatorUpAndDown() throws {
        let (s, lex) = try control(), w = s.world
        let up = ride(s, lex, 100)
        #expect(s.vm.globals["_elev_frame"] == .int(8))
        #expect(up[0..<5].map { $0[0] } == Array(repeating: -165174 + dz, count: 5))      // the trigger ran; the first step is at 00:04
        #expect([5, 9, 13, 17].map { up[$0][1] } == [-164352, -163584, -163072, -162048])  // ELV -642, -639, -637, -633
        for n in 5..<21 { #expect(up[n][0] == up[n][1] + 2312, "tick \(n)") }             // player z = ELV lo.z + F at every ELV step
        for n in 21..<81 { #expect(up[n][0] == up[n][2] + 2312, "tick \(n)") }            // then QSF lo.z + F (rising -57 .. -37)
        #expect(up[41][0] == -14592 + 2312 && up[41][2] == -14592 && up[80][2] == -9984)
        #expect(up[81][0] == -9472 + 2312 && up[81][2] == -9472 && lex.gravity && ints(lex.pos).prefix(2) == [43899, -60969])
        #expect(Set(up[81...].map { $0[0] }) == [-7160])                                   // grounded in the control room, not falling through
        #expect(w.queryHull(lex).lo.z == -9472 && w.warnings.isEmpty)
        let down = ride(s, lex, 76, "LOWER_GARAGE_ELEVATOR")
        #expect(down[3][0] == -7160)
        for n in 4..<60 { #expect(down[n][0] == down[n][2] + 2312, "tick \(n)") }            // QSF -39 .. -57, then reset to -37 at 01:10
        #expect(down[39][2] == -14592 && down[40][2] == -9472)
        for n in 60..<76 { #expect(down[n][0] == down[n][1] + 2312, "tick \(n)") }           // QSF -> ELV at 02:00: ELV -633 .. -642
        #expect(down[60] == [-159736, -162048, -9472] && ints(lex.pos).prefix(2) == [43963, -60007] && down[75][1] == -164352)
        // the last step (ELV -646, GRAVITY ON at 02:16): support is scoped to the garage area, so he stays on ELV's floor (F above it)
        let end = ride(s, lex, 24)
        #expect(Set(end.map { $0[1] }) == [-165376] && Set(end.map { $0[2] }) == [-9472])
        #expect(Set(end.map { $0[0] }) == [-165376 + 2312] && lex.gravity && !lex.falling && w.data.phys[lex.area!].name == "ELV")
    }

    /// Lex placed on ELV with gravity on (z = ELV floor + F) stays grounded and enters TAKEMEUP by himself: the same ride, z following ELV (the
    /// script's GRAVITY OFF at the start leaves him riding), up to the control room and back down to the garage.
    @Test func theRideStartsByStandingOnElvWithGravityOn() throws {
        let (s, lex) = try control(z: -165153 + 2312)
        lex.gravity = true
        let up = ride(s, lex, 100)
        #expect(s.vm.globals["_elev_frame"] == .int(8))
        #expect(up[0..<5].map { $0[0] } == Array(repeating: -165153 + 2312, count: 5))
        for n in 5..<21 { #expect(up[n][0] == up[n][1] + 2312, "tick \(n)") }             // F above ELV at every step
        #expect(Set(up[81...].map { $0[0] }) == [-7160] && lex.gravity)
        let down = ride(s, lex, 100, "LOWER_GARAGE_ELEVATOR")
        #expect(Set(down[80...].map { $0[0] }) == [-165376 + 2312] && down[99][1] == -165376 && !lex.falling)
    }
}
