// Value types of the engine binding (World): figures with their motion state, items, per-type assets with pose cache and a small
// insertion-ordered dictionary (Python dict order is observable in the prototype).
import Foundation

typealias V2 = SIMD2<Double>
typealias V3 = SIMD3<Double>

/// Insertion-ordered String-keyed dictionary (Python dict semantics: re-assigning a key keeps its position).
struct OrderedMap<Value> {
    private(set) var keys: [String] = []
    private var dict: [String: Value] = [:]
    subscript(key: String) -> Value? {
        get { dict[key] }
        set {
            if let v = newValue { if dict.updateValue(v, forKey: key) == nil { keys.append(key) } }
            else if dict.removeValue(forKey: key) != nil { keys.removeAll { $0 == key } }
        }
    }
    var values: [Value] { keys.map { dict[$0]! } }
    var isEmpty: Bool { keys.isEmpty }
    var first: Value? { keys.first.flatMap { dict[$0] } }
    func contains(_ key: String) -> Bool { dict[key] != nil }
    /// `{(new if k == old else k): v for k, v in items}`
    func renaming(_ old: String, to new: String) -> OrderedMap {
        var out = OrderedMap()
        for k in keys { out[k == old ? new : k] = dict[k]! }
        return out
    }
    func filtering(_ keep: (String) -> Bool) -> OrderedMap {
        var out = OrderedMap()
        for k in keys where keep(k) { out[k] = dict[k]! }
        return out
    }
}

/// A scalar of a log entry (key log details).
public enum LogValue: Equatable, Sendable { case none, bool(Bool), int(Int), str(String) }

/// A scripted walk: the figure's origin moves along its motion's root travel to `target` at height `z`.
final class Go {
    let target: V2, z: Double, motion: String, radius: Int
    init(target: V2, z: Double, motion: String, radius: Int) { self.target = target; self.z = z; self.motion = motion; self.radius = radius }
}

/// Lets a blocking MOTION notice that its motion started (id) and later ended or was replaced.
final class MotionToken { var id: Int? }

/// ANIMATE state of one animated texture (1168:055e): current frame, mode byte, period and next-update time in 60 Hz clock units, frame count.
struct TextureAnim: Equatable {
    var frame = 0, mode = 0, period = 0, next = 0, n = 0
}

public class Item {
    public var name: String
    public let type: String
    /// The unique key in World.items (World.addItem): the name when it is free, else `NAME#2`, `NAME#3`...; `name` (the instance, +0xf7)
    /// may repeat. CURITEM, the object locals, pick targets and the monitor's inventory entries hold the key.
    public var key: String
    public var owner: String?, slot: String?
    /// Floor items: position and orientation rows (WorldItems.swift); nil while carried or never placed.
    var pos: V3?, matrix: Mat3?
    /// Flag bit 0x04 of the ITEM record: not drawn.
    var hidden = false
    /// Persistent velocity (+0xc6..) and the last move's step (+0xd2..), s32 per tick; VELOCITYX / LEAP / SETVELOCITY treat figures and items alike.
    var vel = [0, 0, 0], step = [0, 0, 0]
    var vx: Int { get { vel[0] } set { vel[0] = newValue } }
    var vy: Int { get { vel[1] } set { vel[1] = newValue } }
    var vz: Int { get { vel[2] } set { vel[2] = newValue } }
    /// EXTENT half sizes in units
    var extent = [0, 0, 0]
    /// flag bits 0x02, 0x10, 0x20, 0x01
    var noCollide = false, bouncy = false, reflective = false, gravity = true
    var elasticity = 200
    /// the type's HAS_GRAVITY / IS_BOUNCY / ... properties are read once, when the item first moves (WorldEffects.swift)
    var physicsLoaded = false
    /// ANIMATE state per animated texture, see WorldMechanics.swift
    var anim: [String: TextureAnim] = [:]
    init(name: String, type: String, owner: String?) { self.name = name; self.key = name; self.type = type; self.owner = owner }
}

/// A figure type's assets (BODY/<type>.BED) with posed-vertex cache; mirrors world.py Assets.
final class WorldAssets {
    let assets: FigureAssets
    private var cache: [String: [V3]] = [:]
    /// F, model+0x88 (whole units): the engine's rest-pose depth of the lowest joint below the root (Skeleton.footDepth)
    let footOffset: Int

    init(_ a: FigureAssets, cosTable: [Int]) {
        assets = a
        footOffset = a.skeleton.footDepth(cosTable)
    }

    var type: String { assets.type }
    func motion(_ name: String) -> Motion? { assets.motion(name) }

    func pose(_ m: Motion, _ i: Int) -> [V3] {
        let key = "\(m.name)#\(i)"
        if let p = cache[key] { return p }
        let p = assets.pose(m.frames[i])
        cache[key] = p
        return p
    }

    /// FUN_1088_1854/0d63: sample the pose between two interior motion frames.
    func pose(_ m: Motion, _ i: Int, fraction: Double) -> [V3] {
        guard fraction > 0, i + 1 < m.frames.count else { return pose(m, i) }
        let a = m.frames[i], b = m.frames[i + 1]
        func lerp(_ x: Int, _ y: Int) -> Int { Int(Double(x) + Double(y - x) * fraction) }
        func lerp(_ x: SIMD3<Int>, _ y: SIMD3<Int>) -> SIMD3<Int> {
            SIMD3(lerp(x.x, y.x), lerp(x.y, y.y), lerp(x.z, y.z))
        }
        let frame = MotionFrame(pos: lerp(a.pos, b.pos), rootAngle: a.rootAngle,
                                limbs: zip(a.limbs, b.limbs).map { lerp($0.0, $0.1) })
        return assets.pose(frame)
    }
}

/// A CONFRONTENEMY's turn_to_enemy task (FUN_10e8_0000): settled once the figure faces the enemy, then two more updates.
final class ConfrontTask {
    var settled = false, count = 0
}

/// A figure's pose as drawn: its motion, frames, frame and blend toward the next one.
struct HeldPose {
    let motion: String?, frames: [MotionFrame], idx: Int, fraction: Double
}

public final class Figure {
    public internal(set) var name: String
    public internal(set) var type: String
    var assets: WorldAssets
    /// nil = not placed yet
    public internal(set) var pos: SIMD3<Double>?
    public internal(set) var heading: Double
    public internal(set) var motion: String?
    var frames: [MotionFrame]?
    public internal(set) var idx = 0
    public internal(set) var loop = true
    /// time into the current frame, in 1/256 ticks of the 60 Hz clock
    var phase = 0
    /// MY_SPEED: a frame lasts speed x the motion's frame time (FUN_1098_0088)
    let speed: Int
    var motionInfo: Motion?
    var go: Go?
    var afterGo: (name: String, loop: Bool, token: MotionToken?)?
    /// cameras this figure may be seen in; nil = always visible (PLAYER)
    public internal(set) var viewCams: [String]?
    var aiType: String?, aiProc: ScriptProcess?
    /// FUN_1088_31fb enables/resumes AI (the counter back at 0); FUN_1088_3371 starts it later during a visible figure update.
    var aiEnabled: Bool { hold == 0 }
    var enemy: String?
    public internal(set) var combat = false, spar = false
    /// flag bit 0x08 at +0x34 (INVULNERABLE ON/OFF, ISINVULNERABLE) and bit 0x04 (ISHIDDEN; no script command sets it)
    public internal(set) var invulnerable = false, hidden = false
    /// EXPLODE hid the figure (WorldEffects.swift): stays hidden, whatever the viewing cameras say
    var exploded = false
    var hitDone = false
    /// the current motion started with gravity off (its final root z is then carried, see setMotion)
    var hoverMotion = false
    /// The running turn_to_enemy task of a CONFRONTENEMY (FUN_10e8_0000).
    var confront: ConfrontTask?
    /// the hold comes from STOPMOTION / a hit's motion cancel, not from FREEZE: the player's keys still work
    var stopped = false
    /// the current motion is a script's MOTION ... CONTINUE / FREEZE that no process waits on
    var unwaited = false
    /// The pose drawn until the next update after an end-of-update idle (World.posed)
    var heldPose: HeldPose?
    /// APPLY state: {texture name: (mode, picture frame, picture prefix)}, see World.applyDecal
    public internal(set) var decals: [String: (mode: String, frame: Int?, prefix: String?)] = [:]
    /// motId of the recoil a hit started (FUN_1090_09b9 sets ~3 = 1 for its duration)
    var recoilId: Int?
    var motId = 0
    /// The current motion's frame duration (model+0x102), set when the motion starts (World.motionDuration), and the player's
    /// repeated attack (+0x12a name, +0x13e count).
    var duration: Int?, durId = -1, comboName = "", comboCount = 0
    public internal(set) var finished = false, frozen = false
    /// MOTION ... FREEZE (10d0:5e8b clears only the idle-fallback bit 0x80 of +0x34): the motion plays to its end and its last pose is
    /// held, with no STAND / ATK_STAND fallback (1088:508d, 1088:4167); every accepted setMotion clears it. `frozen` is the static hold of
    /// STOPMOTION / SNAPTOPOSE ... FREEZE.
    var noIdle = false
    /// +0x15f: the name of the scripted MOTION that is still running (set by cmdMotion, cleared by the next motion); see motionGateRefuses
    var taskName: String?
    /// the current motion's header flag 2 (+0x1e8, 1098.c:274): its root z is committed to pos.z at each wrap and at its end
    /// (World.advance, setMotion); settle / setPos do not stand the figure on its support meanwhile
    var rises = false
    var manualControl = false
    /// The mover (FUN_10a0_22e1) and the figure push (FUN_1088_3629) run when flag 0x02 is CLEAR (world.py `collisions`).
    public var collisions: Bool { !noCollide }
    /// flag bit 0x01 at +0x34 (GRAVITY CURFIG ON/OFF); ASSUMPTION: on by default
    public internal(set) var gravity = true
    /// flag bit 0x10 at +0x34 (BOUNCINESS <figure> ON/OFF)
    public internal(set) var bouncy = false
    /// z velocity (+0xce), world units per 30 fps frame; falling = +0x1e9; teeter = +0x146 (a whoah probe failed)
    var vz = 0, falling = false, teeter = false
    /// x/y velocity (+0xc6/+0xca): persistent (no friction); the frame move adds velocityStep() of (vx, vy, vz) to the root motion.
    /// Written by knockback, SETVELOCITY, LEAP and the bounce
    var vx = 0, vy = 0
    /// +0xd2/+0xd6/+0xda: this frame's step (the velocity at 30 fps); the mover rescales it on a blocked step
    var step = [0, 0, 0]
    /// +0xde, 8.8 loss fraction per bounce (FUN_1088_22ba; 256 = all)
    var elasticity: Int
    /// root motion of this frame's motion steps, applied by the frame move (World.frameMove)
    var rootDelta = V2(0, 0), rootMoved = false
    /// the current motion's frame 0 root is not applied yet (World.applyFirstRoot)
    var rootStart = false
    var appliedRootZ = 0                  // the previous motion's root z, which R (model+0xa6) still holds while rootStart is set
    /// a GO stride reached its target; the arrival is applied when the frame move completes
    var arriving = false
    /// +0x229, the AI-off counter (AI OFF, a fall, the die method FUN_1088_3196): script process and player input suspended
    var hold = 0
    /// stopped by FUN_1098_0789 with the idle-fallback bit set: the update's end requests the idle (World.stopFigure)
    var idleRequest = false
    /// An idle requested during a scheduler walk: FUN_1098_0745 -> 1098:0e49(fig, name, 1, 0) makes the motion task without running it,
    /// and its first run (10e0:0055) starts the motion: in the next walk (World.startPendingIdles)
    var pendingIdle: (name: String, tick: Int)?
    /// +0x1e1, FUN_1088_3419's call counter
    var autoTurnCount = 0
    /// +0xba (frame start position) and +0xe2 (last position the mover accepted)
    var prevPos: V3?, lastGood: V3?
    /// +0x1e8: set while FUN_10a0_2158 runs SetPos, which then skips the gravity floor snap
    var rawSetPos = false
    /// (tick, lo, hi): the stale fig+0x65 hull SETFLOOROFPHYS leaves behind (WorldFloors.swift; world.py `stored_hull`)
    var storedHull: (tick: Int, lo: SIMD3<Int>, hi: SIMD3<Int>)?
    /// the current motion was requested by the engine (lower case in the original: "walk")
    var engineRequest = false
    /// ADDAVOIDANCEPOINT [(object name, radius cm)], at most World.maxAvoid (+0x1f3 count, +0x1f5 objects, +0x215 radii)
    public internal(set) var avoid: [(name: String, radius: Int)] = []
    /// +0x14e: FLOATATHEIGHT <waypoint> MAXIMUM, a z limit above the area anchor's base z (0 = none); see World.mover
    var zCap = 0
    /// FUN_1138_1a93's current PHYS-area anchor. It is reselected as the figure moves.
    var area: Int?
    /// InTrig (+0x191): one byte per level IMAG, allocated zeroed on first use (FUN_1088_536a); nil until then
    var inTrig: [UInt8]?
    /// +0x2c: key (World.items) of the missile this figure is attached to by FIRE ... CARRY; see WorldMissiles.swift
    var carrier: String?
    /// +0x2c/+0x30: (holder figure name, limb) GRABCRITTER attached this figure to; see WorldMechanics.swift
    var limbHolder: (holder: String, limb: String)?
    /// ANIMATE state per animated texture, see WorldMechanics.swift
    var anim: [String: TextureAnim] = [:]
    /// +0x225: F set by FLOATATHEIGHT <waypoint> (nil = the type's F); see World.foot
    var footOverride: Int?
    /// flag bit 0x02 at +0x34: COLLISIONS CURFIG OFF sets it, ON clears it (FUN_10d0_1aa4); while set, FUN_1088_39ef neither stands the
    /// figure on its support nor lands it, and the mover (FUN_10a0_22e1) skips the PHYS test. All 49 FIGR figures start with it clear;
    /// created figures and the player too (ASSUMPTION: CREATEFIGURE sets no flags bit 0x02)
    var noCollide = false

    init(name: String, type: String, assets: WorldAssets, speed: Int, elasticity: Int = 200, pos: V3? = nil, heading: Double = 0) {
        self.name = name; self.type = type; self.assets = assets; self.speed = speed; self.elasticity = elasticity
        self.pos = pos; self.heading = heading
        _ = setMotion("STAND", loop: true)
    }

    /// Start a motion by name; false if the figure type has no such motion.
    /// FUN_1098_0088: model+0x102 = MY_SPEED x motion+0x52 (in 1/256 ticks of the 60 Hz clock), adjusted when the motion starts
    /// (World.motionDuration); before that, the plain product.
    func frameDuration() -> Int {
        if let d = duration, durId == motId { return d }
        return speed * (motionInfo?.frameTime ?? 0)
    }

    /// Motion flag +0x24 bit 0x01: the root limb's yaw is added to the heading (FUN_10a0_1c83).
    var turning: Bool { frames != nil && (motionInfo?.flags ?? 0) & 1 != 0 }

    /// FUN_10a0_1c83: rotate the figure by the root limb's yaw since the motion's first frame (256 units per turn, d * 45 / 32
    /// degrees; a negative yaw turns right).
    func bakeTurn() {
        guard turning, let f = frames else { return }
        heading -= Double(f[idx].limbs[0].z - f[0].limbs[0].z) * 45 / 32
    }

    /// STOPMOTION (10d0:77d6 -> FUN_1098_0789(fig, 1, 1)): end the motion with the current pose held (FUN_1040_0c07 copies each
    /// limb's target angles into its current ones). A turning motion's yaw goes into the heading (FUN_10a0_1c83), so the held
    /// pose keeps frame 0's root yaw; the motion and GO tasks end (FUN_1088_3229) and ISMYMOTION no longer matches. The figure is
    /// still updated (pushed, grounded); see world.py `stop_motion`.
    func stopMotion() {
        pendingIdle = nil                   // FUN_1088_3229 ends the motion task before its first run: the idle never starts
        guard let f = frames, !f.isEmpty else { return }
        var held = f[min(idx, f.count - 1)]
        if turning {
            bakeTurn()
            var limbs = held.limbs
            limbs[0].z = f[0].limbs[0].z
            held = MotionFrame(pos: held.pos, rootAngle: held.rootAngle, limbs: limbs)
        }
        if rises, let p = pos {
            // Stopping a rising motion mid-cycle commits the current root z (UPLADDER's STOPMOTION at the ladder top keeps the height
            // climbed); the held pose then carries no root z of its own. FUN_1098_0789 clears +0x1e8 and R and sets the teeter (+0x146)
            pos = V3(p.x, p.y, p.z + Double(held.pos.z))
            held = MotionFrame(pos: SIMD3(held.pos.x, held.pos.y, 0), rootAngle: held.rootAngle, limbs: held.limbs)
            rises = false; teeter = true
        }
        frames = [held]; idx = 0; loop = false; phase = 0
        frozen = true; finished = true; go = nil
        stopped = true
        dropDeferred()
        motId += 1
    }

    /// Abandon a MOTION that was deferred behind a GO (`afterGo`) because the GO is cancelled (STOPMOTION, a hit, a new GO or pose):
    /// its blocked caller resumes as if the motion had been replaced (the token's id can never equal a motion id). ASSUMPTION: without
    /// this the caller waits for an arrival that no longer comes (CAYNAN_AI hung in `MOTION ATK_H8` after the first punch took away
    /// its pacing GO).
    func dropDeferred() {
        if let tok = afterGo?.token, tok.id == nil { tok.id = -1 }
        afterGo = nil
    }

    /// FUN_1098_12bd (vtable +0x8c), the scripted MOTION's gate: while a scripted motion task and its name (+0x15f) still exist (the motion
    /// has not finished) a request is refused when that name starts with RECOIL / DIE / SUPER_REC or equals the requested name (it is not
    /// restarted). Refused = a non-blocking zero handle.
    func motionGateRefuses(_ name: String) -> Bool {
        guard let t = taskName, !finished else { return false }
        return t.hasPrefix("RECOIL") || t.hasPrefix("DIE") || t.hasPrefix("SUPER_REC") || t == name
    }

    @discardableResult func setMotion(_ n: String, loop: Bool, freeze: Bool = false, engine: Bool = false, noIdle: Bool = false) -> Bool {
        guard let m = assets.motion(n) else { return false }
        // FUN_1098_0394 tests only the current motion's name: no motion change while DIE is current, SNAP_TO or not (a finished motion is
        // no longer current: 1088:2035 -> 0789 clears it at the last frame, so GET_UP_FORWARD and the rest work then). REVIVELEX
        // (AWAKEN.scr) runs after the nurse's blocking `MOTION DIE`, which resumes once DIE has finished
        if motion == "DIE" && !finished { return false }
        bakeTurn()                          // FUN_1098_0789 (motion stop/change) keeps a turning motion's yaw
        if let f = frames, !f.isEmpty, !rootStart {
            appliedRootZ = f[min(idx, f.count - 1)].pos.z   // model+0xa6 keeps it until the new motion's first update
        }
        if rises, finished, let p = pos, let last = frames?.last {
            // A rising motion that played out commits its last root z (INFERRED for once-motions: design intent and the script
            // calibration, MANTLE_6 / ON_LADDER end on the ledge / rung); the loop wrap commits in World.advance. Done when the next
            // motion starts, so the held last pose and the hull keep the height until then.
            pos = V3(p.x, p.y, p.z + Double(last.pos.z))
        }
        if rises { teeter = true }           // FUN_1098_0789: ending a rising motion marks the teeter, so the landing plays no whoah until all the probes are fine
        if !gravity, finished, !rises, hoverMotion, let p = pos, let f = frames, let last = f.last, Double(last.pos.z) >= World.rootZKeepMin {
            // a finished motion's large root z stays as height (see world.py); only when that motion also started without gravity
            // (hoverMotion): under gravity its root z lived in the pose (z = support + F)
            // INFERRED: only a lift. Live, GUARD1 with gravity off goes WAKE_UP (z base - 1780), GET_UP (z back to base + its root z), atk_stand (base + its root z), so -1780 and GET_UP's -360 do not stay.
            pos = V3(p.x, p.y, p.z + Double(last.pos.z))
        }
        frozen = freeze; finished = false; hitDone = false
        self.noIdle = noIdle
        taskName = nil                      // +0x15f: a new motion ends the scripted one's name (cmdMotion sets it again after the request)
        pendingIdle = nil                   // a newer request supersedes an idle whose task has not run yet (INFERRED)
        stopped = false
        unwaited = false                    // a script MOTION ... CONTINUE / FREEZE nobody waits on (cmdMotion): yields to keys
        idleRequest = false
        hoverMotion = !gravity
        engineRequest = engine
        motId += 1
        motion = n.uppercased(); frames = m.frames; motionInfo = m; idx = 0; self.loop = loop; phase = 0
        rootStart = true
        rises = m.rises
        return true
    }

    /// Forward direction in the world: (-sin h, -cos h).
    func forward() -> V2 {
        let h = heading * World.radPerDeg
        return V2(-sin(h), -cos(h))
    }
}
