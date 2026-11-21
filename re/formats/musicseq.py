"""Deterministic music sequencer: the engine's MUSIC state machine (NOTES "Music state machine") on a
120 Hz XMIDI timeline, plus offline General MIDI rendering through re/tools/midi2wav.swift.

    lib = Library(MUSIC_FLX)
    events, trace = sequence(lib, [(0.0, 10), (20.0, 35)], end=60.0)   # events: [(seconds, bytes)], time sorted
    pcm = render(events, 60.0)                                         # int16 (n, 2) at 22050 Hz

Sequence model (xmi.decode_evnt(keep_xmi=True) keeps the XMIDI controllers in the stream), as AIL's XMIDI layer runs it
(AILADLIB.DLL 1000:26d6.., re/NOTES.md "AdLib music" > "XMIDI layer"; every AIL driver shares this code):
  events          run in file order within a step (2842..2914), not sorted by kind.
  notes           a note on goes to the first free entry of a 32-entry note queue with its duration - 1 (2426; a full queue
                  overwrites entry 0). At each later step, before that step's events, every entry is decremented and those
                  below 0 end in entry order (27d6): a note of duration d ends at step on + max(d, 1).
  stop            _XMI_STOP_SEQUENCE (2e40): note offs for the queued notes in entry order (1fc3), then per channel 0..15
                  CC 64 = 0 where the sequence's last CC 64 was >= 64 (2021; CC 112 likewise, which no song sets). No CC 123.
                  Pause (MUSIC -2) is the same stop.
  end             the FF 2F event runs only 2021 and marks the sequence done (2551); no song has notes queued then.
  resume          _XMI_RESUME_SEQUENCE (2e99 -> 20c8) resends the sequence's last CC 7, 1, 10, 11, 64, 114 (controller by
                  controller, channels 0..15), then per channel its pitch bend and program.
  start           _XMI_START_SEQUENCE (2dd8 -> 1e71) clears the queue and those caches and sends nothing;
                  _XMI_BRANCH_INDEX (3018) seeks to a marker and ends the queued notes (1fc3). So a song entered at a marker
                  keeps the channel state the earlier music left.
  0x77 value          sets the sequence's measure count (220f -> 2313; _XMI_MEASURE_COUNT 2f5f returns it, at least 0).
                       Start sets it to -1 (1e71), a NEXT jump or a branch leaves it. The FF 58 time signature only
                       drives the beat count (26fd..270b), never the measure count. Every song numbers its 0x77s 1..N.
  0x74 FOR count / 0x75 NEXT   Miles loop: NEXT jumps to just after the FOR; count 0 = forever.
                       ASSUMPTION: count n > 0 plays the body n times (n - 1 jumps). A NEXT with no open FOR
                       (entered via a branch marker past the FOR) is ignored.
  0x78 value k         branch marker = entry point k (126 = restart point).
Overlaid transitions share the 16 MIDI channels (ASSUMPTION: just merged).

Song switches (seg 1198; re/NOTES.md "Music state machine"): a request looks up the transition value at measure 1 of the
row (0a91 -> 0595 with the bar counter 72c4, which a switch resets to 1 and whose step in 1668 needs a request for the
song already current, which 0702 turns away). It stores the main sequence's measure count (7197); the music task's
update (1054) then acts when max(1, count) differs from it or the sequence no longer plays (09fc). A transition stores
its own count right after its start, 0, so it ends at the next update. The update runs after every request (1668 ->
183b) and, INFERRED, once per 30 Hz game tick before that tick's music (POLL_HZ); an ended song with a loop measure
restarts there too.

Music level (options dialog, FUN_1100_0dc2(sfx, music)): `volume` (0..100, None = unscaled) is the level in force and
`volumes` [(seconds, level)] its later changes.  Level > 0 enables music: if no song is current it starts the options music
(song 4, _OptionsMusic) or resumes the last requested one, then FUN_1198_1b62 sets the XMIDI relative volume min(level, 127);
level 0 stops the music (MUSIC -4) and disables it, so requests are ignored until it is raised.  AIL's relative volume is a
percentage (AILADLIB.DLL 1000:220f / 21a7, in the XMIDI layer every AIL driver shares): each channel volume controller (CC 7)
is sent as min(127, v * rel // 100) and _XMI_SET_RELATIVE_VOLUME re-sends the current channel volumes; the stream does the same.

Arrangements: Library(flx) is the General MIDI / MT-32 one (songs 0.., transitions 258); Library(flx, adlib=True) is the one
the game picks with its AdLib driver (songs 128.., an empty entry falls back to the first arrangement as FUN_1198_1be0 does;
transitions 260). adlib.py turns the event stream into OPL2 register writes.
"""
import json, os, subprocess, sys, tempfile, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xmi, music
from flex import read_flex

HZ = 120
POLL_HZ = 30             # the music task's update (FUN_1198_1054), INFERRED once per game tick
FOR, NEXT, BAR, BRANCH = 0x74, 0x75, 0x77, 0x78
RESTART = 126
OPTIONS_MUSIC = 4        # script constant _OptionsMusic (GAMEDAT/VARS.DEF _OPTIONSMUSIC): the song the options dialog starts
CC_VOLUME = 7
INF = float('inf')
HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT_SRC = os.path.join(HERE, '..', 'tools', 'midi2wav.swift')


class Seq:
    """items, in file order: (tick, kind, a): kind 'm' (a = channel message bytes), 'note' (a = (note on bytes,
    duration)), 'for'/'next'/'bar'/'br' (a = controller value) or 'end' (always last). bars = item indices of the 0x77
    events."""
    def __init__(self, evnt):
        ev, _ = xmi.decode_evnt(evnt, keep_xmi=True)              # file order; each note on is followed by its note off
        kinds = {FOR: 'for', NEXT: 'next', BAR: 'bar', BRANCH: 'br'}
        self.items, end = [], 0
        for i, (t, order, _, b) in enumerate(ev):
            end = max(end, t)
            if order in (0, 3): continue                           # the note off xmi derives from a duration
            if b[0] >= 0xF0: continue                              # meta / sysex
            if b[0] & 0xF0 == 0x90:
                self.items.append((t, 'note', (b, ev[i + 1][0] - t)))
            elif b[0] & 0xF0 == 0xB0 and b[1] in xmi.XMI_CONTROLLERS:
                if b[1] in kinds: self.items.append((t, kinds[b[1]], b[2]))
            else:
                self.items.append((t, 'm', b))
        self.items.append((end, 'end', 0))
        self.bars = [i for i, it in enumerate(self.items) if it[1] == 'bar']
        self.markers = {}
        for i, it in enumerate(self.items):
            if it[1] == 'br': self.markers.setdefault(it[2], i)


class Library:
    def __init__(self, flx, adlib=False):
        d, ents = read_flex(flx)
        ent = lambda i: d[ents[i][1]:ents[i][1] + ents[i][2]]
        text = ent(music.E_TABLE).decode('latin1')
        self.songs = music.parse_songs(text)
        self._ent, self._cache, self.trans_seq = ent, {}, {}
        ids = {}
        for s in self.songs: ids.setdefault(s['file'], s['id'])
        self.table = {}                  # (from id, to id) -> signed values (index = measure - 1; '!' = negative)
        for r in music.parse_transitions(text):
            self.table[(ids[r['src']], ids[r['dst']])] = [-v if f else v for v, f in zip(r['values'], r['flags'])]
        self.adlib = adlib
        self.trans = xmi.sequences(ent(music.E_TRANS_ALT if adlib else music.E_TRANS))
        self._entry = lambda n: n + music.ALT0 if adlib and ents[n + music.ALT0][2] else n

    def song(self, n):
        if n not in self._cache: self._cache[n] = Seq(xmi.sequences(self._ent(self._entry(music.SONG0 + n)))[0])
        return self._cache[n]

    def transition(self, ref):           # 1-based index into the transition list
        if ref not in self.trans_seq: self.trans_seq[ref] = Seq(self.trans[ref - 1])
        return self.trans_seq[ref]


def step(t):
    """Seconds -> 120 Hz step. Player times are step / HZ, so equal steps give equal times."""
    return int(t * HZ + 0.5)


CACHED = (7, 1, 10, 11, 64, 114)          # the controllers _XMI_RESUME_SEQUENCE resends, in its order (cs:009e up to 110)
QUEUE = 32


class Player:
    """One registered sequence: position on a 120 Hz step timeline, its note queue and its controller caches (1e71)."""
    def __init__(self, seq, t0, idx=0):
        self.seq, self.stack = seq, []
        self.measure = -1                    # the driver's measure count (sequence +0x40): -1 at start, then the last 0x77 value
        self.queue = [None] * QUEUE          # (channel, key, end step)
        self.cc, self.program, self.bend = {}, {}, {}     # (controller, channel) / channel -> last value sent
        self.status = 1                      # the driver's sequence status: 1 playing, 0 stopped, 2 done (reached FF 2F)
        self.jump(idx, step(t0))

    def jump(self, idx, s):
        self.idx, self.base_step, self.base_tick = idx, s, self.seq.items[idx][0]

    def item_step(self):
        return self.base_step + self.seq.items[self.idx][0] - self.base_tick

    def count(self):
        """_XMI_MEASURE_COUNT (2f5f -> 26a7): the measure count, at least 0."""
        return max(0, self.measure)

    def due_step(self):
        """Step of the next note queue expiry, or None."""
        return min((e[2] for e in self.queue if e), default=None)

    def next_step(self):
        d = self.due_step()
        return self.item_step() if d is None else min(d, self.item_step())

    def next_time(self):
        return self.next_step() / HZ


class Sequencer:
    def __init__(self, lib, volume=None):
        self.lib, self.out, self.trace = lib, [], []
        self.volume = volume                 # music level 0..100 (None = unscaled); 0 = disabled (DAT_4b6e)
        self.last_song = None                # song to resume when music is re-enabled (the engine's saved DAT_4e30)
        self.cc7 = {}                        # channel -> latest volume controller value of the songs (unscaled)
        self.main = self.trans = None        # song player / transition player
        self.song = None                     # id of the song in main
        self.entry = {}                      # per-song entry counter 71ab[n] (default -1)
        self.wait = None                     # (n, v): switch to n when main's measure count moves on (states 1, 3, 6)
        self.ref = 0                         # 7197: the measure count stored when the switch or transition began
        self.tick = 0                        # next music task update, in 1 / POLL_HZ s
        self.polling = False                 # 72f3: the update does not re-enter
        self.after = None                    # song to start when the transition player hits a boundary
        self.pending = None                  # request remembered during a transition (72ba)
        self.paused = None                   # time of a -2 pause (players keep their position), else None
        self.held = None                     # song request received while paused, replayed on resume

    # --- output ---------------------------------------------------------------------------------
    def _scale(self, v):
        return v if self.volume is None else min(127, v * min(self.volume, 127) // 100)

    def _put(self, t, m, p=None):
        """Emit message m at t; channel volume controllers are tracked and scaled by the music level. p: the player that
        sends it, whose caches follow (220f, 28c0, 28dc)."""
        hi, ch = m[0] & 0xF0, m[0] & 15
        if p:
            if hi == 0xB0 and m[1] in CACHED: p.cc[(m[1], ch)] = m[2]
            elif hi == 0xC0: p.program[ch] = m[1]
            elif hi == 0xE0: p.bend[ch] = m[1:3]
        if hi == 0xB0 and m[1] == CC_VOLUME:
            self.cc7[ch] = m[2]
            m = bytes([m[0], m[1], self._scale(m[2])])
        self.out.append((t, m))

    def _flush(self, p, t):
        """1fc3: note off for every queued note, in entry order."""
        for i, e in enumerate(p.queue):
            if e:
                self.out.append((t, bytes([0x80 | e[0], e[1], 0])))
                p.queue[i] = None

    def _release(self, p, t):
        """2021: sustain off where the sequence left it on."""
        for ch in range(16):
            if p.cc.get((64, ch), 0) >= 64: self.out.append((t, bytes([0xB0 | ch, 64, 0])))

    def _stop(self, p, t):
        """_XMI_STOP_SEQUENCE: only for a playing sequence."""
        if p.status != 1: return
        self._flush(p, t)
        self._release(p, t)
        p.status = 0

    def _resume(self, p, t):
        """20c8: resend the cached controllers, then each channel's pitch bend and program."""
        for c in CACHED:
            for ch in range(16):
                if (c, ch) in p.cc: self._put(t, bytes([0xB0 | ch, c, p.cc[(c, ch)]]))
        for ch in range(16):
            if ch in p.bend: self.out.append((t, bytes([0xE0 | ch]) + p.bend[ch]))
            if ch in p.program: self.out.append((t, bytes([0xC0 | ch, p.program[ch]])))

    def _kill(self, t):
        for name in ('main', 'trans'):
            if getattr(self, name): self._stop(getattr(self, name), t); setattr(self, name, None)

    # --- state machine --------------------------------------------------------------------------
    def _start(self, n, t, restart=False):
        """Start song n at t (entry-point counter), replacing main."""
        seq = self.lib.song(n)
        if restart:
            idx = seq.markers.get(RESTART, 0)
        else:
            e = self.entry.get(n, -1)
            idx = 0
            if e >= 0:
                if e in seq.markers: idx = seq.markers[e]
                elif 0 in seq.markers: idx = seq.markers[0]
                else: e = -1
            self.entry[n] = e + 1
        self.main, self.song = Player(seq, t, idx), n
        self.trace.append((t, 'start', n, idx))

    def _begin(self, n, t):
        """After a switch/transition: start n, then replay a remembered request."""
        self.wait = self.after = self.trans = None
        self._start(n, t)
        p, self.pending = self.pending, None
        if p is not None: self.request(p, t)

    def request(self, n, t):
        """MUSIC n (FUN_10f0_0953 -> seg 1198): n >= 0 song request, n < 0 control code.  Ignored while music is disabled."""
        if self.volume is not None and self.volume < 1:
            self.trace.append((t, 'disabled', n)); return
        if n >= 0: self.last_song = n
        elif n in (-1, -4): self.last_song = None
        if n in (-1, -4):
            # -1: the engine starts a one-step fade, but every script follows it with `MUSIC _GMRESET`, whose request
            # stops the old song immediately, so -1 is treated as stop. -4 = stop immediately.
            self._kill(t); self.song = self.wait = self.after = self.pending = self.paused = self.held = None
            self.trace.append((t, 'stop'))
            return
        if n == -2:                                    # pause: stop the sequences without releasing them, notes off
            if self.paused is None and (self.main or self.trans):
                self.paused = t
                for p in (self.main, self.trans):
                    if p: self._stop(p, t)
                self.trace.append((t, 'pause'))
            return
        if n == -3:                                    # resume from the paused position
            if self.paused is not None:
                for p in (self.main, self.trans):
                    if p:
                        p.base_step += step(t) - step(self.paused)
                        if p.status == 0: self._resume(p, t); p.status = 1
                self.paused = None
                self.trace.append((t, 'resume'))
                h, self.held = self.held, None
                if h is not None: self.request(h, t)
            return
        if n < 0:
            self.trace.append((t, 'ignored', n)); return
        if self.paused is not None:                    # ASSUMPTION: a song request while paused waits for the resume
            self.held = n; return
        if self.wait or self.trans:
            self.pending = n; return
        if n == self.song: return
        row = self.lib.table.get((self.song, n))
        if self.main is None or self.main.status == 2 or row is None:   # nothing playing, an ended song or no row: switch now
            self._kill(t); self._start(n, t)
        else:
            v = row[0] if row else 0                   # the transition value at measure 1 (module docstring)
            self.wait, self.ref = (n, v), self.main.count()
            self.trace.append((t, 'request', n, v))
        self._poll(t)                                  # 1668 ends with the music task's update (183b)

    def set_volume(self, level, t):
        """FUN_1100_0dc2 music half: level 0 stops and disables, level > 0 enables (a current song continues, else the last
        requested or the options song starts) and rescales the channel volumes."""
        if level < 1:
            if self.volume is None or self.volume > 0:
                keep = self.last_song
                self.request(-4, t)
                self.last_song = keep             # a volume stop does not forget the song (the engine's saved DAT_4e30)
            self.volume = level
            self.trace.append((t, 'volume', level)); return
        self.volume = level
        self.trace.append((t, 'volume', level))
        if self.song is None:
            self.request(self.last_song if self.last_song is not None else OPTIONS_MUSIC, t)
        for ch in sorted(self.cc7):
            self.out.append((t, bytes([0xB0 | ch, CC_VOLUME, self._scale(self.cc7[ch])])))

    def _moved(self, p):
        """FUN_1198_09fc: p's measure count differs from the stored one, or p no longer plays."""
        return p is None or p.status != 1 or max(1, p.count()) != self.ref

    def _poll(self, t):
        """The music task's update (FUN_1198_1054); paused music is left alone (no script pauses it)."""
        if self.polling or self.paused is not None: return
        self.polling = True
        m = self.main
        if m and m.status == 2 and not self.wait and not self.trans and self.lib.songs[self.song]['loop_measure'] > 0:
            self._start(self.song, t, restart=True)
            self.trace.append((t, 'restart', self.song))
        elif self.wait and self._moved(m):
            n, v = self.wait
            self.wait = None
            if v == 0:
                self._kill(t); self._begin(n, t)
            else:
                if v > 0: self._stop(m, t); self.main = None
                self.trans, self.after = Player(self.lib.transition(abs(v)), t), n
                self.ref = self.trans.count()
                self.trace.append((t, 'transition', abs(v), 'overlay' if v < 0 else 'replace', n))
        elif self.trans and self._moved(self.trans):
            self._kill(t); self._begin(self.after, t)
        self.polling = False

    def _step(self, p):
        """Execute p's note queue expiries due now, else its next item."""
        t = p.next_time()
        due = p.due_step()
        if due is not None and due <= p.item_step():
            for i, e in enumerate(p.queue):
                if e and e[2] <= due:
                    self.out.append((t, bytes([0x80 | e[0], e[1], 0])))
                    p.queue[i] = None
            return
        it = p.seq.items[p.idx]
        _, kind, a = it
        p.idx += 1
        if kind == 'note':
            b, dur = a
            i = next((i for i, e in enumerate(p.queue) if e is None), 0)
            p.queue[i] = (b[0] & 15, b[1], step(t) + max(dur, 1))
            self._put(t, b)
        elif kind == 'm':
            self._put(t, a, p)
        elif kind == 'bar':
            p.measure = a
        elif kind == 'for':
            p.stack.append([p.idx, a])
        elif kind == 'next' and p.stack:
            top = p.stack[-1]
            if top[1] == 0 or top[1] > 1:
                top[1] -= top[1] > 0
                p.jump(top[0], step(t))
                self.trace.append((t, 'loop', self.song if p is self.main else 'trans', p.seq.items[top[0]][0] / HZ))
            else:
                p.stack.pop()
        elif kind == 'end':
            self._release(p, t)
            p.status = 2                               # done: no longer served; the next update acts on it
            self.trace.append((t, 'end', 'trans' if p is self.trans else 'song'))

    def run(self, requests, end, volumes=()):
        reqs = sorted([(t, 0, n) for t, n in requests] + [(t, 1, m) for t, m in volumes], key=lambda r: (r[0], r[1]))
        ri = 0
        while True:
            cands = [(reqs[ri][0], 0, None)] if ri < len(reqs) else []
            cands.append((self.tick / POLL_HZ, 1, None))           # a game tick: requests, the update, then the music
            cands += [(p.next_time(), 2, p) for p in (self.main, self.trans) if p and p.status == 1 and self.paused is None]
            t, kind, p = min(cands, key=lambda c: (c[0], c[1]))
            if t >= end: break
            if kind == 0:
                ri += 1
                _, what, arg = reqs[ri - 1]
                if what: self.set_volume(arg, t)
                else: self.request(arg, t)
            elif kind == 1:
                self.tick += 1
                self._poll(t)
            else:
                self._step(p)
        self._kill(end)
        self.out.sort(key=lambda e: e[0])               # stable: keeps per-time order
        return self.out, self.trace


def sequence(lib, requests, end, volume=None, volumes=()):
    """requests: [(seconds, n)], end: seconds; volume / volumes: music level at the start and [(seconds, level)] changes
    (module docstring) -> (time-sorted [(seconds, bytes)], trace)."""
    return Sequencer(lib, volume).run(requests, end, volumes)


def bars_from_timesig(evnt):
    """Bar starts (ticks) from FF 58 time signatures and FF 51 tempos (tick-by-tick integration); used to
    cross-check the 0x77 grid (the tempo/time-signature metas are otherwise ignored by xmi.py)."""
    ev, _ = xmi.decode_evnt(evnt, keep_xmi=True)
    metas = sorted((t, e) for t, _, _, e in ev if e[:2] in (b'\xff\x51', b'\xff\x58'))
    tempo, num, den, i, left, bars = 500000, 4, 4, 0, 0.0, []
    for tick in range(max(e[0] for e in ev) + 1):
        while i < len(metas) and metas[i][0] <= tick:
            e = metas[i][1]
            if e[1] == 0x51: tempo = int.from_bytes(e[3:6], 'big')
            else: num, den = e[3], 1 << e[4]
            i += 1
        if left <= 1e-9: bars.append(tick); left = float(num)
        left -= 1 / (tempo * HZ / 1e6 * 4 / den)         # one tick = this fraction of a (1/den) beat
    return bars


# --- rendering ----------------------------------------------------------------------------------
def _binary():
    """Compiled midi2wav (cached in $MIDI2WAV_BIN or the system temp dir; rebuilt when the source is newer)."""
    exe = os.environ.get('MIDI2WAV_BIN') or os.path.join(tempfile.gettempdir(), 'bioforge-midi2wav')
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(SWIFT_SRC):
        subprocess.run(['swiftc', '-O', SWIFT_SRC, '-o', exe], check=True, capture_output=True)
    return exe


def render(events, duration, rate=22050, out=None):
    """GM-render [(seconds, bytes)] with Apple's built-in synth -> int16 stereo array (n, 2). Raises on failure."""
    sc = tempfile.mkdtemp()
    js, wav = os.path.join(sc, 'in.json'), out or os.path.join(sc, 'out.wav')
    json.dump({'duration': duration, 'events': [{'t': round(t, 6), 'b': list(b)} for t, b in events]}, open(js, 'w'))
    r = subprocess.run([_binary(), js, wav, str(rate)], capture_output=True, text=True)
    if r.returncode: raise RuntimeError(f'midi2wav failed: {r.stderr.strip()}')
    with wave.open(wav) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels())
    return pcm
