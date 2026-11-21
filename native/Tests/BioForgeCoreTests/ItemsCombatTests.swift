// Items and combat rules, twin of re/interp/test_items_combat.py with the same cases and the same numbers:
// R1 the item list (duplicate names, INDIVIDUALIZE, SETCURRENTITEM, ISCARRYING), R2 item position / hull / AMINTRIGGER and the MY_HAND attach,
// R4 the motion gates, death and AI ON, R5 TURN.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ItemsCombatTests {
    static let lexPos = V3(495, -28827, -5000)             // settles to z -5093 on the CHAOS floor
    static let hand = [-322, -29118, -6092]                // CAYARM in Lex's RTHAND at STAND frame 0, heading 0 (rounded engine position)

    /// test_items_combat.Base.setUp: CHAOS at its INITGAME state, Lex (PLAYER) standing at `lexPos` with 100 hit points, no items.
    private struct Rig {
        let s: GameSession, lex: Figure, p: ScriptProcess
        var w: World { s.world }
        var vm: ScriptVM { s.vm }
    }

    private func proc(_ s: GameSession, _ item: String? = nil, handle: Int = 0) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: handle, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "LEX", curItem: item))
    }

    private func make() throws -> Rig {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        let w = s.world
        let p = proc(s)
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        w.items = OrderedMap<Item>()
        itemState(w).pickTargets.removeAll()
        lex.pos = Self.lexPos
        lex.heading = 0
        w.settle(lex)
        lex.setMotion("STAND", loop: true)
        lex.hold = 0
        lex.finished = false
        s.vm.setObject(w.objectKey(lex.name), [.int(100)] + Array(repeating: .int(0), count: 9))
        return Rig(s: s, lex: lex, p: p)
    }

    private func itemState(_ w: World) -> ItemState { w.itemState }

    @discardableResult private func item(_ r: Rig, _ name: String, _ type: String, _ pos: V3? = nil, owner: String? = nil, slot: String? = nil) -> Item {
        let it = Item(name: name, type: type, owner: owner)
        it.slot = slot
        if let pos { it.pos = pos; it.matrix = .identity }
        return r.w.addItem(it)
    }

    private func call(_ r: Rig, _ kind: CallKind, _ name: String, _ args: [ScriptValue], _ p: ScriptProcess? = nil) -> ScriptValue {
        r.w.call(kind, name, args, p ?? r.p)
    }

    private func local0(_ r: Rig, _ key: String) -> Int {
        if case .int(let v) = r.vm.objectRecord(key)[0] { return v }
        return -1
    }

    private func setLocal0(_ r: Rig, _ key: String, _ v: Int) {
        var rec = r.vm.objectRecord(key)
        rec[0] = .int(v)
        r.vm.setObject(key, rec)
    }

    private func trigger(_ r: Rig, _ lo: SIMD3<Int>, _ hi: SIMD3<Int>) {
        r.w.data.triggers.append(Trigger(name: "TESTBOX", lo: lo, hi: hi, once: false, camera: ""))
    }

    private func ints(_ v: V3) -> [Int] { [v.x, v.y, v.z].map { Int($0.rounded(.toNearestOrEven)) } }

    // MARK: R1 the item list

    /// 10d0:5510-5640: FUN_1138_099b, then x, y, z << 8 or the named object's centre.
    @Test func placeItemCoordsAndWayptTakeTheItemOffItsHolder() throws {
        let r = try make()
        _ = r.w.call(.stmt, "CREATEITEM", [.str("FORK")], r.p)
        let fork = try #require(r.w.items["FORK"])
        r.w.placeItem(r.lex, fork, "COORDS", where: [.int(2), .int(-3), .int(4)])
        #expect(fork.owner == nil && fork.slot == nil)
        #expect(fork.pos == V3(512, -768, 1024))
        let name = try #require(r.w.data.objs.first { $0.tag == "WAYP" }?.name)
        let spot = try #require(r.w.arrivalPoint(name.uppercased()))
        r.w.placeItem(r.lex, fork, "WAYPT", where: [.str(name)])
        #expect(fork.pos?.x == spot.xy.x && fork.pos?.y == spot.xy.y)
    }

    /// FUN_1088_2a87 reads it at +0x1ea: a DROGGMIR named DROGG3 has 8, though a DROGG3 block says 100.
    @Test func armourIsReadByTheTypeName() throws {
        let s = try GameSession(resources: try #require(worldResources), level: "PLATFORM")
        let drogg = try #require(s.world.figures["DROGG3"])
        #expect(drogg.type == "DROGGMIR")
        #expect(s.world.prop(drogg, "IMPACT_ARMOR", 0) == 8)
    }

    @Test func createItemKeepsTheTypeAsNameAndDuplicatesCoexist() throws {
        let r = try make()
        _ = call(r, .stmt, "CREATEITEM", [.str("ABAT_500")])
        let first = r.p.curItem
        setLocal0(r, first!, 150)
        _ = call(r, .stmt, "CREATEITEM", [.str("ABAT_500")])
        setLocal0(r, r.p.curItem!, 500)
        #expect(first == "ABAT_500" && r.p.curItem == "ABAT_500#2")
        #expect(r.w.items.values.map { [$0.key, $0.name, $0.type] } == [["ABAT_500", "ABAT_500", "ABAT_500"], ["ABAT_500#2", "ABAT_500", "ABAT_500"]])
        #expect(local0(r, "ABAT_500") == 150 && local0(r, "ABAT_500#2") == 500)            // each keeps its own locals
    }

    @Test func individualizeRenamesInPlaceAndEveryProcessFollows() throws {
        let r = try make()
        _ = call(r, .stmt, "CREATEITEM", [.str("ABAT_500")])
        setLocal0(r, "ABAT_500", 150)
        _ = call(r, .stmt, "CREATEITEM", [.str("ABAT_500")])                              // the second is current
        let other = proc(r.s, "ABAT_500", handle: 9999)                                  // another process points at the first
        r.vm.procs.add(other)
        r.p.curItem = "ABAT_500"
        _ = call(r, .stmt, "INDIVIDUALIZE", [.str("CURITEM"), .str("ALIENBAT")])
        r.vm.procs.remove(9999)
        #expect(Array(r.w.items.keys) == ["ALIENBAT", "ABAT_500#2"])                      // list position kept
        #expect(r.p.curItem == "ALIENBAT" && other.curItem == "ALIENBAT")
        #expect(r.w.items["ALIENBAT"]!.name == "ALIENBAT" && local0(r, "ALIENBAT") == 150 && !r.vm.objectKeys.contains("ABAT_500"))
        _ = call(r, .stmt, "CREATEITEM", [.str("ABAT_500")])                              // the freed name is a fresh item with zeroed locals
        #expect(r.p.curItem == "ABAT_500" && local0(r, "ABAT_500") == 0)
    }

    @Test func setCurrentItemNearestByTypeOrInstanceFirstOnTiesAndUnchangedOnAMiss() throws {
        let r = try make()
        let far = item(r, "FORK", "FORK", V3(495, -27827, -5000))                         // 1000 away
        let near = item(r, "FORK", "FORK", V3(495, -29327, -5000))                        // 500 away
        let tie = item(r, "FORK", "FORK", V3(1495, -28827, -5000))                        // 1000 away
        let named = item(r, "SPOON", "FORK", V3(495, -28727, -5000))                      // 100 away; instance SPOON
        #expect([far.key, near.key, tie.key] == ["FORK", "FORK#2", "FORK#3"])
        #expect(call(r, .function, "SETCURRENTITEM", [.str("FORK")]) == .int(1))
        #expect(r.p.curItem == named.key)                                                // the type matches SPOON too; it is nearest
        #expect(call(r, .function, "SETCURRENTITEM", [.str("SPOON")]) == .int(1))
        r.w.items[named.key] = nil                                                       // Item.type is a let: SPOON becomes a SPORK (same slot, last in the list)
        item(r, "SPOON", "SPORK", V3(495, -28727, -5000))
        #expect(call(r, .function, "SETCURRENTITEM", [.str("FORK")]) == .int(1))
        #expect(r.p.curItem == near.key)                                                 // 500 beats the 1000 pair
        near.pos = V3(495, -27827, -5000)                                                // now three at 1000
        _ = call(r, .function, "SETCURRENTITEM", [.str("FORK")])
        #expect(r.p.curItem == far.key)                                                  // the first wins the tie
        r.p.curItem = tie.key
        #expect(call(r, .function, "SETCURRENTITEM", [.str("NOSUCH")]) == .int(0))
        #expect(r.p.curItem == tie.key)                                                  // unchanged
    }

    @Test func setCurrentItemWithAHandNeedsTheItemInThatHand() throws {
        let r = try make()
        let held = item(r, "FORK", "FORK", owner: "LEX", slot: "LTHAND")
        #expect(call(r, .function, "SETCURRENTITEM", [.str("RTHAND")]) == .int(0))
        #expect(r.p.curItem == nil)
        #expect(call(r, .function, "SETCURRENTITEM", [.str("LTHAND")]) == .int(1))
        #expect(r.p.curItem == held.key)
    }

    @Test func isCarryingInventoryAnywhereAndHands() throws {
        let r = try make()
        item(r, "DANELOG", "LOGBOOK", owner: "LEX", slot: "LTHAND")
        item(r, "BLASTER", "BLASTER", owner: "LEX", slot: "INVENTORY")
        r.p.curItem = "DANELOG"
        func isc(_ a: String, _ b: String) -> ScriptValue { call(r, .function, "ISCARRYING", [.str(a), .str(b)]) }
        #expect([isc("INVENTORY", "BLASTER"), isc("INVENTORY", "DANELOG"), isc("INVENTORY", "LOGBOOK")] == [.int(1), .int(0), .int(0)])
        #expect([isc("ANYWHERE", "BLASTER"), isc("ANYWHERE", "DANELOG"), isc("ANYWHERE", "LOGBOOK"), isc("ANYWHERE", "NOSUCH")] == [.int(1), .int(1), .int(1), .int(0)])
        #expect([isc("LTHAND", "LOGBOOK"), isc("LTHAND", "DANELOG"), isc("RTHAND", "LOGBOOK")] == [.int(1), .int(0), .int(0)])      // a hand compares the TYPE
        #expect(r.p.curItem == "DANELOG")                                                // CURITEM restored after the search
    }

    @Test func isCarryingAnywhereLooksAtTheNearestItemOnly() throws {
        let r = try make()
        item(r, "FORK", "FORK", owner: "LEX", slot: "INVENTORY")                          // at the holder's origin: distance 0
        item(r, "FORK", "FORK", V3(495, -28727, -5000))                                   // on the floor, 100 away
        #expect(call(r, .function, "ISCARRYING", [.str("ANYWHERE"), .str("FORK")]) == .int(1))
        r.w.items["FORK"]!.slot = "LTHAND"                                                // now the hand pose (about 820 away) loses to the floor item
        #expect(call(r, .function, "ISCARRYING", [.str("ANYWHERE"), .str("FORK")]) == .int(0))
    }

    @Test func theObjectArgumentByNameIsTheFirstItemOfThatType() throws {
        let r = try make()
        item(r, "SPOON", "FORK", V3(0, 0, 0))
        item(r, "FORK", "FORK", V3(100, 0, 0))
        #expect(r.w.itemByType("FORK")?.name == "SPOON")
        #expect(r.w.itemByType("SPOON") == nil)                                           // the instance name does not count here
        #expect(call(r, .function, "COORDX", [.str("FORK")]) == .int(0))
    }

    // MARK: R2 item position

    @Test func floorItemHullIsPosPlusMinusExtentAndTouchingIsInclusive() throws {
        let r = try make()
        trigger(r, SIMD3(0, 0, 0), SIMD3(1000, 1000, 1000))
        let arm = item(r, "CAYARM", "CAYARM", V3(1204, 500, 500))                          // EXTENT 10 cm = 204 units: lo x = 1000, touching hi x
        r.p.curItem = arm.key
        func at(_ a: String = "CURITEM") -> ScriptValue { call(r, .function, "AMINTRIGGER", [.str(a), .str("TESTBOX")]) }
        #expect(at() == .int(1))
        arm.pos = V3(1205, 500, 500)
        #expect(at() == .int(0))
        arm.pos = V3(-204, 500, 500)                                                      // hi x = 0 = lo x of the trigger
        #expect(at() == .int(1))
        #expect(at("CAYARM") == .int(1))                                                  // by type name
    }

    @Test func anItemWithoutExtentIsAPoint() throws {
        let r = try make()
        trigger(r, SIMD3(0, 0, 0), SIMD3(1000, 1000, 1000))
        let bat = item(r, "ABAT_500", "ABAT_500", V3(1000, 1000, 1000))
        r.p.curItem = bat.key
        #expect(call(r, .function, "AMINTRIGGER", [.str("CURITEM"), .str("TESTBOX")]) == .int(1))
        bat.pos = V3(1000, 1000, 1001)
        #expect(call(r, .function, "AMINTRIGGER", [.str("CURITEM"), .str("TESTBOX")]) == .int(0))
    }

    @Test func aHeldItemIsWhereTheHandIs() throws {
        let r = try make()
        let arm = item(r, "CAYARM", "CAYARM", owner: "LEX", slot: "RTHAND")
        let pos = try #require(r.w.itemEnginePos(arm))
        #expect(ints(pos) == Self.hand)
        r.p.curItem = arm.key
        let h = Self.hand
        trigger(r, SIMD3(h[0] + 204, -40000, -9000), SIMD3(h[0] + 2000, -20000, -3000))   // lo x = hand x + 204: touching the hull's hi x
        #expect(call(r, .function, "AMINTRIGGER", [.str("CURITEM"), .str("TESTBOX")]) == .int(1))
        r.w.data.triggers[r.w.data.triggers.count - 1] = Trigger(name: "TESTBOX", lo: SIMD3(h[0] + 205, -40000, -9000), hi: SIMD3(h[0] + 2000, -20000, -3000), once: false, camera: "")
        #expect(call(r, .function, "AMINTRIGGER", [.str("CURITEM"), .str("TESTBOX")]) == .int(0))
        #expect(call(r, .function, "COORDX", [.str("CURITEM")]) == .int(h[0] >> 8))
    }

    @Test func anInventoryItemIsWhereTheHolderIs() throws {
        let r = try make()
        let arm = item(r, "CAYARM", "CAYARM", owner: "LEX", slot: "INVENTORY")
        #expect(ints(try #require(r.w.itemEnginePos(arm))) == [495, -28827, -5093])
        r.p.curItem = arm.key
        trigger(r, SIMD3(495 + 204, -30000, -6000), SIMD3(3000, -27000, -4000))
        #expect(call(r, .function, "AMINTRIGGER", [.str("CURITEM"), .str("TESTBOX")]) == .int(1))
        r.w.data.triggers[r.w.data.triggers.count - 1] = Trigger(name: "TESTBOX", lo: SIMD3(495 + 205, -30000, -6000), hi: SIMD3(3000, -27000, -4000), once: false, camera: "")
        #expect(call(r, .function, "AMINTRIGGER", [.str("CURITEM"), .str("TESTBOX")]) == .int(0))
    }

    @Test func aHolderWithoutTheLimbAttachesInItsMyHand() throws {
        let r = try make()
        let w = r.w
        let bot = try #require(w.figure("USE_BOT"))                                       // NURSEBOT: MY_HAND = UP_ARM, no RTHAND limb
        let arm = item(r, "CAYARM", "CAYARM", V3(0, 0, 0)), arm2 = item(r, "CAYARM", "CAYARM", V3(0, 0, 0))
        #expect(w.myHand(bot) == "UP_ARM")
        #expect(w.attachItem(bot, arm))
        #expect(arm.owner == "USE_BOT" && arm.slot == "UP_ARM")
        #expect(!w.attachItem(bot, arm2))                                                 // the hand is occupied
        #expect(w.heldItem(bot, "RTHAND") == nil)
        #expect(w.heldItem(bot, "UP_ARM") === arm)
        #expect(w.heldAny(bot) === arm)                                                   // FUN_1138_036e counts MY_HAND
        #expect(w.itemWorldPose(arm) != nil)                                              // handPose finds the limb now
        #expect(w.attachItem(r.lex, arm2))                                                // Lex has the limb: HANDEDNESS RTHAND
        #expect(arm2.slot == "RTHAND")
        let arm3 = item(r, "CAYARM", "CAYARM", V3(0, 0, 0))
        let bot2 = try #require(w.figure("FIRSTBOT"))
        _ = w.placeItem(bot2, arm3, "CARRY")
        #expect(arm3.slot == "UP_ARM")
    }

    // MARK: R4, R5 combat

    private func makeCombat() throws -> (Rig, Figure) {
        let r = try make()
        let bot = try #require(r.w.figure("FIRSTBOT"))
        bot.viewCams = nil
        r.vm.globals["_difficulty_level"] = .int(0)
        bot.pos = V3(495, -30827, -5000)
        bot.heading = 0
        r.lex.invulnerable = false
        r.lex.hold = 0; bot.hold = 0
        r.lex.finished = false
        return (r, bot)
    }

    private func finish(_ r: Rig, _ f: Figure) {
        let motion = f.motion
        for _ in 0..<2000 {
            if f.finished || f.motion != motion { return }          // 1088:4155 takes a finished motion straight to the idle
            r.w.step()
        }
        Issue.record("motion did not finish")
    }

    @Test func turnNIsNDegreesTowardTheLeft() throws {
        let (r, _) = try makeCombat()
        r.lex.heading = -90
        _ = call(r, .stmt, "TURN", [.int(-5)])
        #expect(r.lex.heading == -85)
        _ = call(r, .stmt, "TURN", [.int(10)])
        #expect(r.lex.heading == -95)
    }

    @Test func aScriptedMotionOfTheSameNameIsRefusedAndNotRestarted() throws {
        let (r, _) = try makeCombat()
        let w = r.w, lex = r.lex
        let p = proc(r.s), q = proc(r.s)
        w.cmdMotion(lex, "TAUNT1", ["CONTINUE"], p)
        let motId = lex.motId
        for _ in 0..<3 { w.step() }
        let idx = lex.idx
        w.cmdMotion(lex, "TAUNT1", [], q)                                                 // blocking form: refused = a zero handle, no wait
        #expect(lex.motId == motId && lex.idx == idx && q.waitPred == nil)
        w.cmdMotion(lex, "TAUNT1", ["NO_SCRIPT", "CONTINUE"], q)                          // NO_SCRIPT skips the gate
        #expect(lex.motId != motId)
        w.cmdMotion(lex, "TAUNT1", ["CONTINUE"], p)
        finish(r, lex)
        let again = lex.motId
        w.cmdMotion(lex, "TAUNT1", ["CONTINUE"], p)                                       // the task has ended: accepted again
        #expect(lex.motId != again)
    }

    @Test func aRecoilDieOrSuperRecTaskRefusesOtherScriptedMotions() throws {
        let (r, _) = try makeCombat()
        let w = r.w, lex = r.lex, p = proc(r.s)
        w.cmdMotion(lex, "RECOIL_TL", ["CONTINUE"], p)
        w.cmdMotion(lex, "TAUNT1", ["CONTINUE"], p)
        #expect(lex.motion == "RECOIL_TL")                                                // refused while RECOIL* is the task
        finish(r, lex)
        w.cmdMotion(lex, "TAUNT1", ["CONTINUE"], p)
        #expect(lex.motion == "TAUNT1")
        lex.taskName = "SUPER_REC_TL"                                                     // 9 characters prefix
        lex.finished = false
        w.cmdMotion(lex, "STAND", ["CONTINUE"], p)
        #expect(lex.motion == "TAUNT1")
    }

    @Test func anUnfinishedDieRefusesSnapToAndSnapToPoseToo() throws {
        let (r, _) = try makeCombat()
        let w = r.w, lex = r.lex, p = proc(r.s)
        w.cmdMotion(lex, "DIE", ["NO_SCRIPT", "CONTINUE"], p)
        w.step()
        w.cmdMotion(lex, "WAKE_UP", ["NO_SCRIPT", "SNAP_TO", "FREEZE"], p)
        #expect(lex.motion == "DIE")
        w.cmdSnapToPose(lex, [.str("WAKE_UP"), .int(3)])
        #expect(lex.motion == "DIE" && lex.idx < 3)
    }

    @Test func aFinishedDieAcceptsAMotionWithHitPointsOrWithout() throws {
        let (r, _) = try makeCombat()
        let w = r.w, lex = r.lex, p = proc(r.s)
        for hp in [100, 0] {
            setLocal0(r, w.objectKey(lex.name), hp)
            w.cmdMotion(lex, "DIE", ["CONTINUE"], p)
            #expect(lex.motion == "DIE")
            finish(r, lex)
            w.cmdMotion(lex, "WAKE_UP", ["CONTINUE"], p)
            #expect(lex.motion == "WAKE_UP", Comment(rawValue: "hp \(hp)"))               // the engine has no corpse lock (1098:0394 / 12bd)
        }
    }

    @Test func aiOnIsRefusedWithAWarningAtZeroHitPoints() throws {
        let (r, _) = try makeCombat()
        let w = r.w, lex = r.lex
        lex.hold = 1
        setLocal0(r, w.objectKey(lex.name), 0)
        _ = call(r, .stmt, "AI", [.str("ON")])
        #expect(!lex.aiEnabled && lex.hold == 1)
        #expect(w.warnings.contains { $0.contains("AI ON") })
        setLocal0(r, w.objectKey(lex.name), 5)
        _ = call(r, .stmt, "AI", [.str("ON")])
        #expect(lex.aiEnabled)
    }

    @Test func aDeadFigureDoesNotIdleAfterAnEngineOneShot() throws {
        let (r, _) = try makeCombat()
        let w = r.w, lex = r.lex
        for (hp, expect) in [(0, "LAND_SOFT"), (5, "STAND")] {
            setLocal0(r, w.objectKey(lex.name), hp)
            lex.setMotion("LAND_SOFT", loop: false, engine: true)
            for _ in 0..<60 { w.step() }                                                  // 8 frames: over after 17 ticks
            #expect(lex.motion == expect, Comment(rawValue: "hp \(hp)"))                  // 1088:508d: idle only with hit points
        }
    }

    @Test func theKillerOfThePlayerGetsTheDieMethodToo() throws {
        let (r, bot) = try makeCombat()
        let w = r.w, lex = r.lex
        setLocal0(r, w.objectKey(lex.name), 5)
        w.damage(lex, bot, 10, 0, 6, false)                                               // hp <= 0 with an attacker
        #expect(lex.hold == 1 && bot.hold == 1)
        lex.hold = 0; bot.hold = 0
        setLocal0(r, w.objectKey(lex.name), 5)
        lex.invulnerable = false
        w.damage(lex, nil, 10, 0, 6, false)                                               // a DAMAGE statement: no attacker, no second hold
        #expect(lex.hold == 1 && bot.hold == 0)
    }
}
