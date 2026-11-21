"""BioForge SALSA figure mesh (.EOR, IFF FORM REAL) reader.

FORM REAL
  INFO  char[8] name
  FORM OBJT { FORM ORNT, EXTE }
  FORM APPR / FORM POLY
    INFO u8
    FORM DETA { LVL0 u16[] }          face order / LOD list
    VERT  n * (s32 x, s32 y, s32 z)   bind-pose model space, +Z is up
    FORM TXMS { INFO u16 n_static, u16 n_anim; TXMP*; TXMD*; TXMA* }
      TXMP  char[8] name, u16 w, u16 h, u8 pixels[w*h]
      TXMD  char[8] name, char[] source path
      TXMA  char[8] name, u16 w, u16 h, u16 nframes, u8 pixels[nframes][w*h]
            animated texture; texture indices n_static.. refer to these in order
    FORM TRIS
      FACE  n * (u8 kind, u8 color, u16 v[3])   kind 6 textured, 5/1 flat (color = palette index)
      MAPS  m * (u16 face, u16 tex, 3 * (u16 u, u16 v))       textured faces only
    FORM QUAD   same as TRIS with 4 vertices (FACE 10 bytes, MAPS 20 bytes)
    FORM LINE   FACE n * (u8 kind, u8 color, u16 v0, u16 v1)
    (old files, ITEMS/BLASTER.IFF and PIPE.IFF: TRIS/VTRI + TRIS/UVXY and a TXMS inside TRIS, see below)
    ATTR  n * 9 bytes (unknown)
All payload integers are little-endian; IFF chunk sizes are big-endian.

Old layout (decoded from ITEMS/BLASTER.IFF; every vertex index and map entry fits one byte):
    TRIS/VTRI  n * 8 bytes (u8 kind, u8 v0, u8 v1, u8 v2, u8 colour, 0, 0xff, flag)
    TRIS/UVXY  m * 8 bytes (u8 face, u8 tex, 3 * (u8 u, u8 v))                 textured faces only
    TRIS/TXMS/{INFO,TXMP,TXMA}   as TXMS above, nested inside TRIS
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iff import parse

def _walk(nodes, out, prefix=''):
    for cid, typ, p, size, kids in nodes:
        key = prefix + '/' + (typ or cid).decode().strip()
        if kids is not None: _walk(kids, out, key)
        else: out.setdefault(key, []).append((p, size))
    return out

class Mesh:
    def __init__(self, path):
        d = self.d = open(path, 'rb').read()
        c = _walk(parse(d), {})
        self.chunks = c
        k = lambda suffix: next(v for key, v in c.items() if key.endswith(suffix))
        p, s = k('/VERT')[0]
        self.verts = [struct.unpack_from('<iii', d, p + 12 * i) for i in range(s // 12)]
        # polys: (kind, color, [vertex indices], tex or None, [uv] or None)
        self.polys, self.lines = [], []
        txms = '/REAL/APPR/POLY/TRIS/TXMS' if '/REAL/APPR/POLY/TRIS/VTRI' in c else '/REAL/APPR/POLY/TXMS'
        for p, s in c.get('/REAL/APPR/POLY/TRIS/VTRI', []):
            maps = {}
            for mp, ms in c.get('/REAL/APPR/POLY/TRIS/UVXY', []):
                for i in range(ms // 8):
                    f, t, *uv = d[mp + 8 * i:mp + 8 * i + 8]
                    maps[f] = (t, list(zip(uv[0::2], uv[1::2])))
            for i in range(s // 8):
                kind, *vi, color = d[p + 8 * i:p + 8 * i + 5]
                t, uv = maps.get(i, (None, None))
                self.polys.append((kind, color, vi, t, uv))
        for group, nv in (('TRIS', 3), ('QUAD', 4)):
            fsz, msz = 2 + 2 * nv, 4 + 4 * nv
            faces = [struct.unpack_from(f'<BB{nv}H', d, p + fsz * i)
                     for p, s in c.get(f'/REAL/APPR/POLY/{group}/FACE', []) for i in range(s // fsz)]
            maps = {}
            for p, s in c.get(f'/REAL/APPR/POLY/{group}/MAPS', []):
                for i in range(s // msz):
                    f, t, *uv = struct.unpack_from(f'<{2 + 2 * nv}H', d, p + msz * i)
                    maps[f] = (t, list(zip(uv[0::2], uv[1::2])))
            for i, (kind, color, *vi) in enumerate(faces):
                t, uv = maps.get(i, (None, None))
                self.polys.append((kind, color, vi, t, uv))
        for p, s in c.get('/REAL/APPR/POLY/LINE/FACE', []):
            self.lines += [struct.unpack_from('<BBHH', d, p + 6 * i) for i in range(s // 6)]
        self.textures = []
        for p, s in c.get(txms + '/TXMP', []):
            name = d[p:p+8].split(b'\0')[0].decode('latin1')
            w, h = struct.unpack_from('<HH', d, p + 8)
            self.textures.append((name, w, h, d[p+12:p+12+w*h]))
        # animated textures follow the static ones in the texture index space
        self.anim = {}                                   # texture index -> [frame pixels]
        for p, s in c.get(txms + '/TXMA', []):
            name = d[p:p+8].split(b'\0')[0].decode('latin1')
            w, h, n = struct.unpack_from('<HHH', d, p + 8)
            frames = [d[p+14+k*w*h:p+14+(k+1)*w*h] for k in range(n)]
            self.anim[len(self.textures)] = frames
            self.textures.append((name, w, h, frames[0]))

if __name__ == '__main__':
    m = Mesh(sys.argv[1])
    kinds = {}
    for f in m.polys: kinds[(len(f[2]), f[0])] = kinds.get((len(f[2]), f[0]), 0) + 1
    mapped = sum(1 for f in m.polys if f[3] is not None)
    bad = sum(1 for f in m.polys for v in f[2] if v >= len(m.verts))
    print(f"{len(m.verts)} verts, {len(m.polys)} polys {kinds}, {mapped} mapped, {len(m.lines)} lines, "
          f"{len(m.textures)} textures, {bad} bad indices")
    for t in m.textures: print("  ", t[0], f"{t[1]}x{t[2]}")
