"""Score camera projection hypotheses by how well projected PHYS box edges land on image edges."""
import sys, os, glob, itertools
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from level import load_level
from camview import background

def edges(img):
    g = np.asarray(img.convert('L'), float)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]; gy[1:-1] = g[2:] - g[:-2]
    return np.hypot(gx, gy)

def segments(objs):
    segs = []
    for o in objs:
        if o['tag'] != 'PHYS': continue
        C = np.array(list(itertools.product(*zip(o['pos'], o['pos2']))))
        for i, j in itertools.combinations(range(8), 2):
            if bin(i ^ j).count('1') == 1: segs.append((C[i], C[j]))
    return segs

def score(E, segs, eye, R, f, asp=1.0, mirror=False, cx=160, cy=100, n=24):
    t = np.linspace(0, 1, n)[:, None]
    tot = cnt = 0
    for a, b in segs:
        P = a + t * (b - a) - eye
        x, y, z = P @ R[0], P @ R[1], P @ R[2]
        if mirror: x = -x
        ok = y > 1
        u = cx + f * x[ok] / y[ok]; v = cy - f * asp * z[ok] / y[ok]
        m = (u >= 0) & (u < 319) & (v >= 0) & (v < 199)
        if m.sum() < 4: continue
        tot += E[v[m].astype(int), u[m].astype(int)].sum(); cnt += m.sum()
    return tot / cnt if cnt else 0, cnt

if __name__ == '__main__':
    rooms = 'game/app/Bioforge/ROOMS'
    cams = []
    for lvl in sorted(glob.glob('game/app/GAMEDAT/*.IFF')):
        objs = load_level(lvl); segs = segments(objs)
        for c in objs:
            if c['tag'] != 'CAMR': continue
            try: E = edges(background(rooms, c['name']))
            except Exception: continue
            cams.append((os.path.basename(lvl), c, segs, E))
    print(len(cams), 'cameras with backgrounds')
    base = np.mean([E.mean() for *_, E in cams])
    print('random-pixel baseline', round(base, 2))
    res = []
    for eye_key in ('pos', 'vec'):
        for mirror in (False, True):
            for f in (150, 204.5, 260, 320, 409, 500):
                s = [score(E, segs, c[eye_key], c['R'], f, 1.0, mirror)[0] for _, c, segs, E in cams]
                res.append((np.mean(s), eye_key, mirror, f))
    for r in sorted(res, reverse=True)[:12]: print(f"score {r[0]:6.2f}  eye={r[1]} mirror={r[2]} f={r[3]}")
