"""BioForge bitmap fonts (DATA/*.FNT).

file:  u16 height, u16 max width, u16 n_glyphs, n * (u32 offset, u16 size), glyph data
glyph: u16 0, u16 width, u16 height, u16 x origin, u16 baseline, u16 rowoff[height]
       (self-relative, not needed), then per row (u8 skip, u8 count, count * u8 colour)
       pairs until x >= width (a skip reaching the width ends the row, as in CAM images).
Glyph index = character code. The engine blits a glyph at (x - x origin, y - baseline) for a
baseline y and advances by width + char spacing (FUN_11d8_03ca; captions use spacing 1).
Each font uses one colour index (SMALL.FNT a 5-step ramp); draw() replaces it with the
requested colour unless colour is None.
"""
import struct, sys


class Font:
    def __init__(self, path):
        d = open(path, 'rb').read()
        self.height, self.max_width, n = struct.unpack_from('<HHH', d, 0)
        self.glyphs = []                     # (width, height, x origin, rows[list of bytes; 0 = clear])
        self.baselines = []
        for i in range(n):
            o, s = struct.unpack_from('<IH', d, 6 + 6 * i)
            _, w, h, xorg, base = struct.unpack_from('<5H', d, o)
            p, rows = o + 10 + 2 * h, []
            for _ in range(h):
                x, row = 0, bytearray(w)
                while x < w:
                    x += d[p]; p += 1
                    if x >= w: break
                    c = d[p]; p += 1
                    row[x:x + c] = d[p:p + c]; p += c; x += c
                rows.append(bytes(row))
            assert p == o + s, (path, i)
            self.glyphs.append((w, h, xorg if xorg < 0x8000 else xorg - 0x10000, rows))
            self.baselines.append(base)
        self.baseline = max(self.baselines)

    def glyph(self, ch):
        i = ord(ch)
        return self.glyphs[i] if i < len(self.glyphs) else None

    def width(self, text, spacing=0):
        return sum(g[0] + spacing for g in map(self.glyph, text) if g)

    def draw(self, img, x, y, text, colour=None, spacing=0, baseline=False):
        """Draw text into img = (buf, pitch, height), a palette-indexed surface. y is the top of
        the line (glyphs aligned on the font's largest baseline), or the baseline itself when
        baseline=True (engine convention). Returns the x after the last glyph."""
        buf, pitch, height = img
        base = y if baseline else y + self.baseline
        for ch in text:
            if ord(ch) < 0x20: continue
            g = self.glyph(ch)
            if not g: continue
            w, h, xorg, rows = g
            top, left = base - self.baselines[ord(ch)], x - xorg
            for r, row in enumerate(rows):
                yy = top + r
                if not 0 <= yy < height: continue
                for c, v in enumerate(row):
                    xx = left + c
                    if v and 0 <= xx < pitch:
                        buf[yy * pitch + xx] = v if colour is None else colour
            x += w + spacing
        return x


if __name__ == '__main__':
    f = Font(sys.argv[1])
    text = sys.argv[2] if len(sys.argv) > 2 else 'BioForge'
    w, h = f.width(text), f.baseline + max(g[1] - b for g, b in zip(f.glyphs, f.baselines))
    buf = bytearray(w * h)
    f.draw((buf, w, h), 0, 0, text, 1)
    for y in range(h): print(''.join('#' if buf[y * w + x] else '.' for x in range(w)))
