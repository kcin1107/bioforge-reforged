"""Missiles: the script function FIRE and the engine's missile task (class 0x10c, ctor FUN_10e0_0440, tick FUN_10e0_0cbc).

World mixes `MissilesMixin` in; world.py calls `cmd_fire`, `move_missiles` and `tick_missiles`. MAKEMISSILE will reuse `spawn_missile`.

A missile is two engine objects: the task (kernel handle, range, spin, hit logic) and its figure, an ordinary Item (mesh
ITEMS/<TYPE>.IFF; ZIPPY and TOSS have none and are invisible). The port keeps one record, `Missile(Item)`, inserted in `World.items`
under a unique key so that CURITEM can name it in the hit scripts, and a native VM process as the handle.

Per 30 Hz frame (FUN_1150 -> 1110:08bf, then the scheduler 1230:0259): the world update moves the item list (Item::Update 1078:1490
-> Move 1078:08f6, `move_missiles`) before the figures; the task tick (`tick_missiles`) comes later with the scripts.
  * Move: step = velocity_step(v); a missile with flag 0x02 (CARRY) just goes there. Otherwise it is cut into sub-steps like the figure
    mover (FUN_10a0_22e1, span = its EXTENT box); every sub-step tests the PHYS volumes (FUN_1058_1a1b, score > 0) and the figures'
    +0x65 bounds (FUN_1110_0b29: the first figure in list order that overlaps). A PHYS block stops the missile and zeroes its velocity
    (FUN_1070_1d8f) unless it is a rebound (bouncy, or reflective at a collider with flag byte 21 & 4: FUN_1070_0fa7, the missile flies on); a figure overlap is only remembered (+0x135) and handled by the tick.
  * Tick: hit check (FUN_10e0_0961) unless flag 0x02, orientation, range -= |step| (FUN_1210_0f9b); at range < 0 or zero velocity the
    block `<TYPE>_HIT_WALL` runs (CURFIG none, CURITEM the missile) and the missile is destroyed (vtable +8, FUN_10e0_1239).
FIRE returns the handle; `SUSPENDWHILE FIRE ...` waits for the missile to die. CARRY attaches an object to the missile (FUN_1138_05ff).
"""
import math
import sys
import types

import numpy as np

import items as items_mod
import salsa
from scene import place

NO_RANGE = -9999999     # 0xFF676981: the range of a missile that was made inside geometry (it expires on its first tick)
CARRY_FLAG = 0x02       # flags (+0x34) bit 0x02: collisions off, set by FIRE's CARRY
PUSH_OUT_CAP = 1000     # owner push-out iterations (the engine loop has no cap)


def _w(world):
    return sys.modules[type(world).__module__]


def unit24(v):
    """A direction as a 24.8 vector (256 = 1.0). ASSUMPTION: float arithmetic rounded to the nearest integer; the engine's
    FUN_1208_09ff (FUN_1208_0b86 shifts, FUN_1208_002c length, FUN_1210_0c24 divides) is not ported. Both ports use the same form."""
    n = math.sqrt(sum(float(c) * float(c) for c in v))
    return [0, 0, 0] if n == 0 else [round(256 * c / n) for c in v]


def cross24(a, b):
    """FUN_1208_0154: a x b with every product through the 24.8 multiply (0c42)."""
    fm = _w_fix_mul
    return [fm(a[1], b[2]) - fm(a[2], b[1]), fm(a[2], b[0]) - fm(a[0], b[2]), fm(a[0], b[1]) - fm(a[1], b[0])]


def _w_fix_mul(a, b):
    return (int(a) * int(b)) >> 8        # world.fix_mul without its 32-bit wrap (a unit vector times a position stays far below it)


def spin_rows(rows, spin):
    """The tumbling orientation (tick FUN_10e0_0cbc): every row turned by a degrees about X, then b about Y, then c about Z.
    ASSUMPTION: world axes (the engine rotates the figure matrix with FUN_1208_2548 / 2858 / 2b64, whose axis frame is not decoded);
    drawing only."""
    ra, rb, rc = (math.radians(d) for d in spin)
    out = []
    for x, y, z in rows:
        x, y, z = float(x), float(y), float(z)
        y, z = y * math.cos(ra) - z * math.sin(ra), y * math.sin(ra) + z * math.cos(ra)
        x, z = x * math.cos(rb) + z * math.sin(rb), z * math.cos(rb) - x * math.sin(rb)
        x, y = x * math.cos(rc) - y * math.sin(rc), x * math.sin(rc) + y * math.cos(rc)
        out.append([round(x), round(y), round(z)])
    return out


class MissilesMixin:
    # ---- FIRE
    def script_point(self, proc, ref):
        """The world position FUN_10c0_152f's object gives through vtable +0x50: a WAYP's position, the centre of a PHYS / IMAG box
        (per axis trunc((lo + hi) / 2), as box_distance), a figure's or floor item's position (CURFIG / CURITEM / a name).
        -> [x, y, z] ints or None. ASSUMPTION: waypoints before boxes before figures and items (the lookup order is not decoded)."""
        W = _w(self)
        name = str(ref).upper()
        if name in self.waypoints:
            p = self.waypoints[name]
        else:
            box = next((b for b in self.phys + self.triggers if b['name'].upper() == name), None)
            if box is not None:
                return [W.fix_div(int(lo) + int(hi), 0x200) for lo, hi in zip(box['lo'], box['hi'])]
            obj = self.script_object(proc, name)
            if obj is None or obj.pos is None:
                return None
            p = obj.pos
        return [int(round(c)) for c in np.asarray(p, float)[:3]]

    def cmd_fire(self, proc, args):
        """FIRE (10d8:18a0): `<type> <from> <to> <speed> <a> <b> <c> [CARRY <obj>]` or `<type> <from> AT <x> <y> <z> <speed> <a> <b> <c>
        [CARRY <obj>]`. The missile flies the straight line from the start to the destination at `speed` m/s (speed * 2048 units a
        second) and has range = the approximate length of that line (FUN_1210_0f9b), so it dies at the destination. The matrix rows
        are {U, D, R}: D the travel direction, R = normalised (start position x D) (an original quirk: the raw start POSITION is the
        first operand), U = D x R, both negated when R.z < 0. AT coordinates are script integers (<< 8). Missing names or an unknown
        object are errors (-> 0). -> the missile's handle."""
        W = _w(self)
        words = [a if isinstance(a, str) else '' for a in args[:3]]
        if len(args) < 3 or not all(words):
            self.warn('FIRE: needs a type, a start and a destination')
            return 0
        mtype, at = words[0].upper(), words[2].upper() == 'AT'
        nums = [a for a in args[3:] if isinstance(a, int)]
        nums += [0] * ((7 if at else 4) - len(nums))
        start = self.script_point(proc, words[1])
        end = None if at else self.script_point(proc, words[2])
        if start is None or (end is None and not at):
            self.warn(f'FIRE {" ".join(str(a) for a in args[:3])}: no such object')
            return 0
        if at:
            end, speed, spin = [c << 8 for c in nums[:3]], nums[3], nums[4:7]
        else:
            speed, spin = nums[0], nums[1:4]
        delta = [e - s for e, s in zip(end, start)]
        d = unit24(delta)
        r = unit24(cross24(start, d))
        u = cross24(d, r)
        if r[2] < 0:
            r, u = [-c for c in r], [-c for c in u]
        m = self.spawn_missile(mtype, start, [u, d, r], W.s32((speed * 80 // 10) << 8), W.approx_length(delta), spin)
        words_after = [str(a).upper() if isinstance(a, str) else '' for a in args[3:]]
        if 'CARRY' in words_after:
            m.no_collide = True                         # *(figure + 0x34) |= 2, after the constructor (the spawn test ran without it)
            k = 3 + words_after.index('CARRY')
            carried = self.script_object(proc, args[k + 1]) if len(args) > k + 1 else None
            if carried is not None:
                self.attach_carried(m, carried)
        return m.handle

    # ---- MAKEMISSILE
    def item_world_pose(self, item):
        """The item's world position and matrix as the renderer places it (items.item_cels): a floor item's own, a held item's hand_pose
        turned by -heading about its holder. -> (pos, 3x3 rows) or None."""
        if item.owner is None:
            return (np.asarray(item.pos, float), np.asarray(item.matrix, float)) if item.pos is not None else None
        fig = self.figures.get(item.owner)
        pose = self.hand_pose(fig, item) if fig is not None and fig.pos is not None else None
        if pose is None:
            return None
        return place(pose[0][None, :], fig.pos, -fig.heading)[0], place(pose[1], np.zeros(3), -fig.heading)

    def cmd_makemissile(self, proc, args):
        """MAKEMISSILE (10d8:3030): `<TYPE> [<LIMB>] <speed> <range> (<a>,<b>,<c>)`; speed and range are metres (n * 2048 units, as FIRE).
        Without a current item the shot leaves CURFIG's limb of that name: matrix = the limb's world matrix, pos = the limb end - row 1 *
        its length (ASSUMPTION: the port has no per-limb scale, so the scaled length 0c42(+0x5e, scale) is the plain length), travel =
        +row 1; no figure, limb name or such limb: 0 without a message. With a current item the shot leaves the item (the limb name is
        ignored): its world position, its matrix with all nine components negated (travel = -row 1). The owner is CURFIG (spawn_missile
        pushes the shot out of its box). -> the missile's handle."""
        W = _w(self)
        flat = [a for v in args for a in (v if isinstance(v, list) else [v])]
        words, nums = [a for a in flat if isinstance(a, str)], [a for a in flat if isinstance(a, int)]
        nums += [0] * (5 - len(nums))
        if not words:
            self.warn('MAKEMISSILE: needs a missile type')
            return 0
        fig, item = self.figure(proc.cur_fig), self.items.get(proc.cur_item) if proc.cur_item else None
        if item is None:
            if fig is None or fig.pos is None or len(words) < 2:
                return 0
            i = next((k for k, l in enumerate(fig.assets.skel) if l.name.upper() == words[1].upper()), None)   # FUN_1040_17d6
            if i is None:
                return 0
            frame = None                                                # a type without motions keeps its rest pose
            if fig.frames:
                p, _, l = fig.frames[min(fig.idx, len(fig.frames) - 1)]
                frame = ((0, 0, p[2]), (0, 0, 0), l)
            _, R, end = salsa.solve(fig.assets.skel, frame)
            rows = [[round(256 * c) for c in r] for r in place(np.asarray(R[i], float), np.zeros(3), -fig.heading)]
            tip = place(np.asarray(end[i], float)[None, :], fig.pos, -fig.heading)[0]
            pos = [round(tip[j]) - W.fix_mul(rows[1][j], fig.assets.skel[i].length) for j in range(3)]
        else:
            pose = self.item_world_pose(item)
            if pose is None:
                return 0
            pos = [round(c) for c in pose[0]]
            rows = [[-round(256 * c) for c in r] for r in pose[1]]
        units = lambda n: W.s32((n * 80 // 10) << 8)
        return self.spawn_missile(words[0].upper(), pos, rows, units(nums[0]), units(nums[1]), nums[2:5], fig).handle

    # ---- the missile task
    def spawn_missile(self, mtype, pos, rows, speed32, dist, spin, owner=None):
        """The constructor FUN_10e0_0440. `rows` = the travel matrix {U, D, R} in 24.8 (D, row 1, the travel direction); `speed32` =
        speed * 2048 (units a second); `dist` = range in units; `spin` = (a, b, c) degrees a tick about X, Y, Z. The figure is turned
        180 degrees about Z (rows 0 and 1 negated: its row 1 is backward), velocity = row 1 * trunc(speed32 << 8 / 0x1e00) >> 8 per
        axis. Type properties come from the script block named <TYPE> (EXTENT in cm: units (cm << 11) / 100, ASSUMPTION for the
        shift). Plays `_<TYPE>_FIRE` and starts `_<TYPE>_TRAVEL` (looped, positional) when those samples exist. A missile whose box
        already overlaps solid PHYS gets the range -9999999 and no velocity (it expires on its first tick). -> the Missile"""
        W = _w(self)
        key, n = mtype, 2
        while key in self.items:
            key, n = f'{mtype}_{n}', n + 1
        m = self.items[key] = W.Missile(key, mtype)
        self.missile_type_props(m)
        m.pos = np.array(pos, float)
        m.set_rows([[-c for c in rows[0]], [-c for c in rows[1]], list(rows[2])])
        k = W.fix_div(speed32, 0x1e00)
        m.vel = [W.fix_mul(c, k) for c in rows[1]]
        if owner is not None and owner.pos is not None:                 # ctor 10e0:0631..06f5: out of the shooter's +0x65 box
            olo, ohi, _ = self.query_hull(owner)
            pos = [int(c) for c in m.pos]
            for _ in range(PUSH_OUT_CAP):                               # do { pos += row1 (travel, up to 256 units) } while overlap
                pos = [c + r for c, r in zip(pos, rows[1])]
                if not self.boxes_touch([pos[j] - m.extent[j] for j in range(3)], [pos[j] + m.extent[j] for j in range(3)], olo, ohi):
                    break
            else:
                self.warn(f'{mtype}: could not push the missile out of {owner.name}')
            m.pos = np.array(pos, float)
        m.dist, m.spin, m.owner_fig = int(dist), tuple(W.s32(c << 16) >> 16 for c in spin), owner      # a, b, c: low 16 bits
        if self.vm is not None:
            m.handle = self.vm.native_handle('MISSILE')
        fire = self.sound_index(f'_{mtype}_FIRE')
        if fire is not None:
            self.play_sound(fire)
        travel = self.sound_index(f'_{mtype}_TRAVEL')
        if travel is not None:
            m.sound = self.play_sound(travel, loop=True, fig=m)
        if not m.no_collide and self.missile_blocked(m, [int(c) for c in m.pos]):
            m.dist, m.vel = NO_RANGE, [0, 0, 0]
        return m

    def missile_type_props(self, m):
        """The type's properties from the script block <TYPE> (1078:0214): bouncy, reflective, gravity, elasticity, EXTENT."""
        W = _w(self)
        def prop(name, default):
            vals = self.item_prop(m.type, name)
            return int(vals[0]) if vals else default
        m.bouncy, m.reflective = bool(prop('IS_BOUNCY', 0)), bool(prop('IS_REFLECTIVE', 0))
        m.gravity = bool(prop('HAS_GRAVITY', 1))        # not modelled: no shipped missile has gravity (Item::Update would add it)
        m.elasticity = prop('ELASTICITY', 200)
        vals = self.item_prop(m.type, 'EXTENT')
        m.extent = [W.hull_units(int(c)) for c in vals[:3]] if vals and len(vals) >= 3 else [0, 0, 0]

    def missile_blocked(self, m, p):
        """FUN_1058_1a1b for the missile's box at ``p``: pos +- EXTENT against the PHYS volumes, score > 0. ASSUMPTION: no PHYS area is
        selected (the null-area path, FUN_1058_192f): every PHYS of the level counts."""
        return self.null_area_blocked([p[k] - m.extent[k] for k in range(3)], [p[k] + m.extent[k] for k in range(3)])

    def missile_touch(self, m, p):
        """FUN_1110_0b29: the first figure (list order) whose +0x65 bounds overlap the missile's box at ``p`` (inclusive, hidden and
        unplaced figures skipped) becomes the hit object (+0x135); the first one found during a move is kept."""
        if m.hit is not None:
            return
        lo, hi = [p[k] - m.extent[k] for k in range(3)], [p[k] + m.extent[k] for k in range(3)]
        for fig in self.figures.values():
            if fig.pos is None or fig.hidden:
                continue
            flo, fhi, _ = self.query_hull(fig)
            if self.boxes_touch(lo, hi, flo, fhi):
                m.hit = fig
                return

    def move_missiles(self):
        """The item list part of the world update: every missile moves, then places what it carries."""
        for m in [i for i in self.items.values() if i.missile]:
            self.move_missile(m)
            if m.carried is not None:
                self.place_carried(m)

    def move_missile(self, m):
        """Item::Update + Move (1078:1490, 1078:08f6; see the module doc). A block stops the missile at the last good sub-step position
        with its velocity zeroed, the step scaled by the finished share of the move, unless the block is a rebound: a bouncy missile, or a
        reflective one (LASER, BOLTPFD, TNFABOLT) whose collider PHYS has flag byte (record byte 21) & 4, takes the generic rebound
        (FUN_1070_1d8f -> 0fa7, item_blocked) and goes on flying."""
        W = _w(self)
        m.hit = None
        start = [int(c) for c in m.pos]
        m.step = W.velocity_step(m.vel)
        target = [s + d for s, d in zip(start, m.step)]
        if m.no_collide:                                # CARRY: pos := target, no tests at all
            m.pos = np.array(target, float)
            return
        spans = [2 * e for e in m.extent]
        n = W.move_steps(m.step, min(spans)) if min(spans) > 0 and not all(abs(m.step[k]) < spans[k] for k in range(3)) else 0
        inc = [W.fix_div(m.step[k], n << 8) for k in range(3)] if n > 0 else None
        good = start
        for i in range(1, n + 1):
            cand = [start[k] + inc[k] * i for k in range(3)]
            if self.missile_blocked(m, cand):
                return self.stop_missile(m, start, cand, good, i - 1, n)
            self.missile_touch(m, cand)
            good = cand
        if self.missile_blocked(m, target):
            return self.stop_missile(m, start, target, good, n, n)
        self.missile_touch(m, target)
        m.pos = np.array(target, float)

    def stop_missile(self, m, start, p, good, done, n):
        W = _w(self)
        self.item_blocked(m, start, p, good, W.scale_step(m.step, done, n) if n > 0 else [0, 0, 0])

    def tick_missiles(self):
        """The task tick of every missile (vtable +0), after the figures."""
        for m in [i for i in self.items.values() if i.missile]:
            if not m.dead:
                self.tick_missile(m)

    def tick_missile(self, m):
        """FUN_10e0_0cbc. Skipped while the range is the spawn-in-geometry sentinel: hit check (not with flag 0x02), orientation, range
        -= |step|. Then range < 0 or no velocity ends the missile with <TYPE>_HIT_WALL. ASSUMPTION: the VM processes and the missile
        tasks are not interleaved by kernel slot; the missile ticks run after the world update, before the next VM tick."""
        W = _w(self)
        if m.dist != NO_RANGE:
            if not m.no_collide and self.missile_hit(m):
                return
            m.set_rows(spin_rows(m.rows, m.spin) if any(m.spin) else self.aim_rows(m))
            m.dist -= W.approx_length(m.step)
        if m.dist < 0 or W.approx_length(m.vel) == 0:
            self.run_missile_block(m, f'{m.type}_HIT_WALL', None)
            self.destroy_missile(m)

    @staticmethod
    def aim_rows(m):
        """Without spin the figure is re-aimed along its flight: row 1 = -velocity, re-orthonormalised (1208:095b) from row 1 and the
        old row 2 (ASSUMPTION for the construction; drawing only). Zero velocity keeps the orientation."""
        r1 = unit24([-c for c in m.vel])
        r0 = unit24(cross24(r1, m.rows[2]))
        if not any(r1) or not any(r0):
            return m.rows
        return [r0, r1, unit24(cross24(r0, r1))]

    def missile_hit(self, m):
        """FUN_10e0_0961. The hit object (cleared here) is run as `<TYPE>_HIT_<instance>` else `<TYPE>_HIT` with CURFIG = it and
        CURITEM = the missile, then the missile is destroyed (-> True). A reflective missile meeting a reflective figure keeps flying
        with its speed turned by a random yaw 5..355 degrees and pitch -20..20 (-> False). The figure's flag test (0x08, "removed" in
        the spec) is not applied: bit 0x08 is INVULNERABLE in the ports, and killed figures have left `figures`. ASSUMPTION: the speed
        is the integer length of the velocity (FUN_1208_002c is not ported) and the new direction is built in floats."""
        W = _w(self)
        t, m.hit = m.hit, None
        if t is None or self.figures.get(t.name) is not t or t.invulnerable:      # 10e0:0961: +0x34 bit 0x08 returns 0, no HIT and the missile flies on
            return False
        if not (m.reflective and int(W.form_prop(t, 'IS_REFLECTIVE', 0))):
            blocks = self.vm.blocks if self.vm is not None else {}
            block = f'{m.type}_HIT_{t.name}'
            self.run_missile_block(m, block if block in blocks else f'{m.type}_HIT', t)
            self.destroy_missile(m)
            return True
        speed = math.isqrt(sum(c * c for c in m.vel))
        dx, dy, _ = unit24([m.vel[0], m.vel[1], 0])
        yaw, pitch = math.radians(self.rng.randint(5, 355)), math.radians(self.rng.randint(0, 40) - 20)
        x, y = dx * math.cos(yaw) - dy * math.sin(yaw), dx * math.sin(yaw) + dy * math.cos(yaw)
        row1 = [round(x * math.cos(pitch)), round(y * math.cos(pitch)), round(256 * math.sin(pitch))]
        m.vel = [W.fix_mul(c, speed) for c in row1]
        return False

    def run_missile_block(self, m, block, fig):
        """FUN_1120_0035: start the script block if it exists, CURFIG = ``fig`` (or none), CURITEM = the missile; its first slice
        runs at once."""
        if self.vm is not None and block in self.vm.blocks:
            self.vm.spawn(block, ctx=types.SimpleNamespace(cur_fig=fig.name if fig else None, cur_item=m.key, owner='level'))

    def destroy_missile(self, m):
        """Vtable +8 (FUN_10e0_1239): the travel sound stops, what the missile carries is released where it is (SetPos: velocity
        zeroed), the figure leaves the item list, and the handle dies, waking the SUSPENDWHILE waiters. They only become
        ready (1238:077f) and run in the next walk, so they see the final state."""
        if m.dead:
            return
        m.dead = True
        if m.sound:
            self.stop_sound(m.sound)
        if m.carried is not None:
            self.detach_carried(m)
        if self.items.get(m.key) is m:
            del self.items[m.key]
        self.kill_item_referents(m)
        if self.vm is not None and m.handle in self.vm.procs:
            self.vm.finish(self.vm.procs[m.handle])

    def end_missiles_for_level_change(self):
        """LOADLEVEL's first act (FUN_10d0_4d46, 10d0.c:4280-4287): every live missile task, in creation order, takes the hit-then-destroy entry
        (vtable +0xc, FUN_10e0_11aa). A stored hit target runs <TYPE>_HIT_<inst> / <TYPE>_HIT and the missile is destroyed (missile_hit);
        otherwise the missile is destroyed with no <TYPE>_HIT_WALL: the travel sound stops, a rider is released where the missile is, the
        item is removed (so the level's IFF never keeps it) and the handle finishes (a waiter wakes and then dies with the level's processes)."""
        for m in [i for i in self.items.values() if i.missile and not i.dead]:
            if not self.missile_hit(m):
                self.destroy_missile(m)

    # ---- CARRY
    def attach_carried(self, m, obj):
        """FUN_1138_05ff: ``obj`` (a figure or item) is attached to the missile figure (+0x2c). ASSUMPTION: its pose is the missile's
        origin (no ON_<CARRIER> property exists for the shipped carriers, and the limb formula FUN_1038_035b for a limbless carrier is
        not decoded). An attached figure skips its own move, gravity, grounding and pushes (FUN_1088_39ef) but keeps animating; an
        item is held by the missile (owner = its key) and is not a floor item meanwhile."""
        m.carried = obj
        if hasattr(obj, 'carrier'):
            obj.carrier = m.name
        else:
            obj.owner, obj.slot = m.name, 'CARRIED'

    def carry_pose(self, m, c):
        """FUN_1138_05ff / FUN_1088_5c19 with the missile as the carrier "limb": the carried object's own type property
        `ON_<MISSILE TYPE>` (figures: FIGURES.scr, `(I,J,K) LENGTH (X,Y,Z)` positional; items: ITEMS.scr, `(0I,0J,0K) 0LENGTH
        (0X,0Y,0Z)`; cm and degrees) gives origin = missile origin + offset in the missile's axes + LENGTH along the turned row 1,
        and the matrix the missile's rotated by the angles (as items.py hand_pose). ASSUMPTION: a limbless carrier uses its
        origin and orientation. No property: the missile's own pose. -> (origin, matrix)"""
        W = _w(self)
        name = 'ON_' + m.type
        if hasattr(c, 'carrier'):
            props = W.figure_props()
            vals = props.get(c.name.upper(), {}).get(name) or props.get(c.type.upper(), {}).get(name)
        else:
            vals = self.item_prop(c.type, name)
        vals = vals or []
        if len(vals) == 7 and all(isinstance(v, int) for v in vals):
            a = dict(zip(('I', 'J', 'K', 'LENGTH', 'X', 'Y', 'Z'), vals))
        else:
            a = items_mod.parse_numbers(vals)
        ang = tuple(items_mod.c_div(a.get(k, 0) * 32, 45) for k in 'IJK')
        off = np.array([items_mod.attach_units(a.get(k, 0)) for k in 'XYZ'], float)
        M = salsa.rotate(m.matrix, ang)
        return m.pos + off @ m.matrix + M[1] * items_mod.attach_units(a.get('LENGTH', 0)), M

    def place_carried(self, m):
        c = m.carried
        origin, M = self.carry_pose(m, c)
        if hasattr(c, 'carrier'):
            self.place_figure(c, origin)
        else:
            c.pos, c.matrix = origin, M

    @staticmethod
    def place_figure(fig, pos):
        fig.pos = np.array(pos, float)
        fig.prev_pos = fig.last_good = fig.pos.copy()

    def detach_carried(self, m):
        """FUN_1078:07c3 -> SetPos at the current position (vtable +0x58, velocity zeroed)."""
        c, m.carried = m.carried, None
        if hasattr(c, 'carrier'):
            c.carrier = None
            if c.pos is not None:
                self.set_pos(c, c.pos, raw=True)
        else:
            c.owner = c.slot = None
