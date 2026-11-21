"""SALSA skeleton (.SKL), motions (.MTN) and forward kinematics.

SKL: FORM SKEL { VERS u16 (2); LIMB n*39; LOCK; SENS }
  LIMB record: char name[9], s16 parent, s16 rest[3], s16 angle[3], s32 length, s32 offset[3]
MTN: FORM MOTN { (MOTN hdr, PRLE|POSE)* }
  MOTN hdr (83 bytes): char name[...], ..., frame event list (bytes, 0xfe end, 0xff pad),
       +77 u8 nlimbs, +79 u16 rowbytes (18 + 8*nlimbs), +81 u16 nframes
  POSE: nframes * rowbytes raw frames
  PRLE: nframes * 18 raw root records, then RLE stream of nframes*nlimbs*3 s8 angles,
        axis-major: (a0 of limb 0..n-1), (a1 of limb 0..n-1), (a2 ...), each nframes long;
        RLE: c >= 0x80 -> (c-0x80) copies of next byte; else c literal bytes. Runs span channels.
  Frame: s32 root pos[3], s16 root angle[3], per limb s16 angle[3] + u16 scale (0x100)
Angles: 256 units per turn. Matrix rows are the local axes; a limb applies rest then
animated angles, each as rotZ(a[2]), rotX(a[0]), rotY(a[1]) about its local axes (X/Z:
row_i' = c*ri + s*rj; Y: row0' = c*r0 - s*r2, per FUN_1208_2548/2b64/2858), then the
next joint is at pos + rowY * length. Offsets are in the parent's end frame.
"""
import struct, sys, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iff import parse

class Limb:
    def __init__(self, r):
        self.name = r[:9].split(b'\0')[0].decode('latin1')
        self.parent, = struct.unpack_from('<h', r, 9)
        self.rest = struct.unpack_from('<3h', r, 11)
        self.angle = struct.unpack_from('<3h', r, 17)
        self.length, = struct.unpack_from('<i', r, 23)
        self.offset = struct.unpack_from('<3i', r, 27)

def load_skel(path):
    d = open(path, 'rb').read()
    p = d.find(b'LIMB'); n, = struct.unpack_from('>I', d, p + 4)
    return [Limb(d[p + 8 + i * 39: p + 8 + (i + 1) * 39]) for i in range(n // 39)]

def load_motions(path):
    d = open(path, 'rb').read()
    kids = parse(d)[0][4]
    out = {}
    for k in range(0, len(kids) - 1, 2):
        _, _, hp, hs, _ = kids[k]; cid, _, p, s, _ = kids[k + 1]
        h = d[hp:hp + hs]
        name = h[:16].split(b'\0')[0].decode('latin1')
        nl = h[77]; rb, nf = struct.unpack_from('<HH', h, 79)
        b = d[p:p + s]
        frames = []
        if cid == b'POSE':
            for f in range(nf):
                row = b[f * rb:(f + 1) * rb]
                pos = struct.unpack_from('<3i', row, 0); rang = struct.unpack_from('<3h', row, 12)
                limbs = [struct.unpack_from('<3h', row, 18 + 8 * i) for i in range(nl)]
                frames.append((pos, rang, limbs))
        else:
            vals, q = [], 18 * nf
            while q < len(b):
                c = b[q]; q += 1
                if c >= 0x80: vals += [b[q]] * (c - 0x80); q += 1
                else: vals += list(b[q:q + c]); q += c
            vals = [v - 256 if v > 127 else v for v in vals]
            for f in range(nf):
                pos = struct.unpack_from('<3i', b, 18 * f); rang = struct.unpack_from('<3h', b, 18 * f + 12)
                limbs = [tuple(vals[(a * nl + i) * nf + f] for a in range(3)) for i in range(nl)]
                frames.append((pos, rang, limbs))
        out.setdefault(name, frames)
    return out

def load_motion_headers(path):
    """{name: (frame_time, flags, strength, limb, kind, loops)} from each MOTN header. In memory the header sits 6 bytes later (motion+0x52 is file
    byte 76, +0x57 the frame count at 81): frame_time (+0x52) times the figure's MY_SPEED is one frame's duration in
    1/256 ticks of the 60 Hz clock (FUN_1098_0088, FUN_1088_1854); flags (+0x24, byte 30) bit 0x01 marks a turning
    motion whose root yaw is added to the heading (FUN_10a0_1c83). The attack fields (FUN_1088_0708) are strength (+0x1e,
    byte 24), the striking limb index (+0x1f, byte 25) and the kind (+0x25, byte 31): 1 strike, 2 guard, 3 movement. Flags
    bit 0x02 (+0x1e8 once the motion runs, 1098.c:274) marks a motion whose root z is committed to the figure at each wrap
    (MANTLE_*, ladders, iris entries). `loops` is the loop rule of FUN_1088_1854 (1088:1854): the frame event list (count at
    byte 28, entries from byte 32) holds the 0xfe end marker; None when the list is empty."""
    d = open(path, 'rb').read()
    kids = parse(d)[0][4]
    out = {}
    for k in range(0, len(kids) - 1, 2):
        _, _, hp, hs, _ = kids[k]
        h = d[hp:hp + hs]
        events = h[32:32 + h[28]]
        out.setdefault(h[:16].split(b'\0')[0].decode('latin1'),
                       (h[76], h[30], h[24], h[25], h[31], 0xfe in events if events else None))
    return out

def load_col(path):
    """<BODY>.COL (FUN_1088_5fe6): 10 records of u8 limb, u8 mode, s32 half-size (world units) -> [(limb, mode, half)] for
    the used ones (an all-zero half-size is unused). Mode 0 centres the cube on the limb's end, else on its midpoint."""
    d = open(path, 'rb').read()
    recs = [struct.unpack_from('<BBi', d, 6 * i) for i in range(len(d) // 6)]
    return [r for r in recs if r[2]]

def _rot(R, a, axis, sign):
    if not a: return R
    t = a * 2 * math.pi / 256
    c, s = math.cos(t), sign * math.sin(t) * (-1 if axis == 'y' else 1)   # FUN_1208_2858 flips Y
    i, j = {'x': (1, 2), 'y': (0, 2), 'z': (0, 1)}[axis]
    R = R.copy(); ri, rj = R[i].copy(), R[j].copy()
    R[i] = c * ri + s * rj; R[j] = c * rj - s * ri
    return R

def rotate(R, ang, sign=1):
    R = _rot(R, ang[2], 'z', sign); R = _rot(R, ang[0], 'x', sign); return _rot(R, ang[1], 'y', sign)

def solve(skel, frame=None, sign=1):
    """Returns per-limb (start position, rotation matrix rows) for a frame (None = rest)."""
    n = len(skel)
    start, R_out, end, R_end = [None] * n, [None] * n, [None] * n, [None] * n
    root_pos = np.array(frame[0], float) if frame else np.zeros(3)
    root_R = np.eye(3)       # frame[1] (record bytes 12..17) is the per-zone guard table, not a rotation (NOTES: melee hits)
    for i, L in enumerate(skel):
        if L.parent < 0: P, R = root_pos.copy(), root_R.copy()
        else: P, R = end[L.parent].copy(), R_end[L.parent].copy()
        P = P + np.array(L.offset, float) @ R
        R = rotate(R, L.rest, sign)
        anim = frame[2][i] if frame and i < len(frame[2]) else (0, 0, 0)
        R = rotate(R, anim, sign)
        start[i], R_out[i] = P, R
        end[i], R_end[i] = P + R[1] * L.length, R
    return start, R_out, end

def pose_vertices(verts, links, skel, frame, sign=1):
    s0, R0, _ = solve(skel, None, sign)
    s1, R1, _ = solve(skel, frame, sign)
    out = []
    for v, l in zip(verts, links):
        local = R0[l] @ (np.array(v, float) - s0[l])
        out.append(s1[l] + local @ R1[l])
    return out

# ---- the engine's fixed-point FK (FUN_1038_035b via FUN_1040_0c7e) and its foot depth F (FUN_1040_0cf8)
COS_TABLE_OFFSET = 0xfd800 + 0x8f74   # BIOFORGE.EXE: DGROUP (NE segment 83, file 0xfd800) + 0x8f74, 361 bytes


def cos_table(exe_path):
    """The engine's quarter-degree cosine bytes (index 0 is never read; the routines use 256 there)."""
    with open(exe_path, 'rb') as f:
        f.seek(COS_TABLE_OFFSET)
        return f.read(361)


def _s32(x):
    x &= 0xffffffff
    return x - (1 << 32) if x >> 31 else x


def _mul8(a, b):
    """FUN_1210_0c42: (a * b) >> 8 on the 64-bit product, kept to 32 bits."""
    return _s32((a * b) >> 8)


def _quarter(a):
    """FUN_1200_0be3 then >> 6: an 8.8 degree angle as quarter degrees in 0..1439."""
    while a < -0xb400:
        a += 0x16800
    while a > 0xb400:
        a -= 0x16800
    q = a >> 6
    return q + 1440 if q < 0 else q


def _cos8(T, a):
    """FUN_1210_0cca (via FUN_1200_05fd)."""
    q = _quarter(a)
    t = lambda i: 256 if i == 0 else T[i]
    if q < 360:
        return t(q)
    b = q - 720
    if b < 0:
        return -t(-b)
    if b < 360:
        return -t(b)
    return t(720 - b)


def _sin8(T, a):
    """FUN_1210_0c71 (via FUN_1200_063c)."""
    q = _quarter(a)
    t = lambda i: 256 if i == 0 else T[i]
    if q < 360:
        return t(360 - q)
    if q < 720:
        return t(q - 360)
    if q < 1080:
        return -t(1080 - q)
    return -t(q - 1080)


def _rot8(T, M, a, i, j, sign):
    """FUN_1208_2548 (X: rows 1, 2), 2b64 (Z: rows 0, 1), 2858 (Y: rows 0, 2, sign -1); each product >> 8 on its own."""
    if abs(a) < 0x38:
        return
    c, s = _cos8(T, a), _sin8(T, a)
    old = M[i]
    M[i] = [_mul8(x, c) + sign * _mul8(y, s) for x, y in zip(M[i], M[j])]
    M[j] = [_mul8(x, c) - sign * _mul8(y, s) for x, y in zip(M[j], old)]


def _rotate8(T, M, ang):
    """FUN_1030_1054: each SALSA angle becomes whole degrees in 8.8 ((a * 45) >> 5 << 8), applied Z, X, Y."""
    deg = [((a * 45) >> 5) << 8 for a in ang]
    _rot8(T, M, deg[2], 0, 1, 1)
    _rot8(T, M, deg[0], 1, 2, 1)
    _rot8(T, M, deg[1], 0, 2, -1)


def solve_fixed(skel, T):
    """Rest-pose limb END positions and 8.8 matrices (rows) as the engine builds them: root at 0 with the identity
    (256) matrix, file angles, scale 0x100. pos += offset . rows, rotate by rest then current angles, pos += row1 . length."""
    pos, mat = [None] * len(skel), [None] * len(skel)
    for k, L in enumerate(skel):
        if L.parent < 0:
            P, M = [0, 0, 0], [[256, 0, 0], [0, 256, 0], [0, 0, 256]]
        else:
            P, M = list(pos[L.parent]), [list(r) for r in mat[L.parent]]
        for o, r in zip(L.offset, M):
            P = [p + _mul8(x, o) for p, x in zip(P, r)]
        _rotate8(T, M, L.rest)
        _rotate8(T, M, L.angle)
        ln = _mul8(L.length, 0x100 << 8) >> 8
        pos[k], mat[k] = [p + _mul8(x, ln) for p, x in zip(P, M[1])], M
    return pos, mat


def foot_depth(skel, T):
    """F (FUN_1040_0cf8, model+0x88): root z minus the lowest of every limb's z and that z plus the ROOT's row1 z scaled
    by the root length (the code uses the root's vector for every limb). MAN = 2312; matches every INITGAME FIGR record."""
    pos, mat = solve_fixed(skel, T)
    rz = pos[0][2]
    drop = _mul8(mat[0][1][2], _mul8(skel[0].length, 0x100 << 8) >> 8)
    return rz - min([rz] + [min(p[2], p[2] + drop) for p in pos])


def load_links(path):
    d = open(path, 'rb').read(); p = d.find(b'LINK'); n, = struct.unpack_from('>I', d, p + 4)
    return list(struct.unpack_from(f'<{n // 2}H', d, p + 8))

if __name__ == '__main__':
    skel = load_skel(sys.argv[1])
    for i, L in enumerate(skel):
        print(f"{i:2} {L.name:9} parent {L.parent:2} rest {L.rest} len {L.length} off {L.offset}")
    if len(sys.argv) > 2:
        m = load_motions(sys.argv[2])
        print(len(m), 'motions:', ' '.join(f"{k}({len(v)})" for k, v in list(m.items())[:20]))
