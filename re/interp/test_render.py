"""Renderer regression checks: re/.venv/bin/python -I -m unittest discover -s re/interp."""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'formats'))
from render import draw_poly  # noqa: E402


class TextureTransparency(unittest.TestCase):
    def test_magenta_texel_keeps_background_and_depth(self):
        screen = np.array([[0., 0., 10.], [3., 0., 10.], [0., 3., 10.]])
        pal = np.zeros((256, 3), np.uint8)
        pal[255] = [255, 0, 255]
        pal[254] = [200, 150, 100]
        img = np.full((4, 4, 3), [10, 20, 30], np.uint8)
        zbuf = np.full((4, 4), np.inf)
        poly = (6, 0, (0, 1, 2), 0, ((0, 0), (0, 0), (0, 0)))
        mesh = types.SimpleNamespace(polys=[poly], textures=[('mask', 1, 1, b'\xff')])

        draw_poly(mesh, 0, screen, pal, img, zbuf)
        np.testing.assert_array_equal(img[0, 0], [10, 20, 30])
        self.assertTrue(np.isinf(zbuf[0, 0]))

        mesh.textures[0] = ('opaque', 1, 1, b'\xfe')
        draw_poly(mesh, 0, screen, pal, img, zbuf)
        np.testing.assert_array_equal(img[0, 0], [200, 150, 100])
        self.assertEqual(zbuf[0, 0], 10)


if __name__ == '__main__':
    unittest.main()
