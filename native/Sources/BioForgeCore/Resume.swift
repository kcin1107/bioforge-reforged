// Resume a native save: figures, carried items and script processes (mirrors re/interp/resume.py; used by
// GameSession.fromNativeState).
//
// What comes from where (details and function citations: SaveGame.swift Proc / ScriptDat, SaveObjRec.swift, re/NOTES.md):
//   * figures: the level IFF's FIGR/PLAY records -> position, heading (COMPASS convention), current motion name, combat flag, hit
//     points and the other nine object locals (`<obj>.~0..~9`), enemy, viewing cameras, AI process link;
//   * items: ITEM records with a holder -> world.items (hand name or INVENTORY) plus their object locals;
//   * script processes (SCRIPT.DAT 'proc' slots): block = definition counter index, resume position = `pc` (byte offset into the
//     tokenized .SCP), locals, current figure/item, wait state (see waitState), handle = task serial, so VARS values such as
//     _CELLONEPROCESS = 18 refer to the restored process; the VM hands out new handles from MISC's next serial;
//   * MODIFYVAREVERYNTH tasks (type 0x10e) -> native ramp processes with the saved value and countdown;
//   * Wait tasks owned by no process (the writer's) -> TIMED native processes under their serial, valid for the ticks left.
// pc / pc0: pc0 = start of the statement the process is executing or last executed (a WAIT / SUSPEND / CALL / timeline line), pc =
// text position right after it (the next statement). pc == pc0 only while the process is blocked inside a CALL expression: that
// statement is re-entered on resume. So the resume point is always `pc`.
import Foundation

private let waitVtable = 0x6677, listEnd = 0x408       // Wait task class (SCRIPT.DAT slot), list terminator in a process record
private let waitRemaining = 0x40                       // u16 in the Wait task object: ticks left (+0x42 = the requested duration)
private let modifyType = 0x10e                         // MODIFYVAREVERYNTH task: s32 value @0x45, s16 step @0x49, end @0x4b, start @0x4d,
                                                       // u16 period @0x4f, u16 countdown @0x51 (ASSUMPTION: field names from one sample)

/// Every `call` node inside an expression, outer before inner (resume.py `_calls`).
private func calls(_ e: ScriptExpr) -> [(name: String, args: [ScriptExpr], id: Int)] {
    switch e {
    case .call(let n, let a, let id): return [(n, a, id)] + a.flatMap(calls)
    case .unary(_, let a): return calls(a)
    case .binary(_, let a, let b): return calls(a) + calls(b)
    case .within(_, let a, let l): return calls(a) + calls(l)
    case .list(let l): return l.flatMap(calls)
    default: return []
    }
}

/// Object ids of the level IFF (1-based; 0 / 0xFFFF = none) -> script names.
private final class Names {
    let recs: [(object: LevelIff.Object, rec: ObjRec?)]
    /// oid -> World.items key of a carried item (a duplicate name gets its own key)
    var itemKeys: [Int: String] = [:]
    init(recs: [(object: LevelIff.Object, rec: ObjRec?)]) { self.recs = recs }
    func rec(_ oid: Int) -> (object: LevelIff.Object, rec: ObjRec?)? { oid > 0 && oid <= recs.count ? recs[oid - 1] : nil }
    func name(_ oid: Int) -> String? {
        guard let r = rec(oid) else { return nil }
        return ((r.rec.map(\.inst).flatMap { $0.isEmpty ? nil : $0 }) ?? r.object.name).uppercased()
    }
    func tag(_ oid: Int) -> String? { rec(oid)?.object.tag }
}

extension World {
    /// What the level reader restores from a FIGR / PLAY record onto its figure (FUN_1148_0d46; the same reader serves a load and a return to
    /// a level): the current motion, the flags (hidden, combat, gravity, bouncy, collisions, invulnerable), teeter, z cap, foot, velocity, the
    /// enemy and the avoidance list. Used by Resume (the resumed level) and `figure` (a level built from its file); see resume.py
    /// `apply_figure_record`. `name` / `tag` resolve a record's object ids within the level's record list.
    func applyFigureRecord(_ fig: Figure, _ rec: ObjRec, key: String, name: (Int) -> String?, tag: (Int) -> String?) {
        if !rec.motion.isEmpty {
            if !fig.setMotion(rec.motion.uppercased(), loop: true) { warn("resume: \(key): motion \(pyRepr(rec.motion)) not found") }
            else { fig.pos!.z -= Double(fig.frames![0].pos.z) }      // saved z includes the motion's root z (FUN_10a0_1ff0); the port keeps it in the pose
        }
        fig.hidden = rec.flags & ObjRec.flagHidden != 0
        fig.combat = rec.flags & ObjRec.flagCombat != 0
        fig.gravity = rec.flags & ObjRec.flagGravity != 0
        fig.bouncy = rec.flags & ObjRec.flagBouncy != 0
        fig.noCollide = rec.flags & ObjRec.flagCollisions != 0
        fig.invulnerable = rec.flags & ObjRec.flagInvulnerable != 0
        fig.teeter = rec.teeter                       // +0x146
        fig.zCap = rec.zCap                           // +0x14e
        if rec.foot != fig.assets.footOffset { fig.footOverride = rec.foot }      // model+0x88: a FLOATATHEIGHT override (the type's F otherwise)
        if let m = fig.motion, !World.motionLoops(fig.assets, m), rec.motionTask == 0 {      // a one-off with no task has ended: its
            fig.loop = false; fig.idx = (fig.frames?.count ?? 1) - 1; fig.finished = true    // last pose (a type with no idle, ESCHEAD)
        }
        if rec.locals[0] <= 0, fig.motion == "DIE" {    // dead: the fixup starts I_AM_DEAD, which no body has, so the figure gets no
            fig.loop = false; fig.idx = (fig.frames?.count ?? 1) - 1; fig.finished = true     // motion; the port holds DIE's last pose (ASSUMPTION)
            fig.frozen = true; fig.stopped = true; fig.noIdle = true
        }
        (fig.vx, fig.vy, fig.vz) = (rec.velocity[0], rec.velocity[1], rec.velocity[2])      // +0xc6..: a zero-g float or a knockback goes on
        fig.enemy = tag(rec.enemy) == "PLAY" ? "PLAYER" : name(rec.enemy)
        fig.avoid = rec.avoid.map { (name($0.waypoint) ?? "", $0.radius) }   // ADDAVOIDANCEPOINT list (FUN_1088_3629 pushes)
    }
}

extension GameSession {
    /// -> {slot: process} of the restored script processes. Figures and items first (processes refer to them).
    func restore(_ st: SaveState) throws -> [Int: ScriptProcess] {
        let names = Names(recs: try st.levels[world.level]?.records() ?? [])
        let figs = figures(names)
        items(names)
        var procs = try processes(st, names)
        for (fig, rec) in figs {                     // a running MOTION ... CONTINUE: its motion task restarts the motion from frame 0
            guard let sl = st.script.slot(rec.motionTask), sl.vtable == SaveWrite.motionVtable else { continue }     // (FUN_1088_4d67 -> 1098:06e0)
            let name = String(decoding: sl.a[0x32..<0x4b].prefix { $0 != 0 }, as: UTF8.self).uppercased()
            let loop = World.motionLoops(fig.assets, name) && !World.gestures.contains { name.hasSuffix($0) }      // as cmdMotion's CONTINUE
            if fig.assets.motion(name) != nil, fig.setMotion(name, loop: loop) { fig.taskName = name; fig.unwaited = true }
        }
        for (_, rec) in figs where rec.tag == "PLAY" {       // the CAPTUREKEYBOARD hook process (DS:6530): the port runs the block per key,
            if rec.hookTask != 0, let p = procs.removeValue(forKey: rec.hookTask) {      // so the idle process only names it
                world.keyboardCaptured = true; world.show.keyHook = p.block.name.uppercased(); world.show.keyHookOwner = "level"
                vm.finish(p)
            }
        }
        for (fig, rec) in figs {                     // AI process link (the task slot of the process behind `AI ON`)
            if let p = procs[rec.aiTask] {
                fig.aiProc = p
                if p.block.name.uppercased().hasSuffix("_AI") { fig.aiType = String(p.block.name.dropLast(3)) }
            }
        }
        vm.reserveHandles(upTo: st.misc.nextSerial)
        world.applyCameraLinks(world.currentCamera)  // the restore ends by switching to the saved camera (1148:0490 -> 1130:0114)
        return procs
    }

    // MARK: figures

    private func figures(_ names: Names) -> [(Figure, ObjRec)] {
        var out: [(Figure, ObjRec)] = []
        for (i, r) in names.recs.enumerated() {
            guard let rec = r.rec, r.object.tag == "FIGR" || r.object.tag == "PLAY", let key = names.name(i + 1) else { continue }
            guard let assets = world.asset(rec.name.uppercased()) else { world.warn("resume: no figure type \(rec.name)"); continue }
            let fig = Figure(name: key, type: rec.name.uppercased(), assets: assets,
                             speed: world.mySpeed(key, rec.name.uppercased()),
                             elasticity: world.elasticity(key, rec.name.uppercased()), pos: v3(rec.pos), heading: rec.heading)
            fig.viewCams = r.object.tag == "PLAY" ? nil : rec.viewCams.map { $0.uppercased() }
            fig.aiType = rec.aiName.isEmpty ? nil : rec.aiName          // +0x178: the AI start runs <it>_AI (1088:33d4)
            fig.hold = rec.aiOff
            world.applyFigureRecord(fig, rec, key: key, name: names.name, tag: names.tag)
            world.updateArea(fig, at: fig.pos!)           // placed: the area list Space walks (FUN_1138_1a93, as setPos; INFERRED for the restore)
            if rec.inTrig.count == world.data.triggers.count { fig.inTrig = rec.inTrig }      // InTrig bytes, one per IMAG of the level
            world.figures[key] = fig
            if r.object.tag == "PLAY" { world.playerName = key }
            vm.setObject(world.objectKey(key), rec.locals.map { .int($0) })
            out.append((fig, rec))
        }
        return out
    }

    /// The player's items, then the item list in record order. The level reader makes the objects in chunk order (FUN_1148_0d46) and each
    /// item appends itself to the item list (1050:10bf), which the inventory walks (FUN_10d0_0076): so a loaded game lists the items in the
    /// file's order, the floor items and those a figure holds among the player's. The writer puts them in the world's creation order
    /// (SaveWrite.levelLayout), so the inventory comes back as it was saved.
    private func items(_ names: Names) {
        var came: [String: [String]] = [:]            // floor items and those a level figure holds came with the level (World.loadFloorItems),
        for key in world.items.keys { came[world.items[key]!.name.uppercased(), default: []].append(key) }     // in record order
        var order: [String] = []
        for (i, r) in names.recs.enumerated() {
            guard let rec = r.rec, r.object.tag == "ITEM", let name = names.name(i + 1) else { continue }
            if rec.holder == 0 || names.tag(rec.holder) == "FIGR" {
                if var q = came[name], !q.isEmpty { order.append(q.removeFirst()); came[name] = q }
                continue
            }
            // ASSUMPTION: a carried item whose hand string is empty sits in the inventory (FUN_10d8_2845 treats a null hand string
            // as "carried, not in a hand")
            let item = Item(name: name, type: rec.name.uppercased(), owner: names.name(rec.holder))
            item.slot = rec.hand.isEmpty ? "INVENTORY" : rec.hand.uppercased()
            world.addItem(item)
            names.itemKeys[i + 1] = item.key
            vm.setObject(item.key, rec.locals.map { .int($0) })
            order.append(item.key)
        }
        let placed = Set(order)
        var out = OrderedMap<Item>()
        for k in order + world.items.keys.filter({ !placed.contains($0) }) { out[k] = world.items[k] }
        world.items = out
    }

    // MARK: processes

    private func file(_ script: String) -> ScriptFile? {
        let stem = (script as NSString).deletingPathExtension.uppercased()
        if let f = vm.files.first(where: { ($0.name as NSString).deletingPathExtension.uppercased() == stem }) { return f }
        return world.resources.library.script(named: stem + ".scr").map { vm.load($0) }
    }

    private func processes(_ st: SaveState, _ names: Names) throws -> [Int: ScriptProcess] {
        let sd = st.script
        var made: [(slot: Int, p: ScriptProcess, rec: Proc?)] = []
        for s in sd.slots {
            if s.vtable == waitVtable, (try? s.task().owner) == 0 {       // owned by no process: a subtitle / sound handle (savewrite's; ASSUMPTION)
                made.append((s.index, vm.adoptTimed(handle: s.serial, ticks: max((try? s.a.u16(waitRemaining)) ?? 0, 1)), nil))
            } else if s.kind == .proc {
                if let rec = try s.proc(), let p = try process(s, rec, names) { made.append((s.index, p, rec)) }
            } else if s.type == modifyType, let c = try ramp(s) {
                made.append((s.index, c, nil))                          // a SUSPENDWHILE MODIFYVAREVERYNTH waiter waits for it again
            }
            else if s.vtable == SaveWrite.missileVtable, let c = try missile(s, names) {
                made.append((s.index, c, nil))                          // a SUSPENDWHILE FIRE waiter waits for it again
            }
        }
        let bySlot = Dictionary(made.map { ($0.slot, $0.p) }, uniquingKeysWith: { $1 })
        for m in made { if let rec = m.rec { try waitState(sd, m.p, rec, bySlot) } }
        return Dictionary(made.filter { $0.rec != nil }.map { ($0.slot, $0.p) }, uniquingKeysWith: { $1 })
    }

    /// A missile in flight (SaveWrite.missileVtable; FUN_10e0_12b7 reads it back): its ITEM record came in with the level's floor items as
    /// a plain Item, which becomes the Missile again with the task's range and spin, the record's position, orientation, velocity and
    /// flags, and a native handle under the task's serial. ASSUMPTION: the travel sound does not restart (+0x40 is a voice, which does
    /// not survive a load).
    private func missile(_ s: Slot, _ names: Names) throws -> ScriptProcess? {
        let c1 = try s.a.u16(0x18), c2 = try s.a.u16(0x22)
        let ownerOid = try s.b.u16(2 * (c1 + c2) + 2), itemOid = try s.b.u16(2 * (c1 + c2) + 4)
        let key = (names.itemKeys[itemOid] ?? names.name(itemOid) ?? "").uppercased()
        guard names.tag(itemOid) == "ITEM", let rec = names.rec(itemOid)?.rec,
              let old = world.items.keys.first(where: { $0.uppercased() == key && !(world.items[$0] is Missile) }) else {
            world.warn("resume: missile task \(s.serial): item #\(itemOid) not found")
            return nil
        }
        let m = Missile(name: old, missileType: rec.name.uppercased())
        world.missileTypeProps(m)
        m.pos = v3(rec.pos)
        m.setRows(rec.matrix)
        m.vel = rec.velocity
        m.noCollide = rec.flags & ObjRec.flagCollisions != 0
        m.dist = try s.a.s32(0x48)
        m.spin = [try s.a.s16(0x4c), try s.a.s16(0x4e), try s.a.s16(0x50)]
        let ownerPtr = try s.a.u32(0x44)
        m.ownerFig = ownerOid != 0 && ownerPtr != 0 ? names.name(ownerOid).flatMap { world.figures[$0] } : nil
        world.items[old] = m
        let c = vm.adoptNative("MISSILE", handle: s.serial)
        m.handle = s.serial
        return c
    }

    private func process(_ s: Slot, _ rec: Proc, _ names: Names) throws -> ScriptProcess? {
        guard let f = file(rec.script), let block = f.defs[rec.block - 1] else {
            world.warn("resume: slot \(s.index): block #\(rec.block) of \(rec.script) not found")
            return nil
        }
        let idx = vm.locate(block, offset: rec.pc)
        let cur = names.rec(rec.curObj) != nil ? rec.curObj : rec.objA        // the constructor starts the context at objA
        let tag = names.tag(cur)
        let ctx = ScriptContext(curFig: tag == "FIGR" || tag == "PLAY" ? names.name(cur) : nil, curItem: tag == "ITEM" ? (names.itemKeys[cur] ?? names.name(cur)) : nil, owner: "level")
        let p = vm.adopt(block, index: idx, handle: s.serial, ctx: ctx)
        for (i, v) in rec.locals.prefix(10).enumerated() { p.locals[i] = .int(v) }
        p.cameras = rec.objs.compactMap { names.name($0)?.uppercased() }      // the LINKMETOCAMERAS list (10c0:4362 registers it again)
        p.suspended = (try s.a.u16(0xe)) & 1 != 0                              // flag bit 0 (+0xe), in the task memory the save keeps: a paused AI stays paused (1230:0259 skips it)
        if rec.pc != rec.pc0, let ts = vm.code(block).ins[vm.locate(block, offset: rec.pc0)].ts {
            p.origin = vm.tick - ts          // timeline: the pc0 line was just executed; ASSUMPTION: its clock origin is not saved
        }                                    // (not in the record), so the next line waits its delta
        return p
    }

    /// Blocked on a Wait task -> sleep for its remaining ticks (u16 at +0x40, same unit as `WAIT n`); on a process -> CALL child
    /// (pc == pc0: the statement is re-entered with the child pending) or SUSPENDWHILE target; nothing -> run next tick.
    /// Evidence (both samples): list1 of a blocked process holds the task it waits for; the Wait task's owner is the process.
    private func waitState(_ sd: ScriptDat, _ p: ScriptProcess, _ rec: Proc, _ made: [Int: ScriptProcess]) throws {
        for b in rec.l1 where b != listEnd {
            if let t = sd.slot(b), t.vtable == waitVtable, made[b] == nil {      // its own WAIT (a timed handle is in `made`)
                p.wake = vm.tick + (try t.a.u16(waitRemaining))
            } else if let child = made[b] {
                p.waitOn = child
                child.waiters.append(p)
                if rec.pc == rec.pc0 {
                    let node = vm.code(p.block).ins[p.pc].stmt.flatMap { stmt in
                        stmt.args.flatMap(calls).first { c in
                            if c.name == "CALL", case .name(let n)? = c.args.first { return n.uppercased() == child.block.name.uppercased() }
                            return false
                        }
                    }
                    if let node { p.pending[node.id] = child }
                    else { world.warn("resume: \(p.block.name): CALL of \(child.block.name) not found at pc 0x\(String(rec.pc, radix: 16))") }
                }
            } else { world.warn("resume: \(p.block.name): blocked on unknown task slot \(b)") }
        }
    }

    /// MODIFYVAREVERYNTH(var, step, start, end, n) task: the variable is found by matching the literal step/start/end/n of a call
    /// site in the loaded scripts (ASSUMPTION: the saved far pointer cannot be mapped to a variable otherwise).
    private func ramp(_ s: Slot) throws -> ScriptProcess? {
        let cur = try s.a.s32(0x45)
        let step = try s.a.s16(0x49), end = try s.a.s16(0x4b), start = try s.a.s16(0x4d), period = try s.a.u16(0x4f), left = try s.a.u16(0x51)
        let want: [Int?] = [step, start, end, period]
        var tgt: ScriptExpr?
        for f in vm.files { for b in f.blocks { for st in ScriptFile.walk(b.body) { for expr in st.args { for c in calls(expr) {
            guard c.name == "MODIFYVAREVERYNTH", c.args.count >= 5, case .variable = c.args[0] else { continue }
            let lits: [Int?] = c.args[1..<5].map { if case .num(let n) = $0 { return n }; return nil }
            if lits == want { tgt = c.args[0] }
        } } } } }
        guard let tgt else { world.warn("resume: MODIFYVAREVERYNTH task \(s.serial): no call site with args \(want.map { $0.map(String.init) ?? "None" })"); return nil }
        return vm.adoptRamp(handle: s.serial, target: tgt, value: cur, left: left, step: step, end: end, period: period)
    }
}
