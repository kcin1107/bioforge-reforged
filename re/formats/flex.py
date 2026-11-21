"""Origin Flex archive (BioForge .FLX / .CAM).

Layout (little-endian):
  0x00  char[0x50]  copyright text, NUL padded
  0x50  u32         magic/flags (0xA1A11A00 seen)
  0x54  u32         entry count
  0x58  u32         version (6 for most, 1 for MUSIC.FLX)
  0x60  u32         entry size: 8 = (off,size); 21 = (off,size,name[13])
  0x80  entries
"""
import struct, sys

def read_flex(path):
    d = open(path, 'rb').read()
    count, ver = struct.unpack_from('<II', d, 0x54)
    esz, = struct.unpack_from('<I', d, 0x60)
    if ver != 6: esz = 8         # MUSIC.FLX (version 1) has no entry size field
    out = []
    for i in range(count):
        p = 0x80 + i * esz
        off, size = struct.unpack_from('<II', d, p)
        name = d[p+8:p+esz].split(b'\0')[0].decode('latin1') if esz > 8 else ''
        out.append((i, off, size, name))
    return d, out

def read_flex_depths(path):
    """Room-file sprite depths: name[9] + s32 at entry offset 17; 0 -> 99999. {} unless 21-byte entries."""
    d = open(path, 'rb').read()
    count, ver = struct.unpack_from('<II', d, 0x54)
    if ver != 6 or struct.unpack_from('<I', d, 0x60)[0] != 21: return {}
    out = {}
    for i in range(count):
        p = 0x80 + i * 21
        name = d[p+8:p+17].split(b'\0')[0].decode('latin1').upper()
        z, = struct.unpack_from('<i', d, p + 17)
        out[name] = z or 99999
    return out

if __name__ == '__main__':
    for path in sys.argv[1:]:
        d, ents = read_flex(path)
        nz = [e for e in ents if e[2]]
        bad = [e for e in nz if e[1] + e[2] > len(d)]
        print(f"{path}: {len(ents)} entries, {len(nz)} non-empty, {len(bad)} out of bounds")
        for i, off, size, name in nz[:12]:
            print(f"   [{i:3}] {name:13} off {off:#9x} size {size:#8x}  {d[off:off+12].hex(' ')}")
