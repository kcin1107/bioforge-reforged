"""The movement fixes (re/NOTES.md "Movement fixes"), twin of native/Tests/BioForgeCoreTests/MovementTests.swift with the same numbers:
A rising motions (MANTLE_*, ladders) commit their root z at each wrap and at their end, with the loop rule from the header event list;
C a GO ends within its radius with no snap; D a LOADLEVEL inside step() drops the PHYS cache; E `support` has no LAND_REVERT clause (so the
LANDPAD jetson tube is walkable). B (FREEZE, DIE then GET_UP) is in test_world.Motions and test_playthrough_base.
    re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_movement.py'"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'formats'))
import test_playthrough_surface  # noqa: E402
import test_world  # noqa: E402
import world as worldmod  # noqa: E402
from test_world import cmd  # noqa: E402


class Movement(unittest.TestCase):
    """The synthetic ROOM space (floor z -3000) of test_world.CollisionResponse, with Lex standing in it."""

    FLOOR = -3000
    box = staticmethod(test_world.CollisionResponse.box)

    def setUp(self):
        self.base = test_world.CollisionResponse('test_mantle_snaps_the_heading_and_picks_by_height')
        self.base.setUp()
        self.w, self.lex, self.stand = self.base.w, self.base.lex, self.base.stand

    def world_with(self, *boxes):
        self.base.world_with(*boxes)

    def step(self, n=1):
        for _ in range(n):
            self.w.step()

    # ---- A: rising motions
    def test_the_header_flag_and_event_list_give_rises_and_the_loop_rule(self):
        a = self.lex.assets
        for name in ('CLIMB_SHUTTLE', 'CLIMB_UP', 'DOWN_LADDER', 'ENTER_IRIS1', 'MANTLE_3', 'MANTLE_6', 'MANTLE_9', 'OFF_LADDER', 'ON_LADDER'):
            self.assertTrue(a.motion_info[name][1] & 2, name)                # +0x1e8 = header flags & 2 (1098.c:274)
        for name in ('WALK', 'STAND', 'ATK_H1', 'TAUNT1', 'DIE'):
            self.assertFalse(a.motion_info[name][1] & 2, name)
        loops = {name: worldmod.motion_loops(a, name) for name in (
            'WALK', 'RUN', 'STAND', 'ATK_STAND', 'TURN_LEFT', 'SIDESTEP_LEFT', 'FALLING', 'CLIMB_UP', 'DOWN_LADDER',
            'TAUNT1', 'ATK_H1', 'MANTLE_3', 'PUSH_BUTTON', 'ON_LADDER', 'CLIMB_SHUTTLE')}
        self.assertEqual([n for n, loop in loops.items() if loop], ['WALK', 'RUN', 'STAND', 'ATK_STAND', 'TURN_LEFT', 'SIDESTEP_LEFT',
                                                                    'FALLING', 'CLIMB_UP', 'DOWN_LADDER'])      # 0xfe in the event list (1088:1854)
        self.assertEqual(a.motion_info['STAND'][5], True)
        self.assertEqual(a.motion_info['TAUNT1'][5], False)
        cmd(self.w, 'MOTION', 'CLIMB_UP', 'CONTINUE')
        self.assertTrue(self.lex.loop)
        cmd(self.w, 'MOTION', 'PUSH_BUTTON', 'CONTINUE')
        self.assertFalse(self.lex.loop)

    def test_motion_continue_of_put_battery_and_twr_victory_does_not_loop(self):
        """R3, closed by inspection: neither motion's event list holds the 0xfe marker (1088:1854), so `MOTION ... CONTINUE` plays once."""
        a = self.lex.assets
        for name in ('PUT_BATTERY', 'TWR_VICTORY'):
            self.assertIn(name, a.motions)
            self.assertFalse(worldmod.motion_loops(a, name), name)

    def test_the_last_root_z_of_the_rising_motions(self):
        a = self.lex.assets.motions
        self.assertEqual([tuple(a[n][-1][0]) for n in ('MANTLE_3', 'MANTLE_6', 'MANTLE_9')],
                         [(42, -1078, 1275), (419, -1010, 3083), (-548, -97, 2792)])
        self.assertEqual((tuple(a['CLIMB_UP'][-1][0]), tuple(a['DOWN_LADDER'][-1][0])), ((0, -13, 1121), (0, -20, -1142)))

    def test_mantle_3_lifts_lex_onto_the_ledge_and_he_stays(self):
        self.world_with(self.box('LEDGE', 1, (1000, -3000, self.FLOOR), (3000, -1000, self.FLOOR + 1200), 2, b'METAL'))
        self.lex.pos = np.array([2000.0, 0.0, self.stand])
        self.lex.heading = 0.0
        self.w.player_input['forward'] = 1
        motions = []
        for _ in range(120):
            self.step()
            if self.lex.motion == 'MANTLE_3':
                self.w.player_input['forward'] = 0                                # released at the bump
            if not motions or motions[-1] != self.lex.motion:
                motions.append(self.lex.motion)
        self.assertEqual(motions, ['WALK', 'MANTLE_3', 'STAND'])                  # no re-mantle: he stands on the ledge
        self.assertEqual(self.lex.pos.tolist(), [2049.0, -1674.0, 512.0])
        self.assertEqual(self.lex.pos[2], self.FLOOR + 1200 + self.lex.assets.foot_offset)    # pos.z == ledge top + F
        lo, hi, sup = self.w.query_hull(self.lex)
        self.assertEqual((sup, lo[2]), (self.FLOOR + 1200, self.FLOOR + 1200))

    def test_climb_up_and_down_ladder_commit_their_last_root_z_per_wrap(self):
        for name, per in (('CLIMB_UP', 1121), ('DOWN_LADDER', -1142)):
            self.world_with()
            z0 = self.lex.pos[2]
            cmd(self.w, 'MOTION', name, 'CONTINUE')
            wraps, prev = 0, self.lex.idx
            while wraps < 2:
                self.step()
                wraps += self.lex.idx < prev
                prev = self.lex.idx
            self.assertEqual((wraps, self.lex.pos[2] - z0), (2, 2 * per), name)   # no stand on the support, no fall: gravity is skipped

    def test_stopmotion_of_a_rising_motion_commits_the_current_root_z(self):
        """UPLADDER's STOPMOTION at the ladder top keeps the height climbed (live: R 0 at once with the z kept). FUN_1098_0789 clears +0x1e8,
        so with no next motion he comes down."""
        self.world_with()
        z0 = self.lex.pos[2]
        cmd(self.w, 'MOTION', 'CLIMB_UP', 'CONTINUE')
        self.step(60)
        self.assertEqual(self.lex.idx, 6)
        self.assertEqual(self.lex.pos[2] - z0, 1121)                                # one wrap committed so far
        cmd(self.w, 'STOPMOTION')
        self.assertEqual((self.lex.pos[2] - z0, tuple(self.lex.frames[0][0])), (1121 + 360, (189, 183, 0)))   # + R of frame 6; the pose carries none
        self.assertEqual((self.lex.rises, self.lex.teeter), (False, True))
        self.step(10)
        self.assertLess(self.lex.pos[2] - z0, 1481)

    # ---- F: a motion's first update applies frame 0's root
    def first_updates(self, motion, n):
        """Lex starts `motion` at a fixed spot, heading 0; returns his x, y displacement after each of n updates."""
        self.world_with()
        self.lex.pos = np.array([2000.0, 0.0, self.stand])
        self.lex.heading = 0.0
        cmd(self.w, 'MOTION', motion, 'CONTINUE')
        p0 = self.lex.pos.copy()
        out = []
        for _ in range(n):
            self.step()
            out.append(((self.lex.pos - p0)[:2]).tolist())
        return out

    def test_a_motions_first_update_moves_lex_by_frame_0s_root(self):
        """FUN_1098_0000 clears the root base when a motion ends and FUN_1088_0581 moves by root minus base, so the first update moves by frame 0's
        whole root x, y. Live, DOSBox-X: WALK_BACK frame 0 (7, 241) moved Lex exactly (7, 241) with the base going (0,0) -> (7,241)."""
        a = self.lex.assets.motions
        self.assertEqual(tuple(a['WALK_BACK'][0][0][:2]), (7, 241))
        self.assertEqual(self.first_updates('WALK_BACK', 2), [[7.0, 241.0], [13.0, 236.0]])          # then frame 1's own root (13, 236)

    def test_whoah_backward_goes_out_by_frame_0_and_frame_1_brings_it_back(self):
        """WHOAH_BACKWARD frame 0 (-69, -259), frame 1 (0, 0): the first update goes out by frame 0, the next returns to the start, so Lex
        is not left 262 units behind it (the old ladder-top fall into the TANKS hatch)."""
        a = self.lex.assets.motions
        self.assertEqual((tuple(a['WHOAH_BACKWARD'][0][0][:2]), tuple(a['WHOAH_BACKWARD'][1][0][:2])), ((-69, -259), (0, 0)))
        self.assertEqual(self.first_updates('WHOAH_BACKWARD', 2), [[-69.0, -259.0], [0.0, 0.0]])

    # ---- B: FREEZE
    def test_only_continue_skips_the_wait_and_freeze_holds_the_last_pose(self):
        """10d0:5e8b / 6083: CONTINUE alone skips the wait; FREEZE clears just the idle-fallback bit, so the motion plays out, the caller
        waits for it, and its last pose stays (no STAND fallback) until the next MOTION."""
        self.world_with()
        lex, w = self.lex, self.w
        p = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'WALK', ['CONTINUE'], p)
        self.assertIsNone(p.wait_pred)
        w.cmd_motion(lex, 'WAKE_UP', ['FREEZE'], p)
        self.assertIsNotNone(p.wait_pred)
        self.assertEqual((lex.motion, lex.frozen, lex.no_idle), ('WAKE_UP', False, True))
        self.assertFalse(p.wait_pred())
        ticks = 0
        while not lex.finished:
            self.step()
            ticks += 1
        self.assertEqual((ticks, lex.idx, p.wait_pred()), (93, len(lex.frames) - 1, True))
        self.step(60)
        self.assertEqual((lex.motion, lex.idx, lex.finished), ('WAKE_UP', len(lex.frames) - 1, True))     # held: no fallback to STAND
        w.cmd_motion(lex, 'STAND', ['CONTINUE'], p)
        self.assertEqual((lex.motion, lex.no_idle, lex.loop), ('STAND', False, True))
        q = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'WAKE_UP', ['FREEZE', 'CONTINUE'], q)                      # CONTINUE: no wait, and it still animates
        self.assertIsNone(q.wait_pred)
        self.step(10)
        self.assertEqual((lex.no_idle, lex.idx > 0), (True, True))

    # ---- C: GO arrival
    def test_a_numeric_gos_fourth_number_is_the_arrival_radius_in_cm(self):
        self.world_with()
        for args, radius in (([10, 0, -12, 'WALK'], 614), ([10, 0, -12, 0, 'WALK'], 614), ([10, 0, -12, 50, 'WALK'], 1024),
                             ([10, 0, -12, 100, 'WALK'], 2048)):
            self.w.cmd_go(self.lex, args)
            self.assertEqual(self.lex.go['radius'], radius, args)                  # N * 2048 // 100, else 0x266 (1098:11c0)

    def test_a_gravity_off_gos_arrival_keeps_its_height(self):
        """GO PELITE / GO FELITE RUN (EL_SCENE.scr:283) used to snap the Elite's origin to the waypoint z at arrival and bury it in PLAT03."""
        self.world_with()
        self.lex.gravity = False
        z0 = self.lex.pos[2]
        self.w.cmd_go(self.lex, [20, 0, 5, 'WALK'])                                 # target z 5 << 8 = 1280, 2048 above Lex
        ticks = 0
        while self.lex.go is not None and ticks < 200:
            self.step()
            ticks += 1
        self.assertEqual((ticks, [round(float(v), 3) for v in self.lex.pos], self.lex.motion), (34, [4633.0, -28.0, z0], 'STAND'))   # 488 short of (5120, 0)
        self.assertLess(float(np.hypot(5120 - self.lex.pos[0], 0 - self.lex.pos[1])), worldmod.GO_RADIUS)

    # ---- D, E
    def test_a_loadlevel_inside_step_drops_the_old_levels_phys_cache(self):
        """step() caches the PHYS boxes for the frame; a trigger's LOADLEVEL swaps self.phys, and `GO FRMZEROG` right after found no floor
        (z -816888) because the cache still held the old level's boxes."""
        w = worldmod.World('CHAOS')
        w._boxes = w._phys_boxes()
        w.load_objects('PLATFORM')
        self.assertIsNone(w._boxes)
        self.assertEqual(len(w._phys_boxes()), 20)
        self.assertEqual(w.point_floor(8553, -116895, 3000, 3000), -1492)             # FRMZEROG's floor, the PLATFORM top

    def test_space_needs_the_hull_on_the_box(self):
        """Live, CRYO_BTN (box edge x -13939): nothing with Lex at x -13567 (hull edge -13935), the button works at -13575 (-13943)."""
        w, _ = test_playthrough_surface.level('CHAOS')
        lex = w.player()
        for x, touching in ((-13567, False), (-13575, True)):
            lex.pos = np.array([x, -79300.0, -5133.0])
            w.select_area(lex)
            self.assertEqual('CRYO_BTN' in w.usable_objects(lex), touching)
        lex.pos = np.array([-13575.0, -79300.0, -5133.0 - 4000])                       # the test is on height too: under the box
        self.assertNotIn('CRYO_BTN', w.usable_objects(lex))

    def test_a_walk_key_breaks_a_scripted_motion(self):
        """10a8:0541 tests only the 1098:12bd gate for walk and run keys: a fresh press ends a taunt, but not a RECOIL. A turn key asks only from stand (1098:13e1)."""
        w, vm = test_playthrough_surface.level('CHAOS')
        lex = w.player()
        lex.pos, lex.manual_control = np.array([-9000.0, -19500.0, -5133.0]), False
        p = types.SimpleNamespace(wait_pred=None)
        def press(key, motion):
            lex.set_motion('STAND', True)
            w.step()
            w.cmd_motion(lex, motion, ['CONTINUE'], p)
            w.key_down(key)
            w.step()
            got = lex.motion
            w.key_up(key)
            w.step()
            return got
        self.assertEqual(press(0x48, 'TAUNT1'), 'WALK')
        self.assertEqual(press(0x4b, 'TAUNT1'), 'TAUNT1')
        self.assertEqual(press(0x48, 'RECOIL_TL'), 'RECOIL_TL')

    def test_a_held_turn_key_steers_a_walk(self):
        """Live: Up + Left stays in walk at 113-117 degrees/s (2 per clock tick here); Left alone plays TURN_LEFT at about 45."""
        w, vm = test_playthrough_surface.level('CHAOS')
        lex = w.player()
        lex.pos, lex.manual_control = np.array([-9000.0, -19500.0, -5133.0]), True
        def rate(keys):
            lex.heading = 0.0
            lex.set_motion('STAND', True)
            for k in keys:
                w.key_down(k)
            for _ in range(10):
                w.step()
            h, motion = lex.heading, lex.motion
            for _ in range(60):
                w.step()
            degrees = round((lex.heading - h) / 2)
            for k in keys:
                w.key_up(k)
            w.step()
            return motion, degrees
        self.assertEqual(rate([0x48, 0x4b]), ('WALK', -120))
        self.assertEqual(rate([0x4b, 0x48]), ('WALK', -120))                           # whichever key went down first
        motion, degrees = rate([0x4b])
        self.assertEqual(motion, 'TURN_LEFT')
        self.assertAlmostEqual(degrees, -45, delta=5)

    def test_ending_a_rising_motion_marks_the_teeter(self):
        """FUN_1098_0789 sets +0x146, so the landing plays no whoah. Live: teeter 0 until ON_LADDER and ENTER_IRIS1 end, 1 at the ladder top."""
        w, _ = test_playthrough_surface.level('CHAOS')
        lex = w.player()
        lex.pos = np.array([-13000.0, -79300.0, -5133.0])
        lex.set_motion('WALK', True)
        lex.set_motion('STAND', True)
        self.assertFalse(lex.teeter)
        lex.set_motion('MANTLE_6', False)
        self.assertFalse(lex.teeter)
        lex.set_motion('STAND', True)
        self.assertTrue(lex.teeter)
        lex.teeter = False
        lex.set_motion('CLIMB_UP', True)
        lex.stop_motion()
        self.assertEqual((lex.teeter, lex.rises), (True, False))

    def test_a_root_move_rounds_down_on_every_update(self):
        """Live moves from CLIMB_UP at heading 87 (FUN_1088_0581): the matrix product is shifted down per axis, not rounded."""
        w = worldmod.World('CHAOS')
        fig = types.SimpleNamespace(heading=87.0)
        self.assertEqual(w.root_step(fig, 22, -1).tolist(), [0, -22])
        self.assertEqual(w.root_step(fig, 0, 5).tolist(), [4, 0])
        self.assertEqual(w.root_step(fig, -2, 0).tolist(), [-1, 1])
        self.assertEqual(w.root_step(fig, 0, 5, 2).tolist(), [3, 0])                  # spread over two updates, (0, 2) then (0, 3)

    def test_a_level_arrival_places_the_player_as_go_does(self):
        """Live, the ladder through the iris: gravity off, TO_TANKS arrives at ENTR_TNK's low z as is; gravity on, TO_CRYO_USE arrives at the floor
        under BTM_LDR + F, far below the box, and CLIMB_UP's -34 stop then falls on the live frame."""
        w, vm = test_playthrough_surface.level('CHAOS')
        lex = test_playthrough_surface.lex_at(w, 'PLAYLOC')
        p = vm.spawn('TO_TANKS')
        lex.gravity, lex.root_start = False, False
        root = w.root_z(lex)
        w.cmd_loadlevel(['TANKS', 'ENTR_TNK'], p)
        self.assertEqual([int(v) for v in lex.pos], [29013, -29002, -3584 - root])
        lex.gravity = True
        for n in range(1, 6):
            vm.globals[f'_qpit{n}_space'] = 0                                         # the open iris
        w.cmd_loadlevel(['CHAOS', 'BTM_LDR'], p)
        self.assertEqual([int(v) for v in lex.pos], [-11380, -74066, -13996 + 2312])

    def test_support_offers_a_tall_solids_top_with_no_land_revert_clause(self):
        """03f2 has no 'top more than 0x1000 above the hull bottom offers the bottom' rule (it blocked the jetson tube and the TANKS catwalk)."""
        self.world_with(self.box('WALL', 1, (1000, -3000, self.FLOOR), (3000, -200, self.FLOOR + 6000)))    # overlaps Lex's hull in y by 168
        self.lex.pos = np.array([2000.0, 0.0, self.stand])
        lo, hi = self.w.hull(self.lex)
        self.assertEqual((lo, hi), ((1632, -368, -3021), (2368, 368, 459)))
        self.assertEqual(self.w.support(self.lex, lo, hi), 3000)                      # the wall's top (the old clause: its bottom, -3000)

    def test_lex_walks_into_the_open_jetson_tube(self):
        """LANDPAD's JETSON1 (state 0 once opened) and its lintel ELVTP4: pushing south from the pad stopped at y -101576 (the lintel's
        bottom was the support); now Lex walks through the door."""
        w, vm = test_playthrough_surface.level('LANDPAD')
        lex = test_playthrough_surface.lex_at(w, 'LEX_POS')
        vm.globals['_jetson1_space'] = vm.globals['_jetson2_space'] = 0
        w.set_pos(lex, [27200.0, -100600.0, -5623.0], raw=True)
        lex.heading, lex.manual_control = 0.0, False
        w.set_player_input(forward=1)
        for _ in range(60):
            vm.tick_once()
            w.step()
        w.set_player_input()
        self.assertEqual([int(v) for v in lex.pos], [27218, -103817, -5628])     # inside the tube; PAD_UP's AI OFF stops him there (FUN_1098_0789)


if __name__ == '__main__':
    unittest.main()
