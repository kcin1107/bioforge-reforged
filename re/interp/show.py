"""Show: the FLIC statements and functions STARTFLIC (10d0:7761 -> 1140:0c6a), STOPFLIC (782f -> 0ecc), SETFLICRATE (7042 -> 0dfc), FLICLOOP
(2f64), PLAYFLIC (10d8:3950) and RUNFLIC (10d8:3a40 -> 10c8:0636), FREEZE / THAW (10d0:3314 / 84c4 -> 10c8:04de / 05b2), the front-end
statements MENU / UNMENU (10d0:5396 / 539d), ADDKEY (10d0:025f), EXIT (10d0:2835) and the functions WASALTPRESSED (10d8:3cc1), CREDITSSTATE
(10d8:1110) and GETOPTDATA (10d8:267f -> 10f0:0651), plus the CAPTUREKEYBOARD hook (10d0:1823 / 1138:1da6). JUMPON (10d0:4024) lives in vm.py.
The Swift twin is WorldShow.swift.

World mixes `ShowMixin` in. One global flic object (DS:6538) is open between STARTFLIC and STOPFLIC; while it is, the frame renderer 1100:0580 draws
it INSTEAD of the world (World.render returns the flic frame; play.to_rgb passes it through the palette step like any frame). `step_show` is the
once-per-render step (World.step, before the frozen check: the flic clock [8334] is the real, never paused one, 2 units of 60 Hz per VM tick).

Timed mode (1140:077b): the first render after STARTFLIC / RUNFLIC sets last = clock - interval, so the first frame is due at once; at most one frame
per render, drawn when last + interval <= clock (last += interval, index++); finished at the render where the next frame is due and index >= count
or (limit and index >= limit): limit L is exclusive. Var mode (a live variable): the interval is ignored; frames are drawn until index > variable,
never backwards. NOT PORTED: the engine's catch-up (the clock is set back when more than one frame is due per render), which with one render per
tick can only happen at interval 1 in timed mode (not shipped). A RUNFLIC scene is a timeline process (stamps SS:TT = SS * 30 + TT ticks from the
RUNFLIC tick, vm.py) that ends when no flic is open or the flic has finished (10c8:081b step 2).
"""
import os
import re

import numpy as np

import flc as flc_mod
import parse
import settings as settings_mod

STMTS = frozenset(('STARTFLIC', 'STOPFLIC', 'SETFLICRATE', 'FLICLOOP', 'FREEZE', 'THAW', 'MENU', 'UNMENU', 'ADDKEY', 'EXIT'))
FUNCS = frozenset(('RUNFLIC', 'PLAYFLIC', 'WASALTPRESSED', 'CREDITSSTATE', 'GETOPTDATA'))
SHOW_DIR = os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'SHOW')
FLIC_INTERVAL = 2           # 60 Hz units per frame after STARTFLIC (30 fps)
CLOCK_PER_TICK = 2          # [8334] 60 Hz units per VM tick (the timeline parser's relation, 10c8:0172)
ALT = 0xc0                  # DEFINES.DEF _EITHER_ALT_PRESSED (10d8:3cc1 tests & 0xC0)
SAVE_SCAN = 0x1f            # the one key the normal handler still answers while the keyboard is captured (not with Alt, 1138:1da6 / 10a8:0541)


class FlicPlayer:
    """The open flic (fields +0x34 count, +0x102 index, +0x160 last, +0x164 interval, +0x170 running, +0x171 limit, +0x173 var, +0x17e mark)."""

    def __init__(self, name, flic):
        self.name, self.flic = name, flic
        self.count, self.interval, self.last = flic.frame_count, FLIC_INTERVAL, None
        self.index, self.limit, self.var, self.running, self.mark = 0, 0, None, True, None
        self.armed = False                        # nothing is drawn until the first RUNFLIC (ASSUMPTION: the brief's reading of 12)
        self.frames = flic.frames()               # decoded lazily, one frame at a time, in order
        self.frame = None                         # the frame on screen (the last one drawn), None = nothing drawn yet

    def draw(self):
        """Decode and show the next frame (1140:0603)."""
        self.frame = next(self.frames, self.frame)
        self.index += 1

    def rewind(self, index):
        """FLICLOOP: back to frame `index` (1140:0bc5 restores the frame index and file offset); the frames before it are decoded again."""
        self.frames, self.index = self.flic.frames(), 0
        for _ in range(index):
            self.draw()


class ShowMixin:
    flic = None                # the open FlicPlayer (DS:6538) or None
    show_clock = 0             # [8334]
    frozen = False             # [50be] as FREEZE sets it
    freeze_marks = ()          # the processes FREEZE suspended (the mark buffer DS:30b8)
    freeze_tick = 0
    frozen_since = None        # the VM tick the game clock stopped at (the outermost FREEZE), None while it runs
    frozen_ticks = 0           # VM ticks the game clock has been stopped for, in total
    key_hook = None            # the CAPTUREKEYBOARD block name (the hook process DS:6530), None = captured without a block
    key_hook_proc = None
    key_hook_owner = 'level'
    key_queue = ()             # ADDKEY events [(scan, mods)] not delivered yet
    _install_opt = None

    @staticmethod
    def _words_nums(args):
        flat = [a for v in args for a in (v if isinstance(v, list) else [v])]
        return [str(a) for a in flat if isinstance(a, str)], [a for a in flat if isinstance(a, int)]

    # ---- statements
    def cmd_show(self, name, args, proc):
        words, nums = self._words_nums(args)
        if name == 'STARTFLIC':
            self.start_flic(words[0] if words else '')
        elif name == 'STOPFLIC':
            self.flic = None                       # 1140:0ecc: the palette comes back (the world's), safe when nothing is open
        elif name == 'SETFLICRATE':
            if self.flic is not None:
                self.flic.interval = (nums[0] if nums else 0) & 0xffff       # u16, no re-base: the next frame is due at last + n
        elif name == 'FLICLOOP':
            if self.flic is not None:
                if (words[0] if words else '') == 'MARK':
                    self.flic.mark = self.flic.index
                elif self.flic.mark is not None:
                    self.flic.rewind(self.flic.mark)
        elif name == 'FREEZE':
            self.cmd_freeze(proc)
        elif name == 'THAW':
            self.cmd_thaw()
        elif name == 'ADDKEY':
            self.key_queue = (*self.key_queue, (nums[0] & 0xff if nums else 0, self._mods(nums[1:])))
        elif name == 'EXIT':
            self.exit_requested = True             # 10d0:2835: [6bda] = 1; the process is not killed
        # MENU / UNMENU (10d0:5396 / 539d) are stubs in the release exe

    @staticmethod
    def _mods(nums):
        """ADDKEY: (byte)(arg1 | arg2 | ... | arg6); the unspecified slots are 0."""
        out = 0
        for n in nums[:5]:
            out |= n & 0xff
        return out

    def start_flic(self, name):
        """`STARTFLIC <name>` (1140:0c6a): closes any open flic, opens SHOW/<NAME>.SHO (interval 2, index 0, no limit, no variable) and draws
        nothing: until the first RUNFLIC frame the screen shows black (ASSUMPTION: the display pages are cleared, 10e8:1d5e, to colour 0 of a black
        palette). A missing or unreadable file warns and leaves no flic (the open failure path of 11a8:083b is not traced: ASSUMPTION)."""
        self.flic = None
        path = os.path.join(SHOW_DIR, name.upper() + '.SHO')
        try:
            flic = flc_mod.load(path)
        except (OSError, ValueError):
            self.warn(f'STARTFLIC {name}: cannot open {path}')
            return
        self.flic = FlicPlayer(name.upper(), flic)

    # ---- RUNFLIC and the per-render step
    def cmd_runflic(self, proc, args):
        """`RUNFLIC <block> [limit] [livevar]` (10d8:3a40 -> 10c8:0636). limit: the exclusive end frame, 0 = none; livevar (args[3], the VM passes its
        name): var mode. It resets the flic's frame timer, starts the scene block as a process whose timeline origin is this tick and returns its
        handle (valid until the process ends: block end, or no flic / a finished flic). An unknown block: a handle that dies on its next update
        (INFERRED: the task has no code). Without an open flic the scene ends at its first update without running anything."""
        words, nums = self._words_nums(args)
        block = words[0].upper() if words else ''
        f = self.flic
        if f is not None:
            f.limit = (nums[0] & 0xffff) if nums else 0
            f.var = words[1].lower() if len(words) > 1 else None
            f.last, f.running, f.armed = None, True, True      # 0f6f -> 0c1f: +0x160 = 0, the flic ticks again
        if self.vm is None:
            return 0
        if block not in self.vm.blocks:
            return self.vm.timed_handle(1)
        p = self.vm.spawn(block, ctx=proc, run=False, owner=getattr(proc, 'owner', 'level'))
        p.scene = True
        if f is not None:
            self.vm.run(p)
        return p.handle

    def scene_alive(self):
        return self.flic is not None and self.flic.running

    def step_show(self):
        """Once per render: deliver ADDKEY events, advance the flic (1140:077b) and end the scenes of a flic that is gone."""
        self.drain_keys()
        f = self.flic
        if f is not None:
            self.show_clock += CLOCK_PER_TICK
            if f.running and f.armed:
                self.advance_flic(f)
        if self.vm is not None and not self.scene_alive():
            for p in [p for p in self.vm.procs.values() if p.scene]:
                self.vm.finish(p)                  # ASSUMPTION: the engine's "dies on its next update" (<= 1 tick) is modelled as 0 ticks

    def advance_flic(self, f):
        if f.var is None:
            if f.last is None:
                f.last = self.show_clock - f.interval
            if f.last + f.interval > self.show_clock:
                return
            if f.index >= f.count or (f.limit and f.index >= f.limit):
                f.running = False
                return
            f.draw()
            f.last += f.interval
        else:
            value = self.vm.globals.get(f.var, 0) if self.vm is not None else 0
            while f.index <= value and f.index < f.count and not (f.limit and f.index >= f.limit):
                f.draw()
            if f.limit and f.index >= f.limit:
                f.running = False

    def flic_rgb(self):
        """The flic frame as the pipeline's 200x320x3 RGB (6-bit DAC values expanded c * 255 // 63, as every palette); black before the first frame."""
        f = self.flic
        if f.frame is None:
            return np.zeros((200, 320, 3), np.uint8)
        pal = np.frombuffer(f.frame.palette, np.uint8).reshape(256, 3)
        pal = (pal.astype(np.int32) >> 2) * 255 // 63
        px = np.frombuffer(f.frame.pixels, np.uint8)
        out = np.zeros((200, 320, 3), np.uint8)
        h, w = min(200, f.flic.height), min(320, f.flic.width)
        out[:h, :w] = pal[px.reshape(f.flic.height, f.flic.width)[:h, :w]]
        return out

    # ---- FREEZE / THAW
    def cmd_freeze(self, proc):
        """10c8:04de: suspend every existing script process except the caller and the ones already suspended; ASSUMPTION: the native handles (sound,
        subtitle, Fade, missile: no script block) are the engine's type < 0x100 / 0x110 kernel tasks and keep running. Sets [50be], which stops
        World.step (figures, physics, camera selection) but not the VM tick, so processes made afterwards (RUNFLIC scenes, the key hook, FADE) run.
        A nested FREEZE replaces the mark buffer."""
        marks = []
        for p in self.vm.procs.values() if self.vm is not None else ():
            if p is proc or p.suspended or p.gen is not None or p.done:
                continue
            p.suspended = True
            marks.append(p)
        self.freeze_marks, self.frozen, self.freeze_tick = marks, True, self.vm.tick if self.vm is not None else 0
        if self.frozen_since is None:
            self.frozen_since = self.freeze_tick

    def cmd_thaw(self):
        """10c8:05b2: resume exactly the marked processes and clear [50be]. ASSUMPTION (INFERRED: WAIT and the timeline clocks run on the pausable
        game clock [8330]): a resumed process's pending wake and timeline origin move later by the frozen duration."""
        now = self.vm.tick if self.vm is not None else 0
        shift = now - self.freeze_tick
        for p in self.freeze_marks:
            if p.done or not p.suspended:
                continue
            p.suspended = False
            if p.wake > self.freeze_tick:                  # a pending timer; a process that was only waiting on another has none
                p.wake += shift
            if p.origin is not None:
                p.origin += shift
        self.freeze_marks, self.frozen = (), False
        if self.frozen_since is not None:
            self.frozen_ticks += now - self.frozen_since
            self.frozen_since = None

    @property
    def game_tick(self):
        """The game clock [8330] in VM ticks (2 clock units each): the scheduler's tick minus the ticks FREEZE has stopped it for ([50be] set,
        FREEZE 10c8:04de .. THAW 10c8:05b2; the options dialog stops the VM tick itself). Read by the journal / log award stamps and `%time%`
        (ADDLOGENTRY, monitor_time) and the attack-combo timer [2958]; the scheduler's tick and the flic / scene clock [8334] are not it."""
        now = self.vm.tick if self.vm is not None else 0
        return (now if self.frozen_since is None else self.frozen_since) - self.frozen_ticks

    # ---- keyboard: ADDKEY, the CAPTUREKEYBOARD hook and key_event
    def drain_keys(self):
        queue, self.key_queue = self.key_queue, ()
        for scan, mods in queue:
            self.key_event(scan, mods)

    def key_event(self, scan, mods=0):
        """One key press (a real one while the keyboard is captured, an ADDKEY one always). Captured (1138:1da6 from 10e8:11e3): the hook block runs at
        once with ~0 = scan code, ~1 = modifiers, ~2 = mouse (0), a scan code of 0 does nothing; the normal handler is bypassed except scan 0x1f
        without Alt (CANNOT_SAVE) and not with a flic open. Not captured: Esc answers an open dialog / monitor, any other key is a press and
        release through key_down."""
        if not scan:
            return
        if self.keyboard_captured:
            if scan not in self.keys_captured:
                self.keys_captured.append(scan)
            self.run_key_hook(scan, mods)
            if scan == SAVE_SCAN and not mods & ALT and self.flic is None:
                self.key_down(scan, mods)
                self.key_up(scan)
        elif scan == 1 and self.options is not None and not self.options.closed:
            self.option_key('ESCAPE')
        elif scan == 1 and self.monitor is not None:
            self.monitor_key('ESCAPE')
        else:
            self.key_down(scan, mods)
            self.key_up(scan)

    def run_key_hook(self, scan, mods):
        if self.vm is None or self.key_hook is None:
            return
        if self.key_hook_proc is not None and not self.key_hook_proc.done:
            self.vm.finish(self.key_hook_proc)     # the hook process is rewound to the block start
        ctx = types_ns(cur_fig=self.player_name, cur_item=None, owner=self.key_hook_owner)
        self.key_hook_proc = self.vm.spawn(self.key_hook, (scan, mods, 0), ctx)

    def cmd_capturekeyboard(self, proc, args):
        """`CAPTUREKEYBOARD <block>` (10d0:1823): already captured warns (error 0xd1) and changes nothing. The hook is the named 3-parameter
        block; ASSUMPTION: a block the VM does not have (or none) captures without a hook, and the parameter count is not checked (error 0xcf
        is not ported: the parser keeps no block signature)."""
        if self.keyboard_captured:
            self.warn('CAPTUREKEYBOARD: the keyboard is already captured (error 0xd1)')
            return
        words = self._words_nums(args)[0]
        self.keyboard_captured = True
        self.key_hook = words[0].upper() if words and self.vm is not None and words[0].upper() in self.vm.blocks else None
        self.key_hook_owner = getattr(proc, 'owner', 'level')

    def cmd_releasekeyboard(self):
        """`RELEASEKEYBOARD` (10d0:677d -> 1138:1e5f) destroys the hook process."""
        self.keyboard_captured, self.key_hook = False, None
        if self.key_hook_proc is not None and self.vm is not None:
            self.vm.finish(self.key_hook_proc)
        self.key_hook_proc = None

    # ---- functions
    def cmd_show_func(self, name, args, proc):
        words, nums = self._words_nums(args)
        if name == 'RUNFLIC':
            return self.cmd_runflic(proc, args)
        if name == 'WASALTPRESSED':
            return int(((nums[0] if nums else 0) & ALT) != 0)
        if name == 'GETOPTDATA':
            return self.install_option(words[0] if words else '')
        if name == 'CREDITSSTATE':
            return self.credits_state()
        return 0                                   # PLAYFLIC is a stub (returns 0, no flic action)

    def install_option(self, key):
        """FUN_10f0_0651: the INSTALL.OPT value of `key` (case-insensitive: INFERRED): a value starting with a digit gives its decimal integer,
        anything else the code of its first character (not upper-cased); a missing key gives 0. `language` is the setting in force (the
        player may change it; INSTALL.OPT only seeds it), so INTRO.SCP picks INTRO / INTROF / INTROG."""
        if key.lower() == 'language':
            return ord(self.settings.language)
        if self._install_opt is None:
            try:
                with open(settings_mod.INSTALL_OPT, 'rb') as f:
                    self._install_opt = settings_mod.parse_install_opt(f.read().decode('latin1'))
            except OSError:
                self._install_opt = {}
        token = re.split(r'[\s,]', self._install_opt.get(key.lower(), '').strip('"'))[0]
        if not token:
            return 0
        digits = re.match(r'\d+', token)
        return int(digits.group()) if token[0].isdigit() and digits else ord(token[0])


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)
