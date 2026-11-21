"""Decode every frame of every image in the given .CAM files; report failures."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flex import read_flex
from cam import decode_frame
ok = bad = 0
for path in sys.argv[1:]:
    d, ents = read_flex(path)
    for i, off, size, name in ents[1:]:
        if not size: continue
        b = d[off:off+size]
        n, = struct.unpack_from('<H', b, 4)
        for fi in range(n):
            fo, = struct.unpack_from('<I', b, 6 + 6 * fi)
            try: decode_frame(b, fo); ok += 1
            except Exception as ex:
                bad += 1
                if bad <= 15: print(f"FAIL {os.path.basename(path)} {name}[{fi}] hdr={b[:12].hex(' ')} frame={b[fo:fo+10].hex(' ')}: {ex}")
print(f"frames ok {ok}, failed {bad}")
