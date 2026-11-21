"""Composite a posed SALSA figure into a room through its game camera.

usage: scene.py LEVEL.IFF CAMNAME FIGURE.BED MOTION FRAME WAYPOINT YAW OUT.png [dz]
Camera model (FUN_1178_0000 + FUN_1150_19a3): d = P - cam.pos; x = R0.d, y = R1.d (depth), z = R2.d;
u = 160 + 204.5 * x / y; v = 100 - 204.5 * 0.833 * z / y.
"""
import sys, os, math
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from level import load_level
from camview import background
from flex import read_flex
from cam import palette
from eor import Mesh
from render import rasterize
from bed import read_bed
import salsa

FX, ASPECT, CX, CY = 204.5, 0.833, 160, 100

def project(P, cam):
    d = np.asarray(P, float) - cam['pos']; R = cam['R']
    x, y, z = d @ R[0], d @ R[1], d @ R[2]
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.stack([CX + FX * x / y, CY - FX * ASPECT * z / y, y], 1)

def place(verts, at, yaw_deg, dz=0.0):
    a = math.radians(yaw_deg); c, s = math.cos(a), math.sin(a)
    V = np.asarray(verts, float)
    return np.stack([c * V[:, 0] - s * V[:, 1], s * V[:, 0] + c * V[:, 1], V[:, 2] + dz], 1) + at

if __name__ == '__main__':
    lvl, camname, bedp, motion, frame, wp, yaw, out, *rest = sys.argv[1:]
    dz = float(rest[0]) if rest else 0.0
    objs = load_level(lvl)
    cam = next(o for o in objs if o['tag'] == 'CAMR' and o['name'].upper() == camname.upper())
    at = next(o for o in objs if o['name'].upper() == wp.upper())['pos']
    rooms = os.path.join(os.path.dirname(os.path.dirname(lvl)), 'Bioforge', 'ROOMS')
    d, ents = read_flex(os.path.join(rooms, camname.upper() + '.CAM'))
    pal = np.frombuffer(palette(d[ents[0][1]:ents[0][1] + 768]), np.uint8).reshape(256, 3)
    img = np.array(background(rooms, camname).convert('RGB'))
    b = read_bed(bedp)
    mesh, skel, links = Mesh(b['REAL'][0]), salsa.load_skel(b['SKEL'][0]), salsa.load_links(b['SKIN'][0])
    motions = {}
    for f in b.get('LIST', b['MOTN']):
        if os.path.exists(f): motions.update({k: v for k, v in salsa.load_motions(f).items() if k not in motions})
    pos, rang, limbs = motions[motion][int(frame)]
    V = salsa.pose_vertices(mesh.verts, links, skel, ((0, 0, pos[2]), rang, limbs))
    S = project(place(V, at, float(yaw), dz), cam)
    zbuf = np.full(img.shape[:2], np.inf)
    rasterize(mesh, S, pal, img, zbuf)
    Image.fromarray(img).resize((640, 400), Image.NEAREST).save(out)
    print('figure at', at.astype(int), 'screen', S[:, :2].min(0).astype(int), S[:, :2].max(0).astype(int))
