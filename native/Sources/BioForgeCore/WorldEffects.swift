// Effects: the script statements MAKEFLATOBJECT (10d0:52ff), EXPLODE (10d0:2841) and THROWCURITEM (10d0:84d0), and the free-item physics
// THROWCURITEM needs (Item::Update 1078:1490 for items that are not missiles). Port of re/interp/effects.py (the oracle, which also holds
// the decoded rules and the ASSUMPTIONs).
//
// A flat object (vtable DS:237b, ctor 1080:0afa, list [1d3d]) is an unscaled room-CAM sprite sequence: ROOMS/<cam>.CAM entry <seq>, shown at
// a world point (captured when it was made) or a screen position, depth-sorted with the room's cels. Frame 0 is a 320x200 blank. With n > 2
// frames the object starts at frame 1 and advances before each draw (so frame 1 is never shown) until frame >= n; with n <= 2 it stays until
// DELETE. ASSUMPTION: one advance per world tick (30 Hz). EXPLODE hides the figure and what it holds and waits 300 / 2 = 150 ticks unless
// CONTINUE; the shrapnel the engine spawns is NOT PORTED (visual only). THROWCURITEM releases the held item at its world pose and adds a
// velocity; a free item with a velocity then moves through the missile PHYS sub-step mover with gravity and a bounce.
import Foundation

/// What VELOCITYX / LEAP / SETVELOCITY / STOPVELOCITY address: a figure or an item.
protocol VelocityObject: AnyObject {
    var vx: Int { get set }
    var vy: Int { get set }
    var vz: Int { get set }
    var step: [Int] { get set }
    var pos: V3? { get }
}
extension Figure: VelocityObject {}
extension Item: VelocityObject {}

final class FlatObject {
    let cam: String, frames: [CAMFrame]
    /// world [x, y, z], or the screen position and depth
    let point: [Int]?, screen: (x: Int, y: Int, depth: Int)?
    var frame: Int
    let w: Int, h: Int

    init(cam: String, frames: [CAMFrame], point: [Int]?, screen: (x: Int, y: Int, depth: Int)?) {
        self.cam = cam; self.frames = frames; self.point = point; self.screen = screen
        frame = frames.count > 2 ? 1 : frames.count - 1
        w = frames.dropFirst().map(\.width).max() ?? 0          // W, H: the largest frame over 1..n-1
        h = frames.dropFirst().map(\.height).max() ?? 0
    }
}

/// A piece of shrapnel (class DS:4d3a, ctor 10f8:124c, list [1d31]): 1..5 faces of the exploding figure's posed mesh as a rigid body. `rel` are
/// its vertices relative to the mean face centre (`pos`), `mesh` the face subset indexed into `rel`; `end` the 60 Hz clock it dies at.
final class Fragment {
    let mesh: EORMesh, rel: [V3]
    var pos: [Int], vel: [Int], end: Int, angle = 0
    let area: Int?
    init(mesh: EORMesh, rel: [V3], pos: [Int], vel: [Int], end: Int, area: Int?) {
        self.mesh = mesh; self.rel = rel; self.pos = pos; self.vel = vel; self.end = end; self.area = area
    }
}

extension World {
    // MARK: MAKEFLATOBJECT

    /// `MAKEFLATOBJECT ( cam, seq [, obj] )` or `( cam, seq, x, y, depth )`. seq DELETE removes every flat object of that cam. The object form
    /// takes the reference point NOW (scriptPoint) and never follows the object; a missing object does nothing. The screen form is x, y in
    /// 320x200 pixels and the s32 camera depth. A missing CAM or entry is a warning. Never blocks.
    func cmdMakeFlatObject(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        let flat = args.flatMap { v -> [ScriptValue] in if case .list(let l) = v { return l }; return [v] }
        let words = flat.compactMap { v -> String? in if case .str(let s) = v { return s.uppercased() }; return nil }
        var nums = flat.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        guard words.count >= 2 else { warn("MAKEFLATOBJECT: needs a CAM and a sequence"); return }
        let cam = words[0], seq = words[1]
        if seq == "DELETE" { flatObjects.removeAll { $0.cam == cam }; return }
        var point: [Int]?, screen: (x: Int, y: Int, depth: Int)?
        if words.count > 2 {
            guard let p = scriptPoint(proc, .str(words[2])) else { return }
            point = p
        } else {
            nums += Array(repeating: 0, count: max(0, 3 - nums.count))
            screen = (nums[0], nums[1], nums[2])
        }
        guard let frames = resources.compositor(cam)?.frames(named: seq), !frames.isEmpty else {
            warn("MAKEFLATOBJECT \(cam) \(seq): no such sequence")
            return
        }
        flatObjects.append(FlatObject(cam: cam, frames: frames, point: point, screen: screen))
    }

    /// Per frame: n > 2 advances (pre-increment); an object past its last frame is finished and removed.
    func tickFlatObjects() {
        for f in flatObjects where f.frames.count > 2 { f.frame += 1 }
        flatObjects.removeAll { $0.frame >= $0.frames.count }
    }

    /// The cels for the compositor: top-left = (x - W / 2 - hotx, y - H / 2 - hoty) of the frame's own hot spot. The world form projects the
    /// point through `camera` (behind it: skipped), depth = camera depth. ASSUMPTION: the room palette applies, the CAM's own is ignored.
    func flatCels(_ camera: Camera) -> [FlatCel] {
        var out: [FlatCel] = []
        for f in flatObjects {
            let frame = f.frames[f.frame]
            let x: Int, y: Int, depth: Double
            if let p = f.point {
                let s = Scene.project(V3(Double(p[0]), Double(p[1]), Double(p[2])), camera)
                guard s.x.isFinite, s.y.isFinite, s.z.isFinite, s.z > 0, abs(s.x) < 1e9, abs(s.y) < 1e9 else { continue }
                (x, y, depth) = (Int(s.x), Int(s.y), s.z)
            } else {
                (x, y, depth) = (f.screen!.x, f.screen!.y, Double(f.screen!.depth))
            }
            out.append(FlatCel(depth: depth, frame: frame, x: x - f.w / 2, y: y - f.h / 2))
        }
        return out
    }

    // MARK: EXPLODE

    /// `EXPLODE <obj> [CONTINUE]`: the object must be the current figure (else a warning, error 0x4c, no wait). t = 300; CONTINUE sets -1, any
    /// other second word is a warning (error 0x66) that keeps t. t >= 0 blocks the process for t / 2 = 150 ticks (the WAIT object). The figure
    /// and the items it holds are hidden (it may be gone already: KILL only defers the engine's destruction, the port drops the figure at once,
    /// so the ref is matched against the current figure's name).
    func cmdExplode(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        let words = args.compactMap { v -> String? in if case .str(let s) = v { return s.uppercased() }; return nil }
        let ref = words.first ?? "CURFIG"
        guard let curName = proc.curFig, !curName.isEmpty, ref == "CURFIG" || resolve(ref) == resolve(curName) else {
            warn("EXPLODE \(ref): not the current figure (error 0x4c)")
            return
        }
        let cur = resolve(curName)
        var t = 300
        if words.count > 1 && !words[1].isEmpty {
            if words[1] == "CONTINUE" { t = -1 } else { warn("EXPLODE \(words[1]): unknown option (error 0x66)") }
        }
        if let fig = figures[cur] ?? deadFigures[cur], !fig.exploded {
            fig.exploded = true
            for it in items.values where it.owner == fig.name { it.hidden = true }
            spawnShrapnel(fig)
        }
        if t >= 0, let vm {
            let until = vm.tick + t / 2
            proc.waitPred = { [weak self] in (self?.vm?.tick ?? until) >= until }
        }
    }

    // MARK: shrapnel

    /// 10f8:124c's speed [4d96] = 220 through (a << 11) / 100: the length of a fragment's velocity; 10f8:19ea's gravity (0x1e00 * ([83a0] / 60)) >> 8
    /// at 30 fps, no cap; the spin in degrees per frame about the local X axis (10f8:191a, INFERRED unit).
    static let shrapnelSpeed = (220 << 11) / 100, fragmentGravity = 240, fragmentSpin = 15

    /// 10f8:1ea2 (called by 10f8:1f8a): N faces of the figure's mesh (INFERRED: its face count); for first = 0, 10, 20 ... while first < N - 10 a
    /// fragment takes faces first .. first + n - 1, n = 1, 2, 3, 4, 5, 1 ... The ctor (10f8:124c) puts it at the mean of the faces' centres of the
    /// posed mesh (world orientation, as it is at this moment: the dying pose; the port keeps a killed figure's object for this) and draws four
    /// values from the shared LCG that script RANDOM uses (`rng`): vx = R(0, 512) - 256, vy = R(0, 514) - 257, vz = R(0, 516) - 258, the vector
    /// normalised to length 256 ((c << 8) / len) and scaled by 4505 (a * b >> 8), then the life, clock60 + 60 * (5 - n) + R % 60. The area box
    /// (fig+0x35 -> +0x16) bounds it. ASSUMPTIONS: the faces taken are all polygons (the engine's face types 0 and 4 are not told apart), the
    /// figure's own orientation is kept (the look-at frame 10f8:0efe is not applied). See effects.py `spawn_shrapnel`.
    func spawnShrapnel(_ fig: Figure) {
        guard fig.pos != nil, fig.frames != nil, let verts = posed(fig) else { return }
        let mesh = fig.assets.assets.mesh
        var first = 0, n = 1
        while first < mesh.polys.count - 10 {
            let polys = Array(mesh.polys[first..<min(first + n, mesh.polys.count)])
            let centres = polys.map { poly in poly.vi.reduce(V3(0, 0, 0)) { $0 + verts[$1] } / Double(poly.vi.count) }
            let mean = centres.reduce(V3(0, 0, 0), +) / Double(centres.count)
            let used = Array(Set(polys.flatMap(\.vi))).sorted()
            var index: [Int: Int] = [:]
            for (k, v) in used.enumerated() { index[v] = k }
            let pieces = polys.map { EORPoly(kind: $0.kind, color: $0.color, vi: $0.vi.map { index[$0]! }, tex: $0.tex, uv: $0.uv) }
            let rel = used.map { verts[$0] - mean }
            var v = [rng.randint(0, 512) - 256, rng.randint(0, 514) - 257, rng.randint(0, 516) - 258]
            let length = Double(v.reduce(0) { $0 + $1 * $1 }).squareRoot()
            if length != 0 { v = v.map { Int(Double($0 << 8) / length) } }
            v = v.map { ($0 * Self.shrapnelSpeed) >> 8 }
            let end = gameTick * 2 + 60 * (5 - n) + rng.randint(0, 59)
            fragments.append(Fragment(mesh: EORMesh(piecesOf: mesh, polys: pieces, verts: rel), rel: rel,
                                      pos: [Int(mean.x.rounded(.toNearestOrEven)), Int(mean.y.rounded(.toNearestOrEven)), Int(mean.z.rounded(.toNearestOrEven))],
                                      vel: v, end: end, area: fig.area))
            first += 10
            n = n == 5 ? 1 : n + 1
        }
    }

    /// 10f8:19ea, per frame: a fragment whose `end` was cleared is deleted; else it moves v * 25 >> 8 (SetPos 10f8:1b0c: on each axis a new
    /// coordinate not strictly inside its area box keeps the old one and negates that velocity component; z first scales vz by 230 / 256 when it
    /// is below -0x400, and `_METAL_HITS_<PHYS name>` plays), dies at the next update once the clock passes `end`, spins 15 degrees about X and
    /// falls (vz -= 240, no cap). See effects.py `tick_fragments`.
    func tickFragments() {
        let clock = gameTick * 2
        fragments.removeAll { $0.end == 0 }
        for f in fragments {
            let box = f.area.flatMap { $0 < data.phys.count ? data.phys[$0] : nil }
            var hit = false
            for k in 0..<3 {
                let new = f.pos[k] + ((f.vel[k] * 25) >> 8)
                if let box, !(Int(box.lo[k]) < new && new < Int(box.hi[k])) {
                    if k == 2 && f.vel[2] < -0x400 { f.vel[2] = (f.vel[2] * 230) >> 8 }
                    f.vel[k] = -f.vel[k]
                    hit = true
                } else {
                    f.pos[k] = new
                }
            }
            if hit, let box, case let idx = ambientId("_METAL_HITS_\(box.name)"), idx >= 0 {      // 10f8:1b0c formats it through 1118:0044
                playSound(idx, volume: positionalVolume(at: V3(Double(f.pos[0]), Double(f.pos[1]), Double(f.pos[2]))))      // 1030:04db at the fragment
            }
            if clock > f.end { f.end = 0 }
            f.angle += Self.fragmentSpin
            f.vel[2] -= Self.fragmentGravity
        }
    }

    /// The shrapnel for the compositor (drawn like a figure's polygons; the compositor sorts by depth). A fragment with a vertex behind the
    /// camera is skipped. Shrapnel carries no ANIMATE state (frame 0).
    func fragmentFigures(_ camera: Camera) -> [DrawFigure] {
        fragments.compactMap { f in
            let a = Double(f.angle) * Double.pi / 180, c = cos(a), s = sin(a)
            let at = V3(Double(f.pos[0]), Double(f.pos[1]), Double(f.pos[2]))
            let v = f.rel.map { V3($0.x, $0.y * c - $0.z * s, $0.y * s + $0.z * c) + at }
            guard v.allSatisfy({ Scene.project($0, camera).z > Self.nearDepth }) else { return nil }
            return DrawFigure(name: "SHRAPNEL", mesh: f.mesh, world: v)
        }
    }

    // MARK: THROWCURITEM

    /// `THROWCURITEM <pitch degrees> <speed>`: needs CURFIG (error 0x4d) and CURITEM (0x62). The item leaves its holder and keeps its current
    /// world pose (itemWorldPose, rounded to whole units); velocity += row 1 * k of CURFIG's orientation turned about X by the pitch,
    /// k = trunc((speed << 11) / 100) (as LEAP: row 1 is backward, so a negative speed throws forward).
    func cmdThrowCurItem(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        guard let fig = figure(proc.curFig) else { warn("THROWCURITEM: no current figure (error 0x4d)"); return }
        guard let item = items[proc.curItem ?? ""] else { warn("THROWCURITEM: no current item (error 0x62)"); return }
        var nums = args.flatMap { v -> [ScriptValue] in if case .list(let l) = v { return l }; return [v] }
            .compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        nums += Array(repeating: 0, count: max(0, 2 - nums.count))
        guard let pose = itemWorldPose(item) else { return }
        item.owner = nil; item.slot = nil
        item.pos = V3(pose.pos.x.rounded(.toNearestOrEven), pose.pos.y.rounded(.toNearestOrEven), pose.pos.z.rounded(.toNearestOrEven))
        item.matrix = pose.m
        loadItemPhysics(item)
        var m = orientation(fig)
        addLeap(item, &m, nums[0], nums[1])
    }

    // MARK: free items

    /// The type's HAS_GRAVITY / IS_BOUNCY / IS_REFLECTIVE / ELASTICITY / EXTENT (as spawnMissile), read once; missiles set theirs.
    func loadItemPhysics(_ it: Item) {
        if it.physicsLoaded || it is Missile { return }
        it.physicsLoaded = true
        func prop(_ name: String, _ fallback: Int) -> Int { itemProp(it.type, name)?.first.flatMap { Int($0) } ?? fallback }
        it.bouncy = prop("IS_BOUNCY", 0) != 0
        it.reflective = prop("IS_REFLECTIVE", 0) != 0
        it.gravity = prop("HAS_GRAVITY", 1) != 0
        it.elasticity = prop("ELASTICITY", 200)
        if let vals = itemProp(it.type, "EXTENT"), vals.count >= 3 { it.extent = vals.prefix(3).map { hullUnits(Int($0) ?? 0) } }
    }

    /// The item list part of the world update for the items that are not missiles (those move in moveMissiles): only free items with a
    /// non-zero velocity move.
    func moveFreeItems() {
        for it in items.values where !(it is Missile) && it.owner == nil && it.pos != nil && it.vel.contains(where: { $0 != 0 }) { moveFreeItem(it) }
    }

    private func ipos(_ it: Item) -> [Int] { [it.pos!.x, it.pos!.y, it.pos!.z].map { Int($0) } }

    /// Item::Update + Move (1078:1490, 1078:08f6): gravity (vz -= 102 while vz > -0x500, as figures), step = velocityStep(v), then the missile
    /// PHYS sub-step mover; flag 0x02 just goes there. A block ends in itemBlocked.
    private func moveFreeItem(_ it: Item) {
        loadItemPhysics(it)
        if it.gravity && it.vel[2] > Self.fallVMin { it.vel[2] -= Self.fallDV }
        let start = ipos(it)
        it.step = velocityStep(it.vel)
        let target = (0..<3).map { start[$0] + it.step[$0] }
        if it.noCollide {
            it.pos = V3(Double(target[0]), Double(target[1]), Double(target[2]))
            return
        }
        let spans = it.extent.map { 2 * $0 }, minSpan = spans.min()!
        let n = minSpan > 0 && !(0..<3).allSatisfy({ abs(it.step[$0]) < spans[$0] }) ? moveSteps(it.step[0], it.step[1], it.step[2], minSpan) : 0
        let inc = n > 0 ? (0..<3).map { fixDiv(it.step[$0], n << 8) } : []
        var good = start
        if n > 0 {
            for i in 1...n {
                let cand = (0..<3).map { start[$0] + inc[$0] * i }
                if missileBlocked(it, cand) { return itemBlocked(it, start, cand, good) }
                good = cand
            }
        }
        if missileBlocked(it, target) { return itemBlocked(it, start, target, good) }
        it.pos = V3(Double(target[0]), Double(target[1]), Double(target[2]))
    }

    /// A PHYS block at `p` (1070:1d8f). The collider is FUN_1070_0f68's (the PHYS of the largest state-1 overlap at P; never a figure).
    /// IS_BOUNCY, or IS_REFLECTIVE (flag 0x20) with the collider's flag byte (+0x34, record byte 21) & 4: the generic rebound of FUN_1070_0fa7
    /// on the item's box: six candidates X, Y, Z, XY, XZ, YZ, each P with those axes put back to the move's start; the first free one is
    /// accepted and those velocity components are negated (none free: the last good position, all three negated); then
    /// v -= (v * ELASTICITY) >> 8, and `_<TYPE>_BOUNCE` plays when it exists (the generic rebound's own sound). Anything else stops at the
    /// last good position with zero velocity (a missile's step is `stoppedStep`, scaled by the finished share of the move). Then
    /// `_<TYPE>_BONK_<material>` plays when it exists (material = the collider's). ASSUMPTION (INFERRED landing): a gravity item rebounding
    /// upward from a fall with at most one gravity step of speed left comes to rest (velocity zeroed) where the rebound put it. See
    /// effects.py `item_blocked`.
    func itemBlocked(_ it: Item, _ start: [Int], _ p: [Int], _ good: [Int], stoppedStep: [Int]? = nil) {
        func setPos(_ q: [Int]) { it.pos = V3(Double(q[0]), Double(q[1]), Double(q[2])) }
        let h = (lo: SIMD3(p[0] - it.extent[0], p[1] - it.extent[1], p[2] - it.extent[2]),
                 hi: SIMD3(p[0] + it.extent[0], p[1] + it.extent[1], p[2] + it.extent[2]))
        var best: Int?, vol: Int32 = 0
        for (i, b) in physBoxes().enumerated() where b.state == 1 {
            let ov = overlapVolume(h, b)
            if ov > vol { best = i; vol = ov }
        }
        let flag4 = best.map { data.phys[$0].raw.count > 21 && data.phys[$0].raw[21] & 4 != 0 } ?? false
        if it.bouncy || (it.reflective && flag4) {
            let step = (0..<3).map { p[$0] - start[$0] }
            var axes = [0, 1, 2], t = good
            for cand in [[0], [1], [2], [0, 1], [0, 2], [1, 2]] {
                var q = p
                for a in cand { q[a] = start[a] }
                if !missileBlocked(it, q) { axes = cand; t = q; break }
            }
            let falling = it.vel[2] < 0
            setPos(t)
            var v = it.vel
            for a in axes { v[a] = -v[a] }
            let e = it.elasticity
            it.vel = v.map { $0 - fixMul($0, e) }
            it.step = step.map { $0 - fixMul($0, e) }
            if let idx = soundIndex(.str("_\(it.type)_BOUNCE")) { playSound(idx, item: it) }
            if it.gravity && falling && axes.contains(2) && abs(it.vel[2]) <= Self.fallDV { it.vel = [0, 0, 0] }
        } else {
            setPos(good)
            it.vel = [0, 0, 0]
            it.step = stoppedStep ?? (0..<3).map { good[$0] - start[$0] }
        }
        if let best {
            let raw = data.phys[best].raw
            let tail = raw.count > 45 ? Array(raw[45..<min(54, raw.count)]) : []
            let material = String(decoding: tail.prefix { $0 != 0 }, as: UTF8.self)
            hitSound("_\(it.type)_BONK_\(material)", item: it)     // FUN_1070_1d8f -> FUN_1100_1ce4
        }
    }
}
