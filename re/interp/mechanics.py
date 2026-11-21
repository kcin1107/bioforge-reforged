"""Level mechanics: the script statements CHANGEMYFORM (10d0:192c), GRABCRITTER (10d0:38a4), RELEASEFROMLIMB (10d0:663e) and FREEHAND
(10d0:3207). The Swift twin is WorldMechanics.swift.

World mixes `MechanicsMixin` in; world.py calls `cmd_changemyform`, `cmd_grabcritter`, `cmd_releasefromlimb`, `cmd_freehand` and, once
a tick after the figures, `place_limb_held`. All four act on CURFIG; errors are warnings (the statement still returns 0, no change).

CHANGEMYFORM loads a new form into the current figure (FUN_1088_2a87, the CREATEFIGURE loader): mesh, skeleton, skin and motions are
the new BODY/<NAME>.BED's, `fig.type` (+0x1ea, what ISMYFORM compares) the new name. EXTENT, armor, IS_REFLECTIVE, AUTO_TURN_SPEED,
PERSONAL_RADIUS, MATERIAL and the foot offset F are read from `fig.type` on use in the ports, so they follow by themselves; MY_SPEED,
ELASTICITY, gravity and IS_BOUNCY are not re-read by the engine and stay. Position, heading, health, items, AI, velocity and flags stay.

GRABCRITTER attaches another figure to a limb of CURFIG (FUN_1138_05ff; +0x2c holder, +0x30 record with the limb name): like a missile
rider it skips its own move, gravity, grounding and pushes, and each tick it is put at the limb's current animated pose, with the grabbed
figure's own `ON_<LIMB>` property as offset (the hand_pose formula). RELEASEFROMLIMB only clears the link (no SetPos, no velocity or flag
change: the figure stays where it was, gravity takes over next tick). FREEHAND drops (RTHAND, with the put-down animation: the motion
event 0xf3 does the drop) or stows (LTHAND) the item in that hand.

ANIMATE (10d0:077b -> 10f8:0631) sets the mode and period of one animated texture of an object's mesh; the texture then steps by the state
machine of 1168:055e. The ports keep it in `anim[texture]` and the renderers draw each animated texture at that state's frame (frame 0 without ANIMATE: a
record starts at frame 0 with mode 0).
SETREFERENT (10d0:7330) re-aims the process's referent (what kills the process when it is destroyed: item destructor 1078:0690);
INCVIRTUALSECONDS (10d0:6cef) and FORCERELOAD (10d0:31db) are the speed-test and player-death statements.
"""
import os
import sys

import numpy as np

import items as items_mod
import options as options_mod
import salsa
from scene import place

ANIM_WORDS = {'FREEZE': 0, 'INCREMENT': 1, 'DECREMENT': 2, 'RANDOM': 3, 'LOOP': 0, 'YOYO': 4, 'TO_LIMIT': 8, 'RESET': 0x10, 'ONCE': 0x20}
ANIM_DEFAULT_PERIOD = 15        # 10d0:0800: a missing or non-positive number


def _w(world):
    return sys.modules[type(world).__module__]


class MechanicsMixin:
    # ---- CHANGEMYFORM
    def cmd_changemyform(self, proc, args):
        """`CHANGEMYFORM <name>` (10d0:192c -> FUN_1088_2a87). Warnings, nothing changes: no current figure (0x4d), empty word (0x64), no
        BODY/<NAME>.BED (0x20). The figure takes the new form's assets and type name (upper-cased); the old model's decals are gone with
        it (INFERRED: the model, and with it the APPLY and ANIMATE texture state, is deleted), and so is the FLOATATHEIGHT foot override. 2a87 starts no motion on the new model.
        ASSUMPTION for the ports: the current motion is re-mapped by name into the new motion set (frame index kept if valid, else 0),
        else the figure STANDs (quiet). Anything waiting on the old motion is released (the motion id changes)."""
        W = _w(self)
        fig = self.figure(proc.cur_fig)
        if fig is None:
            self.warn('CHANGEMYFORM: no current figure (error 0x4d)')
            return
        name = str(args[0]).upper() if args and isinstance(args[0], str) else ''
        if not name:
            self.warn('CHANGEMYFORM: needs a form name (error 0x64)')
            return
        if not os.path.exists(os.path.join(W.BODY, name + '.BED')):
            self.warn(f'CHANGEMYFORM {name}: no such form (error 0x20)')
            return
        fig.bake_turn()                                 # while the old motion set can still answer `turning`
        old = fig.motion
        fig.assets, fig.type = self.asset(name), name
        fig.decals, fig.anim = {}, {}
        fig.foot_override = None                        # 2a87 copies the new model's F to +0x225
        if old in fig.assets.motions:
            fig.frames = fig.assets.motions[old]
            fig.idx = fig.idx if fig.idx < len(fig.frames) else 0
            fig.mot_id += 1
        else:
            fig.motion = fig.frames = None
            fig.idx = 0
            fig.set_motion(W.STAND, True, quiet=True)

    # ---- GRABCRITTER / RELEASEFROMLIMB
    def cmd_grabcritter(self, proc, args):
        """`GRABCRITTER <object> <limb>` (10d0:38a4). The holder is CURFIG, the grabbed object resolves like 10c0:3e14 (PLAYER = the
        player, else an instance name; ASSUMPTION: figures only in the ports). Warnings: an empty argument (0x123), no current figure
        (0x4d); an unknown object is silent. FUN_1138_05ff: the grabbed figure's holder and limb record are set (`limb_holder`). No wait;
        CURFIG is unchanged."""
        words = [a.upper() if isinstance(a, str) else '' for a in args[:2]]
        words += [''] * (2 - len(words))
        if not all(words):
            self.warn('GRABCRITTER: needs an object and a limb (error 0x123)')
            return
        holder = self.figure(proc.cur_fig)
        if holder is None:
            self.warn('GRABCRITTER: no current figure (error 0x4d)')
            return
        grabbed = self.figure(words[0])
        if grabbed is not None:
            grabbed.limb_holder = (holder.name, words[1])

    def cmd_releasefromlimb(self, proc, args):
        """`RELEASEFROMLIMB <limb>` (10d0:663e). Warnings: empty limb (0x4f), no current figure (0x4d), a limb that CURFIG's skeleton lacks
        (0x126). The first figure held by (CURFIG, limb) (1088:5669) is let go: only the link is cleared. Nothing attached: silent."""
        limb = str(args[0]).upper() if args and isinstance(args[0], str) else ''
        if not limb:
            self.warn('RELEASEFROMLIMB: needs a limb (error 0x4f)')
            return
        holder = self.figure(proc.cur_fig)
        if holder is None:
            self.warn('RELEASEFROMLIMB: no current figure (error 0x4d)')
            return
        if limb not in [l.name.upper() for l in holder.assets.skel]:
            self.warn(f'RELEASEFROMLIMB {limb}: {holder.type} has no such limb (error 0x126)')
            return
        held = next((f for f in self.figures.values() if f.limb_holder == (holder.name, limb)), None)
        if held is not None:
            held.limb_holder = None

    def limb_held_pose(self, holder, held, limb):
        """FUN_1088_5c19 (as items.hand_pose): the world origin of ``held`` attached to ``holder``'s ``limb`` -- the limb's end in its
        current animated pose, plus the held figure's own `ON_<LIMB>` offset in the limb's axes and its LENGTH along the turned row 1
        (a figure type without the property, e.g. LEX: all zero, ASSUMPTION) -- turned by the holder's heading. None if the holder is
        unplaced or has no such limb or motion."""
        if holder.pos is None or holder.frames is None:
            return None
        limbs = [l.name.upper() for l in holder.assets.skel]
        if limb not in limbs:
            return None
        i = limbs.index(limb)
        p, r, l = holder.frames[min(holder.idx, len(holder.frames) - 1)]
        _, R, end = salsa.solve(holder.assets.skel, ((0, 0, p[2]), r, l))
        W = _w(self)
        props = W.figure_props()
        key = 'ON_' + limb
        vals = props.get(held.name.upper(), {}).get(key) or props.get(held.type.upper(), {}).get(key) or []
        if len(vals) == 7 and all(isinstance(v, int) for v in vals):       # FIGURES.scr: `(I,J,K) LENGTH (X,Y,Z)` positional
            a = dict(zip(('I', 'J', 'K', 'LENGTH', 'X', 'Y', 'Z'), vals))
        else:
            a = items_mod.parse_numbers(vals)
        ang = tuple(items_mod.c_div(a.get(k, 0) * 32, 45) for k in 'IJK')
        off = np.array([items_mod.attach_units(a.get(k, 0)) for k in 'XYZ'], float)
        M = salsa.rotate(R[i], ang)
        origin = end[i] + off @ R[i] + M[1] * items_mod.attach_units(a.get('LENGTH', 0))
        return place(origin[None, :], holder.pos, -holder.heading)[0]

    def place_limb_held(self):
        """Every tick after the figure updates (ASSUMPTION: 1088:5c19 is a vtable method whose caller is not decoded): each figure held
        by a limb is placed at the holder's limb pose (place_figure, as a missile rider). A holder that is gone releases it."""
        for fig in self.figures.values():
            if fig.limb_holder is None:
                continue
            holder = self.figures.get(fig.limb_holder[0])
            if holder is None:
                fig.limb_holder = None
                continue
            origin = self.limb_held_pose(holder, fig, fig.limb_holder[1])
            if origin is not None:
                self.place_figure(fig, origin)

    # ---- FREEHAND
    def cmd_freehand(self, proc, args):
        """`FREEHAND <hand>` (10d0:3207). Warnings: no current figure (0x4d), empty hand (0x4f). Nothing held in that hand (1138:040c):
        nothing. `RTHAND` starts the put_down_rthand motion as an engine request (vtable +0x7c; ASSUMPTION: the `<TYPE>_PUT_DOWN_RTHAND`
        script override that the Enter key honours is not consulted) and blocks the process until it ends (1238:0f48, as MOTION); its
        event 0xf3 drops the item and runs `<holder>_<item>_DROP`. A figure without that motion: no wait. Any other word (LTHAND) stows
        the item in the inventory (FUN_1138_1274) at once, no animation."""
        fig = self.figure(proc.cur_fig)
        if fig is None:
            self.warn('FREEHAND: no current figure (error 0x4d)')
            return
        hand = str(args[0]).upper() if args and isinstance(args[0], str) else ''
        if not hand:
            self.warn('FREEHAND: needs a hand (error 0x4f)')
            return
        item = self.held_item(fig, hand)
        if item is None:
            return
        if hand != 'RTHAND':
            self.stow_item(fig, item)
            return
        fig.manual_control = False
        if fig.set_motion('PUT_DOWN_RTHAND', False, engine=True):
            tok = fig.mot_id
            proc.wait_pred = lambda: fig.mot_id != tok or fig.finished

    # ---- ANIMATE
    def cmd_animate(self, proc, args):
        """`ANIMATE <object> <TEXTURE> [words] [number]` (10d0:077b -> 10f8:0631 / 0256). The object is CURFIG, CURITEM or a figure /
        item name (ASSUMPTION for names: the engine acts on CURFIG's or CURITEM's model only); the texture name is upper-cased and cut to
        8 characters. Only an animated (TXMA) texture of the object's mesh reacts: a static or unknown one, or no object, is silent. The
        words OR their values into the mode (ANIM_WORDS, case-insensitive; ON / OFF and others are ignored); the number (the first
        integer; <= 0 or none -> 15) is the period of a frame in 60 Hz clock units. 1168:04f4: the mode is overwritten, and exactly 0x10
        (RESET) also shows frame 0; 1168:04ac: next = clock + period. ASSUMPTION: clock = 2 x VM tick."""
        if len(args) < 2 or not isinstance(args[1], str):
            return
        obj = self.script_object(proc, args[0])
        if obj is None:
            return
        mesh = obj.assets.mesh if hasattr(obj, 'carrier') else items_mod.item_mesh(obj.type)
        name = args[1].upper()[:8]
        n = 0 if mesh is None else next((len(f) for i, f in mesh.anim.items() if mesh.textures[i][0].upper() == name), 0)
        if n == 0:
            return
        mode = 0
        for a in args[2:]:
            if isinstance(a, str):
                mode |= ANIM_WORDS.get(a.upper(), 0)
        period = next((a for a in args[2:] if isinstance(a, int)), 0)
        period = period if period > 0 else ANIM_DEFAULT_PERIOD
        st = obj.anim.setdefault(name, {'frame': 0, 'mode': 0, 'period': 0, 'next': 0, 'n': n})
        if mode == 0x10:
            st['frame'] = 0
        st.update(mode=mode, period=period, next=self.clock() + period)

    def clock(self):
        """ASSUMPTION: the 60 Hz clock [8330] is 2 x the game clock in VM ticks (`game_tick`: FREEZE stops it)."""
        return 2 * self.game_tick

    @staticmethod
    def advance_texture(st, clock, rand):
        """1168:055e for one texture state {frame, mode, period, next, n}; ``rand(a, b)`` is the inclusive random draw."""
        n, mode = st['n'], st['mode']
        if n <= 0 or mode == 0 or clock < st['next']:
            return
        f = st['frame']
        if mode & 3 == 1:
            f += 1
        elif mode & 3 == 2:
            f -= 1
        elif mode & 3 == 3:
            f = rand(0, n - 1)
        kind = mode & 0x1c
        if kind == 0:
            f = 0 if f >= n else n - 1 if f < 0 else f
        elif kind == 4:
            if f >= n - 1:
                f, mode = n - 1, (mode & ~3) | 2
            if f < 1:
                f, mode = 0, (mode & ~3) | 1
        elif kind == 8:
            f = max(0, min(n - 1, f))
        st['frame'] = f
        st['mode'] = 0 if mode & 0x20 else mode
        st['next'] = clock + st['period']              # no catch-up: one step per update at most

    def step_textures(self):
        """Once per world step, for every figure and item with ANIMATE state. ASSUMPTION: the engine steps an object when it is drawn
        (1188:1d54); the ports step it every tick, visible or not. RANDOM draws from the shared RNG (`World.rng`, as RANDOM)."""
        clock = self.clock()
        for obj in list(self.figures.values()) + list(self.items.values()):
            for st in obj.anim.values():
                self.advance_texture(st, clock, self.rng.randint)

    # ---- SETREFERENT
    def process_referent(self, proc):
        """10c0:535-556: at spawn the referent is CURFIG if one is given, else CURITEM."""
        return self.figures.get(proc.cur_fig) if proc.cur_fig else self.items.get(proc.cur_item) if proc.cur_item else None

    def cmd_setreferent(self, proc, args):
        """`SETREFERENT <object>` (10d0:7330): the process's referent becomes CURFIG / CURITEM / PLAYER / a figure or item (an unresolved
        object: nothing). The error 0x70 case (a process that is its referent's own owned process, +0xea1 / 10c0:25f7) has no notion in
        the ports and is not modelled."""
        obj = self.script_object(proc, args[0]) if args else None
        if obj is not None:
            proc.referent = obj

    def kill_item_referents(self, item, caller=None):
        """Item destructor 1078:0690: every script process whose referent is the item dies (vtable +0xc: dropped without resuming its
        waiters; the running ``caller`` ends after its statement, as LOADLEVEL does). Figures (1070:05a1) are NOT PORTED."""
        if item is None or self.vm is None:
            return
        for h, q in list(self.vm.procs.items()):
            if q.referent is item:
                if q is caller:
                    q.ended = True
                else:
                    q.done, q.waiters = True, []
                    del self.vm.procs[h]

    # ---- INCVIRTUALSECONDS / FORCERELOAD
    def cmd_incvirtualseconds(self, args):
        """`INCVIRTUALSECONDS <n>` (10d0:6cef). n != 0: the script global `_TimeTest` is loaded from the persisted option of that name
        (ASSUMPTION: 0, the settings have no generic key lookup and INSTALL.OPT has no such key). n == 0: `speed_factor` ([66c6]) + 1,
        capped at 20; the timer rate and the persisted keys are NOT PORTED (nothing reads them)."""
        n = args[0] if args and isinstance(args[0], int) else 0
        if n:
            if self.vm is not None:
                self.vm.globals['_timetest'] = 0
        else:
            self.speed_factor = min(self.speed_factor + 1, 20)

    def cmd_forcereload(self, proc):
        """`FORCERELOAD` (10d0:31db): the player's hit points (object local ~0, ASSUMPTION for +0x92) := -1, then the options dialog
        opens with _OPTS_MUST_RELOAD (FUN_10a8_02cc(2)); the process yields (returns 1)."""
        player = self.player()
        if player is not None and self.vm is not None:
            self.vm.objects[self.object_key(player.name)][0] = -1
        self.open_options(options_mod.MUST_RELOAD)
        proc.wait_pred = lambda: True
