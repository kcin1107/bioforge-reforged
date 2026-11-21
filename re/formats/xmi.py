"""Miles XMIDI (.XMI) -> Standard MIDI File converter.

Container (IFF, big-endian chunk sizes):
  FORM XDIR { INFO u16 n_sequences (LE) }
  CAT  XMID { FORM XMID { TIMB u16 n, n * (u8 patch, u8 bank)    timbres used (ignored here)
                          EVNT event stream }  * n_sequences }
(a lone FORM XMID without the XDIR/CAT wrapper is accepted too).

EVNT stream (differs from SMF):
  - no delta-time varlens: a byte < 0x80 where an event is expected is a delay of that many
    ticks; consecutive delay bytes add up (0x7f 0x7f 0x05 = 259 ticks). Events with no delay
    byte between them are simultaneous.
  - Note On (9n kk vv) is followed by a standard varlen duration; the Note Off is implied.
    We emit explicit Note Offs at start + duration (merged in time order; at equal time Note Offs
    sort before Note Ons so a re-struck key is not cut short; a zero-length note keeps On first).
  - other channel events have their standard length; FF meta and F0 sysex are type/len/data.
  - timing is a fixed 120 Hz: SMF output uses PPQN 60 and tempo 500000 us/qn (= 120 ticks/s).
    # ASSUMPTION: FF 51 tempo metas inside XMIDI are NOT honoured (Miles ignores them; some
    # BioForge files carry nonsense like 6000000 us/qn). They are dropped, the fixed tempo is used.
  - XMIDI-specific controllers 110..120 (0x6e-0x78: channel lock/protect, voice protect, timbre
    bank, indirect controller prefix, for-loop 0x74, next-loop 0x75, clear beat/bar 0x76,
    callback trigger 0x77, sequence branch index 0x78) are DROPPED from the output (they are
    meaningless to a plain MIDI player). The for-loop positions are reported via loop_points().

Output: one type 0 SMF (single MTrk) per sequence.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iff import parse

PPQN = 60
TEMPO_US = 500000          # 60 ticks per 0.5 s = 120 Hz
XMI_CONTROLLERS = range(110, 121)
CHAN_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


def _varlen(d, p):
    v = 0
    while True:
        b = d[p]; p += 1
        v = (v << 7) | (b & 0x7f)
        if not b & 0x80: return v, p


def _put_varlen(v):
    out = [v & 0x7f]
    v >>= 7
    while v:
        out.append((v & 0x7f) | 0x80); v >>= 7
    return bytes(reversed(out))


def decode_evnt(d, keep_xmi=False):
    """EVNT bytes -> (events, loops). events: list of (tick, order, seq, bytes) with absolute ticks,
    Note Offs included; loops: list of (tick, controller, value) for the dropped 0x74/0x75."""
    p, t, ev, loops = 0, 0, [], []
    seq = 0
    while p < len(d):
        b = d[p]
        if b < 0x80:                      # delay
            t += b; p += 1; continue
        p += 1
        hi = b & 0xF0
        if b == 0xFF:
            typ = d[p]; ln, q = _varlen(d, p + 1)
            data = d[q:q + ln]; p = q + ln
            if typ == 0x51 and not keep_xmi: continue      # tempo: ignored, see module docstring
            ev.append((t, 1, seq, bytes([0xFF, typ]) + _put_varlen(ln) + data)); seq += 1
            if typ == 0x2F: break
        elif b in (0xF0, 0xF7):
            ln, q = _varlen(d, p)
            ev.append((t, 1, seq, bytes([b]) + _put_varlen(ln) + d[q:q + ln])); seq += 1
            p = q + ln
        elif hi == 0x90:
            note, vel = d[p], d[p + 1]
            dur, p = _varlen(d, p + 2)
            ev.append((t, 2, seq, bytes([b, note, vel]))); seq += 1
            ev.append((t + dur, 0 if dur else 3, seq, bytes([0x80 | (b & 15), note, 0]))); seq += 1
        elif hi in CHAN_LEN:
            n = CHAN_LEN[hi]; args = d[p:p + n]; p += n
            if hi == 0xB0 and args[0] in XMI_CONTROLLERS:
                loops.append((t, args[0], args[1]))
                if not keep_xmi: continue         # keep_xmi: also leave them in the stream (musicseq.py)
            ev.append((t, 1, seq, bytes([b]) + args)); seq += 1
        else:
            raise ValueError(f"bad XMIDI status {b:#x} at {p-1}")
    return ev, loops


def _smf(events):
    ev = sorted(events, key=lambda e: (e[0], e[1], e[2]))
    trk = bytearray()
    trk += b'\x00\xff\x51\x03' + TEMPO_US.to_bytes(3, 'big')
    last, end = 0, 0
    for t, _, _, data in ev:
        if data[:2] == b'\xff\x2f': end = max(end, t); continue
        trk += _put_varlen(t - last) + data; last = t
    end = max(end, last)
    trk += _put_varlen(end - last) + b'\xff\x2f\x00'
    return (b'MThd' + struct.pack('>IHHH', 6, 0, 1, PPQN) + b'MTrk' + struct.pack('>I', len(trk)) + bytes(trk))


def sequences(d):
    """Raw XMIDI file bytes -> list of EVNT payloads, one per FORM XMID."""
    out = []
    def walk(nodes):
        for cid, typ, p, size, kids in nodes:
            if cid == b'FORM' and typ == b'XMID':
                for c2, _, p2, s2, _ in kids:
                    if c2 == b'EVNT': out.append(d[p2:p2 + s2])
            elif kids is not None:
                walk(kids)
    walk(parse(d))
    return out


def convert(d):
    """Raw XMIDI bytes -> list of SMF bytes (one per sequence)."""
    return [_smf(decode_evnt(e)[0]) for e in sequences(d)]


def end_tick(smf):
    """Total length in ticks (120 Hz) of an SMF produced by this module: sum of its delta times."""
    p = smf.index(b'MTrk') + 8
    t = 0
    while p < len(smf):
        dt, p = _varlen(smf, p); t += dt
        b = smf[p]
        if b == 0xFF:
            ln, q = _varlen(smf, p + 2); p = q + ln
        elif b in (0xF0, 0xF7):
            ln, q = _varlen(smf, p + 1); p = q + ln
        else:
            p += 1 + CHAN_LEN[b & 0xF0]
    return t


def loop_points(d):
    """Per sequence: list of (tick, controller, value) for the dropped loop controllers."""
    return [decode_evnt(e)[1] for e in sequences(d)]


if __name__ == '__main__':
    src, dst = sys.argv[1:3]
    for i, smf in enumerate(convert(open(src, 'rb').read())):
        open(f"{dst}_{i}.mid" if i else dst, 'wb').write(smf)
