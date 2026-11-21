"""Tests for the missile subsystem (missiles.py): FIRE, the missile task, CARRY, hits and walls. The Swift twin is MissileTests.swift
(same cases, same numbers).  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_missiles.py'"""
import os
import sys
import tempfile
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import missiles  # noqa: E402
import scenarios  # noqa: E402
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SCRIPT = '''
{ TESTSHOT
	< HAS_GRAVITY = 0 >
	< IS_BOUNCY = 0 >
	< ELASTICITY = 0 >
	< IS_REFLECTIVE = 0 >
	< EXTENT = ( 20, 20, 20 ) >
}
{ TESTBEAM
	< HAS_GRAVITY = 0 >
	< IS_BOUNCY = 0 >
	< ELASTICITY = 0 >
	< IS_REFLECTIVE = 1 >
	< EXTENT = ( 20, 20, 20 ) >
}
{ TESTBEAM_HIT_WALL
	_beam_wall = 1
}
{ TESTSHOT_HIT_TARGET1
	_shot_hit = 1
	CURITEM.~9 = 5
	CURFIG.~9 = 7
}
{ TESTSHOT_HIT
	_shot_hit = 2
}
{ TESTSHOT_HIT_WALL
	_shot_wall = 1
	_shot_x = COORDX (CURITEM)
}
{ ZIPPY
	< EXTENT = ( 1, 1, 1 ) >
}
{ MMTEST
	_mm_state = 1
	SUSPENDWHILE MAKEMISSILE TESTSHOT GUN 10 2 (0,0,0)
	_mm_state = 2
}
{ ZIPTEST
	_zip_state = 1
	SUSPENDWHILE FIRE ZIPPY LEX_POS LEX_POS2 5 0 0 0 CARRY CURFIG
	_zip_state = 2
}
'''
WORLD = None


def stub(fig='PLAYER'):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=fig, cur_item=None, handle=0, waiters=[])


def fresh():
    """A LANDPAD world (shared, reset) with a VM that has the test script blocks."""
    global WORLD
    if WORLD is None:
        WORLD = worldmod.World('LANDPAD')
    w = WORLD
    w.figures.clear()
    w.items = {k: v for k, v in w.items.items() if not v.missile}
    w.player_name = None
    w.camera = w.default_camera = None
    w.log.clear()
    w.warnings.clear()
    w.unmodelled.clear()
    w.sound_log.clear()
    vm = vmmod.VM(w)
    with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
        t.write(SCRIPT)
    try:
        vm.load(t.name)
    finally:
        os.unlink(t.name)
    return w, vm


def drop_world():
    """A test that changed the level leaves the shared world unusable for the next one."""
    global WORLD
    WORLD = None


def target(w, name, pos):
    w.call('stmt', 'CREATEFIGURE', ['LEX', name], stub())
    fig = w.figures[name]
    fig.gravity = False
    fig.pos = np.array(pos, float)
    return fig


def missile(w):
    return next(i for i in w.items.values() if i.missile)


def run(w, vm, n):
    """Frames of the normal loop (VM tick, then world step) until ``n`` ran or ``done()`` holds."""
    for _ in range(n):
        vm.tick_once()
        w.step()


class Fire(unittest.TestCase):
    def test_orientation_velocity_and_range(self):
        w, vm = fresh()
        h = w.call('func', 'FIRE', ['ZIPPY', 'LEX_POS', 'LEX_POS2', 5, 0, 0, 0], stub())
        m = missile(w)
        self.assertEqual((h, m.handle, h in vm.procs), (m.handle, h, True))
        self.assertEqual(m.pos.tolist(), [-35584, -71047, -7366])
        self.assertEqual(m.dist, 7917)                                   # approx_length of (7916, 7, 0)
        self.assertEqual(m.vel, [341, 0, 0])                             # 5 m/s: k = (5 * 2048 << 8) / 0x1e00 = 341, row 1 = (256, 0, 0)
        self.assertEqual(m.rows, [[0, 255, 26], [-256, 0, 0], [0, -26, 255]])   # {U, D, R} turned 180 degrees about Z; R from start x D
        self.assertEqual((m.extent, m.no_collide, m.spin), ([20, 20, 20], False, (0, 0, 0)))

    def test_at_form_and_spin(self):
        w, vm = fresh()
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 20, 10, -3, 65538], stub())
        m = missile(w)
        self.assertEqual(m.pos.tolist(), [83578, -82740, -1549])         # the centre of the PHYS box
        self.assertEqual((m.vel, m.dist, m.spin), ([1365, 5, 0], 25755, (10, -3, 2)))   # AT x, y, z << 8; c keeps its low 16 bits
        self.assertEqual(m.extent, [409, 409, 409])                      # 20 cm * 2048 / 100

    def test_orientation_tumbles_with_spin_and_aims_along_the_flight_without(self):
        w, vm = fresh()
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 20, 10, -3, 65538], stub())
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 20, 0, 0, 0], stub())
        run(w, vm, 3)
        self.assertEqual(w.items['TESTSHOT'].rows, [[-39, 217, 129], [-250, -19, -45], [-27, -135, 217]])
        self.assertEqual(w.items['TESTSHOT_2'].rows, [[-1, 256, 7], [-256, -1, 0], [1, -7, 256]])      # row 1 = -velocity (1365, 5, 0)

    def test_errors_return_zero(self):
        w, vm = fresh()
        self.assertEqual(w.call('func', 'FIRE', ['ZIPPY', 'NOWHERE', 'LEX_POS2', 5, 0, 0, 0], stub()), 0)
        self.assertEqual(w.call('func', 'FIRE', ['ZIPPY', 'LEX_POS'], stub()), 0)
        self.assertFalse(any(i.missile for i in w.items.values()))
        self.assertEqual(len(w.warnings), 2)

    def test_missiles_get_unique_keys_and_are_not_floor_items(self):
        w, vm = fresh()
        for _ in range(2):
            w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 5, 0, 0, 0], stub())
        self.assertEqual([i.name for i in w.items.values() if i.missile], ['TESTSHOT', 'TESTSHOT_2'])
        self.assertEqual([i.name for i in w.floor_items() if i.missile], [])
        p = stub()
        p.cur_item = 'TESTSHOT_2'
        self.assertIs(w.script_object(p, 'CURITEM'), w.items['TESTSHOT_2'])

    def test_spawn_inside_a_solid_expires_on_the_first_tick(self):
        w, vm = fresh()
        h = w.call('func', 'FIRE', ['TESTSHOT', 'OUTWAL1', 'AT', 600, -323, -6, 20, 0, 0, 0], stub())
        m = missile(w)
        self.assertEqual((m.dist, m.vel, m.pos.tolist()), (missiles.NO_RANGE, [0, 0, 0], [30241, -104620, -3590]))
        run(w, vm, 1)
        self.assertEqual((h in vm.procs, 'TESTSHOT' in w.items, vm.globals['_shot_wall'], vm.globals['_shot_x']), (False, False, 1, 118))


class Flight(unittest.TestCase):
    def test_zip_ride_carries_the_rider_and_expires_at_the_range(self):
        w, vm = fresh()
        rider = target(w, 'RIDER', w.script_point(None, 'LEX_POS'))
        rider.gravity = True
        w.spawn_for(rider, 'ZIPTEST')
        m = missile(w)
        self.assertEqual((vm.globals['_zip_state'], m.handle in vm.procs, rider.carrier, m.no_collide), (1, True, 'ZIPPY', True))
        for tick in range(1, 24):                                         # 7917 range / 341 per tick: dist < 0 at the 24th tick
            rows = m.rows                                                 # the orientation the move saw (the tick turns it afterwards)
            run(w, vm, 1)
            self.assertEqual(vm.globals['_zip_state'], 1)
            self.assertEqual(m.pos.tolist(), [-35584 + 341 * tick, -71047, -7366])
            # ON_ZIPPY = (0,0,0) 0 (0,0,100) on LEX: 100 cm = 2048 units along the missile's row 2 (8 * the 24.8 row)
            self.assertEqual(rider.pos.tolist(), (m.pos + [8 * c for c in rows[2]]).tolist())
            self.assertEqual(m.dist, 7917 - 341 * tick)
        run(w, vm, 1)
        self.assertEqual((m.handle in vm.procs, 'ZIPPY' in w.items, m.dead, rider.carrier), (False, False, True, None))
        self.assertEqual(rider.pos.tolist(), [-27400, -71255, -5326])     # left where the missile expired (268 units past LEX_POS2: range accounting is by |step|), 2048 units up the row 2
        self.assertEqual((rider.vx, rider.vy, rider.vz), (0, 0, 0))
        self.assertEqual(vm.globals['_zip_state'], 1)                     # the death only woke the waiter (1238:077f) ...
        run(w, vm, 1)
        self.assertEqual(vm.globals['_zip_state'], 2)                     # ... it goes on in the next walk
        self.assertNotIn('FIRE: unmodelled function (ignored)', w.unmodelled)
        self.assertEqual(w.call('func', 'ISPROCESSVALID', [m.handle], stub()), 0)

    def test_figure_hit_runs_the_instance_block_with_the_hit_figure_and_the_missile(self):
        w, vm = fresh()
        target(w, 'TARGET1', [86578, -82740, -1549])
        h = w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 5, 0, 0, 0], stub())
        m = missile(w)
        for tick in range(1, 7):
            run(w, vm, 1)
            self.assertEqual((h in vm.procs, m.pos.tolist()[0]), (True, 83578 + 341 * tick))
        run(w, vm, 1)                                                     # the 7th move puts the box at 86374..86374+818 over the hull
        self.assertEqual((h in vm.procs, 'TESTSHOT' in w.items, m.pos.tolist()), (False, False, [85965, -82733, -1549]))
        self.assertEqual(vm.globals['_shot_hit'], 1)
        self.assertEqual((vm.objects['TESTSHOT'][9], vm.objects['TARGET1'][9]), (5, 7))   # CURITEM = the missile, CURFIG = the figure
        self.assertNotIn('_shot_wall', vm.globals)

    def test_figure_without_an_instance_block_runs_the_type_block(self):
        w, vm = fresh()
        target(w, 'OTHER', [86578, -82740, -1549])
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 5, 0, 0, 0], stub())
        run(w, vm, 7)
        self.assertEqual((vm.globals['_shot_hit'], 'TESTSHOT' in w.items), (2, False))

    def test_hidden_figures_are_not_hit(self):
        w, vm = fresh()
        target(w, 'TARGET1', [86578, -82740, -1549]).view_cams = ['NOCAM']     # not in the current camera: hidden
        w.camera = w.current_camera()                                          # (the hide pass needs a camera switched to)
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 5, 0, 0, 0], stub())
        run(w, vm, 7)
        self.assertEqual(('TESTSHOT' in w.items, '_shot_hit' in vm.globals), (True, False))

    def test_wall_stops_the_missile_and_runs_hit_wall_in_the_same_tick(self):
        w, vm = fresh()
        h = w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 600, -323, -6, 20, 0, 0, 0], stub())
        m = missile(w)
        self.assertEqual((m.vel, m.dist), ([1365, 0, 0], 70043))
        for tick in range(1, 100):
            run(w, vm, 1)
            if h not in vm.procs:
                break
        self.assertEqual((tick, vm.globals['_shot_wall'], m.vel), (23, 1, [0, 0, 0]))
        self.assertEqual((m.pos.tolist(), vm.globals['_shot_x']), ([83578 + 1365 * 22, -82740, -1549], 443))   # the last good position
        self.assertNotIn('_shot_hit', vm.globals)
        self.assertEqual('TESTSHOT' in w.items, False)

    def _wall_run(self, kind, flag):
        """Fire ``kind`` along +x from inside HFR at the closed solid DR18 (PHYS, state 1) with its flag byte (record byte 21) set to ``flag``;
        -> (world, vm, missile, handle, ticks until the first block, the velocity after it, whether it is still alive then)."""
        w, vm = fresh()
        h = w.call('func', 'FIRE', [kind, 'HFR', 'AT', 600, 0, 0, 20, 0, 0, 0], stub())
        m = missile(w)
        m.pos, m.vel, m.dist = np.array([-16432.0, -71293.0, -4178.0]), [1365, 0, 0], 70043
        dr18 = next(p for p in w.phys if p.get('name') == 'DR18')
        saved = dr18['raw']
        dr18['raw'] = bytearray(saved)
        dr18['raw'][21] = flag
        try:
            for tick in range(1, 100):
                run(w, vm, 1)
                if h not in vm.procs or m.vel != [1365, 0, 0]:
                    break
            return w, vm, m, h, tick, list(m.vel), h in vm.procs
        finally:
            dr18['raw'] = saved

    def test_reflective_missile_rebounds_off_a_flag_4_wall_and_flies_on(self):
        w, vm, m, h, tick, vel, alive = self._wall_run('TESTBEAM', 4)           # FUN_1070_1d8f: flag 0x20 and the collider's byte & 4
        self.assertEqual((tick, vel, alive, '_beam_wall' in vm.globals), (11, [-1365, 0, 0], True, False))
        self.assertEqual(m.pos.tolist(), [-16432 + 1365 * 10, -71293, -4178])   # the X candidate (the move's start) is free

    def test_reflective_missile_stops_at_a_wall_without_flag_4(self):
        w, vm, m, h, tick, vel, alive = self._wall_run('TESTBEAM', 3)
        self.assertEqual((tick, vel, alive, vm.globals['_beam_wall']), (11, [0, 0, 0], False, 1))

    def test_plain_missile_stops_at_a_flag_4_wall(self):
        w, vm, m, h, tick, vel, alive = self._wall_run('TESTSHOT', 4)
        self.assertEqual((tick, vel, alive, vm.globals['_shot_wall']), (11, [0, 0, 0], False, 1))

    def test_a_level_change_destroys_the_missile_without_hit_wall_and_wakes_its_waiter(self):
        w, vm = fresh()
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 20, 0, 0, 0], stub())
        h = missile(w).handle
        run(w, vm, 3)
        self.addCleanup(drop_world)
        w.call('stmt', 'LOADLEVEL', ['TUNROOM'], stub())                  # 10d0:4d46 -> 10e0:11aa on every missile task, before anything else
        self.assertEqual((any(i.missile for i in w.items.values()), h in vm.procs), (False, False))
        self.assertNotIn('_shot_wall', vm.globals)

    def test_a_level_change_runs_the_hit_block_of_a_stored_target(self):
        w, vm = fresh()
        target(w, 'TARGET1', [-30000, -70000, -5000])
        w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 20, 0, 0, 0], stub())
        m = missile(w)
        m.hit = w.figures['TARGET1']
        self.addCleanup(drop_world)
        w.call('stmt', 'LOADLEVEL', ['TUNROOM'], stub())
        self.assertEqual((vm.globals.get('_shot_hit'), '_shot_wall' in vm.globals, any(i.missile for i in w.items.values())), (1, False, False))

    def test_range_ends_a_free_flight(self):
        w, vm = fresh()
        h = w.call('func', 'FIRE', ['TESTSHOT', 'PAD01', 'AT', 427, -323, -6, 20, 0, 0, 0], stub())    # range 25755 at 1365 a tick
        m = missile(w)
        run(w, vm, 18)
        self.assertEqual((h in vm.procs, m.dist), (True, 25755 - 18 * 1366))         # |step| = approx_length((1365, 5, 0)) = 1366
        run(w, vm, 1)
        self.assertEqual((h in vm.procs, vm.globals['_shot_wall']), (False, 1))


def tower(w, name='TOWER2'):
    """A TOWERBOT (a type with a GUN limb and no motions: rest pose) in the middle of PAD01, turned 30 degrees."""
    w.call('stmt', 'CREATEFIGURE', ['TOWERBOT', name], stub())
    fig = w.figures[name]
    fig.gravity, fig.pos, fig.heading = False, np.array([83578.0, -82740.0, -1549.0]), 30.0
    return fig


class MakeMissile(unittest.TestCase):
    def test_limb_shot_starts_outside_the_owner_and_flies_along_the_limb(self):
        w, vm = fresh()
        fig = tower(w)
        h = w.call('func', 'MAKEMISSILE', ['TESTSHOT', 'GUN', 10, 225, [0, 0, 0]], stub('TOWER2'))
        m = missile(w)
        self.assertEqual((h, m.handle, h in vm.procs, m.owner_fig), (m.handle, h, True, fig))
        self.assertEqual((m.dist, m.vel, m.spin), (225 * 2048, [-341, -592, 0], (0, 0, 0)))   # 10 m/s: k = 682 along the GUN limb's row 1
        self.assertEqual((m.pos.tolist(), m.rows), ([82900, -83916, -2093], [[-222, 128, 0], [128, 222, 0], [0, 0, -256]]))
        travel = [-c for c in m.rows[1]]                                # the figure's row 1 is backward
        self.assertEqual(m.vel, [worldmod.fix_mul(c, 682) for c in travel])
        lo, hi, _ = w.query_hull(fig)
        box = lambda p: ([c - e for c, e in zip(p, m.extent)], [c + e for c, e in zip(p, m.extent)])
        pos = [int(c) for c in m.pos]
        self.assertFalse(w.boxes_touch(*box(pos), lo, hi))              # pushed out of the owner's box ...
        self.assertTrue(w.boxes_touch(*box([c - t for c, t in zip(pos, travel)]), lo, hi))     # ... by the last step only
        self.assertEqual(w.warnings, [])

    def test_script_shot_expires_and_wakes_the_waiter(self):
        w, vm = fresh()
        fig = tower(w)
        w.spawn_for(fig, 'MMTEST')
        m = missile(w)
        self.assertEqual((m.dist, vm.globals['_mm_state'], m.handle in vm.procs), (4096, 1, True))
        for tick in range(1, 6):                                        # |step| = approx_length((-341, -592, 0)) = 709: dist < 0 at the 6th tick
            run(w, vm, 1)
            self.assertEqual((m.handle in vm.procs, m.dist), (True, 4096 - 709 * tick))
        run(w, vm, 1)
        self.assertEqual((m.handle in vm.procs, vm.globals['_mm_state'], vm.globals['_shot_wall'], 'TESTSHOT' in w.items), (False, 1, 1, False))
        run(w, vm, 1)                                                   # the waiter, woken by the expiry, goes on in the next walk (1238:077f)
        self.assertEqual(vm.globals['_mm_state'], 2)
        self.assertNotIn('_shot_hit', vm.globals)                       # the owner is never the hit figure

    def test_missing_limb_figure_or_name_gives_zero_silently(self):
        w, vm = fresh()
        tower(w)
        for args, cur in ((['TESTSHOT', 'NOLIMB', 10, 2, [0, 0, 0]], 'TOWER2'), (['TESTSHOT', 10, 2, [0, 0, 0]], 'TOWER2'),
                          (['TESTSHOT', 'GUN', 10, 2, [0, 0, 0]], 'NOBODY')):
            self.assertEqual(w.call('func', 'MAKEMISSILE', args, stub(cur)), 0)
        self.assertEqual((any(i.missile for i in w.items.values()), w.warnings, 'MAKEMISSILE: unmodelled function (ignored)' in w.unmodelled), (False, [], False))

    def test_held_blaster_shoots_from_the_item_along_minus_row_1_and_hits_the_nurse(self):
        w, vm, lex = test_items.make()
        blaster = w.items['BLASTER']
        self.assertTrue(w.attach_item(lex, blaster))                    # right hand
        lex.set_motion('ATK_SHOOT', False)
        lex.idx = 4                                                     # the frame of the shoot event (0xf0)
        nurse = w.figure('FIRSTBOT')
        nurse.gravity, nurse.pos, nurse.view_cams = False, np.array([400.0, -32800.0, -5000.0]), None
        p = stub('LEX')
        p.cur_item = 'BLASTER'
        h = w.call('func', 'MAKEMISSILE', ['LASER', 6, 60, [0, 0, 0]], p)
        m = missile(w)
        self.assertEqual((m.type, m.owner_fig, m.handle in vm.procs, m.dist, m.vel), ('LASER', lex, True, 60 * 2048, [12, -409, -7]))
        self.assertEqual((m.pos.tolist(), m.rows), ([398, -30538, -4817], [[232, 9, -108], [-8, 256, 4], [-108, 0, -232]]))
        lo, hi, _ = w.query_hull(lex)
        self.assertFalse(w.boxes_touch([c - e for c, e in zip(m.pos, m.extent)], [c + e for c, e in zip(m.pos, m.extent)], lo, hi))
        w.log.clear()
        for tick in range(1, 40):
            test_items.run(w, vm, 1)
            if h not in vm.procs:
                break
        self.assertEqual(tick, 5)
        self.assertEqual(m.pos.tolist(), [458, -32583, -4852])
        blocks = [e[1] for e in w.log]
        self.assertIn('LASER_HIT', blocks)                              # no LASER_HIT_FIRSTBOT: the type block runs for the nurse
        self.assertNotIn('LASER_HIT_LEX', blocks)
        self.assertEqual(vm.objects['FIRSTBOT'][0], 29)                 # LASER_HIT: CURFIG.~0 (the target's health) > 0, so DAMAGE ENERGY 25


class ShootEvent(unittest.TestCase):
    """Event byte 0xf0 (ATK_SHOOT frame 4) -> FUN_1090_15d0: `<held weapon>_FIRE` with CURITEM, else `<figure>_FIRE`."""

    def test_blaster_in_the_right_hand_fires_a_laser_through_the_scripts(self):
        w, vm, lex = test_items.make()
        self.assertTrue(w.attach_item(lex, w.items['BLASTER']))
        self.assertTrue(w.spawn_for(lex, 'LEX_ATK_SHOOT'))              # the shoot attack: MOTION ATK_SHOOT
        self.assertEqual(lex.motion, 'ATK_SHOOT')
        frames = None
        for frames in range(1, 80):
            test_items.run(w, vm, 1)
            if any(i.missile for i in w.items.values()):
                break
        m = missile(w)
        self.assertEqual((frames, lex.idx, w.key_log[-1]), (9, 3, (9, 'item', 'BLASTER_FIRE')))   # 0xf0 after frame byte 3: fires while frame 3 shows
        self.assertEqual((m.type, m.owner_fig, m.dist, m.vel), ('LASER', lex, 60 * 2048, [12, -409, -7]))
        self.assertEqual((m.pos.tolist(), m.rows), ([410, -30552, -4817], [[-232, -9, 108], [-8, 256, 4], [-109, 0, -232]]))
        self.assertNotIn('MAKEMISSILE: unmodelled function (ignored)', w.unmodelled)

    def test_without_a_weapon_the_figure_block_runs_and_a_missing_block_is_silent(self):
        w, vm, lex = test_items.make()
        test_items.script(vm, '{ LEX_FIRE\n\t_lex_fire = CURITEM.~9 + 1\n}\n')
        w.fire_event_item(lex)                                          # nothing held
        self.assertEqual((vm.globals['_lex_fire'], w.key_log[-1][2:]), (1, ('LEX_FIRE',)))
        fork = worldmod.Item('FORK_X', 'FORK', 'LEX', 'RTHAND')         # held but not a weapon (no IS_WEAPON)
        w.items['FORK_X'] = fork
        vm.globals['_lex_fire'] = 0
        w.fire_event_item(lex)
        self.assertEqual(vm.globals['_lex_fire'], 1)
        n = len(w.key_log)
        other = w.figure('GUARD1')
        other.pos = lex.pos.copy()
        w.fire_event_item(other)                                        # no GUARD1_FIRE block: nothing happens
        self.assertEqual((len(w.key_log), any(i.missile for i in w.items.values())), (n, False))


class Beach(unittest.TestCase):
    def test_zip_line_ride(self):
        """BEACH ZIP1_A -> ZIP1_B with the shipped scripts: Lex rides the ZIPPY missile (BEACHZIP.scr) and POSTZIPMOMBO runs."""
        world = worldmod.World('BEACH')
        vm = vmmod.VM(world)
        vmmod.load_level(vm, 'BEACH')
        world.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        lex = world.player()
        a, b = world.script_point(None, 'ZIP1_A'), world.script_point(None, 'ZIP1_B')
        lex.pos = np.array(a, float)
        world.spawn_for(lex, 'ZIP1_A_BLOCK_USE')
        ticks, ran = 0, set()
        while vm.globals.get('_ziptripping') != 0 and ticks < 400:        # POSTZIPMOMBO (the ride's last step) clears it
            scenarios.tick(world, vm, 1)
            ticks += 1
            ran |= {p.block.name for p in vm.procs.values()}
        self.assertEqual((ticks, lex.pos.tolist()), (89, [-1172509, -1016488, -19360]))
        self.assertNotIn('BCHDETH', ran)                                   # the acid trigger stays clear: Lex hangs 2048 units above the line
        self.assertFalse(any(i.missile for i in world.items.values()))
        # the missile ends 195 units from ZIP1_B's centre; Lex is 2048 units up its row 2 (ON_ZIPPY)
        self.assertLess(float(np.linalg.norm(lex.pos - np.array(b, float))), 2300)
        self.assertNotIn('FIRE: unmodelled function (ignored)', world.unmodelled)


if __name__ == '__main__':
    unittest.main()
