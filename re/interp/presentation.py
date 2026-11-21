"""Presentation: what the player sees on top of the simulation. DEBUG / DEBUGINFO (10d0:2445 / 10d0:25cf), CHANGEPALETTE (10d0:1a43), the
FADE function (10d8:17e6), RUMBLE (10d0:6dc6), CAPTION (10d0:16cb) and the monitor pointer set-ups SET_PTR_MOVEMENT (10d0:72b2) and
SET_PTR_PRESS_TIME (10d0:72ef). The Swift twin is WorldPresentation.swift.

World mixes `PresentationMixin` in; world.py calls `cmd_presentation` (the statements), `cmd_fade` (the function), `step_presentation` (once
per tick, after the paused check) and `present_rgb` (play.py's to_rgb, the player-facing frame).

DEBUG / DEBUGINFO are release-build no-ops: the only consumer of their trace mode (10c0:24dc) is an empty `return`. They are only listed as modelled.

Palette: the engine keeps ONE additive offset per channel (DS:c672/4/6) = the gamma offset (1100:0e6f) + the CHANGEPALETTE argument (10e8:18c1), applied
to every one of the 256 entries on the 6-bit VGA values and clamped 0..63 (10e8:16bb). A Fade process scales the source palette in 8.8 fixed
point before the offset is added (1148:1de8). `present_palette` is that whole step, on the 8-bit channels the pipeline stores (c * 255 // 63).
"""
import functools
import re
import sys

import numpy as np

import settings as settings_mod

STMTS = frozenset(('CHANGEPALETTE', 'RUMBLE', 'CAPTION', 'SET_PTR_MOVEMENT', 'SET_PTR_PRESS_TIME'))
PAL_CUT_LIMIT = 12                  # 10e8:1dcc: |dR|+|dG|+|dB| above this on one of entries 0..254 blacks the DAC for the cut
FADE_DEFAULT = 20                   # FADE UP / DOWN without a number (3c74: duration 0 -> 0x14)
TICKS_PER_CHARACTER = 7             # RED.OPT TicksPerCharacter=7 ([2d52]); 60 Hz ticks per caption character
CAPTION_MAX = 0x15f                 # 10b0:0e5a drops a caption of this many characters or more
RUMBLE_MAX = 127                    # 1 .. 127 is the random shake; 0xff (-1) is the fixed MOVE offset (1140:1313)
RUMBLE_LCG = 65539                  # ASSUMPTION: a dedicated LCG seed*65539+1 (FUN_11c8:197e), seeded 0; the engine's shared stream is not recovered
PTR_DEFAULT_PRESS = (14, 5, 14)     # VARS.DEF _PTR_PRESS_TIME / _PTR_HOLD_TIME / _PTR_RELEASE_TIME (1270:00c4-0100)
PTR_DEFAULT_MOVEMENT = (0x140, 2)   # P+0x73 (ctor 1270:04ee) and P+0x5f (written back to 2 at every glide start, 1270:0642)


def _w(world):
    return sys.modules[type(world).__module__]


def s16(value):
    value = int(value) & 0xffff
    return value - 0x10000 if value & 0x8000 else value


def s8(value):
    value = int(value) & 0xff
    return value - 0x100 if value & 0x80 else value


@functools.lru_cache(maxsize=None)
def _channel_lut(offset, fade):
    """256 8-bit values after: back to 6 bits (as gamma_lut), scale by the fade (8.8, None = 256), add `offset`, clamp 0..63, expand."""
    if fade == 'black':
        return np.zeros(256, np.uint8)
    src = (np.arange(256) * 63 + 254) // 255
    base = src if fade is None else (src * fade) >> 8
    return (np.clip(base + offset, 0, 63) * 255 // 63).astype(np.uint8)


def present_palette(pal, gamma, cp=(0, 0, 0), fade=None):
    """The presented palette (or frame) for a source one: `pal` is an array (..., 3) of 8-bit channels. gamma = the setting (0..100);
    cp = the CHANGEPALETTE offsets (r, g, b) in 6-bit units; fade = None (normal), 'black' (FADE HIDE: all zero, no offset) or the Fade
    process's 8.8 scale (0..256; scale 0 keeps the offset, so with gamma 50 the "black" is 6,6,6). With cp zero and no fade it is gamma_lut."""
    pal = np.asarray(pal)
    g = settings_mod.gamma_offset(gamma)
    return np.stack([_channel_lut(g + int(cp[k]), fade)[pal[..., k]] for k in range(3)], -1)


def shift_frame(a, x, y, xp, fill):
    """1140:0ff0: the page moved by (+x, +y) pixels. Rows revealed at the top (y > 0) / bottom (y < 0) take `fill`; columns revealed at the
    left / right keep their old pixels. Rows alternate between x and xp in pairs: for y >= 0 the source rows h-1-y, h-3-y .. use x and the
    ones between use xp; for y < 0 the rows -y, -y+2 .. use x. (The original leaves 1-2 edge rows stale; not ported.) `a` is (h, w) or (h, w, k)."""
    h, w = a.shape[:2]
    out = a.copy()
    if y > 0:
        out[:min(y, h)] = fill
    elif y < 0:
        out[max(h + y, 0):] = fill
    first = (h - 1 - y) % 2 if y >= 0 else (-y) % 2
    for d in range(h):
        s = d - y
        if not 0 <= s < h:
            continue
        dx = x if s % 2 == first else xp
        if 0 <= dx < w:
            out[d, dx:] = a[s, :w - dx]
        elif -w < dx < 0:
            out[d, :w + dx] = a[s, -dx:]
    return out


def sprintf16(fmt, nums):
    """The CAPTION printf (FUN_1000_586c with the 10 s32 arguments flattened to 20 little-endian 16-bit words, missing ones 0): %d %i %u %x %X
    %c take one word, %l? two, %% none. A second %d reads the HIGH word of the first argument, not the second argument."""
    words = []
    for k in range(10):
        v = int(nums[k]) if k < len(nums) else 0
        words += [v & 0xffff, (v >> 16) & 0xffff]
    pos = [0]

    def take(n):
        v = 0
        for i in range(n):
            v |= (words[pos[0]] if pos[0] < len(words) else 0) << (16 * i)
            pos[0] += 1
        return v

    def sub(m):
        flags, width, long, conv = m.groups()
        if conv == '%':
            return '%'
        bits = 32 if long else 16
        v = take(2 if long else 1)
        if conv in 'di' and v >= 1 << (bits - 1):
            v -= 1 << bits
        text = chr(v & 0xff) if conv == 'c' else format(v, 'x' if conv == 'x' else 'X' if conv == 'X' else 'd')
        n = int(width) if width else 0
        if '-' in flags:
            return text.ljust(n)
        return text.rjust(n, '0' if '0' in flags and conv != 'c' else ' ')

    return re.sub(r'%([-0]*)(\d*)(l?)([diuxXc%])', sub, fmt)


def caption_text(text, lang='E'):
    """FUN_1120_03d2: the segment after "/<lang>", else after "/E", else the whole string (a leading "/" + one character, as "/!", is
    skipped), cut at the next "/"."""
    for tag in ('/' + lang, '/E'):
        i = text.find(tag)
        if i >= 0:
            text = text[i + 2:]
            break
    else:
        text = text[2:] if text.startswith('/') else text
    return text.split('/')[0]


class PresentationMixin:
    pal_state = 0              # DS:49bd: 0 normal, 1 fading down, 2 black, 3 fading up
    pal_installed = None       # the raw 6-bit palette last installed (c368+2), for palette_cut
    pal_fade = None            # what the DAC shows: None normal, 'black' (HIDE) or the Fade scale in 8.8 (present_palette)
    fade_handle = None         # the newest Fade process (DS:662a); only it writes the palette
    cp = (0, 0, 0)             # CHANGEPALETTE offsets (DS:c672/4/6 minus the gamma offset)
    cp_ticks = 0               # its duration d in 30 Hz ticks: 0 / negative persistent
    cp_age = None              # renders since it was latched, None until the first one
    rumble_amp = rumble_x = rumble_y = rumble_vx = rumble_vy = rumble_xp = rumble_yp = 0    # DS:6576..657c
    rumble_seed = 0

    @staticmethod
    def _words_nums(args):
        flat = [a for v in args for a in (v if isinstance(v, list) else [v])]
        return [str(a) for a in flat if isinstance(a, str)], [a for a in flat if isinstance(a, int)]

    def cmd_presentation(self, name, args, proc):
        words, nums = self._words_nums(args)
        num = lambda k: nums[k] if k < len(nums) else 0
        if name == 'CHANGEPALETTE':
            self.cmd_changepalette([s16(num(k)) for k in range(4)])
        elif name == 'RUMBLE':
            self.cmd_rumble(words, nums)
        elif name == 'CAPTION':
            self.cmd_caption(proc, words, nums)
        elif self.monitor is not None:             # SET_PTR_*: nothing before MON_START (no monitor running)
            if name == 'SET_PTR_MOVEMENT':
                self.monitor.ptr_movement = (num(0) & 0xffff, num(1) & 0xffff)
            else:
                self.monitor.ptr_press_time = tuple(num(k) & 0xffff for k in range(3))

    # ---- CHANGEPALETTE
    def cmd_changepalette(self, a):
        """`CHANGEPALETTE r g b d` (10d0:1a43 -> 10e8:1427 -> 18c1): signed additive offsets in 6-bit units that REPLACE any earlier one. d is
        in 30 Hz ticks: <= 0 persistent; d >= 1 reverts after d presented frames, counted from the first render after the statement
        (d == 1, the "flash": the engine busy-waits 50 ms at the next render; ASSUMPTION: the ports show exactly one tinted frame). The
        render is `step_presentation`, the once-per-tick step. Never blocks, not saved."""
        self.cp, self.cp_ticks, self.cp_age = tuple(a[:3]), a[3], None

    def cancel_changepalette(self):
        """Setting the gamma (FUN_1100_0e6f) calls 18c1(0, 0, 0)."""
        self.cp, self.cp_ticks, self.cp_age = (0, 0, 0), 0, None

    def step_presentation(self):
        """10e8:145c at the top of the per-frame render (game not paused): the CHANGEPALETTE timer. ASSUMPTION: the ports' per-tick hook is
        World.step (after the tick's scripts, before the frame is drawn)."""
        if self.cp_ticks > 0:
            self.cp_age = 0 if self.cp_age is None else self.cp_age + 1
            if self.cp_age >= self.cp_ticks:
                self.cancel_changepalette()

    # ---- FADE
    def cmd_fade(self, proc, args):
        """`FADE HIDE|SHOW|UP [n]|DOWN [n]` (10d8:17e6 -> 10c0:3c74), n in 30 Hz steps (default 20). HIDE: all-zero palette, state 2; SHOW: normal,
        state 0; both return 0. UP is a no-op (0) in states 0 and 3, DOWN in 1 and 2; otherwise the state becomes 3 / 1 and a Fade process
        (class "Fade", 1148:1ca5; handle returned, valid for n ticks) steps once per tick, the first on the tick after the statement
        (ASSUMPTION): k += 1, scale = (k << 8) // n (UP) or ((n - k) << 8) // n (DOWN), presented = clamp((src * scale >> 8) + offsets).
        Only the newest process writes (and an UP not in state 2 / a DOWN always, 1148:1de8); at k == n UP restores the normal palette (state
        0) and DOWN leaves the scale-0 palette in state 2. A missing or unknown word warns (error 0x69) and returns 0."""
        words, nums = self._words_nums(args)
        word = words[0].upper() if words else ''
        if word == 'HIDE':
            self.pal_fade, self.pal_state = 'black', 2
        elif word == 'SHOW':
            self.pal_fade, self.pal_state = None, 0
        elif word in ('UP', 'DOWN'):
            n = (nums[0] & 0xffff if nums else 0) or FADE_DEFAULT
            down = word == 'DOWN'
            if self.vm is None or self.pal_state in ((1, 2) if down else (0, 3)):
                return 0
            self.pal_state = 1 if down else 3
            h = self.vm.native_handle('Fade', )       # a kernel task: LOADLEVEL's kill walk (10b0:13fb) ends it like any other
            self.fade_handle = h
            p = self.vm.procs[h]
            p.gen = self._fade_steps(h, n, down)                    # the handle made by native_handle runs this instead of sleeping forever
            p.wake = self.vm.tick + 1
            return h
        else:
            self.warn(f'FADE {word or "(no word)"}: needs HIDE, SHOW, UP or DOWN (error 0x69)')
        return 0

    def _fade_steps(self, handle, n, down):
        for k in range(1, n + 1):
            scale = ((n - k) << 8) // n if down else (k << 8) // n
            if handle == self.fade_handle and (down or self.pal_state != 2):       # 1148:1de8: the DAC write condition
                self.pal_fade = scale
            if k == n:
                if down:
                    self.pal_state = 2
                else:
                    self.pal_fade, self.pal_state = None, 0
            else:
                yield 1

    # ---- RUMBLE
    def cmd_rumble(self, words, nums):
        """`RUMBLE` / `RUMBLE 0` stop (zero amplitude, x, y, vx, vy); `RUMBLE n` sets the amplitude (s8) and leaves the offsets; `RUMBLE MOVE a b c d`
        sets amplitude 0xff with x = a, y = b, xp = c, yp = d (s8; all four zero only clears the amplitude) (10d0:6dc6, 1140:12d5 / 133b /
        134a). Presentation only."""
        num = lambda k: nums[k] if k < len(nums) else 0
        if words and words[0].upper() == 'MOVE':
            a = [num(k) & 0xffff for k in range(4)]
            if not any(a):
                self.rumble_amp = 0
            else:
                self.rumble_amp, self.rumble_x, self.rumble_y, self.rumble_xp, self.rumble_yp = -1, *(s8(v) for v in a)
        elif num(0) & 0xffffffff == 0:
            self.rumble_amp = self.rumble_x = self.rumble_y = self.rumble_vx = self.rumble_vy = 0
        else:
            self.rumble_amp = s8(num(0))

    def rumble_rand2(self):
        self.rumble_seed = (self.rumble_seed * RUMBLE_LCG + 1) & 0xffffffff
        return (self.rumble_seed >> 16) & 1

    def rumble_step(self):
        """1140:11cf, once per presented frame while 1 <= amplitude <= 127: the previous x is kept, a spring pulls the velocities toward 0,
        +-1 random per axis (vx's first), velocities are clamped to +-amplitude, then x += vx, y += vy."""
        if not 1 <= self.rumble_amp <= RUMBLE_MAX:
            return
        a = self.rumble_amp
        self.rumble_xp, self.rumble_yp = self.rumble_x, self.rumble_y
        vx, vy = self.rumble_vx, self.rumble_vy
        vx += (-self.rumble_x) >> 1 if self.rumble_x < 0 else -(self.rumble_x >> 1)
        vy += (-self.rumble_y) >> 1 if self.rumble_y < 0 else -(self.rumble_y >> 1)
        vx += -1 if self.rumble_rand2() == 0 else 1
        vy += -1 if self.rumble_rand2() == 0 else 1
        self.rumble_vx, self.rumble_vy = max(-a, min(a, vx)), max(-a, min(a, vy))
        self.rumble_x += self.rumble_vx
        self.rumble_y += self.rumble_vy

    def rumble_frame(self, a, fill=0):
        """1140:1313: shift the presented page by the current offsets, then advance the shake. Skipped while paused. ASSUMPTION: the page's
        black index ([7a7e]) is true black (`fill` 0 on an RGB frame); the HUD and captions shift with the scene."""
        if self.paused or self.frozen or self.rumble_amp == 0:
            return a
        out = shift_frame(a, self.rumble_x, self.rumble_y, self.rumble_xp, fill)
        self.rumble_step()
        return out

    def palette_cut(self, src):
        """10e8:1dcc, once per presented frame: `src` is the screen's source palette, raw 6-bit (256, 3), before gamma, CHANGEPALETTE and
        fade. With no fade running, down or black (DS:49bd == 0) and a source that differs from the one last installed (c368+2: the
        pending palette that 17d8 installed; a source that equals it is no write) by more than 12 in |dR|+|dG|+|dB| on any entry 0..254,
        the original sets the DAC black (183d), draws the frame and installs the new palette (17d8) within that one call. -> True when
        this presented frame is that black one. The installed palette follows the source on every frame with no fade; during a fade it
        stays, so the compare runs against it when the fade ends (the original leaves the pending palette until 49bd is 0).
        ASSUMPTION: the blit is the whole black time, so the nearest whole-frame equivalent is one black presented frame, display only."""
        if src is None or self.pal_state != 0:
            return False
        src = np.asarray(src, np.int32)[:, :3]
        old, self.pal_installed = self.pal_installed, src.copy()
        return old is not None and bool((np.abs(src[:255] - old[:255]).sum(axis=1) > PAL_CUT_LIMIT).any())

    def present_rgb(self, frame, src_pal=None):
        """The player-facing RGB frame (play.py to_rgb): the RUMBLE shift, then the palette step (gamma, CHANGEPALETTE, fade). `src_pal`
        is the screen's 6-bit source palette (palette_cut); a cut presents one black frame."""
        out = present_palette(self.rumble_frame(frame), self.gamma, self.cp, self.pal_fade).astype(np.uint8)
        return np.zeros_like(out) if self.palette_cut(src_pal) else out

    # ---- CAPTION
    def cmd_caption(self, proc, words, nums):
        """`CAPTION "fmt" [numbers] [PAUSE]` (10d0:16cb -> 10b0:0e5a). No string: warning (error 0x2e), nothing shown. The text is sprintf16, then
        language-filtered (caption_text); >= 351 characters are dropped. It lives 7 * len 60 Hz ticks = ceil(7 * len / 2) VM ticks (ASSUMPTION
        on the rounding) and REPLACES any caption or subtitle on screen. Drawn through the subtitle path, centred, colour 0x75 (ASSUMPTION:
        the caption object sets none, as for Alt+V); it shows with subtitles off too (10b0:0f48 never reads [50bc]). A second word must be
        PAUSE, which blocks the caller until the caption ends; any other warns (error 0x127) and the caption still shows."""
        if not words or not words[0]:
            self.warn('CAPTION: needs a string (error 0x2e)')
            return
        raw = sprintf16(words[0], nums)
        h = 0
        if len(raw) < CAPTION_MAX and self.vm is not None:
            text = caption_text(raw, self.settings.language)
            h = self.subtitle((None, 0x75, 0xff, text), ticks=(TICKS_PER_CHARACTER * len(text) + 1) // 2)
            self.caption_handles.add(h)
        if len(words) > 1 and words[1]:
            if words[1].upper() == 'PAUSE':
                if h:
                    proc.wait_pred = lambda: h not in self.vm.procs
            else:
                self.warn(f'CAPTION: unexpected word {words[1]} (error 0x127)')
