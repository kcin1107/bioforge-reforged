"""Write a native-format save (.im1) from prototype state: files are built with savegame.py's encoders.

With `tasks` (World.process_states) SCRIPT.DAT holds the system tasks (slots 0..5) and the prototype's script processes,
their Wait tasks, subtitle / sound timers and MODIFYVAREVERYNTH ramps (task_script_dat), written as the original's kernel writes
them, so the original game loads them (checked live; re/NOTES.md "Port saves load in the original"). Without `tasks`, a native
base state's SCRIPT.DAT is re-emitted unchanged and a new state keeps only the system tasks. The level's records are laid
out by level_layout (killed figures dropped, script-made figures and items added, the world's items in creation order) and
brought up to the world's figure and item state (patch_figure, patch_item); the original loads them (checked live)."""
import collections
import os
import re
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cam  # noqa: E402
import level  # noqa: E402
import savegame as sg  # noqa: E402

RAMP = range(128, 160)      # ASSUMPTION: the game palette's 32-step grey ramp (same entries as the monitor palettes)
SYSTEM_SLOTS = 6            # StdIntHandler, BiosTimer, 3 device handlers, Music


def thumbnail(rgb):
    """CAM frame (rle, 320x200, hotspot 0,0) of an RGB room frame: Rec.601 luma mapped linearly onto the grey ramp.  The
    native thumbnail (re/out/native_save) is the room view in ramp indices 128..145 plus a dialog bar in 35..53; the dialog
    art is not part of the capture here (ASSUMPTION: the capture precedes the dialog)."""
    import numpy as np
    luma = np.asarray(rgb, np.float64)[:, :, :3] @ (0.299, 0.587, 0.114)
    px = (128 + np.clip(np.rint(luma / 255 * 31), 0, 31)).astype(np.uint8)
    return cam.encode_frame(px.shape[1], px.shape[0], px.tobytes())


def system_script_dat(template):
    """A SCRIPT.DAT with only the system task slots of `template` (a ScriptDat); counts follow the kept slots.
    ASSUMPTION: bitmap/flag tables (entries 4, 5) stay as in the template."""
    sd = sg.ScriptDat.parse(template.encode())
    sd.slots = [s for s in sd.slots if s.index < SYSTEM_SLOTS]
    counts = collections.Counter(s.a[8] & 0x1f for s in sd.slots)
    sd.class_counts = [counts.get(i, 0) for i in range(32)]
    k = bytearray(sd.kernel)
    struct.pack_into('<H', k, 0x10, len(sd.slots))
    sd.kernel = bytes(k)
    return sd.encode()


def patch_item(data, state, oids):
    """An ITEM record (191 bytes) brought up to the world's item `state` = (owner, slot, pos, matrix rows) and `oids` {figure name:
    object id}: an item on the floor gets holder 0, no hand, its position and orientation (256 = 1.0); a carried item gets its
    holder's object id and its hand or limb ('RTHAND', 'LTHAND', 'UP_ARM'; empty = inventory), the record's position stays (ASSUMPTION: the engine
    keeps the hand's world position there; the hand string is the property value in upper case, no sample holds a hand).
    Only fields that differ are rewritten, so untouched records stay byte-identical.  A holder that is not a record of this level
    leaves the record alone (GAP: a new game has no PLAY record, and the writer does not add one)."""
    owner, slot, pos, matrix = state
    b = bytearray(data)
    if owner is None:
        holder, hand = 0, ''
        if pos is not None and tuple(int(round(v)) for v in pos) != struct.unpack_from('<3i', b, 9):
            struct.pack_into('<3i', b, 9, *(int(round(v)) for v in pos))
        if matrix is not None:
            m = tuple(int(round(256 * v)) for row in matrix for v in row)
            if m != struct.unpack_from('<9i', b, 147):
                struct.pack_into('<9i', b, 147, *m)
    else:
        if owner not in oids:
            return data
        holder, hand = oids[owner], '' if slot in (None, 'INVENTORY') else slot[:8]     # a hand or a limb (UP_ARM): the string at +0x30
    if struct.unpack_from('<H', b, 22)[0] != holder:
        struct.pack_into('<H', b, 22, holder)
    if sg.cstr(b[24:33]) != hand:
        b[24:33] = hand.encode('latin1').ljust(9, b'\0')
    return bytes(b)


def patch_figure(tag, data, state, oids, triggers):
    """A FIGR / PLAY record brought up to the world's figure `state` (keys pos, heading, motion, flags, locals, enemy, hold,
    in_trig, ai (+0x178), view_cams (a FIGR's list; it changes the record length); level.ObjRec offsets): the fields resume.py reads back. `oids` {figure name: object id} resolve the enemy (PLAYER
    = the PLAY record's id); `triggers` = the level's IMAG count, which the InTrig bytes must match. The motion string keeps its
    stale tail past the terminator, like every other string the writer sets."""
    rec = level.ObjRec(tag, data)
    cams = state.get('view_cams')
    if cams is not None and tag == 'FIGR' and [c.upper() for c in rec.view_cams] != cams:     # u16 count + 9-byte names (+0x1a5 list)
        b, t, n = rec.buf, rec.t, struct.unpack_from('<H', rec.buf, rec.t['ncams'])[0]
        names = b''.join(c.encode('latin1')[:8].ljust(9, b'\0') for c in cams)
        rec = level.ObjRec(tag, bytes(b[:t['ncams']]) + struct.pack('<H', len(cams)) + names + bytes(b[t['cams'] + 9 * n:]))
    b = rec.buf
    if state.get('ai'):
        a = state['ai'].encode('latin1')[:24] + b'\0'
        b[rec.t['name2']:rec.t['name2'] + len(a)] = a
    rec.pos = [int(round(v)) for v in state['pos']]
    if state.get('vel') is not None:
        struct.pack_into('<3i', b, 58, *state['vel'])
    rec.heading = state['heading']
    b[21] = (b[21] & ~MANAGED_FLAGS & 0xff) | state['flags']
    struct.pack_into('<10i', b, 106, *(list(state['locals']) + [0] * 10)[:10])
    m = state['motion'].encode('latin1')[:24] + b'\0'
    p = rec.t['motion']
    b[p:p + len(m)] = m
    enemy = oids.get(state['enemy'], 0) if state['enemy'] else 0
    struct.pack_into('<H', b, rec.t['enemy'], enemy)
    struct.pack_into('<H', b, rec.t['motion_task'], state.get('motion_slot', 0))     # +0x13d: the motion task's slot (0 = none)
    struct.pack_into('<H', b, rec.t['ai_task'], state.get('ai_slot', 0))             # +0x152: the AI process's slot (0 = none)
    if 'teeter' in state:
        b[rec.t['b146']:rec.t['b146'] + 4] = bytes([1 if state['teeter'] else 0, 0, 0, 0])     # +0x146: the whoah teeter
    if 'z_cap' in state:
        struct.pack_into('<i', b, rec.t['b14e'], state['z_cap'])                      # +0x14e: FLOATATHEIGHT ... MAXIMUM
    if 'foot' in state:
        struct.pack_into('<i', b, rec.t['s88'], state['foot'])                        # model+0x88: F
    if 'avoid' in state:                                                              # +0x1f3 count, 8 x (u16 waypoint id, u16 radius)
        av = [(oids[n], r) for n, r in state['avoid'] if n in oids][:8]
        struct.pack_into('<H', b, rec.t['navoid'], len(av))
        struct.pack_into('<16H', b, rec.t['avoid'], *[x for w, r in av + [(0, 0)] * (8 - len(av)) for x in (w, r)])
    if tag == 'PLAY' and 'hook_slot' in state:
        struct.pack_into('<H', b, rec.t['play'], state['hook_slot'])                  # DAT_1290_6530: the CAPTUREKEYBOARD hook's slot
    struct.pack_into('<h', b, rec.t['u229'], state['hold'])
    trig = state.get('in_trig')
    if trig is not None and len(trig) == struct.unpack_from('<H', b, rec.t['L'])[0]:
        b[rec.t['intrig']:rec.t['intrig'] + len(trig)] = bytes(trig)
    return bytes(b)


def resize_intrig(raw, tag, triggers):
    """A FIGR / PLAY record with its InTrig block resized to `triggers` bytes, all clear (patch_figure fills it)."""
    rec = level.ObjRec(tag, raw)
    L, p = rec.t['L'], rec.t['intrig']
    n = struct.unpack_from('<H', rec.buf, L)[0]
    out = bytes(rec.buf[:L]) + struct.pack('<H', triggers) + bytes(triggers) + bytes(rec.buf[p + n:])
    level.ObjRec(tag, out)                                  # the layout still parses
    return out


def figure_template(level_dir, kind):
    """A FIGR record for a figure a script made (CREATEFIGURE): one of the same type from any level IFF in `level_dir`, else the first
    FIGR record there. ASSUMPTION: the other tail fields (task links, scratch) fit; patch_figure sets the state resume.py reads."""
    first = None
    for n in sorted(os.listdir(level_dir)):
        if n.upper().endswith('.IFF'):
            for c, d, _ in sg.LevelIff.parse(open(os.path.join(level_dir, n), 'rb').read()).chunks:
                if c == b'FIGR':
                    if sg.cstr(d[:9]).upper() == kind.upper():
                        return d
                    first = first or d
    return first


def player_record(template, triggers):
    """A PLAY record for a level that has none (a new game's Lex is created by script, not loaded): the template (the
    shipped GAMEDAT CHAOS.IFF's) with its InTrig block resized to this level's `triggers` (all clear; patch_figure fills it).
    ASSUMPTION: the other tail fields of the template (task links, scratch) are fine for any level."""
    rec = level.ObjRec('PLAY', template)
    L, p = rec.t['L'], rec.t['intrig']
    n = struct.unpack_from('<H', rec.buf, L)[0]
    out = bytes(rec.buf[:L]) + struct.pack('<H', triggers) + bytes(triggers) + bytes(rec.buf[p + n:])
    level.ObjRec('PLAY', out)                               # the layout still parses
    return out


def item_template(level_dir):
    """The first 191-byte ITEM record of any level IFF in `level_dir` (a level without ITEM records, TUNROOM, still gets its
    carried items written): new_item_record overwrites the fields that matter. None if no level has one."""
    for n in sorted(os.listdir(level_dir)):
        if n.upper().endswith('.IFF'):
            for c, d, _ in sg.LevelIff.parse(open(os.path.join(level_dir, n), 'rb').read()).chunks:
                if c == b'ITEM' and len(d) == 191:
                    return d
    return None


PROC_VTABLE, WAIT_VTABLE, RAMP_VTABLE, MLIST_END = 0x3031, 0x6677, 0x2ea0, 0x408
TIMELINE_VTABLE = 0x307f      # a `[` block's process (3754 bytes: +0xea2 two clock values, FUN_10d0_6b03)
MOTION_VTABLE = 0x46f5        # a figure's motion task (FUN_10e0_0000, type 0x108, 77 bytes): +0x32 motion name, +0x4b started; B = the figure's id
# A missile in flight (FIRE / MAKEMISSILE, ctor FUN_10e0_0440): 86 bytes, type 0x10c. A: +0x38 serial (the handle), +0x3c the owning process
# (restored from B, FUN_10b8_0d67), +0x40 the travel sound object, +0x44 the owner figure and +0x52 the missile item (far pointers, read back
# from B only when nonzero, FUN_10e0_12b7), +0x48 s32 range, +0x4c/4e/50 s16 spin. B (FUN_10e0_135a): the task lists, the owning process's
# slot (FUN_10b8_0d0b), then the owner figure's and the item's object ids (FUN_1128_0e84). The item is an ordinary ITEM record.
MISSILE_VTABLE, MISSILE_TYPE, MISSILE_SIZE = 0x47a9, 0x10c, 0x56
WAITS, WAITED = 0x2000, 0x4000  # list2 entries: 0x2000|id = this task waits for id, 0x4000|id = task id waits for this one
_DEFS = re.compile(rb'"[^"]*"|//[^\n]*|\[[ \t]*(\w*)|\{[ \t]*(\w+)|(?<!\d):(?!\d)[ \t]*(\w*)')     # savegame.script_blocks
_SKIP = re.compile(rb'"[^"]*"|//[^\n]*')


def block_nesting(script, block, pc, script_dir=sg.SCRIPT_DIR):
    """(object+0x41, whether the block is a `[` timeline) of a process of definition `block` (1-based) of `script` stopped at .SCP
    offset `pc`: the open braces from the definition's first character to pc, the timeline's `[` counting as one. The interpreter
    raises it at `{` and lowers it at `}` and ends the process at 0 (FUN_10c0_2d1e); both original saves hold exactly this count
    (GAMEDAT, re/out/native_save: 23 processes, depths 1, 2 and 4)."""
    try:
        data = open(os.path.join(script_dir, script), 'rb').read()
    except OSError:
        return 1, False
    starts = [m.start() for m in _DEFS.finditer(data) if m.group(0)[:1] not in b'"/']
    if not 0 < block <= len(starts):
        return 1, False
    start = starts[block - 1]
    timeline = data[start:start + 1] == b'['
    text = _SKIP.sub(b'', data[start:pc])
    return max(1, int(timeline) + text.count(b'{') - text.count(b'}')), timeline


_TEMPLATES = None


def task_templates():
    """{vtable: Slot} clean task objects of the shipped GAMEDAT: a script process stopped at its block's top level with no links
    and no locals (CELLTWOBARS), a timeline process (ANIMGUARD), a Wait task, a MODIFYVAREVERYNTH task and a motion task."""
    global _TEMPLATES
    if _TEMPLATES is None:
        sd = sg.SaveState.load(sg.GAMEDAT).script
        out = {}
        for s in sd.slots:
            if s.vtable in out or s.index < SYSTEM_SLOTS:
                continue
            if s.kind == 'proc':
                pr = s.proc()
                if pr.l1 or pr.l2 or s.a[0x70] or s.a[0x41] != 1 or any(s.a[0x75:0x7f]):
                    continue
            out[s.vtable] = s
        _TEMPLATES = (out, {s.vtable: sd.name_ptrs[s.index] for s in sd.slots})
    return _TEMPLATES


def set_lists(a, l1, l2):
    """The two MLIST objects of a task (+0x16, +0x20: vtable, count, ?, far pointer): their counts, and a pointer that is nonzero
    exactly when the list has entries. The list loader reads the entries only behind a nonzero pointer (FUN_1240_08db) and the
    original writes an empty list as count 0 with no entries and no terminator."""
    for at, lst in ((0x16, l1), (0x20, l2)):
        struct.pack_into('<HHHH', a, at + 2, len(lst), 0, 0, 1 if lst else 0)


def task_script_dat(template, tasks, oids, motions=None):
    """A SCRIPT.DAT holding the system slots of `template` and the world's tasks (World.process_states), written as the original's
    kernel serializer would (FUN_1230_2208): a script process per task with 'block' (slot A = a clean process object of the shipped
    GAMEDAT, task_templates, with this process's header, brace depth, local count and links set; B = Proc.encode), a Wait task
    (remaining ticks at A+0x40, owner = the process) for a sleeping one, a MODIFYVAREVERYNTH task for a 'ramp', and a Wait task owned
    by no process for a TIMED subtitle / sound handle (the original's subtitle task, class 0x4901, is not written; ASSUMPTION: a
    plain timer stands in). A link "P waits for T" (a CALL child, a SUSPENDWHILE target, the own Wait task) is written as the kernel
    makes it (FUN_1238_0f48): T in P's list1, 0x2000|T in P's list2, 0x4000|P in T's list2; a CALL child's +0x71 names the caller
    (the process its RETURN value goes to, 10c0:3968), which waits at the CALL statement with +0x46 set. `motions` {figure name:
    motion name} add a motion task per figure whose script motion is still running (class 0x46f5: the name at A+0x32, started flag
    A+0x4b, B = the figure's object id); the load fixup restarts it from frame 0 (FUN_1088_4d67).
    -> (bytes, {slot: serial}, next serial, {figure name: motion task slot})"""
    sd = sg.ScriptDat.parse(template.encode())
    tmpl, ptrs = task_templates()
    slots = [s for s in sd.slots if s.index < SYSTEM_SLOTS]
    free = iter(range(SYSTEM_SLOTS, sd.N_SLOTS))
    by_handle, waits = {}, {}
    for t in tasks:
        by_handle[t['handle']] = next(free)
        if t.get('wait'):
            waits[t['handle']] = next(free)
    serials = {}
    next_serial = max([t['handle'] for t in tasks] + [0]) + 1
    links = []                                              # (waiting slot, awaited slot), in the order the waits began
    for t in tasks:
        me = by_handle[t['handle']]
        links += [(me, by_handle[h]) for h in t.get('blockers', ()) if h in by_handle]
        if t['handle'] in waits:
            links.append((me, waits[t['handle']]))
    caller = {}
    for t in tasks:
        for h in t.get('calls', ()):
            if h in by_handle:
                caller.setdefault(by_handle[h], by_handle[t['handle']])

    def lists(slot):
        l1 = [b for p, b in links if p == slot]
        l2 = [WAITED | p for p, b in links if b == slot] + [WAITS | b for p, b in links if p == slot]
        return l1 + [MLIST_END] if l1 else [], l2 + [MLIST_END] if l2 else []

    def slot_obj(vtable, index, serial, l1=(), l2=()):
        t = tmpl[vtable]
        a = bytearray(t.a)
        struct.pack_into('<H', a, 2, index)
        struct.pack_into('<I', a, 0x38, serial)
        set_lists(a, l1, l2)
        serials[index] = serial
        sd.name_ptrs[index] = ptrs[vtable]
        return a

    def task_b(l1, l2, owner):
        return struct.pack(f'<{len(l1)}H', *l1) + struct.pack(f'<{len(l2)}H', *l2) + struct.pack('<H', owner)

    def wait_task(index, serial, ticks, owner):
        l1, l2 = lists(index)
        w = slot_obj(WAIT_VTABLE, index, serial, l1, l2)
        struct.pack_into('<HH', w, 0x40, min(ticks, 0xffff), min(ticks, 0xffff))
        struct.pack_into('<HH', w, 0x3c, 0, 1 if owner else 0)     # +0x3c: the owner's pointer, read back only when nonzero (FUN_10b8_0d67)
        return sg.Slot(index, bytes(w), task_b(l1, l2, owner))
    for t in tasks:
        i = by_handle[t['handle']]
        if 'missile' in t:
            # the header of an engine-made task of the same base (the motion task: class 1, its class name), the missile's own fields
            # after it. ASSUMPTION: no owning process (+0x3c 0: the port does not keep which process fired it) and no travel sound
            # (+0x40 0: a voice does not survive a load)
            m = t['missile']
            l1, l2 = lists(i)
            a = bytearray(tmpl[MOTION_VTABLE].a[:0x38]) + bytearray(MISSILE_SIZE - 0x38)
            struct.pack_into('<HH', a, 0, MISSILE_VTABLE, i)
            struct.pack_into('<H', a, 6, MISSILE_TYPE)
            struct.pack_into('<I', a, 0x38, t['handle'])
            set_lists(a, l1, l2)
            owner, item = oids.get((m.get('owner') or '').upper(), 0), oids.get(m['item'].upper(), 0)
            struct.pack_into('<IIIi3hI', a, 0x3c, 0, 0, 1 if owner else 0, m['range'], *m['spin'], 1 if item else 0)
            serials[i] = t['handle']
            sd.name_ptrs[i] = ptrs[MOTION_VTABLE]
            slots.append(sg.Slot(i, bytes(a), task_b(l1, l2, 0) + struct.pack('<HH', owner, item)))
            continue
        if 'timed' in t:                                    # a subtitle / sound handle: a Wait task owned by no process, serial = the handle
            slots.append(wait_task(i, t['handle'], t['timed'], 0))
            continue
        if 'ramp' in t:
            a = slot_obj(RAMP_VTABLE, i, t['handle'])
            cur, step, end, start, period, left = t['ramp']
            struct.pack_into('<i', a, 0x45, cur)
            struct.pack_into('<hhhHH', a, 0x49, step, end, start, period, left)
            slots.append(sg.Slot(i, bytes(a), task_b([], [], 0)))
            continue
        depth, timeline = block_nesting(t['script'].upper(), t['block'], t['pc'])
        l1, l2 = lists(i)
        a = slot_obj(TIMELINE_VTABLE if timeline else PROC_VTABLE, i, t['handle'], l1, l2)
        flags = struct.unpack_from('<H', a, 0xe)[0] & ~1      # bit 0: suspended (camera links, SUSPENDPROCESS; the kernel skips it, 1230:0259)
        struct.pack_into('<H', a, 0xe, flags | (1 if t.get('suspended') else 0))
        struct.pack_into('<IbbHHb', a, 0x3c, 0, -1, depth, t.get('fig_index', 0) & 0xffff, 0, 1 if t.get('calls') else 0)
        struct.pack_into('<I', a, 0x47, 0)                  # +0x47: the RETURN value of the CALL child (taken when +0x46 is set)
        n = t.get('nlocals', len(t['locals']))
        wait_slot = caller.get(i, 0)
        struct.pack_into('<IbHH', a, 0x6c, 1 if n else 0, n, wait_slot, 0)      # locals pointer, count; +0x71: the caller
        a[0x75:0xe7b] = bytes(0xe7b - 0x75)                 # per-depth ELSE flags, statement buffers, CALL arguments, variable pointers: scratch
        rec = sg.Proc(l1=l1, l2=l2, owner=0, obj_a=oids.get(t['cur'], 0), obj_b=0, cur_obj=oids.get(t['cur'], 0), wait_slot=wait_slot,
                      block=t['block'], script_raw=t['script'].upper().encode('latin1')[:12].ljust(13, b'\0'), label2=0, file_idx=1000,
                      pc=t['pc'], pc0=t['pc0'], locals=[v & 0xffffffff for v in (list(t['locals']) + [0] * n)[:n]],
                      objs=[oids[c] for c in t['cameras'] if c in oids])
        slots.append(sg.Slot(i, bytes(a), rec.encode()))
        if t['handle'] in waits:
            slots.append(wait_task(waits[t['handle']], next_serial, t['wait'], i))
            next_serial += 1
    motion_slots = {}
    for fig, name in sorted((motions or {}).items()):
        if fig not in oids:
            continue
        i = next(free)
        a = slot_obj(MOTION_VTABLE, i, next_serial)
        next_serial += 1
        a[0x32:0x4b] = name.lower().encode('latin1')[:24].ljust(25, b'\0')
        a[0x4b], a[0x4c] = 1, 0
        slots.append(sg.Slot(i, bytes(a), struct.pack('<H', oids[fig])))
        motion_slots[fig] = i
    sd.slots = sorted(slots, key=lambda s: s.index)
    counts = collections.Counter(s.a[8] & 0x1f for s in sd.slots)
    sd.class_counts = [counts.get(i, 0) for i in range(32)]
    groups = {0} | {s.group for s in sd.slots}              # entry 4: a bit per task group id in use (FUN_1230_2ea2)
    sd.bitmap = bytes(sum(1 << (g % 8) for g in groups if g // 8 == k) for k in range(len(sd.bitmap)))
    k = bytearray(sd.kernel)
    struct.pack_into('<H', k, 0x10, len(sd.slots))
    sd.kernel = bytes(k)
    return sd.encode(), serials, next_serial, motion_slots


MANAGED_FLAGS = level.F_GRAVITY | level.F_COLLISIONS | level.F_HIDDEN | level.F_INVULNERABLE | level.F_BOUNCY | level.F_COMBAT


def new_item_record(template, name, kind, locals_):
    """An ITEM record (191 bytes) for an item a script made (CREATEITEM / INDIVIDUALIZE): `template` (another ITEM record of the level)
    with record name = the item type, instance name = its key, no holder, hand or flags, its object locals; patch_item then sets the
    holder or the floor position. ASSUMPTION: the template's other fields (extents, scratch) fit any item."""
    b = bytearray(template)
    b[0:9] = kind.upper().encode('latin1')[:8].ljust(9, b'\0')
    b[33:58] = name.upper().encode('latin1')[:24].ljust(25, b'\0')
    b[21] = 0
    struct.pack_into('<H', b, 22, 0)
    b[24:33] = bytes(9)
    struct.pack_into('<10i', b, 106, *(list(locals_) + [0] * 10)[:10])
    return bytes(b)


def read_level(path, killed=()):
    """The LevelIff at `path` without the FIGR records of the `killed` figures (instance names): a killed figure's object is
    destroyed (FUN_1090_135a), so the save has no record of it. -> (LevelIff, whether records were dropped)"""
    iff = sg.LevelIff.parse(open(path, 'rb').read())
    killed = {k.upper() for k in killed}
    keep = [c for c in iff.chunks if c[0] != b'FIGR' or (sg.cstr(c[1][33:58]) or sg.cstr(c[1][:9])).upper() not in killed]
    dropped = len(keep) != len(iff.chunks)
    iff.chunks = keep
    return iff, dropped


def _rec_name(cid, d):
    return ((sg.cstr(d[33:58]) if cid in (b'FIGR', b'PLAY', b'ITEM') and len(d) >= 58 else '') or sg.cstr(d[:9])).upper()


def level_layout(level_dir, level, killed=(), player=None, figure_states=None, player_template=None, item_states=None, item_extra=None,
                 drop_items=True):
    """The object records of `level` as the save writes them, before patching: -> (LevelIff, [(chunk id, data)] without VERS,
    {object name: 1-based id}, triggers, whether the record list changed). The killed figures' FIGR records go (read_level); a new
    game's player gets a PLAY record (player_record); then the world's items (`item_states`, in the world's creation order) follow
    the other records in that order: their own records moved there, and an item a script made gets one (new_item_record) when it is
    carried by an object of the level or lies on the floor. The order is the object list's, which the inventory lists the player's
    items in (World.inventory_items, FUN_10d0_0000), so a loaded game shows them as the saved one did. With `item_states` given and
    `drop_items`, the ITEM records of items that are not among them go: the level writer (FUN_1148_1232) writes only the objects in
    the list, so an item carried off to another level, or destroyed, has no record."""
    path = os.path.join(level_dir, level + '.IFF')
    iff, changed = read_level(path, killed)
    objects = [(cid, data) for cid, data, _ in iff.chunks if cid != b'VERS']          # object ids are 1-based indexes
    triggers = sum(1 for cid, _ in objects if cid == b'IMAG')
    if player and player_template and figure_states and player.upper() in figure_states and not any(cid == b'PLAY' for cid, _ in objects):
        rec = player_record(player_template, triggers)
        kind = figure_states[player.upper()]['type']
        rec = kind.upper().encode('latin1')[:8].ljust(9, b'\0') + rec[9:33] + player.upper().encode('latin1')[:24].ljust(25, b'\0') + rec[58:]
        objects.append((b'PLAY', rec))
        changed = True
    if figure_states:                                       # figures a script made (CREATEFIGURE) are objects too: a FIGR record each
        have = {_rec_name(c, d) for c, d in objects if c in (b'FIGR', b'PLAY')}
        for name, state in figure_states.items():
            if name.upper() in have or (player and name.upper() == player.upper()):
                continue
            t = figure_template(level_dir, state['type'])
            if t is None:
                continue
            rec = resize_intrig(t, 'FIGR', triggers)
            rec = state['type'].upper().encode('latin1')[:8].ljust(9, b'\0') + rec[9:33] + name.upper().encode('latin1')[:24].ljust(25, b'\0') + rec[58:]
            objects.append((b'FIGR', rec))
            changed = True
    if item_states is not None:
        records = {_rec_name(c, d): d for c, d in objects if c == b'ITEM' and len(d) == 191}
        holders = {_rec_name(c, d) for c, d in objects if c in (b'FIGR', b'PLAY')} | ({'PLAYER'} if player else set())
        template = next(iter(records.values()), None) or item_template(level_dir)
        moved = []
        for name, state in item_states.items():
            name = name.upper()
            owner = state[0]
            if name in records:
                moved.append((b'ITEM', records[name]))
            elif item_extra and name in item_extra and template is not None and (owner is not None or state[2] is not None) \
                    and (owner is None or owner.upper() in holders):
                moved.append((b'ITEM', new_item_record(template, name, item_extra[name][0], item_extra[name][1])))
        names = {_rec_name(c, d) for c, d in moved}
        in_file = [_rec_name(c, d) for c, d in objects if c == b'ITEM' and len(d) == 191 and _rec_name(c, d) in names]
        new = [_rec_name(c, d) for c, d in moved if _rec_name(c, d) not in records]
        if [_rec_name(c, d) for c, d in moved] == in_file + new:
            # the world's order is the file's, new items last: the records stay where they are, as the original's object list keeps
            # them (re/out/native_save round trip), so the ids of the objects after them do not move
            rest = [(c, d) for c, d in objects if not (c == b'ITEM' and len(d) == 191 and _rec_name(c, d) not in names and drop_items)]
            moved = moved[len(in_file):]
        else:
            rest = [(c, d) for c, d in objects if not (c == b'ITEM' and len(d) == 191 and (_rec_name(c, d) in names or drop_items))]
        if rest + moved != objects:
            changed = True
        objects = rest + moved
    oids = {}
    for i, (cid, d) in enumerate(objects, 1):
        oids.setdefault(_rec_name(cid, d), i)
        if cid == b'PLAY':
            oids.setdefault(sg.cstr(d[:9]).upper(), i)
    if player:
        oids['PLAYER'] = oids.get(player.upper(), 0)
    return iff, objects, oids, triggers, changed


def level_object_ids(level_dir, level, **layout):
    """{object name: 1-based id} of `level` as build_files leaves it (level_layout)."""
    return level_layout(level_dir, level, **layout)[2]


def encode_level(iff, objects, oids, triggers, changed, positions=None, figure_states=None, item_states=None, item_extra=None):
    """The level file of a level_layout, its records brought up to the world's state (positions, patch_figure, patch_item, locals)."""
    positions = positions or {}
    pads = {id(d): p for _, d, p in iff.chunks}
    chunks = [c for c in iff.chunks if c[0] == b'VERS'][:1]
    for cid, data in objects:
        pad = pads.get(id(data), b'\0' if len(data) & 1 else b'')
        size = len(data)
        key = sg.cstr(data[33:42]) if cid == b'FIGR' else sg.cstr(data[:9]) if cid == b'PLAY' else None
        p = positions.get(key.upper()) if key else None
        if p is not None and len(data) >= 21:
            data = data[:9] + struct.pack('<3i', *(int(round(v)) for v in p)) + data[21:]
        if cid in (b'FIGR', b'PLAY') and figure_states:
            state = figure_states.get(_rec_name(cid, data))
            if state is not None:
                data = patch_figure(cid.decode(), data, state, oids, triggers)
        if cid == b'ITEM' and len(data) == 191 and item_states:
            name = _rec_name(cid, data)
            state = item_states.get(name)
            if state is not None:
                data = patch_item(data, state, oids)
                if item_extra and name in item_extra:
                    data = data[:106] + struct.pack('<10i', *(list(item_extra[name][1]) + [0] * 10)[:10]) + data[146:]
                    if len(item_extra[name]) > 2:                   # a missile's item: its velocity (+0xc6) and flags (+0x34)
                        vel, flags = item_extra[name][2]
                        data = data[:21] + bytes([flags & 0xff]) + data[22:58] + struct.pack('<3i', *vel) + data[70:]
        chunks.append((cid, data, pad))
        changed = changed or (len(data) - size) & 1 == 1             # a camera list of odd length moves the pad
    if changed:
        # dropped, appended or moved records: every chunk but the last is padded; the last odd one is short like the writer's (LevelIff)
        chunks = [(c, d, b'\0' if len(d) & 1 else b'') for c, d, _ in chunks]
        iff.short_pad = bool(len(chunks[-1][1]) & 1)
        if iff.short_pad:
            chunks[-1] = chunks[-1][:2] + (b'',)
    iff.chunks = chunks
    return iff.encode()


def build_files(slot_name, level, camera, auto_camera, variables, lists, level_dir, positions, base=None, item_states=None,
                figure_states=None, player=None, player_template=None, tasks=None, item_extra=None, killed=(), other_levels=None):
    """-> {file name: bytes} of a save.  `base` = SaveState of the native directory the world was loaded from (its MISC
    fields, SCRIPT.DAT and VARS table are kept) or None (zeros / initial variables / shipped GAMEDAT headers).
    variables {NAME: int}; lists {name: [(key, stamp)]}; level_dir holds the level IFFs; positions {FIGR instance name or
    PLAY name: (x, y, z)} update the records of `level` (pos at record offset +9); item_states {ITEM instance name: (owner, slot, pos,
    matrix)} update its ITEM records (patch_item). figure_states {FIGR instance name or the player's name: state (patch_figure)}
    bring the figure records up to the world's figures; `player` names the player, and when the level has no PLAY record one is
    appended (player_record from `player_template`). `tasks` (World.process_states) replace SCRIPT.DAT's processes (task_script_dat).
    item_extra {item name: (type, object locals)}: every ITEM record of the world's items gets its locals, and an item without a record
    (one a script made) gets one. `killed` figures (instance names) lose their FIGR record. The record order is level_layout's.
    other_levels {level: (item_states, item_extra[, figure_states])}: the items and figures kept with a level the player left
    (World.level_items, level_figures); that level's file gets them as the current one does (FUN_1148_1404 wrote it at the level change):
    with figure_states given, the FIGR records of figures not among them are dropped. Other levels' files are copied as they are."""
    tmpl = base or sg.SaveState.load(sg.GAMEDAT)
    if base:
        misc = sg.Misc(base.misc.raw)
    else:
        misc = sg.Misc.new(level=level + '.IFF', obj_a=4, obj_b=5)      # ASSUMPTION: obj ids 4, 5 as in every native sample
    misc.save_name, misc.level, misc.camera, misc.auto_camera = slot_name, level + '.IFF', camera or '', int(auto_camera)
    script = base.script.encode() if base else system_script_dat(tmpl.script)
    if not base:
        misc.serials = [s if i < SYSTEM_SLOTS else 0 for i, s in enumerate(misc.serials)]
    iff, objects, oids, triggers, changed = level_layout(level_dir, level, killed, player, figure_states, player_template, item_states, item_extra)
    if tasks is not None:
        motions = {k: v['motion'] for k, v in (figure_states or {}).items() if v.get('motion_task')}
        script, serials, next_serial, motion_slots = task_script_dat(tmpl.script, tasks, oids, motions)
        for k, i in motion_slots.items():
            figure_states[k] = dict(figure_states[k], motion_slot=i)
        slot_of = {serial: slot for slot, serial in serials.items()}
        hook = next((slot_of.get(t['handle'], 0) for t in tasks if t.get('hook')), 0)
        for k, v in list((figure_states or {}).items()):
            figure_states[k] = dict(v, ai_slot=slot_of.get(v.get('ai_handle') or -1, 0), hook_slot=hook if player and k == player.upper() else 0)
        misc.serials = [s if i < SYSTEM_SLOTS else serials.get(i, 0) for i, s in enumerate(misc.serials)]
        misc.next_serial = max(misc.next_serial, next_serial)
    items = base.vars.items if base else sg.default_vars()
    vars_ = sg.DefFile(tmpl.vars.head, tmpl.vars.kind, [(n, variables.get(n.upper(), v)) for n, v in items])
    files = {'MISC.DAT': misc.encode(), 'SCRIPT.DAT': script, 'VARS.DEF': vars_.encode(), 'SOUNDS.DEF': tmpl.sounds.encode(),
             'LISTS.FLX': sg.Lists.from_lists(lists, template=tmpl.lists).encode()}
    other_levels = {k.upper(): v for k, v in (other_levels or {}).items()}
    for n in sorted(os.listdir(level_dir)):
        if not n.upper().endswith('.IFF'):
            continue
        name = n.upper()[:-4]
        if name == level:
            files[n.upper()] = encode_level(iff, objects, oids, triggers, changed, positions, figure_states, item_states, item_extra)
        elif name in other_levels:
            states, extra, kept = (other_levels[name] + (None,))[:3]
            gone = ()
            if kept is not None:                              # the kept figures stay, every other FIGR record is a killed (or carried-off) one
                gone = [_rec_name(c, d) for c, d, _ in sg.LevelIff.parse(open(os.path.join(level_dir, n), 'rb').read()).chunks
                        if c == b'FIGR' and _rec_name(c, d) not in kept]
            layout = level_layout(level_dir, name, gone, figure_states=kept, item_states=states, item_extra=extra)
            files[n.upper()] = encode_level(*layout, figure_states=kept, item_states=states, item_extra=extra)
        else:
            files[n.upper()] = sg.LevelIff.parse(open(os.path.join(level_dir, n), 'rb').read()).encode()
    return files


def write_im1(path, files, rgb):
    """Pack `files` like Im1.pack with a thumbnail of the RGB frame and write `path`."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        for n, b in files.items():
            open(os.path.join(d, n), 'wb').write(b)
        open(path, 'wb').write(sg.Im1.pack(d, thumbnail(rgb)))
