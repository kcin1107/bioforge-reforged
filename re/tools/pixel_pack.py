"""Builds the art pack for View > High-Resolution Art: room pieces and figure textures at 2x or 4x (--scale), still palette indices, in
`--out`. The app builds the same pack itself (PixelPack.swift, with the model converted by convert_model.py); this is the reference and the
route for hand fixes (--export, --overrides).

    <venv with torch, spandrel, numpy, pillow>/bin/python -I re/tools/pixel_pack.py --model 4x_HDCube_200k.pth --all

Output (never committed, it is derived from the game's art): rooms/<CAM>/<ENTRY>.<frame>.frm, monitors/<CAM>/<ENTRY>.<frame>.frm (MONITORS/*.CAM:
the entry named like the file is the screen's background, filtered like a room's; the screen's other elements are drawn plain-doubled, so they are
not built; a CAM without a background is a pointer, and every frame of its first entry is built like a texture, on its own with its own palette;
1x1 dummy frames are skipped) and tex/<fnv1a of the indices>.frm, each one
frame at the pack's scale: 'BFX3', u16 width, height (little-endian), then raw DEFLATE of width*height indices followed by width*height mask
bytes (1 = opaque; the source's mask smoothed by Scale2x, see smooth). Texels outside a texture's mask are 255. (The game's own frame encoding has 16-bit row offsets: too small for 640x400.)
Default --out is ~/Library/Application Support/BioForge/HD/<scale>x, where the app looks.

The model's 4x picture is only a guide: it is halved for 2x, and each new pixel takes the colour of its source neighbourhood closest to it
(pixel_filters.constrain). Room pieces are filtered in place on the finished room, so their edges see what lies behind them.
--export DIR writes the same frames as indexed PNGs; an edited one put in --overrides DIR at the same path replaces the filter's output.
"""
import argparse, glob, os, struct, sys, zlib
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO, 're', 'formats'), os.path.join(REPO, 're', 'tools')]
import numpy as np
from PIL import Image
import cam as camfmt, eor
from flex import read_flex, read_flex_depths
from pixel_filters import constrain, nearest2x

GAME = os.path.join(REPO, 'game', 'app', 'Bioforge')
PAD = 24


def bucket(n, limit):
    """Round n up to a multiple of 32, at most limit: the model sees 10 x 7 input sizes (as PixelPack.swift), so Core ML does not plan each new one."""
    return min((n + 31) // 32 * 32, limit)


def grow(lo, hi, limit):
    """[lo, hi) inside 0..limit grown to bucket(hi - lo): towards the end first, then the start."""
    more = bucket(hi - lo, limit) - (hi - lo)
    right = min(more, limit - hi)
    return lo - (more - right), hi + right


def window(sx0, sy0, sx1, sy1):
    """The crop of the 320x200 screen filtered for a piece on screen: PAD around it, grown with real pixels to a bucketed size."""
    cx0, cx1 = grow(max(0, sx0 - PAD), min(320, sx1 + PAD), 320)
    cy0, cy1 = grow(max(0, sy0 - PAD), min(200, sy1 + PAD), 200)
    return cx0, cy0, cx1, cy1


def padded(up, rgb):
    """up(rgb) for a bucketed size: the edge repeated, the model's picture cropped back."""
    h, w = rgb.shape[:2]
    ph, pw = max(h, bucket(h, 200)), max(w, bucket(w, 320))
    if (ph, pw) == (h, w): return up(rgb)
    big = up(np.pad(rgb, ((0, ph - h), (0, pw - w), (0, 0)), mode='edge'))
    k = big.shape[0] // ph
    return big[:k * h, :k * w]


def fnv1a(b):
    h = 0x811c9dc5
    for c in b: h = ((h ^ c) * 0x01000193) & 0xffffffff
    return h


def base_palette():
    d = open(os.path.join(GAME, 'DATA', 'PALETTE.IFF'), 'rb').read()
    i = d.index(b'PALT', 12)                   # the chunk, not the FORM type at offset 8
    return np.frombuffer(camfmt.palette(d[i + 12:i + 12 + 768]), np.uint8).reshape(256, 3)


def room_entries(path):
    d, ents = read_flex(path)
    pal = np.frombuffer(camfmt.palette(d[ents[0][1]:ents[0][1] + 768]), np.uint8).reshape(256, 3)
    depths = read_flex_depths(path)
    out = []
    for i, off, size, name in ents[1:]:
        if size: out.append((depths.get(name.upper(), 99999), i, name.upper(), list(camfmt.frames(d[off:off + size]))))
    out.sort(key=lambda e: (-e[0], e[1]))
    return pal, out


def paint(img, frame):
    w, h, hx, hy, px, mask = frame
    x0, y0 = -hx, -hy
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(320, x0 + w), min(200, y0 + h)
    if sx1 <= sx0 or sy1 <= sy0: return
    idx = np.frombuffer(bytes(px), np.uint8).reshape(h, w)[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
    m = np.frombuffer(bytes(mask), np.uint8).reshape(h, w)[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] != 0
    img[sy0:sy1, sx0:sx1][m] = idx[m]


def dilate(rgb, solid):
    """Spread opaque colours over transparent texels so the model does not smear the key colour into the edges."""
    rgb, solid = rgb.copy(), solid.copy()
    while not solid.all() and solid.any():
        grown = solid.copy()
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            s = np.roll(solid, shift, axis); c = np.roll(rgb, shift, axis)
            new = s & ~grown
            rgb[new] = c[new]; grown |= new
        solid = grown
    return rgb


def encode(px, mask):
    h, w = px.shape
    z = zlib.compressobj(9, zlib.DEFLATED, -15)
    return b'BFX3' + struct.pack('<HH', w, h) + z.compress(px.astype(np.uint8).tobytes() + mask.astype(np.uint8).tobytes()) + z.flush()


def decode(b):
    assert b[:4] in (b'BFX2', b'BFX3')
    w, h = struct.unpack_from('<HH', b, 4)
    a = np.frombuffer(zlib.decompress(b[8:], -15), np.uint8)
    return a[:w * h].reshape(h, w), a[w * h:].reshape(h, w)


def scale2x(m):
    """Scale2x (EPX) of a 0/1 mask, as PixelPackBuilder.scale2x: each pixel becomes 2x2, and a corner takes the value of the two neighbours beside
    it where they agree and the other two differ. Edges are replicated."""
    p = np.pad(m, 1, mode='edge'); A, B, C, D = p[:-2, 1:-1], p[1:-1, :-2], p[1:-1, 2:], p[2:, 1:-1]
    o = np.zeros((2 * m.shape[0], 2 * m.shape[1]), m.dtype)
    o[0::2, 0::2] = np.where((A == B) & (A != C) & (B != D), A, m)
    o[0::2, 1::2] = np.where((A == C) & (A != B) & (C != D), C, m)
    o[1::2, 0::2] = np.where((B == D) & (B != A) & (D != C), B, m)
    o[1::2, 1::2] = np.where((D == C) & (D != B) & (C != A), D, m)
    return o


def smooth(px, mask, f):
    """The outline of a frame, as PixelPackBuilder.smoothed: `mask` is the source's (HxW), `px` the output at factor f. The mask is Scale2x once
    at 2x, twice at 4x. A sub-pixel that becomes opaque takes the colour of the nearest opaque one (4-neighbour dilation, each pass reading the
    state at its start: up, down, left, right); one that becomes transparent only loses its mask. Returns (px, mask)."""
    src = np.asarray(mask) != 0
    big = nearest2x(src, f); m = src.astype(np.uint8)
    for _ in range(f.bit_length() - 1): m = scale2x(m)
    m = m != 0
    need = m & ~big
    solid, fill = big.copy(), px.copy()
    H, W = big.shape
    while (need & ~solid).any():
        p, ps = np.pad(fill, 1, mode='edge'), np.pad(solid, 1)
        for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
            nb, ns = p[dy:dy + H, dx:dx + W], ps[dy:dy + H, dx:dx + W]
            take = ~solid & ns
            fill[take] = nb[take]; solid |= take
    out = px.copy(); out[need] = fill[need]
    return out, m.astype(np.uint8)


class Writer:
    def __init__(self, out, overrides, export):
        self.out, self.overrides, self.export = out, overrides, export

    def wanted(self, rel):
        def has(d, ext): return bool(d) and os.path.exists(os.path.join(d, rel + ext))
        return not has(self.out, '.frm') or (bool(self.export) and not has(self.export, '.png')) or has(self.overrides, '.png')

    def write(self, rel, px, mask, pal):
        """px, mask: 2x arrays. An override PNG of the same size replaces px."""
        h, w = px.shape
        if self.overrides and os.path.exists(os.path.join(self.overrides, rel + '.png')):
            o = Image.open(os.path.join(self.overrides, rel + '.png'))
            if o.mode != 'P' or o.size != (w, h): sys.exit(f'{rel}.png: needs an indexed PNG of {w}x{h}')
            px = np.asarray(o).astype(np.uint8)
        target = os.path.join(self.out, rel + '.frm')
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f: f.write(encode(px, mask))
        if self.export:
            p = os.path.join(self.export, rel + '.png')
            os.makedirs(os.path.dirname(p), exist_ok=True)
            im = Image.fromarray(px.astype(np.uint8), 'P'); im.putpalette(pal.astype(np.uint8).ravel().tolist()); im.save(p)


def do_room(path, wr, up, f=2):
    room = os.path.splitext(os.path.basename(path))[0].upper()
    pal, entries = room_entries(path)
    finished = np.zeros((200, 320), np.int64)
    for _, _, _, frames in entries: paint(finished, frames[0])
    done = 0
    for _, _, name, frames in entries:
        for k, fr in enumerate(frames):
            w, h, hx, hy, px, mask = fr
            rel = f'rooms/{room}/{name}.{k}'
            m = np.frombuffer(bytes(mask), np.uint8).reshape(h, w)
            if not m.any() or not wr.wanted(rel): continue
            out = nearest2x(np.frombuffer(bytes(px), np.uint8).reshape(h, w).astype(np.int64), f)
            x0, y0 = -hx, -hy
            sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(320, x0 + w), min(200, y0 + h)
            if sx1 > sx0 and sy1 > sy0:                 # the part on screen, filtered in place; the rest stays doubled
                img = finished.copy()
                paint(img, fr)
                cx0, cy0, cx1, cy1 = window(sx0, sy0, sx1, sy1)
                crop = img[cy0:cy1, cx0:cx1]
                big = constrain(crop, up(pal[crop]), pal, factor=f)
                ox, oy, dx, dy = f * (sx0 - cx0), f * (sy0 - cy0), f * (sx0 - x0), f * (sy0 - y0)
                cw, ch = f * (sx1 - sx0), f * (sy1 - sy0)
                out[dy:dy + ch, dx:dx + cw] = big[oy:oy + ch, ox:ox + cw]
            out, sm = smooth(out, m, f)
            wr.write(rel, out, sm, pal)
            done += 1
    return done


def do_textures(wr, up, f=2):
    pal = base_palette()
    done = 0
    for p in sorted(glob.glob(os.path.join(GAME, 'BODY', '*.EOR')) + glob.glob(os.path.join(GAME, 'ITEMS', '*.IFF'))):
        try: m = eor.Mesh(p)
        except Exception: continue
        for i, (name, w, h, px) in enumerate(m.textures):
            for frame in m.anim.get(i, [px]):
                frame = bytes(frame)
                rel = f'tex/{fnv1a(frame):08x}'
                if len(frame) != w * h or not wr.wanted(rel): continue
                idx = np.frombuffer(frame, np.uint8).reshape(h, w).astype(np.int64)
                solid = idx != 255
                if not solid.any(): continue
                out = constrain(idx, up(dilate(pal[idx], solid)), pal, solid, factor=f)
                out[~nearest2x(solid, f)] = 255
                out, mask = smooth(out, solid, f)
                out[mask == 0] = 255
                wr.write(rel, out, mask, pal)
                done += 1
    return done


def do_monitors(wr, up, f=2, names=None):
    """MONITORS/<name>.CAM for each of `names` (default: all): see the module docstring. As the app's monitor pass (PixelPack.swift)."""
    paths = sorted(glob.glob(os.path.join(GAME, 'MONITORS', '*.CAM')))
    if names is not None: paths = [p for p in paths if os.path.splitext(os.path.basename(p))[0].upper() in {n.upper() for n in names}]
    done = 0
    for path in paths:
        mon = os.path.splitext(os.path.basename(path))[0].upper()
        pal, entries = room_entries(path)
        if all(name != mon for _, _, name, _ in entries):   # a pointer (POINTER.CAM, or one MON_SETPTR names): every frame of its first entry
            entries = entries[:1]
        for _, _, name, frames in entries:
            if name == mon:                                  # the background: frame 0 only, as a room piece on itself; nothing else is built
                w, h, hx, hy, px, mask = frames[0]
                rel = f'monitors/{mon}/{name}.0'
                m = np.frombuffer(bytes(mask), np.uint8).reshape(h, w)
                if not m.any() or not wr.wanted(rel): break
                finished = np.zeros((200, 320), np.int64)
                paint(finished, frames[0])
                out = nearest2x(np.frombuffer(bytes(px), np.uint8).reshape(h, w).astype(np.int64), f)
                x0, y0 = -hx, -hy
                sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(320, x0 + w), min(200, y0 + h)
                if sx1 > sx0 and sy1 > sy0:
                    cx0, cy0, cx1, cy1 = window(sx0, sy0, sx1, sy1)
                    crop = finished[cy0:cy1, cx0:cx1]
                    big = constrain(crop, up(pal[crop]), pal, factor=f)
                    ox, oy, dx, dy = f * (sx0 - cx0), f * (sy0 - cy0), f * (sx0 - x0), f * (sy0 - y0)
                    cw, ch = f * (sx1 - sx0), f * (sy1 - sy0)
                    out[dy:dy + ch, dx:dx + cw] = big[oy:oy + ch, ox:ox + cw]
                out, sm = smooth(out, m, f)
                wr.write(rel, out, sm, pal)
                done += 1
                break
            for k, (w, h, hx, hy, px, mask) in enumerate(frames):
                rel = f'monitors/{mon}/{name}.{k}'
                m = np.frombuffer(bytes(mask), np.uint8).reshape(h, w) != 0
                if w * h <= 1 or not m.any() or not wr.wanted(rel): continue
                idx = np.frombuffer(bytes(px), np.uint8).reshape(h, w).astype(np.int64)
                out = constrain(idx, up(dilate(pal[idx], m)), pal, m, factor=f)
                out[~nearest2x(m, f)] = 255
                out, big_mask = smooth(out, m, f)
                out[big_mask == 0] = 255
                wr.write(rel, out, big_mask, pal)
                done += 1
    return done


def level_rooms(level):
    from level import load_level
    objs = load_level(os.path.join(REPO, 'game', 'app', 'GAMEDAT', level.upper() + '.IFF'))
    return sorted({o['name'].upper() for o in objs if o['tag'] == 'CAMR'})


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--model', required=True, help='a 4x model spandrel can load (the pack was made with 4x_HDCube_200k)')
    a.add_argument('--scale', type=int, choices=(2, 4), default=2)
    a.add_argument('--out', help='default: ~/Library/Application Support/BioForge/HD/<scale>x, where the app looks')
    a.add_argument('--level', action='append', default=[], help='rooms of this level (repeatable)')
    a.add_argument('--cam', action='append', default=[], help='one room (repeatable)')
    a.add_argument('--all', action='store_true', help='every room')
    a.add_argument('--no-textures', action='store_true')
    a.add_argument('--monitor', action='append', default=[], help='one monitor, e.g. PIMM, OPTS or POINTER (repeatable)')
    a.add_argument('--no-monitors', action='store_true', help='with --all, skip the monitors')
    a.add_argument('--overrides', help='folder of hand-edited indexed PNGs (rooms/<CAM>/<ENTRY>.<frame>.png, tex/<key>.png)')
    a.add_argument('--export', help='also write every frame made here as an indexed PNG to this folder')
    o = a.parse_args()

    import torch
    from spandrel import ModelLoader                    # loads .pth files through a restricted unpickler
    dev = 'mps' if torch.backends.mps.is_available() else 'cpu'
    model = ModelLoader().load_from_file(o.model)
    if model.scale != 4: sys.exit('need a 4x model')
    model = model.eval().to(dev)

    def model_up(rgb):
        """RGB at the pack's scale: the model's 4x picture, halved by averaging for 2x."""
        t = torch.from_numpy(rgb.astype(np.float32) / 255).permute(2, 0, 1)[None].to(dev)
        with torch.no_grad(): r = model(t)
        big = r[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255
        if o.scale == 4: return big
        h, w = rgb.shape[:2]
        return big.reshape(2 * h, 2, 2 * w, 2, 3).mean((1, 3))

    def up(rgb): return padded(model_up, rgb)

    wr = Writer(o.out or os.path.expanduser(f'~/Library/Application Support/BioForge/HD/{o.scale}x'), o.overrides, o.export)
    names = set(c.upper() for c in o.cam)
    for l in o.level: names |= set(level_rooms(l))
    paths = sorted(glob.glob(os.path.join(GAME, 'ROOMS', '*.CAM')))
    if not o.all: paths = [p for p in paths if os.path.splitext(os.path.basename(p))[0].upper() in names]
    total = 0
    for p in paths:
        n = do_room(p, wr, up, o.scale); total += n
        print(os.path.basename(p), n, flush=True)
    print('room frames', total, flush=True)
    if o.all and not o.no_monitors or o.monitor: print('monitor frames', do_monitors(wr, up, o.scale, None if o.all else o.monitor), flush=True)
    if not o.no_textures: print('textures', do_textures(wr, up, o.scale), flush=True)


if __name__ == '__main__':
    main()
