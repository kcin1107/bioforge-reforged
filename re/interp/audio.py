"""Audio: the voice statements SETVOLUME (10d0:750d), SETPITCH (10d0:7264), ADDTOPITCH (10d0:03bf), REPLACESOUND (10d0:6a73),
REVERTSOUND (10d0:6c22), BANKINSFX (10d0:095d), SETSOUNDCACHE (10d0:739f), REVERTSOUNDCACHE (10d0:6c73), the ramps
MODIFYVOLUMEOVERTIME (10d8:3788 -> 10c0:36b9) / MODIFYPITCHOVERTIME (10d8:374c -> 10c0:3589) and the camera / room ambient loops
(1130:0114 camera switch, 1130:0e6b per frame, 1100:1b59, 1100:1a15). The Swift twin is WorldAudio.swift.

World mixes `AudioMixin` in. Every statement returns at once (AL = 0); script errors continue (warnings here).

Voice state. 1028:09d3 keeps per voice a level (+0x08, the raw 0..255 volume after the positional rule, before the master table) and a
rate (+0x0a, `sample.rate - pitch`, the playback rate in Hz, a u16). The ports keep both per issued sound handle (`voice_state`). SETVOLUME
/ the ramps set the level (1028:1464 / 168e: clamp to 255, an underflow wraps to 255) and log it to `sound_volumes` (the mixer ramps per
handle); SETPITCH / ADDTOPITCH / the pitch ramp set the rate (1028:152b / 15db, no clamp) and log it to `sound_rates` (the mixers
resample with it from that tick on). A dead, unknown, 0 or -1 handle is silently ignored. A positional handle (figure sound) gets its
positional value back at the next frame (1030:07cf overwrites voice+0x08 every frame).
ASSUMPTION (re-timing): a rate change moves the end of a non-looped handle (AI_MAIN SLUR_ENEMY_SPEECH waits on ISHANDLEPLAYING). The
port counts samples played * TPS (`pos30`) and ends the handle when `length * TPS` is reached at the current rate; integer arithmetic only.

REPLACESOUND writes a sound symbol's value (the symbol table's record, +0x19); the port keeps `sound_overrides[name] -> sample id` and
`sound_index` consults it first. NOT PORTED: the overrides are not written into saves (open item: the original's saved SOUNDS.DEF holds
the current values). They persist across LOADLEVEL (script state).

Ambient loops. `_<CAM>_AMBIENT` / `_<ROOM>_AMBIENT` (ROOM = the camera's first 3 characters) play looped at priority 1, non-positional,
at the volume of the camera's volume binding (1110:19cc / 1e3c / 1e74 / 1eab): the script variable `_<CAM>_VOLUME` (else `_<CAM[:3]>_VOLUME`,
else unbound = 255). The shipped data names only 3-letter room ambients, so the camera loop is silent and GETCAMERAAMBIENT stays -1.
"""
import sys

import vm as vmmod


def _w(world):
    return sys.modules[type(world).__module__]


STMTS = frozenset(('SETVOLUME', 'SETPITCH', 'ADDTOPITCH', 'REPLACESOUND', 'REVERTSOUND', 'BANKINSFX', 'SETSOUNDCACHE', 'REVERTSOUNDCACHE'))


def num(v):
    return v if isinstance(v, int) else 0


def s32(v):
    v = int(v) & 0xffffffff
    return v - 0x100000000 if v & 0x80000000 else v


def tdiv(a, b):
    """C integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


class Voice:
    """Per sound handle: level (voice+0x08), rate (voice+0x0a), the sample id, and the playback position model of a non-looped handle
    (`length` samples; `pos30` = samples played * TPS at tick `t0`, at the rate in force since then)."""
    __slots__ = ('index', 'level', 'rate', 'length', 't0', 'pos30')

    def __init__(self, index, level, rate, length, t0):
        self.index, self.level, self.rate, self.length, self.t0, self.pos30 = index, level, rate, length, t0, 0


class Binding:
    """The camera's volume tracker (camera+0x7e): the bound script variable (or None), the cached value and the changed flag."""
    __slots__ = ('var', 'cache', 'dirty')

    def __init__(self, var, cache):
        self.var, self.cache, self.dirty = var, cache, False


class AudioMixin:
    # ---- voice state
    def voice_start(self, h, idx, volume, pitch, looped, length):
        """A sound handle was issued (play_sound): level = the volume after the positional rule, rate = sample.rate - pitch (1028:09d3)."""
        sm, _ = _w(self).sound_bank(self.settings.language)
        self.voice_state[h] = Voice(idx, volume, (sm.get(idx).rate - pitch) & 0xffff, None if looped else length, self.vm.tick)

    def live_voice(self, h):
        """The Voice of a live sound handle, or None (dead, unknown, 0, -1 or not a sound)."""
        v = self.voice_state.get(h) if isinstance(h, int) else None
        return v if v is not None and self.vm is not None and h in self.vm.procs else None

    def log_volume(self, h, v):
        """Append (tick, handle, level) to sound_volumes. Several entries of one handle may share a tick (a ramp's step and remainder,
        SETVOLUME plus the positional refresh): the mixers keep the last."""
        self.sound_volumes.append((self.vm.tick, h, v))

    def set_level(self, h, v):
        """1028:1464: v is unsigned 16 bit, clamped to 255. Live only. A positional handle is re-evaluated by the next frame's refresh."""
        v = min(v & 0xffff, 255)
        voice = self.live_voice(h)
        if voice is None:
            return
        voice.level = v
        self.log_volume(h, v)
        if h in self.sound_pos:
            self.sound_pos[h] = (self.sound_pos[h][0], v)

    def add_level(self, h, x):
        """1028:168e: (level + x) as an unsigned 16 bit, clamped to 255 (an underflow wraps to 255)."""
        voice = self.live_voice(h)
        if voice is not None:
            self.set_level(h, voice.level + x)

    def set_rate(self, h, r):
        """1028:152b: the rate word := r (u16, no clamp)."""
        voice = self.live_voice(h)
        if voice is not None:
            self.change_rate(h, voice, r & 0xffff)

    def add_rate(self, h, d):
        """1028:15db: the rate word += d (u16 wrap)."""
        voice = self.live_voice(h)
        if voice is not None:
            self.change_rate(h, voice, (voice.rate + d) & 0xffff)

    def change_rate(self, h, voice, rate):
        tick = self.vm.tick
        self.sound_rates.append((tick, h, rate))
        voice.pos30 += (tick - voice.t0) * voice.rate
        voice.t0, voice.rate = tick, rate
        if voice.length is None:                           # a looped handle is not re-timed
            return
        remaining = voice.length * vmmod.TPS - voice.pos30
        if remaining <= 0:
            wake = tick + 1
        elif rate == 0:
            wake = vmmod.FOREVER
        else:
            wake = tick + max(1, -(-remaining // rate))
        self.vm.procs[h].wake = wake

    def release_loop(self, h):
        """STOPAMBIENT on a looped voice (1028:10c9 -> 1000:046f): the voice's end (+0x10) becomes the sample's end (+0x0c) and its state
        2, so the mixer (1000:115a) plays on from where it is without wrapping and frees the voice at the end. The handle and its voice slot
        stay live until then (ISHANDLEPLAYING; AWAKEN's quake waits on it). From here on it is timed like a one-shot: `length` and the
        position in the sample (`pos30`, the loop wrapped). A second release changes nothing. -> logged to `sound_releases`."""
        voice = self.live_voice(h)
        if voice is None or voice.length is not None:
            return
        sm, _ = _w(self).sound_bank(self.settings.language)
        s, tick, tps = sm.get(voice.index), self.vm.tick, vmmod.TPS
        p30 = voice.pos30 + (tick - voice.t0) * voice.rate
        lo, hi = s.loop_start * tps, s.loop_end * tps
        if hi > lo and p30 >= hi:
            p30 = lo + (p30 - lo) % (hi - lo)
        voice.pos30, voice.t0, voice.length = p30, tick, len(s.pcm)
        self.sound_releases.append((tick, h))
        remaining = voice.length * tps - p30
        if remaining <= 0:
            wake = tick + 1
        elif voice.rate == 0:
            wake = vmmod.FOREVER
        else:
            wake = tick + max(1, -(-remaining // voice.rate))
        self.vm.procs[h].wake = wake

    # ---- statements
    def cmd_audio(self, name, args):
        """SETVOLUME / SETPITCH / ADDTOPITCH `handle value` (a handle of 0 or -1, or not a number, is skipped); REPLACESOUND `name value`,
        REVERTSOUND `name`; BANKINSFX / SETSOUNDCACHE / REVERTSOUNDCACHE are sample-cache only (modelled no-ops)."""
        if name in ('SETVOLUME', 'SETPITCH', 'ADDTOPITCH'):
            h = args[0] if args else 0
            if not isinstance(h, int) or h in (0, -1):
                return
            value = num(args[1]) if len(args) > 1 else 0
            if name == 'SETPITCH':
                self.set_rate(h, value)
            elif name == 'ADDTOPITCH':
                self.add_rate(h, value & 0xffff)
            else:
                self.set_level(h, value)
                cam = self.current_camera()
                if cam is not None and h in (self.room_ambient, self.camera_ambient):
                    self.binding_set(self.binding(cam), value)     # 10d0:750d: even when the voice is already dead
        elif name == 'REPLACESOUND':
            sm, ids = _w(self).sound_bank(self.settings.language)
            key = args[0].lower() if args and isinstance(args[0], str) else None
            if key not in ids:
                self.warn('REPLACESOUND: not a sound name (error 0x34)')
                return
            value = args[1] if len(args) > 1 else 0
            if isinstance(value, str):                     # another sound name: its CURRENT value (chains copy, they do not follow)
                value = self.sound_overrides.get(value.lower(), ids.get(value.lower()))
            if not isinstance(value, int):
                self.warn(f'REPLACESOUND {args[0]}: unknown value {args[1]!r}')
                return
            self.sound_overrides[key] = value
        elif name == 'REVERTSOUND':
            _, ids = _w(self).sound_bank(self.settings.language)
            key = args[0].lower() if args and isinstance(args[0], str) else None
            if key not in ids:
                self.warn('REVERTSOUND: not a sound name (error 0x34)')
                return
            self.sound_overrides.pop(key, None)            # 6c22: the DEF value comes back
        elif name == 'SETSOUNDCACHE':
            # 10d0:739f: limit [19bb] := FUN_1008_06ab(a << 10, b, c << 10) = a KB, plus b * (free - 5,000,000) / 1024 when more than 5 MB are
            # free, capped at c KB (c != 0); evicts LRU samples above it. Memory management only: no effect here.
            if not all(num(a) for a in (list(args) + [0, 0, 0])[:3]):
                self.warn('SETSOUNDCACHE: needs three non-zero values (error 0x17c)')

    # ---- MODIFYVOLUMEOVERTIME / MODIFYPITCHOVERTIME
    def cmd_overtime(self, name, args):
        """`FN(handle, START, END, DURATION)` is an absolute ramp (DURATION != 0), `FN(handle, DELTA, DURATION)` a relative one
        (10c0:36b9 volume / 10c0:3589 pitch). Error 0x3a (START == END, DELTA == 0) returns 0 without a task; ASSUMPTION: DURATION <= 0
        does too (the engine would divide by zero; no shipped use). -> a new VM native handle that lives exactly DURATION ticks
        (the original task serial from [2ed0]; SUSPENDWHILE on it releases after DURATION ticks)."""
        volume = name == 'MODIFYVOLUMEOVERTIME'
        a = ([num(x) for x in args] + [0, 0, 0, 0])[:4]
        h = a[0]
        absolute = a[3] != 0
        if absolute:
            start, delta, dur = a[1], s32(a[2] - a[1]), s32(a[3])
        else:
            start, delta, dur = None, s32(a[1]), s32(a[2])
        if delta == 0 or dur <= 0:
            self.warn(f'{name}: nothing to ramp (error 0x3a)')
            return 0
        if self.vm is None:
            return 0
        binding = None
        cam = self.current_camera()
        if volume and cam is not None and h not in (0, -1) and h in (self.room_ambient, self.camera_ambient):
            binding = self.binding(cam)                    # 10b8:04d3 / 0653: the current camera's tracker
        if absolute:                                       # 10b8:04d3: the start value is set at once
            if volume:
                self.set_level(h, start)
                if binding is not None:
                    self.binding_set(binding, start)
            else:
                self.set_rate(h, start)
        # 10b8:0762: |delta| < D (case A): step = +1 ALWAYS, period = D / delta (negative for delta < 0: it then fires every tick, so
        # INTRO.scr:416 `(_sfx_2, 65, 0, 120)` RISES by 120: INFERRED from the disassembly, replicated); else step = delta / D, the
        # remainder on the last tick, period 1.
        if abs(delta) < dur:
            step, rem, period = 1, 0, tdiv(dur, delta)
        else:
            step = tdiv(delta, dur)
            rem, period = delta - step * dur, 1

        def apply(x):                                      # 10b8:090c
            if volume:
                self.add_level(h, x)
                if binding is not None:
                    self.binding_set(binding, self.binding_get(binding) + x)
            else:
                self.add_rate(h, x)

        def gen():
            yield 1                                        # the first advance is on the next update
            countdown, elapsed = period, 0
            while True:                                    # 10b8:0853
                elapsed += 1
                countdown -= 1
                if countdown <= 0:
                    countdown = period
                    apply(step)
                if elapsed == dur:
                    apply(rem)
                    return
                yield 1

        return self.vm.native_generator('MODIFYVOLUMEOVERTIME' if volume else 'MODIFYPITCHOVERTIME', gen())

    # ---- camera / room ambient loops
    def binding(self, cam):
        """The volume tracker of camera `cam` (1110:19cc): bound to the script variable `_<CAM>_VOLUME`, else `_<CAM[:3]>_VOLUME`, else
        unbound (255). ASSUMPTION: a bound tracker starts with the variable's value as its cache."""
        b = self.ambient_bindings.get(cam)
        if b is None:
            var = next((n for n in (f'_{cam.lower()}_volume', f'_{cam[:3].lower()}_volume') if n in self.vm.globals), None)
            b = self.ambient_bindings[cam] = Binding(var, 255 if var is None else num(self.vm.globals[var]))
        return b

    def binding_get(self, b):
        """1110:1e74: reads the variable into the cache, clears the changed flag."""
        if b.var is not None:
            b.cache = num(self.vm.globals[b.var])
        b.dirty = False
        return b.cache

    def binding_changed(self, b):
        """1110:1e3c: the variable differs from the cache (bound), or the flag is set (unbound)."""
        return b.cache != num(self.vm.globals[b.var]) if b.var is not None else b.dirty

    def binding_set(self, b, v):
        """1110:1eab: cache := v (flag set when it changes); a bound tracker writes the script variable."""
        if v != b.cache:
            b.dirty = True
        b.cache = v
        if b.var is not None:
            self.vm.set_global(b.var, v)

    def ambient_id(self, name):
        """1118:0044, the lookup of every name the engine formats (room and camera loops, hits, blocks, BONKs, `_METAL_HITS_`, the last
        motion-cue try): the sound named `name` (case-insensitive, through sound_index so REPLACESOUND applies; a name longer than 25
        characters is cut to 24); not found: strip the last `_xxx` segment and retry; nothing left -> -1."""
        if len(name) > 25:
            name = name[:24]
        while name:
            idx = self.sound_index(name)
            if idx is not None:
                return idx
            k = name.rfind('_')
            name = name[:k] if k > 0 else ''
        return -1

    def motion_cue(self, fig, n):
        """FUN_1088_13ea, a sound cue: the first of `_<motion>_<n>_<form>_<camera>`, `_<motion>_<n>_<form>_<room>`, `_<motion>_<n>_<camera>`,
        `_<motion>_<n>_<room>` the bank has exactly (FUN_1100_1d82), else `_<motion>_<n>_<form>` through 1118:0044 (FUN_1100_1c92: cut at
        the last `_` until found, so Lex's `_WALK_1_LEX` exists and `_ATK_M1_1_CAYNAN` is an alias of `_WALK_1_CAYNAN`). form = +0x1ea
        (fig.type), camera = [63e1], room = [63e5] (its first 3 characters). Priority 0, volume 255, pitch 0, positional at the figure."""
        cam = self.switching_to or self.camera or self.default_camera or ''
        m, form = fig.motion, fig.type
        for name in (f'_{m}_{n}_{form}_{cam}', f'_{m}_{n}_{form}_{cam[:3]}', f'_{m}_{n}_{cam}', f'_{m}_{n}_{cam[:3]}'):
            idx = self.sound_index(name)
            if idx is not None:
                break
        else:
            idx = self.ambient_id(f'_{m}_{n}_{form}')
            if idx < 0:
                return
        self.play_sound(idx, priority=0, fig=fig if fig.pos is not None else None)

    def start_or_keep(self, handle, name, vol):
        """1100:1b59 (stop mode 0): keep the loop when its sample is unchanged (only the volume is re-set), else stop the old one at once
        and start the new one (1100:1a15 -> 1028:0f0a: looped, priority 1, volume low byte, pitch 0, not positional). -> the handle."""
        idx = self.ambient_id(name)
        voice = self.live_voice(handle)
        if (voice.index if voice is not None else -1) == idx:
            if handle:
                self.set_level(handle, vol)
            return handle
        if handle:
            self.stop_sound(handle)
            if handle in self.sound_handles and all(h != handle for _, h in self.sound_stops):
                self.sound_stops.append((self.vm.tick, handle))     # a loop whose process ended without a stop: end its voice in the mix
        return self.play_sound(idx, vol & 0xff, 0, loop=True, priority=1) if idx >= 0 else 0

    def update_ambients(self):
        """1130:0e6b, every unpaused frame: after a camera switch start / keep the camera and room loops at the binding's volume; then a
        changed binding (a script assigned `_<CAM>_VOLUME`, SETVOLUME / a ramp on an ambient handle) re-sets both handles."""
        cam = self.current_camera()
        if cam is None or self.vm is None:
            return
        b = self.binding(cam)
        if self.ambient_pending:
            vol = self.binding_get(b)
            self.camera_ambient = self.start_or_keep(self.camera_ambient, f'_{cam}_AMBIENT', vol)
            self.room_ambient = self.start_or_keep(self.room_ambient, f'_{cam[:3]}_AMBIENT', vol)
            self.ambient_pending = False
        if self.binding_changed(b):
            v = self.binding_get(b)
            if self.room_ambient:
                self.set_level(self.room_ambient, v)
            if self.camera_ambient:
                self.set_level(self.camera_ambient, v)

    def camera_switched(self):
        """1130:0114 step e: [63f1] := 1 unless a monitor is running ([4e2c], ISMONITORRUNNING)."""
        if not (self.monitor is not None or (self.options is not None and not self.options.closed)):
            self.ambient_pending = True
