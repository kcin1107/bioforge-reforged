// Level mechanics: the script statements CHANGEMYFORM (10d0:192c), GRABCRITTER (10d0:38a4), RELEASEFROMLIMB (10d0:663e) and FREEHAND
// (10d0:3207). Port of re/interp/mechanics.py (the oracle, which also holds the decoded rules and the ASSUMPTIONs).
//
// CHANGEMYFORM loads a new form into the current figure (FUN_1088_2a87): assets and type name change; EXTENT, armor, IS_REFLECTIVE,
// AUTO_TURN_SPEED, PERSONAL_RADIUS, MATERIAL and the foot offset are read from `Figure.type` on use, so they follow by themselves;
// MY_SPEED, ELASTICITY, gravity and IS_BOUNCY stay. GRABCRITTER attaches a figure to a limb of CURFIG (`Figure.limbHolder`): like a missile
// rider it skips its own move, gravity, grounding and pushes, and each tick it is put at the limb's current animated pose plus its own
// `ON_<LIMB>` property. RELEASEFROMLIMB only clears the link. FREEHAND puts the item of a hand down (RTHAND, with the animation) or stows it.
//
// ANIMATE sets the mode and period of one animated texture of an object's mesh, which then steps by the state machine of 1168:055e (the
// renderers draw each animated texture at that state's frame, frame 0 without ANIMATE). SETREFERENT re-aims a process's referent (what kills it when destroyed: item
// destructor 1078:0690); INCVIRTUALSECONDS (10d0:6cef) and FORCERELOAD (10d0:31db) are the speed-test and player-death statements.
import Foundation

extension World {
    private func word(_ args: [ScriptValue], _ i: Int) -> String {
        if i < args.count, case .str(let s) = args[i] { return s.uppercased() }
        return ""
    }

    // MARK: CHANGEMYFORM

    /// `CHANGEMYFORM <name>`: warnings, nothing changes: no current figure (0x4d), empty word (0x64), no BODY/<NAME>.BED (0x20). The figure
    /// takes the new form's assets and type name; the old model's decals go with it (INFERRED). ASSUMPTION for the ports: the current motion
    /// is re-mapped by name into the new motion set (frame index kept if valid, else 0), else the figure STANDs. Anything waiting on the
    /// old motion is released (the motion id changes). See mechanics.py `cmd_changemyform`.
    func cmdChangeMyForm(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        guard let fig = figure(proc.curFig) else { warn("CHANGEMYFORM: no current figure (error 0x4d)"); return }
        let name = word(args, 0)
        guard !name.isEmpty else { warn("CHANGEMYFORM: needs a form name (error 0x64)"); return }
        guard game.resolve("BODY/\(name).BED") != nil, let assets = asset(name) else { warn("CHANGEMYFORM \(name): no such form (error 0x20)"); return }
        fig.bakeTurn()                                  // while the old motion set can still answer `turning`
        let old = fig.motion
        fig.assets = assets
        fig.type = name
        fig.decals = [:]; fig.anim = [:]
        fig.footOverride = nil                          // 2a87 copies the new model's F to +0x225
        if let old, let m = assets.motion(old) {
            fig.frames = m.frames; fig.motionInfo = m
            fig.idx = fig.idx < m.frames.count ? fig.idx : 0
            fig.motId += 1
        } else {
            fig.motion = nil; fig.frames = nil; fig.motionInfo = nil
            fig.idx = 0
            fig.setMotion("STAND", loop: true)
        }
    }

    // MARK: GRABCRITTER / RELEASEFROMLIMB

    /// `GRABCRITTER <object> <limb>`: the holder is CURFIG, the grabbed object a figure (PLAYER or an instance name). Warnings: an empty
    /// argument (0x123), no current figure (0x4d); an unknown object is silent. No wait; CURFIG is unchanged.
    func cmdGrabCritter(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        let obj = word(args, 0), limb = word(args, 1)
        guard !obj.isEmpty, !limb.isEmpty else { warn("GRABCRITTER: needs an object and a limb (error 0x123)"); return }
        guard let holder = figure(proc.curFig) else { warn("GRABCRITTER: no current figure (error 0x4d)"); return }
        figure(obj)?.limbHolder = (holder.name, limb)
    }

    /// `RELEASEFROMLIMB <limb>`: warnings: empty limb (0x4f), no current figure (0x4d), a limb CURFIG's skeleton lacks (0x126). The first
    /// figure held by (CURFIG, limb) is let go: only the link is cleared. Nothing attached: silent.
    func cmdReleaseFromLimb(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        let limb = word(args, 0)
        guard !limb.isEmpty else { warn("RELEASEFROMLIMB: needs a limb (error 0x4f)"); return }
        guard let holder = figure(proc.curFig) else { warn("RELEASEFROMLIMB: no current figure (error 0x4d)"); return }
        guard holder.assets.assets.skeleton.limbs.contains(where: { $0.name.uppercased() == limb }) else {
            warn("RELEASEFROMLIMB \(limb): \(holder.type) has no such limb (error 0x126)"); return
        }
        figures.values.first { $0.limbHolder?.holder == holder.name && $0.limbHolder?.limb == limb }?.limbHolder = nil
    }

    /// FUN_1088_5c19 (as handPose): the world origin of `held` attached to `holder`'s `limb` (see mechanics.py `limb_held_pose`).
    private func limbHeldPose(_ holder: Figure, _ held: Figure, _ limb: String) -> V3? {
        guard let hp = holder.pos, let frames = holder.frames, !frames.isEmpty else { return nil }
        let skeleton = holder.assets.assets.skeleton
        guard let li = skeleton.limbs.firstIndex(where: { $0.name.uppercased() == limb }) else { return nil }
        let (start, rot) = skeleton.solve(frames[min(holder.idx, frames.count - 1)])
        let end = start[li] + rot[li].r[1] * Double(skeleton.limbs[li].length)
        let props = resources.figureProps, key = "ON_" + limb
        let v = props[held.name.uppercased()]?[key] ?? []
        let vals = (v.isEmpty ? props[held.type.uppercased()]?[key] ?? [] : v).map(pyStr)
        let a: [String: Int]
        if vals.count == 7, vals.allSatisfy({ Int($0) != nil }) { a = Dictionary(uniqueKeysWithValues: zip(["I", "J", "K", "LENGTH", "X", "Y", "Z"], vals.map { Int($0)! })) }
        else { a = ItemRules.parseNumbers(vals) }
        let ang = SIMD3<Int>((a["I"] ?? 0) * 32 / 45, (a["J"] ?? 0) * 32 / 45, (a["K"] ?? 0) * 32 / 45)
        let off = V3(Double(ItemRules.attachUnits(a["X"] ?? 0)), Double(ItemRules.attachUnits(a["Y"] ?? 0)), Double(ItemRules.attachUnits(a["Z"] ?? 0)))
        let m = rot[li].rotated(ang)
        let origin = end + rot[li].apply(off) + m.r[1] * Double(ItemRules.attachUnits(a["LENGTH"] ?? 0))
        return Scene.place([origin], at: hp, yaw: -holder.heading)[0]
    }

    /// Every tick after the figure updates (ASSUMPTION: 1088:5c19's caller is not decoded): each figure held by a limb is placed at the
    /// holder's limb pose, as a missile rider. A holder that is gone releases it.
    func placeLimbHeld() {
        for fig in figures.values {
            guard let h = fig.limbHolder else { continue }
            guard let holder = figures[h.holder] else { fig.limbHolder = nil; continue }
            if let origin = limbHeldPose(holder, fig, h.limb) { fig.pos = origin; fig.prevPos = origin; fig.lastGood = origin }
        }
    }

    // MARK: FREEHAND

    /// `FREEHAND <hand>`: warnings: no current figure (0x4d), empty hand (0x4f). Nothing in that hand: nothing. RTHAND starts the
    /// put_down_rthand motion as an engine request and blocks the process until it ends (its event 0xf3 drops the item); a figure without
    /// that motion: no wait. Any other word (LTHAND) stows the item at once. See mechanics.py `cmd_freehand`.
    func cmdFreeHand(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        guard let fig = figure(proc.curFig) else { warn("FREEHAND: no current figure (error 0x4d)"); return }
        let hand = word(args, 0)
        guard !hand.isEmpty else { warn("FREEHAND: needs a hand (error 0x4f)"); return }
        guard let item = heldItem(fig, hand) else { return }
        if hand != "RTHAND" { stowItem(fig, item); return }
        fig.manualControl = false
        if fig.setMotion("PUT_DOWN_RTHAND", loop: false, engine: true) {
            let tok = fig.motId
            proc.waitPred = { [weak fig] in fig.map { $0.motId != tok || $0.finished } ?? true }
        }
    }

    // MARK: ANIMATE

    static let animWords: [String: Int] = ["FREEZE": 0, "INCREMENT": 1, "DECREMENT": 2, "RANDOM": 3, "LOOP": 0, "YOYO": 4,
                                           "TO_LIMIT": 8, "RESET": 0x10, "ONCE": 0x20]
    static let animDefaultPeriod = 15          // 10d0:0800: a missing or non-positive number

    /// ASSUMPTION: the 60 Hz clock [8330] is 2 x the game clock in VM ticks (`gameTick`: FREEZE stops it).
    var textureClock: Int { 2 * gameTick }

    /// `ANIMATE <object> <TEXTURE> [words] [number]` (10d0:077b -> 10f8:0631 / 0256); see mechanics.py `cmd_animate`.
    func cmdAnimate(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        guard args.count >= 2, case .str(let texture) = args[1] else { return }
        let obj = scriptObject(proc, args[0])
        let mesh: EORMesh?
        if let f = obj.fig { mesh = f.assets.assets.mesh } else if let i = obj.item { mesh = itemMesh(i.type) } else { return }
        let name = String(texture.uppercased().prefix(8))
        guard let mesh, let n = mesh.frames.first(where: { mesh.textures[$0.key].name.uppercased() == name })?.value.count, n > 0 else { return }
        var mode = 0, period = 0
        for a in args.dropFirst(2) {
            if case .str(let w) = a { mode |= Self.animWords[w.uppercased()] ?? 0 }
        }
        for a in args.dropFirst(2) { if case .int(let v) = a { period = v; break } }
        if period <= 0 { period = Self.animDefaultPeriod }
        var st = (obj.fig?.anim ?? obj.item?.anim ?? [:])[name] ?? TextureAnim(frame: 0, mode: 0, period: 0, next: 0, n: n)
        if mode == 0x10 { st.frame = 0 }
        st.mode = mode; st.period = period; st.next = textureClock + period
        if let f = obj.fig { f.anim[name] = st } else { obj.item!.anim[name] = st }
    }

    /// 1168:055e for one texture state; `rand(a, b)` is the inclusive random draw.
    static func advanceTexture(_ st: inout TextureAnim, clock: Int, rand: (Int, Int) -> Int) {
        var mode = st.mode
        let n = st.n
        guard n > 0, mode != 0, clock >= st.next else { return }
        var f = st.frame
        switch mode & 3 {
        case 1: f += 1
        case 2: f -= 1
        case 3: f = rand(0, n - 1)
        default: break
        }
        switch mode & 0x1c {
        case 0: f = f >= n ? 0 : f < 0 ? n - 1 : f
        case 4:
            if f >= n - 1 { f = n - 1; mode = (mode & ~3) | 2 }
            if f < 1 { f = 0; mode = (mode & ~3) | 1 }
        case 8: f = max(0, min(n - 1, f))
        default: break
        }
        st.frame = f
        st.mode = mode & 0x20 != 0 ? 0 : mode
        st.next = clock + st.period                  // no catch-up: one step per update at most
    }

    /// Once per world step, for every figure and item with ANIMATE state. ASSUMPTION: the engine steps an object when it is drawn
    /// (1188:1d54); the ports step it every tick. RANDOM draws from the shared RNG (`World.rng`, as RANDOM).
    func stepTextures() {
        let clock = textureClock
        for fig in figures.values where !fig.anim.isEmpty {
            for k in Array(fig.anim.keys) { Self.advanceTexture(&fig.anim[k]!, clock: clock) { self.rng.randint($0, $1) } }
        }
        for item in items.values where !item.anim.isEmpty {
            for k in Array(item.anim.keys) { Self.advanceTexture(&item.anim[k]!, clock: clock) { self.rng.randint($0, $1) } }
        }
    }

    // MARK: SETREFERENT

    /// 10c0:535-556: at spawn the referent is CURFIG if one is given, else CURITEM.
    func referent(of proc: ScriptProcess) -> AnyObject? {
        if let f = proc.curFig, !f.isEmpty { return figures[f] }
        if let i = proc.curItem, !i.isEmpty { return items[i] }
        return nil
    }

    /// `SETREFERENT <object>` (10d0:7330); see mechanics.py `cmd_setreferent`. The error 0x70 case has no notion in the ports.
    func cmdSetReferent(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        guard let a = args.first else { return }
        let obj = scriptObject(proc, a)
        if let f = obj.fig { proc.referent = f } else if let i = obj.item { proc.referent = i }
    }

    /// Item destructor 1078:0690: every script process whose referent is the item dies (dropped without resuming its waiters; the
    /// running `caller` ends after its statement). Figures (1070:05a1) are NOT PORTED.
    func killItemReferents(_ item: Item?, caller: ScriptProcess? = nil) {
        guard let item, let vm else { return }
        for q in vm.procs.values where q.referent === item {
            if q === caller { q.ended = true }
            else { q.done = true; q.waiters = []; vm.procs.remove(q.handle) }
        }
    }

    // MARK: INCVIRTUALSECONDS / FORCERELOAD

    /// `INCVIRTUALSECONDS <n>` (10d0:6cef); see mechanics.py `cmd_incvirtualseconds`.
    func cmdIncVirtualSeconds(_ args: [ScriptValue]) {
        var n = 0
        if case .int(let v)? = args.first { n = v }
        if n != 0 { vm?.globals["_timetest"] = .int(0) } else { speedFactor = min(speedFactor + 1, 20) }
    }

    /// `FORCERELOAD` (10d0:31db): the player's hit points := -1, then the options dialog with _OPTS_MUST_RELOAD; the process yields.
    func cmdForceReload(_ proc: ScriptProcess) {
        if let player, let vm {
            var rec = vm.objectRecord(objectKey(player.name))
            rec[0] = .int(-1)
            vm.setObject(objectKey(player.name), rec)
        }
        openOptions(Options.mustReload)
        proc.waitPred = { true }
    }

    // MARK: FLOATATHEIGHT <waypoint>

    /// This figure's F (model +0x88 / fig+0x225): the FLOATATHEIGHT override if one was set, else its type's.
    func foot(_ fig: Figure) -> Int { fig.footOverride ?? fig.assets.footOffset }

    /// FLOATATHEIGHT <waypoint> (10d0:2f91, one word); see world.py `float_at_height`.
    func floatAtHeight(_ fig: Figure, _ wp: V3) {
        let x = Int(wp.x), y = Int(wp.y), z = Int(wp.z)
        fig.footOverride = wrap32(z - pointFloor(x, y, z, z))
        guard let p = fig.pos else { return }
        _ = updateArea(fig, at: p)
        let h = hull(fig)
        let sup = support(h.lo, h.hi, area: area(of: fig))
        var pos = p
        if sup > Self.noFloor { pos.z = Double(sup + fig.footOverride!) }
        setPos(fig, pos, raw: true)
    }
}
