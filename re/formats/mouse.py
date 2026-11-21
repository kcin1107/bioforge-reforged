"""BioForge mouse cursor shapes (DATA/MOUSE.SHP, the `mouseptr` option of RED.OPT).

The file is a font (fnt.py): header u16 11, u16 14 (the box of background the engine saves under the cursor:
11 wide, 14 high), u16 8 shapes; each glyph's x origin and baseline are the hotspot. Colours are
real palette indices (no remapping), drawn as they are into whatever palette is active.

Shapes: 0 arrow (11x12, hot 1,1), 1 small marker (3x7, hot 1,3), 2 hourglass (10x14, hot 4,6), 3..7 a busy
animation (9-10x8, hot 8-9,0) that no code selects.

Engine (seg 1058, NOTES "Mouse cursor"): a priority stack of u16 (priority << 8 | shape) entries; the base is
0x7f00 = arrow. Busy code pushes 0x702 (hourglass: level loads, save/load, FLIC streaming) and garbage collection
(FUN_1150_0000) pushes 0x701. Each presented frame draws the top shape at (mouse x - hot x, mouse y - hot y), clipped to
320x200, and restores the background afterwards. The cursor is only visible with BIOFORGE.EXE -e (editor mode,
DAT_50b9 = 0): normal play keeps it hidden and ignores the pushes.
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fnt  # noqa: E402

ARROW, MARKER, HOURGLASS = 0, 1, 2


class MouseShapes:
    def __init__(self, path):
        f = fnt.Font(path)
        self.box = (f.height, f.max_width)       # header u16 0, u16 2: the saved box is 11 wide, 14 high (FUN_1058_029f)
        # (width, height, hot x, hot y, rows) per shape
        self.shapes = [(w, h, xorg, base, rows) for (w, h, xorg, rows), base in zip(f.glyphs, f.baselines)]

    def draw(self, buf, pitch, height, shape, x, y):
        """Draw `shape` with its hotspot at (x, y) into a palette-indexed buffer (bytearray or 2-D array);
        index 0 is transparent, pixels outside the buffer are clipped."""
        w, h, hx, hy, rows = self.shapes[shape]
        flat = not hasattr(buf, 'shape')
        for r, row in enumerate(rows):
            yy = y - hy + r
            if not 0 <= yy < height:
                continue
            for c, v in enumerate(row):
                xx = x - hx + c
                if v and 0 <= xx < pitch:
                    if flat:
                        buf[yy * pitch + xx] = v
                    else:
                        buf[yy, xx] = v

    def digest(self):
        """SHA-256 over every shape's u16 width, height, s16 hot x, hot y and rows (the native port's parity check)."""
        h = hashlib.sha256()
        for w, ht, hx, hy, rows in self.shapes:
            h.update(struct.pack('<HHhh', w, ht, hx, hy))
            for row in rows:
                h.update(row)
        return h.hexdigest()


if __name__ == '__main__':
    m = MouseShapes(sys.argv[1])
    print('box', m.box, 'sha256', m.digest())
    for i, (w, h, hx, hy, rows) in enumerate(m.shapes):
        print(f'{i}: {w}x{h} hot ({hx},{hy})')
        for row in rows:
            print('   ', ''.join('#' if v else '.' for v in row))
