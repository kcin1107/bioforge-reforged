"""Tests for playthrough_base.py and the engine fixes the base / ending playthrough needed (re/playthrough/base.md). The fix tests
have Swift twins in PlaythroughBaseTests.swift (same cases, same numbers); the segment tests are Python only, like scenarios.py.
    re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_playthrough_base.py'"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'formats'))
import playthrough_base as pb  # noqa: E402
import script as script_mod  # noqa: E402
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


class LoadLevelCaller(unittest.TestCase):
    """10b0:13fb spares the caller's CALL chain; 10d0:4d46 ends the caller only if its script file is not in the new level."""

    def test_to_final_goes_on_after_its_loadlevel(self):
        w, vm = level('TUNROOM')
        lex = lex_at(w, 'GFROMFIN')
        w.spawn_for(lex, 'TO_FINAL')
        tick(w, vm, 100)
        self.assertEqual(w.level, 'PLATFORM')
        # GO FRMZEROG, then GO WALKHERE WALK: the walk ends within 614 units of WALKHERE (8553, -124063) and does not snap onto it
        self.assertEqual([int(v) for v in w.player().pos[:2]], [8589, -123501])
        self.assertLess(float(np.hypot(*(w.player().pos[:2] - w.arrival_point('WALKHERE')[0]))), worldmod.GO_RADIUS)
        self.assertEqual([e[3] for e in w.log if e[1] == 'TO_FINAL'][-4:], ['FACE', 'GO', 'MOTION', 'AI'])

    def test_a_caller_whose_file_is_not_in_the_new_level_ends(self):
        w, vm = level('BEACH')
        lex_at(w, 'FROM_PAD')
        vm.fire('TO_PAD')                                                   # BCHTOLAN.scr:15 LOADLEVEL LANDPAD FROM_BCH, then SUSPEND
        tick(w, vm, 3)
        self.assertEqual(w.level, 'LANDPAD')
        self.assertFalse(any(p.block.name == 'TO_PAD' for p in vm.procs.values()))

    def test_the_elevator_ride_runs_its_tail_and_arrives_at_the_destination_word(self):
        w, vm = level('LANDPAD')
        lex_at(w, 'ELV')
        vm.fire('SWITCHTOCONTROLLEVEL')                                     # LOADLEVEL CONTROL ELV ELC _sfx_5 (ELEVATOR.scr:304)
        for _ in range(400):
            tick(w, vm, 1)
            if w.level == 'CONTROL' and not any(p.block.name == 'SWITCHTOCONTROLLEVEL' for p in vm.procs.values()):
                break
        self.assertEqual(w.level_loads[-1][1:3], ('CONTROL', 'ELC'))
        self.assertEqual([int(v) for v in w.player().pos], [-38574, -71176, -5099])     # the centre of ELC, not the garage PHYS ELV
        self.assertEqual(vm.tick, 222)                                      # each CALL return goes on in the next walk (1238:077f)
        self.assertIn('EXITSTASIS', {e[1] for e in w.log})


class ObjectLocals(unittest.TestCase):
    """10c0:24e1: selector 1 = CURITEM (+0xe7f), 2 = CURFIG (+0xe7b); INDIVIDUALIZE keeps an object's locals (+0x92)."""

    def test_selectors_decode_as_the_engine_reads_them(self):
        syms = script_mod.load_symbols(worldmod.parse.SCRIPT_DIR)
        text = script_mod.detokenize(open(os.path.join(worldmod.parse.SCRIPT_DIR, 'CONMACH.SCP'), 'rb').read(), syms)
        self.assertIn('IF CURITEM.~0             >= 375 THEN', text)
        self.assertIn('CURITEM.~2                  = _ABAT_500', text)

    def test_curitem_without_an_item_is_not_the_figure(self):
        w, vm = level('CHAOS')
        p = types.SimpleNamespace(cur_fig='LEX', cur_item=None)
        self.assertEqual((vm.objname(p, 'CURFIG'), vm.objname(p, 'CURITEM')), ('LEX', 'CURITEM'))

    def test_individualize_keeps_an_items_locals(self):
        w, vm = level('CONTROL')
        lex = lex_at(w, 'ELC')
        test_items.script(vm, '''{ RENAME_BATTERY
	SETCURRENTITEM ORIGBIKEBAT
	CURITEM.~0 = 150
	CURITEM.~1 = 500
	CURITEM.~2 = _ABAT_500
	INDIVIDUALIZE CURITEM ABAT_500
}''')
        w.spawn_for(lex, 'RENAME_BATTERY')
        self.assertEqual((sorted(k for k in w.items if 'BAT' in k), vm.objects['ABAT_500'][:3], 'ORIGBIKEBAT' in vm.objects),
                         (['ABAT_500', 'DANEBAT'], [150, 500, 3], False))

    def test_individualize_keeps_a_figures_locals(self):
        w, vm = level('CHAOS')
        guard = w.figure('GUARD1')
        vm.objects['GUARD1'][3] = 7
        w.call('stmt', 'INDIVIDUALIZE', ['CURFIG', 'GRD1B'], test_items.stub('GUARD1'))
        self.assertEqual((guard.name, vm.objects['GRD1B'][3], 'GUARD1' in vm.objects), ('GRD1B', 7, False))


class ScriptCalls(unittest.TestCase):
    def test_call_with_a_parenthesised_argument_list(self):
        vm = vmmod.VM()
        test_items.script(vm, '''{ T2 _A _B
	RETURN ~0 + ~1 * 100
}
{ MAIN
	_r1 = CALL ( T2( 3 , 4 ) )
	_r2 = CALL T2 3 4
	PROCESS ( T2( 5 , 6 ) )
}''')
        vm.fire('MAIN')
        vm.tick_once()
        self.assertEqual((vm.globals['_r1'], vm.globals['_r2']), (403, 403))

    def test_a_refused_motion_does_not_block(self):
        w, vm = level('CHAOS')
        lex = lex_at(w, 'PLAYLOC')
        p = types.SimpleNamespace(cur_fig='LEX', cur_item=None, wait_pred=None)
        w.cmd_motion(lex, 'DIE', ['FREEZE', 'CONTINUE'], p)
        w.cmd_motion(lex, 'GET_UP_FORWARD', [], p)                         # 1098:0394 refuses while DIE is current and unfinished: handle 0
        self.assertEqual((lex.motion, p.wait_pred), ('DIE', None))
        w.cmd_motion(lex, 'GET_UP_FORWARD', ['SNAP_TO'], p)                 # 1098:0394 has no SNAP_TO exception: refused too (REVIVELEX runs after the blocking MOTION DIE)
        self.assertEqual((lex.motion, p.wait_pred), ('DIE', None))

    def test_die_then_get_up_once_die_has_finished(self):
        """OPRSCENE (MASTABA.scr:310): `MOTION DIE FREEZE CONTINUE` and later `MOTION GET_UP_FORWARD`. The guard refuses only while DIE is
        the current, unfinished motion; FREEZE keeps the last pose with no idle fallback, and GET_UP_FORWARD then plays."""
        w, vm = level('CHAOS')
        lex = lex_at(w, 'PLAYLOC')
        p = types.SimpleNamespace(cur_fig='LEX', cur_item=None, wait_pred=None)
        w.cmd_motion(lex, 'DIE', ['FREEZE', 'CONTINUE'], p)
        tick(w, vm, 5)
        w.cmd_motion(lex, 'GET_UP_FORWARD', [], p)
        self.assertEqual(lex.motion, 'DIE')                                  # still falling
        tick(w, vm, 120)
        self.assertEqual((lex.motion, lex.finished, lex.no_idle, lex.idx), ('DIE', True, True, len(lex.frames) - 1))   # held, not STAND
        w.cmd_motion(lex, 'GET_UP_FORWARD', [], p)
        self.assertEqual((lex.motion, lex.no_idle), ('GET_UP_FORWARD', False))
        self.assertIsNotNone(p.wait_pred)


class LevelFigures(unittest.TestCase):
    def test_a_level_figure_takes_its_ai_name_from_the_record(self):
        w, _ = level('PLATFORM')
        self.assertEqual(w.figure('ELITE').ai_type, 'ELITE')               # +0x178; 1088:33d4 runs ELITE_AI after AI ON
        w, _ = level('LANDPAD')
        self.assertEqual((w.figure('AIRMECHO').ai_type, w.figure('MARINE4').ai_type), ('AIRMECHO', 'INE4'))


class UseTakesControl(unittest.TestCase):
    def test_a_use_block_that_walks_lex_keeps_its_walk(self):
        w, vm = level('CONTROL')
        lex = lex_at(w, 'ELC')
        w.set_pos(lex, [51789.0, -45129.0, -165153 + w.foot(lex)], raw=True)  # the garage floor at the bike
        w.key_down(pb.SPACE)
        tick(w, vm, 1)
        w.key_up(pb.SPACE)
        self.assertEqual((lex.motion, lex.go is not None), ('WALK', True))   # BIKE_USE: GO HOOD WALK (CONMACH.scr:46)
        tick(w, vm, 30)
        self.assertLess(np.hypot(*(lex.pos[:2] - [51533, -44747])), worldmod.GO_RADIUS)   # the GO ends within 614 of the hood, no snap
        self.assertIsNone(lex.go)


class Segments(unittest.TestCase):
    """The harness segments (playthrough_base.py), each run once."""
    runs = {}

    @classmethod
    def run_of(cls, name):
        if name not in cls.runs:
            cls.runs[name] = dict(pb.SEGMENTS)[name]().report()
        return cls.runs[name]

    def point(self, run, name):
        return next(c for c in run['checkpoints'] if c['name'] == name)

    def kinds(self, run):
        return {s['kind'] for s in run['shortcuts']}

    def test_control_first_visit(self):
        run = self.run_of('control-first')
        self.assertEqual(self.point(run, 'control-arrival')['caller_tail'], ['ELEVATOR_DOOR_OPEN', 'EXITSTASIS'])
        self.assertEqual(self.point(run, 'mecho2')['alive'], 0)
        room = self.point(run, 'operating-room')
        self.assertEqual((room['operate_done'], room['blasters'], room['hp']), (1, [], 100))
        self.assertIn('fight-outcome', self.kinds(run))
        self.assertEqual(room['lex_motion'], 'STAND')                        # MASTABA.scr:310's blocking GET_UP_FORWARD played; AI ON requests the idle (10a8:1f2e)
        self.assertFalse([p for p in run['problems'] if p['kind'] == 'soft-lock'])

    def test_tower_both_landers_with_gun_keys(self):
        run = self.run_of('tower')
        self.assertEqual(self.point(run, 'at-gun')['stage'], 3)
        self.assertEqual((self.point(run, 'first-lander')['alive'], self.point(run, 'second-lander')['alive']), (0, 0))
        self.assertEqual((self.point(run, 'second-lander')['stage'], self.point(run, 'second-lander')['hp']), (5, 100))
        self.assertEqual([p['kind'] for p in run['problems']], [])         # (the one warning was LOADLEVEL's "carried figures keep their absolute position": they now keep their offsets)

    def test_platform_arrival_city_and_battery(self):
        run = self.run_of('platform')
        self.assertTrue(self.point(run, 'platform-arrival')['at_walkhere'])         # within the GO radius (614), no snap
        self.assertAlmostEqual(self.point(run, 'platform-arrival')['walkhere_gap'], 563.151844532183, places=6)
        self.assertEqual(self.point(run, 'city-seen')['city_seen'], 1)
        battery = self.point(run, 'battery')
        self.assertEqual((battery['gave'], battery['battery']), (1, {'ABAT_500': ['ALBAT', 'LEX', 'RTHAND', [500, 500, 3, 1, 0, 0, 0, 0, 0, 0]]}))
        near = self.point(run, 'near-elite')
        # the Elite walks to Lex by itself at its gravity-off height (GO PELITE keeps z 1279) and its attack makes the contact
        self.assertEqual(near['elite_z'], 1279)
        self.assertGreater(near['elite_moved'], 3000)
        self.assertNotIn('contact', self.kinds(run))
        self.assertFalse([p for p in run['problems'] if p['kind'] == 'stuck'])

    def test_ending_reaches_exit(self):
        run = self.run_of('ending')
        # no item-name shortcut: Lex holds the Elite's ABAT_500 (charge 500) when BIKE_USE starts (it drops it, CONMACH.scr:15-19), then the bike's
        # old battery comes out into his hand and RESTOREALIASOFBATTERY names it ABAT_500 too (key ABAT_500#2, charge 150)
        self.assertEqual(self.point(run, 'alien-battery-held')['gift'], ['ABAT_500', 'LEX', 'RTHAND', 500])
        self.assertEqual(self.point(run, 'old-battery')['old'], ['ABAT_500#2', 'LEX', 'RTHAND', [150, 500, 3, 0, 0, 0, 0, 0, 0, 0]])
        self.assertEqual(self.point(run, 'old-battery')['batteries'], [['ABAT_500', None, None, 500], ['ABAT_500#2', 'LEX', 'RTHAND', 150]])
        self.assertEqual(self.point(run, 'alien-battery-in-hand')['held'], ['LEX', 'RTHAND'])
        end = self.point(run, 'endgame')
        self.assertEqual((end['level'], end['battery_in_bike'], end['endgame_alive']), ('TITLE', 3, True))
        self.assertEqual(self.point(run, 'credits')['flic'], 'ENDGAME')
        rolling = self.point(run, 'credits-rolling')                  # the roll runs over the end flic: not paused, CREDITSSTATE 1
        self.assertEqual((rolling['state'], rolling['paused']), ([1, 1], False))
        self.assertEqual((self.point(run, 'credits-done')['credits_pos'], self.point(run, 'credits-done')['state']), (2784, 2))
        self.assertFalse([p for p in run['problems'] if p['kind'] in ('missing', 'wrong')])
        self.assertTrue(run['exit_requested'])
        self.assertEqual(self.point(run, 'exit')['keyboard_captured'], False)


if __name__ == '__main__':
    unittest.main()
