"""Software preview renderer for .EOR meshes: z-buffered, textured, flat-shaded.

usage: render.py MESH.EOR PALETTE.CAM OUT.png [yaw_degrees ...]
Optional --skel SKL --skin SKN --motion MTN:NAME:FRAME pose the mesh (see salsa.py).
"""
import sys, os, math
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eor import Mesh
from flex import read_flex

def load_palette(cam):
    d, ents = read_flex(cam)
    p = np.frombuffer(d[ents[0][1]:ents[0][1] + 768], np.uint8).reshape(256, 3).astype(np.int32)
    return np.clip(p * 255 // 63, 0, 255).astype(np.uint8)

def draw_poly(mesh, pi, S, pal, img, zbuf=None):
    """Draw polygon pi of mesh from screen coords S[:, (x, y, depth)]; zbuf=None means always draw."""
    H, W = img.shape[:2]
    texs = mesh.textures
    kind, color, vi, t, uv = mesh.polys[pi]
    tris = [(0, 1, 2)] if len(vi) == 3 else [(0, 1, 2), (0, 2, 3)]
    for tri in tris:
        P = S[[vi[k] for k in tri]]
        if not np.isfinite(P).all() or (P[:, 2] <= 0).any(): continue
        UV = np.array([uv[k] for k in tri], float) if uv and t is not None and t < len(texs) else None
        xs, ys = P[:, 0], P[:, 1]
        x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max()))
        y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max()))
        if x1 < x0 or y1 < y0: continue
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-9: continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        w2 = 1 - w0 - w1
        m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not m.any(): continue
        z = w0 * P[0, 2] + w1 * P[1, 2] + w2 * P[2, 2]
        if zbuf is not None:
            zb = zbuf[y0:y1 + 1, x0:x1 + 1]
            m &= z < zb
        if UV is not None:
            name, tw, th, px = texs[t]
            u = np.clip((w0 * UV[0, 0] + w1 * UV[1, 0] + w2 * UV[2, 0]).astype(int), 0, tw - 1)
            v = np.clip((w0 * UV[0, 1] + w1 * UV[1, 1] + w2 * UV[2, 1]).astype(int), 0, th - 1)
            idx = np.frombuffer(px, np.uint8).reshape(th, tw)[v, u]
            m &= idx != 0xff             # palette 255 is the texture's magenta transparent texel
        else:
            idx = np.full(z.shape, color, np.uint8)
        if zbuf is not None: zb[m] = z[m]
        img[y0:y1 + 1, x0:x1 + 1][m] = pal[idx[m]]

def rasterize(mesh, S, pal, img, zbuf):
    """Draw mesh polys given per-vertex screen coords S[:, (x, y, depth)] into img/zbuf."""
    for pi in range(len(mesh.polys)): draw_poly(mesh, pi, S, pal, img, zbuf)

def render(mesh, verts, pal, yaw=0.0, pitch=10.0, size=360, bounds=None):
    V = np.array(verts, float)[:, [0, 2, 1]]             # model is Z-up; view space is Y-up
    V[:, 2] = -V[:, 2]
    a, b = math.radians(yaw), math.radians(pitch)
    Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    V = V @ Ry.T @ Rx.T
    lo, hi = (V.min(0), V.max(0)) if bounds is None else bounds
    scale = 0.9 * size / max(hi[0] - lo[0], hi[1] - lo[1], 1)
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    S = np.stack([(V[:, 0] - cx) * scale + size / 2, size / 2 - (V[:, 1] - cy) * scale, V[:, 2]], 1)
    img = np.full((size, size, 3), 40, np.uint8)
    zbuf = np.full((size, size), np.inf)
    rasterize(mesh, S, pal, img, zbuf)
    return img

if __name__ == '__main__':
    mesh_path, cam, out, *yaws = sys.argv[1:]
    mesh = Mesh(mesh_path)
    pal = load_palette(cam)
    yaws = [float(y) for y in yaws] or [0, 90, 180]
    Image.fromarray(np.hstack([render(mesh, mesh.verts, pal, y) for y in yaws])).save(out)
