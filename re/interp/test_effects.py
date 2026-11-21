"""Tests for effects.py: MAKEFLATOBJECT, EXPLODE, THROWCURITEM and the free-item physics. The Swift twin is EffectsTests.swift (same cases, same
numbers).  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_effects.py'"""
import os
import random
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SCRIPT = '''
{ EXPLTEST
	_ex = 1
	EXPLODE CURFIG
	_ex = 2
}
{ WAITTEST
	_ex = 1
	WAIT 150
	_ex = 2
}
{ EXPLCONT
	_ex = 1
	KILL CURFIG
	EXPLODE CURFIG CONTINUE
	_ex = 2
}
{ EXPLOTHER
	_ex = 1
	EXPLODE SOMEONE
	_ex = 2
}
'''
WORLD = None


def fresh():
    """A LANDPAD world (shared, reset) with a VM that has the test script blocks."""
    global WORLD
    if WORLD is None:
        WORLD = worldmod.World('LANDPAD')
    w = WORLD
    w.figures.clear()
    w.items.clear()
    w.flat_objects = []
    w.fragments, w.dead_figures = [], {}
    w.player_name = None
    w.camera = w.default_camera = None
    w.killed_figures.clear()
    w.warnings.clear()
    w.unmodelled.clear()
    vm = vmmod.VM(w)
    test_items.script(vm, SCRIPT)
    return w, vm


def lifetime(w, vm, args):
    """Ticks (VM tick + world step) after which a flat object made from ``args`` is still in the list (capped at 100)."""
    w.flat_objects = []
    w.call('stmt', 'MAKEFLATOBJECT', args, test_items.stub())
    for n in range(100):
        if not w.flat_objects:
            return n - 1
        test_items.run(w, vm, 1)
    return None


class FlatObjects(unittest.TestCase):
    def test_lifetimes_are_the_frame_count_minus_two(self):
        w, vm = fresh()
        self.assertEqual([lifetime(w, vm, a) for a in (['BOOM', 'PING', 10, 10, 50], ['BOOM', 'WHITE', 10, 10, 50],
                                                       ['TNKD', 'Q4B', 10, 10, 50], ['BOOM', 'BLUEC', 10, 10, 50])], [1, 21, 10, 17])

    def test_a_short_sequence_stays_until_delete(self):
        w, vm = fresh()
        w.call('stmt', 'MAKEFLATOBJECT', ['BOOM', 'BLANK', 0, 0, 50], test_items.stub())
        w.call('stmt', 'MAKEFLATOBJECT', ['TNKD', 'Q4B', 0, 0, 50], test_items.stub())
        test_items.run(w, vm, 40)
        self.assertEqual([f.cam for f in w.flat_objects], ['BOOM'])
        w.call('stmt', 'MAKEFLATOBJECT', ['tnkd', 'q4b', 0, 0, 50], test_items.stub())
        w.call('stmt', 'MAKEFLATOBJECT', ['BOOM', 'delete'], test_items.stub())
        self.assertEqual([f.cam for f in w.flat_objects], ['TNKD'])

    def test_the_object_form_keeps_the_point_it_had_when_made(self):
        w, vm = fresh()
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], test_items.stub())
        lex = w.player()
        lex.pos = np.array([1000.0, 2000.0, 3000.0])
        w.call('stmt', 'MAKEFLATOBJECT', ['BOOM', 'WHITE', 'CURFIG'], test_items.stub())
        lex.pos = np.array([9.0, 9.0, 9.0])
        test_items.run(w, vm, 3)
        self.assertEqual([f.point for f in w.flat_objects], [[1000, 2000, 3000]])
        w.call('stmt', 'MAKEFLATOBJECT', ['BOOM', 'WHITE', 'NO_SUCH_OBJECT'], test_items.stub())
        self.assertEqual(len(w.flat_objects), 1)
        w.call('stmt', 'MAKEFLATOBJECT', ['BOOM', 'NOPE', 1, 2, 3], test_items.stub())
        self.assertEqual(len(w.flat_objects), 1)
        self.assertEqual(len(w.warnings), 1)

    def test_a_flat_sprite_is_drawn_unscaled_at_its_top_left(self):
        w, vm = fresh()
        cam = 'CE24'
        plain = w.render_camera(cam, indexed=True)
        w.call('stmt', 'MAKEFLATOBJECT', ['BOOM', 'WHITE', 160, 100, 50], test_items.stub())
        test_items.run(w, vm, 1)                                        # frame 2: 15 x 21, hot spot (-52, -31); W, H = the largest frame
        f = w.flat_objects[0]
        pw, ph, hx, hy, px, mask = f.frames[f.frame]
        x0, y0 = 160 - f.w // 2 - hx, 100 - f.h // 2 - hy
        img = w.render_camera(cam, indexed=True)
        self.assertEqual((f.frame, pw, ph, f.w, f.h, x0, y0), (2, 15, 21, 112, 91, 160 - 56 + 52, 100 - 45 + 31))
        drawn = [(x, y) for y in range(ph) for x in range(pw) if mask[y * pw + x]]
        self.assertTrue(drawn)
        self.assertTrue(all(img[y0 + y, x0 + x] == px[y * pw + x] for x, y in drawn))
        self.assertGreater(int((img != plain).sum()), 0)
        self.assertEqual(int((img[y0:y0 + ph, x0:x0 + pw] != plain[y0:y0 + ph, x0:x0 + pw]).sum()), int((img != plain).sum()))


def proc_for(vm, block, fig):
    return vm.spawn(block, ctx=types.SimpleNamespace(cur_fig=fig, cur_item=None, owner='level'))


class Explode(unittest.TestCase):
    def test_explode_waits_150_ticks_and_hides_the_figure_and_its_items(self):
        w, vm = fresh()
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'TARGET1'], test_items.stub())
        fig = w.figures['TARGET1']
        fig.pos = np.array([0.0, 0.0, 0.0])
        item = worldmod.Item('HELD', 'FORK', 'TARGET1', 'RTHAND')
        w.items['HELD'] = item
        proc_for(vm, 'EXPLTEST', 'TARGET1')
        self.assertEqual((vm.globals['_ex'], fig.exploded, item.hidden), (1, True, True))
        n = test_items.steps_until(w, vm, lambda: vm.globals['_ex'] == 2, 300)
        proc_for(vm, 'WAITTEST', 'TARGET1')
        self.assertEqual((n, test_items.steps_until(w, vm, lambda: vm.globals['_ex'] == 2, 300)), (n, n))      # the same wait as WAIT 150
        self.assertEqual(n, 151)
        self.assertTrue(fig.hidden)
        self.assertEqual(w.warnings, [])

    def test_continue_does_not_wait_and_survives_a_kill(self):
        w, vm = fresh()
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'TARGET1'], test_items.stub())
        proc_for(vm, 'EXPLCONT', 'TARGET1')
        self.assertEqual(vm.globals['_ex'], 2)
        self.assertEqual(w.warnings, [])

    def test_a_figure_that_is_not_current_is_an_error_without_a_wait(self):
        w, vm = fresh()
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'TARGET1'], test_items.stub())
        proc_for(vm, 'EXPLOTHER', 'TARGET1')
        self.assertEqual(vm.globals['_ex'], 2)
        self.assertEqual(len(w.warnings), 1)
        self.assertFalse(w.figures['TARGET1'].exploded)


class Shrapnel(unittest.TestCase):
    """EXPLODE's fragments (10f8:1ea2, ctor 10f8:124c, update 10f8:19ea): the same stream as script RANDOM, four draws per fragment."""
    def setUp(self):
        self.w, self.vm = fresh()
        self.w.rng = random.Random(7)
        self.w.call('stmt', 'CREATEFIGURE', ['TOWERBOT', 'BOT'], test_items.stub())
        self.fig = self.w.figures['BOT']
        self.fig.gravity = False
        self.fig.pos = np.array([83578.0, -82740.0, -1549.0])
        self.fig.set_motion('EXPLODE', False, quiet=True)               # the dying pose
        self.fig.area = 21                                              # PAD01 (LANDPAD)

    def test_a_kill_then_explode_throws_one_fragment_per_ten_faces_with_one_to_five_faces(self):
        proc_for(self.vm, 'EXPLCONT', 'BOT')                            # KILL CURFIG, EXPLODE CURFIG CONTINUE: the killed object still has its pose
        w = self.w
        self.assertNotIn('BOT', w.figures)
        n = len(self.fig.assets.mesh.polys)
        self.assertEqual(n, 62)
        self.assertEqual([len(f.mesh.polys) for f in w.fragments], [1, 2, 3, 4, 5, 1])        # 6 = ceil((62 - 10) / 10)

    def test_velocities_and_lives_are_four_draws_each_from_the_shared_stream(self):
        w = self.w
        ref = random.Random(7)
        clock = w.game_tick * 2
        proc_for(self.vm, 'EXPLTEST', 'BOT')
        for k, f in enumerate(w.fragments):
            n = k % 5 + 1
            v = [ref.randint(0, 512) - 256, ref.randint(0, 514) - 257, ref.randint(0, 516) - 258]
            length = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
            v = [(int((c << 8) / length) * 4505) >> 8 for c in v]
            end = clock + 60 * (5 - n) + ref.randint(0, 59)
            self.assertEqual((f.vel, f.end), (v, end))
            self.assertTrue(4400 < sum(c * c for c in v) ** 0.5 < 4600)
        self.assertEqual(w.rng.random(), ref.random())                   # exactly 4 * 6 draws

    def test_a_fragment_dies_after_its_life(self):
        w, vm = self.w, self.vm
        proc_for(vm, 'EXPLTEST', 'BOT')
        life = max(f.end - w.game_tick * 2 for f in w.fragments)
        test_items.run(w, vm, life // 2 - 2)
        self.assertGreater(len(w.fragments), 0)
        test_items.run(w, vm, 6)
        self.assertEqual(w.fragments, [])

    def test_the_fragments_are_drawn_as_polygons(self):
        w = self.w
        cam = w.cameras['PAD7']
        self.fig.view_cams, self.fig.area = None, None
        self.fig.pos = np.array(cam['pos']) + cam['R'][1] * 8000          # straight ahead of the camera (row 1 is its axis)
        proc_for(self.vm, 'EXPLTEST', 'BOT')
        with_pieces = w.render_camera('PAD7', indexed=True)
        w.fragments = []
        self.assertGreater(int((with_pieces != w.render_camera('PAD7', indexed=True)).sum()), 0)

    def test_a_fragment_bounces_off_its_area_box_and_falls(self):
        w = self.w
        box = w.phys[21]
        lo, hi = [int(c) for c in box['lo']], [int(c) for c in box['hi']]
        import effects
        f = effects.Fragment(None, np.zeros((0, 3)), [lo[0] + 100, (lo[1] + hi[1]) // 2, (lo[2] + hi[2]) // 2], [-2560, 0, -2000], 10 ** 9, 21)
        w.fragments = [f]
        w.tick_fragments()
        self.assertEqual((f.pos[0], f.vel[0]), (lo[0] + 100, 2560))     # 100 - 250 is outside: the old x stays, vx flips
        self.assertEqual(f.pos[2], (lo[2] + hi[2]) // 2 + ((-2000 * 25) >> 8))
        self.assertEqual(f.vel[2], -2000 - 240)                          # gravity 240 a frame, no cap
        f.pos[2] = lo[2] + 10
        f.vel[2] = -2000
        w.tick_fragments()
        self.assertEqual(f.vel[2], -((-2000 * 230) >> 8) - 240)    # below -0x400: lost 230/256, then flipped


def tunroom(heading):
    """TUNROOM with Lex at PIL_BASE (the temple floor) holding a grenade, facing ``heading``."""
    w = worldmod.World('TUNROOM')
    vm = vmmod.VM(w)
    vmmod.load_level(vm, 'TUNROOM')
    w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], test_items.stub())
    lex = w.player()
    lex.pos = np.array(w.waypoints['PIL_BASE'], float) + np.array([0, 0, lex.assets.foot_offset])
    lex.heading = heading
    w.settle(lex)
    grenade = worldmod.Item('GRENADE', 'GRENADE')
    w.items['GRENADE'] = grenade
    assert w.attach_item(lex, grenade)
    return w, vm, lex, grenade


def cur_item(name):
    p = test_items.stub()
    p.cur_item = name
    return p


class Throw(unittest.TestCase):
    def test_throw_adds_the_velocity_of_a_leap_along_minus_row_1(self):
        w, vm, lex, g = tunroom(-90.0)
        w.call('stmt', 'THROWCURITEM', [0, -12], cur_item('GRENADE'))
        self.assertEqual((g.owner, g.slot, g.pos.tolist(), g.vel), (None, None, [8276, -28035, -10107], [245, 0, 0]))
        self.assertEqual((g.extent, g.bouncy, g.gravity, g.elasticity), ([102, 102, 102], True, True, 110))
        w.call('stmt', 'THROWCURITEM', [0, -12], cur_item('GRENADE'))      # added, not assigned
        self.assertEqual(g.vel, [490, 0, 0])

    def test_throw_errors(self):
        w, vm, lex, g = tunroom(0.0)
        w.call('stmt', 'THROWCURITEM', [0, -12], test_items.stub())            # no current item
        p = cur_item('GRENADE')
        p.cur_fig = None
        w.call('stmt', 'THROWCURITEM', [0, -12], p)                            # no current figure
        self.assertEqual((len(w.warnings), g.owner), (2, lex.name))

    def test_grenade_flies_straight_without_gravity_and_bounces_off_the_wall(self):
        """TEMPLE GRENADE_FIRE (GRAVITY CURITEM OFF, THROWCURITEM 0 -12, PROCESS GRENADEENTERTUBE) with the shipped TUNROOM scripts: the
        grenade flies 245 units a tick along +X, rebounds from the wall (E = 110) and GRENADEENTERTUBE, which waits for VELOCITYX to change, runs."""
        w, vm, lex, g = tunroom(-90.0)
        vm.spawn('GRENADE_FIRE', ctx=types.SimpleNamespace(cur_fig='PLAYER', cur_item='GRENADE', owner='level'))
        self.assertEqual((g.gravity, g.vel, g.pos.tolist()), (False, [245, 0, 0], [8276, -28035, -10107]))
        p = cur_item('GRENADE')
        seen = []
        for tick in range(1, 60):
            test_items.run(w, vm, 1)
            seen.append(w.call('func', 'VELOCITYX', ['CURITEM'], p))
            if seen[-1] != 245:
                break
        self.assertEqual((tick, seen[-1], seen[-2]), (34, -139, 245))
        self.assertEqual((g.pos.tolist(), g.vel, g.bouncy), ([16361, -28035, -10107], [-139, 0, 0], True))
        test_items.run(w, vm, 5)
        self.assertNotIn('GRENADE', w.items)                 # GRENADEENTERTUBE saw the change, was away from the tube and removed the item

    def test_a_gravity_item_falls_and_a_plain_one_stops_on_the_floor(self):
        w, vm, lex, g = tunroom(0.0)
        item = worldmod.Item('ALBAT', 'ALBAT')
        item.pos, item.matrix = np.array([8142.0, -27403.0, -8000.0]), np.eye(3)
        w.items['ALBAT'] = item
        w.call('stmt', 'SETVELOCITY', ['CURITEM', 50, 0, -1], cur_item('ALBAT'))
        test_items.run(w, vm, 1)
        self.assertEqual((item.pos.tolist(), item.vel), ([8192, -27403, -8103], [50, 0, -103]))
        n = test_items.steps_until(w, vm, lambda: not any(item.vel), 30)
        self.assertEqual((n, item.pos.tolist(), item.vel), (7, [8517, -27403, -11271], [0, 0, 0]))

    def test_leap_and_stopvelocity_work_on_items(self):
        w, vm, lex, g = tunroom(0.0)
        item = worldmod.Item('G2', 'GRENADE')
        item.pos, item.matrix = np.array([8142.0, -27403.0, -11672.0]), np.eye(3)
        w.items['G2'] = item
        p = cur_item('G2')
        w.call('stmt', 'GRAVITY', ['CURITEM', 'OFF'], p)
        w.call('stmt', 'LEAP', ['CURITEM', 'TMP_PT', 0, 12], p)
        self.assertEqual((item.vel, w.call('func', 'VELOCITYX', ['CURITEM'], p), item.gravity), ([237, -4, -61], 237, False))
        w.call('stmt', 'STOPVELOCITY', ['CURITEM'], p)
        self.assertEqual((item.vel, w.call('func', 'VELOCITYX', ['CURITEM'], p)), ([0, 0, 0], 0))


if __name__ == '__main__':
    unittest.main()
