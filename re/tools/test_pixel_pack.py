"""The monitor pass of pixel_pack.py (needs the game files under game/app/Bioforge), with a model stand-in that enlarges 2x (the pack's scale)."""
import os, sys, tempfile, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixel_pack as pp

GAME = os.path.join(pp.GAME, 'MONITORS', 'PIMM.CAM')


def up(rgb):
    return np.repeat(np.repeat(rgb.astype(np.float32), 2, 0), 2, 1)


class Shapes(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual([pp.bucket(n, 320) for n in (1, 32, 33, 300, 320)], [32, 32, 64, 320, 320])
        self.assertEqual([pp.bucket(n, 200) for n in (1, 199, 200)], [32, 200, 200])

    def test_window_is_bucketed_and_on_screen(self):
        for sx0, sx1, sy0, sy1 in [(0, 10, 0, 10), (300, 320, 180, 200), (100, 101, 90, 91), (0, 320, 0, 200), (150, 200, 20, 150)]:
            cx0, cy0, cx1, cy1 = pp.window(sx0, sy0, sx1, sy1)
            self.assertTrue(0 <= cx0 <= sx0 and sx1 <= cx1 <= 320 and 0 <= cy0 <= sy0 and sy1 <= cy1 <= 200)
            self.assertEqual((cx1 - cx0, cy1 - cy0), (pp.bucket(cx1 - cx0, 320), pp.bucket(cy1 - cy0, 200)))
            self.assertTrue(cx0 <= max(0, sx0 - pp.PAD) and cx1 >= min(320, sx1 + pp.PAD))

    def test_padded_guide_sees_bucket_sizes_and_crops_back(self):
        seen = []
        def spy(rgb): seen.append(rgb.shape[:2]); return up(rgb)
        rgb = np.arange(5 * 7 * 3).reshape(5, 7, 3)
        big = pp.padded(spy, rgb)
        self.assertEqual(seen, [(32, 32)])
        self.assertEqual(big.shape, (10, 14, 3))
        self.assertTrue((big == up(rgb)).all())


class Outline(unittest.TestCase):
    def test_scale2x(self):                       # the same pattern and result as PixelPackTests.scale2xSmoothsStaircasesOnly
        m = np.array([[1, 0, 0], [1, 1, 0], [1, 1, 1]], np.uint8)
        self.assertEqual([''.join(map(str, r)) for r in pp.scale2x(m)], ['110000', '111000', '111000', '111110', '111111', '111111'])
        for m in (np.array([[1, 1, 0, 0]] * 3, np.uint8), np.pad(np.ones((1, 1), np.uint8), 1)):          # a straight edge, a lone pixel
            self.assertTrue((pp.scale2x(m) == np.kron(m, np.ones((2, 2), np.uint8))).all())

    def test_smooth_fills_new_pixels_with_the_nearest_colour(self):
        m = np.array([[1, 0, 0], [1, 1, 0], [1, 1, 1]], np.uint8)
        px = np.kron(np.arange(9).reshape(3, 3), np.ones((2, 2), np.int64)) + 10
        out, sm = pp.smooth(px, m, 2)
        self.assertTrue((sm == pp.scale2x(m)).all())
        grown = (sm != 0) & (np.kron(m, np.ones((2, 2), np.uint8)) == 0)
        self.assertEqual(sorted(zip(*map(list, np.nonzero(grown)))), [(1, 2), (3, 4)])
        self.assertEqual((out[1, 2], out[3, 4]), (px[2, 2], px[4, 4]))     # the opaque pixel below (up is tried first, but is empty)
        self.assertTrue((out[~grown] == px[~grown]).all())

    def test_frames_roundtrip_and_old_format_decodes(self):
        px, m = np.arange(6, dtype=np.uint8).reshape(2, 3), np.ones((2, 3), np.uint8)
        b = pp.encode(px, m)
        self.assertEqual(b[:4], b'BFX3')
        for data in (b, b'BFX2' + b[4:]): self.assertTrue((pp.decode(data)[0] == px).all())


@unittest.skipUnless(os.path.exists(GAME), 'the game files are not present')
class MonitorPass(unittest.TestCase):
    def test_pimm_builds_only_its_background(self):
        with tempfile.TemporaryDirectory() as out:
            wr = pp.Writer(out, None, None)
            n = pp.do_monitors(wr, lambda rgb: up(rgb), 2, ['pimm'])
            files = sorted(os.listdir(os.path.join(out, 'monitors', 'PIMM')))
            self.assertEqual((n, files), (1, ['PIMM.0.frm']))      # buttons, gauges and bars are drawn plain-doubled (MonitorScreen.render)
            big, bm = pp.decode(open(os.path.join(out, 'monitors', 'PIMM', 'PIMM.0.frm'), 'rb').read())
            self.assertTrue((big[bm == 0] == 255).all())
            self.assertEqual(pp.do_monitors(wr, lambda rgb: up(rgb), 2, ['pimm']), 0)          # resumes: nothing left

    def test_pointers_build_every_frame(self):
        with tempfile.TemporaryDirectory() as out:
            wr = pp.Writer(out, None, None)
            pp.do_monitors(wr, lambda rgb: up(rgb), 2, ['pointer', 'pcayhand'])
            for mon in ('POINTER', 'PCAYHAND'):
                pal, entries = pp.room_entries(os.path.join(pp.GAME, 'MONITORS', mon + '.CAM'))
                _, _, name, frames = entries[0]
                want = {f'{name}.{k}.frm' for k, fr in enumerate(frames) if fr[0] * fr[1] > 1 and any(fr[5])}
                self.assertEqual(set(os.listdir(os.path.join(out, 'monitors', mon))), want)
                self.assertTrue(want)
                for f in want:
                    k = int(f.split('.')[1])
                    w, h = frames[k][0], frames[k][1]
                    big, bm = pp.decode(open(os.path.join(out, 'monitors', mon, f), 'rb').read())
                    self.assertEqual(big.shape, (2 * h, 2 * w))
                    self.assertTrue((big[bm == 0] == 255).all())

if __name__ == '__main__':
    unittest.main()
