"""BioForge room/monitor images (.CAM entries) -> PNG.

Image entry: u16 w, u16 h, u16 nframes, then nframes * (u32 off, u16 size).
Frame (at off): u16 rle, u16 w, u16 h, s16 hotx, s16 hoty, u16 rowoff[h].
rowoff[y] is relative to its own position. Row = repeat { u8 skip; if x>=w stop;
u8 n; if rle: (n&1 ? run of n>>1 copies of next byte : n>>1 literal bytes)
                          else: n literal bytes }
until x>=w (no trailing skip byte when the last span ends the row).
Palette entry: 256 * RGB, 6-bit VGA.
"""
import struct, zlib, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flex import read_flex

def palette(b):
    return bytes(min(255, c * 255 // 63) for c in b[:768])

def decode_frame(b, off):
    rle, w, h, hx, hy = struct.unpack_from('<HHHhh', b, off)
    tab = off + 10
    px = bytearray(w * h); mask = bytearray(w * h)
    for y in range(h):
        p = tab + 2 * y + struct.unpack_from('<H', b, tab + 2 * y)[0]
        x = 0
        while x < w:
            x += b[p]; p += 1
            if x >= w: break
            n = b[p]; p += 1
            cnt = n >> 1 if rle else n
            if rle and n & 1:
                c = b[p]; p += 1
                for i in range(cnt): px[y*w+x+i] = c; mask[y*w+x+i] = 1
            else:
                px[y*w+x:y*w+x+cnt] = b[p:p+cnt]; mask[y*w+x:y*w+x+cnt] = b'\1' * cnt; p += cnt
            x += cnt
    return w, h, hx, hy, px, mask

def encode_frame(w, h, pixels, hotx=0, hoty=0, rle=True, mask=None, min_run=4):
    """Inverse of decode_frame: -> frame bytes.  `mask` (optional, 1 = opaque) makes the rest skip bytes; a row ends right
    after its last span.  RLE: runs of >= min_run equal pixels become (count<<1|1, byte), the rest literals (count<<1);
    counts are capped at 127 (rle) / 255 (raw) per span.  min_run=4 reproduces the native save thumbnail
    byte for byte (re/out/native_save/GAME1.IM1)."""
    rows = []
    for y in range(h):
        row, x, line = bytearray(), 0, pixels[y*w:(y+1)*w]
        ok = [True] * w if mask is None else [bool(m) for m in mask[y*w:(y+1)*w]]
        cap = 127 if rle else 255
        while x < w:
            s = x
            while x < w and not ok[x]: x += 1
            while x - s > 255:                                  # skip bytes are u8: a zero-length span continues
                row += bytes([255, 0]); s += 255
            if x >= w:
                row.append(x - s); break
            row.append(x - s)
            e, first = x, True
            while e < w and ok[e]: e += 1                       # opaque span [x, e)
            while x < e:
                if not first: row.append(0)                     # every span is preceded by a skip byte
                first = False
                r = x + 1
                while r < e and line[r] == line[x]: r += 1
                if rle and r - x >= min_run:
                    n = min(r - x, cap); row += bytes([n << 1 | 1, line[x]]); x += n
                    continue
                q = x
                while q < e and q - x < cap and not (rle and q + min_run <= e and len(set(line[q:q+min_run])) == 1): q += 1
                q = max(q, x + 1)
                row += bytes([(q - x) << 1 if rle else q - x]) + bytes(line[x:q]); x = q
        rows.append(bytes(row))
    off, pos = [], 0
    for y in range(h):
        off.append(2 * h - 2 * y + pos); pos += len(rows[y])
    return struct.pack('<HHHhh', 1 if rle else 0, w, h, hotx, hoty) + struct.pack('<%dH' % h, *off) + b''.join(rows)

def frames(b):
    w, h, n = struct.unpack_from('<HHH', b, 0)
    for i in range(n):
        off, = struct.unpack_from('<I', b, 6 + 6 * i)
        yield decode_frame(b, off)

def write_png(path, w, h, px, pal, mask=None):
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            c = px[y*w+x]
            rows += pal[c*3:c*3+3] + bytes([255 if (mask is None or mask[y*w+x]) else 0])
    def chunk(t, data): return struct.pack('>I', len(data)) + t + data + struct.pack('>I', zlib.crc32(t + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) \
        + chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + chunk(b'IEND', b'')
    open(path, 'wb').write(png)

if __name__ == '__main__':
    src, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    d, ents = read_flex(src)
    pal = palette(d[ents[0][1]:ents[0][1] + ents[0][2]])
    base = os.path.splitext(os.path.basename(src))[0]
    for i, off, size, name in ents[1:]:
        if not size: continue
        b = d[off:off+size]
        for fi, (w, h, hx, hy, px, mask) in enumerate(frames(b)):
            write_png(f"{outdir}/{base}_{name}_{fi:02}.png", w, h, px, pal, mask)
            if fi == 0: print(f"{name}: {w}x{h} hotspot ({hx},{hy}) frames {struct.unpack_from('<H', b, 4)[0]}")
