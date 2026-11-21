"""Render a mesh with its rest-pose skeleton drawn on top (front + side), for both sign conventions."""
import sys, os, math
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eor import Mesh
from render import render, load_palette
import salsa

def project(points, verts, yaw, size=360, pitch=10.0):
    # mirror render(): same normalisation computed from the mesh vertices
    def xf(P):
        V = np.array(P, float)[:, [0, 2, 1]]; V[:, 2] = -V[:, 2]
        a, b = math.radians(yaw), math.radians(pitch)
        Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
        return V @ Ry.T @ Rx.T
    V = xf(verts); lo, hi = V.min(0), V.max(0)
    scale = 0.9 * size / max(hi[0] - lo[0], hi[1] - lo[1], 1)
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    P = xf(points)
    return [((p[0] - cx) * scale + size / 2, size / 2 - (p[1] - cy) * scale) for p in P]

mesh_path, skl, cam, out = sys.argv[1:5]
mesh, skel, pal = Mesh(mesh_path), salsa.load_skel(skl), load_palette(cam)
tiles = []
for sign in (1, -1):
    s, R, e = salsa.solve(skel, None, sign)
    for yaw in (180, 90):
        img = Image.fromarray(render(mesh, mesh.verts, pal, yaw)); dr = ImageDraw.Draw(img)
        A = project(s, mesh.verts, yaw); B = project(e, mesh.verts, yaw)
        for i, L in enumerate(skel):
            dr.line([A[i], B[i]], fill=(255, 40, 40), width=2); dr.ellipse([A[i][0]-2, A[i][1]-2, A[i][0]+2, A[i][1]+2], fill=(255, 255, 0))
        dr.text((4, 4), f"sign {sign:+d} yaw {yaw}", fill=(255, 255, 255))
        tiles.append(np.array(img))
Image.fromarray(np.hstack(tiles)).save(out)
