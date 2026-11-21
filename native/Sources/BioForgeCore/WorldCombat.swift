// Melee hits (world.py update_hit / col_hit / hit_zone / raise_label / damage), recovered from the original (NOTES "Melee hits").
//
// FUN_1088_0708 runs each figure update after the frame advance: a kind-1 (strike) motion with an enemy tests the striking limb's end
// (then one more limb length along the limb) against the enemy's .COL cubes on frames 4 ... nframes-5, once per play. A hit gets a
// zone from its height and side, may be blocked by the enemy's per-zone guard byte (the frame row's bytes 12..17), and otherwise runs
// FUN_1090_09b9 (`damage`): difficulty, armour, hit points, the motion-task cancel and the stimulus labels, knockback, sounds, the
// WOUNDS / DEATH blocks; also the DAMAGE statement and the player's combat auto-turn (FUN_1088_3419).
import Foundation

extension World {
    static let hitZones = ["TL", "TR", "ML", "MR", "BL", "BR"]

    /// Limb end positions in world units and unit limb directions of the figure's current frame, placed like the renderer places
    /// its vertices (root x,y zeroed, root z kept, rotated by -heading, plus pos). The frame's rootAngle words are the guard table,
    /// not a rotation (Skeleton.solve ignores them).
    func limbGeometry(_ fig: Figure) -> (ends: [V3], dirs: [V3]) {
        let frames = fig.frames!, limbs = fig.assets.assets.skeleton.limbs
        let (start, rot) = fig.assets.assets.skeleton.solve(frames[min(fig.idx, frames.count - 1)])
        let ends = zip(zip(start, rot), limbs).map { $0.0 + $0.1.r[1] * Double($1.length) }
        return (Scene.place(ends, at: fig.pos!, yaw: -fig.heading), Scene.place(rot.map { $0.r[1] }, at: .zero, yaw: -fig.heading))
    }

    /// FUN_10b0_0031: `pt` against the figure's .COL cubes (centre = the limb's end for mode 0, else its midpoint, end - row1 x scaled
    /// length / 2; a hit needs all three axis offsets below the half-size). Scale 0x100 = 1: the port has no per-limb scale.
    func colHit(_ fig: Figure, _ pt: V3, _ geom: (ends: [V3], dirs: [V3])) -> Bool {
        for v in fig.assets.assets.col where v.limb < geom.ends.count {
            let c = v.mode == 0 ? geom.ends[v.limb]
                : geom.ends[v.limb] - geom.dirs[v.limb] * (Double(fig.assets.assets.skeleton.limbs[v.limb].length) / 2)
            let d = pt - c, h = Double(v.half)
            if abs(d.x) < h && abs(d.y) < h && abs(d.z) < h { return true }
        }
        return false
    }

    /// FUN_1088_0708's frame conditions: current frame > 3 and more than 3 frames after it (frames 4 ... nframes-5).
    static func inHitWindow(_ frame: Int, _ count: Int) -> Bool { frame > 3 && count - (frame + 1) > 3 }

    /// FUN_1088_0708, run each figure update after the frame advance (see the header). ASSUMPTION: a looping motion's restart also
    /// clears `hitDone` (advance); a frozen (held) figure does not strike. The start-blend condition (+0x128) is not modelled.
    func updateHit(_ fig: Figure) {
        guard let vm, !fig.hitDone, !fig.frozen, fig.pos != nil, let info = fig.motionInfo, info.kind == 1,
              let frames = fig.frames, !frames.isEmpty else { return }
        let n = frames.count, f = fig.idx
        guard Self.inHitWindow(f, n), let e = enemyFig(fig), e.pos != nil, let eframes = e.frames, !eframes.isEmpty else { return }
        if let p = player, fig !== p { p.enemy = fig.name }        // the engine writes the player's enemy pointer (+0x195)
        let limb = info.strikeLimb, geom = limbGeometry(fig)
        guard limb < geom.ends.count else { return }
        let egeom = limbGeometry(e), end = geom.ends[limb]
        // the limb's end, else one more limb length along the limb
        let reach = end + geom.dirs[limb] * Double(fig.assets.assets.skeleton.limbs[limb].length)
        guard let pt = [end, reach].first(where: { colHit(e, $0, egeom) }) else { return }
        fig.hitDone = true
        let zone = hitZone(e, fig, pt.z, egeom)
        // the enemy's current frame record bytes 12..17 are the guard table, one byte per zone
        let guardBits = eframes[min(e.idx, eframes.count - 1)].guardByte(zone) & 3
        if guardBits == 2 && abs(relAngle(e, fig.pos!)) < 110 {
            hitSound("_metal_clank_1")                    // blocked: no damage dispatch (1088:0708 -> FUN_1100_1d34: not positional)
            hits.append((vm.tick, fig.name, e.name, fig.motion ?? "", "BLOCKED"))
            return
        }
        damage(e, fig, info.strength, 0, zone, guardBits == 1 || info.strength > 19)
    }

    /// Zone index of a hit at height `z` on enemy `e`: h = F x 0.16 in the engine's integer form; z above the enemy's root limb end z + h
    /// is top (0), below root z - h bottom (4), else middle (2); +1 when the attacker is on the enemy's right (negative bearing).
    func hitZone(_ e: Figure, _ attacker: Figure, _ z: Double, _ egeom: (ends: [V3], dirs: [V3])) -> Int {
        let h = Double(((foot(e) * 0x1000 / 256) << 8) / 0x6400)
        let rootZ = egeom.ends[0].z
        return (z > rootZ + h ? 0 : z < rootZ - h ? 4 : 2) + (relAngle(e, attacker.pos!) < 0 ? 1 : 0)
    }

    /// FUN_1090_12a6: run `<figure>_STIMULUS` at `label` with _DAMAGE = dmg; true iff the label exists (a block without it is not run).
    func raiseLabel(_ fig: Figure, _ label: String, _ dmg: Int) -> Bool {
        if let labelProbe { return labelProbe(fig.name, label, dmg) }
        return vm?.spawnAt(fig.name + "_STIMULUS", label: label, args: [.int(dmg)], ctx: spawnContext(fig)) != nil
    }

    /// Local ~`i` of the figure's object record (non-integer counts as 0).
    private func local(_ fig: Figure, _ i: Int) -> Int {
        if case .int(let v)? = vm?.objectRecord(objectKey(fig.name))[i] { return v }
        return 0
    }

    private func setLocal(_ fig: Figure, _ i: Int, _ v: Int) {
        guard let vm else { return }
        var rec = vm.objectRecord(objectKey(fig.name))
        rec[i] = .int(v)
        vm.setObject(objectKey(fig.name), rec)
    }

    /// FIGURES.SCP MATERIAL of the figure's TYPE block (fig+2 is the type name), or nil.
    func material(_ fig: Figure) -> String? {
        guard let v = resources.figureProps[fig.type.uppercased()]?["MATERIAL"]?.first else { return nil }
        return pyStr(v).uppercased()
    }

    /// FUN_1100_1ce4 (positional at `fig` / `item`) / FUN_1100_1d34 (neither: not positional) -> 1100:1c3e: the name goes through 1118:0044
    /// (`ambientId`: cut at the last `_` until the bank has it, so `_CAYNAN_HITS_LEX_CE31` plays `_CAYNAN_HITS_LEX`; nothing left plays
    /// nothing), priority 1, volume 255, pitch 0.
    func hitSound(_ name: String, fig: Figure? = nil, item: Item? = nil) {
        let idx = ambientId(name)
        if idx >= 0 { playSound(idx, fig: fig?.pos != nil ? fig : nil, item: item) }
    }

    /// FUN_1120_0000: run script block `block` with `fig` as the current figure; a missing block does nothing.
    @discardableResult func runFigureBlock(_ fig: Figure, _ block: String) -> Bool {
        blockProbe?(fig.name, block)
        return spawnFor(fig, block)
    }

    /// FIGURES.SCP property of the figure as FUN_1088_2a87 reads it, by the type name +0x1ea (test overrides first).
    func prop(_ fig: Figure, _ name: String, _ fallback: Int) -> Int {
        propOverrides[name] ?? resources.figureProp(name: fig.type, type: fig.type, prop: name, default: fallback)    // FUN_1088_2a87 re-reads by the form name
    }

    /// FUN_1088_3196 (figure vtable +0x9c, the same call FUN_10a0_0072 makes when a fall starts): +0x229++, the figure's script process
    /// suspended and player input ignored (applyPlayerInput). NOT PORTED: with `endTask` the engine also ends the figure's task +0x15b
    /// (not identified).
    func dieMethod(_ fig: Figure, endTask: Bool) {
        fig.hold += 1
        if let p = fig.aiProc, !p.done { p.suspended = true }
    }

    /// FUN_1088_3419, called by FUN_1088_39ef for the player in combat mode (flag 0x40) while a game runs: every AUTO_TURN_SPEED
    /// (FIGURES.SCP, +0x1df; Lex 1) calls, during atk_stand or shoot, turn min(|a| >> 1, 6) degrees toward
    /// the enemy when its bearing a (relAngle, positive = left) has 3 <= |a| < 55. ASSUMPTIONS: a is rounded to whole degrees like
    /// DISTFROMENEMY's bearing; the counter resets whenever it reaches the speed, whether or not the motion allows a turn.
    func autoTurn(_ fig: Figure) {
        guard vm != nil, fig === player, fig.combat, let e = enemyFig(fig), e.pos != nil, fig.pos != nil else { return }
        let speed = prop(fig, "AUTO_TURN_SPEED", 0)
        if speed < 1 { return }
        fig.autoTurnCount += 1
        if fig.autoTurnCount < speed { return }
        fig.autoTurnCount = 0
        let m = (fig.motion ?? "").lowercased()
        // 1088:3419 also tests for "atk_m" (DS:2595) with a case-sensitive compare, but the keys name them "atk_M8" (DS:2b34), so it never matches
        guard m == "atk_stand" || m == "shoot" else { return }
        let a = Int(relAngle(fig, e.pos!).rounded(.toNearestOrEven))
        if 2 < abs(a) && abs(a) < 0x37 {
            let step = Double(min(abs(a) >> 1, 6))
            fig.heading -= a > 0 ? step : -step      // +heading turns right; a > 0 is to the left
        }
    }

    /// FUN_1090_09b9(target, attacker, dmg, type, zone, heavy): type 0 impact, 1 energy; `attacker` may be nil (the DAMAGE statement) and
    /// zone 6 means no zone. Appends to `hits`. Without an attacker the ELITE check, knockback and every label raised on the attacker are
    /// skipped and its motion name reads "Unknown". NOT PORTED: FUN_1258_0f8b() for a player target (a HUD refresh, as far as known).
    func damage(_ target: Figure, _ attacker: Figure?, _ strength: Int, _ type: Int, _ zone: Int, _ heavy: Bool) {
        guard let vm else { return }
        var dmg = strength
        let zname: String? = zone < 6 ? Self.hitZones[zone] : nil
        var ran: [String] = []
        func raise(_ fig: Figure, _ label: String) -> Bool {
            let ok = raiseLabel(fig, label, dmg)
            if ok { ran.append(label) }
            return ok
        }
        func record() { hits.append((vm.tick, attacker?.name, target.name, attacker?.motion ?? "Unknown", ran.last ?? "")) }

        let isPlayer = target === player
        let tmat = material(target)
        if let attacker, attacker.name.uppercased() == "ELITE" || attacker.type.uppercased() == "ELITE" {
            if !target.invulnerable { _ = raise(attacker, "HIT_PLAYER_FOR_ZERO") }
            record()
            return
        }
        if local(target, 0) <= 0 { return }
        if let attacker, target.bouncy && !target.invulnerable {
            // knockback: velocity (+0xc6/+0xca/+0xce) -= the attacker's orientation row 1 (FUN_1090_09b9; 256 = 1.0). Row 1 is the
            // figure's BACKWARD vector (-forward()), so the target is pushed away from the attacker at 256 units per frame
            let row1 = orientation(attacker)[1]
            target.vx -= row1[0]; target.vy -= row1[1]; target.vz -= row1[2]
        }
        var d = 0
        if case .int(let v)? = vm.globals["_difficulty_level"] { d = v }
        dmg += isPlayer ? (d == 0 ? -4 : 4 * d) : -4 * d
        if target.invulnerable || dmg < 1 {
            if let te = enemyFig(target) { _ = raise(te, "HIT_PLAYER_FOR_ZERO") }
            _ = raise(target, "HIT_FOR_ZERO")
            if let attacker { hitSound("_BLOCK_\(tmat ?? "None")_\(material(attacker) ?? "None")") }     // FUN_1100_1d34: not positional
            else { hitSound("_BLOCK_\(tmat ?? "None")") }
            record()
            return
        }
        let armor = type == 1 ? "ENERGY_ARMOR" : "IMPACT_ARMOR"
        dmg = max(0, dmg - prop(target, armor, 0))
        let prev = local(target, 0)
        setLocal(target, 0, prev - dmg)
        setLocal(target, 7, max(0, local(target, 7) - dmg))
        let tmotion = target.motion ?? "", amotion = attacker?.motion ?? "Unknown"      // names before the cancel
        let cancel = !(tmotion == "DIE" && !target.finished)
        if cancel { target.stopMotion() }       // FUN_1098_0789(target, 1, 0): ends the script-started motion task (STOPMOTION's equivalent)
        if type == 1 {
            _ = raise(target, "ENERGY_DAMAGE")
            if isPlayer, let pe = enemyFig(target) { _ = raise(pe, local(target, 0) <= 0 ? "KILLED_PLAYER" : "PLAYER_ENERGY_DAMAGE") }
        }
        if let attacker {
            hitSound("_\(material(attacker) ?? "None")_HITS_\(tmat ?? "None")_\(currentCamera ?? "None")", fig: target)
        }
        if isPlayer, let attacker, local(target, 0) <= 0 {
            dieMethod(attacker, endTask: true)      // 1090:0e36: the player's killer gets the die method too (AI suspended, hold++)
        }
        if local(target, 0) > 0 {
            if let zname {
                if !raise(target, "GOT_HIT_\(zname)_\(tmotion)") { _ = raise(target, "GOT_HIT_\(zname)") }
            }
            _ = raise(target, "GOT_HIT")
            for limit in [75, 50, 25] where prev > limit - 1 && local(target, 0) < limit {     // crossing below a quarter threshold
                _ = raise(target, "MY_HPS_\(limit)")
                if isPlayer, let attacker { _ = raise(attacker, "PLAYERS_HPS_\(limit)") }
            }
            if heavy {
                if isPlayer { if let attacker { _ = raise(attacker, "PLAYER_SUPER_RECOILED") } } else { _ = raise(target, "SUPER_RECOIL") }
            }
            if isPlayer, let attacker {
                _ = raise(attacker, "HIT_PLAYER")
                _ = raise(attacker, "HIT_PLAYER_\(amotion)")
            }
            if cancel && local(target, 3) == 0, let zname {        // a motion task still running (an unfinished DIE) blocks the recoil
                let kind = heavy ? "SUPER_REC" : "RECOIL"
                let name = [ "\(kind)_\(zname)", zname.hasSuffix("L") ? "RECOIL_TL" : "RECOIL_TR"].first { target.assets.motion($0) != nil }
                if let name, target.go == nil {         // ASSUMPTION: a walking figure (GO) is not interrupted
                    target.manualControl = false
                    target.confront = nil                   // FUN_1098_0789(target, 1, 0) -> FUN_1088_3229: the hit ends its class 0x109 tasks, turn_to_enemy too
                    target.setMotion(name, loop: false)     // plays once (cmdMotion would loop the turning RECOIL_*)
                    target.taskName = name                  // +0x15f: what the motion gate (FUN_1098_12bd) refuses a script's MOTION for, as a taunt's tail asks
                    target.recoilId = target.motId
                    setLocal(target, 3, 1)
                }
            }
        }
        // <TYPE>_WOUNDS runs for a living and a dead target alike; a dead one then gets the death method and <INSTANCE>_DEATH
        runFigureBlock(target, "\(target.type.uppercased())_WOUNDS")
        if local(target, 0) <= 0 {
            if isPlayer, let attacker { _ = raise(attacker, "KILLED_PLAYER") }
            dieMethod(target, endTask: true)
            target.invulnerable = true
            runFigureBlock(target, "\(target.name.uppercased())_DEATH")
        }
        record()
    }
}
