"""MOUSE.SHP cursor shapes: geometry, hotspots, colours and the digest the native port checks."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mouse

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'game', 'app', 'Bioforge', 'DATA', 'MOUSE.SHP')
DIGEST = '6884ae9627b61987051b0e2a00176f562f28c71e12abd6d7f47b4b3c997ac5f7'   # also in native MouseShapesTests


@unittest.skipUnless(os.path.exists(PATH), 'no game data')
class MouseShapes(unittest.TestCase):
    def setUp(self):
        self.m = mouse.MouseShapes(PATH)

    def test_shapes_and_hotspots(self):
        self.assertEqual(self.m.box, (11, 14))
        self.assertEqual([s[:4] for s in self.m.shapes],
                         [(11, 12, 1, 1), (3, 7, 1, 3), (10, 14, 4, 6), (9, 8, 8, 0),
                          (10, 8, 9, 0), (10, 8, 9, 0), (10, 8, 9, 0), (10, 8, 9, 0)])
        arrow = self.m.shapes[mouse.ARROW][4]
        self.assertEqual(set(b for r in arrow for b in r), {0, 240, 241, 242, 243, 244, 245, 248})
        self.assertEqual(self.m.digest(), DIGEST)

    def test_draw_matches_the_original_at_the_screen_centre(self):
        # DOSBox-X dump of BIOFORGE.EXE -e (mouse at 160,100): rows y=100..102 from x=160.
        buf = bytearray(320 * 200)
        self.m.draw(buf, 320, 200, mouse.ARROW, 160, 100)
        self.assertEqual(list(buf[100 * 320 + 160:100 * 320 + 162]), [248, 240])
        self.assertEqual(list(buf[101 * 320 + 160:101 * 320 + 164]), [245, 241, 240, 240])
        self.assertEqual(list(buf[102 * 320 + 160:102 * 320 + 165]), [0, 244, 241, 241, 240])
        self.assertEqual(buf[99 * 320 + 159], 0)                  # transparent corner

    def test_draw_clips_at_the_edges(self):
        buf = bytearray(320 * 200)
        self.m.draw(buf, 320, 200, mouse.HOURGLASS, 319, 199)
        self.m.draw(buf, 320, 200, mouse.HOURGLASS, 0, 0)
        self.assertEqual(len(buf), 64000)
        self.assertTrue(buf[0] and buf[199 * 320 + 319])


if __name__ == '__main__':
    unittest.main()
