"""BioForge sound samples (SOUND/{E,F,G}SAMPLES.FLX) reader.

Flex archive (see flex.py), 718 entries:
  0..716  one sample each
  717     name table: consecutive 9-byte NUL-padded ASCII names, one per sample index ("scream2a", "bubble2a" ...)
Sample entry (little-endian):
  0x00  u32  data_len          == entry size - 32
  0x04  u16  rate              11111 or 11025 Hz
  0x06  u16  flags             always 1
  0x08  u32  loop_start        both 0 = no loop (~46 samples loop)
  0x0c  u32  loop length       the engine loops [loop_start, loop_start + length) (1028:0f0a -> 1000:03de: +0x0a = start + loop_start +
                               length; 0 = no loop); Sample.loop_end is that end (0 when the length is 0)
  0x10  12 bytes unused (sometimes garbage)
  0x20  s8   data[data_len]    signed 8-bit mono PCM
Engine: script SOUND(id [, volume [, pitch]]) plays sample `id` at volume (default 255, max 255) and
rate - pitch (pitch -1024 plays faster). Sound id = index into the sample list = the number in
GAMEDAT/SOUNDS.DEF (`_NAME = n`), which also covers the SOUNDS2.DEF aliases.

    sound.py <FLX> <outdir> [--limit N]     writes <index>_<name>.wav (8-bit unsigned) and prints a check summary
"""
import os
import re
import struct
import sys
import wave
from collections import namedtuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flex import read_flex  # noqa: E402

HEADER = 32
SOUNDS_DEF = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'game', 'app', 'GAMEDAT', 'SOUNDS.DEF')
Sample = namedtuple('Sample', 'index name rate flags loop_start loop_end pcm')


class Samples:
    def __init__(self, path):
        d, ents = read_flex(path)
        self.d, self.ents = d, ents
        off, size = ents[-1][1:3]
        table = d[off:off + size]
        self.names = [table[i:i + 9].split(b'\0')[0].decode('latin1') for i in range(0, len(table) - 8, 9)]
        self._cache = {}

    def __len__(self):
        return len(self.ents) - 1

    def get(self, i):
        if i not in self._cache:
            _, off, size, _ = self.ents[i]
            n, rate, flags, ls, ll = struct.unpack_from('<IHHII', self.d, off)
            le = ls + ll if ll else 0
            pcm = np.frombuffer(self.d, np.int8, min(n, size - HEADER), off + HEADER)
            self._cache[i] = Sample(i, self.names[i] if i < len(self.names) else '', rate, flags, ls, le, pcm)
        return self._cache[i]

    def duration(self, i, pitch=0):
        """Seconds of one pass through sample i at rate - pitch."""
        s = self.get(i)
        return len(s.pcm) / max(s.rate - pitch, 1)

    def check(self):
        """-> (bad_size, bad_loop) sample index lists."""
        bad_size, bad_loop = [], []
        for i in range(len(self)):
            n = struct.unpack_from('<I', self.d, self.ents[i][1])[0]
            if n + HEADER != self.ents[i][2]:
                bad_size.append(i)
            if self.get(i).loop_end > n:
                bad_loop.append(i)
        return bad_size, bad_loop


def load_sound_ids(path=SOUNDS_DEF):
    """GAMEDAT/SOUNDS.DEF -> {lower-case '_name': sample index}."""
    out = {}
    for ln in open(path, 'rb').read().decode('latin1').splitlines():
        m = re.match(r'\s*(_\w+)\s*=\s*(\d+)', ln)
        if m:
            out[m.group(1).lower()] = int(m.group(2))
    return out


def write_wav(path, s):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(s.rate)
        w.writeframes((s.pcm.astype(np.int16) + 128).astype(np.uint8).tobytes())


if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    limit = None
    if '--limit' in args:
        k = args.index('--limit')
        limit = int(args[k + 1])
        del args[k:k + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    sm = Samples(args[0])
    os.makedirs(args[1], exist_ok=True)
    for i in range(len(sm) if limit is None else min(limit, len(sm))):
        s = sm.get(i)
        write_wav(os.path.join(args[1], '%d_%s.wav' % (i, s.name)), s)
    bs, bl = sm.check()
    loops = sum(1 for i in range(len(sm)) if sm.get(i).loop_end > 0)
    print('%s: %d samples, %d names, %d looped, %d size mismatches, %d loop_end > data_len'
          % (os.path.basename(args[0]), len(sm), len(sm.names), loops, len(bs), len(bl)))
