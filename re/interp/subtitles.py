"""Subtitle drawing, as the engine does it per frame (FUN_1100_1538, caption object set up by FUN_1100_14a9).

Layout (320x200 view, palette indices): the text is split at '~' into up to 3 lines (FUN_1100_14a9; DAT_1290_5121 = "~").
Each line is centred in x = 10..310 (x = ((300 - width) >> 1) + 10, width = sum of glyph widths + 1 px spacing) and
drawn at a baseline y of 194 (last line), 184, 174 (10 px apart). A glyph is blitted at (x - xorigin, y - baseline)
(FUN_11d8_03ca), in a solid colour. The font object has shadow mode 2 (FUN_1100_12a2 `[0x36] = 2`, FUN_1248_192e):
the text is first drawn in colour 0 shifted by (+1, +1). Behind the text a box x 5..315, y top..198 is shaded through a
colour remap table (FUN_1138_1d0a); top = 185 / 175 / 165 for 1 / 2 / 3 lines. The colour is the speaker's palette index
(FUN_1100_1376 only remaps it through CAPTIONCOLORS while a monitor is up, DAT_1290_4e2c).
"""
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'formats'))
from fnt import Font  # noqa: E402

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'game', 'app', 'Bioforge', 'DATA')
# ASSUMPTION: the caption font file. The engine loads it from the option CAPTIONFONT (FUN_1100_12a2), which E.OPT lacks and
# whose default could not be recovered statically. 1.FNT fits the engine's geometry (baseline 8, height 11: a 10 px line
# pitch and the 13 px box).
FONT_NUMBER = 1
SEPARATOR = '~'                 # DAT_1290_5121
SPACING = 1                     # extra pixels after each glyph (font object field +6, FUN_1248_14fd -> FUN_11f0 ctor)
SHADOW_COLOUR = 0               # FUN_1248_192e draws the shadow with colour 0, offset (+1, +1) for shadow mode 2
LINE_Y = (194, 184, 174)        # baselines of the last, second to last, ... line (FUN_1100_1538); n lines use the last n
BOX_X = (5, 315)                # inclusive
BOX_BOTTOM = 198
BOX_TOP = {1: 185, 2: 175, 3: 165}
BOX_SHADE = 0.5                 # ASSUMPTION: the box darkens the picture through a remap table of the view (FUN_1138_1d0a); 50 % brightness


class CaptionFont(Font):
    """Font plus the per-glyph origins that fnt.py leaves out: header words 3 and 4 are the x origin and the baseline
    (the blit position is (x - xorigin, y - baseline), FUN_11d8_03ca)."""

    def __init__(self, path):
        super().__init__(path)
        d = open(path, 'rb').read()
        self.baselines = []
        for i in range(len(self.glyphs)):
            o, _ = struct.unpack_from('<IH', d, 6 + 6 * i)
            self.baselines.append(struct.unpack_from('<5H', d, o)[4])

    def advance(self, ch):
        g = self.glyph(ch)
        return (g[0] if g else 0) + SPACING

    def text_width(self, text):
        return sum(self.advance(c) for c in text)


def load_font(number=FONT_NUMBER):
    return CaptionFont(os.path.join(FONT_DIR, f'{number}.FNT'))


def split_lines(text):
    """Up to 3 lines split at '~' (FUN_1100_14a9: first '~', then the next one; the rest stays in the third line). The log holds the text
    already filtered for the language (World.subtitle)."""
    return text.split(SEPARATOR, 2)


def active_subtitle(subtitle_log, tick):
    """(colour, text) of the subtitle shown at `tick`, or None. A subtitle is up from its tick to its end tick
    (exclusive); a newer one replaces an older one (the log already shortens the replaced entry)."""
    found = None
    for t, _, colour, text, end in subtitle_log:
        if t <= tick < end:
            found = (colour, text)
    return found


def _glyph_rows(font, ch):
    """(x origin, baseline, rows) of a glyph or None. Glyph codes below 0x20 are not drawn (FUN_11f0_14c3)."""
    if ord(ch) < 0x20:
        return None
    g = font.glyph(ch)
    return None if g is None else g


def _draw_line(buf, pitch, height, x, y, line, colour, font):
    for ch in line:
        g = _glyph_rows(font, ch)
        if g is not None:
            w, _, xorg, rows = g
            top = y - font.baselines[ord(ch)]
            for r, row in enumerate(rows):
                yy = top + r
                if not 0 <= yy < height:
                    continue
                for c, v in enumerate(row):
                    xx = x - xorg + c
                    if v and 0 <= xx < pitch:
                        buf[yy * pitch + xx] = colour
        x += font.advance(ch)


def render_subtitle(frame_buf, pitch, height, text, colour, font, shadow=SHADOW_COLOUR):
    """Draw the text lines (shadow first, then `colour`) into an indexed frame buffer (bytearray, pitch x height).
    Returns the (x0, y0, x1, y1) box (inclusive) that the engine shades behind the text."""
    lines = split_lines(text)
    n = len(lines)
    for i, line in enumerate(lines):
        y = LINE_Y[n - 1 - i]
        x = ((300 - font.text_width(line)) >> 1) + 10
        _draw_line(frame_buf, pitch, height, x + 1, y + 1, line, shadow, font)
        _draw_line(frame_buf, pitch, height, x, y, line, colour, font)
    return BOX_X[0], BOX_TOP[n], BOX_X[1], BOX_BOTTOM


def draw_on_rgb(frame, text, colour, font, palette):
    """Subtitle onto an RGB frame (H x W x 3 uint8, modified in place): shaded box, then shadow and text in palette colours."""
    h, w = frame.shape[:2]
    layer = bytearray(w * h)                 # 0 = untouched, 1 = shadow, 2 = text (palette lookups below)
    x0, y0, x1, y1 = render_subtitle(layer, w, h, text, 2, font, shadow=1)
    frame[y0:y1 + 1, x0:x1 + 1] = (frame[y0:y1 + 1, x0:x1 + 1] * BOX_SHADE).astype(np.uint8)
    lay = np.frombuffer(bytes(layer), np.uint8).reshape(h, w)
    frame[lay == 1] = palette[SHADOW_COLOUR]
    frame[lay == 2] = palette[colour]
    return frame
