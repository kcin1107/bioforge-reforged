import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subtitles as sub  # noqa: E402


class TestText(unittest.TestCase):
    def test_split_lines(self):
        self.assertEqual(sub.split_lines('One'), ['One'])
        self.assertEqual(sub.split_lines('One~Two'), ['One', 'Two'])
        self.assertEqual(sub.split_lines('A~B~C~D'), ['A', 'B', 'C~D'])


class TestActive(unittest.TestCase):
    LOG = [(10, 1, 117, 'first', 40), (30, 2, 127, 'second', 60)]

    def test_lookup(self):
        self.assertIsNone(sub.active_subtitle(self.LOG, 9))
        self.assertEqual(sub.active_subtitle(self.LOG, 10), (117, 'first'))
        self.assertEqual(sub.active_subtitle(self.LOG, 29), (117, 'first'))

    def test_replacement_and_end(self):
        log = [(10, 1, 117, 'first', 30)] + self.LOG[1:]      # the log shortens a replaced subtitle to the new one's start
        self.assertEqual(sub.active_subtitle(log, 29), (117, 'first'))
        self.assertEqual(sub.active_subtitle(log, 30), (127, 'second'))
        self.assertEqual(sub.active_subtitle(self.LOG, 35), (127, 'second'))   # newest wins if entries overlap
        self.assertIsNone(sub.active_subtitle(self.LOG, 60))


class TestDraw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = sub.load_font()

    def draw(self, text, colour=200):
        buf = bytearray(320 * 200)
        box = sub.render_subtitle(buf, 320, 200, text, colour, self.font)
        return np.frombuffer(bytes(buf), np.uint8).reshape(200, 320), box

    def test_one_line_inside_box_and_centred(self):
        img, box = self.draw('Hello')
        self.assertEqual(box, (5, 185, 315, 198))
        ys, xs = np.nonzero(img == 200)
        self.assertGreater(len(xs), 0)
        self.assertTrue(xs.min() >= 5 and xs.max() <= 315 and ys.min() >= 185 and ys.max() <= 198)
        w = self.font.text_width('Hello')
        left = ((300 - w) >> 1) + 10
        self.assertTrue(left <= xs.min() <= left + 2 and xs.max() <= left + w)
        self.assertEqual(img[img != 0].max(), 200)             # only text colour and the colour 0 shadow are used

    def test_shadow_offset(self):
        buf = bytearray(320 * 200)
        sub.render_subtitle(buf, 320, 200, 'I', 200, self.font, shadow=7)
        img = np.frombuffer(bytes(buf), np.uint8).reshape(200, 320)
        ys, xs = np.nonzero(img == 200)
        sy, sx = np.nonzero(img == 7)
        self.assertGreater(len(sx), 0)
        self.assertEqual((sy.max() - ys.max(), sx.max() - xs.max()), (1, 1))

    def test_three_lines_box_and_rows(self):
        img, box = self.draw('a~b~c')
        self.assertEqual(box, (5, 165, 315, 198))
        rows = np.nonzero((img == 200).any(axis=1))[0]
        self.assertTrue(rows.min() >= 165 and rows.max() <= 198)
        self.assertTrue(((rows >= 166) & (rows <= 176)).any() and ((rows >= 186) & (rows <= 198)).any())

    def test_rgb_uses_palette(self):
        pal = np.zeros((256, 3), np.uint8)
        pal[200] = (10, 20, 30)
        frame = np.full((200, 320, 3), 100, np.uint8)
        sub.draw_on_rgb(frame, 'Hello', 200, self.font, pal)
        self.assertTrue((frame == (10, 20, 30)).all(axis=2).any())
        self.assertTrue((frame[10, 10] == 100).all())                       # outside the box: untouched
        self.assertTrue((frame[190, 8] == 50).all() or (frame[190, 8] == 0).all())   # inside: shaded


if __name__ == '__main__':
    unittest.main()
