"""Writes native/Tests/BioForgeCoreTests/Fixtures/pixel_filters.json: pixel_filters.constrain on small random inputs, for PixelPackTests
to check the Swift port against (factors 2 and 4, with and without empty pixels, a palette with duplicate colours).

    python3 -I re/tools/pixel_fixtures.py
"""
import json, os, sys
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 're', 'tools'))
import numpy as np
from pixel_filters import constrain


def main():
    rng = np.random.default_rng(1107)
    pal = rng.integers(0, 256, (256, 3))
    pal[9] = pal[4]                                         # duplicate colours compare equal
    cases = []
    for factor in (2, 4):
        for with_solid in (False, True):
            h, w = 7, 9
            src = rng.integers(0, 12, (h, w))
            guide = rng.integers(0, 256, (factor * h, factor * w, 3))
            solid = rng.random((h, w)) > 0.25 if with_solid else None
            out = constrain(src, guide, pal, solid, factor)
            cases.append({'factor': factor, 'width': w, 'height': h, 'src': src.ravel().tolist(), 'guide': guide.ravel().tolist(),
                          'solid': None if solid is None else solid.ravel().astype(int).tolist(), 'out': out.ravel().tolist()})
    path = os.path.join(REPO, 'native', 'Tests', 'BioForgeCoreTests', 'Fixtures', 'pixel_filters.json')
    with open(path, 'w') as f: json.dump({'palette': pal.ravel().tolist(), 'cases': cases}, f, separators=(',', ':'))
    print(path)


if __name__ == '__main__':
    main()
