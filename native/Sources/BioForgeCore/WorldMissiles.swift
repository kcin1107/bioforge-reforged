// Missiles: the script function FIRE and the engine's missile task (class 0x10c, ctor FUN_10e0_0440, tick FUN_10e0_0cbc). Port of
// re/interp/missiles.py (the oracle, which also holds the decoded rules and the ASSUMPTIONs); MAKEMISSILE will reuse spawnMissile.
//
// A missile is two engine objects: the task (kernel handle, range, spin, hit logic) and its figure, an ordinary Item (mesh
// ITEMS/<TYPE>.IFF; ZIPPY and TOSS have none and are invisible). The port keeps one record, `Missile: Item`, inserted in `World.items`
// under a unique key so that CURITEM can name it in the hit scripts, and a native VM process as the handle.
//
// Per 30 Hz frame the world update moves the item list (Item::Update 1078:1490 -> Move 1078:08f6, `moveMissiles`) before the figures;
// the task tick (`tickMissiles`) comes later with the scripts. A move is sub-stepped like the figure mover (FUN_10a0_22e1, span = the
// EXTENT box); every sub-step tests the PHYS volumes (score > 0) and the figures' +0x65 bounds (the first overlap is the hit object).
// The tick: hit check (FUN_10e0_0961) unless flag 0x02 (CARRY), orientation, range -= |step|; at range < 0 or zero velocity the block
// `<TYPE>_HIT_WALL` runs and the missile is destroyed (vtable +8, FUN_10e0_1239). FIRE returns the handle; `SUSPENDWHILE FIRE ...`
// waits for the missile to die. CARRY attaches an object to the missile (FUN_1138_05ff).
import Foundation

/// What a missile carries (FIRE ... CARRY): a figure (flag-driven attachment, `Figure.carrier`) or an item (held by the missile).
enum Carried {
    case figure(Figure), item(Item)
}

/// A FIRE / MAKEMISSILE shot: the engine's missile task and its figure in one record (world.py `Missile`). `type` is the missile type
/// (the script block <TYPE> and ITEMS/<TYPE>.IFF); `pos` is integer world units; velocity / step are s32 per tick (+0xc6.. / +0xd2..).
final class Missile: Item {
    /// The orientation (+0x110) in 24.8; `matrix` is the drawing form (rows are the local axes, row 1 backward).
    private(set) var rows: [[Int]] = []
    /// +0x48: remaining range, units
    var dist = 0
    /// +0x4c..: degrees per tick about X, Y, Z
    var spin = [0, 0, 0]
    /// +0x44 (CURFIG for MAKEMISSILE, none for FIRE)
    var ownerFig: Figure?
    /// the VM handle (+0x38) and the looped _<TYPE>_TRAVEL handle (+0x40)
    var handle = 0, sound = 0
    var carried: Carried?
    /// +0x135: the figure the last move overlapped
    var hit: Figure?
    var dead = false

    init(name: String, missileType: String) {
        super.init(name: name, type: missileType, owner: nil)
        gravity = false
        pos = V3(0, 0, 0)
        setRows([[256, 0, 0], [0, 256, 0], [0, 0, 256]])
    }

    func setRows(_ r: [[Int]]) {
        rows = r
        matrix = Mat3(r: r.map { V3(Double($0[0]) / 256, Double($0[1]) / 256, Double($0[2]) / 256) })
    }
}

enum MissileRules {
    /// 0xFF676981: the range of a missile that was made inside geometry (it expires on its first tick)
    static let noRange = -9_999_999
    /// owner push-out iterations (the engine loop has no cap)
    static let pushOutCap = 1000

    /// A direction as a 24.8 vector (256 = 1.0). ASSUMPTION: float arithmetic rounded to the nearest integer; the engine's FUN_1208_09ff
    /// (FUN_1208_0b86 shifts, FUN_1208_002c length, FUN_1210_0c24 divides) is not ported. Both ports use the same form.
    static func unit24(_ v: [Int]) -> [Int] {
        let n = v.reduce(0.0) { $0 + Double($1) * Double($1) }.squareRoot()
        return n == 0 ? [0, 0, 0] : v.map { Int((Double(256 * $0) / n).rounded(.toNearestOrEven)) }
    }

    /// FUN_1208_0154: a x b with every product through the 24.8 multiply (0c42).
    static func cross24(_ a: [Int], _ b: [Int]) -> [Int] {
        func fm(_ x: Int, _ y: Int) -> Int { (x * y) >> 8 }
        return [fm(a[1], b[2]) - fm(a[2], b[1]), fm(a[2], b[0]) - fm(a[0], b[2]), fm(a[0], b[1]) - fm(a[1], b[0])]
    }

    /// The tumbling orientation (tick FUN_10e0_0cbc): every row turned by a degrees about X, then b about Y, then c about Z.
    /// ASSUMPTION: world axes (the axis frame of FUN_1208_2548 / 2858 / 2b64 is not decoded); drawing only.
    static func spinRows(_ rows: [[Int]], _ spin: [Int]) -> [[Int]] {
        let ra = Double(spin[0]) * (Double.pi / 180), rb = Double(spin[1]) * (Double.pi / 180), rc = Double(spin[2]) * (Double.pi / 180)
        return rows.map { r in
            var x = Double(r[0]), y = Double(r[1]), z = Double(r[2])
            (y, z) = (y * cos(ra) - z * sin(ra), y * sin(ra) + z * cos(ra))
            (x, z) = (x * cos(rb) + z * sin(rb), z * cos(rb) - x * sin(rb))
            (x, y) = (x * cos(rc) - y * sin(rc), x * sin(rc) + y * cos(rc))
            return [Int(x.rounded(.toNearestOrEven)), Int(y.rounded(.toNearestOrEven)), Int(z.rounded(.toNearestOrEven))]
        }
    }
}

extension World {
    // MARK: FIRE

    /// The `<object>` argument of the position functions (FUN_10c0_16a8): CURFIG, CURITEM or a figure / floor item name.
    func scriptObject(_ proc: ScriptProcess, _ ref: ScriptValue) -> (fig: Figure?, item: Item?) {
        let sel = pyStr(ref).uppercased()
        let fig = figure(sel == "CURFIG" ? proc.curFig : sel)
        if sel == "CURITEM" || (fig == nil && itemByType(sel) != nil) { return (nil, sel == "CURITEM" ? items[proc.curItem ?? ""] : itemByType(sel)) }
        return (fig, nil)
    }

    /// The world position FUN_10c0_152f's object gives through vtable +0x50: a WAYP's position, the centre of a PHYS / IMAG box (per axis
    /// trunc((lo + hi) / 2), as boxDistance), a figure's or floor item's position (CURFIG / CURITEM / a name). ASSUMPTION: waypoints
    /// before boxes before figures and items (the lookup order is not decoded).
    func scriptPoint(_ proc: ScriptProcess, _ ref: ScriptValue) -> [Int]? {
        let name = pyStr(ref).uppercased()
        func rounded(_ p: V3) -> [Int] { [p.x, p.y, p.z].map { Int($0.rounded(.toNearestOrEven)) } }
        if let p = data.waypoints[name] { return rounded(p) }
        if let b = data.phys.first(where: { $0.name.uppercased() == name }) { return (0..<3).map { fixDiv(Int(b.lo[$0]) + Int(b.hi[$0]), 0x200) } }
        if let t = data.triggers.first(where: { $0.name == name }) { return (0..<3).map { fixDiv(t.lo[$0] + t.hi[$0], 0x200) } }
        let obj = scriptObject(proc, .str(name))
        guard let p = objectPos(obj) else { return nil }
        return rounded(p)
    }

    /// FIRE (10d8:18a0): `<type> <from> <to> <speed> <a> <b> <c> [CARRY <obj>]` or `<type> <from> AT <x> <y> <z> <speed> <a> <b> <c>
    /// [CARRY <obj>]`. The missile flies the straight line from the start to the destination at `speed` m/s (speed * 2048 units a
    /// second) and has range = the approximate length of that line (FUN_1210_0f9b), so it dies at the destination. The matrix rows are
    /// {U, D, R}: D the travel direction, R = normalised (start position x D) (an original quirk: the raw start POSITION is the first
    /// operand), U = D x R, both negated when R.z < 0. AT coordinates are script integers (<< 8). Missing names or an unknown object
    /// are errors (-> 0). -> the missile's handle.
    func cmdFire(_ proc: ScriptProcess, _ args: [ScriptValue]) -> Int {
        let words = args.prefix(3).map { v -> String in if case .str(let s) = v { return s }; return "" }
        if args.count < 3 || words.contains("") {
            warn("FIRE: needs a type, a start and a destination")
            return 0
        }
        let mtype = words[0].uppercased(), at = words[2].uppercased() == "AT"
        var nums = args.dropFirst(3).compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        nums += Array(repeating: 0, count: max(0, (at ? 7 : 4) - nums.count))
        let start = scriptPoint(proc, args[1])
        let end = at ? nil : scriptPoint(proc, args[2])
        guard let start, at || end != nil else {
            warn("FIRE \(args.prefix(3).map(pyStr).joined(separator: " ")): no such object")
            return 0
        }
        let dest: [Int], speed: Int, spin: [Int]
        if at { dest = nums.prefix(3).map { $0 << 8 }; speed = nums[3]; spin = Array(nums[4..<7]) }
        else { dest = end!; speed = nums[0]; spin = Array(nums[1..<4]) }
        let delta = (0..<3).map { dest[$0] - start[$0] }
        let d = MissileRules.unit24(delta)
        var r = MissileRules.unit24(MissileRules.cross24(start, d))
        var u = MissileRules.cross24(d, r)
        if r[2] < 0 { r = r.map { -$0 }; u = u.map { -$0 } }
        let m = spawnMissile(mtype, start, [u, d, r], wrap32((speed * 80 / 10) << 8), approxLength(delta[0], delta[1], delta[2]), spin)
        let after = args.dropFirst(3).map { v -> String in if case .str(let s) = v { return s.uppercased() }; return "" }
        if let k = after.firstIndex(of: "CARRY") {
            m.noCollide = true                          // *(figure + 0x34) |= 2, after the constructor (the spawn test ran without it)
            if args.count > 3 + k + 1 {
                let obj = scriptObject(proc, args[3 + k + 1])
                if let f = obj.fig { attachCarried(m, .figure(f)) } else if let i = obj.item { attachCarried(m, .item(i)) }
            }
        }
        return m.handle
    }

    // MARK: MAKEMISSILE

    /// The item's world position and matrix as the renderer places it (itemCels): a floor item's own, a held item's handPose turned by
    /// -heading about its holder.
    func itemWorldPose(_ item: Item) -> (pos: V3, m: Mat3)? {
        if item.owner == nil {
            guard let p = item.pos, let m = item.matrix else { return nil }
            return (p, m)
        }
        guard let fig = figures[item.owner!], let fp = fig.pos, let pose = handPose(fig, item) else { return nil }
        return (Scene.place([pose.origin], at: fp, yaw: -fig.heading)[0], Mat3(r: Scene.place(pose.m.r, at: .zero, yaw: -fig.heading)))
    }

    /// MAKEMISSILE (10d8:3030): `<TYPE> [<LIMB>] <speed> <range> (<a>,<b>,<c>)`; speed and range are metres (n * 2048 units, as FIRE).
    /// See missiles.py `cmd_makemissile`. -> the missile's handle (0: no shot, silently).
    func cmdMakeMissile(_ proc: ScriptProcess, _ args: [ScriptValue]) -> Int {
        let flat = args.flatMap { v -> [ScriptValue] in if case .list(let l) = v { return l }; return [v] }
        let words = flat.compactMap { v -> String? in if case .str(let s) = v { return s }; return nil }
        var nums = flat.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        nums += Array(repeating: 0, count: max(0, 5 - nums.count))
        if words.isEmpty { warn("MAKEMISSILE: needs a missile type"); return 0 }
        let fig = figure(proc.curFig)
        let item = proc.curItem.flatMap { items[$0] }
        var pos: [Int], rows: [[Int]]
        func r8(_ x: Double) -> Int { Int(x.rounded(.toNearestOrEven)) }
        if let item {
            guard let pose = itemWorldPose(item) else { return 0 }
            pos = [pose.pos.x, pose.pos.y, pose.pos.z].map(r8)
            rows = pose.m.r.map { [-r8(256 * $0.x), -r8(256 * $0.y), -r8(256 * $0.z)] }
        } else {
            guard let fig, let fp = fig.pos, words.count >= 2 else { return 0 }
            let skeleton = fig.assets.assets.skeleton
            guard let i = skeleton.limbs.firstIndex(where: { $0.name.uppercased() == words[1].uppercased() }) else { return 0 }
            let frame = fig.frames.flatMap { $0.isEmpty ? nil : $0[min(fig.idx, $0.count - 1)] }      // a type without motions keeps its rest pose
            let (start, rot) = skeleton.solve(frame)
            let end = start[i] + rot[i].r[1] * Double(skeleton.limbs[i].length)
            rows = Scene.place(rot[i].r, at: .zero, yaw: -fig.heading).map { [r8(256 * $0.x), r8(256 * $0.y), r8(256 * $0.z)] }
            let tip = Scene.place([end], at: fp, yaw: -fig.heading)[0]
            pos = (0..<3).map { r8([tip.x, tip.y, tip.z][$0]) - fixMul(rows[1][$0], skeleton.limbs[i].length) }
        }
        func units(_ n: Int) -> Int { wrap32((n * 80 / 10) << 8) }
        return spawnMissile(words[0].uppercased(), pos, rows, units(nums[0]), units(nums[1]), Array(nums[2..<5]), owner: fig).handle
    }

    // MARK: the missile task

    /// The constructor FUN_10e0_0440. `rows` = the travel matrix {U, D, R} in 24.8 (D, row 1, the travel direction); `speed32` = speed *
    /// 2048 (units a second); `dist` = range in units; `spin` = (a, b, c) degrees a tick about X, Y, Z. The figure is turned 180 degrees
    /// about Z (rows 0 and 1 negated: its row 1 is backward), velocity = row 1 * trunc(speed32 << 8 / 0x1e00) >> 8 per axis. Type
    /// properties come from the script block named <TYPE> (EXTENT in cm: units (cm << 11) / 100, ASSUMPTION for the shift). Plays
    /// `_<TYPE>_FIRE` and starts `_<TYPE>_TRAVEL` (looped, positional) when those samples exist. A missile whose box already overlaps
    /// solid PHYS gets the range -9999999 and no velocity (it expires on its first tick).
    @discardableResult func spawnMissile(_ mtype: String, _ pos: [Int], _ rows: [[Int]], _ speed32: Int, _ dist: Int, _ spin: [Int],
                                         owner: Figure? = nil) -> Missile {
        var key = mtype, n = 2
        while items.contains(key) { key = "\(mtype)_\(n)"; n += 1 }
        let m = Missile(name: key, missileType: mtype)
        items[key] = m
        missileTypeProps(m)
        m.pos = V3(Double(pos[0]), Double(pos[1]), Double(pos[2]))
        m.setRows([rows[0].map { -$0 }, rows[1].map { -$0 }, rows[2]])
        let k = fixDiv(speed32, 0x1e00)
        m.vel = rows[1].map { fixMul($0, k) }
        if let owner, owner.pos != nil {                                // ctor 10e0:0631..06f5: out of the shooter's +0x65 box
            let oh = queryHull(owner)
            var p = ipos(m), cleared = false
            for _ in 0..<MissileRules.pushOutCap {                      // do { pos += row1 (travel, up to 256 units) } while overlap
                p = (0..<3).map { p[$0] + rows[1][$0] }
                let box = missileBox(m, p)
                if !Self.boxesTouch(box.lo, box.hi, oh.lo, oh.hi) { cleared = true; break }
            }
            if !cleared { warn("\(mtype): could not push the missile out of \(owner.name)") }
            m.pos = V3(Double(p[0]), Double(p[1]), Double(p[2]))
        }
        m.dist = dist
        m.spin = spin.map { Int(Int16(truncatingIfNeeded: $0)) }          // a, b, c: low 16 bits
        m.ownerFig = owner
        if let vm { m.handle = vm.nativeHandle("MISSILE") }
        if let fire = soundIndex(.str("_\(mtype)_FIRE")) { playSound(fire) }
        if let travel = soundIndex(.str("_\(mtype)_TRAVEL")) { m.sound = playSound(travel, loop: true, item: m) }
        if !m.noCollide && missileBlocked(m, ipos(m)) {
            m.dist = MissileRules.noRange
            m.vel = [0, 0, 0]
        }
        return m
    }

    /// The type's properties from the script block <TYPE> (1078:0214): bouncy, reflective, gravity, elasticity, EXTENT.
    func missileTypeProps(_ m: Missile) {
        func prop(_ name: String, _ fallback: Int) -> Int { itemProp(m.type, name)?.first.flatMap { Int($0) } ?? fallback }
        m.bouncy = prop("IS_BOUNCY", 0) != 0
        m.reflective = prop("IS_REFLECTIVE", 0) != 0
        m.gravity = prop("HAS_GRAVITY", 1) != 0        // not modelled: no shipped missile has gravity (Item::Update would add it)
        m.elasticity = prop("ELASTICITY", 200)
        if let vals = itemProp(m.type, "EXTENT"), vals.count >= 3 { m.extent = vals.prefix(3).map { hullUnits(Int($0) ?? 0) } }
    }

    private func ipos(_ m: Missile) -> [Int] { [m.pos!.x, m.pos!.y, m.pos!.z].map { Int($0) } }

    func missileBox(_ m: Item, _ p: [Int]) -> (lo: SIMD3<Int>, hi: SIMD3<Int>) {
        (SIMD3(p[0] - m.extent[0], p[1] - m.extent[1], p[2] - m.extent[2]), SIMD3(p[0] + m.extent[0], p[1] + m.extent[1], p[2] + m.extent[2]))
    }

    /// FUN_1058_1a1b for the missile's box at `p`: pos +- EXTENT against the PHYS volumes, score > 0. ASSUMPTION: no PHYS area is selected
    /// (the null-area path, FUN_1058_192f): every PHYS of the level counts.
    func missileBlocked(_ m: Item, _ p: [Int]) -> Bool {
        collisionScore(missileBox(m, p), members: Array(physBoxes().indices)) > 0
    }

    /// FUN_1110_0b29: the first figure (list order) whose +0x65 bounds overlap the missile's box at `p` (inclusive, hidden and unplaced
    /// figures skipped) becomes the hit object (+0x135); the first one found during a move is kept.
    private func missileTouch(_ m: Missile, _ p: [Int]) {
        if m.hit != nil { return }
        let box = missileBox(m, p)
        for fig in figures.values where fig.pos != nil && !fig.hidden {
            let h = queryHull(fig)
            if Self.boxesTouch(box.lo, box.hi, h.lo, h.hi) { m.hit = fig; return }
        }
    }

    /// The item list part of the world update: every missile moves, then places what it carries.
    func moveMissiles() {
        for case let m as Missile in items.values {
            moveMissile(m)
            if m.carried != nil { placeCarried(m) }
        }
    }

    /// Item::Update + Move (1078:1490, 1078:08f6; see the file header). A block stops the missile at the last good sub-step position with
    /// its velocity zeroed, the step scaled by the finished share of the move, unless the block is a rebound: a bouncy missile, or a
    /// reflective one (LASER, BOLTPFD, TNFABOLT) whose collider PHYS has flag byte (record byte 21) & 4, takes the generic rebound
    /// (FUN_1070_1d8f -> 0fa7, itemBlocked) and goes on flying.
    private func moveMissile(_ m: Missile) {
        m.hit = nil
        let start = ipos(m)
        m.step = velocityStep(m.vel)
        let target = (0..<3).map { start[$0] + m.step[$0] }
        if m.noCollide {                                // CARRY: pos := target, no tests at all
            m.pos = V3(Double(target[0]), Double(target[1]), Double(target[2]))
            return
        }
        let spans = m.extent.map { 2 * $0 }, minSpan = spans.min()!
        let n = minSpan > 0 && !(0..<3).allSatisfy({ abs(m.step[$0]) < spans[$0] }) ? moveSteps(m.step[0], m.step[1], m.step[2], minSpan) : 0
        let inc = n > 0 ? (0..<3).map { fixDiv(m.step[$0], n << 8) } : []
        var good = start
        if n > 0 {
            for i in 1...n {
                let cand = (0..<3).map { start[$0] + inc[$0] * i }
                if missileBlocked(m, cand) { return stopMissile(m, start, cand, good, i - 1, n) }
                missileTouch(m, cand)
                good = cand
            }
        }
        if missileBlocked(m, target) { return stopMissile(m, start, target, good, n, n) }
        missileTouch(m, target)
        m.pos = V3(Double(target[0]), Double(target[1]), Double(target[2]))
    }

    private func stopMissile(_ m: Missile, _ start: [Int], _ p: [Int], _ good: [Int], _ done: Int, _ n: Int) {
        itemBlocked(m, start, p, good, stoppedStep: n > 0 ? scaleStep(m.step, done, n) : [0, 0, 0])
    }

    /// The task tick of every missile (vtable +0), after the figures.
    func tickMissiles() {
        for case let m as Missile in items.values where !m.dead { tickMissile(m) }
    }

    /// FUN_10e0_0cbc. Skipped while the range is the spawn-in-geometry sentinel: hit check (not with flag 0x02), orientation, range -=
    /// |step|. Then range < 0 or no velocity ends the missile with <TYPE>_HIT_WALL. ASSUMPTION: the VM processes and the missile tasks
    /// are not interleaved by kernel slot; the missile ticks run after the world update, before the next VM tick.
    private func tickMissile(_ m: Missile) {
        if m.dist != MissileRules.noRange {
            if !m.noCollide && missileHit(m) { return }
            m.setRows(m.spin.contains { $0 != 0 } ? MissileRules.spinRows(m.rows, m.spin) : aimRows(m))
            m.dist -= approxLength(m.step[0], m.step[1], m.step[2])
        }
        if m.dist < 0 || approxLength(m.vel[0], m.vel[1], m.vel[2]) == 0 {
            runMissileBlock(m, "\(m.type)_HIT_WALL", nil)
            destroyMissile(m)
        }
    }

    /// Without spin the figure is re-aimed along its flight: row 1 = -velocity, re-orthonormalised (1208:095b) from row 1 and the old
    /// row 2 (ASSUMPTION for the construction; drawing only). Zero velocity keeps the orientation.
    private func aimRows(_ m: Missile) -> [[Int]] {
        let r1 = MissileRules.unit24(m.vel.map { -$0 })
        let r0 = MissileRules.unit24(MissileRules.cross24(r1, m.rows[2]))
        if !r1.contains(where: { $0 != 0 }) || !r0.contains(where: { $0 != 0 }) { return m.rows }
        return [r0, r1, MissileRules.unit24(MissileRules.cross24(r0, r1))]
    }

    /// FUN_10e0_0961. The hit object (cleared here) is run as `<TYPE>_HIT_<instance>` else `<TYPE>_HIT` with CURFIG = it and CURITEM =
    /// the missile, then the missile is destroyed (-> true). A reflective missile meeting a reflective figure keeps flying with its
    /// speed turned by a random yaw 5..355 degrees and pitch -20..20 (-> false). The figure's flag test (0x08, "removed" in the spec) is
    /// not applied: bit 0x08 is INVULNERABLE in the ports, and killed figures have left `figures`. ASSUMPTION: the speed is the integer
    /// length of the velocity (FUN_1208_002c is not ported) and the new direction is built in floats.
    private func missileHit(_ m: Missile) -> Bool {
        let t = m.hit
        m.hit = nil
        guard let t, figures[t.name] === t, !t.invulnerable else { return false }     // 10e0:0961: +0x34 bit 0x08 returns 0, no HIT and the missile flies on
        if !(m.reflective && prop(t, "IS_REFLECTIVE", 0) != 0) {
            let block = "\(m.type)_HIT_\(t.name)"
            runMissileBlock(m, vm?.blocks[block] != nil ? block : "\(m.type)_HIT", t)
            destroyMissile(m)
            return true
        }
        let speed = isqrt(m.vel.reduce(0) { $0 + $1 * $1 })
        let d = MissileRules.unit24([m.vel[0], m.vel[1], 0])
        let yaw = Double(rng.randint(5, 355)) * (Double.pi / 180), pitch = Double(rng.randint(0, 40) - 20) * (Double.pi / 180)
        let x = Double(d[0]) * cos(yaw) - Double(d[1]) * sin(yaw), y = Double(d[0]) * sin(yaw) + Double(d[1]) * cos(yaw)
        let row1 = [Int((x * cos(pitch)).rounded(.toNearestOrEven)), Int((y * cos(pitch)).rounded(.toNearestOrEven)),
                    Int((256 * sin(pitch)).rounded(.toNearestOrEven))]
        m.vel = row1.map { fixMul($0, speed) }
        return false
    }

    /// FUN_1120_0035: start the script block if it exists, CURFIG = `fig` (or none), CURITEM = the missile; its first slice runs at once.
    private func runMissileBlock(_ m: Missile, _ block: String, _ fig: Figure?) {
        guard let vm, vm.blocks[block] != nil else { return }
        vm.spawn(block, ctx: ScriptContext(curFig: fig?.name, curItem: m.key, owner: "level"))
    }

    /// Vtable +8 (FUN_10e0_1239): the travel sound stops, what the missile carries is released where it is (SetPos: velocity zeroed),
    /// the figure leaves the item list, and the handle dies, waking the SUSPENDWHILE waiters. They only become
    /// ready (1238:077f) and run in the next walk, so they see the final state.
    /// LOADLEVEL's first act (FUN_10d0_4d46, 10d0.c:4280-4287): every live missile task, in creation order, takes the hit-then-destroy entry
    /// (vtable +0xc, FUN_10e0_11aa). A stored hit target runs <TYPE>_HIT_<inst> / <TYPE>_HIT and the missile is destroyed (missileHit);
    /// otherwise the missile is destroyed with no <TYPE>_HIT_WALL: the travel sound stops, a rider is released where the missile is, the item
    /// is removed (so the level's IFF never keeps it) and the handle finishes. See missiles.py `end_missiles_for_level_change`.
    func endMissilesForLevelChange() {
        for case let m as Missile in items.values where !m.dead {
            if !missileHit(m) { destroyMissile(m) }
        }
    }

    func destroyMissile(_ m: Missile) {
        if m.dead { return }
        m.dead = true
        if m.sound != 0 { stopSound(m.sound) }
        if m.carried != nil { detachCarried(m) }
        if items[m.key] === m { items[m.key] = nil }
        killItemReferents(m)
        if let vm, let p = vm.process(m.handle) { vm.finish(p) }
    }

    // MARK: CARRY

    /// FUN_1138_05ff: `obj` (a figure or item) is attached to the missile figure (+0x2c). ASSUMPTION: its pose is the missile's origin
    /// (no ON_<CARRIER> property exists for the shipped carriers, and the limb formula FUN_1038_035b for a limbless carrier is not
    /// decoded). An attached figure skips its own move, gravity, grounding and pushes (FUN_1088_39ef) but keeps animating; an item is
    /// held by the missile (owner = its key) and is not a floor item meanwhile.
    private func attachCarried(_ m: Missile, _ obj: Carried) {
        m.carried = obj
        switch obj {
        case .figure(let f): f.carrier = m.name
        case .item(let i): i.owner = m.name; i.slot = "CARRIED"
        }
    }

    /// FUN_1138_05ff / FUN_1088_5c19 with the missile as the carrier "limb": the carried object's own type property `ON_<MISSILE TYPE>`
    /// (figures: FIGURES.scr, `(I,J,K) LENGTH (X,Y,Z)` positional; items: ITEMS.scr, `(0I,0J,0K) 0LENGTH (0X,0Y,0Z)`; cm and degrees)
    /// gives origin = missile origin + offset in the missile's axes + LENGTH along the turned row 1, and the matrix the missile's
    /// rotated by the angles (as handPose). ASSUMPTION: a limbless carrier uses its origin and orientation. No property: the
    /// missile's own pose. See missiles.py `carry_pose`.
    private func carryPose(_ m: Missile, _ c: Carried) -> (origin: V3, m: Mat3) {
        let name = "ON_" + m.type
        var vals: [String] = []
        switch c {
        case .figure(let f):
            let props = resources.figureProps
            let v = props[f.name.uppercased()]?[name] ?? []
            vals = (v.isEmpty ? props[f.type.uppercased()]?[name] ?? [] : v).map(pyStr)
        case .item(let i): vals = itemProp(i.type, name) ?? []
        }
        var a: [String: Int]
        if vals.count == 7, vals.allSatisfy({ Int($0) != nil }) { a = Dictionary(uniqueKeysWithValues: zip(["I", "J", "K", "LENGTH", "X", "Y", "Z"], vals.map { Int($0)! })) }
        else { a = ItemRules.parseNumbers(vals) }
        let ang = SIMD3<Int>((a["I"] ?? 0) * 32 / 45, (a["J"] ?? 0) * 32 / 45, (a["K"] ?? 0) * 32 / 45)
        let off = V3(Double(ItemRules.attachUnits(a["X"] ?? 0)), Double(ItemRules.attachUnits(a["Y"] ?? 0)), Double(ItemRules.attachUnits(a["Z"] ?? 0)))
        let rot = m.matrix!.rotated(ang)
        return (m.pos! + m.matrix!.apply(off) + rot.r[1] * Double(ItemRules.attachUnits(a["LENGTH"] ?? 0)), rot)
    }

    private func placeCarried(_ m: Missile) {
        guard let c = m.carried else { return }
        let pose = carryPose(m, c)
        switch c {
        case .figure(let f): f.pos = pose.origin; f.prevPos = pose.origin; f.lastGood = pose.origin
        case .item(let i): i.pos = pose.origin; i.matrix = pose.m
        }
    }

    /// FUN_1078:07c3 -> SetPos at the current position (vtable +0x58, velocity zeroed).
    private func detachCarried(_ m: Missile) {
        let c = m.carried
        m.carried = nil
        switch c {
        case .figure(let f)?:
            f.carrier = nil
            if let p = f.pos { setPos(f, p, raw: true) }
        case .item(let i)?: i.owner = nil; i.slot = nil
        case nil: break
        }
    }
}
