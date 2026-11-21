// Floor items and the Enter key (WorldItems.swift) against the Python prototype: fixtures.json "items" (re/tools/native_fixtures.py
// items_fixture) holds selection probes, the motion chosen for each hand state, a CHAOS pick-up / shoot / put-down run (event timing,
// owners, drop placement), indexed frames of the floor, held and dropped blaster, and the save writer's patched ITEM records. The same
// run is replayed here; every canonical line and frame must match. The rest checks the rules directly (re/interp/test_items.py).
import Foundation
import Testing
@testable import BioForgeCore

nonisolated(unsafe) let itemFixture = fixtures["items"] as! JSON

/// A level at its INITGAME state with Lex placed as the player (items_world in the fixture script).
func itemWorld(_ level: String = "CHAOS", lex: (Double, Double) = (495, -28827), heading: Double = 0) throws -> (GameSession, Figure) {
    let s = try GameSession(resources: try #require(worldResources), level: level)
    let w = s.world
    let fig = Figure(name: "LEX", type: "LEX", assets: try #require(w.asset("LEX")), speed: w.mySpeed("LEX", "LEX"))
    w.figures["LEX"] = fig
    w.playerName = "LEX"
    fig.viewCams = nil
    fig.pos = V3(lex.0, lex.1, -5000)
    fig.heading = heading
    w.settle(fig)
    return (s, fig)
}

extension GameSession {
    func run(_ n: Int) { for _ in 0..<n { tick() } }
    /// Frames until `pred` holds (nil after `limit`).
    func until(_ limit: Int = 200, _ pred: () -> Bool) -> Int? {
        for n in 1...limit { tick(); if pred() { return n } }
        return nil
    }
    func press(_ scan: Int = 0x1c) { world.keyDown(scan); world.keyUp(scan) }
}

func f6(_ x: Double) -> String { abs(x) >= 5e-7 ? String(format: "%.6f", x) : "0.000000" }

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct FloorItemLocalsTests {
    @Test func newLevelItemsHoldTheirRecordsLocals() throws {
        let (control, _) = try itemWorld("CONTROL")
        #expect(control.vm.objects["MEDICAID"]?.first == .int(5))
        #expect(control.vm.objects["DANEBAT"]?.first == .int(100))
        #expect(control.vm.objects["ORIGBIKEBAT"]?.first == .int(150))
    }
}

/// A level change writes the old level's objects to its IFF and reads them back on a return (FUN_1148_14a3 -> 1404, 1148:1386); the
/// player and what he holds travel (FUN_1088_2da1 -> FUN_1060_0df8). test_items.py LevelItemsKept.
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct LevelItemsKeptTests {
    @Test func aFloorItemIsBackWhereItWasWithItsLocals() throws {
        let (s, _) = try itemWorld("CONTROL")
        let w = s.world
        let bat = try #require(w.items["ORIGBIKEBAT"])
        bat.pos = try #require(bat.pos) + V3(100, 0, 0)
        var locals = try #require(s.vm.objects["ORIGBIKEBAT"])
        locals[0] = .int(20)
        s.vm.setObject("ORIGBIKEBAT", locals)
        try w.loadObjects("TUNROOM")
        #expect(w.items["ORIGBIKEBAT"] == nil)
        try w.loadObjects("CONTROL")
        #expect(w.items["ORIGBIKEBAT"] === bat)
        #expect(s.vm.objects["ORIGBIKEBAT"]?.first == .int(20))
        #expect(w.items.values.filter { $0.name == "ORIGBIKEBAT" }.count == 1)
    }

    @Test func whatAnotherFigureHoldsStaysAndThePlayersItemsTravel() throws {
        let (s, _) = try itemWorld("CONTROL")
        let w = s.world
        let talky = try #require(w.items["WTALKY"]), bat = try #require(w.items["DANEBAT"])
        talky.owner = "GRDHANG"; talky.slot = "RTHAND"
        bat.owner = "LEX"; bat.slot = "INVENTORY"
        try w.loadObjects("TUNROOM")
        #expect(w.items.keys == ["DANEBAT"])
        try w.loadObjects("CONTROL")
        #expect(w.items["WTALKY"]?.owner == "GRDHANG")
        #expect(w.items.values.filter { $0.name == "DANEBAT" }.count == 1)
    }
}

/// A level keeps its figures when the player leaves it (FUN_1148_14a3 -> 1404; FUN_1090_135a destroys a killed figure's object).
/// test_items.py LevelFiguresKept.
/// LOADLEVEL <level> <volume> <destination> (FUN_10d0_4d46): test_items.py ElevatorVolumeCarry.
@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ElevatorVolumeCarryTests {
    private func proc(_ s: GameSession) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "LEX"))
    }

    @Test func theVolumesFiguresAndItemsAndThePlayerArriveAtTheirOffsets() throws {
        let (s, lex) = try itemWorld("CHAOS")
        let w = s.world
        let vol = try #require(w.data.objs.first { $0.name == "ELH" })
        let lo = pointwiseMin(v3(vol.pos), v3(vol.pos2!)), hi = pointwiseMax(v3(vol.pos), v3(vol.pos2!))
        let ref = V3(Double(Int((lo.x + hi.x) / 2)), Double(Int((lo.y + hi.y) / 2)), Double(Int(lo.z)))
        let fido = try #require(w.figures["FIDO"])
        fido.gravity = false
        fido.pos = ref + V3(100, -200, 700)
        let flute = try #require(w.items["FLUTE"])
        flute.pos = ref + V3(-300, 150, 40); flute.owner = nil
        lex.gravity = false
        lex.pos = ref + V3(500, 0, 600)
        let lexRel = lex.pos! - ref
        _ = w.call(.stmt, "LOADLEVEL", [.str("CONTROL"), .str("ELH"), .str("ELC"), .str("_sfx_5")], proc(s))
        let c = try #require(w.arrivalPoint("ELC"))
        let dest = V3(c.xy.x, c.xy.y, c.z)
        #expect(w.level == "CONTROL")
        #expect(w.items["FLUTE"]?.pos == dest + V3(-300, 150, 40) && w.items["FLUTE"]?.vel == [0, 0, 0])
        for (fig, rel) in [(try #require(w.figures["FIDO"]), V3(100, -200, 700)), (lex, lexRel)] {
            let off = fig.pos! - (dest + rel)             // the PHYS test may have nudged it, in steps of 204 toward the destination
            #expect(off.z == 0 && off.x.truncatingRemainder(dividingBy: 204) == 0 && off.y.truncatingRemainder(dividingBy: 204) == 0)
            #expect(max(abs(off.x), abs(off.y)) <= 21 * 204)
        }
        #expect(w.figures["GUARD1"] == nil && w.items["CAYARM"] == nil)             // outside the volume: they stay in CHAOS
    }

    @Test func anUnknownVolumeEndsTheCallerAndLoadsNothing() throws {
        let (s, _) = try itemWorld("CHAOS")
        let p = proc(s)
        _ = s.world.call(.stmt, "LOADLEVEL", [.str("CONTROL"), .str("NOVOLUME"), .str("ELC")], p)
        #expect(s.world.level == "CHAOS" && p.done)
    }
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct LevelFiguresKeptTests {
    @Test func aKilledFigureStaysGone() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "CONTROL")
        let w = s.world
        w.killFigure(try #require(w.figures["DANE"]))
        try w.loadObjects("TUNROOM")
        try w.loadObjects("CONTROL")
        #expect(w.figures["DANE"] == nil && w.figure("DANE") == nil)
        #expect(w.figure("GRDHALL") != nil)
    }

    @Test func aSurvivorComesBackAsItWasAndItsAIRestarts() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "CONTROL")
        let w = s.world
        let fig = try #require(w.figures["GRDHALL"])
        fig.pos = fig.pos! + V3(100, 0, 0)
        fig.heading = 90
        fig.hold = 2
        var locals = try #require(s.vm.objects["GRDHALL"])
        locals[0] = .int(7)
        s.vm.setObject("GRDHALL", locals)
        try w.loadObjects("TUNROOM")
        #expect(w.figures["GRDHALL"] == nil)
        try w.loadObjects("CONTROL")
        let back = try #require(w.figures["GRDHALL"])
        #expect(back === fig && back.heading == 90 && back.hold == 2 && s.vm.objects["GRDHALL"]?.first == .int(7))
        #expect(back.aiProc == nil)
        back.hold = 0; back.hidden = false                       // (a camera shows it)
        w.startEnabledAI(back)
        #expect(back.aiProc != nil)
    }

    @Test func theFirstVisitBuildsEveryRecord() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "CONTROL")
        let w = s.world
        #expect(Set(w.figures.keys) == Set(w.data.figDefOrder))
        try w.loadObjects("TUNROOM")
        #expect(w.levelFigures["CONTROL"] != nil)
        #expect(Set(w.figures.keys) == Set(w.data.figDefOrder))
    }

    @Test func aSaveWritesTheKeptFiguresIntoTheOtherLevelsFileAndALoadKeepsTheKilledOneGone() throws {
        let res = try #require(worldResources)
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession(resources: res, level: "CONTROL")
        let w = s.world
        w.killFigure(try #require(w.figures["DANE"]))
        let fig = try #require(w.figures["GRDHALL"])
        fig.pos = fig.pos! + V3(100, 0, 0)
        try w.loadObjects("TUNROOM")
        w.savesDir = dir
        let url = try #require(w.saveNative(slot: 1))
        let out = dir.appendingPathComponent("out")
        try Im1.unpack(try fileBytes(url), to: out)
        let recs = (try #require(try SaveState.load(directory: out).levels["CONTROL"])).objects().filter { $0.tag == "FIGR" }
        #expect(!recs.contains { $0.raw.cString(33, 42) == "DANE" })
        let rec = try #require(recs.first { $0.raw.cString(33, 42) == "GRDHALL" })
        #expect(try (0..<2).map { try rec.raw.s32(9 + 4 * $0) } == [fig.pos!.x, fig.pos!.y].map { Int($0.rounded(.toNearestOrEven)) })
        let s2 = try GameSession.fromNativeState(resources: res, directory: out)
        try s2.world.loadObjects("CONTROL")
        #expect(s2.world.figures["DANE"] == nil && s2.world.figure("DANE") == nil)
        #expect(s2.world.figures["GRDHALL"] != nil)
    }

    /// The level reader restores the whole record (FUN_1148_0d46), for a load as for a return: a save made in another level, after leaving
    /// this one with a turned, moving, fighting figure, hands it back as it was on the first visit after the load.
    @Test func aLoadedGamesFirstVisitGivesTheFigureItsSavedHeadingMotionVelocityEnemyAndAvoidList() throws {
        let res = try #require(worldResources)
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession(resources: res, level: "CONTROL")
        let w = s.world
        let fig = try #require(w.figures["GRDHALL"])
        let wp = try #require(w.data.waypoints.keys.sorted().first)
        fig.heading = 90; fig.combat = true; fig.enemy = "DANE"; fig.avoid = [(wp, 300)]
        _ = fig.setMotion("ATK_STAND", loop: true)
        (fig.vx, fig.vy, fig.vz) = (12, -7, 0)
        try w.loadObjects("TUNROOM")
        w.savesDir = dir
        let url = try #require(w.saveNative(slot: 1))
        let out = dir.appendingPathComponent("out")
        try Im1.unpack(try fileBytes(url), to: out)
        let s2 = try GameSession.fromNativeState(resources: res, directory: out)
        try s2.world.loadObjects("CONTROL")
        let back = try #require(s2.world.figures["GRDHALL"])
        #expect(back.heading == 90 && back.motion == "ATK_STAND" && back.combat && (back.vx, back.vy, back.vz) == (12, -7, 0) && back.enemy == "DANE")
        #expect(back.avoid.count == 1 && back.avoid[0].0 == wp && back.avoid[0].1 == 300)
        #expect(s2.world.figures["DANE"]?.enemy == nil)
    }
}

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ItemTests {
    @Test func mapsEnterAndKeypadEnter() {
        for mods in [0, Keys.shift, Keys.ctrl, Keys.alt] { for combat in [false, true] { #expect(Keys.action(scan: 0x1c, mods: mods, combat: combat) == .pickup) } }
    }

    @Test func oldMeshLayoutLoads() throws {
        let g = try requireGame()
        let m = try EORMesh(data: try g.read("ITEMS/BLASTER.IFF"))
        #expect(m.verts.count == 25 && m.polys.count == 29 && m.textures.count == 9 && m.frames.count == 2)
        #expect(m.polys.filter { $0.tex != nil }.count == 22)
        #expect(m.textures[0].name == "BLASTSR" && m.textures[0].width == 112 && m.textures[0].height == 23)
        #expect(m.polys[0].kind == 8 && m.polys[0].color == 0x90 && m.polys[0].vi == [15, 18, 17])
        #expect(m.polys.allSatisfy { $0.vi.allSatisfy { $0 < m.verts.count } })
        let pipe = try EORMesh(data: try g.read("ITEMS/PIPE.IFF"))
        #expect(pipe.verts.count == 10 && pipe.polys.count == 16)
    }

    @Test func itemRecordsBecomeFloorItems() throws {
        let (s, _) = try itemWorld()
        let w = s.world
        #expect(w.items.keys.filter { w.items[$0]!.owner == nil }.sorted() == ["BLASTER", "CAYARM", "CAYLOG", "DANELOG", "FLUTE", "FORK", "LEXLOG", "MEAT", "PHOTO"])
        #expect(w.items["BLASTER"]!.pos == V3(495, -29827, -7280))
        #expect(["BLASTER", "FORK", "MEAT1", "CAYARM", "NOSUCHITEM"].map { w.itemHand(Item(name: "X", type: $0, owner: nil)) } == ["RTHAND", "LTHAND", "LTHAND", "RTHAND", "LTHAND"])
    }

    @Test func numbersAndUnits() {
        #expect(ItemRules.parseNumbers(["180I", "90J", "0K", "8LENGTH", "0X", "20Y", "-3Z"]) == ["I": 180, "J": 90, "K": 0, "LENGTH": 8, "X": 0, "Y": 20, "Z": -3])
        #expect(ItemRules.parseNumbers(["90I", "0", "0"]) == ["I": 90, "J": 0, "K": 0])
        #expect([0, 1, 7, 8, 20, -3].map(ItemRules.attachUnits) == [0, 20, 143, 163, 409, -61])
    }

    @Test func carryUsesDeclaredHandAndGroundPlacementDrops() throws {
        let (s, lex) = try itemWorld()
        let w = s.world
        w.items = OrderedMap<Item>()
        let fork = Item(name: "FORK", type: "FORK", owner: "LEX")
        fork.slot = "INVENTORY"
        w.items[fork.name] = fork
        #expect(w.placeItem(lex, fork, "CARRY"))
        #expect(fork.owner == "LEX" && fork.slot == "LTHAND" && fork.pos == nil)

        let spare = Item(name: "SPARE", type: "FORK", owner: "LEX")
        spare.slot = "INVENTORY"
        w.items[spare.name] = spare
        #expect(!w.placeItem(lex, spare, "CARRY"))
        #expect(spare.owner == "LEX" && spare.slot == "INVENTORY")

        #expect(w.placeItem(lex, fork, "GROUND"))
        #expect(fork.owner == nil && fork.slot == nil && fork.pos != nil)
    }

    @Test func spaceUsesLeftHandCombinationsAndStandaloneItems() throws {
        let (s, lex) = try itemWorld()
        let w = s.world
        w.items = OrderedMap<Item>()
        let fork = Item(name: "FORK", type: "FORK", owner: "LEX")
        fork.slot = "INVENTORY"
        w.items[fork.name] = fork
        #expect(w.placeItem(lex, fork, "CARRY"))
        lex.pos = V3(6400, -24300, lex.pos!.z)                   // CELPAN
        _ = w.updateArea(lex, at: lex.pos!)
        #expect(w.playerUse(lex) == "CELPAN_FORK_USE")

        w.items = OrderedMap<Item>()
        let medicaid = Item(name: "MEDICAID", type: "MEDICAID", owner: "LEX")
        medicaid.slot = "INVENTORY"
        w.items[medicaid.name] = medicaid
        #expect(w.placeItem(lex, medicaid, "CARRY"))
        lex.pos = V3(0, 0, lex.pos!.z)
        #expect(w.playerUse(lex) == "MEDICAID_USE")
    }

    @Test func eventsOfLexMotions() throws {
        let (s, _) = try itemWorld()
        let ev = s.world.figureEvents("LEX")
        for (name, want) in [("PICK_UP_LTHAND", (16, 0xef)), ("PICK_UP_RTHAND", (15, 0xef)), ("PUT_DOWN_LTHAND", (12, 0xf4)), ("PUT_DOWN_RTHAND", (16, 0xf3))] {
            #expect(ev[name]?.count == 1 && ev[name]?[0].after == want.0 && ev[name]?[0].code == want.1, "\(name)")
        }
    }

    @Test func rulesMatchThePrototype() throws {
        var lines: [String] = []
        var frames: [String: FrameDigest] = [:]
        func frame(_ s: GameSession) -> FrameDigest {
            var fb = Framebuffer()
            s.world.render(into: &fb)
            return FrameDigest(fb, tick: s.vm.tick, camera: s.world.currentCamera, segments: false)
        }
        // selection
        var (s, lex) = try itemWorld()
        var w = s.world
        func pick() -> String? { w.pickupCandidate(lex)?.name }
        for d in [500.0, 1000, 2000, 2303, 2304, 2500] {
            lex.pos = V3(495, -29827 + d, lex.pos!.z); lex.heading = 0
            lines.append(row("S", "dist", Int(d), pick()))
        }
        lex.pos = V3(495, -28827, lex.pos!.z)
        for h in [0, 30, 59, 61, -59, -61, 90, 180] {
            lex.heading = Double(h)
            lines.append(row("S", "heading", h, pick()))
        }
        lex.pos = V3(-1000, -6900, lex.pos!.z); lex.heading = 90
        lines.append(row("S", "two", pick()))
        // the motion for every hand state (LANDPAD has no LEX_PUT_DOWN_* script gate)
        (s, lex) = try itemWorld("LANDPAD", lex: (0, 0))
        w = s.world
        let states: [(String?, String?, String?)] = [(nil, nil, nil), (nil, nil, "BLASTER"), (nil, nil, "FORK"), (nil, "BLASTER", nil), (nil, "BLASTER", "FORK"),
                                                     (nil, "BLASTER", "CAYARM"), ("FORK", nil, nil), ("FORK", nil, "BLASTER"), ("FORK", nil, "MEAT1"),
                                                     ("FORK", "BLASTER", nil), ("FORK", "BLASTER", "BLASTER")]
        for (left, right, near) in states {
            w.items = OrderedMap<Item>()
            lex.setMotion("STAND", loop: true)
            w.itemState.pickTargets = [:]
            for (hand, t) in [("LTHAND", left), ("RTHAND", right)] {
                if let t { let it = Item(name: "HELD_" + hand, type: t, owner: "LEX"); it.slot = hand; w.items["HELD_" + hand] = it }
            }
            if let near { let it = Item(name: "NEAR", type: near, owner: nil); it.pos = V3(0, -1000, -7280); it.matrix = .identity; w.items["NEAR"] = it }
            w.playerPickup(lex)
            lines.append(row("M", left, right, near, lex.motion == "STAND" ? nil : lex.motion, w.itemState.pickTargets.sorted { $0.key < $1.key }.map { [$0.key, $0.value] }))
        }
        // CHAOS: pick up the blaster, shoot, walk to the fork, pick it up, put it down, put the blaster down
        (s, lex) = try itemWorld()
        w = s.world
        w.scriptAuto = false
        w.setCamera("CE24", "items")
        frames["floor"] = frame(s)
        let b = try #require(w.items["BLASTER"]), fork = try #require(w.items["FORK"])
        s.press()
        var n = s.until { b.owner != nil }
        lines.append(row("T", "grab", n, lex.motion, lex.idx, b.owner, b.slot, w.isCarrying(lex, "RTHAND", "BLASTER"), w.isCarrying(lex, "LTHAND", nil),
                         w.keyLog.filter { $0.action == "item" }.map(\.action), w.subtitleLog.count))
        frames["held"] = frame(s)
        s.run(40)
        lines.append(row("T", "end", lex.motion, lex.loop))
        s.press(0x4c); s.run(3)
        lines.append(row("T", "shoot", lex.motion, lex.loop, lex.idx))
        s.run(8)
        frames["shoot"] = frame(s)
        s.run(40)
        lex.setMotion("STAND", loop: true)
        lex.pos = V3(-2466, -6717, lex.pos!.z); lex.heading = 0
        s.press()
        n = s.until { fork.owner != nil }
        lines.append(row("T", "grab-left", n, lex.motion, lex.idx, fork.owner, fork.slot, w.isCarrying(lex, "LTHAND", "FORK")))
        s.run(40)
        lex.pos = V3(5000, -20000, lex.pos!.z); lex.heading = 0
        s.press()
        n = s.until { fork.owner == nil }
        lines.append(row("T", "drop-left", n, lex.motion, fork.owner, fork.slot, b.owner, b.slot, [fork.pos!.x, fork.pos!.y, fork.pos!.z].map(f6),
                         fork.matrix!.r.flatMap { [$0.x, $0.y, $0.z] }.map(f6)))
        s.run(40)
        lex.pos = V3(5000, -20000, lex.pos!.z); lex.heading = 0
        s.press()
        s.run(5)
        lines.append(row("T", "again", lex.motion, w.itemState.pickTargets.sorted { $0.key < $1.key }.map { [$0.key, $0.value] }))
        frames["dropped"] = frame(s)
        // the save writer
        let rec = try #require(w.data.objs.first { $0.tag == "ITEM" && $0.name == "BLASTER" }).raw
        let ground: [[Double]] = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]
        let patches: [SaveWrite.ItemState] = [.init(owner: "LEX", slot: "RTHAND"), .init(owner: "LEX", slot: "LTHAND"), .init(owner: "LEX", slot: "INVENTORY"),
                                              .init(owner: "LEX", slot: "RTHAND"), .init(pos: V3(1, -2, 3), matrix: ground), .init()]
        for st in patches { lines.append(row("R", st.owner, st.slot, sha(SaveWrite.patchItem(rec, st, ["LEX": 260])))) }
        lines.append(row("R", "unknown", sha(SaveWrite.patchItem(rec, .init(owner: "LEX", slot: "RTHAND"), [:]))))

        expectDigest(lines, itemFixture["lines"], "items")
        let fx = itemFixture["frames"] as! JSON
        for (name, f) in frames.sorted(by: { $0.key < $1.key }) { _ = f.check(fx[name] as! JSON, "items frame \(name)") }
        #expect(frames.count == fx.count)
    }

    @Test func savedItemsComeBackCarriedAndDropped() throws {
        let res = try #require(worldResources), g = try requireGame()
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession.fromNativeState(resources: res, directory: try #require(g.gamedat))
        let w = s.world
        let lex = try #require(w.player)
        lex.pos = V3(495, -28827, lex.pos!.z); lex.heading = 0
        lex.hold = 0                                         // the shipped save's Lex has AI off (+0x229 = 1), which keeps the keys out
        s.press(); s.run(40)
        #expect(w.items["BLASTER"]?.owner == "LEX" && w.items["BLASTER"]?.slot == "RTHAND")
        w.savesDir = dir
        let url = try #require(w.saveNative(slot: 1))
        let out = dir.appendingPathComponent("out")
        try Im1.unpack(try fileBytes(url), to: out)
        let s2 = try GameSession.fromNativeState(resources: res, directory: out)
        let b = try #require(s2.world.items["BLASTER"])
        #expect(b.owner == "LEX" && b.slot == "RTHAND" && b.pos == nil)
        #expect(s2.world.items["FORK"]?.owner == nil && s2.world.items["FORK"]?.pos != nil)
        s2.press(); s2.run(40)
        #expect(b.owner == nil)
        s2.world.savesDir = dir
        let url2 = try #require(s2.world.saveNative(slot: 2))
        let out2 = dir.appendingPathComponent("out2")
        try Im1.unpack(try fileBytes(url2), to: out2)
        let again = try #require(try GameSession.fromNativeState(resources: res, directory: out2).world.items["BLASTER"])
        #expect(again.owner == nil && again.slot == nil && abs(again.pos!.x - b.pos!.x) < 0.5 && abs(again.pos!.y - b.pos!.y) < 0.5 && abs(again.pos!.z - b.pos!.z) < 0.5)
    }
}
