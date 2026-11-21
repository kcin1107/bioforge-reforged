"""Depth-sorted (painter) compositor: room sprites and 3D character polygons in one draw list.

Occlusion model (from the disassembly):
  * Every non-palette entry of a room .CAM is a cel (FUN_1110_051f builds the frame cel list,
    FUN_1110_0d9c adds the scene-element cels), including the background entry and full-screen
    320x200 overlays. Each cel draws one frame with its top-left at (-hotx, -hoty).
  * Sprite depth is the s32 at entry offset 17 (right after char name[9]); 0 -> 99999
    (FUN_1108_14fa / FUN_10f0_1dc8, see flex.read_flex_depths).
  * Each character polygon is its own cel. Line primitives use the average vertex depth
    (FUN_1158_0d03, verified); FUN_1170_0197 gives polygon cels the global depth. For
    triangles/quads the vertex average is our best INFERENCE, not verified.
  * Cels are sorted by depth descending (farthest first) and drawn in order, no z-buffer.
    Ties: sprites before polygons.

usage: compose.py LEVEL.IFF CAMNAME FIGURE.BED MOTION FRAME WHERE YAW OUT.png
                  [--depth D] [--side S] [--lift Z] [--frame NAME=K ...] [--verbose]
WHERE is a level object name, or 'cam': in front of the camera at camera depth D (default 10000),
offset sideways by S, raised by Z world units (demo aid), at the floor height of the level's first WAYP seen in the lower half of the
camera view (falls back to the very first WAYP).
"""
import sys, os
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from level import load_level
from flex import read_flex, read_flex_depths
from cam import frames, palette
from eor import Mesh
from render import draw_poly
from bed import read_bed
from scene import project, place
import salsa

def rooms_dir(level_path):
    return os.path.join(os.path.dirname(os.path.dirname(level_path)), 'Bioforge', 'ROOMS')

def compose(level_path, camname, figures, sprite_frames=None, verbose=False, return_cels=False, indexed=False, flats=None):
    """figures: [(mesh, posed_world_vertices)]; sprite_frames: {SPRITE_NAME: frame index}; flats: [(depth, (w, h, hx, hy, px, mask))]
    extra sprite cels (MAKEFLATOBJECT) drawn with top-left (-hx, -hy), depth-sorted like the room's sprites.
    indexed=True returns the 200x320 palette-index buffer instead of RGB (same drawing code, identity palette)."""
    sprite_frames = {k.upper(): v for k, v in (sprite_frames or {}).items()}
    cam = next(o for o in load_level(level_path) if o['tag'] == 'CAMR' and o['name'].upper() == camname.upper())
    path = os.path.join(rooms_dir(level_path), camname.upper() + '.CAM')
    d, ents = read_flex(path)
    depths = read_flex_depths(path)
    pal = np.frombuffer(palette(d[ents[0][1]:ents[0][1] + 768]), np.uint8).reshape(256, 3)
    if indexed: pal = np.arange(256, dtype=np.uint8)[:, None]
    cels = []                                    # (depth, kind 0=sprite 1=poly, order, name, payload)
    for i, off, size, name in ents[1:]:
        if not size: continue
        fr = list(frames(d[off:off + size]))
        w, h, hx, hy, px, mask = fr[min(sprite_frames.get(name.upper(), 0), len(fr) - 1)]
        cels.append((depths.get(name.upper(), 99999), 0, i, name, (w, h, hx, hy, px, mask)))
    for k, (depth, frame) in enumerate(flats or ()):
        cels.append((depth, 0, 1000000 + k, f'flat{k}', frame))
    for fi, (mesh, V) in enumerate(figures):
        S = project(V, cam)
        for pi, (kind, color, vi, t, uv) in enumerate(mesh.polys):
            z = S[list(vi), 2]
            if not np.isfinite(z).all(): continue
            cels.append((float(z.mean()), 1, fi * 100000 + pi, f'fig{fi}.poly{pi}', (mesh, pi, S)))
    cels.sort(key=lambda c: (-c[0], c[1], c[2]))
    img = np.zeros((200, 320, 1 if indexed else 3), np.uint8)
    for depth, kind, _, name, p in cels:
        if verbose: print(f'{name:14} depth {depth:.0f}')
        if kind == 0:
            w, h, hx, hy, px, mask = p
            x0, y0 = -hx, -hy
            sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(320, x0 + w), min(200, y0 + h)
            if sx1 <= sx0 or sy1 <= sy0: continue
            idx = np.frombuffer(bytes(px), np.uint8).reshape(h, w)[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
            m = np.frombuffer(bytes(mask), np.uint8).reshape(h, w)[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] != 0
            img[sy0:sy1, sx0:sx1][m] = pal[idx[m]]
        else:
            draw_poly(p[0], p[1], p[2], pal, img)
    if indexed: img = img[:, :, 0]
    return (img, cels) if return_cels else img

if __name__ == '__main__':
    args = sys.argv[1:]
    verbose = '--verbose' in args
    opts, pos, i = {'--depth': 10000.0, '--side': 0.0, '--lift': 0.0}, [], 0
    fr = {}
    while i < len(args):
        a = args[i]
        if a in opts: opts[a] = float(args[i + 1]); i += 2
        elif a == '--frame': k, v = args[i + 1].split('='); fr[k] = int(v); i += 2
        elif a == '--verbose': i += 1
        else: pos.append(a); i += 1
    lvl, camname, bedp, motion, frame, where, yaw, out = pos
    objs = load_level(lvl)
    cam = next(o for o in objs if o['tag'] == 'CAMR' and o['name'].upper() == camname.upper())
    if where.lower() == 'cam':
        # floor height: first WAYP on screen in the lower half of this camera within 3x the requested depth (the level's very first WAYP is often in another room)
        wps = [o for o in objs if o['tag'] == 'WAYP']
        vis = lambda o: (lambda s: 0 < s[2] < 3 * opts['--depth'] and 0 <= s[0] < 320 and 100 <= s[1] < 200)(project([o['pos']], cam)[0])
        floor = next((o for o in wps if vis(o)), wps[0])['pos'][2]
        R, c = cam['R'], np.asarray(cam['pos'], float)
        # solve world (x, y) at z=floor for camera-space depth D and sideways offset S
        A = np.array([[R[0][0], R[0][1]], [R[1][0], R[1][1]]])
        rhs = np.array([opts['--side'], opts['--depth']]) - np.array([R[0][2], R[1][2]]) * (floor - c[2])
        xy = np.linalg.solve(A, rhs) + c[:2]
        at = np.array([xy[0], xy[1], floor + opts['--lift']], float)
    else:
        at = np.asarray(next(o for o in objs if o['name'].upper() == where.upper())['pos'], float)
    b = read_bed(bedp)
    mesh, skel, links = Mesh(b['REAL'][0]), salsa.load_skel(b['SKEL'][0]), salsa.load_links(b['SKIN'][0])
    motions = {}
    for f in b.get('LIST', b['MOTN']):
        if os.path.exists(f): motions.update({k: v for k, v in salsa.load_motions(f).items() if k not in motions})
    p, rang, limbs = motions[motion][int(frame)]
    V = place(salsa.pose_vertices(mesh.verts, links, skel, ((0, 0, p[2]), rang, limbs)), at, float(yaw))
    img = compose(lvl, camname, [(mesh, V)], fr, verbose)
    Image.fromarray(img).resize((640, 400), Image.NEAREST).save(out)
    S = project(V, cam)
    print('figure at', at.astype(int), 'screen', S[:, :2].min(0).astype(int), S[:, :2].max(0).astype(int))
