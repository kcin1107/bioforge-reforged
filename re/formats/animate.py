"""Animate a SALSA figure: animate.py BED_DIR MESH.EOR SKEL.SKL LINKS.SKN MOTIONS.MTN MOTION PALETTE.CAM OUT.gif [yaw]"""
import sys, os, math
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eor import Mesh
from render import render, load_palette
import salsa

mesh_p, skl, skn, mtn, motion, cam, out, *rest = sys.argv[1:]
yaw = float(rest[0]) if rest else 135
mesh, skel, links, pal = Mesh(mesh_p), salsa.load_skel(skl), salsa.load_links(skn), load_palette(cam)
frames = salsa.load_motions(mtn)[motion]
posed = []
for pos, rang, limbs in frames:
    f = ((0, 0, pos[2]), rang, limbs)            # keep vertical root motion, drop travel
    posed.append(salsa.pose_vertices(mesh.verts, links, skel, f))
# fixed camera bounds from all frames, in render() view space
def view(P):
    V = np.array(P, float)[:, [0, 2, 1]]; V[:, 2] = -V[:, 2]
    a, b = math.radians(yaw), math.radians(10)
    Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    return V @ Ry.T @ Rx.T
allv = np.vstack([view(p) for p in posed]); bounds = (allv.min(0), allv.max(0))
imgs = [Image.fromarray(render(mesh, p, pal, yaw, bounds=bounds, size=300)) for p in posed]
imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=90, loop=0)
sheet = Image.fromarray(np.hstack([np.array(i) for i in imgs[::max(1, len(imgs) // 6)][:6]]))
sheet.save(os.path.splitext(out)[0] + '_sheet.png')
print(motion, len(frames), 'frames')
