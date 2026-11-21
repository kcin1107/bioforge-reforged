"""LINKMETOCAMERAS (re/NOTES.md "Camera-linked processes"), twin of native/Tests/BioForgeCoreTests/CameraLinkTests.swift with the same numbers.
    re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_camera_links.py'"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from test_world import cmd  # noqa: E402

BLOCKS = """
{ CAML_ANIM
	LINKMETOCAMERAS BLK1 HAL1
	:TOP
	_door_frame ++
	SUSPEND
	JUMP TOP
}
{ CAML_WAIT
	LINKMETOCAMERAS BLK1
	_bak_frame = 1
	WAIT 5
	_bak_frame = 2
}
[ CAML_TIME
	LINKMETOCAMERAS BLK1
	00:05 _fnt_frame = 1
	00:10 _fnt_frame = 2
	00:20 _fnt_frame = 3
]
{ CAML_CHILD
	WAIT 3
	_bchz_frame = 1
}
{ CAML_PARENT
	LINKMETOCAMERAS BLK1
	CALL CAML_CHILD
	_bchz_frame = 2
}
{ CAML_BAD
	LINKMETOCAMERAS NOSUCH BLK1
}
{ CE12_LOAD
	PROCESS CAML_ANIM
}
"""


class Base(unittest.TestCase):
    def setUp(self):
        w = self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(BLOCKS)
        try:
            self.vm.load(t.name)
        finally:
            os.unlink(t.name)
        vmmod.load_level(self.vm, 'CHAOS')
        for name in ('_door_frame', '_bchz_frame', '_bak_frame', '_fnt_frame'):
            self.vm.globals[name] = 0
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        w.set_pos(w.player(), [-11000, -12000, -5093])
        w.auto_camera = False

    def spawn(self, name):
        return self.vm.spawn(name)

    def tick(self, n=1):
        for _ in range(n):
            self.vm.tick_once()


class FirstCamera(Base):
    def test_a_link_is_not_a_camera_and_the_first_frame_takes_the_nearest_accepting_one(self):
        w = self.w
        w.auto_camera = True
        p = self.spawn('CAML_ANIM')                    # BLK1 HAL1
        self.tick()
        self.assertIsNone(w.default_camera)
        self.assertFalse(p.suspended)                  # linking alone pauses nothing
        pos = w.player().pos
        accepting = {n: worldmod.accepts(c, pos) for n, c in w.cameras.items()}
        nearest = min((d, n) for n, (ok, d) in accepting.items() if ok and n not in w.disabled)[1]
        self.assertIsNone(w.camera)
        w.update_camera()
        self.assertEqual(w.camera, nearest)            # 1130:0fa3 with [63ce] 0, at once ([63e0] 1)
        self.assertEqual(w.camera_changes[-1][1], None)
        self.assertEqual(p.suspended, nearest not in p.cameras)

    def test_a_level_load_leaves_a_linked_survivor_alone(self):
        w = self.w
        cmd(w, 'CAMERA', 'BLK1')
        p = self.spawn('CAML_ANIM')
        self.tick()
        w.cmd_loadlevel(['CHAOS'], p)                  # 1130:0048 clears [63ce], so 1148:15c7 has no camera to switch to
        self.assertIsNone(w.camera)
        self.assertFalse(w.script_auto)                # LOADLEVEL leaves the flag 1290:63da alone: CAMERA BLK1 set it 0
        self.assertFalse(p.suspended)


class Links(Base):
    def test_linking_alone_pauses_nothing_the_next_switch_decides(self):
        cmd(self.w, 'CAMERA', 'BLK2')                  # not in the list
        p = self.spawn('CAML_ANIM')
        self.assertEqual(p.cameras, ['BLK1', 'HAL1'])
        self.assertFalse(p.suspended)                  # 10c0:547d only registers
        self.tick(3)                                   # the first slice ran at the spawn; its SUSPEND sleeps through tick 0
        self.assertEqual(self.vm.globals['_door_frame'], 3)
        cmd(self.w, 'CAMERA', 'HAL3')                  # 10c0:5688: not listed
        self.assertTrue(p.suspended)
        self.tick(3)
        self.assertEqual(self.vm.globals['_door_frame'], 3)
        cmd(self.w, 'CAMERA', 'HAL1')                  # listed: on again where it stood
        self.assertFalse(p.suspended)
        self.tick(2)
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_an_unknown_name_is_a_warning_and_the_rest_links(self):
        p = self.spawn('CAML_BAD')
        self.assertEqual(self.w.warnings, ['LINKMETOCAMERAS NOSUCH: unknown camera (error 0x1e)'])
        self.assertTrue(p.done)

    def test_the_list_holds_ten(self):
        self.w.link_to_cameras(p := self.spawn('CAML_ANIM'), ['BLK2', 'BLK3', 'BLK4', 'BLK5', 'HAL2', 'HAL3', 'CE11', 'CE12'])
        self.assertEqual(len(p.cameras), 10)
        self.w.link_to_cameras(p, ['CE21'])
        self.assertEqual(len(p.cameras), 10)
        self.assertEqual(self.w.warnings, ['LINKMETOCAMERAS CE21: CAML_ANIM already has 10 cameras (error 0xe1)'])

    def test_a_wait_runs_out_while_paused_and_the_process_goes_on_when_resumed(self):
        cmd(self.w, 'CAMERA', 'BLK1')
        p = self.spawn('CAML_WAIT')
        cmd(self.w, 'CAMERA', 'HAL1')
        self.tick(20)                                  # the Wait task is another task, not flagged
        self.assertEqual(self.vm.globals['_bak_frame'], 1)
        cmd(self.w, 'CAMERA', 'BLK1')
        self.assertEqual(self.vm.globals['_bak_frame'], 1)
        self.tick(1)
        self.assertEqual(self.vm.globals['_bak_frame'], 2)
        self.assertTrue(p.done)

    def test_a_timeline_catches_up_in_one_slice(self):
        cmd(self.w, 'CAMERA', 'BLK1')
        self.spawn('CAML_TIME')
        self.tick(6)
        self.assertEqual(self.vm.globals['_fnt_frame'], 1)
        cmd(self.w, 'CAMERA', 'HAL1')
        self.tick(30)                                  # 10c8:03e1: the clock is [8330], origin stays
        self.assertEqual(self.vm.globals['_fnt_frame'], 1)
        cmd(self.w, 'CAMERA', 'BLK1')
        self.tick(1)
        self.assertEqual(self.vm.globals['_fnt_frame'], 3)

    def test_a_called_child_runs_on_and_its_parent_waits_for_the_camera(self):
        cmd(self.w, 'CAMERA', 'BLK1')
        self.spawn('CAML_PARENT')
        cmd(self.w, 'CAMERA', 'HAL1')
        self.tick(6)
        self.assertEqual(self.vm.globals['_bchz_frame'], 1)
        cmd(self.w, 'CAMERA', 'BLK1')
        self.tick(1)
        self.assertEqual(self.vm.globals['_bchz_frame'], 2)

    def test_a_process_an_event_block_starts_is_flagged_by_the_same_switch(self):
        cmd(self.w, 'CAMERA', 'HAL3')
        cmd(self.w, 'CAMERA', 'CE12')                  # CE12_LOAD's child links BLK1, HAL1; 10c0:5688 comes after the events
        anim = next(p for p in self.vm.procs.values() if p.block.name == 'CAML_ANIM')
        self.assertTrue(anim.suspended)
        self.assertEqual(self.vm.globals['_door_frame'], 1)

    def test_a_switch_overrides_suspendprocess_and_the_same_camera_is_no_switch(self):
        cmd(self.w, 'CAMERA', 'BLK1')
        p = self.spawn('CAML_ANIM')
        p.suspended = True                             # SUSPENDPROCESS: the same flag bit (10d0:7985)
        cmd(self.w, 'CAMERA', 'BLK1')                  # 10d0 CAMERA: no call of 1130:0114 for the current camera
        self.assertTrue(p.suspended)
        cmd(self.w, 'CAMERA', 'HAL1')
        self.assertFalse(p.suspended)

    def test_the_automatic_camera_switches_too(self):
        cmd(self.w, 'CAMERA', 'BLK1')
        p = self.spawn('CAML_ANIM')
        self.w.set_camera('HAL3', 'the camera manager')
        self.assertTrue(p.suspended)


    def test_after_the_show_hide_pass_the_list_decides(self):
        """1130:050d-0546 pauses a hidden figure's AI, then 1130:0549 runs the links: the bot AIs (LANBOT1_AI ...) link themselves."""
        cmd(self.w, 'CAMERA', 'BLK1')
        fig = self.w.figures['CAYNAN']
        p = self.spawn('CAML_ANIM')
        fig.ai_proc, fig.view_cams, fig.hidden = p, ['HAL1'], False
        self.w.update_hidden(fig, 'BLK1')              # not viewed: hidden, but BLK1 is in the AI's list
        self.assertTrue(fig.hidden)
        self.assertFalse(p.suspended)
        fig.hidden = False
        self.w.update_hidden(fig, 'HAL3')              # not viewed and not listed
        self.assertTrue(p.suspended)


class ZeroG(unittest.TestCase):
    def test_the_zero_g_processes_run_only_in_the_zero_g_room(self):
        """ZEROG_TURNING adds TURN on the keypad and ZEROG_GRAVITY pulls Lex to GRAVPT; outside ZEG1-4 they stand still (TUNZEROG.scr:30-75)."""
        w = worldmod.World('TUNROOM', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(w)
        vmmod.load_level(vm, 'TUNROOM')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        w.auto_camera = False
        vm.fire('TUNROOM_LOAD')
        zero_g = [p for p in vm.procs.values() if p.block.name in ('ZEROG_TURNING', 'ZEROG_GRAVITY', 'ZEROG_ROOM')]
        self.assertEqual(len(zero_g), 3)
        cmd(w, 'CAMERA', 'ZEG1')
        self.assertEqual([p.suspended for p in zero_g], [False] * 3)
        cmd(w, 'CAMERA', 'TUB1')
        self.assertEqual([p.suspended for p in zero_g], [True] * 3)
        cmd(w, 'CAMERA', 'ZEG3')
        self.assertEqual([p.suspended for p in zero_g], [False] * 3)


class ChaosLoad(unittest.TestCase):
    def test_the_cell_block_at_ce33_as_sampled_live(self):
        """The flags the original showed on camera CE33 after a new game (dosbox_live `processes`, clock 4438, re/NOTES.md)."""
        w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(w)
        vmmod.load_level(vm, 'CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        w.auto_camera = False
        vm.fire('CHAOS_LOAD')
        cmd(w, 'CAMERA', 'CE33')
        linked = {p.block.name: p for p in vm.procs.values() if p.cameras}
        for name, cameras, paused in (('CELLTWOBARS', ['BLK2', 'BLK3', 'CE12', 'CE21', 'CE22', 'CE23', 'CE24'], True),
                                      ('CELL3_MON', ['CE31', 'CE32', 'CE33'], False),
                                      ('FLICKER_LIGHT', ['BLK1', 'BLK2', 'BLK3', 'BLK4', 'BLK5'], True),
                                      ('BLOCK_DRIP', ['BLK1', 'BLK2', 'BLK3', 'BLK4', 'BLK5'], True),
                                      ('ANIMGUARD', ['GRD2'], True),
                                      ('ANIMCRYO', ['CRY1', 'CRY2', 'CRY3', 'CRY4', 'CRY5'], True)):
            self.assertEqual((linked[name].cameras, linked[name].suspended), (cameras, paused), name)


if __name__ == '__main__':
    unittest.main()
