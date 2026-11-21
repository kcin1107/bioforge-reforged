"""Dump the NE header + segment table of a Phar Lap-bound EXE."""
import struct, sys
d = open(sys.argv[1], 'rb').read()
ne = struct.unpack_from('<I', d, 0x3c)[0]
assert d[ne:ne+2] == b'NE'
h = struct.unpack_from('<2sBBHHIHHHHHHHHHHHHHHHHHIHHBB', d, ne)
fields = "sig lver rev enttab entlen crc flags autodata heap stack ip cs sp ss nseg nmod nresnamlen segtab restab resnamtab modreftab impnamtab nresnamtab movent align nres os exetyp".split()
H = dict(zip(fields, h))
for k in fields: print(f"{k:12} {H[k]!r:>12} {H[k]:#x}" if isinstance(H[k], int) else f"{k:12} {H[k]}")
print("\nsegments (idx, fileoff, len, flags, minalloc):")
for i in range(H['nseg']):
    off, ln, fl, mn = struct.unpack_from('<HHHH', d, ne + H['segtab'] + i*8)
    fo = off << H['align']
    print(f"{i+1:3} {fo:#9x} {ln or 0x10000:#7x} {fl:#06x} {'DATA' if fl&1 else 'CODE'} {mn or 0x10000:#7x}")
# resident names
p = ne + H['resnamtab']
print("\nresident names:")
while d[p]:
    n = d[p]; print(" ", d[p+1:p+1+n], struct.unpack_from('<H', d, p+1+n)[0]); p += n+3
p = ne + H['modreftab']
print("module refs:")
for i in range(H['nmod']):
    o = struct.unpack_from('<H', d, p+i*2)[0]; q = ne+H['impnamtab']+o
    print(" ", d[q+1:q+1+d[q]])
