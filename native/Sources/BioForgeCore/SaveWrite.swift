// Write a native-format save (.IM1) from game state, mirrors re/formats/savewrite.py: files are built with the SaveGame encoders.
//
// SCRIPT.DAT keeps the template's system tasks (slots 0..5) and holds one task per live script process of the world (taskScriptDat:
// the process object, a Wait task for a sleeping one, a Wait task of no owner for a TIMED handle, a MODIFYVAREVERYNTH ramp), written
// as the original's kernel serializer would: the task objects are clean ones of the shipped GAMEDAT with the links, brace depth and
// local count set, so the original game loads these processes (checked live with the Python writer, which this mirrors).
import Foundation

public enum SaveWrite {
    /// ASSUMPTION: the game palette's 32-step grey ramp (same entries as the monitor palettes)
    static let ramp = 128
    /// StdIntHandler, BiosTimer, 3 device handlers, Music
    static let systemSlots = 6

    /// CAM frame (rle, 320x200, hotspot 0,0) of a room frame: Rec.601 luma (of the palette's 8-bit RGB) mapped linearly onto the grey
    /// ramp. The native thumbnail (re/out/native_save) is the room view in ramp indices 128..145 plus a dialog bar in 35..53; the
    /// dialog art is not part of the capture here (ASSUMPTION: the capture precedes the dialog).
    public static func thumbnail(_ fb: Framebuffer) throws -> [UInt8] {
        let px = fb.pixels.map { i -> UInt8 in
            let p = 3 * Int(i)
            let luma = Double(fb.palette[p]) * 0.299 + Double(fb.palette[p + 1]) * 0.587 + Double(fb.palette[p + 2]) * 0.114
            return UInt8(ramp + Int(Swift.min(Swift.max((luma / 255 * 31).rounded(.toNearestOrEven), 0), 31)))
        }
        return try CAMImage.encodeFrame(width: Framebuffer.width, height: Framebuffer.height, pixels: px)
    }

    /// A SCRIPT.DAT with only the system task slots of `template`; counts follow the kept slots.
    /// ASSUMPTION: bitmap/flag tables (entries 4, 5) stay as in the template.
    public static func systemScriptDat(template: ScriptDat) throws -> [UInt8] {
        var sd = template
        sd.slots = sd.slots.filter { $0.index < systemSlots }
        var counts = [Int](repeating: 0, count: 32)
        for s in sd.slots { counts[Int(s.a[8] & 0x1f)] += 1 }
        sd.classCounts = counts
        sd.kernel.put(sd.slots.count, at: 0x10, 2)
        return try sd.encode()
    }

    /// A live script process of the world as the writer sees it (world.py `process_states`): `timed` = a TIMED native (subtitle / sound
    /// handle) with its ticks left, `ramp` = a MODIFYVAREVERYNTH ramp (value, step, end, start, period, ticks to the next step); else a
    /// script process: its block's definition number in `script`, `pc` (the .SCP offset of the next statement), `pc0`, locals, current
    /// figure / item (upper case), LINKMETOCAMERAS names, ticks left of a WAIT and the handles it waits for, the handles of its pending
    /// CALL children, its declared local count (nil = the locals' count), figure index and suspended bit.
    public struct TaskState: Sendable {
        public var handle: Int
        public var timed: Int? = nil
        public var ramp: (cur: Int, step: Int, end: Int, start: Int, period: Int, left: Int)? = nil
        public var hook = false          // the CAPTUREKEYBOARD hook's idle process (the PLAY record links its slot)
        public var missile: (item: String, owner: String?, range: Int, spin: [Int])? = nil     // a missile in flight: its item, owner figure, range, spin
        public var script = "", block = 0, pc = 0, pc0 = 0, locals: [Int] = [], cur = "", cameras: [String] = [], wait = 0, blockers: [Int] = []
        public var calls: [Int] = [], nlocals: Int? = nil, figIndex = 0, suspended = false     // pending CALL children, declared local count, FIGURE index, suspended bit
        public init(handle: Int) { self.handle = handle }
    }

    static let procVtable = 0x3031, waitVtable = 0x6677, rampVtable = 0x2ea0, listEnd = 0x408
    static let timelineVtable = 0x307f   // a `[` block's process (3754 bytes: +0xea2 two clock values, FUN_10d0_6b03)
    static let motionVtable = 0x46f5     // a figure's motion task (FUN_10e0_0000, type 0x108, 77 bytes): +0x32 motion name, +0x4b started; B = the figure's id
    // A missile in flight (FIRE / MAKEMISSILE, ctor FUN_10e0_0440): 86 bytes, type 0x10c. A: +0x38 serial (the handle), +0x3c the owning process
    // (restored from B, FUN_10b8_0d67), +0x40 the travel sound object, +0x44 the owner figure and +0x52 the missile item (far pointers, read back
    // from B only when nonzero, FUN_10e0_12b7), +0x48 s32 range, +0x4c/4e/50 s16 spin. B (FUN_10e0_135a): the task lists, the owning process's
    // slot (FUN_10b8_0d0b), then the owner figure's and the item's object ids (FUN_1128_0e84). The item is an ordinary ITEM record.
    static let missileVtable = 0x47a9, missileType = 0x10c, missileSize = 0x56
    static let waits = 0x2000, waited = 0x4000     // list2 entries: 0x2000|id = this task waits for id, 0x4000|id = task id waits for this one

    /// (object+0x41, whether the block is a `[` timeline) of a process of definition `block` (1-based) of `script` stopped at .SCP
    /// offset `pc`: the open braces from the definition's first character to pc, the timeline's `[` counting as one. The interpreter
    /// raises it at `{` and lowers it at `}` and ends the process at 0 (FUN_10c0_2d1e); both original saves hold exactly this count
    /// (savewrite.block_nesting).
    static func blockNesting(_ game: GameFolder, script: String, block: Int, pc: Int) -> (depth: Int, timeline: Bool) {
        guard let d = try? game.read("SCRIPT/" + script) else { return (1, false) }
        let re = try! NSRegularExpression(pattern: #""[^"]*"|//[^\n]*|\[[ \t]*(\w*)|\{[ \t]*(\w+)|(?<!\d):(?!\d)[ \t]*(\w*)"#)
        let skip = try! NSRegularExpression(pattern: #""[^"]*"|//[^\n]*"#)
        let text = latin1String(d) as NSString
        let starts = re.matches(in: text as String, range: NSRange(location: 0, length: text.length)).map(\.range.location).filter {
            let c = text.character(at: $0)
            return c != 0x22 && c != 0x2f
        }
        guard block > 0, block <= starts.count else { return (1, false) }
        let start = starts[block - 1]
        let timeline = text.character(at: start) == 0x5b
        let body = text.substring(with: NSRange(location: start, length: Swift.max(Swift.min(pc, text.length) - start, 0))) as NSString
        let code = skip.stringByReplacingMatches(in: body as String, range: NSRange(location: 0, length: body.length), withTemplate: "")
        return (Swift.max(1, (timeline ? 1 : 0) + code.filter { $0 == "{" }.count - code.filter { $0 == "}" }.count), timeline)
    }

    /// {vtable: Slot} clean task objects of the shipped GAMEDAT (task_templates): per class the first non-system slot; a script process
    /// stopped at its block's top level with no links and no locals (CELLTWOBARS), a timeline process (ANIMGUARD), a Wait task, a
    /// MODIFYVAREVERYNTH task and a motion task. Also {vtable: class-name pointer}.
    static func taskTemplates(_ game: GameFolder) throws -> (slots: [Int: Slot], ptrs: [Int: (Int, Int)]) {
        guard let g = game.gamedat else { throw FormatError("GAMEDAT not found next to \(game.url.path)") }
        let sd = try SaveState.load(directory: g).script
        var out: [Int: Slot] = [:], ptrs: [Int: (Int, Int)] = [:]
        for s in sd.slots {
            ptrs[s.vtable] = sd.namePtrs[s.index]
            if out[s.vtable] != nil || s.index < systemSlots { continue }
            if s.kind == .proc, let pr = try s.proc() {
                if !pr.l1.isEmpty || !pr.l2.isEmpty || s.a[0x70] != 0 || s.a[0x41] != 1 || s.a[0x75..<0x7f].contains(where: { $0 != 0 }) { continue }
            }
            out[s.vtable] = s
        }
        return (out, ptrs)
    }

    /// The two MLIST objects of a task (+0x16, +0x20: vtable, count, ?, far pointer): their counts, and a pointer that is nonzero
    /// exactly when the list has entries. The list loader reads the entries only behind a nonzero pointer (FUN_1240_08db) and the
    /// original writes an empty list as count 0 with no entries and no terminator (savewrite.set_lists).
    static func setLists(_ a: inout [UInt8], _ l1: [Int], _ l2: [Int]) {
        for (at, lst) in [(0x16, l1), (0x20, l2)] {
            a.put(lst.count, at: at + 2, 2); a.put(0, at: at + 4, 2); a.put(0, at: at + 6, 2); a.put(lst.isEmpty ? 0 : 1, at: at + 8, 2)
        }
    }

    /// A SCRIPT.DAT holding the system slots of `template` and the world's tasks, written as the original's kernel serializer would
    /// (FUN_1230_2208) in the shapes Resume reads (Proc / Slot): a script process per task with a block (slot A = a clean process
    /// object of the shipped GAMEDAT, taskTemplates, with this process's header, brace depth, local count and links set; B =
    /// Proc.encode); a Wait task (remaining ticks at A+0x40, owner = the process) for a sleeping one; a MODIFYVAREVERYNTH task for a
    /// ramp; a Wait task owned by no process for a TIMED subtitle / sound handle (the original's subtitle task, class 0x4901, is not
    /// written; ASSUMPTION: a plain timer stands in). A link "P waits for T" (a CALL child, a SUSPENDWHILE target, the own Wait task)
    /// is written as the kernel makes it (FUN_1238_0f48): T in P's list1, 0x2000|T in P's list2, 0x4000|P in T's list2; a CALL
    /// child's +0x71 names the caller (the process its RETURN value goes to, 10c0:3968), which waits at the CALL statement with +0x46
    /// set. `motions` {figure: motion} add a motion task per figure whose script motion is still running (class 0x46f5: the name at
    /// A+0x32, started flag A+0x4b, B = the figure's object id); the load fixup restarts it from frame 0 (FUN_1088_4d67).
    /// -> (bytes, {slot: serial}, next serial, {figure: motion task slot})
    static func taskScriptDat(template: ScriptDat, game: GameFolder, tasks: [TaskState], oids: [String: Int], motions: [String: String] = [:]) throws
        -> (bytes: [UInt8], serials: [Int: Int], nextSerial: Int, motionSlots: [String: Int]) {
        var sd = template
        let (tmpl, ptrs) = try taskTemplates(game)
        var slots = sd.slots.filter { $0.index < systemSlots }
        var free = systemSlots
        func nextFree() throws -> Int {
            if free >= ScriptDat.nSlots { throw FormatError("more tasks than kernel slots") }
            defer { free += 1 }
            return free
        }
        var byHandle: [Int: Int] = [:], waits: [Int: Int] = [:]
        for t in tasks {
            byHandle[t.handle] = try nextFree()
            if t.wait != 0 { waits[t.handle] = try nextFree() }
        }
        var serials: [Int: Int] = [:]
        var nextSerial = (tasks.map(\.handle) + [0]).max()! + 1
        var links: [(waiter: Int, awaited: Int)] = []           // in the order the waits began
        for t in tasks {
            let me = byHandle[t.handle]!
            links += t.blockers.compactMap { byHandle[$0] }.map { (me, $0) }
            if let w = waits[t.handle] { links.append((me, w)) }
        }
        var caller: [Int: Int] = [:]
        for t in tasks { for h in t.calls { if let c = byHandle[h], caller[c] == nil { caller[c] = byHandle[t.handle]! } } }

        func lists(_ slot: Int) -> (l1: [Int], l2: [Int]) {
            let l1 = links.filter { $0.waiter == slot }.map(\.awaited)
            let l2 = links.filter { $0.awaited == slot }.map { waited | $0.waiter } + links.filter { $0.waiter == slot }.map { Self.waits | $0.awaited }
            return (l1.isEmpty ? [] : l1 + [listEnd], l2.isEmpty ? [] : l2 + [listEnd])
        }
        func slotObj(_ vtable: Int, _ index: Int, _ serial: Int, _ l1: [Int] = [], _ l2: [Int] = []) throws -> [UInt8] {
            guard let t = tmpl[vtable] else { throw FormatError("the shipped GAMEDAT has no task of class 0x\(String(vtable, radix: 16))") }
            var a = t.a
            a.put(index, at: 2, 2)
            a.put(serial, at: 0x38, 4)
            setLists(&a, l1, l2)
            serials[index] = serial
            sd.namePtrs[index] = ptrs[vtable]!
            return a
        }
        func u16s(_ v: [Int]) -> [UInt8] { v.flatMap { [UInt8].le($0, 2) } }
        func taskB(_ l1: [Int], _ l2: [Int], _ owner: Int) -> [UInt8] { u16s(l1) + u16s(l2) + u16s([owner]) }
        func waitTask(_ index: Int, _ serial: Int, _ ticks: Int, _ owner: Int) throws -> Slot {
            let (l1, l2) = lists(index)
            var w = try slotObj(waitVtable, index, serial, l1, l2)
            w.put(Swift.min(ticks, 0xffff), at: 0x40, 2); w.put(Swift.min(ticks, 0xffff), at: 0x42, 2)
            w.put(0, at: 0x3c, 2); w.put(owner != 0 ? 1 : 0, at: 0x3e, 2)       // +0x3c: the owner's pointer, read back only when nonzero (FUN_10b8_0d67)
            return Slot(index: index, a: w, b: taskB(l1, l2, owner))
        }
        for t in tasks {
            let i = byHandle[t.handle]!
            if let m = t.missile {
                // the header of an engine-made task of the same base (the motion task: class 1, its class name), the missile's own fields
                // after it. ASSUMPTION: no owning process (+0x3c 0: the port does not keep which process fired it) and no travel sound
                // (+0x40 0: a voice does not survive a load)
                let (l1, l2) = lists(i)
                guard let motion = tmpl[motionVtable] else { throw FormatError("the shipped GAMEDAT has no task of class 0x\(String(motionVtable, radix: 16))") }
                var a = Array(motion.a.prefix(0x38)) + [UInt8](repeating: 0, count: missileSize - 0x38)
                a.put(missileVtable, at: 0, 2); a.put(i, at: 2, 2); a.put(missileType, at: 6, 2); a.put(t.handle, at: 0x38, 4)
                setLists(&a, l1, l2)
                let owner = oids[(m.owner ?? "").uppercased()] ?? 0, item = oids[m.item.uppercased()] ?? 0
                a.put(0, at: 0x3c, 4); a.put(0, at: 0x40, 4); a.put(owner != 0 ? 1 : 0, at: 0x44, 4); a.put(m.range, at: 0x48, 4)
                for k in 0..<3 { a.put(m.spin[k] & 0xffff, at: 0x4c + 2 * k, 2) }
                a.put(item != 0 ? 1 : 0, at: 0x52, 4)
                serials[i] = t.handle
                sd.namePtrs[i] = ptrs[motionVtable]!
                slots.append(Slot(index: i, a: a, b: taskB(l1, l2, 0) + u16s([owner, item])))
                continue
            }
            if let timed = t.timed {                        // a subtitle / sound handle: a Wait task owned by no process, serial = the handle
                slots.append(try waitTask(i, t.handle, timed, 0))
                continue
            }
            if let r = t.ramp {
                var a = try slotObj(rampVtable, i, t.handle)
                a.put(r.cur, at: 0x45, 4)
                a.put(r.step, at: 0x49, 2); a.put(r.end, at: 0x4b, 2); a.put(r.start, at: 0x4d, 2); a.put(r.period, at: 0x4f, 2); a.put(r.left, at: 0x51, 2)
                slots.append(Slot(index: i, a: a, b: taskB([], [], 0)))
                continue
            }
            let (depth, timeline) = blockNesting(game, script: t.script.uppercased(), block: t.block, pc: t.pc)
            let (l1, l2) = lists(i)
            var a = try slotObj(timeline ? timelineVtable : procVtable, i, t.handle, l1, l2)
            let flags = (try? a.u16(0xe)) ?? 0                // bit 0: suspended (camera links, SUSPENDPROCESS; the kernel skips it, 1230:0259)
            a.put((flags & ~1) | (t.suspended ? 1 : 0), at: 0xe, 2)
            a.put(0, at: 0x3c, 4); a[0x40] = 0xff; a[0x41] = UInt8(truncatingIfNeeded: depth)
            a.put(t.figIndex & 0xffff, at: 0x42, 2); a.put(0, at: 0x44, 2); a[0x46] = t.calls.isEmpty ? 0 : 1
            a.put(0, at: 0x47, 4)                            // +0x47: the RETURN value of the CALL child (taken when +0x46 is set)
            let n = t.nlocals ?? t.locals.count
            let waitSlot = caller[i] ?? 0
            a.put(n != 0 ? 1 : 0, at: 0x6c, 4); a[0x70] = UInt8(truncatingIfNeeded: n)      // locals pointer, count
            a.put(waitSlot, at: 0x71, 2); a.put(0, at: 0x73, 2)                              // +0x71: the caller
            a.replaceSubrange(0x75..<0xe7b, with: [UInt8](repeating: 0, count: 0xe7b - 0x75))     // per-depth ELSE flags, statement buffers, CALL arguments, variable pointers: scratch
            let cur = oids[t.cur] ?? 0
            let rec = Proc(l1: l1, l2: l2, owner: 0, objA: cur, objB: 0, curObj: cur, waitSlot: waitSlot, block: t.block,
                           scriptRaw: Array(latin1Bytes(t.script.uppercased()).prefix(12)).padded(13), label2: 0, fileIdx: 1000, pc: t.pc, pc0: t.pc0,
                           locals: Array((t.locals + [Int](repeating: 0, count: n)).prefix(n)).map { $0 & 0xffffffff }, objs: t.cameras.compactMap { oids[$0] })
            slots.append(Slot(index: i, a: a, b: rec.encode()))
            if let w = waits[t.handle] {
                slots.append(try waitTask(w, nextSerial, t.wait, i))
                nextSerial += 1
            }
        }
        var motionSlots: [String: Int] = [:]
        for fig in motions.keys.sorted() {
            guard let oid = oids[fig], let name = motions[fig] else { continue }
            let i = try nextFree()
            var a = try slotObj(motionVtable, i, nextSerial)
            nextSerial += 1
            a.replaceSubrange(0x32..<0x4b, with: Array(latin1Bytes(name.lowercased()).prefix(24)).padded(25))
            a[0x4b] = 1; a[0x4c] = 0
            slots.append(Slot(index: i, a: a, b: [UInt8].le(oid, 2)))
            motionSlots[fig] = i
        }
        sd.slots = slots.sorted { $0.index < $1.index }
        var counts = [Int](repeating: 0, count: 32)
        for s in sd.slots { counts[Int(s.a[8] & 0x1f)] += 1 }
        sd.classCounts = counts
        let groups = Set([0] + sd.slots.map(\.group))          // entry 4: a bit per task group id in use (FUN_1230_2ea2)
        sd.bitmap = (0..<sd.bitmap.count).map { k in UInt8(truncatingIfNeeded: groups.filter { $0 / 8 == k }.reduce(0) { $0 + (1 << ($1 % 8)) }) }
        sd.kernel.put(sd.slots.count, at: 0x10, 2)
        return (try sd.encode(), serials, nextSerial, motionSlots)
    }

    /// A world item as the writer sees it: owner, slot, floor position and orientation rows.
    public struct ItemState: Sendable {
        public var owner: String? = nil, slot: String? = nil, pos: SIMD3<Double>? = nil, matrix: [[Double]]? = nil
    }

    /// An ITEM record (191 bytes) brought up to the world's item `state` and `oids` {figure name: object id} (savewrite.patch_item): an
    /// item on the floor gets holder 0, no hand, its position and orientation (256 = 1.0); a carried item gets its holder's object id
    /// and its hand (the slot name cut to 8 characters, empty = inventory), the record's position stays (ASSUMPTION: the engine keeps the hand's world
    /// position there; the hand string is the property value in upper case, no sample holds a hand). Only fields that differ are
    /// rewritten. A holder that is not a record of this level leaves the record alone (GAP: a new game has no PLAY record).
    static func patchItem(_ data: [UInt8], _ state: ItemState, _ oids: [String: Int]) -> [UInt8] {
        var b = data
        let holder: Int, hand: String
        if let owner = state.owner {
            guard let oid = oids[owner] else { return data }
            holder = oid; hand = state.slot.flatMap { $0 == "INVENTORY" ? nil : String($0.prefix(8)) } ?? ""
        } else {
            holder = 0; hand = ""
            if let p = state.pos {
                let v = [p.x, p.y, p.z].map { Int($0.rounded(.toNearestOrEven)) }
                if v != (0..<3).map({ (try? b.s32(9 + 4 * $0)) ?? 0 }) { for (i, x) in v.enumerated() { b.put(x, at: 9 + 4 * i, 4) } }
            }
            if let m = state.matrix {
                let v = m.flatMap { $0 }.map { Int((256 * $0).rounded(.toNearestOrEven)) }
                if v != (0..<9).map({ (try? b.s32(147 + 4 * $0)) ?? 0 }) { for (i, x) in v.enumerated() { b.put(x, at: 147 + 4 * i, 4) } }
            }
        }
        if (try? b.u16(22)) != holder { b.put(holder, at: 22, 2) }
        if b.cString(24, 33) != hand {
            b.replaceSubrange(24..<33, with: Array(hand.utf8) + [UInt8](repeating: 0, count: 9 - hand.utf8.count))
        }
        return b
    }

    /// A figure as the writer sees it (world.py `figure_states`): `pos` z includes the current motion's first-frame root z (Resume takes
    /// it off again), `flags` are ObjRec flag bits, `enemy` an upper-case figure name ("PLAYER" = the player, "" = none), `ai` the AI name
    /// (+0x178, "" = none), `vel` the velocity (s32[3] at 58), `viewCams` a FIGR's viewing cameras (nil = not written).
    public struct FigureState: Sendable {
        public var type: String, pos: SIMD3<Double>, heading: Double, motion: String, flags: Int, locals: [Int], enemy: String, hold: Int
        public var inTrig: [UInt8]? = nil
        public var ai = "", vel: [Int]? = nil, viewCams: [String]? = nil
        public var motionTask = false, motionSlot = 0     // a running MOTION ... CONTINUE: its motion task (+0x13d = the slot)
        public var teeter: Bool? = nil, zCap: Int? = nil, foot: Int? = nil, avoid: [(name: String, radius: Int)]? = nil     // +0x146, +0x14e, +0x88, +0x1f3 (nil = not written)
        public var aiHandle = 0, aiSlot = 0, hookSlot: Int? = nil     // the AI process (+0x152 = its slot), a PLAY's CAPTUREKEYBOARD hook process
    }

    static let managedFlags = ObjRec.flagGravity | ObjRec.flagCollisions | ObjRec.flagHidden | ObjRec.flagInvulnerable | ObjRec.flagBouncy | ObjRec.flagCombat

    /// A FIGR / PLAY record brought up to the world's figure `state`: the fields Resume reads back (savewrite.patch_figure). `oids`
    /// {figure name: object id} resolve the enemy; the InTrig bytes are written when their count matches the record's. Also the AI name,
    /// the velocity and a FIGR's viewing-camera list (a different count changes the record length).
    static func patchFigure(_ tag: String, _ data: [UInt8], _ state: FigureState, _ oids: [String: Int]) throws -> [UInt8] {
        var rec = try ObjRec(tag: tag, raw: data)
        if let cams = state.viewCams, tag == "FIGR", rec.viewCams.map({ $0.uppercased() }) != cams {      // u16 count + 9-byte names (+0x1a5 list)
            let b = rec.buf, nc = rec.t["ncams"] ?? 0, n = try b.u16(nc)
            let names = cams.flatMap { Array(latin1Bytes($0).prefix(8)).padded(9) }
            rec = try ObjRec(tag: tag, raw: b.slice(0, nc) + [UInt8].le(cams.count, 2) + names + b.slice((rec.t["cams"] ?? 0) + 9 * n, b.count))
        }
        if !state.ai.isEmpty { rec.setAIName(state.ai) }
        rec.pos = [state.pos.x, state.pos.y, state.pos.z].map { Int($0.rounded(.toNearestOrEven)) }
        if let v = state.vel { rec.velocity = v }
        rec.heading = state.heading
        rec.flags = (rec.flags & ~managedFlags & 0xff) | state.flags
        rec.locals = state.locals
        rec.motion = state.motion
        rec.enemy = state.enemy.isEmpty ? 0 : oids[state.enemy] ?? 0
        rec.motionTask = state.motionSlot                       // +0x13d: the motion task's slot (0 = none)
        rec.aiTask = state.aiSlot                               // +0x152: the AI process's slot (0 = none)
        if let v = state.teeter { rec.teeter = v }              // +0x146: the whoah teeter
        if let v = state.zCap { rec.zCap = v }                  // +0x14e: FLOATATHEIGHT ... MAXIMUM
        if let v = state.foot { rec.foot = v }                  // model+0x88: F
        if let v = state.avoid {                                // +0x1f3 count, 8 x (u16 waypoint id, u16 radius)
            rec.avoid = v.compactMap { a in oids[a.name].map { (waypoint: $0, radius: a.radius) } }
        }
        if tag == "PLAY", let v = state.hookSlot { rec.hookTask = v }     // DAT_1290_6530: the CAPTUREKEYBOARD hook's slot
        rec.aiOff = state.hold
        if let t = state.inTrig { rec.inTrig = t }
        return rec.encode()
    }

    /// A PLAY record for a level that has none (a new game's Lex is created by script): `template` (the shipped GAMEDAT CHAOS.IFF's)
    /// with its InTrig block resized to `triggers` clear bytes (savewrite.player_record).
    static func playerRecord(_ template: [UInt8], triggers: Int) throws -> [UInt8] {
        let rec = try ObjRec(tag: "PLAY", raw: template)
        let l = rec.t["L"] ?? 0, p = rec.t["intrig"] ?? 0
        let out = rec.buf.slice(0, l) + [UInt8].le(triggers, 2) + [UInt8](repeating: 0, count: triggers) + rec.buf.slice(p + rec.inTrig.count, rec.buf.count)
        _ = try ObjRec(tag: "PLAY", raw: out)                   // the layout still parses
        return out
    }

    /// A FIGR / PLAY record with its InTrig block resized to `triggers` bytes, all clear (patchFigure fills it; savewrite.resize_intrig).
    static func resizeInTrig(_ raw: [UInt8], _ tag: String, triggers: Int) throws -> [UInt8] {
        let rec = try ObjRec(tag: tag, raw: raw)
        let l = rec.t["L"] ?? 0, p = rec.t["intrig"] ?? 0, n = try rec.buf.u16(l)
        let out = rec.buf.slice(0, l) + [UInt8].le(triggers, 2) + [UInt8](repeating: 0, count: triggers) + rec.buf.slice(p + n, rec.buf.count)
        _ = try ObjRec(tag: tag, raw: out)                      // the layout still parses
        return out
    }

    /// The level IFFs of `levelDir`, sorted by name (the order the templates are searched in).
    private static func levelFiles(_ levelDir: URL) throws -> [LevelIff] {
        try FileManager.default.contentsOfDirectory(atPath: levelDir.path).sorted().filter { $0.uppercased().hasSuffix(".IFF") }
            .map { try LevelIff.parse([UInt8](try Data(contentsOf: levelDir.appendingPathComponent($0)))) }
    }

    /// A FIGR record for a figure a script made (CREATEFIGURE): one of the same type from any level IFF in `levelDir`, else the first
    /// FIGR record there (savewrite.figure_template). ASSUMPTION: the other tail fields (task links, scratch) fit; patchFigure sets the
    /// state Resume reads.
    static func figureTemplate(_ levelDir: URL, kind: String) throws -> [UInt8]? {
        var first: [UInt8]?
        for iff in try levelFiles(levelDir) {
            for c in iff.chunks where c.id == "FIGR" {
                if c.data.cstr.uppercased() == kind.uppercased() { return c.data }
                first = first ?? c.data
            }
        }
        return first
    }

    /// The first 191-byte ITEM record of any level IFF in `levelDir` (a level without ITEM records, TUNROOM, still gets its carried
    /// items written): newItemRecord overwrites the fields that matter. nil if no level has one (savewrite.item_template).
    static func itemTemplate(_ levelDir: URL) throws -> [UInt8]? {
        for iff in try levelFiles(levelDir) {
            if let c = iff.chunks.first(where: { $0.id == "ITEM" && $0.data.count == 191 }) { return c.data }
        }
        return nil
    }

    /// An ITEM record (191 bytes) for an item a script made (CREATEITEM / INDIVIDUALIZE): `template` (another ITEM record of the level)
    /// with record name = the item type, instance name = its key, no holder, hand or flags, its object locals; patchItem then sets the
    /// holder or the floor position. ASSUMPTION: the template's other fields (extents, scratch) fit any item (savewrite.new_item_record).
    static func newItemRecord(_ template: [UInt8], name: String, kind: String, locals: [Int]) -> [UInt8] {
        var b = template
        b.replaceSubrange(0..<9, with: Array(latin1Bytes(kind.uppercased()).prefix(8)).padded(9))
        b.replaceSubrange(33..<58, with: Array(latin1Bytes(name.uppercased()).prefix(24)).padded(25))
        b[21] = 0
        b.put(0, at: 22, 2)
        b.replaceSubrange(24..<33, with: [UInt8](repeating: 0, count: 9))
        for (i, v) in (locals + [Int](repeating: 0, count: 10)).prefix(10).enumerated() { b.put(v, at: 106 + 4 * i, 4) }
        return b
    }

    /// The upper-case name of a record: its instance name (+33) for a FIGR / PLAY / ITEM one, else / when empty the type name.
    private static func recName(_ id: String, _ d: [UInt8]) -> String {
        let inst = ["FIGR", "PLAY", "ITEM"].contains(id) && d.count >= 58 ? d.cString(33, 58) : ""
        return (inst.isEmpty ? d.cString(0, 9) : inst).uppercased()
    }

    /// A level object record with the pad byte the file had (nil: by size).
    struct LevelRecord { var id: String, data: [UInt8], pad: [UInt8]? = nil }

    /// The object records of `level` as the save writes them, before patching (savewrite.level_layout): the LevelIff (its chunks without
    /// the killed figures), the records in object order (VERS excluded), {object name: 1-based id}, the level's trigger count, whether the
    /// record list changed. The killed figures' FIGR records go; a new game's player gets a PLAY record (playerRecord); a figure a script
    /// made gets a FIGR record (figureTemplate); then the world's items (`itemOrder`, the world's creation order) follow the other records
    /// in that order: their own records moved there, and an item a script made gets one (newItemRecord) when it is carried by an object of
    /// the level or lies on the floor. The order is the object list's, which the inventory lists the player's items in
    /// (World.inventory_items, FUN_10d0_0000), so a loaded game shows them as the saved one did. With `itemStates` given and `dropItems`,
    /// the ITEM records of items that are not among them go: the level writer (FUN_1148_1232) writes only the objects in the list, so an
    /// item carried off to another level, or destroyed, has no record.
    static func levelLayout(levelDir: URL, level: String, killed: Set<String> = [], player: String? = nil, figureStates: [String: FigureState] = [:],
                            figureOrder: [String] = [], playerTemplate: [UInt8]? = nil, itemStates: [String: ItemState]? = nil, itemOrder: [String] = [],
                            itemExtra: [String: (type: String, locals: [Int])] = [:], dropItems: Bool = true) throws
        -> (iff: LevelIff, objects: [LevelRecord], oids: [String: Int], triggers: Int, changed: Bool) {
        var iff = try LevelIff.parse([UInt8](try Data(contentsOf: levelDir.appendingPathComponent(level + ".IFF"))))
        let killedUp = Set(killed.map { $0.uppercased() })
        let keep = iff.chunks.filter { c in
            c.id != "FIGR" || !killedUp.contains(((c.data.cString(33, 58).isEmpty ? c.data.cString(0, 9) : c.data.cString(33, 58))).uppercased())
        }
        var changed = keep.count != iff.chunks.count
        iff.chunks = keep
        var objects = iff.chunks.filter { $0.id != "VERS" }.map { LevelRecord(id: $0.id, data: $0.data, pad: $0.pad) }    // object ids are 1-based indexes
        let triggers = objects.filter { $0.id == "IMAG" }.count
        func fixed(_ kind: String, _ rec: [UInt8], _ name: String) -> [UInt8] {
            Array(latin1Bytes(kind.uppercased()).prefix(8)).padded(9) + rec.slice(9, 33) + Array(latin1Bytes(name.uppercased()).prefix(24)).padded(25) + rec.slice(58, rec.count)
        }
        if let player, let playerTemplate, let ps = figureStates[player.uppercased()], !objects.contains(where: { $0.id == "PLAY" }) {
            objects.append(LevelRecord(id: "PLAY", data: fixed(ps.type, try playerRecord(playerTemplate, triggers: triggers), player)))
            changed = true
        }
        if !figureStates.isEmpty {                              // figures a script made (CREATEFIGURE) are objects too: a FIGR record each
            let have = Set(objects.filter { $0.id == "FIGR" || $0.id == "PLAY" }.map { recName($0.id, $0.data) })
            for name in figureOrder.isEmpty ? figureStates.keys.sorted() : figureOrder {
                guard let state = figureStates[name], !have.contains(name.uppercased()), !(player != nil && name.uppercased() == player!.uppercased()),
                      let t = try figureTemplate(levelDir, kind: state.type) else { continue }
                objects.append(LevelRecord(id: "FIGR", data: fixed(state.type, try resizeInTrig(t, "FIGR", triggers: triggers), name)))
                changed = true
            }
        }
        if let itemStates {
            var records: [String: [UInt8]] = [:], firstRecord: String?       // a duplicate name keeps its first place and its last record (Python dict)
            for o in objects where o.id == "ITEM" && o.data.count == 191 {
                let n = recName(o.id, o.data)
                if records[n] == nil && firstRecord == nil { firstRecord = n }
                records[n] = o.data
            }
            let holders = Set(objects.filter { $0.id == "FIGR" || $0.id == "PLAY" }.map { recName($0.id, $0.data) }).union(player != nil ? ["PLAYER"] : [])
            let template = try firstRecord.flatMap { records[$0] } ?? itemTemplate(levelDir)
            var moved: [LevelRecord] = []
            for key in itemOrder.isEmpty ? itemStates.keys.sorted() : itemOrder {
                let name = key.uppercased()
                guard let state = itemStates[key] else { continue }
                if let r = records[name] {
                    moved.append(LevelRecord(id: "ITEM", data: r))
                } else if let extra = itemExtra[name], let template, state.owner != nil || state.pos != nil,
                          state.owner.map({ holders.contains($0.uppercased()) }) ?? true {
                    moved.append(LevelRecord(id: "ITEM", data: newItemRecord(template, name: name, kind: extra.type, locals: extra.locals)))
                }
            }
            let names = Set(moved.map { recName($0.id, $0.data) })
            let inFile = objects.filter { $0.id == "ITEM" && $0.data.count == 191 && names.contains(recName($0.id, $0.data)) }.map { recName($0.id, $0.data) }
            let new = moved.map { recName($0.id, $0.data) }.filter { records[$0] == nil }
            let rest: [LevelRecord]
            if moved.map({ recName($0.id, $0.data) }) == inFile + new {
                // the world's order is the file's, new items last: the records stay where they are, as the original's object list keeps
                // them (re/out/native_save round trip), so the ids of the objects after them do not move
                rest = objects.filter { !($0.id == "ITEM" && $0.data.count == 191 && !names.contains(recName($0.id, $0.data)) && dropItems) }
                moved = Array(moved[inFile.count...])
            } else {
                rest = objects.filter { !($0.id == "ITEM" && $0.data.count == 191 && (names.contains(recName($0.id, $0.data)) || dropItems)) }
            }
            let after = rest + moved
            if after.count != objects.count || zip(after, objects).contains(where: { $0.id != $1.id || $0.data != $1.data }) { changed = true }
            objects = after
        }
        var oids: [String: Int] = [:]
        for (i, o) in objects.enumerated() {
            if oids[recName(o.id, o.data)] == nil { oids[recName(o.id, o.data)] = i + 1 }
            if o.id == "PLAY", oids[o.data.cString(0, 9).uppercased()] == nil { oids[o.data.cString(0, 9).uppercased()] = i + 1 }
        }
        if let player { oids["PLAYER"] = oids[player.uppercased()] ?? 0 }
        return (iff, objects, oids, triggers, changed)
    }

    /// What a level the player left keeps (World.levelItems, levelFigures): item states, item extra, item order, and the kept figures'
    /// states (nil = not known: the level's FIGR records stay) with their order.
    public typealias OtherLevel = (states: [String: ItemState], extra: [String: (type: String, locals: [Int])], order: [String],
                                   figures: [String: FigureState]?, figureOrder: [String])

    /// {file name: bytes} of a save. `base` = SaveState of the native directory the world was loaded from (its MISC fields,
    /// SCRIPT.DAT and VARS table are kept) or nil (zeros / initial variables / shipped GAMEDAT headers). variables {NAME: int};
    /// lists in file order; levelDir holds the level IFFs; positions {FIGR instance name or PLAY name (upper case): (x, y, z)}
    /// update the records of `level` (upper case; pos at record offset +9). `game` supplies the shipped GAMEDAT and SCRIPT/VARS.DEF.
    /// figureStates {FIGR instance name or the player's name (upper case): state} bring the figure records up to the world's figures
    /// (patchFigure); `player` names the player, and when the level has no PLAY record one is appended from `playerTemplate`.
    /// `tasks` (World.processStates) replace SCRIPT.DAT's processes (taskScriptDat). itemExtra {item name: (type, object locals)} and `missiles` {item name: (velocity, flags)} of the missiles in flight: every
    /// ITEM record of the world's items gets its locals, and an item without a record (one a script made) gets one. `killed` figures
    /// (instance names) lose their FIGR record. The record order is levelLayout's; `figureOrder` / `itemOrder` are the world's creation
    /// orders of figureStates / itemStates (sorted names when empty). otherLevels {level: OtherLevel}: the items and
    /// figures kept with a level the player left (World.levelItems, levelFigures); that level's file gets them as the current one does
    /// (FUN_1148_1404 wrote it at the level change): with figure states given, the FIGR records of figures not among them are dropped. Other levels' files are copied as they are.
    public static func buildFiles(slotName: String, level: String, camera: String?, autoCamera: Bool, variables: [String: Int],
                                  lists: [LogList], levelDir: URL, positions: [String: SIMD3<Double>], base: SaveState?,
                                  game: GameFolder, itemStates: [String: ItemState]? = nil,
                                  figureStates: [String: FigureState] = [:], player: String? = nil, playerTemplate: [UInt8]? = nil,
                                  tasks: [TaskState]? = nil, itemExtra: [String: (type: String, locals: [Int])] = [:],
                                  missiles: [String: (vel: [Int], flags: Int)] = [:], killed: Set<String> = [],
                                  figureOrder: [String] = [], itemOrder: [String] = [],
                                  otherLevels: [String: OtherLevel] = [:]) throws -> [String: [UInt8]] {
        let tmpl: SaveState
        if let base { tmpl = base } else {
            guard let g = game.gamedat else { throw FormatError("GAMEDAT not found next to \(game.url.path)") }
            tmpl = try SaveState.load(directory: g)
        }
        var misc = base != nil ? try Misc(base!.misc.raw) : Misc.new(level: level + ".IFF")
        if base == nil { misc.objA = 4; misc.objB = 5 }                      // ASSUMPTION: obj ids 4, 5 as in every native sample
        misc.saveName = slotName; misc.level = level + ".IFF"; misc.camera = camera ?? ""; misc.autoCamera = autoCamera ? 1 : 0
        var script = base != nil ? try base!.script.encode() : try systemScriptDat(template: tmpl.script)
        if base == nil { misc.serials = misc.serials.enumerated().map { $0 < systemSlots ? $1 : 0 } }
        let layout = try levelLayout(levelDir: levelDir, level: level, killed: killed, player: player, figureStates: figureStates, figureOrder: figureOrder,
                                     playerTemplate: playerTemplate, itemStates: itemStates, itemOrder: itemOrder, itemExtra: itemExtra)
        var states = figureStates
        if let tasks {
            let motions = states.filter { $0.value.motionTask }.mapValues(\.motion)
            let (bytes, serials, nextSerial, motionSlots) = try taskScriptDat(template: tmpl.script, game: game, tasks: tasks, oids: layout.oids, motions: motions)
            for (k, i) in motionSlots { states[k]?.motionSlot = i }
            let slotOf = Dictionary(serials.map { ($1, $0) }, uniquingKeysWith: { $1 })
            let hook = tasks.first { $0.hook }.flatMap { slotOf[$0.handle] } ?? 0
            for (k, v) in states {
                var v = v
                v.aiSlot = slotOf[v.aiHandle] ?? 0
                v.hookSlot = player != nil && k == player!.uppercased() ? hook : 0
                states[k] = v
            }
            script = bytes
            misc.serials = misc.serials.enumerated().map { $0 < systemSlots ? $1 : serials[$0] ?? 0 }
            misc.nextSerial = Swift.max(misc.nextSerial, nextSerial)
        }
        let items = try base?.vars.items ?? defaultVars(game)
        let vars = DefFile(head: tmpl.vars.head, kind: tmpl.vars.kind, items: items.map { ($0.name, variables[$0.name.uppercased()] ?? $0.value) })
        var files = ["MISC.DAT": misc.encode(), "SCRIPT.DAT": script, "VARS.DEF": vars.encode(), "SOUNDS.DEF": tmpl.sounds.encode(),
                     "LISTS.FLX": try Lists.fromLists(lists, template: tmpl.lists).encode()]
        let others = Dictionary(otherLevels.map { ($0.key.uppercased(), $0.value) }, uniquingKeysWith: { $1 })
        for n in try FileManager.default.contentsOfDirectory(atPath: levelDir.path).sorted() where n.uppercased().hasSuffix(".IFF") {
            let name = String(n.uppercased().dropLast(4))
            if name == level {
                files[n.uppercased()] = try encodeLevel(layout, positions: positions, figureStates: states, itemStates: itemStates, itemExtra: itemExtra,
                                                        missiles: missiles)
            } else if let other = others[name] {
                var gone = Set<String>()
                if let figs = other.figures {                    // the kept figures stay, every other FIGR record is a killed (or carried-off) one
                    let old = try LevelIff.parse([UInt8](try Data(contentsOf: levelDir.appendingPathComponent(n))))
                    gone = Set(old.chunks.filter { $0.id == "FIGR" }.map { recName($0.id, $0.data) }.filter { figs[$0] == nil })
                }
                let kept = try levelLayout(levelDir: levelDir, level: name, killed: gone, figureStates: other.figures ?? [:], figureOrder: other.figureOrder,
                                           itemStates: other.states, itemOrder: other.order, itemExtra: other.extra)
                files[n.uppercased()] = try encodeLevel(kept, figureStates: other.figures ?? [:], itemStates: other.states, itemExtra: other.extra)
            } else {
                files[n.uppercased()] = try LevelIff.parse([UInt8](try Data(contentsOf: levelDir.appendingPathComponent(n)))).encode()
            }
        }
        return files
    }

    /// The level file of a levelLayout, its records brought up to the world's state (positions, patchFigure, patchItem, locals)
    /// (savewrite.encode_level).
    static func encodeLevel(_ layout: (iff: LevelIff, objects: [LevelRecord], oids: [String: Int], triggers: Int, changed: Bool),
                            positions: [String: SIMD3<Double>] = [:], figureStates: [String: FigureState] = [:], itemStates: [String: ItemState]? = nil,
                            itemExtra: [String: (type: String, locals: [Int])] = [:], missiles: [String: (vel: [Int], flags: Int)] = [:]) throws -> [UInt8] {
        var iff = layout.iff
        var chunks = Array(iff.chunks.filter { $0.id == "VERS" }.prefix(1))
        var changed = layout.changed
        for o in layout.objects {
            var data = o.data
            let key = o.id == "FIGR" ? data.cString(33, 42) : o.id == "PLAY" ? data.cString(0, 9) : nil
            if let key, let p = positions[key.uppercased()], data.count >= 21 {
                let v = [p.x, p.y, p.z].map { Int($0.rounded(.toNearestOrEven)) }
                data = data.slice(0, 9) + v.flatMap { [UInt8].le($0, 4) } + data.slice(21, data.count)
            }
            if o.id == "FIGR" || o.id == "PLAY", !figureStates.isEmpty, let st = figureStates[recName(o.id, data)] { data = try patchFigure(o.id, data, st, layout.oids) }
            if o.id == "ITEM", data.count == 191, !(itemStates ?? [:]).isEmpty {
                let name = recName(o.id, data)
                if let st = itemStates?[name] {
                    data = patchItem(data, st, layout.oids)
                    if let extra = itemExtra[name] {
                        data.replaceSubrange(106..<146, with: (extra.locals + [Int](repeating: 0, count: 10)).prefix(10).flatMap { [UInt8].le($0, 4) })
                    }
                    if let m = missiles[name] {                     // a missile's item: its velocity (+0xc6) and flags (+0x34)
                        data[21] = UInt8(m.flags & 0xff)
                        data.replaceSubrange(58..<70, with: m.vel.prefix(3).flatMap { [UInt8].le($0, 4) })
                    }
                }
            }
            if data.count & 1 != o.data.count & 1 { changed = true }        // a patch that changed the record's parity moves the pad (Python keeps the old pad)
            chunks.append(LevelIff.Chunk(id: o.id, data: data, pad: o.pad ?? (data.count & 1 == 1 ? [0] : [])))
        }
        if changed {
            // dropped, appended or moved records: every chunk but the last is padded; the last odd one is short like the writer's (LevelIff)
            chunks = chunks.map { LevelIff.Chunk(id: $0.id, data: $0.data, pad: $0.data.count & 1 == 1 ? [0] : []) }
            iff.shortPad = (chunks.last?.data.count ?? 0) & 1 == 1
            if iff.shortPad { chunks[chunks.count - 1].pad = [] }
        }
        iff.chunks = chunks
        return iff.encode()
    }

    /// Pack `files` like Im1.pack with a thumbnail of the frame and write `url` (parent folders are created).
    public static func writeIM1(to url: URL, files: [String: [UInt8]], frame: Framebuffer) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(try Im1.pack(files: files, thumbnail: thumbnail(frame))).write(to: url, options: .atomic)     // a failed write keeps the old save
    }
}
