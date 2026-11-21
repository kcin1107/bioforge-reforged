"""Tests for mechanics.py: CHANGEMYFORM, GRABCRITTER / RELEASEFROMLIMB and FREEHAND, driven by the shipped BEACH / ITEMS scripts. The
Swift twin is MechanicsTests.swift (same cases, same numbers).  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_mechanics.py'"""
import os
import sys
import tempfile
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import items as items_mod  # noqa: E402
import mechanics  # noqa: E402
import monitor as monitor_mod  # noqa: E402
import options as options_mod  # noqa: E402
import scenarios  # noqa: E402
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
import salsa  # noqa: E402
from scene import place  # noqa: E402

SCRIPT = '''
{ MECHFORM
	SETCURRENTFIGURE PLAYER
	IF (ISMYFORM LEX) OR (ISMYFORM LEXMIR) THEN
		{
		CHANGEMYFORM HARD
		}
	ELSE
		{
		CHANGEMYFORM LEX
		}
	CALL LEX_WOUNDS
	_form_done = 1
}
{ REFSHOT
	< HAS_GRAVITY = 0 >
	< IS_BOUNCY = 0 >
	< ELASTICITY = 0 >
	< IS_REFLECTIVE = 0 >
	< EXTENT = ( 20, 20, 20 ) >
}
{ REFSHOT_HIT_WALL
	_ref_state = 1
	WAIT 30
	_ref_state = 2
}
{ REFSHOT2
	< HAS_GRAVITY = 0 >
	< IS_BOUNCY = 0 >
	< ELASTICITY = 0 >
	< IS_REFLECTIVE = 0 >
	< EXTENT = ( 20, 20, 20 ) >
}
{ REFSHOT2_HIT_WALL
	_ref_state = 1
	SETCURRENTFIGURE PLAYER
	SETREFERENT CURFIG
	WAIT 30
	_ref_state = 2
}
{ FREEHANDS
	SETCURRENTFIGURE PLAYER
	IF ISCARRYINGANYTHING LTHAND THEN
		FREEHAND LTHAND
	IF ISCARRYINGANYTHING RTHAND THEN
		FREEHAND RTHAND
	_fh_done = 1
}
'''


def beach():
    """BEACH with Lex (player) at ZIP1_A and the test blocks loaded."""
    w = worldmod.World('BEACH')
    vm = vmmod.VM(w)
    vmmod.load_level(vm, 'BEACH')
    test_items.script(vm, SCRIPT)
    w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], test_items.stub())
    lex = w.player()
    lex.pos = np.array(w.script_point(None, 'ZIP1_A'), float)
    w.settle(lex)
    return w, vm, lex


def ismyform(w, name, fig='PLAYER'):
    return w.call('func', 'ISMYFORM', [name], test_items.stub(fig))


class ChangeMyForm(unittest.TestCase):
    def state(self, w, lex):
        lo, hi = w.hull(lex)
        return (lex.type, [int(c) for c in lex.pos[:2]], lex.heading, len(lex.assets.mesh.verts), lo, hi, lex.speed)

    def test_the_form_block_swaps_lex_and_hard_and_back(self):
        w, vm, lex = beach()
        lex.heading = 40.0
        before = self.state(w, lex)
        self.assertEqual(before, ('LEX', [-1177873, -1002528], 40.0, 159, (-1178241, -1002896, -17356), (-1177505, -1002160, -13876), 384))
        w.spawn_for(lex, 'MECHFORM')
        scenarios.tick(w, vm, 3)
        self.assertEqual(vm.globals['_form_done'], 1)
        self.assertEqual(self.state(w, lex), ('HARD', [-1177873, -1002528], 40.0, 132, (-1178241, -1002896, -17372), (-1177505, -1002160, -13830), 384))
        self.assertEqual((ismyform(w, 'HARD'), ismyform(w, 'LEX'), lex.motion, lex.assets.foot_offset), (1, 0, 'STAND', 2317))
        self.assertEqual(float(lex.pos[2]), -15018.0)                     # regrounded: support + the new foot offset (2317, was 2312)
        vm.globals['_form_done'] = 0
        w.spawn_for(lex, 'MECHFORM')
        scenarios.tick(w, vm, 3)
        self.assertEqual(self.state(w, lex), before)
        self.assertEqual((ismyform(w, 'HARD'), ismyform(w, 'LEX'), float(lex.pos[2])), (0, 1, -15023.0))

    def test_a_changed_form_reads_its_armour_by_the_form_name(self):
        """FUN_1088_2a87 re-reads the armour by the form name: Lex's instance block (IMPACT_ARMOR 0) must not shadow HARD's (5)."""
        w, vm, lex = beach()
        hp = vm.objects['LEX']
        hp[0] = 100
        w.damage(lex, None, 24, 0, 6, False)
        taken = 100 - hp[0]
        w.spawn_for(lex, 'MECHFORM')
        scenarios.tick(w, vm, 3)
        hp[0] = 100
        w.damage(lex, None, 24, 0, 6, False)
        self.assertEqual(taken - (100 - hp[0]), 5)
        self.assertEqual(worldmod.form_prop(lex, 'IMPACT_ARMOR', 0), 5)

    def test_the_hardsuit_machine_script_changes_the_form(self):
        w, vm, lex = beach()
        w.spawn_for(lex, 'HARDSUITMACHINE')
        ticks = 0
        while lex.type == 'LEX' and ticks < 400:
            scenarios.tick(w, vm, 1)
            ticks += 1
        self.assertEqual((ticks, lex.type, w.level, ismyform(w, 'HARD'), vm.globals['_digsite']), (106, 'HARD', 'DIGSITE', 1, 3))

    def test_the_motion_is_remapped_by_name_else_lex_stands(self):
        w, vm, lex = beach()
        lex.set_motion('WALK', True)
        lex.idx = 5
        w.call('stmt', 'CHANGEMYFORM', ['HARD'], test_items.stub())
        self.assertEqual((lex.motion, lex.idx, lex.frames is lex.assets.motions['WALK']), ('WALK', 5, True))
        only_lex = next(m for m in worldmod.Assets('LEX').motions if m not in worldmod.Assets('HARD').motions)
        w.call('stmt', 'CHANGEMYFORM', ['LEX'], test_items.stub())
        lex.set_motion(only_lex, True)
        w.call('stmt', 'CHANGEMYFORM', ['HARD'], test_items.stub())
        self.assertEqual((lex.motion, lex.idx), ('STAND', 0))

    def test_decals_go_with_the_old_model(self):
        w, vm, lex = beach()
        lex.decals['X'] = ('ON', 1, 'LEX')
        w.call('stmt', 'CHANGEMYFORM', ['HARD'], test_items.stub())
        self.assertEqual(lex.decals, {})

    def test_errors_change_nothing(self):
        w, vm, lex = beach()
        for fig, args in (('NOBODY', ['HARD']), ('PLAYER', []), ('PLAYER', ['NOSUCHFORM'])):
            w.call('stmt', 'CHANGEMYFORM', args, test_items.stub(fig))
            self.assertEqual((lex.type, len(lex.assets.mesh.verts)), ('LEX', 159))
        self.assertEqual([m for m in w.warnings if 'CHANGEMYFORM' in m],
                         ['CHANGEMYFORM: no current figure (error 0x4d)', 'CHANGEMYFORM: needs a form name (error 0x64)',
                          'CHANGEMYFORM NOSUCHFORM: no such form (error 0x20)'])


def limb_point(beast, limb):
    """The world position of a limb end of ``beast`` in its current pose."""
    names = [l.name.upper() for l in beast.assets.skel]
    p, r, l = beast.frames[min(beast.idx, len(beast.frames) - 1)]
    _, _, end = salsa.solve(beast.assets.skel, ((0, 0, p[2]), r, l))
    return place(np.asarray(end[names.index(limb)], float)[None, :], beast.pos, -beast.heading)[0]


class Grab(unittest.TestCase):
    def setup_beast(self):
        w, vm, lex = beach()
        beast = w.figure('ACIDD')
        vm.globals['_FluffyRisen'] = 1
        w.spawn_for(beast, 'READY_ACID')
        scenarios.tick(w, vm, 199)
        w.script_auto = False
        w.set_camera('BCHK', 'test')                     # a viewing camera: on BCH9 the hide pass has stopped him (1130:050d), and HIT_LEX wants him in STAND
        scenarios.tick(w, vm, 1)
        return w, vm, lex, beast

    def test_hit_lex_carries_lex_on_the_swallow_finger_and_lets_go(self):
        """AI_BEAST HIT_LEX (the shipped script): GRAB, GRABCRITTER PLAYER RFINGER1, SWALLOW, WAIT 3 SECONDS, RELEASEFROMLIMB, then
        GO 6666 6666 6666. Lex hovers (gravity off) at the spot the CLAW reaches in the GRAB motion, so the 2DDISTFROMITEM poll passes."""
        w, vm, lex, beast = self.setup_beast()
        lex.gravity = False
        lex.pos = np.array([-1104211.0, -1069482.0, -17274.0])
        w.spawn_for(beast, 'HIT_LEX')
        seen, held = {}, []
        for t in range(1, 112):
            scenarios.tick(w, vm, 1)
            if lex.limb_holder is not None:
                held.append(t)
                self.assertEqual(lex.limb_holder, ('ACIDD', 'RFINGER1'))
                self.assertEqual(np.round(lex.pos).tolist(), np.round(limb_point(beast, 'RFINGER1')).tolist())
                self.assertTrue(lex.no_collide)
            seen[t] = (beast.motion, beast.idx, [int(round(c)) for c in lex.pos])
        # the x/y values below follow the beast's heading: `TURN ANGLEFROMENEMY ()` (AI_BEAST.scr:151) now turns it to face Lex (-90), 10a0:19e6
        self.assertEqual((held[0], held[-1]), (17, 106))
        self.assertEqual(seen[16], ('GRAB', 2, [-1104211, -1069482, -17274]))
        self.assertEqual(seen[17], ('SWALLOW', 0, [-1110263, -1066104, -17086]))
        self.assertEqual(seen[28], ('SWALLOW', 1, [-1112287, -1065642, -16810]))
        self.assertEqual(seen[48], ('SWALLOW', 4, [-1108527, -1066904, -15089]))
        self.assertEqual(seen[68], ('SWALLOW', 7, [-1107832, -1065645, -2668]))      # he rises with the finger
        self.assertEqual(seen[106], ('SWALLOW', 12, [-1108633, -1065428, -1264]))
        self.assertIsNone(lex.limb_holder)
        self.assertEqual(seen[107][2], [1706496, 1706496, 1706496 + 40])                                # released, then GO 6666 6666 6666 parks him (x, y, z << 8)
        self.assertEqual(w.warnings, [])

    def test_grab_and_release_by_statements(self):
        w, vm, lex, beast = self.setup_beast()
        stub = test_items.stub('ACIDD')
        w.call('stmt', 'GRABCRITTER', ['PLAYER', 'RFINGER1'], stub)
        self.assertEqual(lex.limb_holder, ('ACIDD', 'RFINGER1'))
        self.assertEqual(stub.cur_fig, 'ACIDD')
        w.call('stmt', 'RELEASEFROMLIMB', ['RFINGER2'], stub)               # another limb: nothing attached there, silent
        self.assertEqual(lex.limb_holder, ('ACIDD', 'RFINGER1'))
        w.call('stmt', 'RELEASEFROMLIMB', ['RFINGER1'], stub)
        self.assertIsNone(lex.limb_holder)
        self.assertEqual(w.warnings, [])

    def test_errors(self):
        w, vm, lex, beast = self.setup_beast()
        w.warnings.clear()
        w.call('stmt', 'GRABCRITTER', ['PLAYER'], test_items.stub('ACIDD'))
        w.call('stmt', 'GRABCRITTER', ['PLAYER', 'RFINGER1'], test_items.stub('NOBODY'))
        w.call('stmt', 'GRABCRITTER', ['NOBODY', 'RFINGER1'], test_items.stub('ACIDD'))          # unknown object: silent
        w.call('stmt', 'RELEASEFROMLIMB', [], test_items.stub('ACIDD'))
        w.call('stmt', 'RELEASEFROMLIMB', ['RFINGER1'], test_items.stub('NOBODY'))
        w.call('stmt', 'RELEASEFROMLIMB', ['NOSUCHLIMB'], test_items.stub('ACIDD'))
        self.assertIsNone(lex.limb_holder)
        self.assertEqual(w.warnings, ['GRABCRITTER: needs an object and a limb (error 0x123)', 'GRABCRITTER: no current figure (error 0x4d)',
                                      'RELEASEFROMLIMB: needs a limb (error 0x4f)', 'RELEASEFROMLIMB: no current figure (error 0x4d)',
                                      'RELEASEFROMLIMB NOSUCHLIMB: ACIDD has no such limb (error 0x126)'])


class FreeHand(unittest.TestCase):
    def hands(self):
        w, vm, lex = test_items.make()
        test_items.script(vm, SCRIPT)
        w.place_item(lex, w.items['FORK'], 'LTHAND')
        w.place_item(lex, w.items['BLASTER'], 'RTHAND')
        return w, vm, lex

    def test_lthand_is_stowed_at_once_rthand_is_put_down_with_the_animation(self):
        w, vm, lex = self.hands()
        fork, blaster = w.items['FORK'], w.items['BLASTER']
        w.spawn_for(lex, 'FREEHANDS')
        test_items.run(w, vm, 1)
        self.assertEqual((fork.owner, fork.slot, fork.pos), ('LEX', 'INVENTORY', None))
        self.assertEqual((lex.motion, blaster.slot, vm.globals.get('_fh_done')), ('PUT_DOWN_RTHAND', 'RTHAND', None))
        dropped = test_items.steps_until(w, vm, lambda: blaster.owner is None)
        self.assertEqual((dropped, lex.motion, lex.idx, vm.globals.get('_fh_done')), (22, 'PUT_DOWN_RTHAND', 15, None))
        done = test_items.steps_until(w, vm, lambda: vm.globals.get('_fh_done') == 1)
        self.assertEqual((done, blaster.owner), (22, None))             # the drop came a frame earlier, the motion's end did not

    def test_flute_use_drops_the_flute_before_playing(self):
        w, vm, lex = test_items.make()
        flute = worldmod.Item('FLUTE', 'FLUTE')
        w.items['FLUTE'] = flute
        w.place_item(lex, flute, 'RTHAND')
        w.spawn_for(lex, 'FLUTE_USE', flute)
        n = test_items.steps_until(w, vm, lambda: lex.motion == 'START_FLUTE')
        self.assertEqual((n, flute.owner), (45, None))

    def test_errors_and_empty_hands(self):
        w, vm, lex = self.hands()
        w.call('stmt', 'FREEHAND', [], test_items.stub())
        w.call('stmt', 'FREEHAND', ['RTHAND'], test_items.stub('NOBODY'))
        self.assertEqual(w.warnings, ['FREEHAND: needs a hand (error 0x4f)', 'FREEHAND: no current figure (error 0x4d)'])
        w.items['BLASTER'].slot = 'LTHAND'
        w.call('stmt', 'FREEHAND', ['RTHAND'], test_items.stub())            # nothing in the right hand
        self.assertEqual(lex.motion, 'STAND')


def advance(mode, n, steps, frame=0, period=1):
    """The texture state machine alone: frame per clock tick 0..steps-1 (a RANDOM draw is always the top frame) and the final mode."""
    st = dict(frame=frame, mode=mode, period=period, next=0, n=n)
    out = []
    for clock in range(steps):
        mechanics.MechanicsMixin.advance_texture(st, clock, lambda a, b: b)
        out.append(st['frame'])
    return out, st['mode']


class Animate(unittest.TestCase):
    def test_the_state_machine(self):
        self.assertEqual(advance(5, 6, 14), ([1, 2, 3, 4, 5, 4, 3, 2, 1, 0, 1, 2, 3, 4], 5))     # INCREMENT YOYO: the end frames show once
        self.assertEqual(advance(2, 4, 6), ([3, 2, 1, 0, 3, 2], 2))                               # DECREMENT wraps
        self.assertEqual(advance(2 | 8, 4, 6, frame=1), ([0, 0, 0, 0, 0, 0], 10))                 # TO_LIMIT clamps
        self.assertEqual(advance(1 | 0x20, 4, 4), ([1, 1, 1, 1], 0))                              # ONCE: one step, then the mode is cleared
        self.assertEqual(advance(3, 5, 2), ([4, 4], 3))                                           # RANDOM draws rand(0, n - 1)
        self.assertEqual(advance(0x10, 4, 3), ([0, 0, 0], 16))                                    # RESET alone: no step
        self.assertEqual(advance(0, 4, 3), ([0, 0, 0], 0))                                        # FREEZE
        self.assertEqual(advance(1, 4, 3, period=2)[0], [1, 1, 2])                                # next = clock + period, no catch-up

    def test_the_beast_acid_texture_from_ready_acid(self):
        """AI_BEAST READY_ACID: ANIMATE CURFIG ACID0 ON INCREMENT YOYO 5 (6 frames); the frame per tick after the 200 ticks of setup."""
        w, vm, lex, beast = Grab().setup_beast()
        self.assertEqual(beast.anim['ACID0'], {'frame': 3, 'mode': 5, 'period': 5, 'next': 403, 'n': 6})
        frames = []
        for _ in range(30):
            scenarios.tick(w, vm, 1)
            frames.append(beast.anim['ACID0']['frame'])
        self.assertEqual(frames, [3, 4, 4, 4, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3])

    def test_the_drawn_frame_is_the_animate_state(self):
        """An item's animated texture draws frame 0 at any tick until ANIMATE, then the state's frame (shade_mesh with the object's anim)."""
        w, vm, lex = beach()
        item = worldmod.Item('PFDBLST', 'PFDBLST')
        w.items['PFDBLST'] = item
        mesh = items_mod.item_mesh('PFDBLST')
        ti, frames = next((i, f) for i, f in mesh.anim.items() if mesh.textures[i][0].upper() == 'PDFFR0')
        V = np.zeros((len(mesh.verts), 3))
        eye = np.array([0.0, -1000.0, 0.0])
        for _ in range(4):
            scenarios.tick(w, vm, 3)
            self.assertIs(worldmod.shade_mesh(mesh, V, eye, item.anim).textures[ti][3], frames[0])
        stub = test_items.stub()
        stub.cur_item = 'PFDBLST'
        w.call('stmt', 'ANIMATE', ['CURITEM', 'PDFFR0', 'ON', 'INCREMENT', 4], stub)
        seen = set()
        for _ in range(12):
            scenarios.tick(w, vm, 1)
            f = item.anim['PDFFR0']['frame']
            self.assertIs(worldmod.shade_mesh(mesh, V, eye, item.anim).textures[ti][3], frames[f])
            seen.add(f)
        self.assertGreater(len(seen), 3)

    def test_the_item_and_lex_textures_from_ai_lex(self):
        w, vm, lex = beach()
        item = worldmod.Item('PFDBLST', 'PFDBLST')
        w.items['PFDBLST'] = item
        stub = test_items.stub()
        stub.cur_item = 'PFDBLST'
        w.call('stmt', 'ANIMATE', ['CURITEM', 'PDFFR0', 'ON', 'RESET', 0], stub)
        self.assertEqual(item.anim['PDFFR0'], {'frame': 0, 'mode': 16, 'period': 15, 'next': 15, 'n': 8})
        w.call('stmt', 'ANIMATE', ['CURITEM', 'PDFFR0', 'ON', 'INCREMENT', 4], stub)
        self.assertEqual(item.anim['PDFFR0'], {'frame': 0, 'mode': 1, 'period': 4, 'next': 4, 'n': 8})
        frames = []
        for _ in range(24):
            scenarios.tick(w, vm, 1)
            frames.append(item.anim['PDFFR0']['frame'])
        self.assertEqual(frames, [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 0, 0, 1, 1, 2, 2, 3, 3, 4])
        w.call('stmt', 'ANIMATE', ['CURFIG', 'LEXPIM', 'ON', 'INCREMENT', 60], stub)
        frames = []
        for _ in range(70):
            scenarios.tick(w, vm, 1)
            frames.append(lex.anim['LEXPIM']['frame'])
        self.assertEqual(frames[::5], [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0])
        w.call('stmt', 'ANIMATE', ['CURFIG', 'LEXPIM', 'OFF'], stub)
        self.assertEqual(lex.anim['LEXPIM'], {'frame': 0, 'mode': 0, 'period': 15, 'next': 203, 'n': 2})
        scenarios.tick(w, vm, 70)
        self.assertEqual(lex.anim['LEXPIM']['frame'], 0)                  # OFF froze it

    def test_unknown_static_and_missing_objects_are_silent(self):
        w, vm, lex = beach()
        stub = test_items.stub()
        for args in (['CURFIG', 'MDTB3', 'ON', 'INCREMENT'], ['CURFIG', 'NOSUCH', 'ON', 'INCREMENT'], ['NOBODY', 'LEXPIM', 'ON', 'INCREMENT'],
                     ['CURFIG'], ['CURITEM', 'LEXPIM', 'ON', 'INCREMENT']):
            w.call('stmt', 'ANIMATE', args, stub)
        self.assertEqual((lex.anim, w.warnings), ({}, []))
        w.call('stmt', 'ANIMATE', ['CURFIG', 'lexpimxx', 'INCREMENT'], stub)                 # 8 characters at most: LEXPIMXX is no texture
        w.call('stmt', 'ANIMATE', ['CURFIG', 'lexpim', 'RANDOM', 'ONCE', -5], stub)           # a number <= 0 means 15
        self.assertEqual(lex.anim['LEXPIM'], {'frame': 0, 'mode': 0x23, 'period': 15, 'next': 15, 'n': 2})

    def test_nursebot_load_sets_the_nurse_textures_and_changemyform_clears_them(self):
        w, vm, lex = test_items.make()
        w.call('stmt', 'CREATEFIGURE', ['NURSEBOT', 'NURSE_X'], test_items.stub())
        nurse = w.figures['NURSE_X']
        self.assertTrue(w.spawn_for(nurse, 'NURSEBOT_LOAD'))
        self.assertEqual({k: (v['n'], v['mode'], v['period']) for k, v in nurse.anim.items()},
                         {'SLEAKSD': (3, 1, 15), 'SLEAKBA': (3, 1, 15), 'SLEAKEY': (4, 1, 15), 'SLEAKNE': (4, 1, 15)})
        w.call('stmt', 'CHANGEMYFORM', ['LEX'], test_items.stub('NURSE_X'))
        self.assertEqual(nurse.anim, {})


class Referent(unittest.TestCase):
    def shoot(self, mtype):
        w, vm, lex = beach()
        x, y, z = (c >> 8 for c in w.script_point(None, 'ZIP1_B'))          # away from Lex, whose hull a shot would hit
        w.call('func', 'FIRE', [mtype, 'ZIP1_B', 'AT', x + 2, y, z, 5, 0, 0, 0], test_items.stub())
        return w, vm, lex

    def test_a_hit_process_dies_with_its_missile(self):
        w, vm, lex = self.shoot('REFSHOT')
        scenarios.tick(w, vm, 6)
        self.assertEqual(vm.globals['_ref_state'], 1)
        self.assertFalse(any(i.missile for i in w.items.values()))
        scenarios.tick(w, vm, 40)
        self.assertEqual(vm.globals['_ref_state'], 1)                    # killed in its WAIT: it never reaches state 2

    def test_setreferent_player_keeps_it_alive(self):
        w, vm, lex = self.shoot('REFSHOT2')
        scenarios.tick(w, vm, 6)
        self.assertEqual(vm.globals['_ref_state'], 1)
        proc = next(p for p in vm.procs.values() if p.block.name == 'REFSHOT2_HIT_WALL')
        self.assertIs(proc.referent, lex)
        scenarios.tick(w, vm, 40)
        self.assertEqual(vm.globals['_ref_state'], 2)

    def test_killcuritem_and_unresolved_objects(self):
        w, vm, lex = beach()
        item = worldmod.Item('PFDBLST', 'PFDBLST')
        w.items['PFDBLST'] = item
        proc = vm.spawn('REFSHOT_HIT_WALL', ctx=types.SimpleNamespace(cur_fig=None, cur_item='PFDBLST', owner='level'))
        self.assertIs(proc.referent, item)
        stub = test_items.stub()
        w.call('stmt', 'SETREFERENT', ['NOBODY'], stub)
        self.assertIsNone(stub.__dict__.get('referent'))
        w.call('stmt', 'SETREFERENT', ['PLAYER'], proc)
        self.assertIs(proc.referent, lex)
        proc.referent = item
        proc.cur_item = 'PFDBLST'
        w.call('stmt', 'KILLCURITEM', [], proc)
        self.assertTrue(proc.ended and 'PFDBLST' not in w.items)


class Small(unittest.TestCase):
    def test_determinemachinespeed_finishes_and_leaves_timetest_zero(self):
        w, vm, lex = test_items.make()
        vm.globals['_timetest'] = 7
        vm.spawn('DETERMINEMACHINESPEED')
        ticks = 0
        while any(p.block.name == 'DETERMINEMACHINESPEED' for p in vm.procs.values()) and ticks < 200:
            scenarios.tick(w, vm, 1)
            ticks += 1
        self.assertEqual((ticks, vm.globals['_timetest'], w.speed_factor), (41, 0, 0))
        for want in (1, 2, 3):
            w.call('stmt', 'INCVIRTUALSECONDS', [0], test_items.stub())
            self.assertEqual(w.speed_factor, want)
        w.speed_factor = 20
        w.call('stmt', 'INCVIRTUALSECONDS', [0], test_items.stub())
        self.assertEqual(w.speed_factor, 20)

    def test_forcereload_kills_the_player_and_opens_the_reload_dialog(self):
        w, vm, lex = test_items.make()
        stub = test_items.stub()
        w.call('stmt', 'FORCERELOAD', [], stub)
        self.assertEqual((w.hit_points(lex), w.paused, w.options.flags & options_mod.MUST_RELOAD, stub.wait_pred()), (-1, True, options_mod.MUST_RELOAD, True))

    def test_falling_into_the_tanks_drowns_lex(self):
        """CRYTOTNK FALL turns Lex's collisions off and loads TANKS at LEX_FALL. Live (re/out/tank_fall_live) he is not stood on the
        walkway there: he falls on, FALL's COORDZ test passes, and TANKDETH's GO DROWN places him with no velocity to drown. The
        ports stood him on the walkway and FALL never ended."""
        w, vm, lex = test_items.make(lex=(-12355.0, -74517.0), heading=87.0)
        vm.spawn('FALL', ctx=types.SimpleNamespace(cur_fig=w.player_name, cur_item=None, owner='level'))
        test_items.run(w, vm, 60)
        lex = w.player()
        self.assertEqual(w.level, 'TANKS')
        self.assertEqual(([int(c) for c in lex.pos], lex.motion.upper(), lex.vz), ([-17408, -57344, -38741], 'DROWN', 0))

    def test_a_failed_load_after_a_death_reopens_the_reload_dialog(self):
        w, vm, lex = test_items.make()
        with tempfile.TemporaryDirectory() as d:
            w.saves_dir = d
            w.forcing_reload = True                              # KILLLEX's _forcing_reload
            w.call('stmt', 'FORCERELOAD', [], test_items.stub())
            w.options.activate('LOAD')
            w.options.activate('OK')
            self.assertEqual(w.record_option_action(w.options.activate('YES')), 'load:1')
            self.assertIsNone(w.pending_load)
            self.assertFalse(w.options.closed)
            self.assertEqual((w.options.flags & options_mod.MUST_RELOAD, w.options.screen), (options_mod.MUST_RELOAD, 'main'))

    def test_reload_dialog_sits_on_the_shown_picture_in_greys(self):
        """KILLLEX: CAMERA SHOW STITLE, then FORCERELOAD. As in a VGA dump of the original, the dialog shows STITLE dimmed onto 128..145
        and the buttons blend with it (CRDX's fill 41 -> 44 at (290, 170)); RETX is disabled (frame 5) and RETURN does nothing.
        Twin of MechanicsTests.reloadDialogSitsOnTheShownPictureInGreys."""
        w, vm, lex = test_items.make()
        stub = test_items.stub()
        w.call('stmt', 'CAMERA', ['SHOW', 'STITLE'], stub)
        w.call('stmt', 'FORCERELOAD', [], stub)
        px, _ = w.options.render(w.shown_picture_rgb())
        self.assertEqual((px[60 * 320 + 160], px[100 * 320 + 60], px[170 * 320 + 290], sum(px)), (131, 141, 44, 7259828))
        self.assertTrue(all(128 <= c <= 145 for c in px[60 * 320 + 40:60 * 320 + 280]))
        self.assertEqual((w.options.monitor.elements['RETX'].frame, w.options.activate('RETURN'), w.options.closed), (5, None, False))
        w.set_camera('BLK6', 'test')                                         # a real switch drops the picture
        self.assertIsNone(w.shown_picture_rgb())

    def test_o_reopens_after_escape_and_the_dialog_sits_on_the_dimmed_room(self):
        """The key that opens the dialog gets no key_up (the dialog takes the keyboard; the app's Escape sends O without one): O, Escape, O
        must open it again. Live (O in CE31) the dialog shows the room dimmed. Twin of MechanicsTests.oReopensAfterEscape..."""
        w, vm, lex = test_items.make()
        w.key_down(0x18)
        w.option_key('ESCAPE')
        self.assertTrue(w.options.closed)
        w.key_down(0x18)
        self.assertFalse(w.options.closed)
        px = w.options.render(w.options_underlay())[0]
        self.assertEqual((px[60 * 320 + 160], px[100 * 320 + 60], sum(px)), (137, 135, 7529057))
        self.assertTrue(all(128 <= c <= 145 for c in px[60 * 320 + 40:60 * 320 + 280]))

    def test_translucent_table(self):
        """FUN_1270_174b's table, as the VGA dump shows it: fill 41 (offset 9) over grey 145 (offset 17) -> 32 + 21 = 53."""
        self.assertEqual((monitor_mod.TRANSLUCENT[9][17], monitor_mod.TRANSLUCENT[0][0], monitor_mod.TRANSLUCENT[4][31], monitor_mod.TRANSLUCENT[31][5]),
                         (21, 0, 31, 31))


class NumericGo(unittest.TestCase):
    def test_numeric_coordinates_snap_walk_and_park(self):
        w, vm, lex = test_items.make()
        stub = test_items.stub()
        w.call('stmt', 'GO', [-57, -292, -21], stub)                       # CHAOSCRY: gravity on, snapped onto the floor
        self.assertEqual(lex.pos.tolist(), [-14592.0, -74752.0, -5093.0])
        w.call('stmt', 'GO', [113, -114, -87, 'WALK'], stub)               # CRYTOTNK
        self.assertEqual((lex.go['target'].tolist(), lex.go['z'], lex.go['motion'], lex.motion), ([28928.0, -29184.0], -5093, 'WALK', 'WALK'))
        self.assertIsNotNone(stub.wait_pred)
        lex.go, lex.gravity = None, False
        w.call('stmt', 'GO', [-4935, -4215, -100], stub)                   # AI_BEAST: gravity off, z used as is
        self.assertEqual(lex.pos.tolist(), [-1263360.0, -1079040.0, -25600.0])
        lex.gravity = True
        w.call('stmt', 'GO', [6666, 6666, 6666], stub)                     # the park: no floor there, z kept
        self.assertEqual(lex.pos.tolist(), [1706496.0] * 3)
        test_items.run(w, vm, 10)
        self.assertEqual(lex.pos[:2].tolist(), [1706496.0] * 2)
        lex.gravity = False
        lex.pos = np.array([3000.0, -9000.0, -5093.0])
        w.call('stmt', 'GO', [110, int(lex.pos[1]) >> 8, int(lex.pos[2]) >> 8], stub)       # LEDGE: GO 110 COORDY (CURFIG) COORDZ (CURFIG)
        self.assertEqual(lex.pos[:2].tolist(), [28160.0, -9216.0])
        self.assertEqual(lex.pos[2] + w.root_z(lex), -5120.0)              # z is origin + R (10a0:1ff0)
        self.assertEqual(w.warnings, [])

    def test_unknown_modifier_is_an_error(self):
        w, vm, lex = test_items.make()
        before = lex.pos.copy()
        w.call('stmt', 'GO', [1, 2, 3, 'FLY'], test_items.stub())
        self.assertEqual((lex.pos.tolist(), w.warnings), (before.tolist(), ['GO FLY: unknown modifier (error 0x120)']))

    def test_ai_beast_ready_acid_places_the_beast_with_numbers(self):
        w, vm, lex = beach()
        beast = w.figure('ACIDD')
        w.spawn_for(beast, 'READY_ACID')
        scenarios.tick(w, vm, 1)
        self.assertEqual((beast.pos.tolist(), beast.gravity), ([-1263360.0, -1079040.0, -25600.0], False))
        self.assertEqual(w.warnings, [])


class FloatAtHeight(unittest.TestCase):
    def test_beachbot_floats_at_its_waypoint_height(self):
        w, vm, lex = beach()
        bot = w.figure('BCHBOT1')
        wp = [int(c) for c in w.waypoints['B_BOT1']]
        self.assertEqual((bot.assets.foot_offset, w.foot(bot), w.point_floor(*wp, wp[2])), (544, 544, -8787))
        w.spawn_for(bot, 'READY_BBOT1')
        scenarios.tick(w, vm, 5)
        self.assertEqual((bot.foot_override, w.foot(bot), bot.pos.tolist()), (2074, 2074, [-1205185.0, -1069266.0, -6713.0]))
        bot.gravity = True                                                 # grounding uses the new F: the origin stays at the waypoint z
        for _ in range(29):
            scenarios.tick(w, vm, 1)
            self.assertEqual(bot.pos[2], -6713.0)
        bot.foot_override = None
        scenarios.tick(w, vm, 3)
        self.assertEqual(bot.pos[2], -7325.0)                              # with the type's F (544) it would sink
        self.assertEqual((w.warnings, w.unmodelled), ([], []))

    def test_the_override_follows_changemyform_and_needs_no_floor_for_a_figure_without_position(self):
        w, vm, lex = beach()
        lex.foot_override = 99
        w.call('stmt', 'CHANGEMYFORM', ['HARD'], test_items.stub())
        self.assertEqual((lex.foot_override, w.foot(lex)), (None, 2317))
        w.call('stmt', 'FLOATATHEIGHT', ['B_BOT1'], test_items.stub('NOBODY'))
        self.assertIsNone(lex.foot_override)


if __name__ == '__main__':
    unittest.main()
