"""Effects: the script statements MAKEFLATOBJECT (10d0:52ff), EXPLODE (10d0:2841) and THROWCURITEM (10d0:84d0), and the free-item physics
THROWCURITEM needs (Item::Update 1078:1490 for items that are not missiles). The Swift twin is WorldEffects.swift.

World mixes `EffectsMixin` in; world.py calls `cmd_makeflatobject`, `cmd_explode`, `cmd_throwcuritem`, `move_free_items`,
`tick_flat_objects` and `flat_cels`.

A flat object (vtable DS:237b, ctor 1080:0afa, list [1d3d]) is an unscaled room-CAM sprite sequence: ROOMS/<cam>.CAM entry <seq>, shown at a world
point (captured when it was made) or a screen position, depth-sorted with the room's cels. Frame 0 is a 320x200 blank. With n > 2 frames the
object starts at frame 1 and advances before each draw (so frame 1 is never shown) until frame >= n; with n <= 2 it stays until DELETE.
ASSUMPTION: one advance per world tick (30 Hz); the engine advances once per drawn frame. EXPLODE hides the figure and what it holds, throws its
shrapnel (`Fragment`, below) and waits 300 / 2 = 150 ticks unless CONTINUE. THROWCURITEM releases the held item at its
world pose and adds a velocity; a free item with a velocity then moves through the missile PHYS sub-step mover with gravity and a bounce.
"""
import copy
import math
import os
import sys
import types

import numpy as np

from cam import frames as cam_frames
from flex import read_flex
from scene import project

SHRAPNEL_SPEED = (220 << 11) // 100    # 10f8:124c's speed [4d96] = 220 through (a << 11) / 100: the length of a fragment's velocity
FRAGMENT_GRAVITY = 240                 # 10f8:19ea: (0x1e00 * ([83a0] / 60)) >> 8 at 30 fps, no cap
FRAGMENT_SPIN = 15                     # degrees per frame about the local X axis (10f8:191a, INFERRED unit)
EXPLODE_TICKS = 300 // 2       # FUN_10f8_1f8a returns 300 (DAT 4d1e); the wait object takes t / 2 ticks
_FRAMES = {}                   # (cam, entry) -> decoded frames, or None


def _w(world):
    return sys.modules[type(world).__module__]


class Fragment:
    """A piece of shrapnel (class DS:4d3a, ctor 10f8:124c, list [1d31]): 1..5 faces of the exploding figure's posed mesh as a rigid body.
    `rel` are its vertices relative to the mean face centre (`pos`), `mesh` the face subset indexed into `rel`; `end` the 60 Hz clock it dies at."""
    def __init__(self, mesh, rel, pos, vel, end, area):
        self.mesh, self.rel, self.pos, self.vel, self.end, self.area, self.angle = mesh, rel, pos, vel, end, area, 0


def flat_frames(rooms, cam, seq):
    """The frames (w, h, hotx, hoty, pixels, mask) of ROOMS/<cam>.CAM's entry named ``seq``, or None."""
    key = (cam, seq)
    if key not in _FRAMES:
        path = os.path.join(rooms, cam + '.CAM')
        found = None
        if os.path.exists(path):
            d, ents = read_flex(path)
            found = next((list(cam_frames(d[off:off + size])) for _, off, size, name in ents[1:] if size and name.upper() == seq), None)
        _FRAMES[key] = found
    return _FRAMES[key]


class FlatObject:
    def __init__(self, cam, frames, point=None, screen=None):
        self.cam, self.frames, self.point, self.screen = cam, frames, point, screen     # point: world [x, y, z]; screen: (x, y, depth)
        n = len(frames)
        self.frame = 1 if n > 2 else n - 1
        self.w = max((f[0] for f in frames[1:]), default=0)         # W, H: the largest frame over 1..n-1
        self.h = max((f[1] for f in frames[1:]), default=0)


class EffectsMixin:
    # ---- MAKEFLATOBJECT
    def cmd_makeflatobject(self, proc, args):
        """`MAKEFLATOBJECT ( cam, seq [, obj] )` or `( cam, seq, x, y, depth )`. seq DELETE removes every flat object of that cam. The
        object form takes the reference point NOW (script_point) and never follows the object; a missing object does nothing. The screen
        form is x, y in 320x200 pixels and the s32 camera depth. A missing CAM or entry is a warning. Never blocks."""
        flat = [a for v in args for a in (v if isinstance(v, list) else [v])]
        words, nums = [str(a).upper() for a in flat if isinstance(a, str)], [a for a in flat if isinstance(a, int)]
        if len(words) < 2:
            self.warn('MAKEFLATOBJECT: needs a CAM and a sequence')
            return
        cam, seq = words[0], words[1]
        if seq == 'DELETE':
            self.flat_objects = [f for f in self.flat_objects if f.cam != cam]
            return
        point = screen = None
        if len(words) > 2:
            point = self.script_point(proc, words[2])
            if point is None:
                return
        else:
            nums += [0] * (3 - len(nums))
            screen = (nums[0], nums[1], nums[2])
        frames = flat_frames(_w(self).ROOMS, cam, seq)
        if not frames:
            self.warn(f'MAKEFLATOBJECT {cam} {seq}: no such sequence')
            return
        self.flat_objects.append(FlatObject(cam, frames, point, screen))

    def tick_flat_objects(self):
        """Per frame: n > 2 advances (pre-increment); an object past its last frame is finished and removed."""
        for f in self.flat_objects:
            if len(f.frames) > 2:
                f.frame += 1
        self.flat_objects = [f for f in self.flat_objects if f.frame < len(f.frames)]

    def flat_cels(self, camera):
        """[(depth, (w, h, hx, hy, pixels, mask))] for compose: top-left = (x - W // 2 - hotx, y - H // 2 - hoty) of the frame's own hot spot
        (hx, hy here are the negated top-left). The world form projects the point through ``camera`` (behind it: skipped), depth = camera
        depth. ASSUMPTION: the room palette applies, the CAM's own is ignored."""
        out = []
        for f in self.flat_objects:
            w, h, hotx, hoty, px, mask = f.frames[f.frame]
            if f.point is not None:
                if camera is None:
                    continue
                u, v, z = project(np.array([f.point], float), camera)[0]
                if not (np.isfinite(u) and np.isfinite(v) and np.isfinite(z)) or z <= 0:
                    continue
                x, y, depth = int(u), int(v), float(z)
            else:
                x, y, depth = f.screen
            out.append((depth, (w, h, -(x - f.w // 2 - hotx), -(y - f.h // 2 - hoty), px, mask)))
        return out

    # ---- EXPLODE
    def cmd_explode(self, proc, args):
        """`EXPLODE <obj> [CONTINUE]`: the object must be the current figure (else a warning, error 0x4c, no wait). t = 300; CONTINUE sets
        -1, any other second word is a warning (error 0x66) that keeps t. t >= 0 blocks the process for t / 2 = 150 ticks (the WAIT
        object). The figure and the items it holds are hidden (it may be gone already: KILL only defers the engine's destruction, the
        port drops the figure at once, so the ref is matched against the current figure's name)."""
        words = [str(a).upper() for a in args if isinstance(a, str)]
        ref = words[0] if words else 'CURFIG'
        cur = self.resolve(proc.cur_fig) if proc.cur_fig else None
        if cur is None or not (ref == 'CURFIG' or self.resolve(ref) == cur):
            self.warn(f'EXPLODE {ref}: not the current figure (error 0x4c)')
            return
        t = 300
        if len(words) > 1 and words[1]:
            if words[1] == 'CONTINUE':
                t = -1
            else:
                self.warn(f'EXPLODE {words[1]}: unknown option (error 0x66)')
        fig = self.figures.get(cur) or self.dead_figures.get(cur)
        if fig is not None and not fig.exploded:
            fig.exploded = True
            for it in self.items.values():
                if it.owner == fig.name:
                    it.hidden = True
            self.spawn_shrapnel(fig)
        if t >= 0 and self.vm is not None:
            until = self.vm.tick + t // 2
            proc.wait_pred = lambda: self.vm.tick >= until

    def spawn_shrapnel(self, fig):
        """10f8:1ea2 (called by 10f8:1f8a): N faces of the figure's mesh (INFERRED: its face count); for first = 0, 10, 20 ... while first < N - 10 a
        fragment takes faces first .. first + n - 1, n = 1, 2, 3, 4, 5, 1 ... The ctor (10f8:124c) puts it at the mean of the faces' centres of the
        posed mesh (world orientation, as it is at this moment: the dying pose; the port keeps a killed figure's object for this) and draws four
        values from the shared LCG that script RANDOM uses (world.rng): vx = R(0, 512) - 256, vy = R(0, 514) - 257, vz = R(0, 516) - 258, the vector
        normalised to length 256 ((c << 8) / len) and scaled by 4505 (a * b >> 8), then the life, clock60 + 60 * (5 - n) + R % 60. The area box
        (fig+0x35 -> +0x16) bounds it. ASSUMPTIONS: the faces taken are all polygons (the engine's face types 0 and 4 are not told apart), the
        figure's own orientation is kept (the look-at frame 10f8:0efe is not applied)."""
        if fig.pos is None or fig.frames is None:
            return
        V = self.posed(fig)
        mesh = fig.assets.mesh
        n_faces, first, n = len(mesh.polys), 0, 1
        while first < n_faces - 10:
            polys = mesh.polys[first:first + n]
            centres = [np.mean([V[i] for i in poly[2]], axis=0) for poly in polys]
            mean = np.mean(centres, axis=0)
            used = sorted({i for poly in polys for i in poly[2]})
            index = {v: k for k, v in enumerate(used)}
            frag_mesh = copy.copy(mesh)
            frag_mesh.polys = [(poly[0], poly[1], [index[i] for i in poly[2]], poly[3], poly[4]) for poly in polys]
            rng = self.rng
            v = [rng.randint(0, 512) - 256, rng.randint(0, 514) - 257, rng.randint(0, 516) - 258]
            length = math.sqrt(sum(c * c for c in v))
            if length:
                v = [int((c << 8) / length) for c in v]
            v = [(c * SHRAPNEL_SPEED) >> 8 for c in v]
            end = self.game_tick * 2 + 60 * (5 - n) + rng.randint(0, 59)
            self.fragments.append(Fragment(frag_mesh, np.array([V[i] for i in used], float) - mean, [int(round(c)) for c in mean], v, end, fig.area))
            first += 10
            n = 1 if n == 5 else n + 1

    def tick_fragments(self):
        """10f8:19ea, per frame: a fragment whose `end` was cleared is deleted; else it moves v * 25 >> 8 (SetPos 10f8:1b0c: on each axis a new
        coordinate not strictly inside its area box keeps the old one and negates that velocity component; z first scales vz by 230 / 256 when it
        is below -0x400, and `_METAL_HITS_<PHYS name>` plays), dies at the next update once the clock passes `end`, spins 15 degrees about X and
        falls (vz -= 240, no cap)."""
        clock = self.game_tick * 2
        for f in list(self.fragments):
            if f.end == 0:
                self.fragments.remove(f)
                continue
            box = self.phys[f.area] if f.area is not None and f.area < len(self.phys) else None
            hit = False
            for k in range(3):
                new = f.pos[k] + ((f.vel[k] * 25) >> 8)
                if box is not None and not (int(box['lo'][k]) < new < int(box['hi'][k])):
                    if k == 2 and f.vel[2] < -0x400:
                        f.vel[2] = (f.vel[2] * 230) >> 8
                    f.vel[k] = -f.vel[k]
                    hit = True
                else:
                    f.pos[k] = new
            if hit:
                idx = self.ambient_id(f'_METAL_HITS_{box["name"]}')      # 10f8:1b0c formats it through 1118:0044
                if idx >= 0:
                    self.play_sound(idx, volume=self.positional_volume(types.SimpleNamespace(pos=np.array(f.pos, float))))      # 1030:04db at the fragment
            if clock > f.end:
                f.end = 0
            f.angle += FRAGMENT_SPIN
            f.vel[2] -= FRAGMENT_GRAVITY

    def fragment_meshes(self, camera):
        """[(mesh, world vertices)] of the shrapnel for compose (drawn like a figure's polygons; the compositor sorts by depth). A fragment with a
        vertex behind the camera is skipped. Shrapnel carries no ANIMATE state (frame 0)."""
        out = []
        for f in self.fragments:
            a = math.radians(f.angle)
            c, s = math.cos(a), math.sin(a)
            V = np.array([[x, y * c - z * s, y * s + z * c] for x, y, z in f.rel], float) + np.asarray(f.pos, float)
            if np.all(project(V, camera)[:, 2] > _w(self).NEAR_DEPTH):
                out.append((f.mesh, V))
        return out

    # ---- THROWCURITEM
    def cmd_throwcuritem(self, proc, args):
        """`THROWCURITEM <pitch degrees> <speed>`: needs CURFIG (error 0x4d) and CURITEM (0x62). The item leaves its holder and keeps its
        current world pose (item_world_pose, rounded to whole units); velocity += row 1 * k of CURFIG's orientation turned about X by the
        pitch, k = trunc((speed << 11) / 100) (as LEAP: row 1 is backward, so a negative speed throws forward)."""
        fig = self.figure(proc.cur_fig)
        if fig is None:
            self.warn('THROWCURITEM: no current figure (error 0x4d)')
            return
        item = self.items.get(proc.cur_item) if proc.cur_item else None
        if item is None:
            self.warn('THROWCURITEM: no current item (error 0x62)')
            return
        nums = [a for v in args for a in (v if isinstance(v, list) else [v]) if isinstance(a, int)]
        nums += [0] * (2 - len(nums))
        pose = self.item_world_pose(item)
        if pose is None:
            return
        item.owner = item.slot = None
        item.pos = np.array([round(c) for c in pose[0]], float)
        item.matrix = np.asarray(pose[1], float)
        self.load_item_physics(item)
        self.add_leap(item, self.orientation(fig), nums[0], nums[1])

    # ---- free items
    def load_item_physics(self, it):
        """The type's HAS_GRAVITY / IS_BOUNCY / IS_REFLECTIVE / ELASTICITY / EXTENT (as spawn_missile), read once; missiles set theirs."""
        if it.physics_loaded or it.missile:
            return
        it.physics_loaded = True
        W = _w(self)
        def prop(name, default):
            vals = self.item_prop(it.type, name)
            return int(vals[0]) if vals else default
        it.bouncy, it.reflective = bool(prop('IS_BOUNCY', 0)), bool(prop('IS_REFLECTIVE', 0))
        it.gravity, it.elasticity = bool(prop('HAS_GRAVITY', 1)), prop('ELASTICITY', 200)
        vals = self.item_prop(it.type, 'EXTENT')
        it.extent = [W.hull_units(int(c)) for c in vals[:3]] if vals and len(vals) >= 3 else [0, 0, 0]

    def move_free_items(self):
        """The item list part of the world update for the items that are not missiles (those move in move_missiles): only free items with
        a non-zero velocity move."""
        for it in [i for i in self.items.values() if not i.missile and i.owner is None and i.pos is not None and any(i.vel)]:
            self.move_free_item(it)

    def move_free_item(self, it):
        """Item::Update + Move (1078:1490, 1078:08f6): gravity (vz -= 102 while vz > -0x500, as figures), step = velocity_step(v), then the
        missile PHYS sub-step mover; flag 0x02 just goes there. A block ends in item_blocked."""
        W = _w(self)
        self.load_item_physics(it)
        if it.gravity and it.vel[2] > W.FALL_VMIN:
            it.vel[2] -= W.FALL_DV
        start = [int(c) for c in it.pos]
        it.step = W.velocity_step(it.vel)
        target = [s + d for s, d in zip(start, it.step)]
        if it.no_collide:
            it.pos = np.array(target, float)
            return
        spans = [2 * e for e in it.extent]
        n = W.move_steps(it.step, min(spans)) if min(spans) > 0 and not all(abs(it.step[k]) < spans[k] for k in range(3)) else 0
        inc = [W.fix_div(it.step[k], n << 8) for k in range(3)] if n > 0 else None
        good = start
        for i in range(1, n + 1):
            cand = [start[k] + inc[k] * i for k in range(3)]
            if self.missile_blocked(it, cand):
                return self.item_blocked(it, start, cand, good)
            good = cand
        if self.missile_blocked(it, target):
            return self.item_blocked(it, start, target, good)
        it.pos = np.array(target, float)

    def item_blocked(self, it, start, p, good, stopped_step=None):
        """A PHYS block at ``p`` (1070:1d8f). The collider is FUN_1070_0f68's (the PHYS of the largest state-1 overlap at P; never a figure).
        IS_BOUNCY, or IS_REFLECTIVE (flag 0x20) with the collider's flag byte (+0x34, record byte 21) & 4: the generic rebound of FUN_1070_0fa7
        on the item's box: six candidates X, Y, Z, XY, XZ, YZ, each P with those axes put back to the move's start; the first free one is
        accepted and those velocity components are negated (none free: the last good position, all three negated); then
        v -= (v * ELASTICITY) >> 8, and `_<TYPE>_BOUNCE` plays when it exists (the generic rebound's own sound). Anything else stops at the
        last good position with zero velocity (a missile's step is ``stopped_step``, scaled by the finished share of the move). Then
        `_<TYPE>_BONK_<material>` plays when it exists (material = the collider's). ASSUMPTION (INFERRED landing): a gravity item
        rebounding upward from a fall with at most one gravity step of speed left comes to rest (velocity zeroed) where the rebound put it."""
        W = _w(self)
        lo, hi = [p[k] - it.extent[k] for k in range(3)], [p[k] + it.extent[k] for k in range(3)]
        best, vol = None, 0
        for phys, state, plo, phi in self._phys_boxes():
            overlap = np.minimum(hi, phi) - np.maximum(lo, plo)
            if state == 1 and np.all(overlap > 0) and W.collision_volume(overlap) > vol:
                best, vol = phys, W.collision_volume(overlap)
        if it.bouncy or (it.reflective and best is not None and len(best['raw']) > 21 and best['raw'][21] & 4):
            step = [p[k] - start[k] for k in range(3)]
            for axes in ((0,), (1,), (2,), (0, 1), (0, 2), (1, 2)):
                t = list(p)
                for a in axes:
                    t[a] = start[a]
                if not self.missile_blocked(it, t):
                    break
            else:
                axes, t = (0, 1, 2), list(good)
            falling = it.vel[2] < 0
            it.pos = np.array(t, float)
            v = list(it.vel)
            for a in axes:
                v[a] = -v[a]
            e = it.elasticity
            it.vel = [c - W.fix_mul(c, e) for c in v]
            it.step = [c - W.fix_mul(c, e) for c in step]
            idx = self.sound_index(f'_{it.type}_BOUNCE')
            if idx is not None:
                self.play_sound(idx, fig=it)
            if it.gravity and not it.missile and falling and 2 in axes and abs(it.vel[2]) <= W.FALL_DV:
                it.vel = [0, 0, 0]
        else:
            it.pos = np.array(good, float)
            it.vel = [0, 0, 0]
            it.step = stopped_step if stopped_step is not None else [good[k] - start[k] for k in range(3)]
        if best is not None:
            material = best['raw'][45:54].split(b'\0')[0].decode('latin1')
            self.hit_sound(f'_{it.type}_BONK_{material}', it)     # FUN_1070_1d8f -> FUN_1100_1ce4
