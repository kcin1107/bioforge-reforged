import unittest
import numpy as np
from pixel_filters import canon, nearest2x, constrain, rule3_violations

PAL = np.random.default_rng(0).integers(0, 256, (256, 3))


class Constrain(unittest.TestCase):
    def test_flat_stays_flat(self):
        a = np.full((6, 6), 7)
        guide = np.random.default_rng(2).integers(0, 256, (12, 12, 3))
        self.assertTrue((constrain(a, guide, PAL) == 7).all())

    def test_only_nearby_colours_and_half_kept(self):
        rng = np.random.default_rng(1)
        a = rng.integers(0, 6, (24, 24))
        up = constrain(a, rng.integers(0, 256, (48, 48, 3)), PAL)
        self.assertEqual(rule3_violations(a, up), 0)
        kept = (up == nearest2x(a)).reshape(24, 2, 24, 2).sum((1, 3))
        self.assertTrue((kept >= 2).all())

    def test_factor_4_keeps_the_rules(self):
        rng = np.random.default_rng(3)
        a = rng.integers(0, 6, (12, 12))
        up = constrain(a, rng.integers(0, 256, (48, 48, 3)), PAL, factor=4)
        self.assertEqual(up.shape, (48, 48))
        self.assertEqual(rule3_violations(a, up, factor=4), 0)
        kept = (up == nearest2x(a, 4)).reshape(12, 4, 12, 4).sum((1, 3))
        self.assertTrue((kept >= 8).all())

    def test_follows_the_guide_where_it_can(self):
        a = np.array([[1, 2]])
        guide = np.zeros((2, 4, 3), np.int64)
        guide[:, :2] = PAL[1]; guide[:, 2:] = PAL[2]
        guide[0, 1] = PAL[2]                                   # one pixel of the left block looks like its neighbour
        up = constrain(a, guide, PAL)
        self.assertEqual(up[0, 1], 2)
        self.assertTrue((up[:, 2:] == 2).all())

    def test_empty_pixels_are_never_picked(self):
        a = np.array([[1, 9]])
        guide = np.tile(PAL[9], (2, 4, 1))
        up = constrain(a, guide, PAL, solid=np.array([[True, False]]))
        self.assertTrue((up[:, :2] == 1).all())

    def test_canon_merges_duplicate_colours(self):
        pal = np.zeros((256, 3), np.int64); pal[5] = pal[9] = (1, 2, 3)
        self.assertEqual(canon(pal)[9], 5)


if __name__ == '__main__':
    unittest.main()
