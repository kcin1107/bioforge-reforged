"""Tests for audio.py: the voice statements, REPLACESOUND, the OVERTIME ramps and the camera / room ambient loops. The Swift twin is
AudioTests.swift (same cases, same numbers).  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_audio.py'"""
import hashlib
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import movie  # noqa: E402
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SCREAM = '_ESCHER_VOX_SCREAM'      # sample 0: 16054 samples at 11111 Hz, one pass 44 ticks


def proc():
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig='PLAYER', cur_item=None, handle=0, waiters=[])


class Base(unittest.TestCase):
    level, camera = 'LANDPAD', None

    def setUp(self):
        self.w = worldmod.World(self.level, self.camera)
        self.vm = vmmod.VM(self.w)
        vmmod.load_level(self.vm, self.level)
        self.sm, self.ids = worldmod.sound_bank()

    def stmt(self, name, *args):
        return self.w.call('stmt', name, list(args), proc())

    def func(self, name, *args):
        return self.w.call('func', name, list(args), proc())

    def run_ticks(self, n):
        for _ in range(n):
            self.vm.tick_once()

    def alive(self, h):
        return h in self.vm.procs

    def vols(self, h):
        return [(t, v) for t, hh, v in self.w.sound_volumes if hh == h]

    def rates(self, h):
        return [(t, r) for t, hh, r in self.w.sound_rates if hh == h]


class VoiceStatements(Base):
    def test_setvolume_clamps_unsigned(self):
        h = self.func('SOUND', SCREAM, 100)
        self.stmt('SETVOLUME', h, 300)
        self.run_ticks(1)
        self.stmt('SETVOLUME', h, -1)
        self.run_ticks(1)
        self.stmt('SETVOLUME', h, 20)
        self.assertEqual(self.vols(h), [(0, 255), (1, 255), (2, 20)])
        self.assertEqual(self.w.voice_state[h].level, 20)

    def test_setvolume_same_tick_logs_both(self):
        h = self.func('SOUND', SCREAM, 100)
        self.stmt('SETVOLUME', h, 10)
        self.stmt('SETVOLUME', h, 30)
        self.assertEqual(self.vols(h), [(0, 10), (0, 30)])           # both are logged, the mixers keep the last

    def test_dead_unknown_and_skipped_handles_do_nothing(self):
        h = self.func('SOUND', SCREAM, 100)
        self.run_ticks(60)
        self.assertFalse(self.alive(h))
        for bad in (h, 0, -1, 9999, 'x'):
            self.stmt('SETVOLUME', bad, 50)
            self.stmt('SETPITCH', bad, 5000)
            self.stmt('ADDTOPITCH', bad, 5)
        self.assertEqual((self.w.sound_volumes, self.w.sound_rates, self.w.warnings), ([], [], []))

    def test_positional_handle_gets_the_positional_value_back(self):
        w = self.w
        self.stmt('CREATEFIGURE', 'LEX', 'PLAYER')
        lex = w.player()
        w.set_pos(lex, [0.0, 0.0, 0.0], raw=True)
        h = w.play_sound(0, fig=lex)
        start = w.sound_pos[h][1]
        self.stmt('SETVOLUME', h, 10)
        self.assertEqual((w.voice_state[h].level, w.sound_pos[h]), (10, (lex.name, 10)))
        w.sound_pos[h] = (lex.name, 10)
        self.run_ticks(1)
        w.refresh_sound_volumes()
        self.assertEqual(start, 0)                          # the figure is far from the camera
        self.assertEqual(self.vols(h), [(0, 0), (0, 10), (1, 0)])   # start value, SETVOLUME, then the refresh logs the rule's value

    def test_setpitch_retimes_the_handle(self):
        h = self.func('SOUND', SCREAM, 100)
        self.assertEqual(self.w.voice_state[h].rate, 11111)
        self.stmt('SETPITCH', h, 5555)                     # ceil(16054 * 30 / 5555) = 87
        self.assertEqual(self.rates(h), [(0, 5555)])
        self.run_ticks(87)
        self.assertTrue(self.alive(h))
        self.run_ticks(1)
        self.assertFalse(self.alive(h))

    def test_setpitch_midway(self):
        h = self.func('SOUND', SCREAM, 100)
        self.run_ticks(10)
        self.stmt('SETPITCH', h, 5555)                     # 10 * 11111 played; ceil((481620 - 111110) / 5555) = 67 more
        self.run_ticks(66)
        self.assertTrue(self.alive(h))                     # tick 76 done; wake = 77
        self.run_ticks(2)
        self.assertFalse(self.alive(h))

    def test_setpitch_zero_never_ends_and_a_later_rate_resumes(self):
        h = self.func('SOUND', SCREAM, 100)
        self.stmt('SETPITCH', h, 0)
        self.run_ticks(500)
        self.assertTrue(self.alive(h))
        self.stmt('SETPITCH', h, 11111)
        self.run_ticks(46)
        self.assertFalse(self.alive(h))

    def test_addtopitch_wraps_u16(self):
        h = self.func('SOUND', SCREAM, 100)
        self.stmt('ADDTOPITCH', h, -20000)
        self.stmt('ADDTOPITCH', h, 20000)
        self.assertEqual(self.rates(h), [(0, 56647), (0, 11111)])
        self.assertEqual(self.w.voice_state[h].rate, 11111)

    def test_mixer_follows_the_rate_and_the_volume_log(self):
        h = self.func('SOUND', SCREAM, 200)
        self.run_ticks(10)
        self.stmt('SETPITCH', h, 0)                        # rate 0 holds the source position from tick 10 on
        self.stmt('SETVOLUME', h, 100)
        self.assertEqual(self.w.sound_volumes, [(10, h, 100)])
        mixed = movie.mix_audio(self.w, 60)
        f10 = round(10 / 30 * movie.AUDIO_RATE)
        self.assertGreater(np.abs(mixed[:f10]).sum(), 0)
        self.assertEqual(len(set(mixed[f10 + movie.AUDIO_RATE // 30 + 2:].tolist())), 1)     # held after the one-tick volume ramp
        self.assertGreater(np.abs(mixed[f10 + 3:f10 + 20]).sum(), 0)


    def test_mixer_piecewise_rate_digest(self):
        h = self.func('SOUND', SCREAM, 200)
        self.run_ticks(10)
        self.stmt('SETPITCH', h, 5555)
        self.run_ticks(5)
        self.stmt('SETPITCH', h, 0)
        self.stmt('SETVOLUME', h, 100)
        self.run_ticks(3)
        self.stmt('SETPITCH', h, 20000)
        mixed = movie.mix_audio(self.w, 60)
        self.assertEqual(hashlib.sha256(mixed.astype('<i2').tobytes()).hexdigest(), '15407c246ae7de44be20b0ef9ff29589557ecd1d7443264ff92d82582f851766')

    def test_released_loop_plays_its_tail(self):
        # rumble1a: 40505 samples at 11025 Hz, loop 7819 + 15313 = 7819..23132. STOPAMBIENT (1000:046f) lets it play on from where it is, without
        # wrapping, to the end of the sample; the handle lives until then.
        h = self.func('AMBIENT', '_quake_1', 200)
        self.run_ticks(30)
        self.stmt('SETPITCH', h, 9000)
        self.run_ticks(60)
        self.stmt('STOPAMBIENT', h)
        self.assertEqual(self.w.sound_releases, [(90, h)])
        # 30 * 11025 + 60 * 9000 = 870750 samples * 30 -> 29025, wrapped: 7819 + 21206 % 15313 = 13712; 26793 left at 9000 Hz = 89.3 ticks
        self.assertEqual(self.vm.procs[h].wake, 90 + 90)
        self.run_ticks(90)
        self.assertTrue(self.alive(h))
        self.run_ticks(1)
        self.assertFalse(self.alive(h))
        mixed = movie.mix_audio(self.w, 300)
        f90 = round(90 / 30 * movie.AUDIO_RATE)
        step = 9000 / movie.AUDIO_RATE
        tail = int((40504 - 13712.0) / step) + 1           # frames from the release to the last sample, about 3 s
        self.assertGreater(np.abs(mixed[f90 + tail - 400:f90 + tail]).sum(), 0)
        self.assertEqual(np.abs(mixed[f90 + tail + 2:]).sum(), 0)
        self.assertEqual(hashlib.sha256(mixed.astype('<i2').tobytes()).hexdigest(), '08b0ecc9160c04201772302e12e6e9b10e9ab1717f90b515a2a138341329a177')


class ReplaceSound(Base):
    def test_replace_chain_and_revert(self):
        w = self.w
        self.assertEqual(w.sound_index('_wind2'), 59)
        self.stmt('REPLACESOUND', '_wind2', '_wind4')
        self.assertEqual((w.sound_index('_wind2'), w.sound_index('_WIND2'), w.sound_index('_wind4')), (61, 61, 61))
        h = self.func('SOUND', '_wind2')
        self.assertEqual(w.sound_log[-1][1], 61)
        self.stmt('REPLACESOUND', '_wind4', 5)             # copy semantics: _wind2 does not follow
        self.assertEqual((w.sound_index('_wind2'), w.sound_index('_wind4')), (61, 5))
        self.stmt('REVERTSOUND', '_wind2')
        self.assertEqual(w.sound_index('_wind2'), 59)
        self.stmt('REVERTSOUND', '_wind4')
        self.assertEqual(w.sound_index('_wind4'), 61)
        self.assertEqual(w.warnings, [])

    def test_out_of_range_override_resolves_to_nothing(self):
        self.stmt('REPLACESOUND', '_wind2', 99999)
        self.assertIsNone(self.w.sound_index('_wind2'))

    def test_non_sound_names_warn(self):
        self.stmt('REPLACESOUND', '_not_a_sound', 1)
        self.stmt('REVERTSOUND', '_not_a_sound')
        self.assertEqual(self.w.warnings, ['REPLACESOUND: not a sound name (error 0x34)', 'REVERTSOUND: not a sound name (error 0x34)'])

    def test_cache_statements_are_no_ops(self):
        self.stmt('BANKINSFX', '_wind2', '_wind3')
        self.stmt('SETSOUNDCACHE', 1000, 100, 1000)
        self.stmt('REVERTSOUNDCACHE')
        self.assertEqual(self.w.warnings, [])
        self.stmt('SETSOUNDCACHE', 1000, 0, 1000)
        self.assertEqual(self.w.warnings, ['SETSOUNDCACHE: needs three non-zero values (error 0x17c)'])


class Ramps(Base):
    def loop(self, volume=0):
        return self.func('AMBIENT', '_wind2', volume)

    def test_absolute_total_and_remainder_on_the_last_tick(self):
        h = self.loop(255)
        r = self.func('MODIFYVOLUMEOVERTIME', h, 100, 0, 30)    # delta -100 over 30: step -3, remainder -10 on tick 30
        self.assertEqual(self.vols(h), [(0, 100)])
        self.run_ticks(30)
        self.assertTrue(self.alive(r))
        self.assertEqual(self.vols(h)[1:4], [(1, 97), (2, 94), (3, 91)])
        self.run_ticks(1)
        self.assertFalse(self.alive(r))
        self.assertEqual((self.vols(h)[-1], self.w.voice_state[h].level), ((30, 0), 0))

    def test_case_a_positive(self):
        h = self.loop(50)
        r = self.func('MODIFYVOLUMEOVERTIME', h, 10, 30)         # relative: +1 every 3 ticks
        self.assertEqual(self.vols(h), [])
        self.run_ticks(31)
        self.assertFalse(self.alive(r))
        self.assertEqual(self.vols(h)[:2], [(3, 51), (6, 52)])
        self.assertEqual(self.w.voice_state[h].level, 60)

    def test_negative_case_a_rises(self):
        h = self.loop(0)
        self.func('MODIFYVOLUMEOVERTIME', h, 65, 0, 120)         # INTRO.scr:416: 65 -> 0 over 120 RISES (period < 0)
        self.run_ticks(121)
        self.assertEqual(self.w.voice_state[h].level, 185)

    def test_relative_form(self):
        h = self.loop(100)
        self.func('MODIFYVOLUMEOVERTIME', h, -40, 20)
        self.run_ticks(21)
        self.assertEqual(self.w.voice_state[h].level, 60)

    def test_error_0x3a_returns_zero(self):
        h = self.loop(100)
        self.assertEqual(self.func('MODIFYVOLUMEOVERTIME', h, 50, 50, 10), 0)
        self.assertEqual(self.func('MODIFYVOLUMEOVERTIME', h, 0, 10), 0)
        self.assertEqual(self.func('MODIFYPITCHOVERTIME', h, 7, 7, 10), 0)
        self.assertEqual(len(self.w.warnings), 2)           # one text per function name

    def test_underflow_wraps_to_255(self):
        h = self.loop(10)
        self.func('MODIFYVOLUMEOVERTIME', h, -20, 10)
        self.run_ticks(11)                                  # 8 6 4 2 0, then -2 wraps to 255, 253 ... 247
        self.assertEqual([v for _, v in self.vols(h)][4:8], [0, 255, 253, 251])
        self.assertEqual(self.w.voice_state[h].level, 247)

    def test_pitch_ramp_logs_rates(self):
        h = self.loop(10)
        r = self.func('MODIFYPITCHOVERTIME', h, 9000, 11000, 20)
        self.assertEqual(self.rates(h), [(0, 9000)])
        self.run_ticks(21)
        self.assertFalse(self.alive(r))
        got = self.rates(h)
        self.assertEqual((len(got), got[1], got[20], got[-1]), (22, (1, 9100), (20, 11000), (20, 11000)))


class Ambient(Base):
    level, camera = 'CHAOS', 'CE33'

    def switch(self, cam):
        self.w.set_camera(cam, 'test')
        self.w.step()

    def test_first_camera_starts_the_room_loop_after_the_frame(self):
        w = self.w
        self.assertTrue(self.vm.globals.get('_ce33_volume') == 80)
        w.set_camera('CE33', 'test')
        self.assertEqual((w.room_ambient, self.func('GETROOMAMBIENT')), (0, -1))
        w.step()
        h = w.room_ambient
        self.assertEqual(w.sound_log, [(0, 8, 'hum1e', 80, 0, h)])
        self.assertEqual((self.func('GETROOMAMBIENT'), self.func('GETCAMERAAMBIENT')), (h, -1))
        self.assertIn(h, w.sound_loops)

    def test_same_room_keeps_the_handle_and_sets_the_cameras_volume(self):
        w = self.w
        self.switch('CE33')
        h = w.room_ambient
        self.switch('CE31')
        self.assertEqual((w.room_ambient, len(w.sound_log)), (h, 1))
        self.assertEqual(self.vols(h), [(0, 0)])             # _CE31_VOLUME: CE3_LOAD (the room event) restarts its 0 -> 100 ramp

    def test_a_different_sample_replaces_the_loop(self):
        w = self.w
        self.switch('CE33')
        old = w.room_ambient
        self.switch('HAL1')
        self.assertEqual(w.sound_stops, [(0, old)])
        self.assertNotEqual(w.room_ambient, old)
        self.assertEqual(w.sound_log[-1][1:4], (17, 'hum3a', 150))

    def test_setvolume_on_the_room_handle_writes_the_variable(self):
        w = self.w
        self.switch('CE33')
        h = w.room_ambient
        self.stmt('SETVOLUME', h, 33)
        self.assertEqual(self.vm.globals['_ce33_volume'], 33)
        self.w.step()
        self.assertEqual(self.vols(h), [(0, 33)])
        self.stmt('SETVOLUME', h, 300)                     # the variable gets the unclamped level
        self.assertEqual(self.vm.globals['_ce33_volume'], 300)

    def test_a_script_assignment_is_applied_next_frame(self):
        w = self.w
        self.switch('CE33')
        h = w.room_ambient
        self.vm.set_global('_ce33_volume', 20)
        self.assertEqual(self.vols(h), [])
        w.step()
        self.assertEqual(self.vols(h), [(0, 20)])

    def test_monitor_running_does_not_set_pending(self):
        w = self.w
        w.monitor = types.SimpleNamespace(update=lambda: None)
        w.set_camera('CE33', 'test')
        w.step()
        self.assertEqual((w.ambient_pending, w.room_ambient, w.sound_log), (False, 0, []))
        w.monitor = None

    def test_volume_ramp_on_the_room_handle_edits_the_variable(self):
        w = self.w
        self.switch('CE33')
        h = w.room_ambient
        self.func('MODIFYVOLUMEOVERTIME', h, 80, 40, 20)   # 80 -> 40 over 20: -2 per tick
        self.assertEqual(self.vm.globals['_ce33_volume'], 80)
        for _ in range(21):
            self.vm.tick_once()
            w.step()
        self.assertEqual((self.vm.globals['_ce33_volume'], w.voice_state[h].level), (40, 40))

    def test_loop_voice_takes_a_slot_and_stops_with_stopallsounds(self):
        w = self.w
        self.switch('CE33')
        h = w.room_ambient
        self.assertIn(h, [v[0] for v in w.voices if v])
        self.stmt('STOPALLSOUNDS')
        self.assertFalse(self.alive(h))


if __name__ == '__main__':
    unittest.main()


class MotionCues(Base):
    """FUN_1088_1854's event walk and FUN_1088_13ea's sound cues (bytes 0xfd..0xf9)."""
    level, camera = 'CHAOS', 'CE31'

    def fig(self, ftype, motion='WALK'):
        return types.SimpleNamespace(name=ftype, type=ftype, motion=motion, mot_id=1, idx=0, pos=np.array([0.0, 0.0, 0.0]))

    def walk(self, fig, frames):
        cues = []
        self.w.motion_cue = lambda f, n: cues.append((f.idx, n))
        for i in frames:
            fig.idx = i
            self.w.event_walk(fig)
        return cues

    def test_caynan_walk_cues_at_the_frame_before_their_frame_byte(self):
        # CAYNAN WALK: 0 1 2 3 4 fc 5 ... 10 fc 11 12 13 fe
        fig = self.fig('CAYNAN')
        self.assertEqual(self.walk(fig, list(range(14)) * 2), [(4, 1), (10, 1), (4, 1), (10, 1)])

    def test_lex_walk_cue_before_frame_zero_and_after_a_wrap(self):
        # MAN WALK: fb 0 1 2 3 4 fc 5 6 fb 7 8 9 10 fc 11 12 13 fe; after the wrap the walk waits for the first frame change
        fig = self.fig('LEX')
        self.assertEqual(self.walk(fig, list(range(14)) + [0, 1, 2]), [(0, 2), (4, 1), (6, 2), (10, 1), (1, 2)])

    def test_skipped_frames_and_a_new_motion(self):
        fig = self.fig('CAYNAN')
        self.assertEqual(self.walk(fig, [0, 7, 12]), [(7, 1), (12, 1)])
        fig.mot_id, fig.motion = 2, 'RECOIL_TL'                # 0 fc 1 ...: the new motion starts its list again
        self.assertEqual(self.walk(fig, [0, 1]), [(0, 1)])

    def test_cue_names_in_order_then_the_cut_form_name(self):
        tried = []
        self.w.sound_index = lambda name: tried.append(name) or None
        self.w.motion_cue(self.fig('CAYNAN', 'ATK_M1'), 2)
        self.assertEqual(tried[:5], ['_ATK_M1_2_CAYNAN_CE31', '_ATK_M1_2_CAYNAN_CE3', '_ATK_M1_2_CE31', '_ATK_M1_2_CE3',
                                     '_ATK_M1_2_CAYNAN'])
        self.assertEqual(tried[5:], ['_ATK_M1_2', '_ATK_M1', '_ATK'])

    def test_cues_play_the_bank_samples_at_priority_0_on_the_figure(self):
        played = []
        self.w.play_sound = lambda idx, volume=255, pitch=0, loop=False, priority=1, fig=None: played.append((idx, priority, fig))
        caynan, lex = self.fig('CAYNAN'), self.fig('LEX')
        self.w.motion_cue(caynan, 1)
        self.w.motion_cue(lex, 1)
        self.w.motion_cue(lex, 2)
        caynan.motion = 'RECOIL_TL'
        self.w.motion_cue(caynan, 1)
        ids = [self.w.sound_index(n) for n in ('_WALK_1_CAYNAN', '_WALK_1_LEX', '_WALK_2_LEX', '_RECOIL_TL_1_CAYNAN')]
        self.assertEqual(played, [(ids[0], 0, caynan), (ids[1], 0, lex), (ids[2], 0, lex), (ids[3], 0, caynan)])

    def test_the_lookup_cuts_long_names_to_24_characters(self):
        tried = []
        self.w.sound_index = lambda name: tried.append(name) or None
        self.assertEqual(self.w.ambient_id('_ABCDEFGHIJKLMNOPQRSTUVWXYZ'), -1)
        self.assertEqual(tried, ['_ABCDEFGHIJKLMNOPQRSTUVW'])
        tried.clear()
        self.w.ambient_id('_ABCDEFGHIJKLMNOPQRSTUVWX')        # 25 characters stay whole
        self.assertEqual(tried, ['_ABCDEFGHIJKLMNOPQRSTUVWX'])
