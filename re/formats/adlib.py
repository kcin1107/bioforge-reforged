"""The original AdLib music path: MUSIC.FLX's AdLib arrangement through a port of the game's AIL AdLib driver into opl.py.

    lib = musicseq.Library(MUSIC_FLX, adlib=True)          # songs 128.., transitions 260 (the arrangement the driver plays)
    events, trace = musicseq.sequence(lib, [(0.0, 10)], 60.0)
    writes = register_writes(events, trace, 60.0, Bank.load(MUSIC_FLX))   # [(serve, register, value)], serves at 60 Hz
    pcm = render(writes, 60.0, 22050)                      # int16 mono

Device choice (NOTES "AdLib music"): INSTALL.EXE copies MUSIC/AILADLIB.DLL to AILXMI.DLL for MusicCardId 1..3 (Adlib, Sound
Blaster, SB Pro/16), AILAWE32.DLL for 4 and AILMT32.DLL for 5..7. CMUSIC.C (FUN_1198_0071) compares three driver bytes with
"MPU"; the MT-32 and AWE32 drivers carry that tag, so only the AdLib driver selects the second arrangement (FLX entry + 0x80,
FUN_1198_1be0), the AdLib transitions (entry 260, FUN_11a0_03e5) and installs timbres from entry 259 (MUSICFLS.C, FUN_11a0_0990)
for every timbre listed in the TIMB chunks of all songs and transitions. The driver's 0xe00-byte cache holds all of them (80 x 14
bytes), so nothing is evicted and a program selects its timbre if it was installed.

Driver (AILADLIB.DLL, AIL 2 XMIDI + YAMAHA; a scratch Ghidra import, functions named by their 1000:xxxx offset. The DLL has a
code segment with the tables (read through CS:) and a separate data segment, zero on disk, whose selector is the one relocation
at 1000:009c; offsets like 08f0 or 0b38 below are data-segment offsets). All 185 bank timbres are 14-byte "BNK" timbres, so the
driver's TVFX (time-variant timbres, 1000:099c / 0767 envelopes) never runs and is not ported.
  init (_XMI_INIT_DRIVER)  registers 1..0xf5 from the init table (0x01 = 0x20 waveform select, 0x04 = 0x60, every operator
           0x20 = 1, 0x40 = 0x3f, 0x60 = 0xff, 0x80 = 0x0f, 0xBD = 0xc0 deep tremolo/vibrato); then channels 1..9 get controllers
           7=127 1=0 10=64 11=127 64=0 114=0 110=0 111=0 112=0 (cs:009e/00a7; 110/111 do nothing here), pitch bend 0x2000
           and programs 68 48 95 78 41 3 110 122 (channel 9 none).
  messages (1b86)  note on/off only on MIDI channels 1..9 (channel 0 and 10..15 are ignored; channel 9 is percussion: timbre
           bank 127, patch = key, played at the timbre's transpose byte). 16 voice slots (S_), 9 OPL voices.
           CC 1 (vibrato bit at >= 64), 7, 11 (levels), 10 (stored at 0ac8, which nothing reads: only a level rewrite),
           64 (sustain; < 64 releases sustained slots), 112 voice protect,
           114 timbre bank, 121 reset (sustain 0, mod 0, expression 127, bend centre), 123 all notes off (per slot: note-off
           with the slot's *played* note, so percussion slots are missed - as in the original); program change sets the
           channel's timbre for later notes; pitch bend +-12 semitones.
  note on (1a3e)   first free slot of 16 (none: dropped); velocity = VEL[vel >> 3]; a free OPL voice round robin (131b), or
           the priority pass (17d3) when all 9 are busy: priority = 0x7fff (0xffff with voice protect) - voices of the
           channel; the highest-priority voiceless slot takes the voice of the lowest-priority voiced one (that note ends),
           while its priority is >= that one's.
  note off (19c7)  every slot of the channel with that key: sustained if CC 64 >= 64, else key off, slot freed, and the
           first voiceless slot takes the freed voice (0644) - but its registers are not written until a later update of
           its channel (the original's behaviour), then the priority pass.
  serve (0767)     adds 5 to a counter (08f0) and runs the priority pass when it reaches 120: every 24th serve. The counter is
           zeroed only by the reset 1274, which only _XMI_INIT_DRIVER calls (once, at boot: FUN_1198_0071 -> 0d4e), so it runs on
           across songs; it advances only on serves (below).
  registers (13ea) per update flag: 0x20 AVEKM | vibrato, 0x40 KSL | level, 0x60/0x80 AD/SR, 0xE0 waveform (carrier first),
           0xC0 feedback/connection, 0xA0/0xB0 frequency + key on (key off rewrites 0xB0 without bit 5).
           level: v = vol * expr * 2 >> 8 (+1 if non-zero), v = v * vel * 2 >> 8 (+1 if non-zero); the carrier (and the
           modulator of an additive timbre) gets TL = 63 - (63 - TL) * v / 127.
           frequency: n = note + transpose - 24 folded into -12.. by octaves, + 24 then down by octaves to <= 95; index =
           ((n * 256 + ((bend - 0x2000) >> 5) * 12 + 8) >> 4) - 192, folded into 0..0x5ff by 192s; F-number / block from
           FREQ, NOTE_OF and BLOCK_OF (sign bit = keep block, else block - 1; block -1 -> 0 with F-number >> 1).
           The driver never writes 0xBD after init (0xc0) nor 0x08, so rhythm mode is never used.
Timing. The game's music timer runs at 60 Hz (FUN_1198_0f13: FUN_1198_0e0d(.., 0x3c) -> FUN_1238_16e9, period 1e6 / 60 us) and
every song start sets the relative tempo to 200 (FUN_1198_1e3c, DGROUP 717b = 1). XMI_SERVE_DRIVER (26d6) adds the tempo to
each sequence's accumulator and runs one 120 Hz XMIDI step per 100 (275a..27a0), so two steps per serve, then calls the synth
serve 0767 once. The timer calls it (FUN_1198_102e) only while a sequence is loaded ([72ca] / [72d7]) and music is not paused
([7199]: 0 at MUSIC -2, 1 at -3; stop releases the sequences). So serve k sits at music time k / 60 and takes the musicseq events
at 120 Hz ticks floor(t * 120 + 0.5) <= 2k + 1, in stream order; its register writes take effect at chip sample
k * 49716 // 60, and it calls serve() only while serving() (from the musicseq trace) is on. INFERRED: serve k comes right after
the game frame at the same time (the original's timer phase against the frames, and the jitter of a 60 Hz timer dispatched from
the kernel's 140 Hz PIT tick, need a live capture), and the counter is 0 when the new game's music starts (in the original it
carries the serves of the music before, e.g. the menu's).
"""
import os, struct, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iff, music, opl
from flex import read_flex

HZ = 120                 # XMIDI steps per second
SERVE_HZ = 60            # driver serves per second, two steps each
SERVING = {'start': True, 'resume': True, 'stop': False, 'pause': False}
INIT_REGS = {0x01: 0x20, 0x04: 0x60, 0xbd: 0xc0}
for _base, _val in ((0x20, 0x01), (0x40, 0x3f), (0x60, 0xff), (0x80, 0x0f)):
    for _r in range(_base, _base + 0x16): INIT_REGS[_r] = _val
INIT_CONTROLLERS = ((7, 127), (1, 0), (10, 64), (11, 127), (64, 0), (114, 0), (110, 0), (111, 0), (112, 0))
INIT_PROGRAMS = (None, 68, 48, 95, 78, 41, 3, 110, 122, None)       # MIDI channel 0..9
VEL = (82, 85, 88, 91, 94, 97, 100, 103, 106, 109, 112, 115, 118, 121, 124, 127)
MOD_OP = (0, 1, 2, 6, 7, 8, 12, 13, 14)
CAR_OP = (3, 4, 5, 9, 10, 11, 15, 16, 17)
OP_REG = (0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 21)
BLOCK_OF = tuple(i // 12 for i in range(96))
NOTE_OF = tuple(i % 12 for i in range(96))
FREQ = (690, 692, 695, 697, 700, 702, 705, 707, 710, 713, 715, 718, 720, 723, 726, 728, 731, 733, 736, 739, 741, 744, 747, 749,
        752, 755, 758, 760, 763, 766, 769, 771, 774, 777, 780, 783, 785, 788, 791, 794, 797, 800, 803, 806, 809, 811, 814, 817,
        820, 823, 826, 829, 832, 835, 838, 841, 844, 847, 850, 854, 857, 860, 863, 866, 869, 872, 875, 879, 882, 885, 888, 891,
        895, 898, 901, 904, 908, 911, 914, 917, 921, 924, 927, 931, 934, 937, 941, 944, 948, 951, 955, 958, 961, 965, 968, 972,
        975, 979, 983, 986, 990, 993, 997, 1000, 1004, 1008, 1011, 1015, 1019, 1022, -511, -509, -507, -505, -504, -502, -500,
        -498, -496, -494, -492, -490, -488, -486, -484, -482, -480, -479, -477, -475, -473, -471, -469, -467, -465, -463, -460,
        -458, -456, -454, -452, -450, -448, -446, -444, -442, -440, -438, -436, -433, -431, -429, -427, -425, -423, -420, -418,
        -416, -414, -412, -409, -407, -405, -403, -401, -398, -396, -394, -391, -389, -387, -385, -382, -380, -378, -375, -373,
        -371, -368, -366, -363, -361, -359, -356, -354, -351, -349, -347, -344, -342, -339, -337)
F_AVEKM, F_LEVEL, F_ENV, F_WAVE, F_FB, F_FREQ = 0x80, 0x40, 0x20, 0x10, 0x08, 0x01
F_ALL = 0xf9
HERE = os.path.dirname(os.path.abspath(__file__))
OPL_SWIFT = os.path.join(HERE, '..', '..', 'native', 'Sources', 'BioForgeCore', 'OPL2.swift')
TOOL_SWIFT = os.path.join(HERE, '..', 'tools', 'opl2wav.swift')


def timb_list(raw):
    """(bank, patch) pairs of every TIMB chunk in an XMIDI file (u16 count, then u8 patch, u8 bank pairs)."""
    out = []
    def walk(nodes):
        for cid, _, p, size, kids in nodes:
            if cid == b'TIMB':
                n = int.from_bytes(raw[p:p + 2], 'little')
                out.extend((raw[p + 3 + 2 * i], raw[p + 2 + 2 * i]) for i in range(n))
            elif kids:
                walk(kids)
    walk(iff.parse(raw))
    return out


class Bank:
    """The installed timbres: {(bank, patch): 14 timbre bytes (u16 length, s8 transpose, 11 register bytes)}."""
    def __init__(self, timbres):
        self.timbres = timbres

    @classmethod
    def load(cls, flx):
        d, ents = read_flex(flx)
        ent = lambda i: d[ents[i][1]:ents[i][1] + ents[i][2]]
        raw = ent(music.E_TIMBRES)
        table, p = {}, 0
        while raw[p:p + 2] != b'\xff\xff':
            patch, bank, off = struct.unpack_from('<BBI', raw, p); p += 6
            table.setdefault((bank, patch), raw[off:off + struct.unpack_from('<H', raw, off)[0]])
        wanted = set()
        for e in list(range(music.ALT0, music.ALT0 + music.N_SONGS)) + [music.E_TRANS_ALT]:
            if ents[e][2]: wanted.update(timb_list(ent(e)))
        return cls({k: v for k, v in table.items() if k in wanted})


class Slot:
    __slots__ = ('status', 'chan', 'key', 'note', 'transpose', 'vel', 'sustained', 'voice', 'flags', 'b0', 'kon', 'conn',
                 'ksl', 'avekm', 'ad', 'sr', 'mask', 'fb', 'tl', 'mult', 'ws', 'prio', 'eff')

    def __init__(self):
        self.status, self.voice, self.chan, self.key, self.note, self.transpose = 0, 0xff, 0, 0, 0, 0
        self.vel = self.sustained = self.flags = self.b0 = self.kon = self.conn = self.mask = self.fb = self.prio = self.eff = 0
        self.ksl, self.avekm, self.ad, self.sr, self.tl, self.mult, self.ws = [0, 0], [0, 0], [0, 0], [0, 0], [0, 0], [0, 0], [0, 0]


class Driver:
    """AILADLIB.DLL's YAMAHA part. send() takes MIDI channel messages, serve() is the 60 Hz service; register writes are
    collected in `writes` as (register, value)."""
    def __init__(self, bank):
        self.bank = bank.timbres
        self.writes = []
        self.slots = [Slot() for _ in range(16)]
        self.owner = [0xff] * 9                  # OPL voice -> MIDI channel (0xbf8)
        self.voices = [0] * 16                   # voices per channel (0xbe8)
        self.rr = -1                             # last voice tried (0x8f3)
        self.serves = 0                          # 0x8f0 / 5
        z = lambda v=0: [v] * 16
        self.vol, self.expr, self.pan, self.mod, self.sus = z(), z(), z(), z(), z()
        self.bend_lsb, self.bend_msb, self.vprot, self.tbank = z(), z(), z(), z()
        self.timbre = [None] * 16                # current timbre per channel (0xb38)
        for r in range(1, 0xf6): self.writes.append((r, INIT_REGS.get(r, 0)))
        for ch in range(1, 10):
            for c, v in INIT_CONTROLLERS: self.send(bytes([0xb0 | ch, c, v]))
        for ch in range(1, 10):
            self.send(bytes([0xe0 | ch, 0, 0x40]))
            if INIT_PROGRAMS[ch] is not None: self.send(bytes([0xc0 | ch, INIT_PROGRAMS[ch]]))

    # --- MIDI -----------------------------------------------------------------------------------------
    def send(self, m):
        st, ch = m[0] & 0xf0, m[0] & 15
        a = m[1] if len(m) > 1 else 0
        b = m[2] if len(m) > 2 else 0
        if st == 0xb0:
            if a == 114: self.tbank[ch] = b; return
            if a == 112: self.vprot[ch] = b; return
            if a == 113: return                              # timbre protect: only affects cache eviction
            if a == 1: self.mod[ch] = b; mask = F_AVEKM
            elif a == 7: self.vol[ch] = b; mask = F_LEVEL
            elif a == 11: self.expr[ch] = b; mask = F_LEVEL
            elif a == 10: self.pan[ch] = b; mask = F_LEVEL
            elif a == 64:
                self.sus[ch] = b
                if b < 64: self.release_sustain(ch)
                return
            elif a == 121:
                self.sus[ch] = 0
                self.release_sustain(ch)
                self.mod[ch], self.expr[ch], self.bend_lsb[ch], self.bend_msb[ch] = 0, 127, 0, 64
                mask = F_AVEKM | F_LEVEL | F_FREQ
            elif a == 123:
                for s in self.slots:
                    if s.status == 1 and s.chan == ch: self.note_off(ch, s.note)
                return
            else:
                return
        elif st == 0xc0:
            self.timbre[ch] = self.bank.get((self.tbank[ch], a)); return
        elif st == 0xe0:
            self.bend_lsb[ch], self.bend_msb[ch] = a, b; mask = F_FREQ
        elif st == 0x90:
            if 1 <= ch <= 9:
                if b: self.note_on(ch, a, b)
                else: self.note_off(ch, a)
            return
        elif st == 0x80:
            self.note_off(ch, a); return
        else:
            return
        for i, s in enumerate(self.slots):
            if s.status and s.chan == ch:
                s.flags |= mask; self.update(i)

    def serve(self):
        self.serves += 1
        if self.serves == 24:
            self.serves = 0
            self.priority()

    # --- voices --------------------------------------------------------------------------------------
    def note_on(self, ch, key, vel):
        t = self.bank.get((127, key)) if ch == 9 else self.timbre[ch]
        if t is None: return
        for i, s in enumerate(self.slots):
            if s.status == 0: break
        else:
            return
        s.chan, s.key = ch, key
        tr = struct.unpack_from('b', t, 2)[0]
        s.note, s.transpose = (t[2], 0) if ch == 9 else (key, tr)
        s.vel = VEL[(vel >> 1 & 0x7f) >> 2]
        s.status, s.sustained = 1, 0
        s.kon, s.prio = 0x20, 0x7fff
        s.conn = t[8] & 1
        s.fb = t[8] & 0x0f
        s.ksl = [t[4] & 0xc0, t[10] & 0xc0]
        s.tl = [~t[4] & 0x3f, ~t[10] & 0x3f]                # 63 - TL
        s.avekm = [t[3] & 0xf0, t[9] & 0xf0]
        s.mult = [t[3] & 0x0f, t[9] & 0x0f]
        s.ad, s.sr, s.ws = [t[5], t[11]], [t[6], t[12]], [t[7], t[13]]
        s.mask = s.conn | 2
        s.flags = F_ALL
        s.voice = 0xff
        self.assign(i)

    def assign(self, i):
        """131b: the next free OPL voice after the last one tried, else the priority pass."""
        s = self.slots[i]
        for _ in range(9):
            self.rr = (self.rr + 1) % 9
            if self.owner[self.rr] == 0xff:
                self.take(i, self.rr)
                self.update(i)
                return
        self.priority()

    def take(self, i, v):
        s = self.slots[i]
        s.voice = v
        self.voices[s.chan] += 1
        self.owner[v] = s.chan
        s.flags = F_ALL

    def release(self, i):
        """137d: key off and give the voice back; a BNK slot is freed with it."""
        s = self.slots[i]
        if s.voice == 0xff: return
        s.kon = 0
        s.flags |= F_FREQ
        self.update(i)
        self.voices[s.chan] -= 1
        self.owner[s.voice] = 0xff
        s.voice = 0xff
        s.status = 0

    def note_off(self, ch, key):
        for i, s in enumerate(self.slots):
            if s.status == 1 and s.key == key and s.chan == ch:
                if self.sus[ch] < 64:
                    self.release(i)
                    s.status = 0
                    self.reassign()
                else:
                    s.sustained = 1

    def release_sustain(self, ch):
        for s in self.slots:
            if s.status and s.chan == ch and s.sustained: self.note_off(ch, s.note)

    def reassign(self):
        """0644: the first voiceless slot gets the first free voice (registers not written here), then the priority pass."""
        for i, s in enumerate(self.slots):
            if s.status and s.voice == 0xff: break
        else:
            return
        for v in range(9):
            if self.owner[v] == 0xff: break
        else:
            return
        self.take(i, v)
        self.priority()

    def priority(self):
        """17d3."""
        count = 0
        for s in self.slots:
            if s.status:
                count += 1
                base = 0xffff if self.vprot[s.chan & 15] >= 64 else s.prio
                n = self.voices[s.chan & 15]
                s.eff = 0 if base < n else base - n
        while count:
            best, a, worst, b = 0, None, 0xffff, None
            for i, s in enumerate(self.slots):
                if not s.status: continue
                if s.voice == 0xff:
                    if best <= s.eff: best, a = s.eff, i
                elif s.eff <= worst:
                    worst, b = s.eff, i
            if best < worst or best == 0 or b is None: return
            v = self.slots[b].voice
            self.release(b)
            self.take(a, v)
            self.update(a)
            count -= 1

    # --- registers -----------------------------------------------------------------------------------
    def _op(self, op, reg, val):
        self.writes.append((reg + OP_REG[op], val & 0xff))

    def update(self, i):
        """13ea for a BNK slot: write the registers named by the slot's flags."""
        s = self.slots[i]
        if s.voice == 0xff: return
        v, ch = s.voice, s.chan & 15
        mo, co = MOD_OP[v], CAR_OP[v]
        f = s.flags
        if f & F_LEVEL:
            x = (self.vol[ch] * self.expr[ch] * 2 >> 8) & 0xff
            x = x + 1 if x else 0
            x = ((x & 0xff) * s.vel * 2 >> 8) & 0xff
            level = x + 1 if x else 0
        if f & F_AVEKM:
            vib = 0x40 if self.mod[ch] >= 64 else 0
            self._op(mo, 0x20, s.mult[0] | vib | s.avekm[0])
            self._op(co, 0x20, s.mult[1] | vib | s.avekm[1])
        if f & F_LEVEL:
            for j, op in ((0, mo), (1, co)):
                lv = s.tl[j]
                if s.mask & (1 << j): lv = lv * (level & 0xff) // 0x7f
                self._op(op, 0x40, (~lv & 0x3f) | s.ksl[j])
        if f & F_ENV:
            self._op(mo, 0x60, s.ad[0]); self._op(co, 0x60, s.ad[1])
            self._op(mo, 0x80, s.sr[0]); self._op(co, 0x80, s.sr[1])
        if f & F_WAVE:
            self._op(co, 0xe0, s.ws[1]); self._op(mo, 0xe0, s.ws[0])
        if f & F_FB:
            self.writes.append((0xc0 + v, s.fb))
        if f & F_FREQ:
            if not s.kon & 0x20:
                self.writes.append((0xb0 + v, s.b0 & 0xdf))
            else:
                fnum, hi = self.frequency(s)
                self.writes.append((0xa0 + v, fnum & 0xff))
                s.b0 = hi | s.kon
                self.writes.append((0xb0 + v, s.b0))
        s.flags = 0

    def frequency(self, s):
        ch = s.chan & 15
        bend = (self.bend_msb[ch] << 7) | self.bend_lsb[ch]
        b = ((bend - 0x2000) >> 5) * 12
        n = s.note + s.transpose - 24
        while n + 12 < 0: n += 12
        n += 24
        n -= 12
        while n > 0x5f: n -= 12
        u = ((n * 256 + b + 8) >> 4) - 0xc0
        while u + 0xc0 < 0: u += 0xc0
        u += 0x180
        u -= 0xc0
        while u > 0x5ff: u -= 0xc0
        f = FREQ[NOTE_OF[u >> 4] * 16 + (u & 15)]
        blk = BLOCK_OF[u >> 4] if f < 0 else BLOCK_OF[u >> 4] - 1
        if blk < 0:
            blk = 0; f >>= 1
        return f & 0x3ff, ((f & 0x3ff) >> 8) | (blk << 2)


def serving(trace):
    """musicseq trace -> [(seconds, on)]: when the driver is served (a song loaded and not paused, module docstring "Timing")."""
    return [(e[0], SERVING[e[1]]) for e in trace if e[1] in SERVING]


def register_writes(events, trace, end, bank):
    """musicseq events [(seconds, bytes)] and trace up to `end` seconds -> [(serve, register, value)] (module docstring
    "Timing"). A serve runs once both its steps are known: the last is the one whose second step is at or before `end`."""
    drv = Driver(bank)
    out = [(0, r, v) for r, v in drv.writes]
    drv.writes = []
    tick = lambda t: int(t * HZ + 0.5)
    changes = serving(trace)
    last, i, j, on = tick(end), 0, 0, False
    k = 0
    while 2 * k + 1 <= last:
        while i < len(events) and tick(events[i][0]) <= 2 * k + 1:
            drv.send(events[i][1]); i += 1
        while j < len(changes) and tick(changes[j][0]) <= 2 * k + 1:
            on = changes[j][1]; j += 1
        if on: drv.serve()
        out += [(k, r, v) for r, v in drv.writes]
        drv.writes = []
        k += 1
    return out


def chip_writes(writes):
    """(serve, reg, val) -> (chip sample, reg, val)."""
    return [(k * opl.RATE // SERVE_HZ, r, v) for k, r, v in writes]


def _binary():
    """Compiled opl2wav (native OPL2.swift + re/tools/opl2wav.swift), cached like musicseq's midi2wav."""
    exe = os.environ.get('OPL2WAV_BIN') or os.path.join(tempfile.gettempdir(), 'bioforge-opl2wav')
    newest = max(os.path.getmtime(OPL_SWIFT), os.path.getmtime(TOOL_SWIFT))
    if not os.path.exists(exe) or os.path.getmtime(exe) < newest:
        subprocess.run(['swiftc', '-O', '-parse-as-library', OPL_SWIFT, TOOL_SWIFT, '-o', exe], check=True, capture_output=True)
    return exe


def render_chip(writes, samples):
    """(chip sample, reg, val) writes -> int16 array of `samples` chip-rate outputs, rendered by the native OPL2 (opl2wav)."""
    sc = tempfile.mkdtemp()
    src, dst = os.path.join(sc, 'in.bin'), os.path.join(sc, 'out.raw')
    with open(src, 'wb') as f:
        f.write(struct.pack('<I', samples))
        for s, r, v in writes: f.write(struct.pack('<IBB', s, r, v))
    r = subprocess.run([_binary(), src, dst], capture_output=True, text=True)
    if r.returncode: raise RuntimeError(f'opl2wav failed: {r.stderr.strip()}')
    return np.fromfile(dst, '<i2')


def render(writes, duration, rate=22050):
    """Driver register writes -> int16 mono at `rate` (chip output at 49716 Hz, linearly resampled with np.interp)."""
    n = int(duration * opl.RATE)
    pcm = render_chip(chip_writes(writes), n).astype(np.float64)
    m = int(duration * rate)
    x = np.interp(np.arange(m) * (opl.RATE / rate), np.arange(n), pcm)
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)
