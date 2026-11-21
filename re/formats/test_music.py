"""Checks for xmi.py / music.py: all 100 XMIDI entries of MUSIC.FLX convert to sane SMFs."""
import os, re, shutil, struct, sys, unittest, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flex import read_flex
import xmi, music, musicseq

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
FLX = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'MUSIC', 'MUSIC.FLX')


def vl(d, p):
    v = 0
    while True:
        b = d[p]; p += 1
        v = (v << 7) | (b & 0x7f)
        if not b & 0x80: return v, p


def check_smf(smf):
    """Independent minimal SMF parser. Returns (length_ticks, n_notes); asserts validity."""
    assert smf[:4] == b'MThd' and struct.unpack_from('>I', smf, 4)[0] == 6
    fmt, ntrk, div = struct.unpack_from('>HHH', smf, 8)
    assert (fmt, ntrk, div) == (0, 1, 60)
    p = 14
    assert smf[p:p + 4] == b'MTrk'
    ln, = struct.unpack_from('>I', smf, p + 4); p += 8
    assert p + ln == len(smf)
    end, t, status, on, notes, ended = p + ln, 0, 0, {}, 0, False
    while p < end:
        assert not ended, "data after End of Track"
        dt, p = vl(smf, p); t += dt
        b = smf[p]
        if b == 0xFF:
            typ = smf[p + 1]; l, q = vl(smf, p + 2); p = q + l
            ended = typ == 0x2F
        elif b in (0xF0, 0xF7):
            l, q = vl(smf, p + 1); p = q + l
        else:
            assert b >= 0x80
            hi, ch = b & 0xF0, b & 15
            if hi in (0xC0, 0xD0): p += 2
            else:
                k, v = smf[p + 1], smf[p + 2]; p += 3
                if hi == 0x90 and v:
                    on[(ch, k)] = on.get((ch, k), 0) + 1; notes += 1
                elif hi == 0x80 or hi == 0x90:
                    assert on.get((ch, k), 0) > 0, "note off without note on"
                    on[(ch, k)] -= 1
    assert ended, "no End of Track"
    assert all(v == 0 for v in on.values()), "hanging notes"
    return t, notes


class MusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d, cls.ents = read_flex(FLX)

    def ent(self, i):
        _, o, s, _ = self.ents[i]
        return self.d[o:o + s]

    def test_all_xmidi_entries_convert(self):
        xm = [i for i, (_, o, s, _) in enumerate(self.ents) if s and self.d[o:o + 4] == b'FORM']
        self.assertEqual(len(xm), 100)
        secs, nseq = [], 0
        for i in xm:
            for j, smf in enumerate(xmi.convert(self.ent(i))):
                t, n = check_smf(smf)
                nseq += 1
                if (i, j) in ((159, 0), (260, 8)):   # alt gmreset / alt im1_t14a: genuinely empty (metas only)
                    self.assertEqual(t, 0); continue
                self.assertGreater(t, 0, f"entry {i}")
                secs.append(t / 120)
        self.assertEqual(nseq, 2 * 49 + 2 * 55)     # 98 songs + 110 transitions
        print(f"\n{len(xm)} entries, {nseq} sequences; duration s: min {min(secs):.1f} "
              f"median {statistics.median(secs):.1f} max {max(secs):.1f}")

    def test_song_table_and_mapping(self):
        songs = music.parse_songs(self.ent(261).decode('latin1'))
        self.assertEqual(len(songs), 49)
        self.assertEqual([s['id'] for s in songs], list(range(49)))
        for k, s in enumerate(songs):
            for e in (k, 128 + k):
                self.assertEqual(len(xmi.sequences(self.ent(e))), 1)
        self.assertEqual(self.ent(0)[:], self.ent(48)[:])      # id 0 and 'M' are both im1_18a
        names = self.ent(257).decode().split()
        self.assertEqual(len(names), 55)
        self.assertEqual(len(xmi.sequences(self.ent(258))), 55)
        self.assertEqual(len(xmi.sequences(self.ent(260))), 55)

    def test_transition_refs_name_their_source_song(self):
        names = self.ent(257).decode().split()
        rows = music.parse_transitions(self.ent(261).decode('latin1'))
        self.assertEqual(len(rows), 39)
        n = 0
        for r in rows:
            num = re.search(r'im1_(\d+)', r['src']).group(1)
            for v in r['values']:
                if v:
                    self.assertTrue(names[v - 1].startswith(f'im1_t{num}'), (r['src'], v))
                    n += 1
        self.assertGreater(n, 900)

    def test_timbre_bank(self):
        t = music.parse_timbres(self.ent(259))
        self.assertGreater(len(t), 128)
        self.assertEqual({x['bank'] for x in t}, {0, 0x7f})
        self.assertTrue(all(x['length'] == 14 for x in t))


class SequencerTests(unittest.TestCase):
    """musicseq.Sequencer against the real tables (song ids = FLX entries; see NOTES "Music state machine")."""
    @classmethod
    def setUpClass(cls):
        cls.lib = musicseq.Library(FLX)

    def run_(self, reqs, end=60.0):
        return musicseq.sequence(self.lib, reqs, end)

    def bar_time(self, song, k):            # seconds of the k-th 0x77 (0-based)
        seq = self.lib.song(song)
        return seq.items[seq.bars[k]][0] / 120

    def poll_after(self, song, k):          # the first music task update after the k-th 0x77 (an update runs before the step)
        seq = self.lib.song(song)
        return (seq.items[seq.bars[k]][0] // 4 + 1) / musicseq.POLL_HZ

    def next_bar(self, song, t):            # index of the first 0x77 at or after t (a request comes before that step's events)
        seq = self.lib.song(song)
        return next(k for k, i in enumerate(seq.bars) if seq.items[i][0] >= t * 120)

    def starts(self, trace):
        return [(e[0], e[2]) for e in trace if e[1] == 'start']

    def test_measure_count_is_the_last_0x77_value(self):
        s = musicseq.Sequencer(self.lib)
        s.request(10, 0.0)                                        # song 10: 0x77 values 1..13, then NEXT back
        self.assertEqual((s.main.measure, s.main.count()), (-1, 0))
        seen = []
        while not any(e[1] == 'loop' for e in s.trace):
            s._step(s.main)
            if s.main.measure not in seen: seen.append(s.main.measure)
        self.assertEqual(seen, [-1] + list(range(1, 13)))       # the loop body ends before the 13th 0x77
        self.assertEqual(s.main.measure, 12)                      # the jump leaves it ...
        while s.main.measure == 12: s._step(s.main)
        self.assertEqual(s.main.seq.items[s.main.idx - 1][1], 'bar')   # ... until the next 0x77 sets it

    def test_transition_value_comes_from_measure_1(self):
        row = self.lib.table[(11, 27)]
        self.assertEqual((row[0], row[4]), (0, 5))                # measure 5 names transition 5, measure 1 a direct switch
        _, tr = self.run_([(0, 11), (12.0, 27)], 30)
        self.assertEqual([r for _, k, *r in tr if k in ('request', 'transition')], [[27, 0]])
        self.assertEqual(self.starts(tr)[-1], (self.poll_after(11, self.next_bar(11, 12.0)), 27))

    def test_same_song_is_noop(self):
        _, tr = self.run_([(0, 10), (3, 10)], 10)
        self.assertEqual(tr, [(0, 'start', 10, 0)])

    def test_no_row_switches_immediately(self):
        self.assertNotIn((10, 3), self.lib.table)
        _, tr = self.run_([(0, 10), (5.0, 3)], 10)
        self.assertEqual(self.starts(tr), [(0, 10), (5.0, 3)])

    def test_value_zero_switches_at_next_bar(self):
        self.assertEqual(self.lib.table[(11, 27)][0], 0)          # measure 1 of im1_1a -> im1_30a: direct
        out, tr = self.run_([(0, 11), (0.5, 27)], 8)
        self.assertEqual(self.starts(tr), [(0, 11), (self.poll_after(11, 1), 27)])
        t = self.poll_after(11, 1)
        ons = [(t2, b) for t2, b in out if b[0] & 0xF0 == 0x90 and b[2]]
        self.assertTrue(any(t2 < t for t2, _ in ons) and any(t2 >= t for t2, _ in ons))

    def test_positive_value_plays_transition_until_the_next_update(self):
        self.assertEqual(self.lib.table[(10, 21)][0], 10)         # measure 1 -> transition #10
        out, tr = self.run_([(0, 10), (12.0, 21)], 30)
        kinds = [(k, *r) for _, k, *r in tr]
        self.assertEqual(kinds[1:3], [('request', 21, 10), ('transition', 10, 'replace', 21)])
        t_tr = [t for t, k, *_ in tr if k == 'transition'][0]
        self.assertEqual(t_tr, self.poll_after(10, self.next_bar(10, 12.0)))
        # the transition stored its count right after its start (0), so the next update ends it (09fc: max(1, n) != 0)
        k = round(t_tr * musicseq.POLL_HZ)
        t_song = (k + 1) / musicseq.POLL_HZ
        self.assertEqual(self.starts(tr)[-1], (t_song, 21))
        self.assertTrue(any(t_tr <= t < t_song and b[0] & 0xF0 == 0x90 for t, b in out))    # its tick 1 notes sound

    def test_negative_value_overlays_transition(self):
        self.assertEqual(self.lib.table[(10, 5)][0], -39)         # '!' flag = negative
        out, tr = self.run_([(0, 10), (1.0, 5)], 20)
        t_over = [t for t, k, *r in tr if k == 'transition'][0]
        self.assertEqual(t_over, self.poll_after(10, 1))
        self.assertEqual([k for _, k, *r in tr if k == 'transition' and r[1] == 'overlay'], ['transition'])
        k = round(t_over * musicseq.POLL_HZ)
        self.assertEqual(self.starts(tr)[-1], ((k + 1) / musicseq.POLL_HZ, 5))
        # song 10 is not stopped by the overlay: its note offs come with the transition's at the next update
        offs = [t for t, b in out if b[0] & 0xF0 == 0x80 and t <= (k + 1) / musicseq.POLL_HZ]
        self.assertFalse(any(t == t_over for t in offs))

    def test_entry_points_alternate(self):
        seq = self.lib.song(13)                                   # im1_14a: markers 0, 126, 1
        self.assertEqual(sorted(seq.markers), [0, 1, 126])
        reqs = [(0, 13), (3, -1), (4, 13), (8, -1), (9, 13), (13, -1), (14, 13)]
        _, tr = self.run_(reqs, 20)
        idx = [i for _, k, n, i in (x for x in tr if x[1] == 'start')]
        self.assertEqual(idx, [0, seq.markers[0], seq.markers[1], seq.markers[0]])   # marker 2 missing -> 0

    def test_infinite_loop_repeats(self):
        out, tr = self.run_([(0, 10)], 60)
        loops = [t for t, k, *_ in tr if k == 'loop']
        self.assertEqual(len(loops), 2)
        self.assertAlmostEqual(loops[0], 2879 / 120, places=3)
        self.assertAlmostEqual(loops[1] - loops[0], 2879 / 120, places=3)

    def test_for_next_count(self):
        evnt = bytes([0xB0, 0x74, 2, 0x90, 60, 100, 5, 5, 0xB0, 0x75, 127, 0xFF, 0x2F, 0])   # FOR 2, one note, NEXT
        seq = musicseq.Seq(evnt)
        lib = type('L', (), dict(songs=[dict(measures=1, loop_measure=0)], table={}, song=lambda self, n: seq))()
        out, _ = musicseq.sequence(lib, [(0, 0)], 10)
        self.assertEqual(sum(1 for _, b in out if b[0] == 0x90), 2)

    @staticmethod
    def sounding(out, t):
        """(channel, key) of the notes on before t and not yet off, in note on order."""
        on = []
        for t2, b in out:
            if t2 >= t: break
            if b[0] & 0xF0 == 0x90 and b[2]: on.append((b[0] & 15, b[1]))
            elif b[0] & 0xF0 == 0x80 or b[0] & 0xF0 == 0x90: on.remove((b[0] & 15, b[1]))
        return on

    def test_stop_silences_everything(self):
        # _XMI_STOP_SEQUENCE ends every queued note and sends no all-notes-off (1fc3, 2021)
        out, tr = self.run_([(0, 10), (3.0, -1)], 10)
        self.assertEqual(tr[-1], (3.0, 'stop'))
        self.assertTrue(all(t <= 3.0 for t, _ in out))
        offs = [(b[0] & 15, b[1]) for t, b in out if t == 3.0 and b[0] & 0xF0 == 0x80]
        self.assertTrue(offs)
        self.assertEqual(sorted(offs), sorted(self.sounding(out, 3.0)))
        self.assertFalse([b for _, b in out if b[0] & 0xF0 == 0xB0 and b[1] == 123])

    def synth(self, evnt, reqs, end=10):
        seq = musicseq.Seq(bytes(evnt))
        lib = type('L', (), dict(songs=[dict(measures=1, loop_measure=0)], table={}, song=lambda self, n: seq))()
        return musicseq.sequence(lib, reqs, end)[0]

    def test_zero_length_note_ends_at_the_next_step(self):
        out = self.synth([0x90, 60, 100, 0, 3, 0xFF, 0x2F, 0], [(0, 0)])
        self.assertEqual(out, [(0.0, bytes([0x90, 60, 100])), (1 / 120, bytes([0x80, 60, 0]))])

    def test_events_keep_file_order_within_a_step(self):
        out = self.synth([0x90, 60, 100, 4, 0xC1, 5, 0xB0, 7, 90, 8, 0xFF, 0x2F, 0], [(0, 0)])
        self.assertEqual([b for t, b in out if t == 0], [bytes([0x90, 60, 100]), bytes([0xC1, 5]), bytes([0xB0, 7, 90])])

    def test_notes_of_one_step_end_in_queue_order(self):
        # A (entry 0, 3 steps), B (entry 1, 10 steps); A ends; C at step 4 takes entry 0 and ends with B at step 10
        out = self.synth([0x90, 60, 100, 3, 0x90, 62, 100, 10, 4, 0x90, 64, 100, 6, 10, 0xFF, 0x2F, 0], [(0, 0)])
        self.assertEqual([b[1] for t, b in out if b[0] == 0x80 and t == 10 / 120], [64, 62])

    def test_entering_at_a_marker_sends_no_earlier_state(self):
        # program 7, marker 0, a note: the second start enters at marker 0 and sends only what follows it (3018)
        out = self.synth([0xC0, 7, 0xB0, 0x78, 0, 0x90, 60, 100, 5, 10, 0xFF, 0x2F, 0], [(0, 0), (1.0, -1), (2.0, 0)], 4)
        self.assertEqual([b for t, b in out if t == 0], [bytes([0xC0, 7]), bytes([0x90, 60, 100])])
        self.assertEqual([b for t, b in out if t == 2.0], [bytes([0x90, 60, 100])])

    def test_resume_resends_controllers_bend_and_program(self):
        out = self.synth([0xB0, 7, 90, 0xE0, 0, 0x50, 0xC0, 9, 0xB0, 64, 127, 0x90, 60, 100, 100, 120, 0xFF, 0x2F, 0],
                         [(0, 0), (0.1, -2), (0.2, -3)], 1)
        self.assertEqual([b for t, b in out if t == 0.1], [bytes([0x80, 60, 0]), bytes([0xB0, 64, 0])])   # 1fc3, 2021
        self.assertEqual([b for t, b in out if t == 0.2],
                         [bytes([0xB0, 7, 90]), bytes([0xB0, 64, 127]), bytes([0xE0, 0, 0x50]), bytes([0xC0, 9])])   # 20c8

    def test_stop_immediately_matches_stop(self):
        out, tr = self.run_([(0, 10), (3.0, -4)], 10)
        self.assertEqual(tr[-1], (3.0, 'stop'))
        self.assertTrue(all(t <= 3.0 for t, _ in out))

    def test_unknown_negative_code_is_ignored(self):
        _, tr = self.run_([(0, 10), (2.0, -9)], 5)
        self.assertEqual(tr[-1], (2.0, 'ignored', -9))

    def test_pause_and_resume(self):
        ref, _ = self.run_([(0, 10)], 8)
        out, tr = self.run_([(0, 10), (2.0, -2), (5.0, -3)], 8)
        self.assertIn((2.0, 'pause'), tr)
        self.assertIn((5.0, 'resume'), tr)
        self.assertEqual(self.starts(tr), [(0, 10)])
        offs = [(b[0] & 15, b[1]) for t, b in out if t == 2.0 and b[0] & 0xF0 == 0x80]
        self.assertEqual(sorted(offs), sorted(self.sounding(out, 2.0)))
        self.assertFalse([1 for t, b in out if 2.0 < t < 5.0 and b[0] & 0xF0 == 0x90])        # silent while paused
        # after the resume the song continues 3 s later than the uninterrupted one
        notes = lambda ev, a, b: [(round(t, 4), bytes(m)) for t, m in ev if a <= t < b and m[0] & 0xF0 == 0x90]
        shifted = [(round(t + 3.0, 4), m) for t, m in notes(ref, 2.0, 5.0)]
        self.assertEqual(notes(out, 5.0, 8.0), shifted)

    def test_resume_without_pause_and_song_request_while_paused(self):
        _, tr = self.run_([(0, 10), (1.0, -3)], 3)
        self.assertNotIn('resume', [e[1] for e in tr])
        _, tr = self.run_([(0, 10), (1.0, -2), (2.0, 13), (4.0, -3)], 6)
        later = [t for t, n in self.starts(tr) if n == 13]
        self.assertTrue(later and later[0] >= 4.0)

    def cc7(self, events):
        return [(t, b[0] & 15, b[2]) for t, b in events if b[0] & 0xF0 == 0xB0 and b[1] == 7]

    def test_music_level_scales_channel_volumes(self):
        ref, _ = self.run_([(0, 10)], 4)
        out, _ = musicseq.sequence(self.lib, [(0, 10)], 4, volume=60)
        raw = self.cc7(ref)
        self.assertTrue(raw)
        self.assertEqual(self.cc7(out), [(t, ch, min(127, v * 60 // 100)) for t, ch, v in raw])  # AIL relative volume: percent
        self.assertEqual([e for e in out if not (e[1][0] & 0xF0 == 0xB0 and e[1][1] == 7)],
                         [e for e in ref if not (e[1][0] & 0xF0 == 0xB0 and e[1][1] == 7)])      # nothing else changes
        full, _ = musicseq.sequence(self.lib, [(0, 10)], 4, volume=100)
        self.assertEqual(full, ref)                                                              # 100 % = unscaled

    def test_level_change_resends_the_channel_volumes(self):
        out, tr = musicseq.sequence(self.lib, [(0, 10)], 6, volume=100, volumes=[(3.0, 50)])
        late = [(t, ch, v) for t, ch, v in self.cc7(out) if t == 3.0]
        base = {ch: v for t, ch, v in self.cc7(musicseq.sequence(self.lib, [(0, 10)], 3.0)[0])}
        self.assertEqual(late, [(3.0, ch, base[ch] * 50 // 100) for ch in sorted(base)])
        self.assertIn((3.0, 'volume', 50), tr)
        self.assertEqual(self.starts(tr), [(0, 10)])                                             # the song continues

    def test_level_zero_stops_and_ignores_requests_until_raised(self):
        out, tr = musicseq.sequence(self.lib, [(0, 10), (4.0, 13)], 9, volume=100, volumes=[(2.0, 0), (6.0, 40)])
        self.assertIn((2.0, 'stop'), tr)
        self.assertIn((4.0, 'disabled', 13), tr)
        self.assertFalse([1 for t, b in out if 2.0 < t < 6.0 and b[0] & 0xF0 == 0x90])          # silent while disabled
        self.assertEqual(self.starts(tr), [(0, 10), (6.0, 10)])                                  # re-enabled: the last song resumes
        self.assertTrue([1 for t, b in out if t > 6.0 and b[0] & 0xF0 == 0x90])

    def test_enabling_without_a_song_starts_the_options_music(self):
        _, tr = musicseq.sequence(self.lib, [], 3, volume=100, volumes=[(1.0, 70)])
        self.assertEqual(self.starts(tr), [(1.0, musicseq.OPTIONS_MUSIC)])
        _, tr = musicseq.sequence(self.lib, [(0, 10), (2.0, -1)], 6, volume=0, volumes=[(3.0, 50)])    # disabled from the start
        self.assertEqual(self.starts(tr), [(3.0, musicseq.OPTIONS_MUSIC)])

    def test_bar_grid_matches_timesig(self):
        for n in (10, 13, 21, 5):
            raw = xmi.sequences(self.lib._ent(n))[0]
            ts = musicseq.bars_from_timesig(raw)
            bars = [self.lib.song(n).items[i][0] for i in self.lib.song(n).bars]
            self.assertLessEqual(max(abs(a - b) for a, b in zip(ts, bars)), 30, n)

    @unittest.skipUnless(shutil.which('swiftc'), 'swiftc not available')
    def test_render_gm(self):
        pcm = musicseq.render([(0, bytes([0x90, 60, 100])), (0.5, bytes([0x80, 60, 0]))], 1.0, rate=22050)
        self.assertEqual(pcm.shape, (22050, 2))
        self.assertGreater(abs(pcm.astype(float)).max(), 500)


if __name__ == '__main__':
    unittest.main()
