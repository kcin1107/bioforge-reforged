"""Parse a SALSA .BED descriptor and render a contact sheet of one motion.

usage: bed.py FIGURE.BED PALETTE.CAM OUT.png [MOTION] [yaw]
"""
import sys, os, re, math
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eor import Mesh
from render import render, load_palette
import salsa

def read_bed(path):
    out, base = {}, os.path.dirname(path)
    files = {f.upper(): f for f in os.listdir(base)}
    for line in open(path, encoding='latin1'):
        m = re.match(r'\s*(\w+)\s*=\s*([^\s;]+)', line)
        if not m: continue
        key, val = m.group(1).upper(), m.group(2)
        names = [files.get(v.upper(), v) for v in val.split('+')]
        out[key] = [os.path.join(base, n) for n in names]
    return out

if __name__ == '__main__':
    bed, cam, out, *rest = sys.argv[1:]
    b = read_bed(bed)
    mesh, skel, links = Mesh(b['REAL'][0]), salsa.load_skel(b['SKEL'][0]), salsa.load_links(b['SKIN'][0])
    motions = {}
    for f in b.get('LIST', b['MOTN']):
        if os.path.exists(f): motions.update({k: v for k, v in salsa.load_motions(f).items() if k not in motions})
    name = rest[0] if rest and rest[0] in motions else next(iter(motions))
    yaw = float(rest[1]) if len(rest) > 1 else 135
    frames = motions[name]
    assert len(links) == len(mesh.verts), (len(links), len(mesh.verts))
    pick = frames[::max(1, len(frames) // 5)][:5]
    posed = [salsa.pose_vertices(mesh.verts, links, skel, ((0, 0, p[2]), r, l)) for p, r, l in pick]
    def view(P):
        V = np.array(P, float)[:, [0, 2, 1]]; V[:, 2] = -V[:, 2]
        a, c = math.radians(yaw), math.radians(10)
        Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        Rx = np.array([[1, 0, 0], [0, math.cos(c), -math.sin(c)], [0, math.sin(c), math.cos(c)]])
        return V @ Ry.T @ Rx.T
    allv = np.vstack([view(p) for p in posed])
    pal = load_palette(cam)
    tiles = [render(mesh, p, pal, yaw, bounds=(allv.min(0), allv.max(0)), size=200) for p in posed]
    Image.fromarray(np.hstack(tiles)).save(out)
    print(f"{os.path.basename(bed)}: {len(skel)} limbs, {len(motions)} motions, showing {name} ({len(frames)} frames)")
