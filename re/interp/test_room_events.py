"""Room events, the camera switch's show / hide pass and the default AI (re/NOTES.md "Room events and the default AI"), twin of
native/Tests/BioForgeCoreTests/RoomEventsTests.swift with the same numbers.
    re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_room_events.py'"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'formats'))
import level as levelmod  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from test_world import cmd, proc  # noqa: E402

BLOCKS = """
{ BLK_UNLOAD
	_door_frame = 1
}
{ BLK1_UNLOAD
	_door_frame = 2
}
{ CE11_LOAD
	_bak_frame = ISCURRENTCAMERA CE11
	_fnt_frame = ISMYFORM LEX
	_tnkd_frame = ISCURRENTCAMERA CE1
	_bchz_frame = ISCURRENTCAMERA BLK1
}
{ LEX_ON_IN_WALK
	SUSPEND
	SETCURRENTFIGURE PLAYER
	AI ON
	SUSPEND
	_bak_frame = 1
}
{ LEX_ON_THEN_STOP
	SUSPEND
	SETCURRENTFIGURE PLAYER
	AI ON
	SUSPEND
	STOPMOTION
}
{ TESTAI_AI
	_door_frame ++
	AI OFF
	_bchz_frame = 1
	SUSPEND
	_bchz_frame = 2
	:TOP
	SUSPEND
	JUMP TOP
}
"""


class Base(unittest.TestCase):
    def setUp(self):
        w = self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        vmmod.load_level(self.vm, 'CHAOS')
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(BLOCKS)
        try:
            self.vm.load(t.name)
        finally:
            os.unlink(t.name)
        for name in ('_door_frame', '_bchz_frame', '_bak_frame', '_fnt_frame'):
            self.vm.globals[name] = 0
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        self.lex = w.player()
        w.set_pos(self.lex, [-11000, -12000, -5093])
        w.auto_camera = False

    def tick(self, n=1):
        for _ in range(n):
            self.vm.tick_once()
            self.w.step()


class RoomEvents(Base):
    def test_order_room_then_camera_load_then_unload(self):
        w = self.w
        cmd(w, 'CAMERA', 'BLK1')
        self.assertEqual([e[1] for e in w.events], ['BLK_LOAD', 'BLK1_LOAD'])
        w.events.clear()
        cmd(w, 'CAMERA', 'HAL1')                       # 1130:0307-044f
        self.assertEqual([e[1] for e in w.events], ['HAL_LOAD', 'BLK_UNLOAD', 'HAL1_LOAD', 'BLK1_UNLOAD'])
        self.assertEqual(self.vm.globals['_door_frame'], 2)

    def test_same_room_runs_only_the_camera_events(self):
        w = self.w
        cmd(w, 'CAMERA', 'HAL1')
        w.events.clear()
        cmd(w, 'CAMERA', 'HAL3')
        self.assertEqual([e[1] for e in w.events], ['HAL3_LOAD'])

    def test_blocks_run_at_once_with_the_player_and_see_the_new_names(self):
        w, g = self.w, self.vm.globals
        cmd(w, 'CAMERA', 'BLK1')
        cmd(w, 'CAMERA', 'CE11')
        self.assertEqual((g['_bak_frame'], g['_tnkd_frame'], g['_bchz_frame'], g['_fnt_frame']), (1, 1, 0, 1))   # 10d8:2aea: [63e1] or [63e5]
        self.assertEqual(w.current_camera(), 'CE11')

    def test_iscurrentcamera_takes_the_room_name(self):
        w = self.w
        cmd(w, 'CAMERA', 'HAL3')
        func = lambda *a: w.call('func', 'ISCURRENTCAMERA', list(a), proc('LEX'))
        self.assertEqual((func('HAL3'), func('HAL'), func('HAL1'), func('HA')), (1, 1, 0, 0))

    def test_camera_load_form_is_silent_and_switches_nothing(self):
        w = self.w
        cmd(w, 'CAMERA', 'BLK1')
        w.events.clear()
        cmd(w, 'CAMERA', 'BCHZ', 'LOAD')               # FUN_1110_024a: the resource cache only
        self.assertEqual((w.current_camera(), w.events, w.warnings), ('BLK1', [], []))

    def test_a_level_load_keeps_the_old_names(self):
        w = self.w
        cmd(w, 'CAMERA', 'HAL1')
        cmd(w, 'LOADLEVEL', 'TANKS', 'ENTR_TNK')
        self.assertEqual(w.level, 'TANKS')
        self.assertEqual((w.loaded_cam, w.loaded_room), ('HAL1', 'HAL'))        # 1130:0048 clears only [63e1] / [63e5]


class Records(unittest.TestCase):
    def test_ai_off_counter_of_the_records(self):
        def records(path):
            return {o['raw'][33:42].split(b'\0')[0].decode(): worldmod.figr_ai_off(o['raw']) for o in levelmod.load_level(path) if o['tag'] == 'FIGR'}
        self.assertEqual(records(os.path.join(worldmod.INITGAME, 'CHAOS.IFF')), {'USE_BOT': 0, 'FIRSTBOT': 0, 'FIDO': 0, 'HALMECHO': 0, 'CAYNAN': 0, 'GUARD1': 0})
        self.assertEqual(records(os.path.join(worldmod.GAMEDAT, 'CHAOS.IFF')), {'USE_BOT': 1, 'FIDO': 0, 'HALMECHO': 0, 'CAYNAN': 0, 'GUARD1': 0})


class DefaultAI(Base):
    def test_every_record_figure_exists_after_the_load_in_record_order(self):
        self.assertEqual([n for n in self.w.figures if n != 'LEX'], ['USE_BOT', 'FIRSTBOT', 'FIDO', 'HALMECHO', 'CAYNAN', 'GUARD1'])
        self.assertTrue(all(self.w.figures[n].hidden for n in ('USE_BOT', 'HALMECHO')))     # flag 0x04 of the records

    def test_created_figure_is_named_after_itself_with_ai_on(self):
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'TESTAI')
        fig = self.w.figures['TESTAI']
        self.assertEqual((fig.ai_type, fig.hold, fig.ai_enabled), ('TESTAI', 0, True))

    def sentry(self):
        mecho = self.w.figures['HALMECHO']
        cmd(self.w, 'DEFINEVIEWINGCAMS', 'HAL1', 'HAL2', fig='HALMECHO')
        return mecho

    def test_sentry_starts_only_on_a_viewing_camera(self):
        w, mecho = self.w, self.sentry()
        cmd(w, 'CAMERA', 'BLK1')
        self.tick(3)
        self.assertIsNone(mecho.ai_proc)
        cmd(w, 'CAMERA', 'HAL1')
        self.tick(1)
        self.assertEqual((mecho.ai_proc.block.name, mecho.hidden), ('HALMECHO_AI', False))

    def test_hiding_pauses_the_ai_and_stops_the_motion_showing_resumes(self):
        w, mecho = self.w, self.sentry()
        cmd(w, 'CAMERA', 'HAL1')
        self.tick(1)
        proc, handle = mecho.ai_proc, mecho.ai_proc.handle
        mecho.set_motion('WALK', True)
        cmd(w, 'CAMERA', 'BLK1')
        self.tick(1)
        self.assertEqual((mecho.hidden, proc.suspended, proc.done), (True, True, False))
        self.assertEqual((mecho.frozen, mecho.stopped, mecho.idle_request), (True, True, True))   # FUN_1098_0789(fig, 1, 0)
        cmd(w, 'CAMERA', 'HAL2')
        self.tick(1)
        self.assertEqual((mecho.hidden, proc.suspended, mecho.ai_proc.handle), (False, False, handle))

    def test_the_followed_figure_is_shown(self):
        w, mecho = self.w, self.sentry()
        cmd(w, 'CAMERA', 'BLK1')
        self.tick(1)
        self.assertTrue(mecho.hidden)
        w.follow = 'HALMECHO'                             # 1130:00c1, vtable +0x68
        self.tick(1)
        self.assertFalse(mecho.hidden)

    def test_a_block_less_ai_name_starts_nothing_silently(self):
        w = self.w
        fig = w.figures['USE_BOT']
        fig.hidden, fig.view_cams = False, None
        self.tick(2)
        self.assertEqual((fig.ai_proc, w.warnings, self.vm.warnings), (None, [], []))


class AICounter(Base):
    def rig(self):
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'TESTAI')
        fig = self.w.figures['TESTAI']
        self.w.set_pos(fig, [-9000, -12000, -5000])
        self.vm.objects.setdefault('TESTAI', [0] * 10)[0] = 50
        return fig

    def test_off_off_on_stays_off(self):
        fig = self.rig()
        for word, hold in (('OFF', 1), ('OFF', 2), ('ON', 1), ('ON', 0), ('ON', 0)):
            cmd(self.w, 'AI', word, fig='TESTAI')
            self.assertEqual(fig.hold, hold)
        self.assertTrue(fig.ai_enabled)

    def test_own_off_yields_and_on_resumes_where_it_stopped(self):
        fig, g = self.rig(), self.vm.globals
        self.tick(2)                                      # the update starts it (run flag 0), the next slice runs it to its AI OFF
        proc = fig.ai_proc
        self.assertEqual((g['_door_frame'], g['_bchz_frame'], proc.suspended, fig.hold), (1, 0, True, 1))
        self.tick(3)
        self.assertEqual((g['_door_frame'], g['_bchz_frame'], proc.done), (1, 0, False))
        cmd(self.w, 'AI', 'ON', fig='TESTAI')
        self.tick(3)
        self.assertEqual((g['_door_frame'], g['_bchz_frame'], fig.ai_proc), (1, 2, proc))

    def test_off_stops_the_figure_once_and_no_stop_motion_keeps_it(self):
        fig = self.rig()
        self.w.auto_camera, fig.view_cams, fig.hidden = False, None, False
        fig.set_motion('WALK', True)
        cmd(self.w, 'AI', 'OFF', 'NO_STOP_MOTION', fig='TESTAI')
        self.assertEqual((fig.motion, fig.hold), ('WALK', 1))
        cmd(self.w, 'AI', 'ON', fig='TESTAI')
        cmd(self.w, 'AI', 'OFF', fig='TESTAI')
        self.assertEqual((fig.stopped, fig.idle_request, fig.hold), (True, True, 1))
        self.w.step()
        self.assertEqual((fig.motion, fig.stopped), ('STAND', False))    # FUN_1098_0789 keeps the idle-fallback bit (1088:4167)

    def test_second_word_names_the_figure(self):
        fig = self.rig()
        cmd(self.w, 'AI', 'OFF', 'TESTAI', fig='LEX')
        self.assertEqual((fig.hold, self.lex.hold), (1, 0))

    def test_on_refused_without_hit_points(self):
        fig = self.rig()
        cmd(self.w, 'AI', 'OFF', fig='TESTAI')
        self.vm.objects['TESTAI'][0] = 0
        cmd(self.w, 'AI', 'ON', fig='TESTAI')
        self.assertEqual(fig.hold, 1)                     # 10d0:04b3, message 0xea

    def test_player_on_requests_the_idle_and_keys_wait_for_the_counter(self):
        w, lex = self.w, self.lex
        lex.set_motion('WALK', True)
        cmd(w, 'AI', 'OFF', fig='LEX')
        self.assertEqual(self.w.call('func', 'ISAION', [], proc('LEX')), 0)
        cmd(w, 'AI', 'ON', fig='LEX')
        self.assertEqual((lex.motion, lex.hold), ('STAND', 0))    # 10a8:1f2e

    def lex_off_walking(self):
        lex = self.lex
        lex.set_motion('WALK', True)
        cmd(self.w, 'AI', 'OFF', 'NO_STOP_MOTION', fig='LEX')
        return lex

    def test_player_on_in_a_walk_starts_the_idle_in_the_next(self):
        """1098:0745 -> 0e49(fig, name, 1, 0) makes the motion task without running it; made in a walk it first runs in the next one."""
        lex = self.lex_off_walking()
        self.vm.fire('LEX_ON_IN_WALK')
        self.tick(1)                                      # the fire's own slice suspends
        self.tick(1)                                      # AI ON in this walk: the update after it keeps WALK
        self.assertEqual((lex.hold, lex.motion, lex.pending_idle), (0, 'WALK', ('STAND', self.vm.tick - 1)))
        self.tick(1)                                      # the task's first run starts it, the update applies it
        self.assertEqual((lex.motion, lex.pending_idle), ('STAND', None))

    def test_stopmotion_before_the_task_runs_drops_the_idle(self):
        """TO_0G_USE's case (re/NOTES.md "Lex's height in the zero-g room"): STOPMOTION ends the motion task before its first run."""
        lex = self.lex_off_walking()
        self.vm.fire('LEX_ON_THEN_STOP')
        self.tick(3)
        self.assertEqual(lex.pending_idle, None)
        self.assertNotEqual(lex.motion, 'STAND')


if __name__ == '__main__':
    unittest.main()
