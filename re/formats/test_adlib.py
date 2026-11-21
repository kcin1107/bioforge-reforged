"""Checks for adlib.py (AIL AdLib driver port) and opl.py (OPL2 model). The digests are the values the native AdLibTests expect."""
import hashlib, os, shutil, sys, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'interp'))
import adlib, musicseq, opl
import settings

FLX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'game', 'app', 'Bioforge', 'MUSIC', 'MUSIC.FLX')


def digest(writes):
    return hashlib.sha256(''.join(f'{s}:{r:02x}:{v:02x}\n' for s, r, v in writes).encode()).hexdigest()


class AdLibTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = musicseq.Library(FLX, adlib=True)
        cls.bank = adlib.Bank.load(FLX)

    def writes(self, reqs, end):
        events, trace = musicseq.sequence(self.lib, reqs, end)
        return adlib.chip_writes(adlib.register_writes(events, trace, end, self.bank))

    def test_bank_holds_the_listed_timbres(self):
        self.assertEqual(len(self.bank.timbres), 80)
        self.assertTrue(all(len(t) == 14 for t in self.bank.timbres.values()))
        self.assertIn((127, 36), self.bank.timbres)                          # percussion: bank 127, patch = key

    def test_adlib_library_uses_the_second_arrangement(self):
        self.assertEqual(len(self.lib.trans), 55)
        self.assertEqual(self.lib._entry(10), 138)
        self.assertEqual(musicseq.Library(FLX)._entry(10), 10)

    def test_init_writes_every_register_once(self):
        drv = adlib.Driver(self.bank)
        regs = dict(drv.writes)
        self.assertEqual(len(drv.writes), 0xf5)
        self.assertEqual((regs[0x01], regs[0xbd], regs[0x20], regs[0x40], regs[0x60], regs[0x80]), (0x20, 0xc0, 1, 0x3f, 0xff, 0x0f))

    def test_note_frequency_and_key_on(self):
        drv = adlib.Driver(self.bank)
        drv.writes = []
        prog = next(p for b, p in self.bank.timbres if b == 0)
        drv.send(bytes([0xc1, prog]))
        tr = self.bank.timbres[(0, prog)][2]
        tr -= 256 if tr > 127 else 0
        drv.send(bytes([0x91, 69 - tr, 100]))                                # sounds as A4
        regs = dict(drv.writes)
        self.assertEqual((regs[0xa0], regs[0xb0]), (580 & 0xff, 0x20 | 4 << 2 | 580 >> 8))   # F-number 580, block 4: 440.0 Hz
        drv.writes = []
        drv.send(bytes([0x81, 69 - tr, 0]))
        self.assertEqual(drv.writes, [(0xb0, (0x20 | 4 << 2 | 580 >> 8) & 0xdf)])

    def test_percussion_plays_at_the_timbre_note(self):
        drv = adlib.Driver(self.bank)
        drv.send(bytes([0x99, 36, 100]))
        s = next(s for s in drv.slots if s.status)
        self.assertEqual((s.key, s.note, s.transpose), (36, self.bank.timbres[(127, 36)][2], 0))
        drv.send(bytes([0x90, 60, 100]))                                     # channel 0 is not played
        self.assertEqual(sum(1 for s in drv.slots if s.status), 1)

    def test_tenth_note_steals_by_priority(self):
        drv = adlib.Driver(self.bank)
        for k in range(9): drv.send(bytes([0x91, 40 + k, 100]))
        drv.send(bytes([0x92, 70, 100]))                                     # channel 2 has fewer voices: takes one
        self.assertEqual(sorted(s.chan for s in drv.slots if s.status and s.voice != 0xff), [1] * 8 + [2])

    def test_reused_slot_keeps_its_old_key_on_register_copy(self):
        # The slot's 0xB0 copy (09f8) is written only by the register writer (13ea), never at note on: a slot that gets a voice
        # through 0644 (no write) and is released before any write keys off with the value of its previous note.
        drv = adlib.Driver(self.bank)
        prog = min(p for b, p in self.bank.timbres if b == 0)
        for ch in (1, 2, 3): drv.send(bytes([0xc0 | ch, prog]))
        for k in range(9): drv.send(bytes([0x91, 40 + k, 100]))        # slots 0..8 on voices 0..8
        drv.send(bytes([0x92, 70, 100]))                                 # slot 9 takes voice 8 by priority: written
        old = [v for r, v in drv.writes if r == 0xb8][-1]
        drv.send(bytes([0x82, 70, 0]))                                   # slot 9 free again
        drv.send(bytes([0xb1, 112, 127]))                                # channel 1 voice protect
        drv.send(bytes([0x91, 48, 100]))                                 # slot 8, the free voice 8
        drv.send(bytes([0x93, 60, 100]))                                 # slot 9 waits: protected voices win
        drv.send(bytes([0x81, 40, 0]))                                   # voice 0 goes to slot 9 without a write
        drv.writes = []
        drv.send(bytes([0x83, 60, 0]))
        self.assertEqual(drv.writes[-1], (0xb0, old & 0xdf))
        self.assertNotEqual(old & 0xdf, 0)

    def test_serves_only_while_a_song_is_loaded_and_not_paused(self):
        ev, trace = musicseq.sequence(self.lib, [(1.0, 10), (2.0, -2), (3.0, -3), (4.0, -1)], 5.0)
        self.assertEqual(adlib.serving(trace), [(1.0, True), (2.0, False), (3.0, True), (4.0, False)])
        # the priority pass (every 24th serve) gives a waiting slot its voice: channel 1 holds all nine voices under voice
        # protect, a channel 3 note waits, the protect ends at 0.05 s
        prog = min(p for b, p in self.bank.timbres if b == 0)
        ev = ([(0.0, bytes([0xc1, prog])), (0.0, bytes([0xc3, prog])), (0.0, bytes([0xb1, 112, 127]))]
              + [(0.0, bytes([0x91, 40 + k, 100])) for k in range(9)] + [(0.0, bytes([0x93, 60, 100])), (0.05, bytes([0xb1, 112, 0]))])
        def steal(trace):
            on = [k for k, r, v in adlib.register_writes(ev, trace, 2.0, self.bank)[0xf5:] if 0xb0 <= r <= 0xb8 and v & 0x20]
            return on[9:]
        self.assertEqual(steal([(0.0, 'start')]), [23])                                   # serves 0..23
        self.assertEqual(steal([(0.0, 'start'), (0.1, 'pause'), (0.5, 'resume')]), [47])  # serves 0..5, then 30..47
        self.assertEqual(steal([]), [])

    def test_writes_land_on_the_60_hz_serves(self):
        w = self.writes([(0.0, 10), (8.0, -1)], 8.0)
        self.assertTrue(all(s in {k * opl.RATE // 60 for k in range(481)} for s, _, _ in w))

    def test_register_writes_match_the_native_port(self):
        w = self.writes([(0.0, 10), (8.0, -1)], 8.0)
        self.assertEqual((len(w), digest(w)), (607, '89659a959506de4ba655a8513b82c0a0c870b890b6c63b91c3b64d496f0aded0'))
        w = self.writes([(0.0, 10), (12.0, 21), (30.0, -1)], 30.0)
        self.assertEqual((len(w), digest(w)), (3220, 'b3879836e7e9912435feddf83aeab3b1f8238bde6500b894fb60a6644c343975'))
        w = self.writes([(0.0, 10), (1.0, 5), (20.0, -1)], 20.0)
        self.assertEqual((len(w), digest(w)), (2426, '50083c92cbc04641acad416de1095f0bcc795251b76e60219b62708a4c8b7d8c'))

    def test_chip_output(self):
        w = self.writes([(0.0, 10), (8.0, -1)], 8.0)
        pcm = np.array(opl.render_writes(w, opl.RATE // 2), '<i2')
        self.assertEqual(int(np.abs(pcm.astype(int)).sum()), 46420190)
        self.assertEqual(hashlib.sha256(pcm.tobytes()).hexdigest(), '4837f5d034909acb3eb3073b6fcc404a47cc07ab63891832e4897e100db81f29')

    @unittest.skipUnless(shutil.which('swiftc'), 'needs the Swift toolchain')
    def test_native_chip_matches(self):
        w = self.writes([(0.0, 10), (8.0, -1)], 8.0)
        n = opl.RATE // 2
        self.assertTrue(np.array_equal(adlib.render_chip(w, n), np.array(opl.render_writes(w, n), np.int16)))

    def test_install_opt_music_device(self):
        dev = lambda t: settings.Settings.from_text(t).music_device
        self.assertEqual(dev('MUSIC=ON\r\nMusicCardId=7\r\n'), 'gm')
        self.assertEqual([dev(f'MusicCardId={i}') for i in range(1, 8)], ['adlib'] * 3 + ['gm'] * 4)
        self.assertIsNone(dev('MUSIC=OFF\r\nMusicCardId=0'))
        self.assertEqual(dev(''), 'gm')


if __name__ == '__main__':
    unittest.main()
