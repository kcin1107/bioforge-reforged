"""Floors: the script statements SETFLOOROFPHYS (10d0:708e) and TELEPORTALLONPHYS (10d0:7d5b), the garage elevator of CONTROL
(CONMACH.scr RAISE_GARAGE_ELEVATOR / LOWER_GARAGE_ELEVATOR). The Swift twin is WorldFloors.swift.

World mixes `FloorsMixin` in; world.py calls `cmd_setfloorofphys` and `cmd_teleportallonphys`. Both look the PHYS up by name like
AMINEXTENT does (FUN_1050_0996: the first PHYS of that name) and never block.

SETFLOOROFPHYS moves one PHYS box in z (the box keeps its height); TELEPORTALLONPHYS carries every item and figure whose hull lies
strictly inside box A in x and y over to box B, scaled between the two boxes, seated on B's floor. The scripts turn the player's gravity
off for the ride, so SetPos does not snap the player to the support. The engine also persists the moved box in the level state / saves
(INFERRED) and sets DAT_222c = 2 so loose items re-check their support for ~2 frames: NOT PORTED.
"""
import sys

import numpy as np


def _w(world):
    return sys.modules[type(world).__module__]


def s16(value):
    value = int(value) & 0xffff
    return value - 0x10000 if value & 0x8000 else value


class FloorsMixin:
    def find_phys(self, name):
        """The first PHYS named ``name`` (FUN_1050_0996, as AMINEXTENT), or None."""
        return next((p for p in self.phys if p['name'] == name), None)

    # ---- SETFLOOROFPHYS
    def cmd_setfloorofphys(self, proc, args):
        """`SETFLOOROFPHYS <name> <n>` (10d0:708e): n is only its low 16 bits, signed (MOV SI,[ctx+0xe2b]; CWD at 10d0:70a7), in script
        coordinate units (v = n << 8, as COORDZ). Warnings (nothing moves): no name (0xfc); n & 0xffff == 0 (0xfd: `X 0` is an error, not a
        move); no such PHYS (0x8b); a state that is neither 0 nor 1 (0x100). With h = hi.z - lo.z: state 0 (space) lo.z = v, hi.z = v + h;
        state 1 (solid) hi.z = v, lo.z = v - h. x and y are untouched and no object moves."""
        flat = [a for v in args for a in (v if isinstance(v, list) else [v])]
        words, nums = [str(a).upper() for a in flat if isinstance(a, str)], [a for a in flat if isinstance(a, int)]
        if not words or not words[0]:
            self.warn('SETFLOOROFPHYS: needs a PHYS name (error 0xfc)')
            return
        n = s16(nums[0]) if nums else 0
        if n == 0:
            self.warn(f'SETFLOOROFPHYS {words[0]}: needs a non-zero floor (error 0xfd)')
            return
        phys = self.find_phys(words[0])
        if phys is None:
            self.warn(f'SETFLOOROFPHYS {words[0]}: no such PHYS (error 0x8b)')
            return
        state = self.phys_state(phys)
        if state not in (0, 1):
            self.warn(f'SETFLOOROFPHYS {words[0]}: PHYS state {state} (error 0x100)')
            return
        v, h = n << 8, int(phys['hi'][2]) - int(phys['lo'][2])
        lo, hi = (v, v + h) if state == 0 else (v - h, v)
        tick = self.vm.tick if self.vm is not None else 0
        for fig in self.figures.values():       # 708e rebuilds no hulls: fig+0x65 stays as 21b2 last left it (before the floor moves)
            if fig.pos is not None and (fig.stored_hull is None or fig.stored_hull[0] != tick):
                fig.stored_hull = (tick, *self.query_hull(fig)[:2])
        phys['lo'][2], phys['hi'][2] = lo, hi
        cached = self._boxes is not None          # step() caches the boxes for the figures; the script runs inside it (`_areas` is keyed to them)
        self._boxes = None
        if cached:
            self._boxes = self._phys_boxes()

    # ---- TELEPORTALLONPHYS
    def cmd_teleportallonphys(self, proc, args):
        """`TELEPORTALLONPHYS <A> <B>` (10d0:7d5b): every item (the item list, then the figure list: the player too, hidden or dead ones
        not excluded) whose hull lies STRICTLY inside A in x and y (FUN_1058_18b4; z is not tested) moves to B: x' = B.lo.x +
        fix_mul(x - A.lo.x, sx), y' likewise, sx = fix_div(B width x, A width x), z' = B's floor + (z - hull bottom), so the height above
        the object's own hull bottom (+0x6d) is kept. B's floor is lo.z for a state 0 box and hi.z for state 1. The set is evaluated before
        anything moves; each object then gets its SetPos (figures: set_pos, which zeroes velocity / step; items: 1070:1e9d, no snap).
        Warnings (nothing moves): a missing name (0xff), no such PHYS (0x15), a B state that is neither 0 nor 1. A zero-width A is guarded
        (ASSUMPTION: scale 256, the engine would divide by zero). ASSUMPTION: an item has no hull in the port, its xy test uses the point
        position and its hull bottom is z - EXTENT z (0 when its physics are not loaded yet; a missile has its extent from the start);
        a carried item (pos None) is skipped."""
        W = _w(self)
        words = [str(a).upper() for a in args if isinstance(a, str)]
        if len(words) < 2 or not words[0] or not words[1]:
            self.warn('TELEPORTALLONPHYS: needs two PHYS names (error 0xff)')
            return
        a, b = self.find_phys(words[0]), self.find_phys(words[1])
        for name, p in zip(words, (a, b)):
            if p is None:
                self.warn(f'TELEPORTALLONPHYS {name}: no such PHYS (error 0x15)')
                return
        state = self.phys_state(b)
        if state not in (0, 1):
            self.warn(f'TELEPORTALLONPHYS {words[1]}: PHYS state {state}')
            return
        alo, ahi, blo, bhi = ([int(c) for c in box[k]] for box in (a, b) for k in ('lo', 'hi'))
        scale = [W.fix_div(bhi[k] - blo[k], ahi[k] - alo[k]) if ahi[k] != alo[k] else 256 for k in (0, 1)]
        floor = blo[2] if state == 0 else bhi[2]

        def inside(lo, hi):
            return all(alo[k] < lo[k] and hi[k] < ahi[k] for k in (0, 1))

        def xy(x, y):
            return [blo[k] + W.fix_mul(c - alo[k], scale[k]) for k, c in enumerate((x, y))]

        moves = []
        for it in self.items.values():
            if it.pos is None:
                continue
            x, y = (int(round(c)) for c in it.pos[:2])
            dz = it.extent[2] if it.physics_loaded or it.missile else 0
            if inside((x, y), (x, y)):
                moves.append((it, xy(x, y) + [floor + dz]))
        for fig in self.figures.values():
            if fig.pos is None:
                continue
            # 10d0:7d5b reads the hull at fig+0x65/+0x6d, the one 21b2 built before this script's SETFLOOROFPHYS moved a floor
            tick = self.vm.tick if self.vm is not None else 0
            lo, hi = fig.stored_hull[1:] if fig.stored_hull is not None and fig.stored_hull[0] == tick else self.query_hull(fig)[:2]
            if inside(lo, hi):
                x, y = (int(round(c)) for c in fig.pos[:2])
                moves.append((fig, xy(x, y) + [fig.pos[2] + floor - lo[2]]))
        for obj, pos in moves:
            if isinstance(obj, W.Item):
                obj.pos = np.array(pos, float)
                obj.vel, obj.step = [0, 0, 0], [0, 0, 0]
            else:
                self.set_pos(obj, pos)
