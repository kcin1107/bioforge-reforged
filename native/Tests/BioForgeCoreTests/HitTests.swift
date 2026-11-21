// Melee hits (WorldCombat.swift) against re/interp/test_hits.py: the .COL decoder, the motion attack fields, the guard bytes, the
// hit window, once per play, cube and zone arithmetic, block, armour, the motion-task cancel with its recoil, and the damage rules.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct HitTests {
    /// test_hits.py `Hits.setUp`: CHAOS at its INITGAME state, Lex as the player 100 cm in front of the nurse (it faces -y).
    private func make() throws -> (GameSession, Figure, Figure) {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        let w = s.world
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let p = ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        w.autoCamera = false                                 // at this staged spot CE11 would take over, and CE1_LOAD's SPARWITHPLAYER retarget Lex
        let lex = try #require(w.player), bot = try #require(w.figure("FIRSTBOT"))
        bot.viewCams = nil
        s.vm.globals["_difficulty_level"] = .int(0)
        place(bot, lex, 0, -2000)
        bot.enemy = "PLAYER"; lex.enemy = "FIRSTBOT"
        return (s, lex, bot)
    }

    private func place(_ bot: Figure, _ lex: Figure, _ lx: Double, _ ly: Double) {
        bot.pos = V3(0, 0, 0); bot.heading = 0
        lex.pos = V3(lx, ly, 0)
    }

    private func ticks(_ w: World, _ fig: Figure) -> Int { (fig.frames!.count * w.motionDuration(fig) + World.clockPerTick - 1) / World.clockPerTick }

    private func play(_ s: GameSession, _ fig: Figure, _ motion: String) {
        fig.setMotion(motion, loop: false)
        for _ in 0..<ticks(s.world, fig) { s.tick() }
    }

    private func hp(_ s: GameSession, _ name: String, _ i: Int = 0) -> Int {
        if case .int(let v) = s.vm.objectRecord(s.world.objectKey(name))[i] { return v }
        return -1
    }

    private func setHP(_ s: GameSession, _ name: String, _ v: Int, _ i: Int = 0) {
        var rec = s.vm.objectRecord(s.world.objectKey(name))
        rec[i] = .int(v)
        s.vm.setObject(s.world.objectKey(name), rec)
    }

    @Test func nurseColDecodes() throws {
        let g = try requireGame()
        #expect(try ColVolume.load(g.read("BODY/NURSEBOT.COL")) == [ColVolume(limb: 8, mode: 1, half: 280), ColVolume(limb: 10, mode: 0, half: 220),
                                                                    ColVolume(limb: 14, mode: 1, half: 560), ColVolume(limb: 3, mode: 1, half: 480),
                                                                    ColVolume(limb: 7, mode: 1, half: 200)])
    }

    @Test func motionAttackFieldsAndGuardBytes() throws {
        let g = try requireGame()
        let man = try Motion.load(g.read("BODY/MAN.MTN")), nurse = try Motion.load(g.read("BODY/NURSEBOT.MTN"))
        func find(_ ms: [Motion], _ n: String) throws -> Motion { try #require(ms.first { $0.name == n }) }
        let h8 = try find(man, "ATK_H8"), syringe = try find(nurse, "ATK_SYRINGE")
        #expect((h8.strength, h8.strikeLimb, h8.kind, h8.frames.count) == (25, 17, 1, 13))
        #expect((syringe.strength, syringe.strikeLimb, syringe.kind, syringe.frames.count) == (5, 13, 1, 10))
        #expect(try find(nurse, "DEFEND").kind == 2 && find(man, "ATK_M8").kind == 3)
        let h1 = try find(man, "ATK_H1"), defend = try find(nurse, "DEFEND")
        #expect((0..<6).map { h1.frames[6].guardByte($0) } == [3, 3, 2, 2, 0, 0])
        #expect((0..<6).map { defend.frames[3].guardByte($0) } == [2, 2, 2, 2, 3, 3])
    }

    @Test func rootAnglesAreNotRotations() throws {
        let g = try requireGame()
        let sk = try Skeleton(data: g.read("BODY/MAN.SKL"))
        let h8 = try #require(try Motion.load(g.read("BODY/MAN.MTN")).first { $0.name == "ATK_H8" })
        let f = h8.frames[7]
        #expect(f.rootAngle != .zero)
        let a = sk.solve(f), b = sk.solve(MotionFrame(pos: f.pos, rootAngle: .zero, limbs: f.limbs))
        #expect(zip(a.start, b.start).allSatisfy { $0 == $1 })
    }

    @Test func hitWindowIsFrames4ToNMinus5() {
        #expect((0..<13).filter { World.inHitWindow($0, 13) } == [4, 5, 6, 7, 8])
        #expect((0..<10).filter { World.inHitWindow($0, 10) } == [4, 5])
    }

    @Test func syringeHitsOnceInItsWindowAndAgainOnTheNextPlay() throws {
        let (s, lex, bot) = try make()
        bot.setMotion("ATK_SYRINGE", loop: false)
        var at: [Int] = []
        for _ in 0..<ticks(s.world, bot) {
            let before = s.world.hits.count
            s.tick()
            if s.world.hits.count > before { at.append(bot.idx) }
        }
        #expect(at.count == 1 && (4...5).contains(at[0]))
        place(bot, lex, 0, -2000)                             // Lex recoiled out of reach
        lex.setMotion("STAND", loop: true)
        play(s, bot, "ATK_SYRINGE")
        // the second syringe hit starts REVIVELEX, whose zap is a DAMAGE statement: a hit row without an attacker
        #expect(s.world.hits.filter { $0.attacker != nil }.count == 2)
    }

    @Test func syringeMissesBeyondReachAndBehind() throws {
        let (s, lex, bot) = try make()
        for (x, y) in [(0.0, -9000.0), (0.0, 2000.0)] {
            place(bot, lex, x, y)
            play(s, bot, "ATK_SYRINGE")
        }
        #expect(s.world.hits.isEmpty)
    }

    @Test func attackerBecomesThePlayersEnemy() throws {
        let (s, lex, bot) = try make()
        lex.enemy = nil
        place(bot, lex, 0, -9000)
        play(s, bot, "ATK_SYRINGE")
        #expect(lex.enemy == "FIRSTBOT")
    }

    @Test func cubeIsStrictAndCentredOnEndOrMidpoint() throws {
        let (s, _, bot) = try make()
        let w = s.world, geom = w.limbGeometry(bot)
        let end = geom.ends[10]
        for (d, expect) in [(V3(0, 0, 0), true), (V3(219, 0, 0), true), (V3(220, 0, 0), false), (V3(0, -219, 220), false), (V3(0, 0, -219), true)] {
            #expect(w.colHit(bot, end + d, geom) == expect)
        }
        let mid = geom.ends[8] - geom.dirs[8] * (Double(bot.assets.assets.skeleton.limbs[8].length) / 2)
        #expect(w.colHit(bot, mid, geom) && w.colHit(bot, mid + V3(0, 0, 279), geom) && !w.colHit(bot, mid + V3(0, 0, 280), geom))
    }

    @Test func zoneHeightAndSide() throws {
        let (s, lex, _) = try make()
        let w = s.world, egeom = w.limbGeometry(lex)
        #expect(lex.assets.footOffset == 2312)
        let rootZ = egeom.ends[0].z, h = 369.0              // F x 0.16 in the engine's integer form
        lex.pos = V3(0, 0, 0); lex.heading = 0               // faces -y: +x is its left
        let left = Figure(name: "A", type: "LEX", assets: lex.assets, speed: 512, pos: V3(2000, -1000, 0))
        let right = Figure(name: "B", type: "LEX", assets: lex.assets, speed: 512, pos: V3(-2000, -1000, 0))
        for (z, base) in [(rootZ + h + 1, 0), (rootZ + h, 2), (rootZ, 2), (rootZ - h, 2), (rootZ - h - 1, 4)] {
            #expect(w.hitZone(lex, left, z, egeom) == base)
            #expect(w.hitZone(lex, right, z, egeom) == base + 1)
        }
    }

    @Test func armouredNurseTakesNoDamageButStillRunsGotHitAndRecoils() throws {
        let (s, lex, bot) = try make()
        s.vm.globals["_nursebot_is_hit"] = .int(0)
        bot.setMotion("STAND", loop: true)
        lex.setMotion("ATK_H8", loop: false)
        s.world.damage(bot, lex, 25, 0, 2, true)                // ML, heavy
        #expect(hp(s, "FIRSTBOT") == 50)                      // IMPACT_ARMOR 100
        #expect(s.vm.globals["_nursebot_is_hit"] == .int(1))   // FIRSTBOT_STIMULUS :GOT_HIT
        #expect(bot.motion == "RECOIL_TL" && hp(s, "FIRSTBOT", 3) == 1)    // super_rec_ml missing: side fallback
        #expect(s.world.hits.last.map { [$0.attacker, $0.target, $0.motion] } == ["LEX", "FIRSTBOT", "ATK_H8"])
        for _ in 0..<(ticks(s.world, bot) + 3) { s.tick() }
        #expect(hp(s, "FIRSTBOT", 3) == 0)                    // ASSUMPTION: cleared when the recoil ends
    }

    @Test func hitCancelsTheMotionTaskSoABusyTargetRecoils() throws {
        let (s, lex, bot) = try make()
        bot.setMotion("ATK_STAND", loop: true)
        lex.setMotion("ATK_H8", loop: false)
        s.world.damage(bot, lex, 25, 0, 2, false)
        #expect(bot.motion == "RECOIL_TL" && hp(s, "FIRSTBOT", 3) == 1)
    }

    /// FUN_1098_0789(target, 1, 0) ends turn_to_enemy; +0x15f holds the recoil's name, so a taunt's next MOTION is refused (FUN_1098_12bd).
    @Test func aRecoilEndsTheTurnTaskAndRefusesAScriptsMotion() throws {
        let (s, lex, bot) = try make()
        bot.setMotion("ATK_STAND", loop: true)
        lex.setMotion("ATK_H8", loop: false)
        bot.confront = ConfrontTask()
        s.world.damage(bot, lex, 25, 0, 2, false)
        #expect(bot.confront == nil && bot.motion == "RECOIL_TL")
        #expect(bot.motionGateRefuses("STAND"))
    }

    @Test func unfinishedDieIsNotCancelledAndDoesNotRecoil() throws {
        let (s, lex, bot) = try make()
        lex.setMotion("DIE", loop: false)
        bot.setMotion("ATK_SYRINGE", loop: false)
        setHP(s, "LEX", 100)
        s.world.damage(lex, bot, 10, 0, 2, false)
        #expect(lex.motion == "DIE" && !lex.frozen && hp(s, "LEX", 3) == 0)
    }

    @Test func noMotionReplacesDie() throws {
        // FUN_1098_0394 refuses a motion change while the current motion is DIE
        let (_, lex, _) = try make()
        #expect(lex.setMotion("DIE", loop: false))
        #expect(!lex.setMotion("ATK_STAND", loop: true))
        #expect(lex.motion == "DIE")
        #expect(!lex.setMotion("WAKE_UP", loop: false))      // 1098:0394 has no SNAP_TO exception (REVIVELEX runs after the blocking MOTION DIE)
    }

    @Test func godModeKeepsLexsHitPointsWhateverHitsHimAndRefillRestoresThem() throws {
        let (s, _, bot) = try make()
        s.world.setGodMode(true)
        let before = hp(s, "LEX")
        s.world.damage(try #require(s.world.player), bot, 25, 0, 2, false)       // a combat hit
        s.vm.addToObject(s.world.objectKey("LEX"), 0, -30)                       // DAMAGE / a script's `LEX.~0 -= n`
        #expect(hp(s, "LEX") == before)
        s.world.setGodMode(false)
        s.vm.addToObject(s.world.objectKey("LEX"), 0, -30)
        #expect(hp(s, "LEX") == before - 30)                  // off: as before
        s.world.refillHealth()
        #expect(hp(s, "LEX") == hp(s, "LEX", 5) && hp(s, "LEX") > before - 30)
    }

    @Test func syringeRunsHitPlayerLabelAndHurtsLexByTheDifficultyAdjustedAmount() throws {
        let (s, _, bot) = try make()
        s.vm.globals["_lex_drugged"] = .int(0)
        play(s, bot, "ATK_SYRINGE")
        #expect(s.vm.globals["_lex_drugged"] == .int(1))
        #expect(hp(s, "LEX") == 99)                           // 5 - 4 at difficulty 0
        #expect(s.world.hits.last.map { [$0.attacker, $0.target, $0.motion, $0.label] } == ["FIRSTBOT", "LEX", "ATK_SYRINGE", "HIT_PLAYER_ATK_SYRINGE"])
    }

    @Test func difficultyScalesDamageToThePlayer() throws {
        let (s, lex, bot) = try make()
        s.vm.globals["_difficulty_level"] = .int(2)
        bot.setMotion("ATK_SYRINGE", loop: false)
        s.world.damage(lex, bot, 5, 0, 2, false)
        #expect(hp(s, "LEX") == 100 - 13)                     // +4 x 2
    }

    @Test func invulnerableOrZeroDamageLeavesHitPointsAndRunsNoGotHit() throws {
        let (s, lex, bot) = try make()
        bot.setMotion("ATK_SYRINGE", loop: false)
        s.world.damage(lex, bot, 4, 0, 2, false)                 // 4 - 4 = 0 at difficulty 0
        #expect(hp(s, "LEX") == 100 && s.world.hits.last?.label == "")
        lex.invulnerable = true
        s.world.damage(lex, bot, 40, 0, 2, false)
        #expect(hp(s, "LEX") == 100)
    }

    @Test func deadPlayerIsIgnoredAndEliteDoesNoDamage() throws {
        let (s, lex, bot) = try make()
        bot.setMotion("ATK_SYRINGE", loop: false)
        setHP(s, "LEX", 3)
        s.world.damage(lex, bot, 10, 0, 2, false)
        #expect(hp(s, "LEX") == -3)
        s.world.damage(lex, bot, 10, 0, 2, false)                // HP <= 0: ignored
        #expect(hp(s, "LEX") == -3)
        setHP(s, "LEX", 100)
        bot.name = "ELITE"
        s.world.damage(lex, bot, 40, 0, 2, false)
        #expect(hp(s, "LEX") == 100)
    }

    /// DEFEND's guard bytes are 02 02 02 02 03 03 from frame 2, so a punch landing in the top or middle zone from the front is blocked
    /// (no damage dispatch, no GOT_HIT); the same punch on a standing nurse (guard 03 03 ... = not a block) runs GOT_HIT.
    @Test func guardedZoneBlocksAPunch() throws {
        var labels: [String: [String]] = [:]
        for motion in ["STAND", "DEFEND"] {
            let (s, lex, bot) = try make()
            s.vm.globals["_nursebot_is_hit"] = .int(0)
            place(bot, lex, 0, -2000); lex.heading = 180
            bot.setMotion(motion, loop: true); bot.idx = 3
            lex.setMotion("ATK_H8", loop: false)
            for _ in 0..<ticks(s.world, lex) { s.tick() }
            labels[motion] = s.world.hits.map(\.label)
            if motion == "DEFEND" { #expect(s.vm.globals["_nursebot_is_hit"] == .int(0)) }
        }
        #expect(labels["STAND"] == ["GOT_HIT"] && labels["DEFEND"] == ["BLOCKED"])
    }

    // MARK: combat auto-turn (test_hits.py AutoTurn)

    /// Process whose current figure is `fig`, for statements such as DAMAGE.
    private func proc(_ s: GameSession, _ fig: String) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: fig))
    }

    private func cmd(_ s: GameSession, _ fig: String, _ name: String, _ args: ScriptValue...) { _ = s.world.call(.stmt, name, args, proc(s, fig)) }

    /// Lex at the origin facing -y with the robot `deg` degrees to its left (negative: right); combat mode, enemy set.
    private func aim(_ s: GameSession, _ lex: Figure, _ bot: Figure, _ deg: Double, _ motion: String = "ATK_STAND") {
        let a = deg * Double.pi / 180
        lex.pos = V3(0, 0, 0); lex.heading = 0
        bot.pos = V3(2000 * sin(a), -2000 * cos(a), 0)
        lex.combat = true; lex.enemy = "FIRSTBOT"; lex.motion = motion
        lex.autoTurnCount = 0
        #expect(abs(s.world.relAngle(lex, bot.pos!) - deg) < 0.01)
    }

    private func turned(_ lex: Figure) -> Double { defer { lex.heading = 0 }; return lex.heading }

    @Test func autoTurnWindowAndStepCap() throws {
        let (s, lex, bot) = try make()
        for (deg, step) in [(2, 0), (3, 1), (10, 5), (12, 6), (30, 6), (54, 6), (55, 0), (90, 0)] {
            for sign in [1.0, -1.0] {
                aim(s, lex, bot, sign * Double(deg))
                s.world.autoTurn(lex)
                #expect(turned(lex) == -sign * Double(step))      // +heading turns right, so a bearing to the left lowers the heading
            }
        }
    }

    @Test func autoTurnReducesTheBearing() throws {
        let (s, lex, bot) = try make()
        aim(s, lex, bot, 20)
        s.world.autoTurn(lex)
        #expect(abs(s.world.relAngle(lex, bot.pos!) - 14) < 0.01)
    }

    @Test func autoTurnOnlyInAttackStandShootAndAtkMButNotM4M6() throws {
        let (s, lex, bot) = try make()
        for (motion, acts) in [("ATK_M8", false), ("atk_m1", false), ("ATK_M4", false), ("ATK_M6", false), ("ATK_STAND", true),
                               ("SHOOT", true), ("STAND", false), ("ATK_H8", false), ("WALK", false)] {
            aim(s, lex, bot, 20, motion)
            s.world.autoTurn(lex)
            #expect((turned(lex) != 0) == acts, "\(motion)")
        }
    }

    @Test func autoTurnOnlyThePlayerInCombatWithAnEnemy() throws {
        let (s, lex, bot) = try make()
        aim(s, lex, bot, 20); lex.combat = false
        s.world.autoTurn(lex)
        #expect(turned(lex) == 0)
        aim(s, lex, bot, 20); lex.enemy = nil
        s.world.autoTurn(lex)
        #expect(turned(lex) == 0)
        aim(s, lex, bot, 20)
        bot.combat = true; bot.enemy = "PLAYER"; bot.motion = "ATK_M8"          // a non-player never auto-turns
        bot.pos = V3(0, 0, 0); lex.pos = V3(-1000, -1000, 0)
        s.world.autoTurn(bot)
        #expect(bot.heading == 0)
    }

    @Test func autoTurnCounterActsEveryAutoTurnSpeedCalls() throws {
        let (s, lex, bot) = try make()
        s.world.propOverrides["AUTO_TURN_SPEED"] = 3
        aim(s, lex, bot, 20)
        s.world.autoTurn(lex); s.world.autoTurn(lex)
        #expect(lex.heading == 0 && lex.autoTurnCount == 2)
        s.world.autoTurn(lex)
        #expect(lex.heading == -6 && lex.autoTurnCount == 0)
        s.world.propOverrides["AUTO_TURN_SPEED"] = 0
        lex.heading = 0
        s.world.autoTurn(lex)
        #expect(lex.heading == 0)
    }

    @Test func stepRunsAutoTurnEachFrame() throws {
        let (s, lex, bot) = try make()
        aim(s, lex, bot, 20)
        lex.setMotion("ATK_STAND", loop: true)
        lex.heading = 0
        s.world.step()
        #expect(lex.heading == -6)
    }

    // MARK: damage extras (test_hits.py DamageExtras)

    /// Replace the stimulus-label lookup; `existing` are the (figure, label) pairs that count as present.
    private func labels(_ s: GameSession, _ existing: Set<String> = []) -> LabelLog {
        let log = LabelLog()
        s.world.labelProbe = { fig, label, dmg in log.rows.append((fig, label, dmg)); return existing.contains("\(fig)/\(label)") }
        return log
    }

    final class LabelLog { var rows: [(fig: String, label: String, dmg: Int)] = []; var names: [String] { rows.map { "\($0.fig)/\($0.label)" } } }

    @Test func damageStatementIsImpactOrEnergyWithoutAttacker() throws {
        let (s, _, _) = try make()
        setHP(s, "FIRSTBOT", 100)
        let log = labels(s)
        cmd(s, "FIRSTBOT", "DAMAGE", .str("ENERGY"), .int(30))
        #expect(hp(s, "FIRSTBOT") == 70)                      // NURSEBOT ENERGY_ARMOR 0; difficulty 0 adjusts a non-player by 0
        #expect(Set(log.rows.map(\.dmg)) == [30])
        let h = try #require(s.world.hits.last)
        #expect(h.attacker == nil && h.target == "FIRSTBOT" && h.motion == "Unknown")
    }

    @Test func energyUsesEnergyArmourAndImpactUsesImpactArmour() throws {
        let (s, _, _) = try make()
        setHP(s, "FIRSTBOT", 100)
        cmd(s, "FIRSTBOT", "DAMAGE", .int(20))                // impact: NURSEBOT IMPACT_ARMOR 100 swallows it
        #expect(hp(s, "FIRSTBOT") == 100)
        cmd(s, "FIRSTBOT", "DAMAGE", .int(20), .str("ENERGY"))   // energy: ENERGY_ARMOR 0
        #expect(hp(s, "FIRSTBOT") == 80)
    }

    @Test func energyLabelsAndZone6SkipsZoneLabelsAndRecoil() throws {
        let (s, _, _) = try make()
        setHP(s, "FIRSTBOT", 100)
        let log = labels(s)
        cmd(s, "FIRSTBOT", "DAMAGE", .str("ENERGY"), .int(10))
        #expect(log.names == ["FIRSTBOT/ENERGY_DAMAGE", "FIRSTBOT/GOT_HIT"])
        #expect(hp(s, "FIRSTBOT", 3) == 0)                    // no recoil
        log.rows.removeAll()
        setHP(s, "LEX", 100)
        cmd(s, "LEX", "DAMAGE", .str("ENERGY"), .int(10))     // player with an enemy: PLAYER_ENERGY_DAMAGE on it
        #expect(log.names == ["LEX/ENERGY_DAMAGE", "FIRSTBOT/PLAYER_ENERGY_DAMAGE", "LEX/GOT_HIT"])
        #expect(hp(s, "LEX") == 100 - 6)                      // difficulty 0: 10 - 4
        log.rows.removeAll()
        setHP(s, "LEX", 5)
        cmd(s, "LEX", "DAMAGE", .str("ENERGY"), .int(20))
        #expect(log.names.contains("FIRSTBOT/KILLED_PLAYER") && !log.names.contains("FIRSTBOT/PLAYER_ENERGY_DAMAGE"))
    }

    @Test func noAttackerSkipsAttackerLabels() throws {
        let (s, lex, _) = try make()
        let log = labels(s)
        setHP(s, "LEX", 80)
        s.world.damage(lex, nil, 25, 0, 2, true)
        #expect(!log.rows.map(\.fig).contains("FIRSTBOT"))
        let h = try #require(s.world.hits.last)
        #expect(h.attacker == nil && h.target == "LEX" && h.motion == "Unknown")
    }

    @Test func energyArmourValue() throws {
        let (s, _, bot) = try make()
        let w = s.world
        w.propOverrides = ["ENERGY_ARMOR": 15, "IMPACT_ARMOR": 10]
        setHP(s, "FIRSTBOT", 100)
        bot.invulnerable = false
        w.damage(bot, nil, 40, 1, 6, false)
        #expect(hp(s, "FIRSTBOT") == 75)
        w.damage(bot, nil, 40, 0, 6, false)
        #expect(hp(s, "FIRSTBOT") == 45)
        w.damage(bot, nil, 15, 1, 6, false)                   // fully absorbed
        #expect(hp(s, "FIRSTBOT") == 45)
    }

    @Test func knockbackOnlyForABouncyVulnerableTargetWithAnAttacker() throws {
        let (s, lex, bot) = try make()
        let w = s.world
        lex.heading = 90                                      // forward = (-1, 0)
        bot.bouncy = true
        w.damage(bot, lex, 25, 0, 2, false)
        #expect((bot.vx, bot.vy, bot.vz) == (-256, 0, 0))      // v -= row 1: pushed away from the attacker, along forward
        bot.vx = 0
        w.damage(bot, nil, 25, 0, 6, false)
        #expect((bot.vx, bot.vy) == (0, 0))
        bot.invulnerable = true
        w.damage(bot, lex, 25, 0, 2, false)
        #expect((bot.vx, bot.vy) == (0, 0))
        bot.invulnerable = false; bot.bouncy = false
        w.damage(bot, lex, 25, 0, 2, false)
        #expect((bot.vx, bot.vy) == (0, 0))
        bot.bouncy = true
        setHP(s, "FIRSTBOT", 0)                               // a dead target is not pushed either
        w.damage(bot, lex, 25, 0, 2, false)
        #expect((bot.vx, bot.vy) == (0, 0))
    }

    @Test func hitAndBlockSoundNames() throws {
        let (s, lex, bot) = try make()
        let w = s.world
        var names: [String] = []
        w.soundNameProbe = { names.append($0); return 3 }
        bot.invulnerable = false
        setHP(s, "FIRSTBOT", 100)
        let before = w.soundLog.count
        w.damage(bot, lex, 25, 0, 2, false)
        #expect(names.first == "_LEX_HITS_NURSEBOT_\(w.currentCamera ?? "None")")
        #expect(w.soundLog.count > before && w.soundLog[before].index == 3)
        names.removeAll()
        bot.invulnerable = true
        let blocked = w.soundLog.count
        w.damage(bot, lex, 25, 0, 2, false)
        #expect(names.first == "_BLOCK_NURSEBOT_LEX")
        #expect(w.soundLog.count == blocked + 1 && w.soundPos[w.soundLog[blocked].handle] == nil)     // FUN_1100_1d34: a block sound is not positional
        names.removeAll()
        w.damage(bot, nil, 25, 0, 6, false)
        #expect(names.first == "_BLOCK_NURSEBOT")
        w.soundNameProbe = { _ in nil }                       // unknown names play nothing
        let n = w.soundLog.count
        w.damage(bot, lex, 25, 0, 2, false)
        #expect(w.soundLog.count == n)
    }

    @Test func hitAndBlockNamesFallBackToShorterNames() throws {
        let (s, lex, bot) = try make()
        let w = s.world
        bot.invulnerable = false
        setHP(s, "FIRSTBOT", 100)
        var n0 = w.soundLog.count
        w.damage(bot, lex, 25, 0, 2, false)
        #expect(w.soundLog[n0].index == w.soundIndex(.str("_LEX_HITS_NURSEBOT")))
        #expect(w.soundPos[w.soundLog[n0].handle]?.key == bot.name)
        n0 = w.soundLog.count
        bot.invulnerable = true
        w.damage(bot, lex, 25, 0, 2, false)
        #expect(w.soundLog[n0].index == w.soundIndex(.str("_BLOCK")))
        #expect(w.ambientId("_CAYNAN_HITS_LEX_CE31") == w.soundIndex(.str("_CAYNAN_HITS_LEX")))
        #expect(w.ambientId("_BLOCK_LEX_ELITE_X") == w.soundIndex(.str("_BLOCK_LEX_ELITE")))
    }

    private func spyBlocks(_ s: GameSession) -> BlockLog {
        let log = BlockLog()
        s.world.blockProbe = { fig, block in log.rows.append("\(fig)/\(block)") }
        return log
    }

    final class BlockLog { var rows: [String] = [] }

    @Test func woundsBlockRunsOnAHitWithTheTypeName() throws {
        let (s, lex, bot) = try make()
        let log = spyBlocks(s)
        setHP(s, "FIRSTBOT", 100)
        bot.invulnerable = false
        s.world.damage(bot, lex, 25, 0, 2, false)
        #expect(log.rows == ["FIRSTBOT/NURSEBOT_WOUNDS"])
        log.rows.removeAll()
        s.world.damage(lex, bot, 25, 0, 2, false)             // the player: LEX_WOUNDS (DAMAGE.scr)
        #expect(log.rows == ["LEX/LEX_WOUNDS"])
    }

    @Test func deathRunsWoundsThenSuspendsAIAndSetsInvulnerableAndRunsDeathBlock() throws {
        let (s, lex, bot) = try make()
        let text = "{ FIRSTBOT_DEATH\n\t_door_frame = 42\n}\n"
        s.vm.load(DecodedScript(name: "SYN_DEATH.scr", text: Array(text.utf8), lineStarts: [], columns: [], unresolved: []))
        s.vm.globals["_door_frame"] = .int(0)
        let block = ScriptBlock("TEST", "routine", 0, nil)
        let ai = ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: "FIRSTBOT"))
        bot.aiProc = ai
        setHP(s, "FIRSTBOT", 5)
        bot.invulnerable = false
        let log = spyBlocks(s)
        _ = labels(s)
        s.world.damage(bot, lex, 25, 1, 2, false)             // energy: the nurse's IMPACT_ARMOR 100 would absorb it
        #expect(log.rows == ["FIRSTBOT/NURSEBOT_WOUNDS", "FIRSTBOT/FIRSTBOT_DEATH"])
        #expect(s.vm.globals["_door_frame"] == .int(42))
        #expect(bot.invulnerable && bot.hold == 1 && ai.suspended)
        #expect(hp(s, "FIRSTBOT") <= 0)
    }

    @Test func aLivingTargetGetsNoDeathHandling() throws {
        let (s, lex, bot) = try make()
        let log = spyBlocks(s)
        setHP(s, "FIRSTBOT", 100)
        bot.invulnerable = false
        s.world.damage(bot, lex, 25, 0, 2, false)
        #expect(!bot.invulnerable && bot.hold == 0)
        #expect(!log.rows.contains("FIRSTBOT/FIRSTBOT_DEATH"))
    }

    @Test func deadPlayerGetsKilledPlayerOnTheAttackerAndNoInput() throws {
        let (s, lex, bot) = try make()
        let log = labels(s)
        setHP(s, "LEX", 3)
        s.world.damage(lex, bot, 10, 0, 2, false)
        #expect(log.names == ["FIRSTBOT/KILLED_PLAYER"])
        #expect(lex.invulnerable && lex.hold == 1)
        lex.pos = V3(0, 0, 0); lex.heading = 0
        s.world.setPlayerInput(forward: 1)
        s.world.applyPlayerInput()
        #expect(!lex.manualControl)
    }
}
