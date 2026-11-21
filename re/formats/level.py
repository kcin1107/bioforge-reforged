"""BioForge level object files (GAMEDAT/*.IFF, INITGAME/*.IFF): FORM OBJS.

Every record starts with a 45-byte base:
  char name[9]; s32 pos[3]; u32 a; u8 b; u8 junk[7]; s32 pos2[3]
PHYS (55): base + 10 bytes; pos/pos2 = AABB corners (collision box)
WAYP (45): base only (pos == pos2)
IMAG (54): base + 9 bytes (char[8] camera/image name?, u8)
CAMR (102): name = room image (.CAM) name; pos = eye; u8 flag at 33;
            s16x? 3x3 rotation at 34 as s32 rows, 8.8 fixed (rows = camera axes);
            s32 vec[3] at 70; u32 at 82 (38), u32 at 86; s32 at 90, s32 at 94 (16.16), s16 at 98, s16 at 100
FIGR, ITEM, PLAY: placed characters, items, player.
Read by FUN_1148_0d46 (dispatch on tag); CAMR by FUN_1110_1450.
"""
import math, re, struct, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iff import parse

def load_level(path):
    d = open(path, 'rb').read()
    objs = []
    for cid, _, p, s, _ in parse(d)[0][4]:
        r = d[p:p + s]
        if cid == b'VERS': continue
        o = {'tag': cid.decode(), 'raw': r, 'name': r[:9].split(b'\0')[0].decode('latin1')}
        o['pos'] = np.array(struct.unpack_from('<3i', r, 9), float)
        if cid == b'CAMR':
            o['flag'] = r[33]
            o['R'] = np.array(struct.unpack_from('<9i', r, 34), float).reshape(3, 3) / 256
            o['vec'] = np.array(struct.unpack_from('<3i', r, 70), float)
            o['extra'] = struct.unpack_from('<iiiihh', r, 82)
        elif len(r) >= 45:
            o['pos2'] = np.array(struct.unpack_from('<3i', r, 33), float)
        objs.append(o)
    return objs

if __name__ == '__main__':
    for o in load_level(sys.argv[1]):
        if o['tag'] == 'CAMR':
            print('CAMR', o['name'].ljust(8), o['pos'].astype(int), 'fwd?', np.round(o['R'][2], 2), 'vec', o['vec'].astype(int), o['extra'])


# ---------------------------------------------------------------------------------------------------------------------
# FIGR / ITEM / PLAY records (decoded 2026-10-15 from the object writers behind FUN_1148_1232 -> vtable +0x34; readers are
# the +0x30 slots; all decoded fields verified byte-exact on INITGAME, the shipped GAMEDAT and a native save)
#
#  ITEM, and the 191-byte base of FIGR/PLAY (writer FUN_1070_0d5b -> FUN_1060_16dd -> FUN_1178_0e5f; fields are object members):
#     0 char[9] type name (obj+2)      9 s32[3] position (obj+0xb)       21 u8 flags (obj+0x34)      22 u16 holder object id
#    24 char[9] hand name (string behind obj+0x30; empty = not in a hand)      33 char[25] instance name (obj+0xf7)
#    58 s32[3] velocity (+0xc6; VELOCITYX/Y/Z read it)   70 s32[3] (+0xd2, 0 in every sample)   82 s32[3] (+0xba, previous
#    position)   94 s32[3] (+0xe2, position copy)   106 s32[10] the ten script object locals `<obj>.~0..~9` (+0x92; ~0 = hit
#    points: `IF PLAYER.~0 <= 0`, FUN_1088_4d67 raises I_AM_DEAD at <= 0; ~5 holds the maximum)
#   146 u8 + s32[9] orientation (+0x110; FUN_1070_0edc is vtable +0x20): 3x3 matrix, 256 = 1.0, row 1 is the facing vector that
#       COMPASS reads (FUN_10d8_0f68 -> FUN_1208_39a8: atan2(m[1][0], m[1][1]) in degrees)   183 s32 (+0xee), 187 s32 (+0xf2)
#  FIGR and PLAY continue (writer FUN_1088_489f; 0x75f9 is a fixed marker word written by FUN_11f0_167d):
#   191 u16 0x75f9 | 193 char[9] type name copy (+0x1ea) | u16 enemy object id (+0x195, via FUN_1128_0e84; DEFINEENEMY) |
#       u16 task slot of the figure's own 0x108 motion task (+0x13d) | u16 task slot of the AI script process (+0x152) |
#       u16 task slot (+0x15b, 0 in every sample) | u16 0x75f9 | u8 (+0x141, 0xff) | 4 bytes (+0x146) |
#       char[25] current motion name (+0x15f; compared against atk_M1.. by the key handler FUN_10a8_0541) |
#       u16 L (DAT 1ce9 = number of IMAG objects of the level) + L bytes (+0x191, "InTrig": inside-trigger flag per IMAG) |
#       u16 0x75f9 | char[25] (+0x178, the AI name: the upper-cased creation name, SETAI overwrites it) | 4 bytes (+0x14e) |
#       u16 n + n * char[9] viewing cameras (+0x19d/+0x19f, camera names from the object table; hide/show per camera) |
#       u16 (+0x229) | u16 avoidance count (+0x1f3) + 8 * (u16 waypoint id (+0x1f5 via FUN_1128_0e84), u16 radius (+0x215));
#       ADDAVOIDANCEPOINT <wp> <radius> fills them | s32 (+0x88 of the sub-object at +0x17) | s32 (+0xa6) | 12 bytes (+0x8c) |
#       u16 0x75f9 | 21 bytes (FUN_1088_04b4: 12 + 1 + 1 + 6 + 1)
#   PLAY adds (FUN_10a8_1ffa): u16 task slot (DAT_1290_6530, a script process, 0 in both samples) | u32 clock (DAT_1290_8330) |
#       u16 object id (+0x22f, the item the player is about to use; 69 = MEAT1 in GAMEDAT)
#  Flag bits at +0x34 (statement/function handlers): 0x01 gravity (ISGRAVITYON FUN_10d8_2b57), 0x02 COLLISIONS statement
#  (FUN_10d0_1aa4, polarity unverified), 0x04 hidden (ISHIDDEN FUN_10d8_2be4; set while the current camera is not one of the
#  viewing cameras: USE_BOT 0x44 in CE31 but 0x40 in CE33), 0x08 invulnerable (ISINVULNERABLE FUN_10d8_2c9e), 0x10 bouncy
#  (BOUNCINESS FUN_10d0_0ab2; items start 0x11), 0x40 combat mode (ISINCOMBATMODE), 0x80 cleared by STOPMOTION/SNAPTOPOSE
#  (FUN_1088_508d reads it with the hit points; meaning unverified).
F_GRAVITY, F_COLLISIONS, F_HIDDEN, F_INVULNERABLE, F_BOUNCY, F_COMBAT, F_80 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x40, 0x80
MARK = 0x75f9
RECORD_TAGS = ('FIGR', 'ITEM', 'PLAY')


def _cs(b):
    return b.split(b'\0')[0].decode('latin1')


class ObjRec:
    """Decoded FIGR / ITEM / PLAY record: field views over the raw bytes, so `encode()` is byte-exact and unknown bytes are
    kept (stale junk after strings included). Setters patch the bytes in place (strings keep the stale tail)."""
    def __init__(self, tag, raw):
        self.tag, self.buf = tag, bytearray(raw)
        self.t = {}
        if len(raw) < 191 or (tag != 'ITEM' and not self._parse_tail()) or (tag == 'ITEM' and len(raw) != 191):
            raise ValueError(f'{tag} record of {len(raw)} bytes does not match the decoded layout')

    def _parse_tail(self):
        b, t, p = self.buf, self.t, 191
        try:
            def u16():
                nonlocal p
                p += 2
                return struct.unpack_from('<H', b, p - 2)[0]
            marks = [u16() == MARK]
            t['type2'], p = p, p + 9
            t['enemy'] = p; p += 2
            t['motion_task'] = p; p += 2
            t['ai_task'] = p; p += 2
            t['task3'] = p; p += 2
            marks.append(u16() == MARK)
            t['b141'], t['b146'], t['motion'] = p, p + 1, p + 5
            p += 30
            t['L'] = p; L = u16(); t['intrig'] = p; p += L
            marks.append(u16() == MARK)
            t['name2'], t['b14e'] = p, p + 25
            p += 29
            t['ncams'] = p; n = u16(); t['cams'] = p; p += 9 * n
            t['u229'] = p; p += 2
            t['navoid'] = p; na = u16(); t['avoid'] = p; p += 32
            t['s88'] = p; p += 20
            marks.append(u16() == MARK)
            t['t21'] = p; p += 21
            if self.tag == 'PLAY':
                t['play'] = p; p += 8
            return all(marks) and na <= 8 and p == len(b)
        except struct.error:
            return False

    def encode(self):
        return bytes(self.buf)

    # ---- base fields
    def _get(self, fmt, off):
        return struct.unpack_from(fmt, self.buf, off)

    @property
    def name(self): return _cs(self.buf[:9])
    @property
    def inst(self): return _cs(self.buf[33:58])
    @property
    def pos(self): return self._get('<3i', 9)
    @pos.setter
    def pos(self, v): struct.pack_into('<3i', self.buf, 9, *map(int, v))
    @property
    def flags(self): return self.buf[21]
    @flags.setter
    def flags(self, v): self.buf[21] = v
    @property
    def holder(self): return self._get('<H', 22)[0]
    @holder.setter
    def holder(self, v): struct.pack_into('<H', self.buf, 22, v)
    @property
    def hand(self): return _cs(self.buf[24:33])
    @property
    def velocity(self): return self._get('<3i', 58)
    @property
    def locals(self): return list(self._get('<10i', 106))
    @property
    def matrix(self): return [self._get('<3i', 147 + 12 * i) for i in range(3)]

    @property
    def hp(self): return self.locals[0]

    @property
    def heading(self):
        """COMPASS degrees (atan2(m[1][0], m[1][1])); the interpreter's Figure.heading uses the same convention."""
        m = self.matrix
        return math.degrees(math.atan2(m[1][0], m[1][1]))

    @heading.setter
    def heading(self, deg):
        c, s = round(256 * math.cos(math.radians(deg))), round(256 * math.sin(math.radians(deg)))
        struct.pack_into('<9i', self.buf, 147, c, -s, 0, s, c, 0, 0, 0, 256)

    # ---- FIGR / PLAY tail
    def _u16(self, key, i=0):
        return struct.unpack_from('<H', self.buf, self.t[key] + 2 * i)[0]

    @property
    def enemy(self): return self._u16('enemy')
    @property
    def motion_task(self): return self._u16('motion_task')
    @property
    def ai_task(self): return self._u16('ai_task')
    @property
    def ai_off(self): return struct.unpack_from('<h', self.buf, self.t['u229'])[0]
    @property
    def motion(self): return _cs(self.buf[self.t['motion']:self.t['motion'] + 25])
    @property
    def in_trig(self): return bytes(self.buf[self.t['intrig']:self.t['intrig'] + self._u16('L')])
    @property
    def ai_name(self):
        """+0x178, the AI name (SETAI's word; the AI start runs `<it>_AI`): '' if empty or not a name."""
        n = _cs(self.buf[self.t['name2']:self.t['name2'] + 25])
        return n.upper() if re.fullmatch(r'[A-Za-z0-9_]+', n) else ''
    @property
    def view_cams(self):
        n, p = self._u16('ncams'), self.t['cams']
        return [_cs(self.buf[p + 9 * i:p + 9 * i + 9]) for i in range(n)]
    @property
    def avoid(self):
        """[(waypoint object id, radius)] of the ADDAVOIDANCEPOINT list."""
        return [(self._u16('avoid', 2 * i), self._u16('avoid', 2 * i + 1)) for i in range(self._u16('navoid'))]
    @property
    def player_clock(self): return struct.unpack_from('<I', self.buf, self.t['play'] + 2)[0]
    @property
    def player_target(self): return struct.unpack_from('<H', self.buf, self.t['play'] + 6)[0]
    @property
    def hook_task(self):
        """PLAY: the task slot of the CAPTUREKEYBOARD hook process (DAT_1290_6530), 0 = none."""
        return struct.unpack_from('<H', self.buf, self.t['play'])[0]
    @property
    def foot(self):
        """F, model+0x88 (s32): the type's foot depth or a FLOATATHEIGHT override."""
        return struct.unpack_from('<i', self.buf, self.t['s88'])[0]
    @property
    def z_cap(self):
        """+0x14e (s32): FLOATATHEIGHT ... MAXIMUM's z limit, 0 = none."""
        return struct.unpack_from('<i', self.buf, self.t['b14e'])[0]
    @property
    def teeter(self):
        """+0x146 (4 bytes, the first is the teeter flag the whoah probe sets)."""
        return self.buf[self.t['b146']]


def object_records(objs):
    """[(tag, ObjRec | None)] aligned with load_level / LevelIff.objects order (None for other tags)."""
    return [(t, ObjRec(t, r) if t in RECORD_TAGS else None) for t, r in objs]
