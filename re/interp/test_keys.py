"""Tests for the original key mapping (keys.py) and the world's key-driven player input."""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys  # noqa: E402
import monitor as monitor_mod  # noqa: E402
import options as options_mod  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SHIFT, CTRL, ALT = 0x0c, 0x30, 0xc0


def stub(fig='PLAYER'):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=fig, cur_item=None, handle=0,
                                 waiters=[], goto=None, ended=False, wait_pred=None)


class Mapper(unittest.TestCase):
    def test_normal_mode(self):
        a = lambda s, m=0: keys.action(s, m, False)
        for s in (0x48, 0x47, 0x49):
            self.assertEqual(a(s), ('motion', 'walk', True))
            self.assertEqual(a(s, SHIFT), ('motion', 'run', True))
        self.assertEqual(a(0x4b), ('motion', 'turn_left', True))
        self.assertEqual(a(0x4d, SHIFT), ('motion', 'turn_right_fast', True))
        self.assertEqual(a(0x50), ('motion', 'walk_back', True))
        self.assertEqual(a(0x4f), ('motion', 'sidestep_left', True))
        self.assertEqual(a(0x51), ('motion', 'sidestep_right', True))
        self.assertEqual(a(0x4c), ('oneshot', 'shoot'))
        self.assertIsNone(a(0x01))

    def test_combat_mode(self):
        a = lambda s, m=0, playing=None: keys.action(s, m, True, playing)
        pad = {0x47: '7', 0x48: '8', 0x49: '9', 0x4b: '4', 0x4d: '6', 0x4f: '1', 0x50: '2', 0x51: '3'}
        for s, n in pad.items():
            self.assertEqual(a(s), ('motion', 'atk_M' + n, True))
            self.assertEqual(a(s, CTRL), ('oneshot', 'atk_F' + n))
            self.assertEqual(a(s, ALT), ('oneshot', 'atk_H' + n))
        self.assertEqual(a(0x48, SHIFT), ('motion', 'run', True))
        self.assertEqual(a(0x4c), ('oneshot', 'atk_shoot'))
        self.assertIsNone(a(0x4b, 0, 'ATK_M7'))                       # M4/M6 wait for other attacks / run
        self.assertIsNone(a(0x4d, 0, 'run'))
        self.assertEqual(a(0x4b, 0, 'ATK_M4'), ('motion', 'atk_M4', True))   # its own motion may continue
        self.assertEqual(a(0x4b, 0, 'atk_h4'), ('motion', 'atk_M4', True))

    def test_other_keys(self):
        for c in (False, True):
            self.assertEqual(keys.action(0x2e, 0, c), ('combat_toggle',))
            self.assertEqual(keys.action(0x39, 0, c), ('use',))
            self.assertEqual(keys.action(0x1f, 0, c), ('save',))
            self.assertEqual(keys.action(0x13, 0, c), ('credits',))
            self.assertEqual(keys.action(0x18, 0, c), ('options',))
            self.assertEqual(keys.action(0x26, 0, c), ('load',))
        self.assertIsNone(keys.action(0x1f, ALT, False))                 # Alt+S is ignored
        self.assertEqual(keys.action(0x2d, ALT, False), ('exit',))
        self.assertIsNone(keys.action(0x2d, 0, False))
        self.assertEqual([keys.action(s, 0, False) for s in (0x17, 0x19, 0x20, 0x24)],
                         [('pimm', 'INVENTORY'), ('pimm', ''), ('pimm', 'DIAGNOSTICS'), ('pimm', 'JOURNAL')])
        self.assertIsNone(keys.action(0x17, SHIFT, False))               # PIMM keys ignore modifiers
        self.assertEqual(keys.action(0x33, SHIFT, False), ('gamma', -10))
        self.assertEqual(keys.action(0x34, ALT, False), ('gamma', 10))
        self.assertEqual(keys.action(0x4a, SHIFT, False), ('gamma', -10))
        self.assertEqual(keys.action(0x4e, ALT, False), ('gamma', 10))
        self.assertIsNone(keys.action(0x34, 0, False))
        self.assertEqual(keys.action(0x2f, ALT, False), ('version',))
        self.assertIsNone(keys.action(0x2f, 0, False))

    def test_sdl_table(self):
        self.assertEqual({keys.SDL_TO_PC[s] for s in (82, 96)}, {0x48})
        self.assertEqual(keys.SDL_TO_PC[93], 0x4c)
        self.assertEqual(keys.SDL_MODS[225], SHIFT)
        self.assertEqual([keys.SDL_TO_PC[s] for s in (22, 21, 18, 15, 27)], [0x1f, 0x13, 0x18, 0x26, 0x2d])   # S R O L X


class WorldKeys(unittest.TestCase):
    def setUp(self):
        self.w = w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        vmmod.load_level(self.vm, 'CHAOS')
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        self.lex = w.player()
        self.place(0, 0)

    def place(self, x, y):
        self.lex.pos = np.array([x, y, -7168.0])
        self.lex.set_motion(worldmod.STAND, True)             # (keeps a turning motion's yaw first, FUN_1098_0789)
        self.lex.heading = 0.0
        self.w.select_area(self.lex)                          # Space reads the area a frame last selected
        self.lex.manual_control = False
        # test scaffolding: (0, 0) is not inside any CHAOS room, so with collisions on (flag 0x02 clear, the original's
        # default) the hull would be blocked at once; these tests measure the key-to-motion mapping, not walls
        self.lex.no_collide = True

    def tick(self, n):
        for _ in range(n):
            self.w.step()

    def travel(self, scan, mods=0, ticks=12):
        start = self.lex.pos.copy()
        self.w.key_down(scan, mods)
        self.tick(ticks)
        self.w.key_up(scan)
        return self.lex.pos - start

    def test_forward_and_run(self):
        walk = self.travel(0x48)
        self.assertEqual(self.lex.motion, 'WALK')
        self.assertGreater(float(walk[:2] @ self.lex.forward()), 100)
        self.tick(1)
        self.assertEqual(self.lex.motion, 'STAND')
        self.place(0, 0)
        run = self.travel(0x48, SHIFT)
        self.assertEqual(self.lex.motion, 'RUN')
        self.assertGreater(np.hypot(*run[:2]), np.hypot(*walk[:2]))

    def test_back_and_sidestep(self):
        back = self.travel(0x50)
        self.assertLess(float(back[:2] @ self.lex.forward()), -100)
        self.place(0, 0)
        left = self.travel(0x4f, ticks=38)
        self.assertEqual(self.lex.motion, 'SIDESTEP_LEFT')
        left_vec = np.array([self.lex.forward()[1] * -1, self.lex.forward()[0]])      # forward rotated 90 deg counter-clockwise
        self.assertGreater(float(left[:2] @ left_vec), 100)
        self.place(0, 0)
        right = self.travel(0x51, ticks=32)
        self.assertEqual(self.lex.motion, 'SIDESTEP_RIGHT')
        self.assertLess(float(right[:2] @ left_vec), -100)

    def ticks_for(self, frames):
        return -(-frames * self.lex.frame_duration() // worldmod.CLOCK_PER_TICK)

    def test_turning(self):
        # TURN_* are turning motions: each cycle adds the root limb's yaw (TURN_RIGHT ends at -64 units) to the heading
        # (FUN_10a0_1c83), and a release keeps the yaw reached so far (FUN_1098_0789).
        self.w.key_down(0x4d)
        self.tick(1)
        self.assertEqual((self.lex.motion, self.lex.heading), ('TURN_RIGHT', 0.0))
        self.tick(self.ticks_for(len(self.lex.frames)) - 1)
        self.assertEqual((self.lex.motion, self.lex.idx, self.lex.heading), ('TURN_RIGHT', 0, 90.0))
        self.tick(self.ticks_for(3))
        yaw = self.lex.frames[self.lex.idx][2][0][2]
        self.w.key_up(0x4d)
        self.tick(1)
        self.assertEqual((self.lex.motion, self.lex.heading), ('STAND', 90.0 - yaw * 45 / 32))
        self.place(0, 0)
        self.w.key_down(0x4b, SHIFT)
        self.tick(1)
        self.assertEqual(self.lex.motion, 'TURN_LEFT_FAST')
        self.tick(self.ticks_for(len(self.lex.frames)) - 1)
        self.assertEqual(self.lex.heading, -90.0)

    def test_scripted_go_keeps_ownership(self):
        self.lex.go = {'target': np.array([500.0, 0.0]), 'kind': 'WALK', 'motion': 'WALK', 'z': -7168.0}
        self.w.key_down(0x4d)
        self.tick(2)
        self.assertEqual(self.lex.heading, 0.0)

    def test_combat_toggle_calls_block(self):
        self.w.key_down(0x2e)
        self.tick(1)
        self.assertTrue(self.lex.combat)
        self.w.key_up(0x2e)
        self.w.key_down(0x2e)
        self.tick(1)
        self.assertFalse(self.lex.combat)
        self.assertEqual([k[2] for k in self.w.key_log if k[1] == 'combat'], [True, False])

    def test_the_combat_key_plays_enter_combat_then_the_combat_idle(self):
        self.w.key_down(0x2e)
        self.tick(1)
        self.w.key_up(0x2e)
        self.assertEqual(self.lex.motion, 'ENTER_COMBAT')                # LEX_ENTER_COMBAT, AI_LEX.scr:344; live: ENTER_COMBAT, then atk_stand
        self.tick(60)
        self.assertEqual(self.lex.motion, 'ATK_STAND')

    def test_combat_attacks(self):
        self.lex.combat = True
        self.w.key_down(0x47)
        self.tick(2)
        self.assertEqual((self.lex.motion, self.lex.loop), ('ATK_M7', True))
        self.w.key_up(0x47)
        self.tick(1)
        self.assertEqual(self.lex.motion, 'ATK_STAND')                   # FUN_1098_0745: the combat idle
        for scan, mods, name in ((0x4f, CTRL, 'ATK_F1'), (0x51, ALT, 'ATK_H3')):
            self.place(0, 0)
            self.lex.combat = True
            self.w.key_down(scan, mods)
            self.tick(2)
            self.w.key_up(scan)
            self.assertEqual((self.lex.motion, self.lex.loop), (name, False))
            self.tick(60)                       # plays out, then returns to the combat idle on the next input tick
            self.assertEqual(self.lex.motion, 'ATK_STAND')

    def test_use_calls_use_block(self):
        self.place(20800, -61000)                                    # inside the DR7_BTN trigger box
        self.w.key_down(0x39)
        self.tick(1)
        self.assertEqual([k[2] for k in self.w.key_log if k[1] == 'use'], ['DR7_BTN_USE'])
        self.w.key_up(0x39)
        self.place(0, 0)
        self.w.key_log.clear()
        self.w.key_down(0x39)
        self.tick(1)
        self.assertEqual(self.w.key_log, [])                         # nothing within reach

    def test_use_with_held_item(self):
        self.place(6400, -24300)                                     # CELPAN
        p = stub('PLAYER')
        self.w.call('stmt', 'CREATEITEM', ['FORK'], p)
        self.w.call('stmt', 'PLACEITEM', ['RTHAND'], p)
        self.w.key_down(0x39)
        self.tick(1)
        self.assertEqual([k[2] for k in self.w.key_log if k[1] == 'use'], ['CELPAN_FORK_USE'])

    def test_pimm_and_logged_keys(self):
        self.w.key_down(0x17)
        for _ in range(80):                                          # PIMM's `MOTION LOOK_AT_PIM FREEZE` blocks until the motion has played
            self.vm.tick_once()
            if self.w.monitor is not None:                           # (no world step once it is up: that clears the held keys)
                break
            self.w.step()
        self.assertIsNotNone(self.w.monitor)
        self.assertEqual(self.w.monitor.name, 'PIMM')
        self.w.key_down(0x48)                                        # ignored while the monitor runs
        self.assertEqual(self.w.keys_held, [0x17])
        self.w.key_up(0x17)
        self.w.monitor_key('ESCAPE')
        self.vm.run_ticks(4)
        self.assertIsNone(self.w.monitor)
        for scan, mods in ((0x34, ALT), (0x2f, ALT)):
            self.w.key_down(scan, mods)
        self.assertEqual([k[1:] for k in self.w.key_log], [('gamma', 10), ('version', None)])

    def test_keys_are_ignored_while_pimm_holds_lex(self):
        # FUN_10a8_0541: with +0x229 raised (PIMM_INVENTORY's AI OFF) only S is answered. A second I while the wrist rises started a
        # second PIMM_INVENTORY whose AI OFF outlived the page: Lex could not move after Escape.
        def run(n):
            for _ in range(n):
                self.vm.tick_once()
                self.w.step()
        self.w.key_down(0x17)
        self.w.key_up(0x17)
        run(5)
        self.assertEqual(self.lex.hold, 1)
        self.assertIsNone(self.w.monitor)
        self.w.key_down(0x17)
        self.w.key_up(0x17)
        for _ in range(80):
            if self.w.monitor is not None:
                break
            run(1)
        self.assertEqual(sum(str(getattr(p.block, 'name', p.block)).upper() == 'PIMM_INVENTORY' for p in self.vm.procs.values()), 1)
        self.w.monitor_key('ESCAPE')
        run(10)
        self.assertIsNone(self.w.monitor)
        self.assertEqual(self.lex.hold, 0)


class HotkeyTests(unittest.TestCase):
    """R / O / S / L / Alt+X open the options dialog through the FUN_10a8_02cc guard."""
    def setUp(self):
        self.w = w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        vmmod.load_level(self.vm, 'CHAOS')
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        self.lex = w.player()
        w.objects_for(self.lex)[0] = 100                            # alive
        w.call('stmt', 'CREATEFIGURE', ['NURSEBOT'], stub(None))
        self.other = w.figures['NURSEBOT']

    def press(self, scan, mods=0):
        self.w.key_down(scan, mods)
        self.w.key_up(scan)

    def opened(self):
        o = self.w.options
        return None if o is None or o.closed else (o.screen, o.flags)

    def subtitles(self):
        return [t[3] for t in self.w.subtitle_log if 'Save temporarily disabled' in t[3]]

    def test_each_key_opens_its_screen(self):
        for scan, mods, want in ((0x18, 0, 'main'), (0x13, 0, 'credits'), (0x1f, 0, 'save'), (0x26, 0, 'load'),
                                 (0x2d, ALT, 'confirm')):
            self.press(scan, mods)
            self.assertEqual(self.opened()[0], want, hex(scan))
            self.w.options.closed = True
        self.press(0x2d, ALT)
        self.assertEqual(self.w.options.screen, 'confirm')
        self.assertEqual(self.w.options.flags, options_mod.EXIT)
        self.assertEqual([k[1] for k in self.w.key_log], [])

    def test_alt_v_shows_the_version_subtitle_once(self):
        self.press(0x2f, ALT)
        self.assertEqual([t[3] for t in self.w.subtitle_log],
                         ['BioForge  ver f1.01~(C) 1994, 1995 Origin Systems'])
        self.press(0x2f, ALT)                                        # refused while the caption is still showing
        self.assertEqual(len(self.w.subtitle_log), 1)
        self.assertIsNone(self.opened())                             # not an options action

    def test_alt_v_without_alt_does_nothing(self):
        self.press(0x2f, 0)
        self.assertEqual(self.w.subtitle_log, [])

    def test_flags(self):
        for scan, flags in ((0x18, 1), (0x13, 0x10), (0x1f, 8), (0x26, 4)):
            self.press(scan)
            self.assertEqual(self.opened()[1], flags)
            self.w.options.closed = True

    def test_alt_s_and_alt_x_rules(self):
        self.press(0x1f, ALT)
        self.assertIsNone(self.opened())
        self.press(0x2d)                                            # X alone does nothing
        self.assertIsNone(self.opened())

    def test_load_conditions(self):
        self.w.objects_for(self.lex)[0] = 0                         # dead player
        self.press(0x26)
        self.assertIsNone(self.opened())
        self.w.objects_for(self.lex)[0] = 5
        self.w.save_busy = True                                     # a save or load is running
        self.press(0x26)
        self.assertIsNone(self.opened())
        self.press(0x2d, ALT)
        self.assertIsNone(self.opened())
        self.w.save_busy = False
        self.w.monitor = monitor_mod.Monitor('PIMM', lambda *a: 0)
        self.press(0x26)                                            # a monitor is open: L needs Alt
        self.assertIsNone(self.opened())
        self.press(0x26, ALT)
        self.assertEqual(self.opened()[0], 'load')

    def test_player_handler_keys_are_ignored_while_a_monitor_runs(self):
        self.w.monitor = monitor_mod.Monitor('PIMM', lambda *a: 0)
        for scan in (0x18, 0x13, 0x1f):
            self.press(scan)
        self.assertIsNone(self.opened())
        self.press(0x2d, ALT)                                       # the global hook still answers
        self.assertEqual(self.opened()[0], 'confirm')

    def test_keys_ignored_while_the_dialog_is_open(self):
        self.press(0x18)
        self.press(0x13)
        self.assertEqual(self.opened(), ('main', 1))

    def test_invulnerable_visible_living_figure_refuses_save(self):
        self.other.invulnerable = True
        self.w.objects_for(self.other)[0] = 10
        self.press(0x1f)
        self.assertIsNone(self.opened())
        self.assertEqual(len(self.subtitles()), 1)
        self.assertEqual(self.w.options, None)

    def test_invulnerable_visible_living_figure_disables_save_in_the_main_panel(self):
        self.other.invulnerable = True
        self.w.objects_for(self.other)[0] = 10
        self.press(0x18)
        self.assertEqual(self.opened(), ('main', 1 | options_mod.NO_SAVE))
        self.assertEqual(len(self.subtitles()), 1)
        self.assertEqual(self.w.options.monitor.el('SAVX').state, monitor_mod.NOT_SELECTABLE)
        self.assertIsNone(self.w.option_activate('SAVX'))
        self.assertEqual(self.w.options.screen, 'main')
        self.assertEqual(self.w.options.monitor.el('LODX').state, 1)
        self.w.option_activate('LODX')
        self.assertEqual(self.w.options.screen, 'load')

    def test_other_flags_open_with_no_save(self):
        self.other.invulnerable = True
        self.w.objects_for(self.other)[0] = 10
        self.press(0x13)
        self.assertEqual(self.opened(), ('credits', 0x10 | options_mod.NO_SAVE))
        self.assertEqual(self.subtitles(), [])

    def test_hidden_or_dead_invulnerable_figure_does_not_block(self):
        self.other.invulnerable = True
        self.other.hidden = True
        self.w.objects_for(self.other)[0] = 10
        self.assertTrue(self.w.save_safe())
        self.other.hidden = False
        self.w.objects_for(self.other)[0] = 0
        self.assertTrue(self.w.save_safe())
        self.press(0x1f)
        self.assertEqual(self.opened()[0], 'save')
        self.assertEqual(self.subtitles(), [])

    def test_invulnerable_and_predicates_follow_the_statements(self):
        p = stub('NURSEBOT')
        self.w.call('stmt', 'INVULNERABLE', ['ON'], p)
        self.assertTrue(self.other.invulnerable)
        self.assertEqual(self.w.call('func', 'ISINVULNERABLE', [], p), 1)
        self.assertEqual(self.w.call('func', 'ISHIDDEN', [], p), 0)
        self.w.call('stmt', 'INVULNERABLE', ['OFF'], p)
        self.assertEqual(self.w.call('func', 'ISINVULNERABLE', [], p), 0)

    def test_captured_keyboard_blocks_saving(self):
        self.w.call('stmt', 'CAPTUREKEYBOARD', ['GETANYKEY'], stub())
        self.assertFalse(self.w.save_safe())
        self.press(0x1f)
        self.assertIsNone(self.opened())
        self.assertEqual(len(self.subtitles()), 1)
        self.press(0x18)                                            # the player handler ignores everything else
        self.assertIsNone(self.opened())
        self.w.call('stmt', 'RELEASEKEYBOARD', [], stub())
        self.assertTrue(self.w.save_safe())
        self.press(0x1f)
        self.assertEqual(self.opened()[0], 'save')

    def test_forced_reload_blocks_saving(self):
        self.w.forcing_reload = True
        self.press(0x1f)
        self.assertIsNone(self.opened())
        self.assertEqual(len(self.subtitles()), 1)
        self.w.forcing_reload = False
        self.vm.globals['_forcing_reload'] = 1                      # the script variable counts too
        self.assertTrue(self.w.forcing_reload_on())
        self.press(0x1f)
        self.assertIsNone(self.opened())
        self.vm.globals['_forcing_reload'] = 0
        self.press(0x1f)
        self.assertEqual(self.opened()[0], 'save')

    def test_grenade_blocks_saving(self):
        self.w.call('stmt', 'CREATEITEM', ['GRENADE'], stub())
        self.assertFalse(self.w.save_safe())

    def test_save_busy_suppresses_cannot_save(self):
        self.other.invulnerable = True
        self.w.objects_for(self.other)[0] = 10
        self.w.save_busy = True
        self.press(0x1f)
        self.assertEqual(self.subtitles(), [])

    def test_mon_code_goes_through_the_guard(self):
        self.other.invulnerable = True
        self.w.objects_for(self.other)[0] = 10
        self.w.call('stmt', 'MON_CODE', [options_mod.SAVE], stub())
        self.assertIsNone(self.opened())
        self.assertEqual(len(self.subtitles()), 1)
        self.w.call('stmt', 'MON_CODE', [options_mod.DEFAULT], stub())
        self.assertEqual(self.opened(), ('main', 1 | options_mod.NO_SAVE))
        self.w.call('stmt', 'MON_CODE', [options_mod.AUDIO], stub())   # a dialog is already up
        self.assertEqual(self.opened()[0], 'main')

    def test_is_exit_mon_running_blocks(self):
        self.vm.globals['_isexitmonrunning'] = 1
        self.press(0x18)
        self.assertIsNone(self.opened())


if __name__ == '__main__':
    unittest.main()
