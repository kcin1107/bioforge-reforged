"""Tests for sound samples (formats/sound.py) and their engine binding: re/.venv/bin/python -I -m unittest discover -s re/interp -p 'test_*.py'"""
import math
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
import movie  # noqa: E402
import sound  # noqa: E402

SND = os.path.join(worldmod.parse.ROOT, 'game', 'app', 'Bioforge', 'SOUND')


def proc():
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig='PLAYER', cur_item=None, handle=0, waiters=[])


class Format(unittest.TestCase):
    def test_all_languages(self):
        for lang in 'EFG':
            sm = sound.Samples(os.path.join(SND, lang + 'SAMPLES.FLX'))
            self.assertEqual((len(sm), len(sm.names)), (717, 717))
            self.assertEqual(sm.check(), ([], []))
            self.assertTrue(all(sm.get(i).rate in (11111, 11025) for i in range(len(sm))))

    def test_names_match_ids(self):
        sm = sound.Samples(os.path.join(SND, 'ESAMPLES.FLX'))
        ids = sound.load_sound_ids()
        self.assertEqual(sm.names[ids['_escher_vox_scream']], 'scream2a')
        self.assertEqual(sm.names[ids['_acid_bubbles']], 'bubble2a')

    def test_duration_and_pitch(self):
        sm = sound.Samples(os.path.join(SND, 'ESAMPLES.FLX'))
        s = sm.get(0)
        self.assertAlmostEqual(sm.duration(0), len(s.pcm) / s.rate)
        self.assertLess(sm.duration(0, -1024), sm.duration(0))          # negative pitch plays faster


class Engine(unittest.TestCase):
    def setUp(self):
        self.w = worldmod.World('LANDPAD')
        self.vm = vmmod.VM(self.w)
        self.sm, self.ids = worldmod.sound_bank()

    def call(self, name, *args, kind='func'):
        return self.w.call(kind, name, list(args), proc())

    def run_ticks(self, n):
        for _ in range(n):
            self.vm.tick_once()

    def looped(self):
        return next(i for i in range(len(self.sm)) if self.sm.get(i).loop_end > 0)

    def test_sound_handle_lifetime_and_log(self):
        i = self.ids['_escher_vox_scream']
        h = self.call('SOUND', '_ESCHER_VOX_SCREAM', 100)
        n = math.ceil(self.sm.duration(i) * vmmod.TPS)
        self.assertEqual(self.w.sound_log, [(0, i, 'scream2a', 100, 0, h)])
        self.run_ticks(n - 1)
        self.assertIn(h, self.vm.procs)
        self.run_ticks(3)                                               # timed_handle expires one tick late (generator exhaustion)
        self.assertNotIn(h, self.vm.procs)

    def test_volume_clamped_and_pitch(self):
        i = self.ids['_escher_vox_scream']
        h = self.call('SOUND', '_escher_vox_scream', 999, -1024)
        self.assertEqual(self.w.sound_log[0][3:5], (255, -1024))
        self.run_ticks(math.ceil(self.sm.duration(i, -1024) * vmmod.TPS) + 2)
        self.assertNotIn(h, self.vm.procs)
        self.assertLess(math.ceil(self.sm.duration(i, -1024) * vmmod.TPS), math.ceil(self.sm.duration(i) * vmmod.TPS))

    def test_unknown_sound_keeps_default_lifetime_without_log(self):
        h = self.call('SOUND', '_no_such_sound')
        self.assertIn(h, self.vm.procs)
        self.assertEqual(self.w.sound_log, [])

    def test_stopsound_and_loop(self):
        i = self.looped()
        name = next(k for k, v in self.ids.items() if v == i)
        once = self.call('SOUND', name)                                 # 1028:09d3 clears the loop flag: a sample with loop points still plays once
        h = self.call('AMBIENT', name)                                  # 1028:0f0a sets it
        self.run_ticks(3000)
        self.assertNotIn(once, self.vm.procs)
        self.assertIn(h, self.vm.procs)                                 # looped: valid until stopped
        self.call('STOPSOUND', h, kind='stmt')
        self.assertNotIn(h, self.vm.procs)
        self.assertEqual(self.w.sound_stops, [(self.vm.tick, h)])

    def test_stopallsounds(self):
        a = self.call('SOUND', '_acid_bubbles')
        b = self.call('SOUND', name_of(self.ids, self.looped()))
        self.call('STOPALLSOUNDS', kind='stmt')
        self.assertFalse({a, b} & set(self.vm.procs))
        self.assertEqual(sorted(h for _, h in self.w.sound_stops), sorted([a, b]))

    def long_sound(self):
        return name_of(self.ids, self.looped())

    def fill(self, priority=1):
        return [self.worldplay(priority) for _ in range(8)]

    def worldplay(self, priority):
        return self.w.play_sound(self.ids[self.long_sound()], 255, 0, priority=priority)

    def test_ninth_sound_steals_slot_zero(self):
        hs = self.fill()
        self.run_ticks(2)
        h9 = self.call('SOUND', self.long_sound())
        self.assertNotIn(hs[0], self.vm.procs)
        self.assertIn(h9, self.vm.procs)
        self.assertEqual(self.w.sound_stops, [(2, hs[0])])
        self.assertEqual(self.w.voices[0][0], h9)
        self.assertEqual(self.call('ISHANDLEPLAYING', hs[0]), 0)
        self.assertEqual(self.call('ISSOUNDPLAYING', self.long_sound()), 1)

    def test_free_slot_reused_after_natural_end(self):
        hs = self.fill()
        self.call('STOPSOUND', hs[3], kind='stmt')
        short = self.call('SOUND', '_escher_vox_scream')
        self.assertEqual(self.w.voices[3][0], short)
        self.run_ticks(math.ceil(self.sm.duration(self.ids['_escher_vox_scream']) * vmmod.TPS) + 2)
        self.assertNotIn(short, self.vm.procs)
        h = self.call('SOUND', '_escher_vox_scream')                         # slot 3 is the first free one again
        self.assertEqual(self.w.voices[3][0], h)
        self.assertEqual(self.w.sound_stops, [(0, hs[3])])

    def test_priority_drop_and_steal(self):
        hs = self.fill(priority=2)
        n = len(self.w.sound_log)
        self.assertEqual(self.call('SOUND', self.long_sound()), 0)      # script sounds use priority 1
        self.assertEqual(len(self.w.sound_log), n)
        self.assertEqual(self.w.sound_drops, [(0, self.ids[self.long_sound()], self.sm.get(self.ids[self.long_sound()]).name)])
        self.assertTrue(all(h in self.vm.procs for h in hs))
        h = self.worldplay(2)                                           # equal priority steals slot 0
        self.assertNotIn(hs[0], self.vm.procs)
        self.assertEqual(self.w.voices[0], (h, 2))

    def test_stopsound_frees_slot(self):
        hs = self.fill()
        self.call('STOPSOUND', hs[5], kind='stmt')
        h = self.call('SOUND', self.long_sound())
        self.assertEqual(self.w.voices[5][0], h)
        self.assertIn(hs[0], self.vm.procs)
        self.assertEqual(self.w.sound_drops, [])

    def test_getsoundhandle_returns_live_sound(self):
        h = self.call('SOUND', '_acid_bubbles')
        self.assertEqual(self.call('GETSOUNDHANDLE', '_acid_bubbles'), h)
        self.assertEqual(self.call('ISSOUNDPLAYING', '_acid_bubbles'), 1)

    # ---- positional volume
    def place(self, cam_pos, fig_pos, name='PLAYER'):
        """Camera 'T' at cam_pos (None = no camera), figure `name` at fig_pos. -> proc whose current figure it is"""
        self.w.cameras = {} if cam_pos is None else {'T': {'pos': np.array(cam_pos, float)}}
        self.w.camera = None if cam_pos is None else 'T'
        self.w.default_camera = None
        self.w.auto_camera = False
        self.w.figure(name).pos = np.array(fig_pos, float)
        p = proc()
        p.cur_fig = name
        return p

    def vol_at(self, d, script_volume=255):
        p = self.place((0, 0, 0), (d, 0, 0))
        n = len(self.w.sound_log)
        h = self.w.call('func', 'SOUND', ['_acid_bubbles', script_volume], p)
        self.assertEqual(len(self.w.sound_log), n + 1)
        self.vm.finish(self.vm.procs[h])
        self.w.voices = [None] * 8
        return self.w.sound_log[-1][3]

    def test_positional_volume_formula(self):
        for d, v in [(0, 255), (127, 255), (2175, 255), (2176, 226), (128 * 20, 163), (128 * 32, 64), (128 * 32 + 127, 64),
                     (128 * 64, 16), (128 * 255, 1)]:
            self.assertEqual(self.vol_at(d), v, d)
        self.assertEqual(self.vol_at(4096, 10), 64)             # the script volume is ignored
        self.assertEqual(self.vol_at(int(math.hypot(3000, 4000)) , 255), 65536 // (39 * 39))   # d = 5000 (3-4-5 triangle)

    def test_distance_is_3d_euclidean(self):
        p = self.place((0, 0, 0), (2000, 2000, 2000))           # d = 3464 -> q = 27
        h = self.w.call('func', 'SOUND', ['_acid_bubbles'], p)
        self.assertEqual(self.w.sound_log[-1][3], 65536 // 27 ** 2)

    def test_no_camera_halves_script_volume(self):
        p = self.place(None, (100, 0, 0))
        self.w.call('func', 'SOUND', ['_acid_bubbles', 200], p)
        self.w.call('func', 'SOUND', ['_acid_bubbles'], p)
        self.assertEqual([e[3] for e in self.w.sound_log], [100, 127])

    def test_no_current_figure_is_not_positional(self):
        p = proc()
        p.cur_fig = None
        self.place((0, 0, 0), (9000, 0, 0))
        h = self.w.call('func', 'SOUND', ['_acid_bubbles', 100], p)
        self.assertEqual(self.w.sound_log[0][3], 100)
        self.assertEqual(self.w.sound_volumes, [])

    def test_unresolved_current_figure_is_error_without_sound(self):
        p = self.place((0, 0, 0), (100, 0, 0))
        p.cur_fig = 'NOSUCHFIG'
        self.assertEqual(self.w.call('func', 'SOUND', ['_acid_bubbles'], p), -1)
        self.assertEqual(self.w.sound_log, [])
        self.assertNotIn('NOSUCHFIG', self.w.figures)
        self.assertTrue(any('NOSUCHFIG' in x for x in self.w.warnings))

    def test_volume_follows_moving_figure_and_camera(self):
        p = self.place((0, 0, 0), (1000, 0, 0))
        h = self.w.call('func', 'SOUND', ['_escher_vox_scream'], p)
        self.assertEqual(self.w.sound_volumes, [(0, h, 255)])
        self.run_ticks(1); self.w.step()
        self.assertEqual(self.w.sound_volumes, [(0, h, 255)])   # unchanged: nothing logged
        self.w.figure('PLAYER').pos[0] = 4096
        self.run_ticks(1); self.w.step()
        self.assertEqual(self.w.sound_volumes[-1], (self.vm.tick, h, 64))
        self.w.cameras['T']['pos'][0] = 4096 - 128 * 8          # the camera moves too: q = 8
        self.run_ticks(1); self.w.step()
        self.assertEqual(self.w.sound_volumes[-1][2], 255)
        self.assertEqual(self.w.sound_log[0][3], 255)           # sound_log keeps the initial volume

    def test_finished_sound_stops_being_tracked(self):
        p = self.place((0, 0, 0), (1000, 0, 0))
        h = self.w.call('func', 'SOUND', ['_escher_vox_scream'], p)
        self.run_ticks(math.ceil(self.sm.duration(self.ids['_escher_vox_scream']) * vmmod.TPS) + 3)
        self.w.step()
        self.assertEqual(self.w.sound_pos, {})

    def test_mix_audio_applies_volume_changes(self):
        i = self.ids['_escher_vox_scream']
        self.w.sound_log.append((0, i, 'x', 255, 0, 7))
        loud = movie.mix_audio(self.w, 30).astype(float)
        self.w.sound_volumes = [(0, 7, 255), (10, 7, 0)]        # silent from tick 10 (a one-tick ramp down)
        quiet = movie.mix_audio(self.w, 30).astype(float)
        n10 = 10 * movie.AUDIO_RATE // 30
        self.assertTrue(np.array_equal(loud[:8 * n10 // 10], quiet[:8 * n10 // 10]))
        self.assertEqual(float(np.abs(quiet[n10:]).max()), 0.0)
        self.assertGreater(float(np.abs(loud[n10:]).max()), 0)

    # ---- subtitles
    def sub(self, *args, p=None):
        return self.w.call('func', 'SUBTITLE', list(args), p or proc())

    def test_subtitle_lifetime_formula(self):
        i = self.ids['_escher_vox_scream']
        n = len(self.sm.get(i).pcm)
        text = 'Noooo...!'
        h = self.sub('_escher_vox_scream', 0x30, text + '/FNoonn.../GNeiiin')
        life = n * 30 // 11025 + len(text)                      # English segment only
        self.assertEqual(self.w.subtitle_log, [(0, h, 0x30, text, life)])
        self.run_ticks(life - 1)
        self.assertIn(h, self.vm.procs)
        self.run_ticks(3)
        self.assertNotIn(h, self.vm.procs)

    def test_subtitle_unresolved_sound_lifetime_is_text_length(self):
        h = self.sub('_no_such_sound', 5, 'x' * 40)
        self.assertEqual(self.w.subtitle_log[0][3:], ('x' * 40, 40))
        self.assertEqual(self.w.sound_log, [])
        self.run_ticks(42)
        self.assertNotIn(h, self.vm.procs)

    def test_subtitle_defaults_and_priority(self):
        self.sub('_acid_bubbles', 0, 'a')
        self.sub('_acid_bubbles', 0, 0, 'b')
        self.sub('_acid_bubbles', 7, 90, 'c')
        self.assertEqual([e[2] for e in self.w.subtitle_log], [0x75, 0x75, 7])
        self.assertEqual([e[3] for e in self.w.sound_log], [255, 255, 90])
        self.assertEqual({v[1] for v in self.w.voices if v}, {2})
        self.assertEqual(self.w.sound_volumes, [])              # non-positional even with a current figure

    def test_subtitle_replaces_previous(self):
        h1 = self.sub('_escher_vox_scream', 1, 'x' * 300)
        self.run_ticks(4)
        h2 = self.sub('_acid_bubbles', 1, 'second')
        self.assertNotIn(h1, self.vm.procs)
        self.assertEqual(self.w.subtitle_log[0][4], 4)           # the first ended at the replacement tick
        self.assertEqual(self.w.subtitle_log[1][1], h2)
        voice1 = self.w.sound_log[0][5]
        self.assertNotIn(voice1, self.vm.procs)                 # 10e8:08a4 stops its voice

    def test_minorsubtitle_skipped_while_subtitle_is_live(self):
        mp = lambda *a: self.w.call('func', 'MINORSUBTITLE', list(a), proc())
        h1 = mp('_acid_bubbles', 1, 'first')                    # none live: acts like SUBTITLE
        self.assertGreater(h1, 0)
        self.assertEqual(mp('_acid_bubbles', 1, 'second'), 0)
        self.assertEqual(len(self.w.subtitle_log), 1)
        self.assertEqual(len(self.w.sound_log), 1)
        self.run_ticks(len('first') + len(self.sm.get(self.ids['_acid_bubbles']).pcm) * 30 // 11025 + 3)
        self.assertGreater(mp('_acid_bubbles', 1, 'third'), 0)

    def test_voice_drop_does_not_end_subtitle(self):
        self.fill(priority=3)                                   # all voices busy with higher priority
        h = self.sub('_escher_vox_scream', 1, 'x' * 100)
        self.assertEqual(self.w.sound_drops[-1][1], self.ids['_escher_vox_scream'])
        self.assertIn(h, self.vm.procs)
        self.assertEqual(self.w.subtitle_log[0][1], h)

    def test_music_log(self):
        self.call('MUSIC', 31, kind='stmt')
        self.run_ticks(5)
        self.call('MUSIC', -1, kind='stmt')
        self.assertEqual(self.w.music_log, [(0, 31), (5, -1)])
        self.assertEqual(self.w.current_music, -1)

    def test_mix_audio(self):
        i = self.ids['_escher_vox_scream']
        self.call('SOUND', '_escher_vox_scream')
        pcm = movie.mix_audio(self.w, 30)
        self.assertEqual(len(pcm), movie.AUDIO_RATE)
        self.assertGreater(int(np.abs(pcm).max()), 0)
        self.assertEqual(pcm.dtype, np.int16)


def name_of(ids, i):
    return next(k for k, v in ids.items() if v == i)


if __name__ == '__main__':
    unittest.main()
