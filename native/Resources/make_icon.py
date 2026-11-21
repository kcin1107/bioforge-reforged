"""Draws native/Resources/AppIcon.png, the app icon (1024 x 1024, full-bleed square: macOS rounds the corners itself).

    re/.venv/bin/python -I native/Resources/make_icon.py

Original artwork, not taken from the game: a steel gear ring (the machine) around a two-strand helix (the bio), on a dark slate gradient.
HIG "App icons": a simple background, a few bold filled shapes, centred, no text, no added shadows or glows."""
import math
import os

from PIL import Image, ImageDraw

SIZE, SCALE = 1024, 4                    # drawn at 4x and scaled down for smooth edges
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'AppIcon.png')


def frange(a, b, steps):
    return [a + (b - a) * i / steps for i in range(steps + 1)]


def brush(d, pts, width, color):
    """A round brush along the points: smooth thick strokes with round ends."""
    r = width / 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def main():
    n = SIZE * SCALE
    img = Image.new('RGB', (n, n))
    top, bottom = (38, 58, 70), (11, 18, 24)
    px = ImageDraw.Draw(img)
    for y in range(n):
        t = y / (n - 1)
        px.line([(0, y), (n, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))

    layer = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = n / 2
    steel = (178, 190, 198, 255)
    # gear: ring plus eight teeth with rounded ends
    outer, inner = 0.34 * n, 0.255 * n
    tooth_w, tooth_out = 0.10 * n, outer + 0.07 * n
    for k in range(8):
        a = math.radians(k * 45 + 22.5)
        dx, dy = math.cos(a), math.sin(a)
        brush(d, [(c + dx * r, c + dy * r) for r in frange(outer - 0.03 * n, tooth_out - tooth_w / 2, 60)], tooth_w, steel)
    d.ellipse([c - outer, c - outer, c + outer, c + outer], fill=steel)
    d.ellipse([c - inner, c - inner, c + inner, c + inner], fill=(0, 0, 0, 0))

    # helix: two thick strands inside the ring, rungs behind them
    amber, teal, rung = (240, 150, 40, 255), (40, 200, 180, 255), (220, 228, 234, 255)
    height, amp, width = 0.40 * n, 0.105 * n, 0.06 * n
    turns = 1.25

    def x_at(t, phase):
        return c + amp * math.sin(2 * math.pi * turns * t + phase)

    def y_at(t):
        return c - height / 2 + height * t

    for i in range(1, 7):
        t = i / 7
        xa, xb = x_at(t, 0.0), x_at(t, math.pi)
        if abs(xa - xb) > 1.6 * width:
            brush(d, [(x, y_at(t)) for x in frange(min(xa, xb), max(xa, xb), 40)], 0.03 * n, rung)
    for color, phase in ((teal, math.pi), (amber, 0.0)):
        brush(d, [(x_at(t, phase), y_at(t)) for t in frange(0, 1, 400)], width, color)

    img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
    img.resize((SIZE, SIZE), Image.LANCZOS).save(OUT)
    print(OUT)


if __name__ == '__main__':
    main()
