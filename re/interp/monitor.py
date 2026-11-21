"""Monitor (computer screen UI) engine: MONITORS/<NAME>.CAM elements driven by the MON_* script statements.

    mon = Monitor('MLBT'); mon.define_button('pwrb', 'POWER', 1)
    px, pal = mon.render()          # 64000 palette indices (320x200) + 768-byte RGB palette

Findings (segments 10d0 handlers, 1250/1258 DLGBOOK.C, 1260/1270 element classes):
  * Element screen position = (-hotx, -hoty) of its frames, relative to the 320x200 screen (the background is
    the entry named like the file, e.g. MLBT in MLBT.CAM).  Frame 0 of every element is a 1x1 dummy = invisible.
  * The 4th character of the entry name gives the class (FUN_1250_1ddc): B button, L text label, T text list /
    text area, S scale bar, V viewport, anything else (A, ...) an art image whose frame MON_SETFRAME selects.
  * Internal state = script value - 1 (0 invisible, 1 normal, 2 highlight, 3 selected, 4 selected+highlight,
    5 not selectable; the default 0 -> 1).  A button draws frame min(state, nframes - 1).
  * A button's text is drawn in the label with the same first 3 letters + 'L' (FUN_1250_1f81).  A label's first
    pixels hold its style (FUN_1260_0891): px[0..4] = text colours for states 1..5 (state 0 reuses px[0]) and
    px[5] = font number (DATA/<n>.FNT); text is centred in the label rectangle (FUN_1260_0a0a).
  * Text args are "ENGLISH/FFRENCH/GGERMAN" (FUN_1120_03d2); "/!" prefixes text that is shown as is.
  * MON_DEFINELIST / MON_DEFINETEXTAREA name entries of MONITORS/TEXT.FLX ("[KEY] text" records).
Everything else (frame choice for not-selectable, toggle behaviour, scale clipping, viewport content) is an
ASSUMPTION, marked below.
"""
import os
import re
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'formats'))
from flex import read_flex  # noqa: E402
import cam as cammod  # noqa: E402
from fnt import Font  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
MONITORS = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'MONITORS')
DATA = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'DATA')
REPEAT_DELAY = 10             # ASSUMPTION: ticks before a held button repeats (_REPEAT_DELAY option not found)
ENTRY_UP, ENTRY_DOWN, LINE_UP, LINE_DOWN, PAGE_UP, PAGE_DOWN = 45, 43, 200, 208, 201, 209   # DEFINES.DEF

INVISIBLE, NORMAL, HIGHLIGHT, SELECTED, SEL_HIGH, NOT_SELECTABLE = range(6)     # internal states
_FONTS = {}
_TEXTS = {}
_POINTERS = {}


def font(n):
    # ASSUMPTION: style bytes 0x80+ (129..131 on some labels, e.g. CMAL = 0x82) render in font 0 like the native shot; the low
    # bits may be an alignment flag (unrecovered, FUN_1260_0891 not read).  A few labels carry no style (e.g. 236) -> font 0.
    if n >= 0x80 or not os.path.exists(os.path.join(DATA, f'{n}.FNT')):
        n = 0
    if n not in _FONTS:
        _FONTS[n] = Font(os.path.join(DATA, f'{n}.FNT'))
    return _FONTS[n]


def localize(s, lang='E'):
    """FUN_1120_03d2: pick the "/<lang>" segment (else "/E", else the whole string), drop a leading "/x" marker,
    stop at the next '/'."""
    for tag in ('/' + lang, '/E'):
        i = s.find(tag)
        if i >= 0:
            s = s[i:]
            break
    if s.startswith('/'):
        s = s[2:]
    j = s.find('/')
    return s if j < 0 else s[:j]


def text_entry(name, lang='E'):
    """Raw text of MONITORS/TEXT.FLX (G: GTEXT.FLX, F: FTEXT.FLX; the OPT/<L>.OPT `text=`) entry `name` (case-insensitive) or None."""
    if lang not in _TEXTS:
        d, ents = read_flex(os.path.join(MONITORS, ('' if lang == 'E' else lang) + 'TEXT.FLX'))
        _TEXTS[lang] = {n.upper(): d[o:o + s].decode('latin1') for _, o, s, n in ents}
    return _TEXTS[lang].get(str(name).upper())


# The pointer object (FUN_1270_0000) reads these globals when it is made; VARS.DEF sets them and no script changes them. A pointer
# frame sits at its CAM hotspot in a 320x200 canvas (the hand at about 109,11), and the canvas point (_PTR_X_HOT, _PTR_Y_HOT), the
# fingertip, is the pointer position. The margins clamp the position: "hand ptrs do not reach to top of screen".
PTR_HOT = (122, 13)                    # _PTR_X_HOT, _PTR_Y_HOT
PTR_MARGINS = (0, 319, 14, 199)        # _ptr_left_margin, _ptr_right_margin, _ptr_top_margin, _ptr_bottom_margin (FUN_1270_0151)
# The press animation (FUN_1270_01ae / 01ec / 0263 / 02c9 / 02ef) times its phases on the 60 Hz clock [8334]. This port has no
# never-paused 60 Hz count (show_clock only runs while a flic plays and the options dialog stops the world), so the pointer keeps its
# own, advanced by update() once per tick (the world calls it before its pause check): INFERRED equal to [8334] for the pointer's use.
PTR_CLOCK_PER_TICK = 2                 # 60 Hz units per VM tick
PTR_GLIDE_DT = 4                       # FUN_1270_0891: max(1, [83a4] >> 7), [83a4] the 8.8 frame time (512 at 30 fps)
# The key handler FUN_1250_0cf9 (jump table 1250:112e): each extended key (PC scan | 0x80) tries up to three directions of the
# focus search FUN_1250_0638 (0 up, 1 down, 2 right, 3 left, 4 up-right, 5 down-right, 6 down-left, 7 up-left, 8 nearest in either
# axis), takes the first that moves the focus, and else steps to the previous (1250:05bf) or next (1250:0544) button.
KEY_TRIES = {0xc7: ((7, 3, 0), 'prev'), 0xc8: ((0, 7, 4), 'prev'), 0xc9: ((4, 2, 0), 'next'), 0xcb: ((3, 6, 7), 'prev'),
             0xcc: ((8,), 'prev'), 0xcd: ((2, 5, 4), 'next'), 0xcf: ((6, 3, 1), 'prev'), 0xd0: ((1, 6, 5), 'next'),
             0xd1: ((5, 2, 1), 'next')}
KEY_TAB, KEY_BACKTAB, KEY_RETURN, KEY_ESCAPE, KEY_SPACE = 0x09, 0x8f, 0x0d, 0x1b, 0x20
SCAN_RETURN, SCAN_ESCAPE = 0x1c, 0x01                                # the +0x11e values: Return and Space hold 0x1c, Escape 1
_ASCII = {**dict(zip(range(0x10, 0x1a), 'qwertyuiop')), **dict(zip(range(0x1e, 0x27), 'asdfghjkl')), **dict(zip(range(0x2c, 0x33), 'zxcvbnm')),
          **dict(zip(range(0x02, 0x0c), '1234567890'))}


def key_code(scan, shift=False):
    """The event's key byte for a PC scan code (FUN_1250_0cf9): the ASCII byte when the key has one, else the scan code | 0x80; Shift+Tab 0x8f.
    None for keys the monitor ignores. (The keypad shares the extended codes, as the original told them apart only by NumLock.)"""
    if scan == 0x0f:
        return KEY_BACKTAB if shift else KEY_TAB
    if scan in (0x1c, 0x01, 0x39):
        return {0x1c: KEY_RETURN, 0x01: KEY_ESCAPE, 0x39: KEY_SPACE}[scan]
    if scan in _ASCII:
        return ord(_ASCII[scan])
    code = scan | 0x80
    return code if code in KEY_TRIES else None


PTR_IDLE, PTR_PRESSING, PTR_HOLDING, PTR_RELEASING = 0, 1, 2, -1      # the state byte at +0x30


# FUN_1270_174b: the 32x32 table of the translucent draw (FUN_1270_185b). Element offset o in its 32-entry ramp over grey ramp offset u:
# o + ((31 - o) * (u * 100 / 31) + 50) / 100, capped at 31 (integer division throughout). Checked against a VGA dump of the original's
# reload dialog (DOSBox-X, 2026-11-11): fill 41 over grey 145 -> 53.
TRANSLUCENT = tuple(tuple(min(31, o + ((31 - o) * (u * 100 // 31) + 50) // 100) for u in range(32)) for o in range(32))


def dark_grey(rgb):
    """The screen behind the options dialog: each pixel's 6-bit max(r, g, b) on the dark grey range 128..145, 128 + max * 18 / 64
    (FUN_1108_0d83 brightness, FUN_1108_0cfc range table, applied by FUN_1138_1d0a; the range length 18 is measured from the VGA dump,
    where it matches every pixel the dialog leaves transparent). `rgb`: 8-bit c * 255 / 63, so the 6-bit value is ceil(v * 63 / 255)."""
    six = (np.asarray(rgb, np.int32).max(axis=-1) * 63 + 254) // 255
    return (128 + six * 18 // 64).astype(np.uint8)


def pointer_frames(name=None):
    """Frames of a monitor pointer CAM.  A selected pointer is its own CAM file;
    the generic pointer comes from POINTER.CAM.  Indices render through the active
    monitor palette; any original palette remapping remains unconfirmed."""
    stem = str(name or 'POINTER').upper()
    if stem.endswith('.CAM'):
        stem = stem[:-4]
    if stem not in _POINTERS:
        path = os.path.join(MONITORS, stem + '.CAM')
        if not os.path.exists(path):
            _POINTERS[stem] = ()
        else:
            d, ents = read_flex(path)
            entry = next((x for x in ents[1:] if x[2]), None)
            _POINTERS[stem] = tuple(cammod.frames(d[entry[1]:entry[1] + entry[2]])) if entry else ()
    return _POINTERS[stem]


def parse_entries(raw):
    """"[KEY] text" records -> [(KEY, text)]; text before the first '[' is ignored, '[]' = anonymous (key '')."""
    out = []
    for m in re.finditer(r'\[([^\]\n]*)\][ \t]?(.*?)(?=\n\[|\Z)', raw, re.S):
        out.append((m.group(1).strip().upper(), m.group(2).strip('\n')))
    return out


def format_game_time(vm_tick, start_tick=0, start_date=0):
    """Format the original monitor ``%time%`` field as ``day-HHMM``.

    INFERRED: the Python VM advances at 30 Hz while the executable clock at
    ``DAT_1290_8330`` advances at 60 Hz, so each VM tick contributes two
    engine ticks.  ``StartTick`` is therefore in 60-Hz ticks.
    """
    minutes = (int(start_tick) + 2 * int(vm_tick)) // (60 * 60)
    hours, minute = divmod(minutes, 60)
    day, hour = divmod(hours, 24)
    return f'{int(start_date) + day}-{hour:02d}{minute:02d}'


def substitute(text, resolve=None, time_value=None):
    """Expand monitor ``%variable%`` fields without changing their stored source text.

    ``%%`` is a literal percent.  ``time_value`` supplies the original clock's
    ``%time%`` field.  A missing resolver deliberately leaves other fields
    literal, which keeps standalone monitor inspection useful.
    """
    out, i = [], 0
    while i < len(text):
        if text[i] != '%':
            out.append(text[i])
            i += 1
            continue
        if i + 1 < len(text) and text[i + 1] == '%':
            out.append('%')
            i += 2
            continue
        end = text.find('%', i + 1)
        if end < 0:
            out.append(text[i:])
            break
        name = text[i + 1:end]
        value = time_value if name.lower() == 'time' else (None if resolve is None else resolve(name))
        out.append(text[i:end + 1] if value is None else str(value))
        i = end + 1
    return ''.join(out)


class Element:
    def __init__(self, name, frames):
        self.name, self.frames = name.upper(), frames
        self.kind = self.name[3:4]
        self.active, self.state, self.frame, self.mode = False, NORMAL, 0, 0
        self.gauge = False
        self.shortcut = ''                       # +0x42: the letter key that clicks a button. FUN_1278_0894 (button vtable slot 0x20) stores tolower(text[0]), but no
                                                 # script statement reaches it with text (MON_DEFINEBUTTON 10d0:540a -> 1258:08b4 -> 1270:0ffa sets a label), so it stays ''
        self.text, self.scale = '', {}
        self.entries, self.entry_times, self.sel, self.top, self.source, self.selectable = [], [], 0, 0, [], False   # lists
        self.items = []                          # item names parallel to entries (inventory lists)
        real = [f for f in frames[1:] if f[0] > 1]
        self.x = -real[0][2] if real else 0
        self.y = -real[0][3] if real else 0
        self.w, self.h = (max(f[0] for f in real), max(f[1] for f in real)) if real else (0, 0)
        self.header = None                       # (5 text colours, font number) from the first frame's first pixels
        if self.kind in 'LT' and real and len(real[0][4]) > 6:
            px = real[0][4]
            self.header = (list(px[:5]), px[5])

    def colour(self, state):
        c = self.header[0]
        return c[max(min(state, 5), 1) - 1]

    def hit(self, x, y):
        return any(f[0] > 1 and -f[2] <= x < -f[2] + f[0] and -f[3] <= y < -f[3] + f[1] for f in self.frames[1:])


def grey_ramp(pal):
    """Palette indices of the monitor's grey ramp: the last run of >= 16 consecutive grey (r == g == b) entries, cut to its
    last 32 (CELL.CAM: 128..159, black to white).  ASSUMPTION: found generically since the original's table is unrecovered."""
    grey = [pal[3 * i] == pal[3 * i + 1] == pal[3 * i + 2] for i in range(256)] + [False]
    best, start = [], None
    for i, g in enumerate(grey):
        if g and start is None:
            start = i
        elif not g and start is not None:
            if i - start >= 16:
                best = list(range(start, i))
            start = None
    return best[-32:]


class Monitor:
    def __init__(self, name, resolve_var=None, format_time=None, viewport_frame=None, language='E'):
        self.name = name.upper()
        self.language = language
        path = os.path.join(MONITORS, self.name + '.CAM')
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        d, ents = read_flex(path)
        self.pal = cammod.palette(d[ents[0][1]:ents[0][1] + ents[0][2]])
        self.translucent = ()                     # element kinds drawn by FUN_1270_185b (the options dialog: 'X')
        self.elements, self.order, self.background = {}, [], None
        for _, off, size, nm in ents[1:]:
            if not size:
                continue
            fr = list(cammod.frames(d[off:off + size]))
            if nm.upper() == self.name and self.background is None:
                self.background = fr[0]   # the first entry named like the file; CELL.CAM also has a later CELL label
            else:
                self.elements[nm.upper()] = Element(nm, fr)
                self.order.append(nm.upper())
        self.viewport = None                       # (element name, camera name)
        # frame +10, state +0x30, start time +0x43, interval +0x3f, releasePending +0x49, clock = the pointer's own 60 Hz count
        self.pointer = {'name': None, 'frame': 1, 'pos': (160, 100), 'state': PTR_IDLE, 'start': 0, 'interval': 0,
                        'release_pending': False, 'clock': 0}
        self.ptr_press_time = (14, 5, 14)         # SET_PTR_PRESS_TIME: press / hold / release in 60 Hz ticks (VARS.DEF _PTR_*_TIME)
        self.press_action, self.release_action = self._press_button, self._release_button      # FUN_1250_12f6 / 13f1; the options dialog replaces them
        self.ptr_movement = (0x140, 2)            # SET_PTR_MOVEMENT: P+0x73 (dead data) and P+0x5f (rewritten to 2 at each glide start); stored only
        # +0x120, set by FUN_1250_0415 (MON_ENABLEINPUT; the pointer clears it when a press starts and sets it on the release): while it
        # is 0 the monitor's event handler (FUN_1250_0cf9) drops mouse moves, mouse downs and keys; only the mouse up (FUN_1250_0c4c) gets through
        # The glide (FUN_1270_0536 start, 064f step; +0x63..+0x61): None, or start / target / delta / rounding / dist / half / t / s / accel / phase
        self.glide = None
        self.gliding = False                      # DAT_9fea: set by the update while the pointer is off its target, cleared by the next one after arrival
        self.keys_down = set()                    # PC scan codes the keyboard holds (DAT_1290_7bbe)
        self.held = 0                             # +0x11e: the key whose release ends a press (SCAN_RETURN for Return and Space, SCAN_ESCAPE)
        self.buttons_fn = None                    # the options dialog lists its X controls as the focusable buttons
        self.hover_fn = None                      # ... and tracks the control under the pointer itself
        self.focus = None                         # +0x112: the focused button (Tab moves it at once, the pointer's crossing buttons too)
        self.mouse_moved = False                  # [9dca] & 2: set by a mouse move (FUN_1250_1a21), cleared by a key's glide (15ef); the dialog's defaults
        self.shortcut = None                      # +0x122: the button a letter shortcut is gliding to; the arrival clicks it (FUN_1250_1acf)
        self.codes, self.input_enabled, self.tabs = [], True, ()
        self.mouse_warp = None                    # set_input(True): INT 33h AX=4 puts the DOS mouse on the pointer (FUN_11d8_0e91); the host may follow
        self.hl_a = self.hl_b = self.pressed = self.released = ''     # 9da2 / 9db6 / 9d7a / 9d8e
        self.repeat = 0                                               # 4e2e
        self.hovered = None
        self.captured = None
        self.click_button_pending = False
        self.warnings = []
        self.resolve_var, self.format_time = resolve_var, format_time
        # A world-owned callback that returns the full 320x200 RGB view of a camera (background + figures/objects).
        self.viewport_frame = viewport_frame
        self.grey_ramp = grey_ramp(self.pal)

    # ---- helpers
    def el(self, name):
        e = self.elements.get(str(name).upper())
        if e is None:
            self.warnings.append(f'{self.name}: no element {name!r}')
        return e

    def label_for(self, btn):
        return self.elements.get(btn.name[:3] + 'L')

    # ---- statements
    def hide_all(self):
        """MON_HIDEALL (FUN_1258_0000): every element is hidden and unselectable until redefined."""
        for e in self.elements.values():
            e.active, e.frame, e.text, e.scale, e.entries, e.entry_times = False, 0, '', {}, [], []
            e.state = NORMAL
        self.viewport = None
        self.hovered = None

    def define_button(self, name, text=None, state=NORMAL, mode=0):
        e = self.el(name)
        if e is None:
            return
        e.active, e.state, e.mode = True, state, mode
        lab = self.label_for(e)
        if text:                                   # empty text = null = unchanged (ASSUMPTION)
            e.text = text
        if lab is not None:
            lab.active, lab.state, lab.text = state != INVISIBLE, state, e.text

    def define_text(self, name, text, state=NORMAL):
        e = self.el(name)
        if e is None:
            return
        e.active, e.state, e.text = True, state, text

    def define_list(self, name, source, entry_keys=(), entry_times=()):
        e = self.el(name)
        if e is None:
            return
        raw = text_entry(source, self.language)
        if raw is None:
            self.warnings.append(f'{self.name}: no TEXT.FLX entry {source!r}')
            raw = ''
        e.active, e.source, e.entries, e.sel, e.top = True, parse_entries(raw), [], 0, 0
        self.set_list_entries(name, entry_keys, entry_times)

    def set_list_entries(self, name, entry_keys, entry_times=()):
        """Fill a text list: the record's unkeyed ``[]`` entries in authored order, then the persistent log keys in award order.

        The list's first update (FUN_1268_04a8) rewinds its TEXT.FLX record and adds every ``[]`` entry (FUN_1268_10c5: a '['
        followed by ']'; keyed records are skipped), then the ADDLOGENTRY store's keys (FUN_1268_1213). So Caynan's, Dane's and
        Escher's logs and the CHAOS cell and freezer lists, all ``[]``, show without any ADDENTRY.
        ``*KEY`` is the maintenance log notation for every TEXT.FLX record
        keyed ``KEY``.  It keeps those records in their authored order.
        """
        e = self.el(name)
        if e is None:
            return
        entries = [entry for entry in e.source if entry[0] == '']
        times = [None] * len(entries)
        for i, key in enumerate(entry_keys):
            key = str(key).upper()
            stamp = entry_times[i] if i < len(entry_times) else None
            match = key[1:] if key.startswith('*') else key
            found = [entry for entry in e.source if entry[0] == match]
            if key.startswith('*'):
                entries.extend(found)
                times.extend([stamp] * len(found))
            elif found:
                entries.append(found[0])
                times.append(stamp)
            else:
                self.warnings.append(f'{self.name}: {name} has no entry {key!r}')
        e.entries, e.entry_times, e.sel, e.top = entries, times, 0, 0

    def define_textarea(self, name, source, tabs=()):
        e = self.el(name)
        if e is None:
            return
        raw = text_entry(source, self.language)
        if raw is None:
            self.warnings.append(f'{self.name}: no TEXT.FLX entry {source!r}')
            raw = ''
        e.active, e.entries, e.entry_times, e.sel, e.top, self.tabs = True, [('', re.sub(r'(?m)^\[[^\]]*\] ?', '', raw).strip('\n'))], [], 0, 0, tuple(tabs)
        e.source = []

    def set_frame(self, name, n):
        e = self.el(name)
        if e is not None:
            e.active, e.frame = True, int(n)

    def set_gauge(self, name, n):
        """Class Q (1270:09db): the draw 1270:0a64 blits frames 1..n together, a backdrop and then the bars."""
        e = self.el(name)
        if e is not None:
            e.active, e.frame, e.gauge = True, int(n), True

    def set_scale(self, name, pct, idx):
        e = self.el(name)
        if e is not None:
            e.active = True
            e.scale[int(idx)] = max(0, min(100, int(pct)))

    def define_viewport(self, name, camera):
        e = self.el(name)
        if e is not None:
            e.active = True
            self.viewport = (e.name, str(camera).upper())

    def add_entry(self, name, key, fire=False):
        e = self.el(name)
        if e is None:
            return
        k = str(key).upper()
        ent = next((x for x in e.source if x[0] == k), None)
        if ent is None:
            self.warnings.append(f'{self.name}: {name} has no entry {key!r}')
            return
        e.entries.append(ent)
        e.entry_times.append(None)
        if fire and len(e.entries) == 1 and k:
            self.hl_b = k

    def remove_entry(self, name, key):
        e = self.el(name)
        if e is None:
            return
        k = str(key).upper()
        if k.startswith('*'):                      # "*" = all, "*+KEY" = replace all with KEY (no highlight event)
            e.entries, e.entry_times, e.sel, e.top = [], [], 0, 0
            if k.startswith('*+'):
                self.add_entry(name, k[2:])
        else:
            kept = [(entry, stamp) for entry, stamp in zip(e.entries, e.entry_times) if entry[0] != k]
            e.entries, e.entry_times = [entry for entry, _ in kept], [stamp for _, stamp in kept]
            e.sel = min(e.sel, max(len(e.entries) - 1, 0))

    def make_inventory(self, name, items):
        """MON_MAKEINVENTORY: fill list `name` with the entries of the player's inventory `items` [(name, type[, store key])]; several rows of one name are fine.
        ASSUMPTION: an item is listed under its own name if the list text has that key, else under its type
        (MY_BATTERY -> MONBAT); items with neither are not listed."""
        e = self.el(name)
        if e is None:
            return
        e.entries, e.entry_times, e.items, e.sel, e.top, e.selectable = [], [], [], 0, 0, True
        keys = {k for k, _ in e.source}
        for iname, itype, *ikey in items:
            key = iname.upper() if iname.upper() in keys else itype.upper() if itype.upper() in keys else None
            if key:
                self.add_entry(name, key)
                e.items.append(ikey[0] if ikey else iname)
        if e.entries and e.entries[0][0]:
            self.hl_b = e.entries[0][0]            # ASSUMPTION: the first entry starts highlighted

    def scroll_list(self, name, code):
        e = self.el(name)
        if e is None or not e.entries:
            return
        if code in (ENTRY_UP, ENTRY_DOWN):
            n = max(0, min(len(e.entries) - 1, e.sel + (1 if code == ENTRY_DOWN else -1)))
            if n != e.sel:
                e.sel = n
                if e.entries[n][0]:
                    self.hl_b = e.entries[n][0]
        elif code in (LINE_UP, LINE_DOWN, PAGE_UP, PAGE_DOWN):
            step = 1 if code in (LINE_UP, LINE_DOWN) else max(e.h // max(font(e.header[1]).height, 1) - 1, 1)
            e.top = max(0, e.top + (step if code in (LINE_DOWN, PAGE_DOWN) else -step))

    def list_index(self, name):
        e = self.elements.get(str(name).upper())
        return e.sel if e is not None else 0

    def list_key(self, name):
        e = self.elements.get(str(name).upper())
        return e.entries[e.sel][0] if e is not None and e.entries else None

    # ---- input (test hooks / UI)
    def _button(self, name):
        e = self.elements.get(str(name).upper())
        return e if e is not None and e.kind == 'B' and e.active and e.state != NOT_SELECTABLE else None

    def button_at(self, x, y):
        """The topmost selectable button at authored monitor coordinates, if any."""
        for name in reversed(self.order):
            e = self._button(name)
            if e is not None and e.hit(x, y):
                return e
        return None

    def set_pointer_pos(self, x, y):
        """FUN_1270_0463: the position changes only while the pointer is idle (state 0), clamped to the margins (FUN_1270_0151).
        -> True if it moved. A mouse move also ends a glide (FUN_1270_08ef: target := position)."""
        self.glide = None
        if self.pointer['state'] != PTR_IDLE:
            return False
        left, right, top, bottom = PTR_MARGINS
        self.pointer['pos'] = (max(left, min(right, int(x))), max(top, min(bottom, int(y))))
        return True

    def set_input(self, on):
        """FUN_1250_0415 (MON_ENABLEINPUT): store +0x120; turning input on with a mouse present moves the mouse to the pointer."""
        self.input_enabled = bool(on)
        if self.input_enabled:
            self.mouse_warp = tuple(self.pointer['pos'])

    def pointer_move(self, x, y):
        """Move the monitor pointer and update the button under it (dropped while input is off: "PROHIBIT PTR MOVEMENT OF PTR BY
        DISABLING MONITOR INPUT", CHAOSMON.scr)."""
        self._poll_held()
        if not self.input_enabled:
            return False
        if not self.set_pointer_pos(x, y):
            return self.hovered is not None
        return self._hover_under_pointer()

    def _hover_under_pointer(self):
        """FUN_1250_19bc: highlight the button under the pointer (the focus follows it, `_HIGHLIGHT` fires once per crossing)."""
        if self.hover_fn is not None:
            return self.hover_fn()
        x, y = self.pointer['pos']
        e = self.button_at(x, y)
        if e is self.hovered:
            return e is not None
        self.unhover()
        return self.hover(e.name) if e is not None else False

    def place_pointer(self, x, y):
        """MON_SETPTRPOS (FUN_1258_03f2 -> FUN_1270_08ef): the pointer jumps and any glide ends. Not clamped, as before."""
        self.glide = None
        self.pointer['pos'] = (x, y)

    # ---- the pointer's glide (FUN_1270_0536 start, 064f step, 0891 update)
    def glide_to(self, x, y):
        """FUN_1270_0536: clamp the target to the margins, then the distance is |dx| or |dy| on an axis and else ceil(sqrt(|dx|*|dy|)) from
        a 16-bit signed product (a product that wraps to <= 0 gives 0: the first step snaps to the target)."""
        left, right, top, bottom = PTR_MARGINS
        tx, ty = max(left, min(right, int(x))), max(top, min(bottom, int(y)))
        sx, sy = self.pointer['pos']
        dx, dy = tx - sx, ty - sy
        if dx == 0:
            dist = abs(dy)
        elif dy == 0:
            dist = abs(dx)
        else:
            prod = (abs(dx) * abs(dy)) & 0xffff
            prod = prod - 0x10000 if prod > 0x7fff else prod
            dist, odd = 0, -1
            while prod > 0:
                dist, prod, odd = dist + 1, prod + odd, odd - 2
        self.glide = {'start': (sx, sy), 'target': (tx, ty), 'd': (dx, dy), 'round': (-50 if dx < 0 else 50, -50 if dy < 0 else 50),
                      'dist': dist, 'half': dist // 2, 't': 0, 's': 0, 'a': 2, 'p': 2}

    def _glide_step(self, dt):
        """FUN_1270_064f: accelerate by a up to half the distance, coast one step, decelerate; the position is the percentage of the way."""
        g = self.glide
        if g['p'] == 0:
            g['p'] = -g['a']
        elif g['p'] > 0 and g['half'] <= g['t']:
            g['p'] = 0
        g['s'] += g['p'] * dt
        t = g['t'] + ((g['s'] * dt + 30) & 0xffffffff) // 60          # an unsigned long division into a 16-bit int
        g['t'] = ((t + 0x8000) & 0xffff) - 0x8000
        if g['t'] < g['dist'] and (g['s'] > 0 or g['p'] >= 0):
            pct = g['t'] * 100 // g['dist']
            pos = []
            for d, r, st in zip(g['d'], g['round'], g['start']):
                n = d * pct + r
                pos.append((n // 100 if n >= 0 else -(-n // 100)) + st)      # C division truncates
            self.pointer['pos'] = tuple(pos)
        else:
            self.pointer['pos'] = g['target']
        self._arrived()

    def _arrived(self):
        """FUN_1250_1acf after each step: the button under the pointer is highlighted, and a letter shortcut's button is clicked once the
        pointer sits on its centre (FUN_1250_1a92: mouse down and up, the shortcut cleared)."""
        self._hover_under_pointer()
        e = self.shortcut
        if e is not None and self.focus is e and self.pointer['pos'] == (e.x + e.w // 2, e.y + e.h // 2):
            self.shortcut = None
            self._ptr_down()
            self.mouse_up()

    # ---- the pointer's press animation (FUN_1270_01ec mouse down, 0263 mouse up, 02ef per-tick update)
    def _ptr_count(self):
        """+0x2e: the number of frames of the pointer CAM entry minus 1 (HAND: 3)."""
        return len(pointer_frames(self.pointer['name'])) - 1

    def _ptr_phase(self, time):
        """FUN_1270_01ae: restart the phase clock; the interval is (time + (count + 1) / 2) / (count + 1) 60 Hz units."""
        p, n = self.pointer, self._ptr_count() + 1
        p['start'], p['interval'] = p['clock'], (time + n // 2) // n

    def mouse_down(self):
        """The pointer's button went down. Frame 1 starts the press animation (the button is pressed when it reaches the last frame,
        update); a press while it runs is dropped (the original sets +0x47 and never reads it); with the last frame held the
        button is pressed at once. -> True if a selectable button is under the pointer and the press was taken."""
        p = self.pointer
        self._poll_held()
        if not self.input_enabled:                     # FUN_1250_0cf9 drops the event
            return False
        return self._ptr_down()

    def _ptr_down(self):
        """FUN_1270_01ec: the press animation starts (the shortcut's click calls it without the event handler's input check)."""
        p = self.pointer
        if self._ptr_count() < 1:                      # ASSUMPTION: a pointer without animation frames presses at once
            return self.press_action()
        if p['frame'] <= 0 or p['state'] != PTR_IDLE:
            return False
        if p['frame'] == self._ptr_count():
            return self.press_action()                 # FUN_1250_185d: only when a button is under the pointer
        p['frame'], p['state'] = 1, PTR_PRESSING
        self._ptr_phase(self.ptr_press_time[0])
        self.set_input(False)                          # FUN_1250_0415(...,0): input stays off until the release
        return self.button_at(*p['pos']) is not None

    def settle_pointer(self):
        """Test driver (not the original): the animation has run its course and the hand is idle on its last frame, as a held mouse
        leaves it; the next mouse down presses at once and the next mouse up releases at once."""
        p = self.pointer
        p['state'], p['release_pending'] = PTR_IDLE, False
        if self._ptr_count() >= 1:
            p['frame'] = self._ptr_count()

    def mouse_up(self):
        """The pointer's button went up: the release runs at once when idle, else when the press animation has ended (update)."""
        p = self.pointer
        self._poll_held()
        if self._ptr_count() < 1:
            self.release_action()
        elif p['frame'] > 0:
            if p['state'] == PTR_IDLE:
                self._ptr_release()
            else:
                p['release_pending'] = True

    def _ptr_release(self):
        p = self.pointer
        self.set_input(True)                           # FUN_1250_0415(...,1), before the release action
        self.release_action()
        p['release_pending'], p['state'] = False, PTR_RELEASING
        self._ptr_phase(self.ptr_press_time[2])

    def update(self):
        """FUN_1270_02ef, once per tick: the press / hold / release phases and the frame step. The blocks fall through within one call."""
        p = self.pointer
        p['clock'] += PTR_CLOCK_PER_TICK
        g = self.glide                                 # FUN_1270_0891: step while off the target; DAT_9fea says so until the next update
        if g is None or p['pos'] == g['target']:
            self.gliding = False
        else:
            self._glide_step(PTR_GLIDE_DT)
            self.gliding = True
        now, count, step = p['clock'], self._ptr_count(), 0
        if p['state'] == PTR_PRESSING:
            if p['frame'] == count:
                if not self.gliding:                   # FUN_1270_02ef: the press is skipped while the pointer glides (DAT_9fea); hold and release still run
                    self.press_action()
                p['state'] = PTR_HOLDING
                self._ptr_phase(self.ptr_press_time[1])
            elif now - p['start'] >= p['interval']:
                p['start'], step = now, 1
        if p['state'] == PTR_HOLDING:
            if now - p['start'] >= p['interval']:
                p['state'] = PTR_IDLE
                if p['release_pending']:
                    self._ptr_release()
                    step = -1
        if p['state'] == PTR_RELEASING:
            if p['frame'] == 1:
                step, p['state'] = 0, PTR_IDLE
            elif now - p['start'] >= p['interval']:
                p['start'], step = now, -1
        p['frame'] += step

    def _press_button(self):
        """Capture and press the button below the pointer, if any (FUN_1250_12f6; input is off by then, and 12f6 does not check it)."""
        e = self.button_at(*self.pointer['pos'])
        if e is None:
            return False
        if self.press(e.name):
            self.captured = e.name
            return True
        return False

    def _release_button(self):
        """Release the button captured by the matching press (FUN_1250_13f1)."""
        name, self.captured = self.captured, None
        ok = bool(name and self.release(name))
        if ok and self.pressed and not self.repeat:
            self.click_button_pending = True
        return ok

    def _sync_label(self, e):
        lab = self.label_for(e)
        if lab is not None and lab.active:
            lab.state = e.state

    def hover(self, name):
        e = self._button(name)
        if e is None:
            return False
        self.unhover()
        if e.state in (NORMAL, SELECTED):
            e.state += 1                               # highlight / selected+highlight
        self.hovered = self.focus = e
        self.hl_a = e.name
        self._sync_label(e)
        return True

    def unhover(self):
        e, self.hovered = self.hovered, None
        if e is not None and e.state in (HIGHLIGHT, SEL_HIGH):
            e.state -= 1
            self._sync_label(e)

    def press(self, name):
        e = self._button(name)
        if e is None:
            return False
        if e.state in (HIGHLIGHT, SEL_HIGH) or self.hovered is e:
            self.hovered = None
        # ASSUMPTION: pressing shows the selected frame; a toggle button flips selected <-> normal
        e.state = NORMAL if (e.mode and e.state in (SELECTED, SEL_HIGH)) else SELECTED
        self._sync_label(e)
        self.pressed, self.repeat = e.name, 0
        return True

    def release(self, name):
        e = self._button(name)
        if e is None:
            return False
        if not e.mode and e.state in (SELECTED, SEL_HIGH):
            e.state = NORMAL
            self._sync_label(e)
        self.released = e.name
        return True

    def key(self, name):
        """A key press that scripts map to <name>_BUTTON (ESCAPE -> ESCAPE_BUTTON); dropped while input is off (FUN_1250_0cf9)."""
        if not self.input_enabled:
            return
        self.pressed, self.repeat = str(name).upper(), 0

    # ---- keys (FUN_1250_0cf9 and the focus helpers 0449, 0544, 05bf, 0638, 15ef, 1166)
    def _focusables(self):
        if self.buttons_fn is not None:
            return self.buttons_fn()
        return [self.elements[name] for name in self.order if self._button(name) is not None]

    def _focus_buttons(self):
        """FUN_1250_0449: the selectable buttons. The focus (+0x112) starts on the first button of the monitor and moves to the first selectable
        one when it is not selectable itself. [] when there is none."""
        buttons = self._focusables()
        if buttons and self.focus not in buttons:
            first = None
            if self.focus is None and self.buttons_fn is None:
                first = next((self.elements[n] for n in self.order if self.elements[n].kind == 'B'), None)
            self.focus = first if first in buttons else buttons[0]
        return buttons

    @staticmethod
    def _centre(e):
        return e.x + e.w // 2, e.y + e.h // 2

    def _direction(self, d, buttons):
        """FUN_1250_0638: the button nearest the focus in direction `d` (the focus when there is none). A button counts when it is not the
        focus, in the direction's half-plane without overlapping the focus's span on the other axis (0-3 need the focus's centre inside its
        span), and 0 < distance < the best so far (the first of equals wins); the distance is along the axis, or |dx| + |dy| of the centres."""
        cur = self.focus
        cx, cy = self._centre(cur)
        best, found = 0x7fff, cur
        for e in buttons:
            if e is cur:
                continue
            ex, ey = self._centre(e)
            in_y = e.y < cy < e.y + e.h                    # the focus's centre row lies inside the candidate's rows
            in_x = e.x < cx < e.x + e.w
            if d in (0, 1):
                ok = in_x
            elif d in (2, 3):
                ok = in_y
            elif d == 8:
                ok = not in_y and not in_x
            else:
                ok = not in_y and not in_x and {4: ex > cx and ey <= cy, 5: ex > cx and ey > cy,
                                                6: ex <= cx and ey > cy, 7: ex <= cx and ey <= cy}[d]
            if not ok:
                continue
            dist = {0: cy - ey, 1: ey - cy, 2: ex - cx, 3: cx - ex}.get(d, abs(ex - cx) + abs(ey - cy))
            if 0 < dist < best:
                best, found = dist, e
        return found

    def _step(self, buttons, delta):
        """FUN_1250_0544 (+1) / 05bf (-1): the next / previous selectable button, wrapping."""
        return buttons[(buttons.index(self.focus) + delta) % len(buttons)]

    def _focus_to(self, e):
        """The focus moves at once (+0x112) and FUN_1250_15ef glides the pointer to its centre (and clears [9dca] & 2)."""
        self.focus = e
        self.mouse_moved = False
        self.glide_to(*self._centre(e))

    def tab(self):
        """FUN_1250_0fe2: focus the next selectable button and glide the pointer there (MON_SIMULATE _KB_TAB). The highlight comes as it crosses."""
        buttons = self._focus_buttons()
        if not buttons:
            return False
        self._focus_to(self._step(buttons, 1))
        return True

    def _poll_held(self):
        """FUN_1250_0c4c, first in every event: a held Return / Space press ends, with a mouse up, once the key it follows is up and the hand
        is past its first frame (Space follows the Return key's state, as the original reads scan 0x1c); an Escape ends with ESCAPE released."""
        if self.held and self.held not in self.keys_down:
            if self.held == SCAN_RETURN:
                if self.pointer['frame'] > 1:
                    self.held = 0
                    self.mouse_up()
            else:
                self.released, self.held = 'ESCAPE', 0

    def key_event(self, code, scan=None, force=False):
        """A key press reaches the event handler (FUN_1250_0cf9): `code` is the ASCII byte, or the PC scan code | 0x80 for the extended keys
        (Home, arrows, Page keys, keypad 5; 0x8f is Shift+Tab), `scan` the key's scan code (the keyboard state 0c4c reads), `force` the input
        switch MON_SIMULATE turns on for the call (FUN_1258_017f). -> True when the key was used."""
        self._poll_held()
        if scan is not None:
            self.keys_down.add(scan)
        if not (self.input_enabled or force):
            return False
        if code in (KEY_RETURN, KEY_SPACE):                # FUN_1250_10c3: +0x11e = 0x1c, the pointer's mouse down
            self.held = SCAN_RETURN
            self._ptr_down()
            return True
        if code == KEY_ESCAPE:                             # FUN_1250_10e4: +0x11e = 1, "ESCAPE" pressed (the key is not consumed)
            self.held = SCAN_ESCAPE
            self.pressed, self.repeat = 'ESCAPE', 0
            return False
        buttons = self._focus_buttons()
        if code in (KEY_TAB, KEY_BACKTAB):
            if buttons:
                self._focus_to(self._step(buttons, 1 if code == KEY_TAB else -1))
            return True
        tries, fallback = KEY_TRIES.get(code, (None, None))
        if tries is None and code < 0x80 and chr(code).upper() == 'L':
            tries, fallback = (8,), 'prev'
        if tries is not None:
            if buttons:
                moved = next((e for e in (self._direction(d, buttons) for d in tries) if e is not self.focus), None)
                self._focus_to(moved if moved is not None else self._step(buttons, 1 if fallback == 'next' else -1))
            return True
        return self.letter_key(chr(code)) if code < 0x80 else False

    def right_click(self):
        """A right mouse button down (event type 1 with flag 2, FUN_1250_0cf9): "ESCAPE" pressed through FUN_1258_0f8b, as the Escape key does; the
        event is not consumed and nothing holds it (no release label). Dropped while input is off."""
        self._poll_held()
        if self.input_enabled:
            self.pressed, self.repeat = 'ESCAPE', 0

    def key_release(self, scan):
        """A key went up: the keyboard state changes and the event ends a held press (FUN_1250_0c4c)."""
        self.keys_down.discard(scan)
        self._poll_held()

    def letter_key(self, ch):
        """FUN_1250_1166: a letter / digit / punctuation key (above '/' and below '{') clicks the selectable button whose shortcut is that
        character: the pointer on its centre with the button focused clicks at once (FUN_1250_1a92: mouse down and up), else it glides there
        and the arrival clicks (_arrived). -> True when a button matched."""
        if not self._focus_buttons() or not '/' < ch < '{':
            return False
        e = next((b for b in self._focusables() if b.shortcut == ch.lower()), None)
        if e is None:
            self.shortcut = None
            return False
        self.shortcut = e
        if self.focus is e and self.pointer['pos'] == self._centre(e):
            self.shortcut = None
            self._ptr_down()
            self.mouse_up()
        else:
            self.glide_to(*self._centre(e))
        return True

    def poll(self):
        """MON_JUMP (FUN_10d0_5896) -> (label or None, yield).  Priority: highlight 9db6, highlight 9da2,
        released, repeat state / first button press."""
        if self.hl_b:
            lab, self.hl_b = self.hl_b + '_HIGHLIGHT', ''
            return lab, False
        if self.hl_a:
            lab, self.hl_a = self.hl_a + '_HIGHLIGHT', ''
            return lab, False
        if self.click_button_pending:
            # SDL may deliver a complete click before the next 30 Hz MON_JUMP poll.
            # Preserve its BUTTON event before the already-pending RELEASED event.
            self.click_button_pending = False
            self.repeat = 1
            return self.pressed + '_BUTTON', True
        if self.released:
            lab = self.released + '_RELEASED'
            self.repeat, self.pressed, self.released = 0, '', ''
            return lab, False
        if self.repeat:
            if self.repeat > 1:
                return self.pressed + '_REPEAT', True
            self.repeat = 2
            return None, REPEAT_DELAY                      # wait _REPEAT_DELAY, no jump
        if self.pressed:
            self.repeat = 1
            return self.pressed + '_BUTTON', True
        return None, False

    # ---- drawing
    def blit(self, img, frame, x, y):
        w, h, hx, hy, px, mask = frame
        for r in range(h):
            yy = y - hy + r
            if not 0 <= yy < 200:
                continue
            for c in range(w):
                xx = x - hx + c
                if mask[r * w + c] and 0 <= xx < 320:
                    img[yy * 320 + xx] = px[r * w + c]

    def blit_translucent(self, img, frame, x, y):
        """FUN_1270_185b, an element with its translucent flag (+0x2e bit 0): pixel p over screen pixel d becomes
        (p & 0xe0) + TRANSLUCENT[p & 31][d - 128] when d is in the grey ramp 128..159, p != 0 and p's ramp is not 0xe0; else p.
        The element is first drawn into a buffer cleared to 0xff, so a 0xff pixel is transparent here."""
        w, h, hx, hy, px, mask = frame
        for r in range(h):
            yy = y - hy + r
            if not 0 <= yy < 200:
                continue
            for c in range(w):
                xx = x - hx + c
                p = px[r * w + c]
                if mask[r * w + c] and p != 0xff and 0 <= xx < 320:
                    u = img[yy * 320 + xx] - 0x80
                    img[yy * 320 + xx] = (p & 0xe0) + TRANSLUCENT[p & 31][u] if 0 <= u < 32 and p != 0 and p & 0xe0 != 0xe0 else p

    def draw_clipped(self, img, frame, pct):
        w, h, hx, hy, px, mask = frame
        cw = w * pct // 100
        mask2 = bytearray(mask)
        for r in range(h):
            mask2[r * w + cw:(r + 1) * w] = bytes(w - cw)
        self.blit(img, (w, h, hx, hy, px, mask2), 0, 0)

    def draw_viewport(self, img, e, camera):
        """Draw the camera's whole 320x200 view, stretched to the viewport rectangle, in the monitor's grey ramp.

        Observed in the original (NOTES, CELL monitor 1): non-uniform stretch of the full view onto the V rectangle and a
        greyscale palette matching the monitor's grey ramp.  ASSUMPTION: nearest-neighbour sampling at pixel centres
        (the original's resampler is unrecovered); brightness = Rec.601 luma 0.299 R + 0.587 G + 0.114 B mapped linearly
        onto the ramp (the original's conversion is unrecovered)."""
        if self.viewport_frame is None or not self.grey_ramp:
            return
        rgb = self.viewport_frame(camera)
        if rgb is None:
            return
        rgb = np.asarray(rgb)
        if rgb.ndim != 3 or rgb.shape[2] < 3:
            self.warnings.append(f'{self.name}: viewport {camera!r} returned no RGB frame')
            return
        sh, sw = rgb.shape[:2]
        x0, y0, x1, y1 = max(e.x, 0), max(e.y, 0), min(e.x + e.w, 320), min(e.y + e.h, 200)
        if x1 <= x0 or y1 <= y0:
            return
        sx = np.minimum((np.arange(x0, x1) - e.x) * sw // e.w, sw - 1)
        sy = np.minimum((np.arange(y0, y1) - e.y) * sh // e.h, sh - 1)
        mapped = self.to_grey_ramp(rgb[sy][:, sx, :3])
        for row, yy in enumerate(range(y0, y1)):
            img[yy * 320 + x0:yy * 320 + x1] = mapped[row].tobytes()

    def to_grey_ramp(self, rgb):
        """RGB pixels -> grey ramp indices: Rec.601 luma mapped linearly onto the ramp (fitted, see draw_viewport)."""
        luma = np.asarray(rgb, np.float64) @ (0.299, 0.587, 0.114)
        ramp = np.array(self.grey_ramp, np.uint8)
        return ramp[np.clip(np.rint(luma / 255 * (len(ramp) - 1)).astype(int), 0, len(ramp) - 1)]

    def wrap(self, text, fnt, width):
        lines = []
        for para in text.replace('\t', '  ').split('\n'):
            cur = ''
            for word in para.split(' '):
                t = (cur + ' ' + word) if cur else word
                if cur and fnt.width(t) > width:
                    lines.append(cur)
                    cur = word
                else:
                    cur = t
            lines.append(cur)
        return lines

    def draw_text(self, img, e, text, state):
        text = self.expand(text)
        fnt = font(e.header[1])
        base = e.y + (e.h + fnt.height) // 2 - (1 if fnt.height % 2 == 0 else 0)
        x = e.x + (e.w - fnt.width(text)) // 2
        fnt.draw((img, 320, 200), x, base, text, e.colour(state), baseline=True)

    def draw_list(self, img, e):
        fnt = font(e.header[1])
        lh = fnt.height + 1
        rows = []                                   # (text, state)
        for i, (k, t) in enumerate(e.entries):
            st = HIGHLIGHT if e.selectable and i == e.sel else NORMAL
            stamp = e.entry_times[i] if i < len(e.entry_times) else None
            rows += [(ln, st) for ln in self.wrap(self.expand(t, stamp), fnt, e.w)]
        for i, (ln, st) in enumerate(rows[e.top:e.top + max(e.h // lh, 1)]):
            fnt.draw((img, 320, 200), e.x, e.y + i * lh, ln, e.colour(st))

    def expand(self, text, stamp=None):
        """Substitute a label at the current time or a list entry at its award time."""
        return substitute(text, self.resolve_var, self.format_time(stamp) if self.format_time else None)

    def render(self, underlay=None):
        """-> (bytearray of 320*200 palette indices, 768-byte RGB palette). `underlay`: the 200x320x3 RGB picture already on screen (a
        CAMERA SHOW picture), dimmed onto the dark grey range (dark_grey) where the background is transparent. Matches a VGA dump of the
        original's reload dialog over STITLE (DOSBox-X, 2026-11-11)."""
        if underlay is not None:
            img = bytearray(dark_grey(np.asarray(underlay)[:200, :320, :3]).tobytes())
            if self.background:
                self.blit(img, self.background, 0, 0)
        else:
            img = bytearray(self.background[4]) if self.background else bytearray(64000)
        # viewports are the bottom layer: the original draws buttons and art over the camera feed (CELL: buttons sit inside VEWV)
        for nm in sorted(self.order, key=lambda n: self.elements[n].kind != 'V'):
            e = self.elements[nm]
            if not e.active:
                continue
            nf = len(e.frames)
            if e.kind == 'B':
                if e.state != INVISIBLE:
                    f = 1 if e.state == NOT_SELECTABLE and nf <= e.state else min(e.state, nf - 1)    # ASSUMPTION: disabled = its own frame when the art has one, else normal
                    self.blit(img, e.frames[f], 0, 0)
            elif e.kind == 'S':
                for idx in sorted(e.scale):           # ASSUMPTION: scale idx k draws frame k clipped to pct% of its width
                    if idx < nf:
                        self.draw_clipped(img, e.frames[idx], e.scale[idx])
            elif e.kind == 'V':
                if self.viewport and self.viewport[0] == e.name:
                    self.draw_viewport(img, e, self.viewport[1])
            elif e.kind in 'LT':
                continue
            elif e.gauge:
                for i in range(1, min(e.frame + 1, nf)):
                    self.blit(img, e.frames[i], 0, 0)
            elif 0 < e.frame < nf:
                (self.blit_translucent if e.kind in self.translucent else self.blit)(img, e.frames[e.frame], 0, 0)
        for nm in self.order:
            e = self.elements[nm]
            if not e.active or e.header is None:
                continue
            if e.kind == 'L' and e.text and e.state != INVISIBLE:
                self.draw_text(img, e, e.text, e.state)
            elif e.kind == 'T' and e.entries:
                self.draw_list(img, e)
        frames = pointer_frames(self.pointer['name'])
        n = int(self.pointer['frame'])
        if 0 < n < len(frames):
            x, y = self.pointer['pos']
            self.blit(img, frames[n], x - PTR_HOT[0], y - PTR_HOT[1])
        return img, self.pal

    def render_rgb(self):
        """RGB live preview: the indexed render through the palette (viewports are already in the grey ramp)."""
        px, pal = self.render()
        return np.frombuffer(pal, np.uint8).reshape(256, 3)[np.frombuffer(px, np.uint8)].reshape(200, 320, 3).copy()

    def image(self):
        from PIL import Image
        px, pal = self.render()
        im = Image.frombytes('P', (320, 200), bytes(px))
        im.putpalette(pal)
        return im


# ---- CLI
def main():
    import argparse
    ap = argparse.ArgumentParser(description='Run a monitor script block and render the screen.')
    ap.add_argument('--script', help='script file name without extension, e.g. ROBOCNTL (its level group is loaded)')
    ap.add_argument('--block', help='block to start')
    ap.add_argument('--args', nargs='*', type=int, default=[], help='integer block arguments')
    ap.add_argument('--level', default='CHAOS', help='level whose scripts/state are loaded')
    ap.add_argument('--pimm', help='open a PIMM screen on the new-game boot state (INVENTORY, DIAGNOSTICS, JOURNAL or MAIN)')
    ap.add_argument('--click', nargs='*', default=[], help='element names to tap in order (press, release)')
    ap.add_argument('--press', help='press (and hold) an element after the clicks')
    ap.add_argument('--hover', help='hover an element after the clicks')
    ap.add_argument('--ticks', type=int, default=5, help='ticks to run before the first input and after each one')
    ap.add_argument('--scale', type=int, default=2)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    import world as worldmod
    import vm as vmmod
    import scenarios
    if a.pimm:
        world, vm = scenarios.boot_opening()
        scenarios.tick(world, vm, scenarios.opening_ticks(1170))
        vm.fire('GIVELEXSTARTINGBATT')
        world.open_pimm('' if a.pimm.upper() == 'MAIN' else a.pimm)
    else:
        world = worldmod.World(a.level)
        vm = vmmod.VM(world)
        vmmod.load_level(vm, a.level)
        world.vm = vm
        world.start_script(a.script, a.block, a.args)
    for _ in range(a.ticks):
        vm.tick_once()
    for n in a.click:
        world.monitor_tap(n)
        vm.run_ticks(a.ticks)
    if a.press:
        world.monitor_press(a.press)
    if a.hover:
        world.monitor_hover(a.hover)
    mon = world.monitor
    if mon is None:
        from PIL import Image
        Image.new('RGB', (320 * a.scale, 200 * a.scale)).save(a.out)
        print('monitor not running (stopped by the script); wrote a black image')
    else:
        mon.image().convert('RGB').resize((320 * a.scale, 200 * a.scale), 0).save(a.out)
        print('wrote', a.out, 'monitor', mon.name)
    for w in (world.warnings + vm.warnings)[:10]:
        print('warning:', w)


if __name__ == '__main__':
    main()
