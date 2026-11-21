"""CAM frame encoder: decode(encode(x)) == x, and the native save thumbnail is reproduced byte for byte."""
import os, random, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cam, savegame

NATIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'native_save', 'GAME1.IM1')


class Encoder(unittest.TestCase):
    def roundtrip(self, w, h, px, rle=True, mask=None, hot=(0, 0)):
        b = cam.encode_frame(w, h, bytes(px), *hot, rle=rle, mask=mask)
        w2, h2, hx, hy, px2, m2 = cam.decode_frame(b, 0)
        self.assertEqual((w2, h2, hx, hy), (w, h, *hot))
        want = mask if mask is not None else b'\1' * (w * h)
        self.assertEqual(bytes(m2), bytes(want))
        self.assertEqual(bytes(a if m else 0 for a, m in zip(px2, m2)), bytes(a if m else 0 for a, m in zip(px, want)))

    def test_random_images(self):
        rnd = random.Random(5)
        for rle in (True, False):
            for _ in range(20):
                w, h = rnd.randint(1, 40), rnd.randint(1, 12)
                px = [rnd.choice((0, 0, 7, rnd.randrange(256))) for _ in range(w * h)]
                self.roundtrip(w, h, px, rle)
                self.roundtrip(w, h, px, rle, mask=bytes(rnd.random() < .6 for _ in range(w * h)), hot=(-3, 9))

    def test_long_runs_and_gaps(self):
        self.roundtrip(700, 2, [9] * 1400)
        self.roundtrip(700, 2, bytes(range(256)) * 5 + bytes(120), mask=bytes([0] * 600 + [1] * 100 + [1] * 600 + [0] * 100))

    @unittest.skipUnless(os.path.exists(NATIVE), 'no native save sample')
    def test_native_thumbnail_is_reproduced_byte_for_byte(self):
        th = savegame.Im1.entries(open(NATIVE, 'rb').read())[1]
        w, h, hx, hy, px, _ = cam.decode_frame(th, 0)
        self.assertEqual(cam.encode_frame(w, h, px, hx, hy), th)


if __name__ == '__main__':
    unittest.main()
