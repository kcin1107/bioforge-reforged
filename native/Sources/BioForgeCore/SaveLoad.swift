// Native save / load of a running game, mirrors the save part of re/interp/world.py (export_state, save_native, load_native,
// from_native_state). The save carries the live script processes (processStates -> SCRIPT.DAT tasks), the FIGR/PLAY state (position,
// heading, motion, flags, object locals, enemy, AI hold and name, velocity, InTrig, viewing cameras; a PLAY record is appended when the
// level file has none, a FIGR record for each figure a script made, and a killed figure's record is dropped), the level's ITEM records
// (holder, hand, floor position, object locals; the world's items follow the other records in creation order, a script-made item gets
// one), variables, logs, level and camera. Limits: the figure record tails past those fields are kept from the template / base, native
// processes other than TIMED handles and ramps (fades, missiles) are not saved, and a one-off motion is saved as the idle it ends in.
import Foundation

public struct ExportedState {
    public var level: String, camera: String?, autoCamera: Bool
    /// {NAME: value} of the integer globals (upper-cased names)
    public var vars: [String: Int]
    public var lists: [LogList]
    public var figures: [String: SIMD3<Double>]
    /// {item name: state} of every item of the world (SaveWrite.patchItem applies those that have an ITEM record)
    public var items: [String: SaveWrite.ItemState] = [:]
    /// {FIGURE NAME: state} of the placed figures (SaveWrite.patchFigure applies those that have a record)
    public var figureStates: [String: SaveWrite.FigureState] = [:]
    /// the player's name, nil before Lex exists
    public var player: String?
    /// the live script processes (World.processStates)
    public var tasks: [SaveWrite.TaskState] = []
    /// {item name: (type, object locals)} of the world's items but missiles (the writer's item_extra)
    public var itemExtra: [String: (type: String, locals: [Int])] = [:]
    /// {item name: (velocity, flag byte)} of the missiles in flight (the writer's item_extra third element)
    public var missiles: [String: (vel: [Int], flags: Int)] = [:]
    /// killed figures' names (their FIGR records are dropped)
    public var killed: Set<String> = []
    /// creation order of `figureStates` / `items` (the writer's record order)
    public var figureOrder: [String] = [], itemOrder: [String] = []
    /// {level: (item states, {item name: (type, locals)}, item order, figure states, figure order)} of the items and figures kept with the
    /// levels the player left (World.levelItems, levelFigures)
    public var otherLevels: [String: SaveWrite.OtherLevel] = [:]
}

extension World {
    /// The pieces of the native GAMEDAT state this port can populate (export_state).
    public func exportState() -> ExportedState {
        var vars: [String: Int] = [:]
        for (k, v) in vm?.globals ?? [:] { if case .int(let i) = v { vars[k.uppercased()] = i } }
        let lists = logEntries.keys.map { l -> LogList in
            let keys = logEntries[l] ?? [], times = logEntryTimes[l] ?? []
            return LogList(name: l, items: zip(keys, times).map { LogItem(key: $0, stamp: $1) })
        }
        var figs: [String: SIMD3<Double>] = [:]
        for k in figures.keys { if let p = figures[k]?.pos { figs[k] = p } }
        var its: [String: SaveWrite.ItemState] = [:]
        for k in items.keys {
            guard let i = items[k] else { continue }
            its[k] = Self.itemState(i)
        }
        let states = figureStates(figures)
        var extra: [String: (type: String, locals: [Int])] = [:]
        for k in items.keys {
            guard let i = items[k], !(i is Missile) else { continue }
            extra[k.uppercased()] = (i.type, (vm?.objectRecord(i.key) ?? []).map { v -> Int in if case .int(let n) = v { return n }; return 0 })
        }
        var missiles: [String: (vel: [Int], flags: Int)] = [:]
        for (k, m) in savedMissiles() {
            extra[k.uppercased()] = (m.type, [Int](repeating: 0, count: 10))
            missiles[k.uppercased()] = (m.vel, Self.missileFlags(m))
        }
        var state = ExportedState(level: level + ".IFF", camera: currentCamera, autoCamera: scriptAuto, vars: vars, lists: lists, figures: figs, items: its,
                             figureStates: states, player: playerName, tasks: processStates(), itemExtra: extra, killed: killedFigures,
                             figureOrder: figures.keys.filter { figures[$0]?.pos != nil }.map { $0.uppercased() }, itemOrder: items.keys,
                             otherLevels: levelItemStates())
        state.missiles = missiles
        return state
    }

    /// {FIGURE NAME: the record fields SaveWrite.patchFigure writes} of the placed figures in `figs`: the saved z adds the motion's root z
    /// back (Resume takes it off), flags as the record's bit set, the object locals, the enemy's name (PLAYER for the player).
    func figureStates(_ figs: OrderedMap<Figure>) -> [String: SaveWrite.FigureState] {
        var states: [String: SaveWrite.FigureState] = [:]
        for k in figs.keys {
            guard let f = figs[k], let p = f.pos else { continue }
            let flags = (f.gravity ? ObjRec.flagGravity : 0) | (f.noCollide ? ObjRec.flagCollisions : 0) | (f.hidden ? ObjRec.flagHidden : 0)
                | (f.invulnerable ? ObjRec.flagInvulnerable : 0) | (f.bouncy ? ObjRec.flagBouncy : 0) | (f.combat ? ObjRec.flagCombat : 0)
            var motion = f.motion ?? ""
            let task = !motion.isEmpty && f.unwaited && f.taskName == motion && !f.finished     // a running MOTION ... CONTINUE: its task
            let dead = motion == "DIE" && ((vm?.objects[objectKey(k)]?.first).map { if case .int(let h) = $0 { return h }; return 0 } ?? 1) <= 0
            let idle = f.combat ? "ATK_STAND" : "STAND"
            if !motion.isEmpty, !f.loop, !task, !dead, f.assets.motion(idle) != nil {     // a type with no idle keeps its held pose
                motion = idle                                  // Resume loops the saved motion from frame 0 (the original keeps no phase either,
            }                                                  // FUN_1088_489f): a one-off midway or held on its last frame would repeat for
                                                               // ever, so it is saved as the idle it ends in (ASSUMPTION); a blocking MOTION
                                                               // comes back with its process, which re-runs the statement
            let first = motion.isEmpty ? nil : f.assets.motion(motion)?.frames.first
            let z = p.z + Double(first?.pos.z ?? 0)            // Resume takes the motion's root z off again
            var enemy = f.enemy
            if let e = enemy, e.uppercased() != "PLAYER", resolve(e) == playerName { enemy = "PLAYER" }
            let locals = (vm?.objectRecord(objectKey(k)) ?? []).map { v -> Int in if case .int(let i) = v { return i }; return 0 }
            states[k.uppercased()] = SaveWrite.FigureState(type: f.type, pos: SIMD3(p.x, p.y, z), heading: f.heading, motion: motion, flags: flags,
                                                          locals: locals, enemy: (enemy ?? "").uppercased(), hold: f.hold, inTrig: f.inTrig,
                                                          ai: (f.aiType ?? "").uppercased(), vel: [f.vx, f.vy, f.vz], viewCams: f.viewCams?.map { $0.uppercased() },
                                                          motionTask: task, teeter: f.teeter, zCap: f.zCap, foot: foot(f),
                                                          avoid: f.avoid.map { ($0.name.uppercased(), $0.radius) }, aiHandle: f.aiProc.flatMap { $0.done ? nil : $0.handle } ?? 0)
        }
        return states
    }

    /// The missiles a save keeps: in flight, with a live handle. NOT PORTED: what one carries (FIRE ... CARRY: the player cannot save on
    /// a zip line, CANNOT_SAVE) is not linked back on a load.
    func savedMissiles() -> [(String, Missile)] {
        items.keys.compactMap { k in
            guard let m = items[k] as? Missile, !m.dead, m.pos != nil, let p = vm?.procs[m.handle], !p.done else { return nil }
            return (k, m)
        }
    }

    /// The missile item's flag byte (+0x34) as its record keeps it: gravity, collisions off (CARRY), bouncy, reflective.
    static func missileFlags(_ m: Missile) -> Int {
        (m.gravity ? ObjRec.flagGravity : 0) | (m.noCollide ? ObjRec.flagCollisions : 0) | (m.bouncy ? ObjRec.flagBouncy : 0) | (m.reflective ? 0x20 : 0)
    }

    /// An item as the writer sees it: owner, slot, floor position and orientation rows (SaveWrite.patchItem).
    static func itemState(_ i: Item) -> SaveWrite.ItemState {
        SaveWrite.ItemState(owner: i.owner, slot: i.slot, pos: i.pos, matrix: i.matrix.map { m in m.r.map { [$0.x, $0.y, $0.z] } })
    }

    /// The items and figures kept with the levels the player left, as SaveWrite.buildFiles' `otherLevels` takes them (level_item_states).
    func levelItemStates() -> [String: SaveWrite.OtherLevel] {
        Dictionary(uniqueKeysWithValues: levelItems.map { level, kept -> (String, SaveWrite.OtherLevel) in
            var states: [String: SaveWrite.ItemState] = [:], extra: [String: (type: String, locals: [Int])] = [:], order: [String] = []
            for (i, locals) in kept {
                let k = i.key.uppercased()
                if states[k] == nil { order.append(k) }
                states[k] = Self.itemState(i)
                extra[k] = (i.type, locals.map { v -> Int in if case .int(let n) = v { return n }; return 0 })
            }
            guard let figs = levelFigures[level] else { return (level, (states, extra, order, nil, [])) }
            return (level, (states, extra, order, figureStates(figs), figs.keys.filter { figs[$0]?.pos != nil }.map { $0.uppercased() }))
        })
    }

    /// The local count a saved process record carries (object+0x70): the block's LOCALVAR declarations, and at least up to the last
    /// nonzero local the port holds (world.py declared_locals).
    static func declaredLocals(_ block: ScriptBlock, _ values: [Int]) -> Int {
        let n = ScriptFile.walk(block.body).filter { $0.op == "LOCALVAR" }.count
        let used = values.enumerated().filter { $0.element != 0 }.map { $0.offset + 1 }.max() ?? 0
        return Swift.min(Swift.max(n, used), 10)
    }

    /// The live script processes in the terms SaveWrite.taskScriptDat writes and Resume reads (world.py `process_states`): the block's
    /// definition number in its file, `pc` = the .SCP offset of the statement it runs next and `pc0` = of the one before (a timeline's
    /// last line, whose time Resume measures from), both the same for a process blocked in a CALL expression (Resume re-enters it); the
    /// locals, the current figure / item, the LINKMETOCAMERAS list, the ticks left of a WAIT, and the processes it waits for.
    /// MODIFYVAREVERYNTH's native ramps become ramp tasks and the TIMED ones (subtitle / sound handles) Wait tasks of their own; other
    /// native processes (fades, missiles) are not saved. ASSUMPTION: a process the engine holds in a blocking MOTION / GO (waitPred) is
    /// saved at that statement and re-runs it on load.
    func processStates() -> [SaveWrite.TaskState] {
        guard let vm else { return [] }
        var out: [SaveWrite.TaskState] = []
        for p in vm.procs.values {
            if p.done { continue }
            guard let f = p.block.file else {
                if p.block.name == "TIMED" && p.waitOn == nil {          // a SUBTITLE / sound handle: a Wait task of the ticks left (ASSUMPTION)
                    var t = SaveWrite.TaskState(handle: p.handle)
                    t.timed = Swift.max(p.wake - vm.tick, 1)
                    out.append(t)
                } else if p.block.name == "MODIFYVAREVERYNTH", p.gen != nil, let r = p.ramp {
                    var t = SaveWrite.TaskState(handle: p.handle)
                    t.ramp = (r.value(), r.step, r.end, r.start, r.period, Swift.max(p.wake - vm.tick, 0))
                    out.append(t)
                }
                continue
            }
            guard let own = p.block.defid, f.source != nil, f.defs[own] === p.block else { continue }
            let offs = Dictionary(f.positions().map { (ObjectIdentifier($0.stmt), $0.offset) }, uniquingKeysWith: { $1 })
            let ins = p.code.ins
            let nxt = ins[Swift.min(p.pc, ins.count)...].lazy.compactMap { $0.stmt }.first { offs[ObjectIdentifier($0)] != nil }
            let prev = ins[..<Swift.min(p.pc, ins.count)].reversed().lazy.compactMap { $0.stmt }.first { offs[ObjectIdentifier($0)] != nil }
            if nxt == nil && prev == nil { continue }
            let pc = nxt.map { offs[ObjectIdentifier($0)]! } ?? offs[ObjectIdentifier(prev!)]! + 1
            let pc0 = !p.pending.isEmpty || p.waitPred != nil ? pc : (prev.map { offs[ObjectIdentifier($0)]! } ?? pc)
            // pending is a dictionary here (Python's keeps the insertion order): CALL node ids, which grow with the source position
            var blockers: [Int] = []
            for h in p.pending.sorted(by: { $0.key < $1.key }).map({ $0.value.handle }) + (p.waitOn.map { [$0.handle] } ?? []) where !blockers.contains(h) { blockers.append(h) }
            var t = SaveWrite.TaskState(handle: p.handle)
            t.script = ((f.name as NSString).deletingPathExtension.uppercased()) + ".SCP"
            t.block = own + 1; t.pc = pc; t.pc0 = pc0
            t.locals = p.locals.map { v -> Int in if case .int(let n) = v { return n }; return 0 }
            t.cur = ([p.curItem, p.curFig].compactMap { $0 }.first { !$0.isEmpty } ?? "").uppercased()
            t.cameras = p.cameras.map { $0.uppercased() }
            t.wait = p.waitOn == nil && p.pending.isEmpty ? Swift.max(p.wake - vm.tick, 0) : 0
            t.blockers = blockers
            t.calls = p.pending.sorted(by: { $0.key < $1.key }).map { $0.value.handle }
            t.nlocals = Self.declaredLocals(p.block, t.locals)
            t.figIndex = p.figIndex; t.suspended = p.suspended
            out.append(t)
        }
        for (k, m) in savedMissiles() {                          // a missile in flight is a task of its own (missile vtable): the original keeps it
            let owner = figures.keys.first { figures[$0] === m.ownerFig }
            var t = SaveWrite.TaskState(handle: m.handle)
            t.missile = (k.uppercased(), owner?.uppercased(), m.dist, m.spin)
            out.append(t)
        }
        // CAPTUREKEYBOARD's hook is a process of its own (DS:6530) that every key event restarts; the PLAY record links its slot. The port
        // spawns it per key, so it is written idle at the block's first statement (ASSUMPTION).
        if keyboardCaptured, let name = show.keyHook, let hook = vm.blocks[name], let f = hook.file, f.source != nil, let own = hook.defid,
           let first = f.positions().filter({ $0.block === hook }).map(\.offset).min() {
            var t = SaveWrite.TaskState(handle: (out.map(\.handle) + [vm.nextHandle]).max()! + 1)
            t.script = ((f.name as NSString).deletingPathExtension.uppercased()) + ".SCP"
            t.block = own + 1; t.pc = first; t.pc0 = first; t.locals = [0, 0, 0]; t.hook = true; t.nlocals = Self.declaredLocals(hook, [])
            out.append(t)
        }
        return out
    }

    /// Write savesDir/GAME<slot>.IM1: thumbnail = the bare room frame at save time (the native sample shows the room, not the dialog
    /// art). -> the file, or nil with a warning.
    @discardableResult public func saveNative(slot: Int) -> URL? {
        guard let savesDir else { warn("save: no saves folder"); fileError = (false, slot, "There is no saves folder."); return nil }
        do {
            var base: SaveState?
            if let dir = stateDirectory, ["MISC.DAT", "SCRIPT.DAT", "VARS.DEF", "SOUNDS.DEF", "LISTS.FLX"].allSatisfy({ GameFolder(dir).resolve($0) != nil }) {
                base = try SaveState.load(directory: dir)
            }
            guard let levelDir = stateDirectory ?? game.initgame else { throw FormatError("INITGAME not found") }
            let st = exportState()
            var template: [UInt8]?                                  // the new-game state's PLAY record, for a level whose file has none
            if let g = game.gamedat, let f = GameFolder(g).resolve("CHAOS.IFF") {
                template = try LevelIff.parse([UInt8](try Data(contentsOf: f))).chunks.first { $0.id == "PLAY" }?.data
            }
            let files = try SaveWrite.buildFiles(slotName: "GAME\(slot).IM1", level: level, camera: st.camera, autoCamera: st.autoCamera,
                                                 variables: st.vars, lists: st.lists, levelDir: levelDir, positions: st.figures, base: base, game: game, itemStates: st.items,
                                                 figureStates: st.figureStates, player: st.player, playerTemplate: template,
                                                 tasks: st.tasks, itemExtra: st.itemExtra, missiles: st.missiles, killed: st.killed, figureOrder: st.figureOrder, itemOrder: st.itemOrder,
                                                 otherLevels: st.otherLevels)
            var fb = Framebuffer()
            render(into: &fb)
            let url = savesDir.appendingPathComponent("GAME\(slot).IM1")
            try SaveWrite.writeIM1(to: url, files: files, frame: fb)
            return url
        } catch { warn("save: slot \(slot): \(error)"); fileError = (false, slot, error.localizedDescription); return nil }
    }

    /// Unpack savesDir/GAME<slot>.IM1 to GAME<slot>.d and boot it with `GameSession.fromNativeState`; the result is left in
    /// `pendingLoad` for the caller's loop. A missing file only warns.
    @discardableResult public func loadNative(slot: Int) -> GameSession? {
        guard let savesDir, FileManager.default.fileExists(atPath: savesDir.appendingPathComponent("GAME\(slot).IM1").path) else {
            warn("load: no save in slot \(slot)")
            fileError = (true, slot, "There is no saved game in this slot.")
            return nil
        }
        do {
            let data = [UInt8](try Data(contentsOf: savesDir.appendingPathComponent("GAME\(slot).IM1")))
            let out = savesDir.appendingPathComponent("GAME\(slot).d", isDirectory: true)
            try Im1.unpack(data, to: out)
            let s = try GameSession.fromNativeState(resources: resources, directory: out)
            s.world.savesDir = savesDir
            s.world.configureSettings(settings)
            pendingLoad = s
            return s
        } catch { warn("load: slot \(slot): \(error)"); fileError = (true, slot, error.localizedDescription); return nil }
    }
}

extension GameSession {
    /// A session booted from a native play directory (GAMEDAT, an unpacked .IM1): level + camera from MISC.DAT, VARS.DEF values,
    /// LISTS.FLX logs, the level IFF as the object file, then the saved figures, carried items and script processes (Resume.swift);
    /// `world.resumed` = {kernel slot: process}.
    public static func fromNativeState(resources: GameResources, directory: URL) throws -> GameSession {
        let st = try SaveState.load(directory: directory)
        let level = st.misc.level.uppercased().replacingOccurrences(of: ".IFF", with: "")
        let s = try GameSession(resources: resources, level: level, camera: st.misc.camera.isEmpty ? nil : st.misc.camera, stateDirectory: directory)
        let upper = Dictionary(s.vm.globals.keys.map { ($0.uppercased(), $0) }, uniquingKeysWith: { $1 })
        for (name, value) in st.vars.items { if let k = upper[name.uppercased()] { s.vm.globals[k] = .int(value) } }
        for l in try st.lists.lists() {
            s.world.logEntries[l.name] = l.items.map(\.key)
            s.world.logEntryTimes[l.name] = l.items.map(\.stamp)
        }
        s.world.scriptAuto = st.misc.autoCamera != 0
        if !st.misc.camera.isEmpty {                         // 1148:0490 fills [63e9] / [63ed] from the saved camera: restoring it runs no events
            s.world.loadedCam = st.misc.camera.uppercased()
            s.world.camera = s.world.loadedCam               // ... and the restore's switch (1130:0114) makes it current ([63ce])
            s.world.loadedRoom = String(s.world.loadedCam!.prefix(3))
        }
        s.world.resumed = try s.restore(st)
        s.origin = directory
        s.world.ambientPending = true                        // INFERRED: the engine re-requests the camera, so the ambient loops restart
        return s
    }
}
