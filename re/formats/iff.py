"""EA IFF-85 reader (big-endian sizes) as used by BioForge. FORM/CAT/LIST nest."""
import struct, sys

CONTAINERS = {b'FORM', b'CAT ', b'LIST'}

def parse(d, off=0, end=None):
    """Yield (id, type_or_None, payload_off, size, children)."""
    end = len(d) if end is None else end
    out = []
    while off + 8 <= end:
        cid = d[off:off+4]; size, = struct.unpack_from('>I', d, off+4)
        p = off + 8
        if cid in CONTAINERS:
            out.append((cid, d[p:p+4], p+4, size-4, parse(d, p+4, p+size)))
        else:
            out.append((cid, None, p, size, None))
        off = p + size + (size & 1)
    return out

def dump(d, nodes, depth=0, maxdata=24, limit=None):
    seen = {}
    for cid, typ, p, size, kids in nodes:
        key = (cid, typ)
        seen[key] = seen.get(key, 0) + 1
        if limit and seen[key] > limit:
            if seen[key] == limit + 1: print('  ' * depth + f"... more {cid.decode()} {typ.decode() if typ else ''}")
            continue
        if kids is not None:
            print('  ' * depth + f"{cid.decode()} {typ.decode()} ({size})")
            dump(d, kids, depth+1, maxdata, limit)
        else:
            print('  ' * depth + f"{cid.decode()} ({size}) {d[p:p+min(size,maxdata)].hex(' ')}")

if __name__ == '__main__':
    lim = 3
    for path in sys.argv[1:]:
        d = open(path, 'rb').read()
        print(f"=== {path} ({len(d)})")
        dump(d, parse(d), limit=lim)
