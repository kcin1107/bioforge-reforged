"""Tests for show.py and the JUMPON watch of vm.py: the FLIC statements, RUNFLIC scenes, JUMPON, FREEZE / THAW, the CAPTUREKEYBOARD hook, ADDKEY and the
front-end functions. The Swift twin is ShowTests.swift (same cases, same numbers).
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_show.py'"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SCRIPT = '''
[ SCN
	00:00 _s = 1
	300:00 _s = 2
]
[ MARK00
	00:00 _m = 1
]
{ JWAIT
	JUMPON USERINTERRUPT HIT
	WAIT 90
	_j = 1
	:HIT
	_n = _n + 1
	WAIT 20
	_j = 3
}
{ JSTART
	JUMPON USERINTERRUPT HIT2
	_j2 = 1
	:HIT2
	_j2 = 2
}
{ JBAD
	JUMPON USERINTERRUPT NOLABEL
	JUMPON NOSUCHVAR HIT3
	JUMPON USERINTERRUPT
	_jb = 1
}
{ JSUSP
	JUMPON USERINTERRUPT HIT4
	LOCALVAR ~0
	~0 = PROCESS LONGWAIT
	SUSPENDWHILE ~0
	_js = 1
	:HIT4
	_js = 2
}
{ LONGWAIT
	WAIT 500
}
{ OTHER
	WAIT 2
	_c = 1
}
{ LATE
	_d = 1
}
{ FRZMAIN
	FREEZE
	_late = PROCESS LATE
	WAIT 10
	THAW
	_z = 1
}
{ GETKEY _KEY _MODIFIERS _MOUSE
	_hk = ~0
	_hm = ~1
	_hs = ~2
}
{ GETESCKEY _KEY _MODIFIERS _MOUSE
	IF ( ~0 == 1 ) THEN
		_UserInterrupt = 1
}
'''


def fresh():
    w = worldmod.World('LANDPAD')
    vm = vmmod.VM(w)
    test_items.script(vm, SCRIPT)
    for k in ('_n', '_j', '_c', '_d', '_z', '_hk', '_hm', '_hs', '_s', '_m', '_j2', '_jb', '_js'):
        vm.globals[k] = 0
    return w, vm


def stmt(w, name, *args):
    w.call('stmt', name, list(args), test_items.stub())


def func(w, name, *args):
    return w.call('func', name, list(args), test_items.stub())


def lifetime(w, vm, *args):
    """RUNFLIC ran inside tick T; its render is this tick's step. -> ticks until the handle is gone."""
    h = func(w, 'RUNFLIC', *args)
    w.step()
    n = 0
    while h in vm.procs and n < 5000:
        vm.tick_once()
        w.step()
        n += 1
    return n


def shown(w):
    return w.flic.index - 1


class Flic(unittest.TestCase):
    def test_intro_space_segment_is_1563_ticks_then_one_frame_3(self):
        w, vm = fresh()
        stmt(w, 'STARTFLIC', 'intro')
        stmt(w, 'SETFLICRATE', 6)
        self.assertEqual(lifetime(w, vm, 'SCN', 521), 1563)
        self.assertEqual((shown(w), sum(w.flic.frame.pixels)), (520, 964686))
        self.assertEqual(lifetime(w, vm, 'SCN', 522), 3)
        self.assertEqual((shown(w), sum(w.flic.frame.pixels)), (521, 3322826))

    def test_default_interval_is_2_and_startflic_resets_it(self):
        w, vm = fresh()
        stmt(w, 'SETFLICRATE', 6)                                              # no flic open: ignored
        stmt(w, 'STARTFLIC', 'intro')
        self.assertEqual(lifetime(w, vm, 'SCN', 10), 10)
        stmt(w, 'SETFLICRATE', 6)
        stmt(w, 'STARTFLIC', 'intro')
        self.assertEqual(lifetime(w, vm, 'SCN', 10), 10)

    def test_nothing_is_drawn_until_runflic_and_the_flic_replaces_the_world(self):
        w, vm = fresh()
        stmt(w, 'STARTFLIC', 'intro')
        for _ in range(5):
            vm.tick_once()
            w.step()
        self.assertEqual((w.flic.index, w.render().sum()), (0, 0))
        func(w, 'RUNFLIC', 'SCN', 10)
        w.step()
        self.assertEqual((shown(w), sum(w.flic.frame.pixels)), (0, 434373))
        self.assertGreater(w.render().sum(), 0)
        func(w, 'FADE', 'HIDE')
        self.assertEqual(w.present_rgb(w.render()).sum(), 0)                   # the palette step applies to the flic
        stmt(w, 'STOPFLIC')
        self.assertIsNone(w.flic)
        stmt(w, 'STOPFLIC')                                                    # safe when nothing is open

    def test_var_mode_follows_the_variable_and_never_goes_back(self):
        w, vm = fresh()
        stmt(w, 'STARTFLIC', 'plt0')
        stmt(w, 'SETFLICRATE', 1)
        h = func(w, 'RUNFLIC', 'SCN', 0, 0, '_plt0_frame')
        got = []
        for v in (0, 3, 1, 7, 7, 5, 47, 100):
            vm.globals['_plt0_frame'] = v
            w.step()
            got.append(shown(w))
        self.assertEqual(got, [0, 3, 3, 7, 7, 7, 47, 47])
        self.assertIn(h, vm.procs)                                             # never finishes by itself

    def test_flicloop_mark_and_back(self):
        w, vm = fresh()
        stmt(w, 'STARTFLIC', 'intro')
        func(w, 'RUNFLIC', 'SCN', 0)
        w.step()
        for _ in range(3):
            vm.tick_once()
            w.step()
        stmt(w, 'FLICLOOP', 'MARK')
        for _ in range(3):
            vm.tick_once()
            w.step()
        self.assertEqual(shown(w), 6)
        stmt(w, 'FLICLOOP', 'BACK')
        self.assertEqual((w.flic.index, sum(w.flic.frame.pixels)), (4, 437470))      # frame 3 is on screen, 4 is next

    def test_scenes_without_a_flic_and_unknown_blocks_end_at_once(self):
        w, vm = fresh()
        h = func(w, 'RUNFLIC', 'MARK00', 0)
        self.assertIn(h, vm.procs)
        vm.tick_once()
        self.assertEqual((h in vm.procs, vm.globals['_m']), (False, 0))
        stmt(w, 'STARTFLIC', 'intro')
        h = func(w, 'RUNFLIC', 'NOSUCHBLOCK')
        self.assertIn(h, vm.procs)
        vm.run_ticks(2)                                                        # dies at its next update (the one after this tick)
        self.assertNotIn(h, vm.procs)

    def test_missing_file_warns_and_playflic_is_a_stub(self):
        w, vm = fresh()
        stmt(w, 'STARTFLIC', 'nosuchshow')
        self.assertEqual((w.flic, len(w.warnings)), (None, 1))
        stmt(w, 'STARTFLIC', 'intro')
        self.assertEqual((func(w, 'PLAYFLIC'), w.flic.index), (0, 0))


class JumpOn(unittest.TestCase):
    def test_a_watch_cancels_the_wait_fires_once_and_is_level_triggered(self):
        w, vm = fresh()
        vm.fire('JWAIT')
        vm.run_ticks(5)
        self.assertEqual(vm.globals['_n'], 0)
        vm.globals['_userinterrupt'] = 1
        vm.tick_once()
        self.assertEqual(vm.globals['_n'], 1)                                  # at once, the WAIT 90 cancelled
        vm.globals['_userinterrupt'] = 0
        vm.globals['_userinterrupt'] = 1                                       # one-shot: not re-armed
        vm.run_ticks(3)
        self.assertEqual(vm.globals['_n'], 1)
        vm.run_ticks(30)
        self.assertEqual((vm.globals['_j'], vm.globals['_userinterrupt']), (3, 1))     # the variable is not reset
        vm.globals['_userinterrupt'] = 1
        vm.fire('JSTART')                                                      # already non-zero when armed
        self.assertEqual(vm.globals['_j2'], 2)

    def test_errors_clear_the_registration(self):
        w, vm = fresh()
        vm.globals['_userinterrupt'] = 1
        vm.fire('JBAD')
        self.assertEqual(vm.globals['_jb'], 1)
        self.assertEqual([x.split('(error ')[1] for x in vm.warnings], ['0x11)', '0x17)', '0x29)'])

    def test_it_removes_the_process_from_the_waiters_of_what_it_waited_on(self):
        w, vm = fresh()
        vm.fire('JSUSP')
        long = next(p for p in vm.procs.values() if p.block.name == 'LONGWAIT')
        self.assertEqual(len(long.waiters), 1)
        vm.globals['_userinterrupt'] = 1
        vm.tick_once()
        self.assertEqual((vm.globals['_js'], long.waiters), (2, []))


class Freeze(unittest.TestCase):
    def test_freeze_suspends_the_existing_processes_and_stops_the_world(self):
        w, vm = fresh()
        vm.fire('OTHER')
        native = vm.timed_handle(3)
        vm.fire('FRZMAIN')                                                     # tick 0
        self.assertTrue(w.frozen)
        self.assertEqual((vm.globals['_d'], vm.globals['_z']), (1, 0))         # a process made after FREEZE runs
        stmt(w, 'CHANGEPALETTE', 5, 5, 5, 2)
        for _ in range(5):
            vm.tick_once()
            w.step()
        self.assertEqual((w.cp, native in vm.procs, vm.globals['_c']), ((5, 5, 5), False, 0))    # the world and its timers stand still
        self.assertEqual(w.game_tick, 0)                                       # the game clock [8330] stands still while frozen
        while vm.globals['_z'] == 0:
            vm.tick_once()
            w.step()
        self.assertEqual((vm.tick, w.frozen, w.game_tick), (11, False, 1))                     # THAW at tick 10, _z the same tick
        n = 0
        while vm.globals['_c'] == 0:
            vm.tick_once()
            n += 1
        self.assertEqual(vm.tick, 13)                                          # its WAIT 2 (due at tick 2) moved later by the 10 frozen ticks: 12


class Keys(unittest.TestCase):
    def test_the_hook_block_runs_per_key_event(self):
        w, vm = fresh()
        stmt(w, 'CAPTUREKEYBOARD', 'GETKEY')
        stmt(w, 'CAPTUREKEYBOARD', 'GETKEY')
        self.assertEqual(len(w.warnings), 1)                                   # already captured (0xd1)
        w.key_event(0x2d, 0xc0)
        self.assertEqual([vm.globals[k] for k in ('_hk', '_hm', '_hs')], [45, 192, 0])
        w.key_event(0, 5)
        self.assertEqual(vm.globals['_hm'], 192)                               # scan code 0: nothing
        stmt(w, 'RELEASEKEYBOARD')
        w.key_event(0x10, 7)
        self.assertEqual(vm.globals['_hk'], 45)

    def test_a_captured_key_is_in_the_key_table_and_not_the_normal_handler(self):
        """ZEROG_TURNING reads ISKEYPRESSED with the keyboard captured: the table comes from the keyboard interrupt (11d8:1561), whoever gets the press."""
        w, vm = fresh()
        stmt(w, 'CAPTUREKEYBOARD', 'GETKEY')
        w.key_event(0x4b)
        proc = types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=None, cur_item=None)
        self.assertEqual(w.call('func', 'ISKEYPRESSED', [0x4b], proc), 1)
        self.assertEqual(w.keys_held, [])                                      # no walk or turn request from it
        w.key_up(0x4b)
        self.assertEqual(w.call('func', 'ISKEYPRESSED', [0x4b], proc), 0)

    def test_esc_through_getesckey_sets_the_interrupt_only_while_captured(self):
        w, vm = fresh()
        w.key_event(1, 0)
        self.assertEqual(vm.globals['_userinterrupt'], 0)
        stmt(w, 'CAPTUREKEYBOARD', 'GETESCKEY')
        w.key_event(0x2d, 0)
        self.assertEqual(vm.globals['_userinterrupt'], 0)
        w.key_event(1, 0)
        self.assertEqual(vm.globals['_userinterrupt'], 1)

    def test_wasaltpressed(self):
        w, vm = fresh()
        self.assertEqual([func(w, 'WASALTPRESSED', m) for m in (0xc0 | 0x80 | 0x40, 0x80, 0x40, 0, 0x0c, 0x30)], [1, 1, 1, 0, 0, 0])

    def test_addkey_is_delivered_at_the_next_step_through_key_event(self):
        w, vm = fresh()
        stmt(w, 'CAPTUREKEYBOARD', 'GETKEY')
        stmt(w, 'ADDKEY', 45, 128, 64)
        self.assertEqual(vm.globals['_hk'], 0)
        w.step()
        self.assertEqual([vm.globals['_hk'], vm.globals['_hm']], [45, 192])

    def test_addkey_esc_reaches_a_running_monitor(self):
        w, vm = fresh()
        stmt(w, 'MON_START', 'PIMM')
        stmt(w, 'ADDKEY', 1)
        w.step()
        self.assertEqual(w.monitor.poll()[0], 'ESCAPE_BUTTON')


class FrontEnd(unittest.TestCase):
    def test_getoptdata_reads_install_opt(self):
        w, vm = fresh()
        self.assertEqual([func(w, 'GETOPTDATA', k) for k in ('LANGUAGE', 'language', 'Soundvol', 'NOSUCHKEY')], [69, 69, 100, 0])

    def test_menu_unmenu_creditsstate_and_exit(self):
        w, vm = fresh()
        stmt(w, 'MENU', 8)
        stmt(w, 'UNMENU')
        self.assertEqual((func(w, 'CREDITSSTATE'), w.exit_requested, w.warnings), (0, False, []))
        stmt(w, 'EXIT')
        self.assertTrue(w.exit_requested)
        self.assertEqual(w.unmodelled, [])


if __name__ == '__main__':
    unittest.main()
