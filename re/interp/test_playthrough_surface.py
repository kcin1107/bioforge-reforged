"""Tests for playthrough_surface.py and the engine fixes the surface playthrough needed (re/playthrough/surface.md). The fix tests
have Swift twins in PlaythroughSurfaceTests.swift (same cases, same numbers); the segment tests are Python only, like scenarios.py.
    re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_playthrough_surface.py'"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playthrough_surface as ps  # noqa: E402
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from scenarios import tick  # noqa: E402


def level(name):
    w = worldmod.World(name, state_dir=worldmod.INITGAME)
    vm = vmmod.VM(w)
    vmmod.load_level(vm, name)
    w.fire_event(name + '_LOAD')
    return w, vm


def lex_at(w, arrival):
    w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], test_items.stub())
    t = w.arrival_point(arrival)
    w.set_pos(w.player(), [t[0][0], t[0][1], t[1] + w.foot(w.player())], raw=True)
    return w.player()


def ctx():
    return types.SimpleNamespace(cur_fig=None, cur_item=None, owner='level')


def press(w, vm, scan, after=1):
    w.key_down(scan)
    tick(w, vm, 1)
    w.key_up(scan, 0)
    tick(w, vm, after)


DANGLING = """{ SYN_DANGLE
	IF _temp1 = 1 THEN
		IF _temp2 = 1 THEN
			_temp3 = 1
	ELSE
		_temp3 = 2
}
{ SYN_BRACED
	IF _temp1 = 1 THEN
		{
		IF _temp2 = 1 THEN
			_temp3 = 1
		}
	ELSE
		_temp3 = 2
}
"""


class DanglingElse(unittest.TestCase):
    """IF (10d0:3a6c) keeps its result per brace depth, a false IF skips a nested IF without its ELSE (10c0:0f78), and ELSE (10d0:27f9)
    runs iff the depth's last IF was false."""

    def outcomes(self, block):
        w, vm = level('BEACH')
        test_items.script(vm, DANGLING)
        out = []
        for a, b in ((0, 0), (1, 0), (1, 1)):
            vm.globals.update({'_temp1': a, '_temp2': b, '_temp3': 0})
            vm.spawn(block, ctx=ctx())
            test_items.run(w, vm, 2)
            out.append(vm.globals['_temp3'])
        return out

    def test_an_else_after_a_braceless_if_chain_also_runs_when_the_outer_if_is_false(self):
        self.assertEqual(self.outcomes('SYN_DANGLE'), [2, 2, 1])

    def test_an_else_after_a_braced_then_belongs_to_the_outer_if(self):
        self.assertEqual(self.outcomes('SYN_BRACED'), [2, 0, 1])

    def test_the_dropped_warhead_counts_down_to_zero(self):
        w, vm = level('BEACH')
        vm.globals.update({'_warhead_status': 2, '_warhead_timer': 5})     # LEX_BOMB_DROP in FIREBTN2 (WARHEAD.scr:256-267)
        vm.spawn('WARHEAD_TIMER', ctx=ctx())
        seq = []
        for _ in range(24):
            seq.append(vm.globals['_warhead_timer'])
            test_items.run(w, vm, 1)
        self.assertEqual(seq, [5] * 5 + [4] * 4 + [3] * 4 + [2] * 4 + [1] * 4 + [0] * 3)    # one step per 00:04; it used to stop at 4


class GoTarget(unittest.TestCase):
    """GO <name> (10d0:33c8): a figure, a waypoint, then an IMAG at its reference point (vtable +0x50: the box centre)."""

    def test_a_trigger_is_reached_at_its_box_centre_and_a_waypoint_at_its_position(self):
        w, vm = level('BEACH')
        xy, z, is_fig = w.go_target('TO_LNDR')          # IMAG (-1142956, -1001050, -11776)..(-1132204, -999002, -9728)
        self.assertEqual(([int(v) for v in xy], z, is_fig), ([-1137580, -1000026], -10752.0, False))
        xy, z, _ = w.go_target('KNEEL')
        self.assertEqual(([int(v) for v in xy], z), ([-1105184, -1032017], -21277.0))


class PlayerInput(unittest.TestCase):
    def test_a_suited_lex_shoots_through_the_instance_name(self):
        """FUN_1098_0e49 formats `%s_%s` with the instance name +0xf7: HARD runs LEX_ATK_SHOOT (no HARD_ATK_SHOOT exists)."""
        w, vm = level('LANDPAD')
        lex = lex_at(w, 'LEX_POS')
        w.call('stmt', 'CHANGEMYFORM', ['HARD'], test_items.stub())
        w.items['BLASTER'] = worldmod.Item('BLASTER', 'BLASTER', owner='LEX', slot='RTHAND')
        tick(w, vm, 10)
        press(w, vm, ps.COMBAT, 40)
        press(w, vm, ps.SHOOT, 40)
        self.assertEqual((lex.type, lex.combat), ('HARD', True))
        self.assertEqual(w.key_log[-2:], [(11, 'combat', True), (60, 'item', 'BLASTER_FIRE')])

    def test_a_script_loop_of_a_player_move_yields_to_the_keys(self):
        """AIRMECHO's death leaves Lex in `MOTION ATK_M2 CONTINUE` with AI ON (AI_AMECH.scr:95): Up takes him over."""
        w, vm = level('LANDPAD')
        lex = lex_at(w, 'LEX_POS')
        tick(w, vm, 10)
        lex.set_motion('ATK_M2', True)
        lex.manual_control = False
        start = lex.pos.copy()
        w.key_down(0x48)
        tick(w, vm, 1)
        self.assertEqual((lex.manual_control, lex.motion), (True, 'WALK'))
        tick(w, vm, 10)
        w.key_up(0x48, 0)
        self.assertEqual([int(v) for v in lex.pos - start], [18, -733, 0])

    def test_a_trigger_loadlevel_drops_the_old_levels_figures_from_the_frame(self):
        """TO_BCH's LOADLEVEL BEACH FROM_PAD (LANDPAD.scr:712-733) runs inside the frame's trigger pass; LANDPAD's other figures used
        to be updated against BEACH's PHYS list afterwards (IndexError)."""
        w, vm = level('LANDPAD')
        lex = lex_at(w, 'FROM_BCH')
        w.figure('LDGBOT1')
        o = next(o for o in w.objs if o['name'] == 'TO_BCH')
        c = (np.minimum(o['pos'], o['pos2']) + np.maximum(o['pos'], o['pos2'])) / 2
        w.set_pos(lex, [c[0], c[1], lex.pos[2]], raw=True)
        tick(w, vm, 4)
        self.assertEqual(w.level, 'BEACH')
        self.assertEqual([int(v) for v in lex.pos], [-1181989, -987717, -7874])
        self.assertEqual(sorted(w.figures), ['ACIDD', 'BCHBOT1', 'BCHBOT2', 'BCHBOT3', 'LEX', 'MARINE2', 'MARINE3A', 'TUMOLT'])    # every FIGR of BEACH (1148:18d3)


class Segments(unittest.TestCase):
    """The harness's four segments, run once: which steps pass, which known blockers fail, and which shortcuts were staged."""

    @classmethod
    def setUpClass(cls):
        cls.reports = {r['segment']: r for r in ps.run_all()}

    def outcomes(self, name):
        return [(s['step'], s['ok']) for s in self.reports[name]['steps']]

    def kinds(self, name):
        return [c['kind'] for c in self.reports[name]['shortcuts']]

    def test_landpad_plays_from_the_elevator_to_the_beach(self):
        self.assertEqual(self.outcomes('landpad'), [
            ('elevator-arrival', True), ('meet-mech', True), ('airmecho-dead', True), ('airlock-solved', True),
            ('decontamination', True), ('walk-into-tube', True), ('jetson-tube', True), ('to-beach', True)])
        # the one set_pos is the meet-mech correction (Lex stood on LEXSTUK); AIRMECHO is fought by keys (airmecho_duel);
        # the walk into the open jetson tube is real
        self.assertEqual(self.kinds('landpad'), ['form', 'item', 'global', 'global', 'item', 'process', 'set_pos'])

    def test_beach_plays_from_the_pad_to_the_digsite_suit_machine(self):
        self.assertEqual(self.outcomes('beach'), [
            ('arrival', True), ('reach-zip1', True), ('zip1', True), ('zip2', True), ('zip3', True), ('climb-block32', True),
            ('zip4', True), ('warhead', True), ('door-blasted', True), ('to-digsite', True)])
        last = self.reports['beach']['steps'][-1]
        self.assertEqual((last['level'], last['lex']['form']), ('DIGSITE', 'LEX'))
        self.assertEqual(self.kinds('beach'), ['form', 'item', 'item', 'global', 'global', 'global', 'global', 'global', 'global',
                                               'set_pos', 'set_pos', 'set_pos', 'set_pos', 'set_pos'])      # (+ the mantle run-up)

    def test_digsite_reaches_tunroom_through_the_dig_tube(self):
        self.assertEqual(self.outcomes('digsite'), [('arrival', True), ('dig-tube-to-tunroom', True)])

    def test_tunroom_reaches_platform(self):
        self.assertEqual(self.outcomes('tunroom'), [
            ('arrival', True), ('walk-after-tube', True), ('zero-g-room', True), ('exit-to-platform', True)])
        # walk-after-tube: a fresh key press now breaks ENTER_GRAV FREEZE (1098:12bd ignores the freeze flag; prison playthrough)
        last = self.reports['tunroom']['steps'][-1]
        self.assertEqual(last['level'], 'PLATFORM')
        # TO_FINAL's `GO FRMZEROG` runs inside the frame's trigger pass: the stale PHYS cache used to find no floor there (z -816888); Lex
        # now stands on the PLATFORM floor (-1492 + F 2312) and `GO WALKHERE WALK` ends 554 units short of WALKHERE (no snap)
        self.assertEqual(last['lex']['pos'], [8589, -123501, 820])


if __name__ == '__main__':
    unittest.main()
