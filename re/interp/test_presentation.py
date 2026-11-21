"""Tests for presentation.py: DEBUG / DEBUGINFO, CHANGEPALETTE, FADE, RUMBLE, CAPTION and SET_PTR_*. The Swift twin is PresentationTests.swift
(same cases, same numbers).  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_presentation.py'"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import presentation  # noqa: E402
import settings  # noqa: E402
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SCRIPT = '''
{ FADEWAIT
	_f = 1
	SUSPENDWHILE FADE DOWN 5
	_f = 2
}
{ CAPWAIT
	_c = 1
	CAPTION "abc" PAUSE
	_c = 2
}
'''
VISION = 'Your vision begins to blur... /FVotre vue commence... /GAlles verschwimmt...'


def fresh(gamma=30):
    """A LANDPAD world with a VM that has the test script blocks; gamma 30 (offset 0) unless given."""
    w = worldmod.World('LANDPAD')
    vm = vmmod.VM(w)
    test_items.script(vm, SCRIPT)
    w.gamma = gamma
    return w, vm


def stmt(w, name, *args):
    w.call('stmt', name, list(args), test_items.stub())


def fade(w, *args):
    return w.call('func', 'FADE', list(args), test_items.stub())


def six(v8):
    return (int(v8) * 63 + 254) // 255


def eight(v6):
    return v6 * 255 // 63


def shown(w):
    """The 6-bit channels the DAC shows for a source entry of 63 on every channel."""
    return [six(c) for c in presentation.present_palette(np.array([[255, 255, 255]]), w.gamma, w.cp, w.pal_fade)[0]]


def settle(vm):
    """The statement ran inside tick T; this finishes T, so the next tick_once is the Fade process's first step."""
    vm.tick_once()


class DebugNoOps(unittest.TestCase):
    def test_debug_and_debuginfo_are_modelled_and_silent(self):
        w, vm = fresh()
        stmt(w, 'DEBUG', 'Cannot find Fluffy!', 'CONTINUE')
        stmt(w, 'DEBUG', 'NEVER')
        stmt(w, 'DEBUG', 13)
        stmt(w, 'DEBUGINFO')
        self.assertEqual(w.unmodelled, [])
        self.assertEqual(w.warnings, [])
        self.assertEqual([e[3] for e in w.log], ['DEBUG', 'DEBUG', 'DEBUG', 'DEBUGINFO'])


class Palette(unittest.TestCase):
    def test_without_changepalette_or_fade_it_is_the_gamma_lut(self):
        ramp = np.arange(256)
        pal = np.stack([ramp, ramp[::-1], ramp // 2], -1)
        for g in (0, 30, 50, 100):
            lut = np.array(settings.gamma_lut(g))
            np.testing.assert_array_equal(presentation.present_palette(pal, g), lut[pal])

    def test_changepalette_numbers(self):
        def out(g, cp, r, gr, b):
            return [six(c) for c in presentation.present_palette(np.array([[eight(r), eight(gr), eight(b)]]), g, cp)[0]]
        self.assertEqual(out(30, (20, 20, 20), 10, 30, 50), [30, 50, 63])
        self.assertEqual(out(30, (30, 30, 30), 63, 0, 0), [63, 30, 30])
        self.assertEqual(out(30, (0, 0, 8), 10, 10, 10), [10, 10, 18])
        self.assertEqual(out(30, (-1, -1, -1), 0, 1, 63), [0, 0, 62])
        self.assertEqual(out(50, (20, 20, 20), 20, 0, 0), [46, 26, 26])        # gamma 50 is +6

    def test_fade_scales_before_the_offset_and_black_ignores_it(self):
        one = np.array([[255, 255, 255]])
        self.assertEqual([six(c) for c in presentation.present_palette(one, 50, (0, 0, 0), 0)[0]], [6, 6, 6])
        self.assertEqual([six(c) for c in presentation.present_palette(one, 50, (9, 9, 9), 'black')[0]], [0, 0, 0])
        self.assertEqual([six(c) for c in presentation.present_palette(one, 30, (0, 0, 0), 128)[0]], [31, 31, 31])


class ChangePalette(unittest.TestCase):
    def tinted(self, w, ticks):
        """After each of `ticks` world steps: is a CHANGEPALETTE offset in force for the frame drawn then?"""
        seen = []
        for _ in range(ticks):
            w.step()
            seen.append(w.cp != (0, 0, 0))
        return seen

    def test_a_flash_shows_one_frame_and_d_ticks_show_d_frames(self):
        w, vm = fresh()
        stmt(w, 'CHANGEPALETTE', 20, 20, 20, 1)
        self.assertEqual(self.tinted(w, 3), [True, False, False])
        stmt(w, 'CHANGEPALETTE', 10, 0, 0, 3)
        self.assertEqual(self.tinted(w, 5), [True, True, True, False, False])

    def test_zero_and_negative_are_persistent_and_a_new_one_replaces(self):
        w, vm = fresh()
        stmt(w, 'CHANGEPALETTE', 0, 0, 8, 0)
        self.assertEqual(self.tinted(w, 40), [True] * 40)
        stmt(w, 'CHANGEPALETTE', -1, -1, -1, -1)
        self.assertEqual((w.cp, self.tinted(w, 40)), ((-1, -1, -1), [True] * 40))
        stmt(w, 'CHANGEPALETTE', 4, 0, 0, 999)
        self.assertEqual(w.cp, (4, 0, 0))                                      # replaced, not added
        self.assertEqual(shown(w), [63, 63, 63])                               # 63 + 4 clamps
        stmt(w, 'CHANGEPALETTE', -4, 0, 0, 0)
        self.assertEqual(shown(w), [59, 63, 63])

    def test_setting_the_gamma_cancels_it(self):
        w, vm = fresh()
        stmt(w, 'CHANGEPALETTE', 10, 10, 10, 0)
        w.apply_gamma(40)
        self.assertEqual((w.cp, self.tinted(w, 2)), ((0, 0, 0), [False, False]))


class Fade(unittest.TestCase):
    def ramp(self, w, vm, ticks, at):
        out = {}
        for k in range(1, ticks + 1):
            vm.tick_once()
            if k in at:
                out[k] = shown(w)[0]
        return out

    def test_fade_up_60(self):
        w, vm = fresh()
        self.assertEqual((fade(w, 'HIDE'), w.pal_state, shown(w)), (0, 2, [0, 0, 0]))
        h = fade(w, 'UP', 60)
        self.assertEqual(w.pal_state, 3)
        self.assertIn(h, vm.procs)
        settle(vm)
        self.assertEqual(self.ramp(w, vm, 59, (1, 15, 30)), {1: 0, 15: 15, 30: 31})
        self.assertIn(h, vm.procs)                                              # N - 1 ticks: still valid
        vm.tick_once()
        self.assertEqual((shown(w), w.pal_state, h in vm.procs), ([63, 63, 63], 0, False))

    def test_fade_down_65_ends_on_the_offset_only_palette(self):
        w, vm = fresh(gamma=50)
        h = fade(w, 'DOWN', 65)
        self.assertEqual(w.pal_state, 1)
        settle(vm)
        self.assertEqual(self.ramp(w, vm, 64, (1, 32, 64)), {1: 63, 32: 37, 64: 6})              # gamma 50 adds +6 to 62 (clamped), 31, 0
        self.assertIn(h, vm.procs)
        vm.tick_once()
        self.assertEqual((shown(w), w.pal_state, h in vm.procs), ([6, 6, 6], 2, False))
        self.assertEqual(fade(w, 'DOWN', 5), 0)                                  # already hidden: a no-op
        fade(w, 'SHOW')
        self.assertEqual((shown(w), w.pal_state), ([63, 63, 63], 0))

    def test_fade_down_65_with_gamma_30(self):
        w, vm = fresh()
        fade(w, 'DOWN', 65)
        settle(vm)
        self.assertEqual(self.ramp(w, vm, 64, (1, 32, 64)), {1: 62, 32: 31, 64: 0})

    def test_no_ops_default_length_and_unknown_word(self):
        w, vm = fresh()
        self.assertEqual((fade(w, 'UP', 30), w.pal_state), (0, 0))               # normal: UP does nothing
        h = fade(w, 'DOWN')
        self.assertEqual(fade(w, 'DOWN', 30), 0)                                 # fading down: DOWN does nothing
        settle(vm)
        for _ in range(19):
            vm.tick_once()
        self.assertIn(h, vm.procs)
        vm.tick_once()
        self.assertEqual(h in vm.procs, False)                                   # omitted n = 20
        self.assertEqual(w.warnings, [])
        self.assertEqual((fade(w, 'SIDEWAYS'), fade(w)), (0, 0))
        self.assertEqual(len(w.warnings), 2)

    def test_only_the_newest_process_writes(self):
        w, vm = fresh()
        fade(w, 'DOWN', 10)
        fade(w, 'SHOW')
        fade(w, 'DOWN', 4)
        settle(vm)
        vm.tick_once()
        self.assertEqual(w.pal_fade, 192)                                        # the 4-step process: (3 << 8) // 4, not (9 << 8) // 10

    def test_suspendwhile_waits_for_the_process(self):
        w, vm = fresh()
        vm.fire('FADEWAIT')
        settle(vm)
        for _ in range(5):
            vm.tick_once()
        self.assertEqual(vm.globals['_f'], 1)
        vm.tick_once()                                                           # the fade ended last walk: the waiter goes on in this one (1238:077f)
        self.assertEqual(vm.globals['_f'], 2)


class Rumble(unittest.TestCase):
    def test_rumble_3_sequence(self):
        w, vm = fresh()
        stmt(w, 'RUMBLE', 3)
        got = []
        for _ in range(10):
            w.rumble_step()
            got.append((w.rumble_x, w.rumble_y))
        self.assertEqual(got, [(-1, 1), (-1, 1), (-2, 2), (-1, 1), (-1, 1), (-2, 0), (-3, 0), (-4, -1), (-2, -3), (0, -5)])

    def test_forms(self):
        w, vm = fresh()
        stmt(w, 'RUMBLE', 3)
        w.rumble_step()
        stmt(w, 'RUMBLE', 'MOVE', 0, 0, 0, 0)                                    # only the amplitude: x and y stay
        self.assertEqual((w.rumble_amp, w.rumble_x, w.rumble_y), (0, -1, 1))
        stmt(w, 'RUMBLE', 'MOVE', 2, -1, 300, 0)
        self.assertEqual((w.rumble_amp, w.rumble_x, w.rumble_y, w.rumble_xp, w.rumble_yp), (-1, 2, -1, 44, 0))
        w.rumble_step()
        self.assertEqual((w.rumble_x, w.rumble_y), (2, -1))                      # MOVE mode never moves on its own
        stmt(w, 'RUMBLE', 5)
        self.assertEqual(w.rumble_amp, 5)
        stmt(w, 'RUMBLE')
        self.assertEqual((w.rumble_amp, w.rumble_x, w.rumble_y, w.rumble_vx, w.rumble_vy), (0, 0, 0, 0, 0))

    def test_shift_frame(self):
        a = (np.arange(24).reshape(6, 4) + 1).astype(np.uint8)
        # y = 1: row 0 revealed (fill 99); source rows 4, 2, 0 use x = 1 and rows 5, 3, 1 use xp = -1; revealed columns keep the old pixels
        self.assertEqual(presentation.shift_frame(a, 1, 1, -1, 99).tolist(),
                         [[99, 99, 99, 99], [5, 1, 2, 3], [6, 7, 8, 12], [13, 9, 10, 11], [14, 15, 16, 20], [21, 17, 18, 19]])
        # y = -2: rows 4 and 5 revealed; source rows 2, 4 use x = 0 and the ones between xp = 1
        self.assertEqual(presentation.shift_frame(a, 0, -2, 1, 99).tolist(),
                         [[9, 10, 11, 12], [5, 13, 14, 15], [17, 18, 19, 20], [13, 21, 22, 23], [99, 99, 99, 99], [99, 99, 99, 99]])

    def test_present_rgb_shifts_when_rumbling_and_skips_the_stopped_state(self):
        w, vm = fresh()
        frame = np.zeros((200, 320, 3), np.uint8)
        frame[:, 0] = 255
        np.testing.assert_array_equal(w.present_rgb(frame), np.array(settings.gamma_lut(30), np.uint8)[frame])
        stmt(w, 'RUMBLE', 'MOVE', 2, 0, 2, 0)
        out = w.present_rgb(frame)
        self.assertEqual((out[100, 0, 0], out[100, 2, 0], out[100, 3, 0]), (255, 255, 0))      # the old column stays, the line moved by +2


class PaletteCut(unittest.TestCase):
    """10e8:1dcc: a source palette more than 12 apart (|dR|+|dG|+|dB|, raw 6-bit, entries 0..254) from the installed one is presented black once."""
    FRAME = np.full((200, 320, 3), 200, np.uint8)

    def src(self, value=10):
        return np.full((256, 3), value, np.int32)

    def test_a_big_change_presents_one_black_frame_then_the_picture(self):
        w, vm = fresh()
        self.assertTrue(w.present_rgb(self.FRAME, self.src(10)).any())              # the first palette is installed as it comes
        cut = w.present_rgb(self.FRAME, self.src(20))                                 # 3 * 10 = 30 > 12
        self.assertFalse(cut.any())
        self.assertTrue(w.present_rgb(self.FRAME, self.src(20)).any())

    def test_a_small_change_does_not(self):
        w, vm = fresh()
        w.present_rgb(self.FRAME, self.src(10))
        self.assertTrue(w.present_rgb(self.FRAME, self.src(14)).any())                # 3 * 4 = 12 is not above 12
        s = self.src(14)
        s[5] += (7, 0, 0)                                                              # one entry by 7 is fine too
        self.assertTrue(w.present_rgb(self.FRAME, s).any())
        s[5] += (13, 0, 0)                                                             # 13 from the installed one is
        self.assertFalse(w.present_rgb(self.FRAME, s).any())

    def test_entry_255_is_not_compared(self):
        w, vm = fresh()
        w.present_rgb(self.FRAME, self.src(10))
        s = self.src(10)
        s[255] = 63
        self.assertTrue(w.present_rgb(self.FRAME, s).any())

    def test_a_fade_suppresses_it_and_the_installed_palette_waits(self):
        w, vm = fresh()
        w.present_rgb(self.FRAME, self.src(10))
        w.pal_state = 1                                                                # FADE DOWN running
        self.assertTrue(w.present_rgb(self.FRAME, self.src(40)).any())
        w.pal_state = 0                                                                # the fade ended: the pending palette meets the old one
        self.assertFalse(w.present_rgb(self.FRAME, self.src(40)).any())
        self.assertTrue(w.present_rgb(self.FRAME, self.src(40)).any())

    def test_loadlevel_leaves_the_black_palette_installed(self):
        w, vm = fresh()
        w.present_rgb(self.FRAME, self.src(10))
        stmt(w, 'LOADLEVEL', 'LANDPAD')                                                # 1130:147c: 1a9e(0, 0), an all-black pending palette
        self.assertFalse(w.pal_installed.any())
        self.assertFalse(w.present_rgb(self.FRAME, self.src(10)).any())                # even a palette equal to the old one meets black
        self.assertTrue(w.present_rgb(self.FRAME, self.src(10)).any())

    def test_a_camera_cut_between_very_different_rooms_in_to_rgb(self):
        import play
        w, vm = fresh()
        w.render = lambda indexed=False: self.FRAME
        w.credits_rolling = lambda: False
        names = sorted(f[:-4] for f in os.listdir(worldmod.ROOMS) if f.endswith('.CAM'))
        pals = {n: play.six_bit(play.room_palette(n)) for n in names[:60]}
        pairs = [(a, b) for a in pals for b in pals if int(np.abs(pals[a][:255] - pals[b][:255]).sum(1).max()) > 12]
        similar = [(a, b) for a in pals for b in pals if a < b and int(np.abs(pals[a][:255] - pals[b][:255]).sum(1).max()) <= 12]
        a, b = pairs[0]
        w.current_camera = lambda: a
        self.assertTrue(play.to_rgb(w).any())
        w.current_camera = lambda: b
        self.assertFalse(play.to_rgb(w).any())                                         # the cut frame is black
        self.assertTrue(play.to_rgb(w).any())                                          # the next shows the picture
        if similar:
            c, d = similar[0]
            w.current_camera = lambda: c
            play.to_rgb(w)
            play.to_rgb(w)
            w.current_camera = lambda: d
            self.assertTrue(play.to_rgb(w).any())


class Caption(unittest.TestCase):
    def test_sprintf_reads_16_bit_words(self):
        self.assertEqual(presentation.sprintf16('Dist: %d', [7]), 'Dist: 7')
        self.assertEqual(presentation.sprintf16('Escher Id: %d %d %d %d %d', [1, 2, 3, 4, 5]), 'Escher Id: 1 0 2 0 3')
        self.assertEqual(presentation.sprintf16('%d %u %x %c %%', [-2, -2, 255, 65]), '-2 65535 fffe \xff %')
        self.assertEqual(presentation.sprintf16('%ld', [-70000]), '-70000')
        self.assertEqual(presentation.sprintf16('[%3d][%-3d][%03d]', [5, 5, 5]), '[  5][0  ][005]')

    def test_language_filter(self):
        self.assertEqual(presentation.caption_text(VISION), 'Your vision begins to blur... ')
        self.assertEqual(presentation.caption_text("/!Caynan's id changed to 12345."), "Caynan's id changed to 12345.")
        self.assertEqual(presentation.caption_text('Yep'), 'Yep')
        self.assertEqual(presentation.caption_text('/FBonjour/EHello/GHallo'), 'Hello')

    def test_lifetime_is_7_per_character_in_60_hz_ticks(self):
        got = []
        for args in ((VISION,), ('abc',), ('Dist: %d', 7)):
            w, vm = fresh()
            stmt(w, 'CAPTION', *args)
            (tick, _, colour, text, end), = w.subtitle_log
            got.append((text, colour, end - tick))
        self.assertEqual(got, [('Your vision begins to blur... ', 0x75, 105), ('abc', 0x75, 11), ('Dist: 7', 0x75, 25)])

    def test_a_new_caption_replaces_the_old_one(self):
        w, vm = fresh()
        stmt(w, 'CAPTION', VISION)
        vm.run_ticks(10)
        stmt(w, 'CAPTION', 'abc')
        first, second = w.subtitle_log
        self.assertEqual((first[4], second[0], second[4] - second[0]), (10, 10, 11))
        self.assertNotIn(first[1], vm.procs)

    def test_a_caption_shows_with_subtitles_off(self):
        """10d0:16cb -> 10b0:0f48 never reads the subtitles switch [50bc]; only SUBTITLE does (10e8:0529)."""
        w, vm = fresh()
        w.settings.subtitles = False
        stmt(w, 'CAPTION', 'abc')
        self.assertEqual(w.active_subtitle(vm.tick), (0x75, 'abc'))
        w.subtitle(('_pim_beep_5', 0x75, 0xff, 'spoken'))
        self.assertIsNone(w.active_subtitle(vm.tick))

    def test_a_new_subtitle_stops_the_old_voice(self):
        """10e8:0529 -> vtable +8 = 10e8:08a4 stops the old subtitle's sound if it is still playing."""
        w, vm = fresh()
        w.subtitle(('_pim_beep_5', 0x75, 0xff, 'one two three four five six'))
        voice = w.subtitle_voice
        self.assertIn(voice, vm.procs)
        w.subtitle(('_pim_beep_5', 0x75, 0xff, 'next'))
        self.assertNotIn(voice, vm.procs)
        self.assertIn(w.subtitle_voice, vm.procs)

    def test_pause_blocks_the_caller_until_it_ends(self):
        w, vm = fresh()
        vm.fire('CAPWAIT')
        self.assertEqual(vm.globals['_c'], 1)
        vm.run_ticks(11)
        self.assertEqual(vm.globals['_c'], 1)
        vm.run_ticks(2)
        self.assertEqual(vm.globals['_c'], 2)

    def test_warnings_and_drops(self):
        w, vm = fresh()
        stmt(w, 'CAPTION')
        self.assertEqual((len(w.warnings), len(w.subtitle_log)), (1, 0))
        stmt(w, 'CAPTION', 'x' * 351)
        self.assertEqual(len(w.subtitle_log), 0)
        stmt(w, 'CAPTION', 'x' * 350)
        self.assertEqual(len(w.subtitle_log), 1)
        stmt(w, 'CAPTION', 'abc', 'CONTINUE')                                    # a word other than PAUSE: warns, still shows, never waits
        self.assertEqual((len(w.warnings), len(w.subtitle_log)), (2, 2))


class PointerSetup(unittest.TestCase):
    def test_set_ptr_is_a_silent_no_op_before_mon_start_then_stored(self):
        w, vm = fresh()
        stmt(w, 'SET_PTR_PRESS_TIME', 2, 5, 2)
        stmt(w, 'SET_PTR_MOVEMENT', 360, 1)
        self.assertEqual((w.warnings, w.unmodelled, w.monitor), ([], [], None))
        stmt(w, 'MON_START', 'PIMM')
        self.assertEqual((w.monitor.ptr_press_time, w.monitor.ptr_movement), ((14, 5, 14), (320, 2)))
        stmt(w, 'SET_PTR_PRESS_TIME', 2, 5, 2)
        stmt(w, 'SET_PTR_MOVEMENT', 360, 1)
        self.assertEqual((w.monitor.ptr_press_time, w.monitor.ptr_movement), ((2, 5, 2), (360, 1)))
        stmt(w, 'MON_START', 'PIMM')                                             # every MON_START restarts at the defaults
        self.assertEqual(w.monitor.ptr_press_time, (14, 5, 14))


if __name__ == '__main__':
    unittest.main()
