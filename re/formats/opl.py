"""YM3812 (OPL2) FM synthesis: the chip behind the original's AdLib / Sound Blaster music (adlib.py drives it).

    chip = OPL2()
    chip.write(0x20, 0x01); ...
    pcm = chip.generate(n)            # list of int samples (mono, unclipped sum of the 9 channels, clipped to 16 bit) at RATE

This is an own implementation of the documented chip behaviour, written to be mirrored bit for bit by
native/Sources/BioForgeCore/OPL2.swift (re/formats/test_adlib.py compares the two). It models the parts the AIL AdLib driver uses:
9 two-operator melodic channels, 4 waveforms (register 0x01 bit 5), feedback, FM/additive connection, KSL, KSR, the envelope
generator, and the tremolo/vibrato LFOs (register 0xBD depth bits). Not modelled: rhythm mode, CSM, timers, the note-select bit
of register 0x08 (the driver writes 0), and the YM3014 DAC's floating-point quantisation.

Model (per output sample, at RATE = 3.579545 MHz / 72):
  phase    19-bit accumulator, increment ((fnum' << block) >> 1) * MT2[mult] >> 1, waveform index = phase >> 9 (10 bits);
           fnum' = fnum + vibrato (range = fnum >> 7, LFO position (n >> 10) & 7: 0 at positions 0/4, half at odd positions,
           halved again when 0xBD bit 6 is clear, negative at positions 4..7).
  output   attenuation = logsin[quarter-wave index] + (envelope' << 3), level = ((exp[~att & 255] | 0x400) << 1) >> (att >> 8),
           ones' complement for the negative half; envelope' = env + TL * 4 + KSL + tremolo (AM bit), max 511.
           logsin[i] = round(-log2(sin((i + 0.5) pi / 512)) * 256), exp[i] = round((2 ** (i / 256) - 1) * 1024).
  modulation  carrier index += modulator output (FM); modulator index += (out[n-1] + out[n-2]) >> (9 - FB) when FB > 0.
  envelope 9 bits (0.1875 dB), clocked every second sample (odd n). Effective rate R = 4 * rate + KSR value (block * 2 + fnum
           bit 9, >> 2 unless the KSR bit is set), max 63; rate 0 holds. R < 48: a step every 2 ** (11 - R // 4) clocks, size
           EG_STEP[R & 3][(counter >> shift) & 7]; 48 <= R < 60: every clock, EG_FAST[R & 3][counter & 7] << (R // 4 - 12);
           R >= 60: 8 per clock (attack: instant). Attack: env += (~env * step) >> 3 until 0; decay to SL * 16 (SL 15 = 496);
           sustain holds while EGT is set, else falls at the release rate; release to 511.
  key on   (KON 0 -> 1) restarts both operators' phase and attack. An operator in release at 511 is idle: it outputs 0 and
           its phase and feedback history hold (they matter again only after the next key on resets the phase).
  tremolo  triangle (n >> 6) % 210 -> 0..105, >> 2 (4.8 dB, 0xBD bit 7) or >> 4 (1 dB).
"""
import math

RATE = 49716
MT2 = (1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 20, 24, 24, 30, 30)
KSL_ROM = (0, 32, 40, 45, 48, 51, 53, 55, 56, 58, 59, 60, 61, 62, 63, 64)
KSL_SHIFT = (None, 1, 2, 0)                      # KSL bits -> shift (off, 3 dB/oct, 1.5 dB/oct, 6 dB/oct)
EG_STEP = ((0, 1, 0, 1, 0, 1, 0, 1), (0, 1, 0, 1, 1, 1, 0, 1), (0, 1, 1, 1, 0, 1, 1, 1), (0, 1, 1, 1, 1, 1, 1, 1))
EG_FAST = ((1, 1, 1, 1, 1, 1, 1, 1), (1, 1, 1, 2, 1, 1, 1, 2), (1, 2, 1, 2, 1, 2, 1, 2), (1, 2, 2, 2, 1, 2, 2, 2))
LOGSIN = tuple(round(-math.log2(math.sin((i + 0.5) * math.pi / 512)) * 256) for i in range(256))
EXP = tuple(round((2 ** (i / 256) - 1) * 1024) for i in range(256))
ATTACK, DECAY, SUSTAIN, RELEASE = 0, 1, 2, 3
MAX_ENV = 0x1ff


def wave(index, ws, env):
    """Operator output for a 10-bit waveform index, waveform ws and attenuation env (0..511)."""
    s = index & 0x3ff
    neg = False
    if ws == 0:
        neg = bool(s & 0x200)
    elif ws == 1:
        if s & 0x200: return 0
    elif ws == 3:
        if s & 0x100: return 0
        s &= 0xff
    q = (~s & 0xff) if s & 0x100 else s & 0xff
    a = LOGSIN[q] + (env << 3)
    if a > 0x1fff: a = 0x1fff
    v = ((EXP[(a & 0xff) ^ 0xff] | 0x400) << 1) >> (a >> 8)
    return ~v if neg else v


class Op:
    __slots__ = ('am', 'vib', 'egt', 'ksr', 'mult', 'ksl', 'tl', 'ar', 'dr', 'sl', 'rr', 'ws', 'phase', 'env', 'state')

    def __init__(self):
        self.am = self.vib = self.egt = self.ksr = False
        self.mult = self.ksl = self.tl = self.ar = self.dr = self.sl = self.rr = self.ws = 0
        self.phase, self.env, self.state = 0, MAX_ENV, RELEASE

    def idle(self):
        return self.state == RELEASE and self.env == MAX_ENV


class OPL2:
    def __init__(self):
        self.ops = [Op() for _ in range(18)]               # channel c: modulator ops[2c], carrier ops[2c + 1]
        self.fnum = [0] * 9
        self.block = [0] * 9
        self.kon = [False] * 9
        self.fb = [0] * 9
        self.con = [0] * 9
        self.fbuf = [[0, 0] for _ in range(9)]
        self.wse = False
        self.am_deep = self.vib_deep = False
        self.n = 0                                          # output samples so far
        self.eg_counter = 0

    # --- registers -----------------------------------------------------------------------------------------
    @staticmethod
    def _op_index(off):
        """Register offset 0..21 -> ops index, or None for the unused offsets."""
        if off > 21 or off % 8 > 5: return None
        ch = (off // 8) * 3 + (off % 8) % 3
        return ch * 2 + (off % 8) // 3

    def write(self, reg, val):
        reg &= 0xff; val &= 0xff
        hi = reg & 0xe0
        if reg == 0x01:
            self.wse = bool(val & 0x20)
        elif reg == 0xbd:
            self.am_deep, self.vib_deep = bool(val & 0x80), bool(val & 0x40)
        elif hi in (0x20, 0x40, 0x60, 0x80, 0xe0):
            i = self._op_index(reg & 0x1f)
            if i is None: return
            op = self.ops[i]
            if hi == 0x20:
                op.am, op.vib, op.egt, op.ksr, op.mult = bool(val & 0x80), bool(val & 0x40), bool(val & 0x20), bool(val & 0x10), val & 15
            elif hi == 0x40:
                op.ksl, op.tl = val >> 6, val & 0x3f
            elif hi == 0x60:
                op.ar, op.dr = val >> 4, val & 15
            elif hi == 0x80:
                op.sl, op.rr = val >> 4, val & 15
            else:
                op.ws = val & 3
        elif 0xa0 <= reg <= 0xa8:
            c = reg - 0xa0
            self.fnum[c] = (self.fnum[c] & 0x300) | val
        elif 0xb0 <= reg <= 0xb8:
            c = reg - 0xb0
            self.fnum[c] = (self.fnum[c] & 0xff) | (val & 3) << 8
            self.block[c] = (val >> 2) & 7
            kon = bool(val & 0x20)
            if kon and not self.kon[c]:
                for op in self.ops[2 * c:2 * c + 2]:
                    op.phase, op.state = 0, ATTACK
                    if self._rate(c, op, op.ar) >= 60: op.env, op.state = 0, DECAY
            elif not kon and self.kon[c]:
                for op in self.ops[2 * c:2 * c + 2]: op.state = RELEASE
            self.kon[c] = kon
        elif 0xc0 <= reg <= 0xc8:
            c = reg - 0xc0
            self.fb[c], self.con[c] = (val >> 1) & 7, val & 1

    # --- synthesis -----------------------------------------------------------------------------------------
    def _rate(self, c, op, rate):
        if rate == 0: return 0
        ksv = (self.block[c] << 1) | (self.fnum[c] >> 9 & 1)
        if not op.ksr: ksv >>= 2
        return min(63, rate * 4 + ksv)

    def _eg(self, c, op):
        st = op.state
        if st == ATTACK: rate = op.ar
        elif st == DECAY: rate = op.dr
        elif st == SUSTAIN:
            if op.egt: return
            rate = op.rr
        else:
            if op.env == MAX_ENV: return
            rate = op.rr
        r = self._rate(c, op, rate)
        if r == 0: return
        k = self.eg_counter
        hi = r >> 2
        if hi < 12:
            shift = 11 - hi
            if k & ((1 << shift) - 1): return
            inc = EG_STEP[r & 3][(k >> shift) & 7]
        elif hi < 15:
            inc = EG_FAST[r & 3][k & 7] << (hi - 12)
        else:
            inc = 8
        if not inc: return
        env = op.env
        if st == ATTACK:
            env = 0 if hi == 15 else env + (((~env) * inc) >> 3)
            if env <= 0: op.env, op.state = 0, DECAY; return
        else:
            env = min(MAX_ENV, env + inc)
            if st == DECAY and env >= op.sl << 4: op.state = SUSTAIN
        op.env = env

    def generate(self, count):
        out = []
        ops = self.ops
        for _ in range(count):
            n = self.n
            t = (n >> 6) % 210
            trem = (t if t < 105 else 210 - t) >> (2 if self.am_deep else 4)
            vibpos = (n >> 10) & 7
            eg_clock = n & 1
            acc = 0
            for c in range(9):
                m, k = ops[2 * c], ops[2 * c + 1]
                if m.idle() and k.idle(): continue
                fnum, block = self.fnum[c], self.block[c]
                ksl_base = (KSL_ROM[fnum >> 6] << 2) - ((8 - block) << 5)
                if ksl_base < 0: ksl_base = 0
                res = []
                for j, op in enumerate((m, k)):
                    if op.idle():
                        res.append(None); continue
                    env = op.env + (op.tl << 2) + (op.am and trem or 0)
                    sh = KSL_SHIFT[op.ksl]
                    if sh is not None: env += ksl_base >> sh
                    res.append(min(MAX_ENV, env))
                fb = self.fbuf[c]
                o0 = 0
                if res[0] is not None:
                    mod = (fb[0] + fb[1]) >> (9 - self.fb[c]) if self.fb[c] else 0
                    o0 = wave((m.phase >> 9) + mod, m.ws if self.wse else 0, res[0])
                    fb[0], fb[1] = fb[1], o0
                o1 = 0
                if res[1] is not None:
                    o1 = wave((k.phase >> 9) + (0 if self.con[c] else o0), k.ws if self.wse else 0, res[1])
                acc += o1 + (o0 if self.con[c] else 0)
                for op in (m, k):
                    if op.idle(): continue
                    f = fnum
                    if op.vib:
                        rng = (fnum >> 7) & 7
                        if not vibpos & 3: rng = 0
                        elif vibpos & 1: rng >>= 1
                        if not self.vib_deep: rng >>= 1
                        f = fnum - rng if vibpos & 4 else fnum + rng
                    op.phase = (op.phase + ((((f << block) >> 1) * MT2[op.mult]) >> 1)) & 0x7ffff
                    if eg_clock: self._eg(c, op)
            if eg_clock: self.eg_counter += 1
            out.append(32767 if acc > 32767 else -32768 if acc < -32768 else acc)
            self.n = n + 1
        return out


def render_writes(writes, samples):
    """[(sample, reg, val)] sorted by sample -> int list of `samples` outputs (writes at sample s apply before output s)."""
    chip, out, i = OPL2(), [], 0
    for s in range(samples):
        while i < len(writes) and writes[i][0] <= s:
            chip.write(writes[i][1], writes[i][2]); i += 1
        out += chip.generate(1)
    return out
