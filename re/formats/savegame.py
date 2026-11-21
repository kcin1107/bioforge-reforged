"""BioForge saved-game state: GAMEDAT/ (the native play directory) and the .im1 save container.

    savegame.py dump GAMEDAT_DIR            human-readable summary of every piece
    savegame.py roundtrip GAMEDAT_DIR       decode -> encode -> byte-compare every file
    savegame.py diff GAMEDAT_DIR [INITGAME] saved vs initial level objects, VARS vs defaults
    savegame.py pack GAMEDAT_DIR OUT.im1    pack a directory like FUN_1140_134f (see Im1)
    savegame.py unpack IN.im1 OUT_DIR       extract like FUN_11f8_0f03

Everything is derived from the executable (function citations are in the docstrings) and checked against the shipped native
sample game/app/GAMEDAT.  Anything not decoded stays raw bytes; guesses are marked ASSUMPTION.

Files (all written by FUN_1148_0076, the save action; read back by FUN_1148_0490 / FUN_1148_18d3):
  MISC.DAT     449 bytes, raw field dump                              -> Misc
  SCRIPT.DAT   Flex archive of the kernel task table (FUN_1148_1523)  -> ScriptDat
  LISTS.FLX    Flex archive of the log lists (FUN_1278_13ec)          -> Lists
  VARS.DEF / SOUNDS.DEF  text (FUN_1118_4c7f)                         -> DefFile
  <LEVEL>.IFF  FORM OBJS of the level objects (FUN_1148_1404)         -> LevelIff
"""
import argparse
import collections
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import level  # noqa: E402
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
GAMEDAT = os.path.join(ROOT, 'game', 'app', 'GAMEDAT')
INITGAME = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'INITGAME')
SCRIPT_DIR = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'SCRIPT')
DGROUP = os.path.join(ROOT, 're', 'dgroup.bin')          # data segment image: class-name strings of the task table

LEVELS = ('BEACH', 'CHAOS', 'CONTROL', 'DIGSITE', 'LANDPAD', 'PLATFORM', 'TANKS', 'TITLE', 'TOWER', 'TUNROOM')


def cstr(b):
    return b.split(b'\0')[0].decode('latin1')


# ---------------------------------------------------------------------------------------------------------- Flex
class FlexEntry:
    def __init__(self, data=b'', tail=b''):
        self.data, self.tail = data, tail           # tail = entry record bytes after (offset, size): names etc.


class Flex:
    """Origin Flex archive as the engine writes it (FUN_1200_0018 create, FUN_11f8_1355 header, FUN_11f8_1479 checksum).

    Header (0x80 bytes): char comment[0x50] NUL padded; 0x50 magic 00 1A A1 A1 (FUN_11f8_1355); 0x54 u32 entry count;
    0x58 u16 version 6; 0x5A u16 0; 0x60 u32 entry size; 0x64 u16 checksum; 0x66 u16 stale (uninitialised memory in the
    native files, kept verbatim).  checksum = sum of the u16 at offsets 0, 4, 8 .. 0x7C without the checksum itself, mod
    2**16 (verified on every shipped .FLX/.CAM and on SCRIPT.DAT/LISTS.FLX).  Entry i is at 0x80 + i*size: u32 offset,
    u32 size, then `size - 8` bytes (`tail`).  Data follows the table, entries in index order, no padding (verified);
    an empty entry is (0, 0)."""
    MAGIC = b'\x00\x1a\xa1\xa1'

    def __init__(self, hdr, entries, esz, order=None):
        # order: entry indices in data order; .im1 stores entry 0 (the thumbnail) after the files
        self.hdr, self.entries, self.esz, self.order = bytes(hdr), entries, esz, order

    @staticmethod
    def checksum(hdr):
        s = sum(struct.unpack_from('<H', hdr, o)[0] for o in range(0, 0x80, 4))
        return (s - struct.unpack_from('<H', hdr, 0x64)[0]) & 0xFFFF

    @classmethod
    def parse(cls, d):
        if d[0x50:0x54] != cls.MAGIC:
            raise ValueError('not a Flex archive (magic)')
        count, ver = struct.unpack_from('<II', d, 0x54)
        esz, = struct.unpack_from('<I', d, 0x60)
        if struct.unpack_from('<H', d, 0x64)[0] != cls.checksum(d[:0x80]):
            raise ValueError('Flex header checksum mismatch')
        entries, spans = [], []
        for i in range(count):
            p = 0x80 + i * esz
            off, size = struct.unpack_from('<II', d, p)
            entries.append(FlexEntry(d[off:off + size] if size else b'', d[p + 8:p + esz]))
            if size: spans.append((off, size, i))
        pos = 0x80 + count * esz
        for off, size, i in sorted(spans):
            if off != pos:
                raise ValueError(f'entry {i}: data not contiguous ({off} != {pos})')
            pos += size
        if pos != len(d):
            raise ValueError('trailing bytes after the last Flex entry')
        order = [i for _, _, i in sorted(spans)]
        return cls(d[:0x80], entries, esz, order if order != sorted(order) else None)

    @classmethod
    def new(cls, comment, esz, entries):
        hdr = bytearray(0x80)
        hdr[:len(comment)] = comment
        hdr[0x50:0x54] = cls.MAGIC
        struct.pack_into('<HH', hdr, 0x58, 6, 0)
        return cls(hdr, entries, esz)

    def encode(self):
        hdr, n, esz = bytearray(self.hdr), len(self.entries), self.esz
        order = self.order or [i for i, e in enumerate(self.entries) if e.data]
        offs, data, base = {}, bytearray(), 0x80 + n * esz
        for i in order:
            offs[i] = base + len(data); data += self.entries[i].data
        table = bytearray()
        for i, e in enumerate(self.entries):
            tail = e.tail.ljust(esz - 8, b'\0')[:esz - 8]
            table += struct.pack('<II', offs.get(i, 0), len(e.data)) + tail
        struct.pack_into('<I', hdr, 0x54, n)
        struct.pack_into('<I', hdr, 0x60, esz)
        struct.pack_into('<H', hdr, 0x64, self.checksum(hdr))
        return bytes(hdr) + bytes(table) + bytes(data)


# ---------------------------------------------------------------------------------------------------------- MISC.DAT
class Misc:
    """MISC.DAT (FUN_1148_0076 writes with FUN_11e8_0605(stream, ptr, len); FUN_1148_0490 reads).  The field list and sizes
    come from the push sequence of the 0605 calls (sizes 0xd, 0xd, 9, 1, 1, 2, 2, 4, 0x190, 2, 2):
      0   char[13] save file name  (GAME1.IM1)      uninitialised bytes after the NUL are kept (`raw`)
      13  char[13] level file      ([63ce] -> CHAOS.IFF)
      26  char[9]  current camera  ([63e1], CE33)
      35  u8  [50bd]   36 u8 [63da] = automatic camera flag (1)
      37  u16 0   39 u16 0     (both written as constant 0)
      41  u32 [2ed0]  next task serial number (FUN_10b8_0aa7 `serial = [2ed0]++`)
      45  u32[100] [2ed4]  serial of the task in each kernel slot (task+0x38, verified against SCRIPT.DAT); stale entries stay
      445 u16, 447 u16   ids of two global objects (DAT_1290_716c/19fc, each +2); ASSUMPTION: 4 and 5 are object ids"""
    SIZE = 449
    STR = (('save_name', 0, 13), ('level', 13, 13), ('camera', 26, 9))

    def __init__(self, raw):
        if len(raw) != self.SIZE:
            raise ValueError('MISC.DAT must be 449 bytes')
        self.raw = raw
        for name, o, n in self.STR:
            setattr(self, name, cstr(raw[o:o + n]))
        self.flag_50bd, self.auto_camera, self.zero1, self.zero2 = struct.unpack_from('<BBHH', raw, 35)
        self.next_serial, = struct.unpack_from('<I', raw, 41)
        self.serials = list(struct.unpack_from('<100I', raw, 45))
        self.obj_a, self.obj_b = struct.unpack_from('<HH', raw, 445)

    @classmethod
    def new(cls, save_name='', level='CHAOS.IFF', camera='', **kw):
        m = cls(bytes(cls.SIZE))
        m.save_name, m.level, m.camera = save_name, level, camera
        for k, v in kw.items():
            setattr(m, k, v)
        return m

    def encode(self):
        b = bytearray(self.raw)
        for name, o, n in self.STR:
            if cstr(self.raw[o:o + n]) != getattr(self, name):          # unchanged strings keep their stale bytes
                b[o:o + n] = getattr(self, name).encode('latin1')[:n - 1].ljust(n, b'\0')
        struct.pack_into('<BBHH', b, 35, self.flag_50bd, self.auto_camera, self.zero1, self.zero2)
        struct.pack_into('<I', b, 41, self.next_serial)
        struct.pack_into('<100I', b, 45, *self.serials)
        struct.pack_into('<HH', b, 445, self.obj_a, self.obj_b)
        return bytes(b)


# ---------------------------------------------------------------------------------------------------------- text files
class DefFile:
    """Saved VARS.DEF / SOUNDS.DEF (FUN_1118_4c7f): head text (string 0xf5 / 0xf6 of the resource table, which contains
    the *literal* characters backslash-r-backslash-n), then "{ Vars\\r\\n" / "{ Sounds\\r\\n", one "\\t%s = %d\\r\\n" per
    entry in table order, "}\\r\\n"."""
    RE = re.compile(rb'^(?P<head>.*?)\{ (?P<kind>\w+)\r\n(?P<body>(?:\t\S+ = -?\d+\r\n)*)\}\r\n$', re.S)

    def __init__(self, head, kind, items):
        self.head, self.kind, self.items = head, kind, items

    @classmethod
    def parse(cls, d):
        m = cls.RE.match(d)
        if not m:
            raise ValueError('not a saved .DEF file')
        items = [(a.decode('latin1'), int(b)) for a, b in re.findall(rb'\t(\S+) = (-?\d+)\r\n', m['body'])]
        return cls(m['head'], m['kind'].decode(), items)

    def encode(self):
        return (self.head + b'{ ' + self.kind.encode() + b'\r\n'
                + b''.join(b'\t%s = %d\r\n' % (n.encode('latin1'), v) for n, v in self.items) + b'}\r\n')

    def values(self):
        return dict(self.items)


def default_vars(path=os.path.join(SCRIPT_DIR, 'VARS.DEF')):
    """Initial values from the shipped VARS.DEF (names upper-cased, in table order; `_x` without '=' is 0)."""
    out = []
    for ln in open(path, 'rb').read().decode('latin1').splitlines():
        m = re.match(r'\s*(_\w+)\s*(?:=\s*(-?\d+))?', ln)
        if m and not ln.strip().startswith('//'):
            out.append((m.group(1).upper(), int(m.group(2) or 0)))
    return out


class Lists:
    """LISTS.FLX (FUN_1278_13ec): a Flex archive with 21-byte entries (offset, size, char name[13]); every entry is the text
    of one monitor log list as "KEY,VALUE " items (VALUE = engine clock stamp of the award, the `%time%` source)."""

    def __init__(self, flex):
        self.flex = flex

    @classmethod
    def parse(cls, d):
        return cls(Flex.parse(d))

    def lists(self):
        out = collections.OrderedDict()
        for e in self.flex.entries:
            items = [it.rsplit(',', 1) for it in e.data.decode('latin1').split()]
            out[cstr(e.tail[:13])] = [(k, int(v)) for k, v in items]
        return out

    @classmethod
    def from_lists(cls, lists, template=None):
        ents = [FlexEntry(''.join(f'{k},{v} ' for k, v in items).encode('latin1'), name.encode('latin1').ljust(13, b'\0'))
                for name, items in lists.items()]
        if template is not None:
            return cls(Flex(template.flex.hdr, ents, 21))
        return cls(Flex.new(b'(C) 1994 Origin Systems Inc.', 21, ents))

    def encode(self):
        return self.flex.encode()


# ---------------------------------------------------------------------------------------------------------- level IFF
class LevelIff:
    """<LEVEL>.IFF as the save writes it (FUN_1148_1404 -> 1232): FORM OBJS { VERS, then one chunk per level object }.
    Chunk pad bytes and trailing bytes are kept.  The writer's FORM size counts the pad byte of the last chunk even though
    the file is one byte short when that chunk has odd size (BEACH, CONTROL, DIGSITE, TANKS in the sample): `short_pad`.
    The object view is level.load_level (FIGR/ITEM/PLAY beyond the 45-byte
    base are not decoded here)."""

    def __init__(self, form_type, chunks, trailer=b'', short_pad=False):
        self.form_type, self.chunks, self.trailer = form_type, chunks, trailer      # chunks: (id, data, pad bytes)
        self.short_pad = short_pad

    @classmethod
    def parse(cls, d):
        if d[:4] != b'FORM':
            raise ValueError('not an IFF FORM')
        size, = struct.unpack_from('>I', d, 4)
        chunks, p, end = [], 12, 8 + size
        short = end == len(d) + 1
        if short:
            end -= 1
        while p + 8 <= end:
            cid, csize = d[p:p + 4], struct.unpack_from('>I', d, p + 4)[0]
            data = d[p + 8:p + 8 + csize]
            pad = d[p + 8 + csize:p + 8 + csize + (csize & 1)]
            chunks.append((cid, data, pad))
            p += 8 + csize + (csize & 1)
        if p != end + short:
            raise ValueError('malformed IFF chunk sizes')
        return cls(d[8:12], chunks, d[end:], short)

    def encode(self):
        body = self.form_type + b''.join(c + struct.pack('>I', len(x)) + x + p for c, x, p in self.chunks)
        return b'FORM' + struct.pack('>I', len(body) + self.short_pad) + body + self.trailer

    def objects(self):
        """[(tag, name, raw record)] without VERS, in file order = object ids 1.. (verified: process object ids)."""
        return [(c.decode(), cstr(x[:9]), x) for c, x, _ in self.chunks if c != b'VERS']

    def records(self):
        """[(tag, name, raw, level.ObjRec | None)]: objects() plus the decoded FIGR / ITEM / PLAY view (see level.py)."""
        return [(t, n, r, level.ObjRec(t, r) if t in level.RECORD_TAGS else None) for t, n, r in self.objects()]


def level_diff(init_objs, saved_objs):
    """What a save changes in one level: added/removed objects (matched by tag, name and occurrence), moved objects
    (pos at record offset 9), changed flag word `a` (offset 21), changed record sizes."""
    def keyed(objs):
        c, out = collections.Counter(), collections.OrderedDict()
        for tag, name, raw in objs:
            out[(tag, name, c[(tag, name)])] = raw
            c[(tag, name)] += 1
        return out
    a, b = keyed(init_objs), keyed(saved_objs)
    res = {'added': [k for k in b if k not in a], 'removed': [k for k in a if k not in b],
           'moved': [], 'flags': [], 'resized': []}
    for k in a:
        if k not in b:
            continue
        ra, rb = a[k], b[k]
        pa, pb = struct.unpack_from('<3i', ra, 9), struct.unpack_from('<3i', rb, 9)
        if pa != pb:
            res['moved'].append((k, pa, pb))
        if len(ra) >= 25 and len(rb) >= 25 and ra[21:25] != rb[21:25]:
            res['flags'].append((k, struct.unpack_from('<I', ra, 21)[0], struct.unpack_from('<I', rb, 21)[0]))
        if len(ra) != len(rb):
            res['resized'].append((k, len(ra), len(rb)))
    return res


# ---------------------------------------------------------------------------------------------------------- SCRIPT.DAT
def class_names(dgroup=DGROUP):
    try:
        return open(dgroup, 'rb').read()
    except OSError:
        return None


def script_blocks(name, script_dir=SCRIPT_DIR):
    """Definition names of <name> (.SCP) in compiler order: label index n (1-based) of a process is entry n-1.
    Same counter as formats/script.py (FUN_1118_07dc)."""
    try:
        data = open(os.path.join(script_dir, name), 'rb').read()
    except OSError:
        return []
    out = []
    for m in re.finditer(rb'"[^"]*"|//[^\n]*|\[[ \t]*(\w*)|\{[ \t]*(\w+)|(?<!\d):(?!\d)[ \t]*(\w*)', data):
        if m.group(0)[:1] not in b'"/':
            out.append((m.group(1) or m.group(2) or m.group(3) or b'#%d' % len(out)).decode('latin1'))
    return out


class Proc:
    """Serialised form of a script process, class vtable 0x3031 / 0x307f (writer FUN_10c0_4ef4 -> FUN_10b8_0d0b ->
    FUN_1238_147b; reader FUN_10c0_4a91).  The "B" entry of the slot is, in order (u16 unless noted):
      list1 ids (count = u16 at object+0x18; here: tasks waiting for this one)
      list2 ids (count = u16 at object+0x22; 0x2000|id = a task waiting for this one, 0x4000|id = this waits for id,
                 0x408 terminator; count includes the terminator)
      owner     slot id of the task at object+0x3c (0 = none)
      obj_a, obj_b, cur_obj  object ids (1-based index into the level IFF objects, negative = persistent table, 0 = none)
                from object+0xe7b/0xe7f/0xe83 (the constructor FUN_10c0_0bb3 params; cur_obj starts as obj_a else obj_b)
      wait_slot slot id of the task at object+0x71 (the Wait task of an active WAIT/SUSPEND?, ASSUMPTION), 0 = none
      block     1-based definition index of the running block in the script file (FUN_1128_0f21; verified: it names the
                real block, e.g. CHAOSBLK.SCP #29 = CELLONEBARS)
      script    char[13] script file name (the 13 bytes at object+0xe87 -> file record +0xd)
      label2    u16 (object+0xe8f -> FUN_1128_0f21, 0 here)
      file_idx  u16 index in the script file table (0xe8b; 1000 = table size = "not found", always 1000 here)
      pc, pc0   u32 object+0xe9b / +0xe97: byte offsets into the .SCP text (verified: inside the running block);
                pc = next statement, pc0 = start of the current one (ASSUMPTION for the exact roles)
      locals    object+0x70 (u8, in the raw object) 32-bit values, 4 bytes at +0x19 of each 29-byte local record
      objs      u16 count + that many object ids (FUN_10c0_56f1 list: cameras that watch the process; ids are CAMR objects)
    """
    def __init__(self, **kw):
        self.__dict__.update(kw)

    @classmethod
    def parse(cls, a, b):
        c1, c2 = struct.unpack_from('<H', a, 0x18)[0], struct.unpack_from('<H', a, 0x22)[0]
        p = 0
        l1 = list(struct.unpack_from(f'<{c1}H', b, p)); p += 2 * c1
        l2 = list(struct.unpack_from(f'<{c2}H', b, p)); p += 2 * c2
        owner, = struct.unpack_from('<H', b, p); p += 2
        obj_a, obj_b, cur_obj, wait_slot, block = struct.unpack_from('<5H', b, p); p += 10
        script = b[p:p + 13]; p += 13
        label2, file_idx = struct.unpack_from('<HH', b, p); p += 4
        pc, pc0 = struct.unpack_from('<II', b, p); p += 8
        n = a[0x70]
        loc = list(struct.unpack_from(f'<{n}I', b, p)); p += 4 * n
        cnt, = struct.unpack_from('<H', b, p); p += 2
        objs = list(struct.unpack_from(f'<{cnt}H', b, p)); p += 2 * cnt
        if p != len(b):
            raise ValueError(f'process record has {len(b) - p} undecoded bytes')
        return cls(l1=l1, l2=l2, owner=owner, obj_a=obj_a, obj_b=obj_b, cur_obj=cur_obj, wait_slot=wait_slot, block=block,
                   script_raw=script, label2=label2, file_idx=file_idx, pc=pc, pc0=pc0, locals=loc, objs=objs)

    @property
    def script(self):
        return cstr(self.script_raw)

    def encode(self):
        return (struct.pack(f'<{len(self.l1)}H', *self.l1) + struct.pack(f'<{len(self.l2)}H', *self.l2)
                + struct.pack('<6H', self.owner, self.obj_a, self.obj_b, self.cur_obj, self.wait_slot, self.block)
                + self.script_raw + struct.pack('<HHII', self.label2, self.file_idx, self.pc, self.pc0)
                + struct.pack(f'<{len(self.locals)}I', *self.locals)
                + struct.pack('<H', len(self.objs)) + struct.pack(f'<{len(self.objs)}H', *self.objs))

    def block_name(self, script_dir=SCRIPT_DIR):
        names = script_blocks(self.script, script_dir)
        return names[self.block - 1] if 0 < self.block <= len(names) else None


# vtable offset (data segment) -> (kind, note).  Kinds: 'handler' (no B entry), 'task' (B = two lists + owner), 'proc'.
CLASSES = {
    0x9aa6: ('handler', 'StdIntHandler (FUN_1240_099f, 72 bytes)'),
    0x9a46: ('handler', 'BiosTimer (64 bytes)'),
    0x8373: ('handler', 'device handler (56 bytes)'), 0x8347: ('handler', 'device handler (56 bytes)'),
    0x1a3a: ('handler', 'device handler (56 bytes)'), 0x7381: ('handler', 'Music handler (56 bytes)'),
    0x6677: ('task', 'Wait task (68 bytes, type 0x102); owner = awaited task'),
    0x2ea0: ('task', 'task type 0x10e (85 bytes)'),
    0x46f5: ('task', 'task type 0x108 (77 bytes)'),
    0x47a9: ('task', 'missile task (86 bytes, type 0x10c, FUN_10e0_0440); B = lists, owner, the owner figure and missile item ids'),
    0x3031: ('proc', 'script process (3746 bytes, type 0x10a, FUN_10c0_0840)'),
    0x307f: ('proc', 'script process subclass (3754 bytes, type 0x10a)'),
}


class Slot:
    """One kernel task slot: A = raw object memory (FUN_1230_2208 writes `[988c][slot]` bytes at the task pointer, entry
    10+2*slot) and B = the virtual serialiser output (entry 11+2*slot).  Common task header in A (FUN_1238_164b, 04ac):
      0 u16 vtable (data segment offset), 2 u16 slot id, 4 u16 group id, 6 u16 type, 8 u8 scheduling class (& 0x1f),
      0xe u16 flags (0x300 = task base), 0x10 u16 flags2 (bit0 = serialisable), 0x16/0x20 MLIST sub-objects (list1, list2:
      u16 vtable, u16 count ...), 0x38 u32 serial (MISC.DAT table, tasks of the 0x10b8 class only)."""

    def __init__(self, index, a, b, name=None):
        self.index, self.a, self.b, self.class_name = index, a, b, name

    @property
    def vtable(self):
        return struct.unpack_from('<H', self.a, 0)[0]

    @property
    def kind(self):
        return CLASSES.get(self.vtable, ('unknown', ''))[0]

    @property
    def note(self):
        return CLASSES.get(self.vtable, ('', f'unknown class {self.vtable:#x}'))[1]

    @property
    def type(self):
        return struct.unpack_from('<H', self.a, 6)[0]

    @property
    def group(self):
        return struct.unpack_from('<H', self.a, 4)[0]

    @property
    def serial(self):
        return struct.unpack_from('<I', self.a, 0x38)[0]

    def task(self):
        """(list1, list2, owner) for kinds 'task' and 'proc'."""
        c1, c2 = struct.unpack_from('<H', self.a, 0x18)[0], struct.unpack_from('<H', self.a, 0x22)[0]
        l1 = struct.unpack_from(f'<{c1}H', self.b, 0)
        l2 = struct.unpack_from(f'<{c2}H', self.b, 2 * c1)
        return list(l1), list(l2), struct.unpack_from('<H', self.b, 2 * (c1 + c2))[0]

    def proc(self):
        return Proc.parse(self.a, self.b) if self.kind == 'proc' else None


KERNEL_FIELDS = (            # entry 1 = DS:0x9888..0x9921 (153 bytes): (offset, name, fmt) of the fields with known meaning
    (0x0e, 'slot_count', 'H'), (0x10, 'live_tasks', 'H'), (0x12, 'scan_cursor', 'H'),
    (0x3a, 'pit_divisor', 'H'), (0x3c, 'tick_accum', 'H'), (0x42, 'active_list_count', 'H'))


class ScriptDat:
    """SCRIPT.DAT: Flex archive (8-byte entries), 210 entries = 10 kernel entries + 2 per task slot (100 slots), written by
    the kernel serializer FUN_1230_2208 (reader FUN_1230_1d7c):
      0  text   sprintf("Defines=%x Id=%s", 0x77e, "Kernel Ver. 1.00 - T. Zurovec") + NUL     (checked on load)
      1  153 B  raw memory DS:0x9888..0x9921, the kernel globals: far pointers (stale), slot count 100 (0x9896), live task
                count (0x9898), the PIT divisor and tick accumulator ([98c2], [98c4]), the active-list MLIST object (0x98c8)
      2  u16[] ids of the MLIST at DS:0x98c8 (count*2 bytes, includes the 0x408 sentinel): tasks 1, 3, 4, 5
      3  u16[100] object size per slot ([988c]); 0 = empty slot
      4  1152 B bitmap indexed by task id (bit set = the id is the group/owner of a task, FUN_1230_2ea2)       [9914]
      5  9216 B byte per id, bit (type & 7) | 0x10 flags (FUN_1230_2f91)                                          [9918]
      6  u16[32] number of live tasks per scheduling class [98ae] (class 1: 22, class 31: 3)
      7  far-pointer[100] [98be]: per slot offset of its class-name string in the data segment + runtime segment 0x040F
      8, 9 never written (empty)
      10+2s  A: raw object of slot s     11+2s  B: virtual serialisation (see Slot / Proc)"""
    N_SLOTS = 100

    def __init__(self, flex, dgroup=None):
        self.flex = flex
        e = [x.data for x in flex.entries]
        self.ident = cstr(e[0])
        self.kernel = e[1]
        self.active_list = list(struct.unpack(f'<{len(e[2]) // 2}H', e[2]))
        self.sizes = list(struct.unpack('<100H', e[3]))
        self.bitmap, self.id_flags = e[4], e[5]
        self.class_counts = list(struct.unpack('<32H', e[6]))
        self.name_ptrs = [struct.unpack_from('<HH', e[7], 4 * i) for i in range(self.N_SLOTS)]
        self.slots = []
        for s in range(self.N_SLOTS):
            a, b = e[10 + 2 * s], e[11 + 2 * s]
            if len(a) != self.sizes[s]:
                raise ValueError(f'slot {s}: size table {self.sizes[s]} != object {len(a)}')
            if a:
                nm = None
                if dgroup:
                    o = self.name_ptrs[s][0]
                    nm = cstr(dgroup[o:o + 40])
                self.slots.append(Slot(s, a, b, nm))

    @classmethod
    def parse(cls, d, dgroup=None):
        f = Flex.parse(d)
        if f.esz != 8 or len(f.entries) != 210:
            raise ValueError('unexpected SCRIPT.DAT geometry')
        return cls(f, dgroup if dgroup is not None else class_names())

    def kernel_fields(self):
        return {n: struct.unpack_from('<' + f, self.kernel, o)[0] for o, n, f in KERNEL_FIELDS}

    @property
    def defines(self):
        m = re.match(r'Defines=([0-9a-f]+) Id=(.*)', self.ident)
        return int(m[1], 16), m[2]

    def slot(self, i):
        return next((s for s in self.slots if s.index == i), None)

    def encode(self):
        ents = [FlexEntry() for _ in range(210)]
        ents[0].data = self.ident.encode('latin1') + b'\0'
        ents[1].data = self.kernel
        ents[2].data = struct.pack(f'<{len(self.active_list)}H', *self.active_list)
        by = {s.index: s for s in self.slots}
        sizes = [len(by[i].a) if i in by else 0 for i in range(self.N_SLOTS)]
        ents[3].data = struct.pack('<100H', *sizes)
        ents[4].data, ents[5].data = self.bitmap, self.id_flags
        ents[6].data = struct.pack('<32H', *self.class_counts)
        ents[7].data = b''.join(struct.pack('<HH', *p) for p in self.name_ptrs)
        for i, s in by.items():
            ents[10 + 2 * i].data, ents[11 + 2 * i].data = s.a, s.b
        return Flex(self.flex.hdr, ents, 8).encode()


# ---------------------------------------------------------------------------------------------------------- whole directory
class SaveState:
    """All files of a native GAMEDAT directory, decoded."""

    def __init__(self, misc, script, lists, vars_, sounds, levels):
        self.misc, self.script, self.lists, self.vars, self.sounds, self.levels = misc, script, lists, vars_, sounds, levels

    @classmethod
    def load(cls, path=GAMEDAT):
        rd = lambda n: open(os.path.join(path, n), 'rb').read()
        levels = {n[:-4]: LevelIff.parse(rd(n)) for n in sorted(os.listdir(path)) if n.upper().endswith('.IFF')}
        return cls(Misc(rd('MISC.DAT')), ScriptDat.parse(rd('SCRIPT.DAT')), Lists.parse(rd('LISTS.FLX')),
                   DefFile.parse(rd('VARS.DEF')), DefFile.parse(rd('SOUNDS.DEF')), levels)

    def files(self):
        """{file name: encoded bytes}"""
        out = {'MISC.DAT': self.misc.encode(), 'SCRIPT.DAT': self.script.encode(), 'LISTS.FLX': self.lists.encode(),
               'VARS.DEF': self.vars.encode(), 'SOUNDS.DEF': self.sounds.encode()}
        out.update({n + '.IFF': lv.encode() for n, lv in self.levels.items()})
        return out

    def write(self, path):
        os.makedirs(path, exist_ok=True)
        for n, b in self.files().items():
            open(os.path.join(path, n), 'wb').write(b)

    def level_objects(self):
        """Objects of the current level (ids are 1-based indexes into this list)."""
        lv = self.levels.get(self.misc.level.upper().replace('.IFF', ''))
        return lv.objects() if lv else []

    def describe_obj(self, oid):
        objs = self.level_objects()
        if 0 < oid <= len(objs):
            return f'{objs[oid - 1][0]} {objs[oid - 1][1]}'
        return str(oid) if oid else '-'


# ---------------------------------------------------------------------------------------------------------- .im1
class Im1:
    """The save container `gameN.im1`: a Flex archive of the play directory (FUN_1140_134f called by FUN_1148_0076 with the
    file name, the directory, the optional thumbnail and its size; class "DirPack" FUN_11f8_0859, packing FUN_11f8_09ee,
    extraction FUN_11f8_0f03).

    Layout (all from the code, NO native sample exists):
      header   0x80 bytes as Flex.  Comment = sprintf("%s %s savegame %s", "BioForge", "ver f1.01", "(C) 1994, 1995 Origin
               Systems Inc.") when a thumbnail is stored (FUN_11f8_1698: copied to 80 bytes, '_' -> ' '); otherwise the
               default "(C) 1994 Origin Systems Inc." (FUN_11f8_1355).
      entries  count = number of files + 1.  Entry size = longest relative file name + 14 (FUN_11f8_09ee sets [8e6e] =
               maxlen + 0x10 for the entry object that includes a 2-byte vtable word).  Entry 0 is reserved for the
               thumbnail blob (1200:02a9 at index 0, written after the files; (offset, size) only, empty name).
               Entries 1.. in directory order, each: u32 offset, u32 stored size, u32 original size, u8 flag (1 =
               compressed; the save passes compress = 0, so 0), char name[maxlen + 1] NUL padded.
      data     table is followed by the file bodies back to back (flat Flex layout), then the thumbnail.
    Extraction skips entries with an empty name (so the thumbnail is not extracted) and, for flag 1, runs the 11c8:0837
    decompressor, which is not implemented here (raises).
    Verified: header/checksum/table mechanics against the shipped Flex files, entry tail order from the 09ee decompile
    (local_6a/local_68 = file size at entry+0xa, local_66 = flag, local_65 = name) and 1200:02a9; the pack/unpack pair is
    checked against a native GAME1.IM1 (re/out/native_save): the file order is alphabetical, the 3rd dword is the original
    size, and repacking its files with its thumbnail reproduces it except the stale header word at 0x66."""
    COMMENT = b'BioForge ver f1.01 savegame (C) 1994, 1995 Origin Systems Inc.'

    @staticmethod
    def pack(src_dir, thumbnail=None, files=None):
        names = sorted(files if files is not None else
                       (n for n in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, n))))
        esz = max((len(n) for n in names), default=0) + 14
        ents, buf = [FlexEntry()], bytearray(esz - 13)
        for n in names:     # one reused name buffer: bytes after the NUL keep earlier, longer names (native files do)
            body, b = open(os.path.join(src_dir, n), 'rb').read(), n.encode('latin1') + b'\0'
            buf[:len(b)] = b
            ents.append(FlexEntry(body, struct.pack('<IB', len(body), 0) + bytes(buf)))
        if thumbnail:
            ents[0] = FlexEntry(thumbnail)
        comment = Im1.COMMENT.replace(b'_', b' ') if thumbnail else b'(C) 1994 Origin Systems Inc.'
        f = Flex.new(comment, esz, ents)
        f.order = list(range(1, len(ents))) + ([0] if thumbnail else [])   # thumbnail written last (1200:02a9)
        return f.encode()

    @staticmethod
    def entries(data):
        """[(name, flag, original size, stored bytes)] for entries 1.., plus the thumbnail (entry 0 data)."""
        f = Flex.parse(data)
        out = []
        for e in f.entries[1:]:
            osz, flag = struct.unpack_from('<IB', e.tail, 0)
            out.append((cstr(e.tail[5:]), flag, osz, e.data))
        return out, f.entries[0].data, f

    @staticmethod
    def unpack(data, out_dir):
        ents, thumb, _ = Im1.entries(data)
        os.makedirs(out_dir, exist_ok=True)
        for name, flag, osz, body in ents:
            if not name:
                continue
            if flag:
                raise NotImplementedError('compressed .im1 member (codec 11c8:0837 not implemented)')
            if len(body) != osz:
                raise ValueError(f'{name}: stored size {len(body)} != original size {osz}')
            open(os.path.join(out_dir, name), 'wb').write(body)
        return [n for n, *_ in ents if n], thumb


# ---------------------------------------------------------------------------------------------------------- CLI
def roundtrip(path):
    """decode -> encode -> byte-compare every file of a GAMEDAT; also re-encodes every decoded task record."""
    st = SaveState.load(path)
    enc, ok = st.files(), True
    for n in sorted(os.listdir(path)):
        raw = open(os.path.join(path, n), 'rb').read()
        same = enc.get(n.upper()) == raw
        ok &= same
        print(f'{n:14} {len(raw):7d} bytes  {"byte-exact" if same else "MISMATCH"}')
    for n, lv in st.levels.items():
        for t, nm, raw, rec in lv.records():
            if rec is not None and rec.encode() != raw:
                ok = False
                print(f'  {n}: {t} {nm} record re-encode MISMATCH')
    for s in st.script.slots:
        if s.kind == 'proc':
            good = s.proc().encode() == s.b
            ok &= good
            if not good:
                print(f'  slot {s.index}: process record re-encode MISMATCH')
    print('all files byte-exact' if ok else 'ROUNDTRIP FAILED')
    return ok


def dump(path, script_dir=SCRIPT_DIR):
    st = SaveState.load(path)
    m = st.misc
    print(f'== MISC.DAT: save {m.save_name!r} level {m.level!r} camera {m.camera!r} auto_camera {m.auto_camera} '
          f'[50bd] {m.flag_50bd} next_serial {m.next_serial} objs {m.obj_a},{m.obj_b}')
    live = {i: v for i, v in enumerate(m.serials) if v}
    print(f'   serial table: {len(live)} non-zero ' + ' '.join(f'{i}:{v}' for i, v in list(live.items())[:12]) + ' ...')
    sd = st.script
    defs, ident = sd.defines
    print(f'== SCRIPT.DAT: id {sd.ident!r} (defines {defs:#x}), {len(sd.flex.entries)} entries, '
          f'{sum(1 for e in sd.flex.entries if e.data)} non-empty, {len(sd.slots)} live task slots')
    print('   kernel', sd.kernel_fields(), 'active list', [hex(x) for x in sd.active_list])
    print('   tasks per scheduling class', {i: c for i, c in enumerate(sd.class_counts) if c})
    for s in sd.slots:
        line = f'   slot {s.index:2} {s.class_name or "?":14} type {s.type:#05x} group {s.group} {s.note}'
        if s.kind in ('task', 'proc'):
            line += f' serial {s.serial}'
        if s.kind in ('task', 'proc'):
            l1, l2, own = s.task()
            line += f'\n      waiters {l1} links {[hex(x) for x in l2]} owner {own}'
        if s.kind == 'proc':
            p = s.proc()
            line += (f'\n      {p.script} block #{p.block} {p.block_name(script_dir)} pc {p.pc:#x} pc0 {p.pc0:#x} locals {p.locals}'
                     f'\n      obj_a {st.describe_obj(p.obj_a)} obj_b {st.describe_obj(p.obj_b)} cur {st.describe_obj(p.cur_obj)}'
                     f' cameras {[st.describe_obj(o) for o in p.objs]}')
        print(line)
    print('== LISTS.FLX')
    for name, items in st.lists.lists().items():
        print(f'   {name}: {items}')
    dv = default_vars()
    sv = st.vars.items
    diff = [(a[0], b[1], a[1]) for a, b in zip(sv, dv) if a[1] != b[1]]
    print(f'== VARS.DEF: {len(sv)} variables, {len(diff)} differ from the shipped defaults (names match: '
          f'{all(a[0] == b[0] for a, b in zip(sv, dv))})')
    print('   ' + ', '.join(f'{n}={v}({d})' for n, d, v in diff[:24]) + (' ...' if len(diff) > 24 else ''))
    print(f'== SOUNDS.DEF: {len(st.sounds.items)} sounds, {sum(1 for i, (_, v) in enumerate(st.sounds.items) if v != i)} '
          f'with an id different from their table position')
    print('== levels')
    for n, lv in st.levels.items():
        ini = os.path.join(INITGAME, n + '.IFF')
        objs = lv.objects()
        tags = collections.Counter(t for t, _, _ in objs)
        line = f'   {n:8} {len(objs):3} objects ' + ' '.join(f'{k}:{v}' for k, v in sorted(tags.items()))
        if os.path.exists(ini):
            d = level_diff(LevelIff.parse(open(ini, 'rb').read()).objects(), objs)
            line += f'  vs INITGAME: +{len(d["added"])} -{len(d["removed"])} moved {len(d["moved"])} flags {len(d["flags"])}'
        print(line)
    lv = st.levels.get(m.level.upper().replace('.IFF', ''))
    if lv:
        print(f'== figures / items of {m.level}')
        objs = lv.records()
        name = lambda i: f'{objs[i - 1][0]} {(objs[i - 1][3].inst if objs[i - 1][3] else "") or objs[i - 1][1]}' if 0 < i <= len(objs) else (str(i) if i else '-')
        for i, (t, nm, raw, r) in enumerate(objs, 1):
            if t == 'ITEM' and (r.holder or r.flags & level.F_HIDDEN):
                print(f'   #{i:3} ITEM {r.name} {r.inst}: flags {r.flags:#04x} holder {name(r.holder)} hand {r.hand!r} locals {r.locals[:3]}')
            elif t in ('FIGR', 'PLAY'):
                print(f'   #{i:3} {t} {r.name} {r.inst}: pos {r.pos} heading {r.heading:.1f} hp {r.hp} flags {r.flags:#04x} '
                      f'motion {r.motion!r} enemy {name(r.enemy)} tasks motion {r.motion_task} ai {r.ai_task}\n'
                      f'        cameras {r.view_cams} avoid {[(name(w), rad) for w, rad in r.avoid]}')


def diff(path, init=INITGAME):
    st = SaveState.load(path)
    dv = default_vars()
    print('VARS differing from defaults:')
    for (n, v), (_, d) in zip(st.vars.items, dv):
        if v != d:
            print(f'  {n} = {v} (default {d})')
    for n, lv in st.levels.items():
        ini = os.path.join(init, n + '.IFF')
        d = level_diff(LevelIff.parse(open(ini, 'rb').read()).objects(), lv.objects())
        if not any(d.values()):
            print(f'{n}: unchanged records')
            continue
        print(f'{n}:')
        for k in ('added', 'removed', 'resized'):
            if d[k]:
                print(f'  {k}: {d[k]}')
        for k, pa, pb in d['moved']:
            print(f'  moved {k[0]} {k[1]}#{k[2]}: {pa} -> {pb}')
        for k, fa, fb in d['flags']:
            print(f'  flags {k[0]} {k[1]}#{k[2]}: {fa:#x} -> {fb:#x}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for c in ('dump', 'roundtrip'):
        sub.add_parser(c).add_argument('dir', nargs='?', default=GAMEDAT)
    p = sub.add_parser('diff'); p.add_argument('dir', nargs='?', default=GAMEDAT); p.add_argument('init', nargs='?', default=INITGAME)
    p = sub.add_parser('pack'); p.add_argument('dir'); p.add_argument('out')
    p = sub.add_parser('unpack'); p.add_argument('im1'); p.add_argument('out')
    a = ap.parse_args(argv)
    if a.cmd == 'dump':
        dump(a.dir)
    elif a.cmd == 'roundtrip':
        sys.exit(0 if roundtrip(a.dir) else 1)
    elif a.cmd == 'diff':
        diff(a.dir, a.init)
    elif a.cmd == 'pack':
        open(a.out, 'wb').write(Im1.pack(a.dir))
    elif a.cmd == 'unpack':
        names, _ = Im1.unpack(open(a.im1, 'rb').read(), a.out)
        print('\n'.join(names))


if __name__ == '__main__':
    main()
