"""Overlay a level's collision boxes (PHYS) and waypoints (WAYP) on a camera's background.

usage: camview.py LEVEL.IFF ROOMS_DIR CAMNAME OUT.png [focal ...] [--mirror]
Projection under test: d = P - eye; x = right.d, y = fwd.d, z = up.d (rows 0,1,2 of R);
u = 160 + f*x/y, v = 100 - f*z/y (screen 320x200).
"""
import sys, os, itertools
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from level import load_level
from flex import read_flex
from cam import frames, palette

def background(rooms, name):
    d, ents = read_flex(os.path.join(rooms, name + '.CAM'))
    pal = palette(d[ents[0][1]:ents[0][1] + 768])
    for i, off, size, n in ents[1:]:
        if n.upper() == name.upper():
            w, h, hx, hy, px, mask = next(frames(d[off:off + size]))
            img = np.frombuffer(pal, np.uint8).reshape(256, 3)[np.frombuffer(bytes(px), np.uint8)].reshape(h, w, 3)
            return Image.fromarray(img)
    raise KeyError(name)

def project(P, cam, f, mirror=False, aspect=1.0):
    d = np.atleast_2d(P) - cam['pos']
    R = cam['R']; x, y, z = d @ R[0], d @ R[1], d @ R[2]
    if mirror: x = -x
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.stack([160 + f * x / y, 100 - f * aspect * z / y, y], 1)

def draw(img, objs, cam, f, mirror, label):
    img = img.copy().convert('RGB'); dr = ImageDraw.Draw(img)
    for o in objs:
        if o['tag'] == 'PHYS':
            a, b = o['pos'], o['pos2']
            C = np.array(list(itertools.product(*zip(a, b))))
            S = project(C, cam, f, mirror)
            for i, j in itertools.combinations(range(8), 2):
                if bin(i ^ j).count('1') == 1 and S[i, 2] > 0 and S[j, 2] > 0:
                    dr.line([tuple(S[i, :2]), tuple(S[j, :2])], fill=(255, 60, 60))
        elif o['tag'] == 'WAYP':
            S = project(o['pos'], cam, f, mirror)[0]
            if S[2] > 0: dr.ellipse([S[0] - 2, S[1] - 2, S[0] + 2, S[1] + 2], fill=(60, 255, 60))
    dr.text((3, 3), label, fill=(255, 255, 0))
    return img

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    lvl, rooms, camname, out, *fs = args
    objs = load_level(lvl)
    cam = next(o for o in objs if o['tag'] == 'CAMR' and o['name'].upper() == camname.upper())
    bg = background(rooms, camname)
    fs = [float(x) for x in fs] or [160, 240, 320, 480]
    tiles = [draw(bg, objs, cam, f, m, f"f={f:g}{' mirror' if m else ''}") for m in (False, True) for f in fs]
    W = Image.new('RGB', (320 * len(fs), 400))
    for k, t in enumerate(tiles): W.paste(t, ((k % len(fs)) * 320, (k // len(fs)) * 200))
    W = W.resize((W.width * 2, W.height * 2), Image.NEAREST)
    W.save(out)
