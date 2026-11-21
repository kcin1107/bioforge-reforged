"""Prison playthrough regressions: the input fixes it needed (twins of PlaythroughTests.swift) and the segments that pass."""
import os
import sys
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import playthrough_prison as pp  # noqa: E402
import world as worldmod  # noqa: E402
from test_items import make, run  # noqa: E402


class PlayerInput(unittest.TestCase):
    def test_space_names_held_item_blocks_after_the_instance(self):
        """"%s_USE" with the item instance (+0xf7): DANELOG, a LOGBOOK, runs DANELOG_USE (10a8:17f0-1803)."""
        w, vm, lex = make(lex=(-10186.0, -33568.0))
        w.items.clear()
        log = worldmod.Item('DANELOG', 'LOGBOOK', 'LEX', 'INVENTORY')
        w.items['DANELOG'] = log
        self.assertTrue(w.place_item(lex, log, 'CARRY'))
        self.assertEqual(w.player_use(lex), 'DANELOG_USE')

    def test_a_use_blocks_go_is_not_replaced_by_stand(self):
        """Space returns once a USE block started (10a8:1113): PRY_DR_USE's GO PRY_HERE WALK walks Lex there."""
        # (starts about 1270 units from PRY_HERE, with the hull on PRY_DR's box: a GO ends within 614 units of its target, so the old start 535 units away arrived at once)
        w, vm, lex = make(lex=(7000.0, -20200.0), heading=180.0)
        w.items.clear()
        w.key_down(0x39)
        run(w, vm, 1)
        w.key_up(0x39)
        self.assertEqual((lex.motion, lex.go is not None), ('WALK', True))     # was: GO kept, motion STAND, no travel
        start = lex.pos[:2].copy()
        run(w, vm, 10)
        self.assertEqual((lex.motion, int(np.hypot(*(lex.pos[:2] - start))) > 200), ('WALK', True))   # towards PRY_HERE's centre
        self.assertEqual(w.key_log[-1][1:], ('use', 'PRY_DR_USE'))

    def test_freeze_and_unwaited_script_motions_yield_to_keys(self):
        """1098:12bd stops any motion but RECOIL / DIE / SUPER_REC for a key's motion: a FREEZE'd LOOK_AT_MON, CHAOSHAL's
        `PUSH_BUTTON CONTINUE FREEZE` and a looping CONTINUE (ATK_STAND: its header event list holds the 0xfe marker) give way to Up; a
        MOTION a script blocks on stays (port ownership rule)."""
        w, vm, lex = make(lex=(0.0, -20000.0))
        for motion, flags in (('LOOK_AT_MON', ['FREEZE']), ('PUSH_BUTTON', ['CONTINUE', 'FREEZE']), ('ATK_STAND', ['CONTINUE'])):
            w.cmd_motion(lex, motion, flags)
            run(w, vm, 3)
            w.set_player_input(forward=1)
            run(w, vm, 2)
            self.assertEqual(lex.motion, 'WALK', (motion, flags))
            w.set_player_input()
            run(w, vm, 10)
        proc = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'PUSH_BUTTON', [], proc)
        w.set_player_input(forward=1)
        run(w, vm, 2)
        self.assertEqual(lex.motion, 'PUSH_BUTTON')


class Segments(unittest.TestCase):
    """One run of the harness from a new game through the TANKS catwalk; each segment that passes is a test."""

    @classmethod
    def setUpClass(cls):
        cls.r = pp.play()
        cls.seg = {s["name"]: s for s in cls.r.segments}

    def passed(self, name):
        self.assertEqual(self.seg[name]['status'], 'passed', [p for p in self.r.problems if p['segment'] == name])
        return next(c for c in self.r.checkpoints if c['name'] == name)

    def test_fork_and_cell_panel(self):
        self.passed('fork')
        self.passed('cell-panel')
        self.assertEqual(self.r.vm.globals['_celpan_state'], 4)

    def test_cell_block_door_and_cell_four_bars(self):
        self.passed('cell-block-door')
        self.passed('cell-four-bars')
        self.assertEqual((self.r.vm.globals['_cel_door_state'], self.r.vm.globals['_bars4_on']), (1, 0))

    def test_danes_log_shows_the_rolled_code(self):
        self.passed('danes-log')
        g = self.r.vm.globals
        self.assertEqual(self.r.code, ''.join(str(g[f'_access_id{i}_to_match']) for i in range(1, 6)))

    def test_robot_holds_the_arm_for_the_terminal_and_the_floor_panel(self):
        point = self.passed('caynans-arm')
        self.assertEqual(point['held']['RTHAND'], 'CAYARM')
        self.passed('arm-to-reader')
        arm = self.r.world.items['CAYARM']
        self.assertEqual((arm.owner, arm.slot), ('USE_BOT', 'UP_ARM'))   # the NURSEBOT has no RTHAND limb: MY_HAND (1138:088d)
        self.passed('security-terminal')
        self.assertEqual(self.r.terminal_answer, 'GSECPASS')           # AMINTRIGGER(CAYARM, ARMHERE1) sees the arm in the claw
        self.passed('guard-room-door')                                 # CHANDQ (the floor panel) opens DR6 with the arm still in the claw
        self.assertEqual((arm.owner, arm.slot), ('USE_BOT', 'UP_ARM'))

    def test_hallway_cryo_room_and_ladder_reach_tanks(self):
        self.passed('hallway')
        point = self.passed('cryo-ladder')
        self.assertEqual(point['level'], 'TANKS')
        self.assertEqual(self.r.vm.globals['_beenintanks'], 1)
        self.assertTrue(-24500 < point['player']['position'][2] < -20000)
        # DOWNLADDER / TO_TANKS wait for COORDZ / DISTFROMTRIGGER while the looping DOWN_LADDER commits -1142 units per wrap: no placement
        self.assertNotIn('ladder-descent', {s['name'] for s in self.r.shortcuts})

    def test_tanks_catwalk_mantles_onto_the_ledge_and_reaches_tocell2(self):
        """Lex walks the catwalk with the Fido puzzle staged, MANTLE_6 lifts him onto the CBLT / LTB ledge (a ledge top is 2838 above the
        floor, MANTLE_6's last root z is 3083) and TOCELL2 loads CHAOS."""
        self.passed('tanks')
        self.assertEqual(self.r.world.level, 'CHAOS')
        self.assertEqual([load[1] for load in self.r.world.level_loads][-2:], ['TANKS', 'CHAOS'])
        self.assertNotIn('go-arrival', {s['name'] for s in self.r.shortcuts})

    def test_shortcuts_are_the_listed_ones(self):
        self.assertEqual(sorted({s['name'] for s in self.r.shortcuts}),
                         sorted(['nurse-poses', 'difficulty-easy', 'fido-puzzle']))
        self.assertTrue(all(s['name'] in pp.SHORTCUTS for s in self.r.shortcuts))

    def test_lex_keeps_the_health_the_caynan_fight_left(self):
        after_caynan = next(c for c in self.r.checkpoints if c['name'] == 'caynan')['lex_health']
        at_the_ladder = next(c for c in self.r.checkpoints if c['name'] == 'cryo-ladder')['lex_health']
        self.assertEqual((after_caynan, at_the_ladder), (57, 57))          # (the seeded Easy fight, scenarios.CAYNAN_SEED, on the stream EXPLODE's shrapnel moves; Lex is hit by none after it)
        self.assertEqual(self.r.world.unmodelled, [])


if __name__ == '__main__':
    unittest.main()
