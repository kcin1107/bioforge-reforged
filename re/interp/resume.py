"""Resume a native save in the prototype: figures, carried items and script processes (used by World.from_native_state).

    resume.restore(world, vm, st)       st = savegame.SaveState (a native GAMEDAT / .im1 directory)

What comes from where (details and function citations: savegame.Proc / ScriptDat, level.ObjRec, NOTES "Save state"):
  * figures: the level IFF's FIGR/PLAY records -> position, heading (COMPASS convention), current motion name, combat flag, hit
    points and the other nine object locals (`<obj>.~0..~9`), enemy, viewing cameras, avoidance points, AI process link;
  * items: ITEM records the player holds -> world.items (hand name or INVENTORY) plus their object locals;
  * script processes (SCRIPT.DAT 'proc' slots): block = definition counter index, resume position = `pc` (byte offset into the
    tokenized .SCP; see below), locals, current figure/item, wait state (see `_wait_state`), handle = task serial, so VARS values
    such as _CELLONEPROCESS = 18 refer to the restored process; the VM hands out new handles from MISC's next serial;
  * MODIFYVAREVERYNTH tasks (type 0x10e) -> native ramp processes with the saved value and countdown.
pc / pc0 (evidence: every process of both samples): pc0 = start of the statement the process is executing or last executed
(a WAIT / SUSPEND / CALL / timeline line), pc = text position right after it (the next statement, or the whitespace/comment
before it; `parse.File.statements_from` skips to the statement). pc == pc0 only while the process is blocked inside a CALL
expression: that statement is re-entered on resume. So the resume point is always `pc`.
"""
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'formats'))
import parse  # noqa: E402
import vm as vmmod  # noqa: E402
import level as levelmod  # noqa: E402

MOTION_VTABLE = 0x46f5          # a figure's motion task (savewrite.MOTION_VTABLE)

WAIT_VTABLE, MLIST_END = 0x6677, 0x408      # Wait task class (SCRIPT.DAT slot), list terminator in a process record
MISSILE_VTABLE = 0x47a9                     # a missile in flight (savewrite.MISSILE_VTABLE)
WAIT_REMAINING = 0x40                       # u16 in the Wait task object: ticks left (+0x42 = the requested duration; FUN_1150_018c)
MODIFY_TYPE = 0x10e                         # MODIFYVAREVERYNTH task: far var ptr @0x41, s32 value @0x45, s16 step @0x49, end @0x4b,
                                            # start @0x4d, u16 period @0x4f, u16 countdown @0x51 (ASSUMPTION: field names from one sample)


def _calls(e):
    if isinstance(e, tuple):
        if e and e[0] == 'call':
            yield e
        for x in e[1:]:
            yield from _calls(x)
    elif isinstance(e, list):
        for x in e:
            yield from _calls(x)


class Names:
    """Object ids of the level IFF (1-based; 0 / 0xFFFF = none) -> script names."""
    def __init__(self, recs):
        self.recs = recs
        self.item_keys = {}                       # oid -> World.items key of a carried item

    def rec(self, oid):
        return self.recs[oid - 1] if 0 < oid <= len(self.recs) else None

    def name(self, oid):
        r = self.rec(oid)
        if r is None:
            return None
        tag, nm, raw, rec = r
        return (rec.inst if rec is not None and rec.inst else nm).upper()

    def tag(self, oid):
        r = self.rec(oid)
        return r[0] if r else None


def restore(world, vm, st):
    """-> {slot: Process} of the restored script processes. Figures and items first (processes refer to them)."""
    lv = st.levels.get(world.level)
    names = Names(lv.records() if lv else [])
    figs = _figures(world, vm, names)
    _items(world, vm, names)
    procs = _processes(world, vm, st, names)
    tasks = {sl.index: sl for sl in st.script.slots}
    for rec_slot, (fig, rec) in figs.items():          # a running MOTION ... CONTINUE: its motion task restarts the motion from frame 0
        sl = tasks.get(rec.motion_task)                 # (the fixup FUN_1088_4d67 -> FUN_1098_06e0(model, task+0x32, 0, 0)); it plays once
        if sl is None or sl.vtable != MOTION_VTABLE:
            continue
        name = bytes(sl.a[0x32:0x4b]).split(b'\0')[0].decode('latin1').upper()
        W = sys.modules[type(world).__module__]
        loop = W.motion_loops(fig.assets, name) and not name.endswith(W.GESTURES)       # as cmd_motion's CONTINUE
        if name in fig.assets.motions and fig.set_motion(name, loop, quiet=True):
            fig.task_name, fig.unwaited = name, True
    for fig, rec in [v for v in figs.values() if v[1].tag == 'PLAY']:     # the CAPTUREKEYBOARD hook process (DAT_1290_6530): the port runs
        p = procs.pop(rec.hook_task, None) if rec.hook_task else None    # the block per key, so the idle process only names it
        if p is not None:
            world.keyboard_captured, world.key_hook, world.key_hook_owner = True, p.block.name.upper(), 'level'
            vm.finish(p)
    for rec_slot, (fig, rec) in figs.items():          # AI process link (the task slot of the process behind `AI ON`)
        p = procs.get(rec.ai_task)
        if p is not None:
            fig.ai_proc = p
            fig.ai_type = p.block.name[:-3] if p.block.name.upper().endswith('_AI') else fig.ai_type
    vm.next_handle = max(vm.next_handle, st.misc.next_serial)
    world.apply_camera_links(world.current_camera())   # the restore ends by switching to the saved camera (1148:0490 -> 1130:0114)
    return procs


# ---------------------------------------------------------------------------------------------------------------- figures
def apply_figure_record(world, fig, rec, names, key):
    """What the level reader restores from a FIGR / PLAY record onto its figure (FUN_1148_0d46; the same reader serves a load and a return to
    a level): the current motion, the flags (hidden, combat, gravity, bouncy, collisions, invulnerable), teeter, z cap, foot, velocity, the
    enemy and the avoidance list. Used by `_figures` (the resumed level) and by World.figure (a level built from its file)."""
    if rec.motion and not fig.set_motion(rec.motion.upper(), True, quiet=True):
        world.warn(f'resume: {key}: motion {rec.motion!r} not found')
    elif rec.motion:
        fig.pos[2] -= fig.frames[0][0][2]      # saved z includes the motion's root z (FUN_10a0_1ff0: support + F + root z); the prototype keeps it in the pose
    fig.hidden = bool(rec.flags & levelmod.F_HIDDEN)
    fig.combat = bool(rec.flags & levelmod.F_COMBAT)
    fig.gravity = bool(rec.flags & levelmod.F_GRAVITY)
    fig.bouncy = bool(rec.flags & levelmod.F_BOUNCY)
    fig.no_collide = bool(rec.flags & levelmod.F_COLLISIONS)
    fig.invulnerable = bool(rec.flags & levelmod.F_INVULNERABLE)
    fig.teeter = bool(rec.teeter)                     # +0x146
    fig.z_cap = rec.z_cap                             # +0x14e
    if rec.foot != fig.assets.foot_offset:            # model+0x88: a FLOATATHEIGHT override (the type's F otherwise)
        fig.foot_override = rec.foot
    W2 = sys.modules[type(world).__module__]
    if fig.motion and not W2.motion_loops(fig.assets, fig.motion) and not rec.motion_task:    # a one-off with no task has ended: its
        fig.loop, fig.idx, fig.finished = False, len(fig.frames) - 1, True                    # last pose (a type with no idle, ESCHEAD)
    if rec.locals[0] <= 0 and fig.motion == 'DIE':          # dead: the fixup starts I_AM_DEAD, which no body has, so the figure gets no
        fig.loop, fig.idx, fig.finished = False, len(fig.frames) - 1, True     # motion; the port holds DIE's last pose (ASSUMPTION)
        fig.frozen = fig.stopped = fig.no_idle = True
    fig.vx, fig.vy, fig.vz = rec.velocity               # +0xc6..: a zero-g float or a knockback goes on
    e = names.name(rec.enemy)
    fig.enemy = 'PLAYER' if names.tag(rec.enemy) == 'PLAY' else e
    fig.avoid = [(names.name(w) or '', r) for w, r in rec.avoid]       # ADDAVOIDANCEPOINT list (FUN_1088_3629 pushes)


def _figures(world, vm, names):
    W = sys.modules[type(world).__module__]
    out = {}
    for oid, (tag, nm, raw, rec) in enumerate(names.recs, 1):
        if tag not in ('FIGR', 'PLAY'):
            continue
        key = names.name(oid)
        try:
            fig = W.Figure(key, rec.name.upper(), world.asset(rec.name.upper()), rec.pos, rec.heading)
        except (OSError, KeyError):
            world.warn(f'resume: no figure type {rec.name}')
            continue
        fig.view_cams = None if tag == 'PLAY' else [c.upper() for c in rec.view_cams]
        fig.ai_type = rec.ai_name or None                 # +0x178: the AI start runs <it>_AI (1088:33d4)
        fig.hold = rec.ai_off
        apply_figure_record(world, fig, rec, names, key)
        world.select_area(fig)                       # placed: the area list Space walks (FUN_1138_1a93, as set_pos; INFERRED for the restore)
        if len(rec.in_trig) == len(world.triggers):                  # InTrig bytes, one per IMAG of the level
            fig.in_trig = bytearray(rec.in_trig)
        world.figures[key] = fig
        if tag == 'PLAY':
            world.player_name = key
        vm.objects[world.object_key(key)] = rec.locals
        out[oid] = (fig, rec)
    return out


def _items(world, vm, names):
    """The player's items, then the item list in record order. The level reader makes the objects in chunk order (FUN_1148_0d46) and each
    item appends itself to the item list (1050:10bf), which the inventory walks (FUN_10d0_0076): so a loaded game lists the items in
    the file's order, the floor items and those a figure holds among the player's. The writer puts them in the world's creation order
    (savewrite.level_layout), so the inventory comes back as it was saved."""
    W = sys.modules[type(world).__module__]
    came = {}                                           # floor items and those a level figure holds came with the level (load_floor_items),
    for key, item in world.items.items():               # in record order
        came.setdefault(item.name.upper(), []).append(key)
    order = []
    for oid, (tag, nm, raw, rec) in enumerate(names.recs, 1):
        if tag != 'ITEM':
            continue
        if not rec.holder or names.tag(rec.holder) == 'FIGR':
            if came.get(names.name(oid)):
                order.append(came[names.name(oid)].pop(0))
            continue
        name = names.name(oid)
        # ASSUMPTION: a carried item whose hand string is empty sits in the inventory (FUN_10d8_2845 treats a null hand
        # string as "carried, not in a hand")
        item = world.add_item(W.Item(name, rec.name.upper(), names.name(rec.holder), rec.hand.upper() or 'INVENTORY'))
        names.item_keys[oid] = item.key                  # a duplicate name gets its own key
        vm.objects[item.key] = rec.locals
        order.append(item.key)
    placed = set(order)
    world.items = {k: world.items[k] for k in order + [k for k in world.items if k not in placed]}


# -------------------------------------------------------------------------------------------------------------- processes
def _file(vm, script):
    stem = os.path.splitext(script)[0].upper()
    f = next((f for f in vm.files if os.path.splitext(f.name)[0].upper() == stem), None)
    if f is None:
        path = os.path.join(parse.ROOT, 're', 'out', 'scripts', stem + '.scr')
        f = vm.load(path) if os.path.exists(path) else None
    return f


def _processes(world, vm, st, names):
    sd = st.script
    made, links = {}, []
    for s in sd.slots:
        if s.vtable == WAIT_VTABLE and s.task()[2] == 0:
            made[s.index] = (_timed(vm, s), None)        # owned by no process: a subtitle / sound handle (savewrite's; ASSUMPTION)
        elif s.kind == 'proc':
            p = _process(world, vm, s, names)
            if p is not None:
                made[s.index] = (p, s.proc())
        elif s.type == MODIFY_TYPE:
            c = _ramp(world, vm, s)
            if c is not None:
                made[s.index] = (c, None)                # a SUSPENDWHILE MODIFYVAREVERYNTH waiter waits for it again
        elif s.vtable == MISSILE_VTABLE:
            c = _missile(world, vm, s, names)
            if c is not None:
                made[s.index] = (c, None)                # a SUSPENDWHILE FIRE waiter waits for it again
    for slot, (p, rec) in made.items():
        if rec is not None:
            _wait_state(world, vm, sd, slot, p, rec, made)
    return {slot: p for slot, (p, rec) in made.items() if rec is not None}


def _missile(world, vm, s, names):
    """A missile in flight (savewrite MISSILE_VTABLE; FUN_10e0_12b7 reads it back): its ITEM record came in with the level's floor items
    as a plain Item, which becomes the Missile again with the task's range and spin, the record's position, orientation, velocity and
    flags, and a native handle under the task's serial. ASSUMPTION: the travel sound does not restart (+0x40 is a voice, which does not
    survive a load)."""
    import struct
    W = sys.modules[type(world).__module__]
    c1, c2 = struct.unpack_from('<H', s.a, 0x18)[0], struct.unpack_from('<H', s.a, 0x22)[0]
    owner_oid, item_oid = struct.unpack_from('<HH', s.b, 2 * (c1 + c2) + 2)
    rec = names.rec(item_oid)[3] if names.tag(item_oid) == 'ITEM' else None
    key = names.item_keys.get(item_oid, names.name(item_oid))
    old = next((k for k, i in world.items.items() if k.upper() == (key or '').upper() and not getattr(i, 'missile', False)), None)
    if rec is None or old is None:
        world.warn(f'resume: missile task {s.serial}: item #{item_oid} not found')
        return None
    m = W.Missile(old, rec.name.upper())
    world.missile_type_props(m)
    m.pos = np.array(rec.pos, float)
    m.set_rows([list(r) for r in rec.matrix])
    m.vel = list(rec.velocity)
    m.no_collide = bool(rec.flags & 0x02)
    m.dist = struct.unpack_from('<i', s.a, 0x48)[0]
    m.spin = struct.unpack_from('<3h', s.a, 0x4c)
    m.owner_fig = world.figures.get(names.name(owner_oid)) if owner_oid and struct.unpack_from('<I', s.a, 0x44)[0] else None
    world.items = {k: (m if k == old else i) for k, i in world.items.items()}
    c = vmmod.Process(vm, s.serial, parse.Block('MISSILE', 'native', 0, None), None, None)
    c.code = vmmod.Code(c.block)
    c.owner = 'level'
    c.gen = iter([vmmod.FOREVER])
    vm.procs[s.serial] = c
    vm.run(c)
    m.handle = s.serial
    return c


def _timed(vm, s):
    """A TIMED native process (VM.timed_handle) under the task's serial, valid for the Wait task's ticks left."""
    c = vmmod.Process(vm, s.serial, parse.Block('TIMED', 'native', 0, None), None, None)
    c.code = vmmod.Code(c.block)
    c.owner = 'level'
    c.gen = iter([max(int.from_bytes(s.a[WAIT_REMAINING:WAIT_REMAINING + 2], 'little'), 1)])
    vm.procs[s.serial] = c
    vm.run(c)
    return c


def _process(world, vm, s, names):
    rec = s.proc()
    f = _file(vm, rec.script)
    block = f.defs.get(rec.block - 1) if f else None
    if block is None:
        world.warn(f'resume: slot {s.index}: block #{rec.block} of {rec.script} not found')
        return None
    code, idx = vm.locate(block, rec.pc)
    cur = rec.cur_obj if names.rec(rec.cur_obj) else rec.obj_a        # the constructor starts the context at obj_a
    tag = names.tag(cur)
    ctx = types.SimpleNamespace(cur_fig=names.name(cur) if tag in ('FIGR', 'PLAY') else None,
                                cur_item=names.item_keys.get(cur, names.name(cur)) if tag == 'ITEM' else None, owner='level')
    p = vm.adopt(block, idx, s.serial, ctx)
    p.locals[:len(rec.locals)] = rec.locals
    p.cameras = [names.name(o).upper() for o in rec.objs]        # the LINKMETOCAMERAS list (10c0:4362 registers it again)
    p.suspended = bool(int.from_bytes(s.a[0xe:0x10], 'little') & 1)     # flag bit 0 (+0xe), in the task memory the save keeps: a paused AI stays paused (1230:0259 skips it)
    _, i0 = vm.locate(block, rec.pc0)
    ts = code.ins[i0].ts if rec.pc != rec.pc0 else None
    if ts is not None:                                    # timeline: the pc0 line was just executed; ASSUMPTION: its clock origin
        p.origin = vm.tick - ts                           # is not saved (not in the record), so the next line waits its delta
    return p


def _wait_state(world, vm, sd, slot, p, rec, made):
    """Blocked on a Wait task -> sleep for its remaining ticks (u16 at +0x40, same unit as `WAIT n`); on a process -> CALL
    child (pc == pc0: the statement is re-entered with the child pending) or SUSPENDWHILE target; nothing -> run next tick.
    Evidence (both samples): list1 of a blocked process holds the task it waits for; the Wait task's owner is the process."""
    blockers = [b for b in rec.l1 if b != MLIST_END]
    for b in blockers:
        t = sd.slot(b)
        if t is not None and t.vtable == WAIT_VTABLE and b not in made:      # its own WAIT (a timed handle is in `made`)
            p.wake = vm.tick + int.from_bytes(t.a[WAIT_REMAINING:WAIT_REMAINING + 2], 'little')
        elif b in made:
            child = made[b][0]
            p.wait_on = child
            child.waiters.append(p)
            if rec.pc == rec.pc0:
                stmt = vm.code(p.block).ins[p.pc].stmt
                node = next((c for c in _calls(stmt.args) if c[1] == 'CALL' and c[2] and c[2][0][0] == 'name'
                             and str(c[2][0][1]).upper() == child.block.name.upper()), None) if stmt else None
                if node is None:
                    world.warn(f'resume: {p.block.name}: CALL of {child.block.name} not found at pc {rec.pc:#x}')
                else:
                    p.pending[id(node)] = child
        else:
            world.warn(f'resume: {p.block.name}: blocked on unknown task slot {b}')


def _ramp(world, vm, s):
    """MODIFYVAREVERYNTH(var, step, start, end, n) task: the variable is found by matching the literal step/start/end/n of a
    call site in the loaded scripts (ASSUMPTION: the saved far pointer cannot be mapped to a variable otherwise)."""
    import struct
    a = s.a
    cur, = struct.unpack_from('<i', a, 0x45)
    step, end, start, period, left = struct.unpack_from('<hhhHH', a, 0x49)
    want = [step, start, end, period]
    tgt = None
    for f in vm.files:
        for b in f.blocks:
            for st in parse.walk(b.body):
                for c in _calls(st.args):
                    if c[1] == 'MODIFYVAREVERYNTH' and len(c[2]) >= 5 and c[2][0][0] == 'var' \
                            and [x[1] if x[0] == 'num' else None for x in c[2][1:5]] == want:
                        tgt = c[2][0]
    if tgt is None:
        world.warn(f'resume: MODIFYVAREVERYNTH task {s.serial}: no call site with args {want}')
        return
    c = vmmod.Process(vm, s.serial, parse.Block('MODIFYVAREVERYNTH', 'native', 0, None), None, None)
    c.code = vmmod.Code(c.block)

    def gen():
        v, wait = cur, left
        while v != end and (v - end) * step < 0:
            yield max(wait, 1)
            wait, v = period, v + step
            vm.assign(c, tgt, v)
    c.gen = gen()
    vm.procs[s.serial] = c
    vm.run(c)
    return c
