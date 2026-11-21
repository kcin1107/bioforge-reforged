"""Read figure records from the running original game through DOSBox-X's debugger control client.

    re/.venv/bin/python -I re/tools/dosbox_live.py WORKDIR [--seconds 150] [--every 1.0] [--start 40] [--keys "..."]
        [--hold SCAN@SECONDS+DURATION] [--phys NAME=STATE] [--set-z NAME=VALUE] [--load-save GAME1.IM1]
        [--control DIR] [--app-bundle] [--only NAME] [--boxes NAME,NAME]

WORKDIR is a scratch folder (created; never point it at game/). The script copies game/app/Bioforge and
game/app/GAMEDAT into WORKDIR/c, writes a DOSBox-X config with the GOG settings (dosboxBIO.conf: svga_s3,
16 MB, cycles 35000, SB16 220/5/1/5) plus `mcp_server=<port>`, listens on 127.0.0.1:<port>, starts dosbox-x
and, once it connects, samples the figure records every --every seconds from --start on. DOSBox-X sends
nothing by itself: this server writes `REQ <id> EXEC <debugger command>` and reads up to `END <id>`.
`MEMDUMPBIN <sel>:<off> <len> <file>` writes into DOSBox-X's working directory (WORKDIR), upper-cased.

Memory layout used (NOTES "Figure grounding"): DGROUP is selector 040F. DGROUP 0x1d19 is the figure list
(u16 count, far pointer array at +8 = 0x1d21), 0x2a66 the player's far pointer. Figure object: +2 type
name, +0xb s32 x, y, z, +0x17 far pointer to the model, +0x34 flags (0x01 gravity, 0x02 no collisions),
+0x6d s32 hull bottom z, +0x79 s32 hull top z, +0xce s32 z velocity, +0xee s32 support z, +0xf7 instance name, +0x146 whoah
teeter, +0x15f current motion name, +0x191 far pointer to the InTrig bytes (one per IMAG; DGROUP 0x1ce9 count,
0x1cf1 far pointer array, printed as index:name of the set ones), +0x1e9 falling, +0x1f3 s16 avoidance count, +0x1f5
far pointers to the avoided objects (name at +2), +0x215 s16 radii (cm). DGROUP 0x63ce is the current camera (name at
+2). Model: +0x25 s16 root limb yaw (256 units per turn), +0x3e s32[9] orientation (24.8 rows; heading =
atan2(m[1][0], m[1][1]) in COMPASS degrees, the ports' convention; it includes the root yaw), +0x88 s32 F, +0x94 s32
base z, +0xa6 s32 root z (R), +0x119 s32 current frame.

--hold presses a PC scan code (hex, e.g. 48 = up: walk) at SECONDS and releases it DURATION later, through the
debugger's port writes: 8042 command D2 on port 64, then the code on port 60, arrives as a keystroke. --phys sets a
PHYS entry's state byte (+0x4a; DGROUP 0x1cf5 count, 0x1cfd far pointer array; name at +2) once the game runs.
--set-z stops the CPU at --start, moves one named figure's rendered origin to signed position z VALUE, then resumes and
prints the injection event. It writes both model base z and figure position z while halted; VALUE is an absolute engine
coordinate for controlled live experiments.
--load-save copies a native GAME1.IM1 into the scratch game directory for manual load-dialog experiments. It does not
alter the normal New Game startup sequence.

The control command {"command": "vga", "out": FILE} writes the mode 13h screen (64000 palette indices) to FILE.

--only NAME samples just that figure (instance name), about ten times a second with --every 0.

Set BIOFORGE_DOSBOX_MUTE=1 to silence the music too: DOSBox-X then sends the MPU-401 output nowhere (mididevice=none).

Prints one JSON line per sample whose values changed. The GOG INSTALL.OPT gamma only changes displayed
colours, never these records.
"""
import argparse
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import threading
import pty
import fcntl
import termios
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME = os.path.join(ROOT, 'game', 'app')
DGROUP = '040F'
# BIOFORGE_DOSBOX_MUTE=1 also silences the MPU-401 music (nosound only covers the mixer); the game still sees the device.
MIDI_DEVICE = 'none' if os.environ.get('BIOFORGE_DOSBOX_MUTE') else 'default'
CONF = """[sdl]
fullscreen=false
output=opengl
[dosbox]
machine=svga_s3
memsize=16
mcp_server={port}
[render]
aspect=false
[cpu]
core=normal
cputype=auto
cycles=35000
[sblaster]
sbtype=sb16
sbbase=220
irq=5
dma=1
hdma=5
[mixer]
nosound=true
[midi]
mididevice=""" + MIDI_DEVICE + """
[dos]
xms=true
ems=true
umb=true
keyboardlayout=none
[autoexec]
mount c "{c}"
c:
cd \\Bioforge
AUTOTYPE -w {wait} -p {period} {keys}
BIOFORGE.EXE
"""


def config_text(port, c, keys, wait=30, period=6):
    return CONF.format(port=port, c=c, keys=keys, wait=wait, period=period)


class Debugger:
    def __init__(self, conn, workdir, reconnect=None):
        self.conn, self.workdir, self.rid, self.buf = conn, workdir, 0, b''
        self.reconnect = reconnect

    def request(self, command):
        for attempt in range(2):
            try:
                self.rid += 1
                self.conn.sendall(f'REQ {self.rid} {command}\n'.encode())
                end = f'END {self.rid}'.encode()
                while end not in self.buf:
                    data = self.conn.recv(65536)
                    if not data:
                        raise EOFError('DOSBox-X closed the control connection')
                    self.buf += data
                out, self.buf = self.buf.split(end, 1)
                text = out.decode('latin1')
                if f'BEGIN {self.rid} ERR' in text or '\nERR' in text or ' ERROR' in text:
                    raise RuntimeError(f'DOSBox-X rejected {command!r}: {text.strip()}')
                return text
            except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
                if attempt or self.reconnect is None:
                    raise
                self.conn = self.reconnect()
                self.buf = b''

    def exec(self, command):
        return self.request(f'EXEC {command}')

    def pause(self):
        return self.request('BREAK')

    def run(self):
        return self.exec('RUN')

    def dump(self, sel, off, length):
        name = 'D.BIN'
        path = os.path.join(self.workdir, name)
        if os.path.exists(path):
            os.remove(path)
        self.exec(f'MEMDUMPBIN {sel}:{off:04X} {length:X} {name.lower()}')
        for _ in range(50):
            if os.path.exists(path) and os.path.getsize(path) >= length:
                break
            time.sleep(0.02)
        with open(path, 'rb') as f:
            return f.read()


def key(dbg, code):
    dbg.exec('OUTP 64 D2')
    dbg.exec(f'OUTP 60 {code:03X}')


def set_phys_state(dbg, name, value):
    count = struct.unpack('<H', dbg.dump(DGROUP, 0x1cf5, 2))[0]
    off, sel = struct.unpack('<HH', dbg.dump(DGROUP, 0x1cfd, 4))
    arr = dbg.dump(f'{sel:04X}', off, 4 * count)
    for i in range(count):
        po, ps = struct.unpack_from('<HH', arr, 4 * i)
        if cstr(dbg.dump(f'{ps:04X}', po, 16)[2:]).upper() == name.upper():
            dbg.exec(f'SM {ps:04X}:{po + 0x4a:04X} {value:X}')
            return True
    return False


def set_s32(dbg, sel, off, value):
    """Write literal bytes; leading zero prevents AF/CF/DF/AC flag-name parsing."""
    bytes_ = ' '.join(f'{byte:03X}' for byte in struct.pack('<i', value))
    dbg.exec(f'SM {sel:04X}:{off:04X} {bytes_}')


def set_bytes(dbg, sel, off, value):
    """Write one halted contiguous record with the debugger's byte SM form."""
    bytes_ = ' '.join(f'{byte:03X}' for byte in value)
    dbg.exec(f'SM {sel:04X}:{off:04X} {bytes_}')


def set_figure_z(dbg, name, value):
    """Set one halted figure's model base and position z, returning its pre-injection sample."""
    raw = sample(dbg)
    before = next((f for f in raw['figures'] if f['name'].upper() == name.upper()), None)
    if before is None:
        return None
    off, sel = before['ptr']
    delta = value - before['pos'][2]
    # The rendered origin is model base + F + root z. Keep position in sync while
    # halted, then let the next engine update begin the fall from that origin.
    b = dbg.dump(f'{sel:04X}', off + 0x17, 4)
    moff, msel = struct.unpack('<HH', b)
    if msel:
        set_s32(dbg, msel, moff + 0x94, value - before['F'] - before['R'])
    set_s32(dbg, sel, off + 0x13, value)
    # Collision checks use this cached hull before deriving it from the model again.
    set_s32(dbg, sel, off + 0x6d, before['hull_bottom'] + delta)
    set_s32(dbg, sel, off + 0x79, before['hull'][5] + delta)
    return before


def set_figure_xy(dbg, name, x, y):
    """Translate one loaded figure, its model, and cached XY hull while halted."""
    raw = sample(dbg)
    before = next((f for f in raw['figures'] if f['name'].upper() == name.upper()), None)
    if before is None:
        raise RuntimeError(f'figure {name} not found')
    if (before['pos'][0], before['pos'][1]) == (0, 0) or before['support'] <= -800000:
        raise RuntimeError(f'game is not ready: {before["name"]} has no loaded world')
    off, sel = before['ptr']
    dx, dy = x - before['pos'][0], y - before['pos'][1]
    moff, msel = struct.unpack('<HH', dbg.dump(f'{sel:04X}', off + 0x17, 4))
    if not msel:
        raise RuntimeError(f'figure {before["name"]} has no model')
    model_x, model_y = struct.unpack('<2i', dbg.dump(f'{msel:04X}', moff + 0x31, 8))
    base_x, base_y = struct.unpack('<2i', dbg.dump(f'{msel:04X}', moff + 0x8c, 8))
    values = (x, y, model_x + dx, model_y + dy, base_x + dx, base_y + dy,
              before['hull'][0] + dx, before['hull'][1] + dy,
              before['hull'][3] + dx, before['hull'][4] + dy)
    if not all(-(1 << 31) <= value < (1 << 31) for value in values):
        raise ValueError('translated figure coordinates must be signed 32-bit integers')
    set_s32(dbg, sel, off + 0x0b, x)
    set_s32(dbg, sel, off + 0x0f, y)
    set_s32(dbg, msel, moff + 0x31, model_x + dx)
    set_s32(dbg, msel, moff + 0x35, model_y + dy)
    set_s32(dbg, msel, moff + 0x8c, base_x + dx)
    set_s32(dbg, msel, moff + 0x90, base_y + dy)
    for hull_offset, value in ((0x65, before['hull'][0] + dx), (0x69, before['hull'][1] + dy),
                               (0x71, before['hull'][3] + dx), (0x75, before['hull'][4] + dy)):
        set_s32(dbg, sel, off + hull_offset, value)
    return before, (model_x, model_y, base_x, base_y)


def set_figure_word(dbg, name, offset, value):
    """Write one signed 16-bit field of a loaded figure object while halted (e.g. +0x229, the AI-off counter that AI OFF / AI ON
    step, NOTES "Default AI"). -> the value before."""
    raw = sample(dbg)
    found = next((f for f in raw['figures'] if f['name'].upper() == name.upper()), None)
    if found is None:
        raise RuntimeError(f'figure {name} not found')
    off, sel = found['ptr']
    before = struct.unpack('<h', dbg.dump(f'{sel:04X}', off + offset, 2))[0]
    set_bytes(dbg, sel, off + offset, struct.pack('<h', value))
    return before


def set_figure_heading(dbg, name, degrees):
    """Set only a loaded figure's persistent base-orientation matrix while halted."""
    raw = sample(dbg)
    before = next((f for f in raw['figures'] if f['name'].upper() == name.upper()), None)
    if before is None:
        raise RuntimeError(f'figure {name} not found')
    if (before['pos'][0], before['pos'][1]) == (0, 0) or before['support'] <= -800000:
        raise RuntimeError(f'game is not ready: {before["name"]} has no loaded world')
    motion = before['motion'].upper()
    if motion.startswith('TURN_') or motion in ('ATK_M4', 'ATK_M6'):
        raise RuntimeError(f'cannot change heading during turning motion {before["motion"]}')
    radians = math.radians(degrees)
    cosine, sine = round(256 * math.cos(radians)), round(256 * math.sin(radians))
    matrix = (cosine, -sine, 0, sine, cosine, 0, 0, 0, 256)
    off, sel = before['ptr']
    packed = struct.pack('<9i', *matrix)
    set_bytes(dbg, sel, off + 0x111, packed)
    actual = dbg.dump(f'{sel:04X}', off + 0x111, len(packed))
    if actual != packed:
        raise RuntimeError('set_heading write failed')
    base_heading = round(math.degrees(math.atan2(sine, cosine)), 1)
    return {'before': before, 'base_heading': base_heading}


def verify_set_xy(dbg, before, model_xy, x, y):
    """Confirm all translated XY values without touching Z or figure flags."""
    off, sel = before['ptr']
    dx, dy = x - before['pos'][0], y - before['pos'][1]
    moff, msel = struct.unpack('<HH', dbg.dump(f'{sel:04X}', off + 0x17, 4))
    actual = (
        *struct.unpack('<2i', dbg.dump(f'{sel:04X}', off + 0x0b, 8)),
        *struct.unpack('<2i', dbg.dump(f'{msel:04X}', moff + 0x31, 8)),
        *struct.unpack('<2i', dbg.dump(f'{msel:04X}', moff + 0x8c, 8)),
        *struct.unpack('<2i', dbg.dump(f'{sel:04X}', off + 0x65, 8)),
        *struct.unpack('<2i', dbg.dump(f'{sel:04X}', off + 0x71, 8)),
    )
    expected = (x, y, model_xy[0] + dx, model_xy[1] + dy, model_xy[2] + dx, model_xy[3] + dy,
                before['hull'][0] + dx, before['hull'][1] + dy,
                before['hull'][3] + dx, before['hull'][4] + dy)
    if actual != expected:
        raise RuntimeError(f'set_xy write failed: {actual}, expected {expected}')


def phys_record(dbg, name):
    """Return a named PHYS object pointer and its object bytes."""
    count = struct.unpack('<H', dbg.dump(DGROUP, 0x1cf5, 2))[0]
    off, sel = struct.unpack('<HH', dbg.dump(DGROUP, 0x1cfd, 4))
    if not count or not sel or count > 1000:
        raise RuntimeError('no loaded PHYS objects')
    arr = dbg.dump(f'{sel:04X}', off, 4 * count)
    for po, ps in struct.iter_unpack('<HH', arr):
        record = dbg.dump(f'{ps:04X}', po, 0x4b)
        if cstr(record[2:]).upper() == name.upper():
            return po, ps, record
    raise RuntimeError(f'PHYS {name} not found')


def set_phys_top(dbg, name, value):
    """Set a non-solid named PHYS maximum Z for a controlled fall."""
    po, ps, record = phys_record(dbg, name)
    before = {'name': cstr(record[2:]), 'state': record[0x4a],
              'top_z': struct.unpack_from('<i', record, 0x3d)[0]}
    if before['state'] != 0:
        raise RuntimeError(f'PHYS {before["name"]} is solid (state {before["state"]})')
    set_s32(dbg, ps, po + 0x3d, value)
    top_z = struct.unpack('<i', dbg.dump(f'{ps:04X}', po + 0x3d, 4))[0]
    state = dbg.dump(f'{ps:04X}', po + 0x4a, 1)[0]
    if (top_z, state) != (value, 0):
        raise RuntimeError(f'phys_top write failed: top {top_z}, state {state}')
    return {'before': before, 'name': before['name'], 'top_z': top_z, 'state': state}


def verify_ready(dbg, camera=None):
    """Reject unloaded worlds and ungrounded Lex before an injection."""
    state = sample(dbg)
    lex = next((f for f in state['figures'] if f['name'].upper() == 'LEX'), None)
    if lex is None:
        raise RuntimeError('game is not ready: LEX is missing')
    if camera and state['camera'].upper() != camera.upper():
        raise RuntimeError(f'game is not ready: camera {state["camera"]!r} is not {camera!r}')
    if (lex['pos'][0], lex['pos'][1]) == (0, 0) or lex['support'] <= -800000:
        raise RuntimeError(f'game is not ready: LEX has no loaded world ({lex["pos"]}, support {lex["support"]})')
    if not lex['flags'] & 1 or lex['falling'] or lex['vz'] or lex['hull_bottom'] != lex['support']:
        raise RuntimeError(f'game is not ready: LEX is not grounded ({lex["name"]})')
    return lex


def game_clock(dbg):
    return struct.unpack('<I', dbg.dump(DGROUP, 0x8330, 4))[0]


def breakpoint_ids(text):
    """Return debugger breakpoint ids from BPLIST's human-readable output.

    DOSBox-X has changed the punctuation around these rows over time, but each
    version labels the row with its decimal id and prints a segmented address.
    Keep this parser deliberately conservative: an unrecognised non-empty list
    is unsafe to edit, so the caller rejects it.
    """
    ids = set()
    for pattern in (
        r'(?im)^\s*(\d+)\.\s*bp\s+[0-9a-f]{1,4}:[0-9a-f]{1,4}',
        r'(?im)^\s*(?:breakpoint\s*)?#?(\d+)\s*(?:[:=]|\s)\s*[0-9a-f]{1,4}:[0-9a-f]{1,4}',
        r'(?im)^\s*(\d+)\s+.*\b[0-9a-f]{1,4}:[0-9a-f]{1,4}\b',
    ):
        ids.update(int(value) for value in re.findall(pattern, text))
    return ids


def list_breakpoints(dbg):
    text = dbg.exec('BPLIST')
    ids = breakpoint_ids(text)
    if ids:
        return ids
    # MCP's BEGIN marker precedes the debugger's own listing text.
    listing = re.sub(r'(?im)^\s*begin\s+\d+\s+\w+\s*$', '', text)
    if re.search(r'(?i)\b(no|none|0)\b.*\bbreakpoint', listing) or re.fullmatch(
            r'(?is)\s*breakpoint list:\s*-*\s*', listing):
        return set()
    raise RuntimeError(f'cannot safely parse BPLIST output: {listing.strip()!r}')


def breakpoint_for_figure(dbg, pointer):
    """Resolve this live figure's per-frame vtable entry and own one breakpoint."""
    off, sel = pointer
    vtable = struct.unpack('<H', dbg.dump(f'{sel:04X}', off, 2))[0]
    entry_off, entry_sel = struct.unpack('<HH', dbg.dump(DGROUP, vtable + 8, 4))
    if not entry_sel:
        raise RuntimeError(f'figure at {sel:04X}:{off:04X} has no update entry')
    before = list_breakpoints(dbg)
    if before:
        raise RuntimeError('refusing frame capture while debugger breakpoints already exist')
    dbg.exec(f'BP {entry_sel:04X}:{entry_off:04X}')
    after = list_breakpoints(dbg)
    added = after - before
    if len(added) != 1 or len(after) != 1:
        raise RuntimeError('could not identify the breakpoint created for frame capture')
    return next(iter(added)), (entry_sel, entry_off), vtable


def debug_registers(dbg):
    """Read the stopped CPU's entry registers from the DOSBox-X debugger."""
    text = dbg.exec('EV CS EIP SS ESP')
    values = re.findall(r'(?i)\b[0-9a-f]+\b', text.split(':', 1)[-1])
    if len(values) < 4:
        raise RuntimeError(f'cannot parse EV register output: {text.strip()!r}')
    cs, ip, ss, sp = (int(value, 16) for value in values[-4:])
    return {'cs': cs, 'ip': ip, 'ss': ss, 'sp': sp}


def frame_samples(dbg, figure_name, count, timeout=2.0):
    """Advance to `count` verified entries of one figure's update function.

    At its update entry the preceding game update is complete, which is the
    stable boundary needed for live motion and landing captures.
    """
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 100:
        raise ValueError('count must be an integer from 1 through 100')
    dbg.pause()
    initial = sample(dbg)
    target = next((f for f in initial['figures'] if f['name'].upper() == figure_name.upper()), None)
    if target is None:
        raise RuntimeError(f'figure {figure_name} not found')
    pointer = target['ptr']
    breakpoint_id = None
    try:
        breakpoint_id, address, vtable = breakpoint_for_figure(dbg, pointer)
        out = []
        for _ in range(count):
            dbg.run()
            deadline = time.monotonic() + timeout
            while True:
                registers = debug_registers(dbg)
                if (registers['cs'], registers['ip']) == address:
                    stack = struct.unpack('<4H', dbg.dump(f'{registers["ss"]:04X}', registers['sp'], 8))
                    stack_pointer = (stack[2], stack[3])
                    if stack_pointer != pointer:
                        # Several figures share the same update wrapper. A hit for
                        # another instance is not the requested update boundary.
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f'timed out waiting for {figure_name} update entry')
                        dbg.run()
                        continue
                    raw = sample(dbg, pointer)
                    raw['clock'] = game_clock(dbg)
                    raw['boundary'] = {
                        'entry': {'cs': registers['cs'], 'ip': registers['ip']},
                        'figure_ptr': list(pointer), 'vtable': vtable,
                        'return': {'ip': stack[0], 'cs': stack[1]},
                    }
                    out.append(raw)
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f'timed out waiting for {address[0]:04X}:{address[1]:04X} frame entry')
                time.sleep(.005)
        return {'samples': out, 'paused': True}
    finally:
        try:
            if breakpoint_id is not None:
                dbg.exec(f'BPDEL {breakpoint_id}')
        finally:
            dbg.pause()


def verify_set_z(dbg, before, value):
    off, sel = before['ptr']
    pos = struct.unpack('<i', dbg.dump(f'{sel:04X}', off + 0x13, 4))[0]
    b = dbg.dump(f'{sel:04X}', off + 0x17, 4)
    moff, msel = struct.unpack('<HH', b)
    base = struct.unpack('<i', dbg.dump(f'{msel:04X}', moff + 0x94, 4))[0]
    bottom = struct.unpack('<i', dbg.dump(f'{sel:04X}', off + 0x6d, 4))[0]
    top = struct.unpack('<i', dbg.dump(f'{sel:04X}', off + 0x79, 4))[0]
    expected = value - before['F'] - before['R']
    delta = value - before['pos'][2]
    expected_bottom, expected_top = before['hull_bottom'] + delta, before['hull'][5] + delta
    if (pos, base, bottom, top) != (value, expected, expected_bottom, expected_top):
        raise RuntimeError('set_z write failed: '
                           f'pos {pos}, base {base}, hull {bottom}/{top}, '
                           f'expected {value}/{expected}/{expected_bottom}/{expected_top}')


def far_pointer(data, offset=0):
    off, sel = struct.unpack_from('<HH', data, offset)
    return (sel, off) if sel or off else None


def camera_links(dbg):
    """The LINKMETOCAMERAS list (DGROUP 0x2f1d, 10c0:547d): node +4 next, +8 process, +0xc s16 count, +0xe far camera pointers (name at +2).
    -> {(process selector, offset): [camera names]}"""
    links, node = {}, far_pointer(dbg.dump(DGROUP, 0x2f1d, 4))
    while node:
        rec = dbg.dump(f'{node[0]:04X}', node[1], 0x36)
        cams = (far_pointer(rec, 0xe + 4 * i) for i in range(min(struct.unpack_from('<h', rec, 0xc)[0], 10)))
        links[far_pointer(rec, 8)] = [cstr(dbg.dump(f'{c[0]:04X}', c[1], 11)[2:]) for c in cams if c]
        node = far_pointer(rec, 4)
    return links


def script_processes(dbg):
    """Every script process in the kernel task table (DGROUP 0x9888 far array, 0x9896 count; type +6 == 0x10a): block name (+0xe93, a record
    that starts with the name), serial +0x38, paused = flag bit 0 of +0xe (1230:0259 skips the task), wait list +0x1c, and its camera links."""
    count = struct.unpack('<H', dbg.dump(DGROUP, 0x9896, 2))[0]
    table = far_pointer(dbg.dump(DGROUP, 0x9888, 4))
    if table is None or not 0 < count <= 1000:
        raise RuntimeError('the kernel task table is not loaded')
    pointers = dbg.dump(f'{table[0]:04X}', table[1], 4 * count)
    links, out = camera_links(dbg), []
    for i in range(count):
        task = far_pointer(pointers, 4 * i)
        if task is None:
            continue
        head = dbg.dump(f'{task[0]:04X}', task[1], 0x40)
        flags = struct.unpack_from('<H', head, 0xe)[0]
        if struct.unpack_from('<H', head, 6)[0] != 0x10a or flags & 8:     # bit 3: a dead task
            continue
        block = far_pointer(dbg.dump(f'{task[0]:04X}', task[1] + 0xe93, 4))
        name = cstr(dbg.dump(f'{block[0]:04X}', block[1], 25)) if block else ''
        row = {'block': name, 'serial': struct.unpack_from('<I', head, 0x38)[0], 'paused': bool(flags & 1),
               'waiting': any(head[0x1c:0x20]), 'cameras': links.get(task, [])}
        if block and dbg.dump(f'{block[0]:04X}', block[1] + 0x22, 1) == b'[':      # a timeline: clock origin and next line's due time ([8330] units, 10c8:0172)
            row['origin'], row['due'] = struct.unpack('<II', dbg.dump(f'{task[0]:04X}', task[1] + 0xea2, 8))
        out.append(row)
    return out


def force_camera(dbg, name=None, auto=None):
    """Staged camera switch: a named camera goes to the trigger-forced slot [63d6] (the camera manager 1130:0fa3 takes it at the next frame); `auto`
    writes the script's auto flag [63da] (0 = held as by `CAMERA <cam>`, so the manager does not switch back). Camera list: DGROUP 0x1d01 count,
    0x1d09 far array, name at +2."""
    if name is not None:
        count = struct.unpack('<H', dbg.dump(DGROUP, 0x1d01, 2))[0]
        table = far_pointer(dbg.dump(DGROUP, 0x1d09, 4))
        pointers = dbg.dump(f'{table[0]:04X}', table[1], 4 * count)
        for i in range(count):
            cam = far_pointer(pointers, 4 * i)
            if cstr(dbg.dump(f'{cam[0]:04X}', cam[1], 11)[2:]).upper() == name.upper():
                set_bytes(dbg, int(DGROUP, 16), 0x63d6, struct.pack('<HH', cam[1], cam[0]))
                break
        else:
            raise ValueError(f'no camera {name} in this level')
    if auto is not None:
        set_bytes(dbg, int(DGROUP, 16), 0x63da, bytes([1 if auto else 0]))


def control_dispatch(dbg, request):
    """Run one JSON control request. The caller keeps the CPU paused between requests."""
    command = request['command']
    if command == 'processes':
        dbg.pause()
        state = sample(dbg)
        return {'clock': game_clock(dbg), 'camera': state['camera'], 'processes': script_processes(dbg)}
    if command == 'vga':                                  # the mode 13h screen (selector 05E7 = A000, NOTES "Visual check"): 64000 palette indices
        dbg.pause()
        data = dbg.dump('05E7', 0, 64000)
        with open(request['out'], 'wb') as f:
            f.write(data)
        return {'clock': game_clock(dbg), 'bytes': len(data), 'paused': True}
    if command == 'force_camera':
        dbg.pause()
        force_camera(dbg, request.get('name'), request.get('auto'))
        return {'clock': game_clock(dbg)}
    if command == 'variables':
        names = request.get('names')
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError('names must be a nonempty list of script variable names')
        dbg.pause()
        return {'clock': game_clock(dbg), 'values': script_variables(dbg, names)}
    if command == 'set_variable':
        name, value = request.get('name'), request.get('value')
        if not isinstance(name, str) or not name or not isinstance(value, int) or isinstance(value, bool) or not -(1 << 31) <= value < (1 << 31):
            raise ValueError('name must be a script variable name and value a signed 32-bit integer')
        dbg.pause()
        before = set_script_variable(dbg, name, value)
        return {'clock': game_clock(dbg), 'before': before, 'value': value}
    if command == 'mouse':
        x, y, buttons = request.get('x'), request.get('y'), request.get('buttons', 0)
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y, buttons)) or not (0 <= x < 320 and 0 <= y < 200 and 0 <= buttons < 8):
            raise ValueError('x, y and buttons must be integers on the 320x200 screen')
        dbg.pause()
        set_mouse(dbg, x, y, buttons)
        return {'clock': game_clock(dbg)}
    if command == 'sample':
        dbg.pause()
        only = request.get('figure')
        raw = sample(dbg)
        if only:
            found = next((f for f in raw['figures'] if f['name'].upper() == only.upper()), None)
            if found is None:
                raise RuntimeError(f'figure {only} not found')
            raw = sample(dbg, found['ptr'])
        raw['clock'] = game_clock(dbg)
        return raw
    if command == 'debug':                                # one raw DOSBox-X debugger command (BP, BPDEL, EV, D ...); its text output
        text = request.get('text')
        if not isinstance(text, str) or not text.strip() or '\n' in text:
            raise ValueError('text must be one debugger command line')
        return {'output': dbg.exec(text.strip())}
    if command == 'pause':
        dbg.pause()
        return {'clock': game_clock(dbg), 'paused': True}
    if command == 'run':
        dbg.run()
        return {'running': True}
    if command == 'set_z':
        dbg.pause()
        verify_ready(dbg, request.get('camera'))
        before = set_figure_z(dbg, request.get('name', 'LEX'), int(request['value']))
        if before is None:
            raise RuntimeError('figure not found')
        verify_set_z(dbg, before, int(request['value']))
        return {'before': before, 'value': int(request['value'])}
    if command == 'set_xy':
        x, y = request.get('x'), request.get('y')
        if (not isinstance(x, int) or isinstance(x, bool) or not -(1 << 31) <= x < (1 << 31) or
                not isinstance(y, int) or isinstance(y, bool) or not -(1 << 31) <= y < (1 << 31)):
            raise ValueError('x and y must be signed 32-bit integers')
        dbg.pause()
        before, model_xy = set_figure_xy(dbg, request.get('name', 'LEX'), x, y)
        verify_set_xy(dbg, before, model_xy, x, y)
        return {'before': before, 'pos': [x, y, before['pos'][2]]}
    if command == 'set_heading':
        name, value = request.get('name', 'LEX'), request.get('value')
        if not isinstance(name, str) or not name:
            raise ValueError('name must name a figure')
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError('value must be a finite number of degrees')
        dbg.pause()
        return set_figure_heading(dbg, name, value)
    if command == 'figure_word':
        name, offset, value = request.get('name'), request.get('offset'), request.get('value')
        if not isinstance(name, str) or not name:
            raise ValueError('name must name a figure')
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (offset, value)) or not 0 <= offset < 0x400 or not -32768 <= value < 32768:
            raise ValueError('offset must be 0..0x3ff and value a signed 16-bit integer')
        dbg.pause()
        return {'before': set_figure_word(dbg, name, offset, value), 'value': value}
    if command == 'phys_top':
        name, value = request.get('name'), request.get('value')
        if not isinstance(name, str) or not name:
            raise ValueError('name must name a PHYS object')
        if not isinstance(value, int) or isinstance(value, bool) or not -(1 << 31) <= value < (1 << 31):
            raise ValueError('value must be a signed 32-bit integer')
        dbg.pause()
        return set_phys_top(dbg, name, value)
    if command == 'key':
        scan, duration = int(request['scan'], 16) if isinstance(request['scan'], str) else int(request['scan']), float(request['duration'])
        if not math.isfinite(duration) or not 0 <= duration <= 120:
            raise ValueError('duration must be finite and from 0 through 120 seconds')
        modifiers = request.get('modifiers', [])
        if not isinstance(modifiers, list):
            raise ValueError('modifiers must be a list of scan codes')
        modifier_scans = [int(value, 16) if isinstance(value, str) else int(value) for value in modifiers]
        dbg.pause()
        dbg.run()
        pressed_modifiers, pressed_primary = [], False
        try:
            for modifier in modifier_scans:
                key(dbg, modifier)
                pressed_modifiers.append(modifier)
            key(dbg, scan)
            pressed_primary = True
            time.sleep(duration)
        finally:
            active_error = sys.exc_info()[0] is not None
            release_error = None
            if pressed_primary:
                try:
                    key(dbg, scan | 0x80)
                except Exception as exc:
                    release_error = exc
            for modifier in reversed(pressed_modifiers):
                try:
                    key(dbg, modifier | 0x80)
                except Exception as exc:
                    if release_error is None:
                        release_error = exc
            try:
                dbg.pause()
            except Exception as exc:
                if release_error is None:
                    release_error = exc
            if release_error is not None and not active_error:
                raise release_error
        return {'clock': game_clock(dbg), 'paused': True}
    if command in ('key_down', 'key_up'):                # hold a key across `frames` requests
        scan = int(request['scan'], 16) if isinstance(request['scan'], str) else int(request['scan'])
        dbg.pause()
        dbg.run()
        key(dbg, scan if command == 'key_down' else scan | 0x80)
        dbg.pause()
        return {'clock': game_clock(dbg), 'paused': True}
    if command == 'run_for':
        seconds, every = float(request['seconds']), float(request.get('every', .05))
        if not math.isfinite(seconds) or not math.isfinite(every) or not 0 <= seconds <= 120 or every < .01:
            raise ValueError('seconds must be finite and from 0 through 120; every must be finite and at least .01')
        dbg.pause()
        figure_name, out, remaining = request.get('figure'), [], seconds
        pointer = None
        if figure_name:
            raw = sample(dbg)
            found = next((f for f in raw['figures'] if f['name'].upper() == figure_name.upper()), None)
            if found is None:
                raise RuntimeError(f'figure {figure_name} not found')
            pointer = found['ptr']
        try:
            while remaining > 0:
                interval = min(every, remaining)
                dbg.run()
                time.sleep(interval)
                remaining -= interval
                dbg.pause()
                raw = sample(dbg, pointer) if pointer else sample(dbg)
                raw['clock'] = game_clock(dbg)
                out.append(raw)
        finally:
            dbg.pause()
        return {'samples': out, 'paused': True}
    if command == 'frames':
        return frame_samples(dbg, request.get('figure', 'LEX'), request['count'])
    if command == 'quit':
        return {'quit': True}
    raise ValueError(f'unknown control command {command!r}')


def control_loop(dbg, directory, owns_emulator=False):
    incoming, outgoing, running = (os.path.join(directory, name) for name in ('in', 'out', 'running'))
    os.makedirs(incoming, exist_ok=True)
    os.makedirs(outgoing, exist_ok=True)
    os.makedirs(running, exist_ok=True)
    while True:
        names = sorted(name for name in os.listdir(incoming) if name.endswith('.json'))
        if not names:
            time.sleep(.02)
            continue
        for name in names:
            path = os.path.join(incoming, name)
            claimed = os.path.join(running, name)
            try:
                os.replace(path, claimed)
            except FileNotFoundError:
                continue
            try:
                with open(claimed) as f:
                    request = json.load(f)
                if request.get('command') == 'quit' and owns_emulator and request.get('stop_emulator') is not True:
                    raise ValueError('quit would stop the owned emulator; set stop_emulator=true explicitly')
                result = control_dispatch(dbg, request)
                reply = {'ok': True, 'result': result}
            except Exception as exc:
                reply = {'ok': False, 'error': str(exc)}
            finally:
                os.unlink(claimed)
            temporary = os.path.join(outgoing, name + '.tmp')
            with open(temporary, 'w') as f:
                json.dump(reply, f, sort_keys=True)
            os.replace(temporary, os.path.join(outgoing, name))
            if reply['ok'] and reply['result'].get('quit'):
                return


def attach_control(work, port, directory):
    """Serve a live DOSBox-X connection without starting or stopping its process."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(1)
    try:
        srv.settimeout(45)
        conn, _ = srv.accept()
        conn.settimeout(20)

        def reconnect():
            srv.settimeout(20)
            connection, _ = srv.accept()
            connection.settimeout(20)
            return connection

        dbg = Debugger(conn, work, reconnect)
        dbg.pause()
        print(json.dumps({'control': os.path.abspath(directory), 'paused': True, 'attached': True}), flush=True)
        control_loop(dbg, directory)
    finally:
        srv.close()


def app_bundle(work, binary):
    """Make the CUA-visible DOSBox-X test wrapper without modifying the installed app."""
    app = os.path.join(work, 'DOSBox-X.app')
    macos = os.path.join(app, 'Contents', 'MacOS')
    executable = os.path.join(macos, 'dosbox-x')
    if not os.path.exists(executable):
        os.makedirs(macos, exist_ok=True)
        shutil.copy2(shutil.which(binary) or binary, executable)
        with open(os.path.join(app, 'Contents', 'Info.plist'), 'w') as f:
            f.write('''<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>CFBundleIdentifier</key><string>org.bioforge.dosboxx.test</string><key>CFBundleName</key><string>DOSBox-X BioForge Test</string><key>CFBundleDisplayName</key><string>DOSBox-X BioForge Test</string><key>CFBundleExecutable</key><string>dosbox-x</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>\n''')
    return executable


def boxes(dbg, names):
    """{'PHYS name': [lo, hi], ...} for PHYS (DGROUP 0x1cf5/0x1cfd) and IMAG (0x1ce9/0x1cf1) objects: +0xb lo, +0x35 hi."""
    out = {}
    for tag, count_off, list_off in (('PHYS', 0x1cf5, 0x1cfd), ('IMAG', 0x1ce9, 0x1cf1)):
        count = struct.unpack('<H', dbg.dump(DGROUP, count_off, 2))[0]
        off, sel = struct.unpack('<HH', dbg.dump(DGROUP, list_off, 4))
        for po, ps in struct.iter_unpack('<HH', dbg.dump(f'{sel:04X}', off, 4 * count)):
            b = dbg.dump(f'{ps:04X}', po, 0x4b)
            if cstr(b[2:11]).upper() in names:
                out.setdefault(f'{tag} {cstr(b[2:11])}', []).append(
                    [list(struct.unpack_from('<3i', b, 0xb)), list(struct.unpack_from('<3i', b, 0x35)), b[0x4a]])
    return out


def cstr(b):
    return b.split(b'\0')[0].decode('latin1')


def object_names(dbg, count_off, list_off):
    """Names (+2) of a DGROUP object list: u16 count at count_off, far pointer array behind the far pointer at list_off."""
    count = struct.unpack('<H', dbg.dump(DGROUP, count_off, 2))[0]
    off, sel = struct.unpack('<HH', dbg.dump(DGROUP, list_off, 4))
    if not count or not sel or count > 1000:
        return []
    arr = dbg.dump(f'{sel:04X}', off, 4 * count)
    return [cstr(dbg.dump(f'{ps:04X}', po, 11)[2:]) for po, ps in struct.iter_unpack('<HH', arr)]


def script_variables(dbg, names):
    """Script manager +0x10 count/+0x12 array, 29-byte name/value records (1118:288d)."""
    count, off, sel = struct.unpack('<3H', dbg.dump(DGROUP, 0xcae6 + 0x10, 6))
    if not 0 < count <= 2000 or not sel or off + count * 29 > 0x10000:
        raise RuntimeError('script variable table is not loaded')
    data = dbg.dump(f'{sel:04X}', off, count * 29)
    values = {cstr(data[i:i + 25]).upper(): struct.unpack_from('<i', data, i + 25)[0]
              for i in range(0, len(data), 29)}
    wanted = [name.upper() for name in names]
    missing = [name for name in wanted if name not in values]
    if missing:
        raise ValueError(f'unknown script variables: {", ".join(missing)}')
    return {name: values[name] for name in wanted}


def set_mouse(dbg, x, y, buttons):
    """Staged: the state the mouse callback leaves (FUN_11d8_0b8e), which the reader takes when no event is queued (FUN_11d8_0b0c): buttons [7bad], x [7baf], y [7bb1], changed [7b9f]."""
    set_bytes(dbg, int(DGROUP, 16), 0x7bad, struct.pack('<HHH', buttons, x, y))
    set_bytes(dbg, int(DGROUP, 16), 0x7b9f, b'\x01')


def set_script_variable(dbg, name, value):
    """Staged: one script global in the 29-byte records of `script_variables`. -> the value it had."""
    count, off, sel = struct.unpack('<3H', dbg.dump(DGROUP, 0xcae6 + 0x10, 6))
    if not 0 < count <= 2000 or not sel or off + count * 29 > 0x10000:
        raise RuntimeError('script variable table is not loaded')
    data = dbg.dump(f'{sel:04X}', off, count * 29)
    for i in range(0, len(data), 29):
        if cstr(data[i:i + 25]).upper() == name.upper():
            set_bytes(dbg, sel, off + i + 25, struct.pack('<i', value))
            return struct.unpack_from('<i', data, i + 25)[0]
    raise ValueError(f'unknown script variable: {name}')


def figure(dbg, ptr, triggers=(), include_avoid=True):
    off, sel = ptr
    b = dbg.dump(f'{sel:04X}', off, 0x240)
    moff, msel = struct.unpack_from('<HH', b, 0x17)
    m = dbg.dump(f'{msel:04X}', moff, 0x12a) if msel else bytes(0x12a)
    rot = struct.unpack_from('<9i', m, 0x3e)
    base_rot = struct.unpack_from('<9i', b, 0x111)
    toff, tsel = struct.unpack_from('<HH', b, 0x191)
    in_trig = dbg.dump(f'{tsel:04X}', toff, len(triggers)) if tsel and triggers else b''
    return {
        'type': cstr(b[2:11]), 'name': cstr(b[0xf7:0xf7 + 25]),
        'pos': list(struct.unpack_from('<3i', b, 0xb)), 'flags': b[0x34],
        'hull': list(struct.unpack_from('<6i', b, 0x65)),
        'locals': list(struct.unpack_from('<10i', b, 0x92)),
        'hull_bottom': struct.unpack_from('<i', b, 0x6d)[0], 'vz': struct.unpack_from('<i', b, 0xce)[0],
        'velocity': list(struct.unpack_from('<3i', b, 0xc6)),
        'move_delta': list(struct.unpack_from('<3i', b, 0xd2)),
        'frame_start': list(struct.unpack_from('<3i', b, 0xba)),
        'last_good': list(struct.unpack_from('<3i', b, 0xe2)),
        'bounce_loss': struct.unpack_from('<i', b, 0xde)[0],
        'support': struct.unpack_from('<i', b, 0xee)[0], 'teeter': struct.unpack_from('<H', b, 0x146)[0],
        'falling': b[0x1e9], 'F': struct.unpack_from('<i', m, 0x88)[0], 'base': struct.unpack_from('<i', m, 0x94)[0],
        'R': struct.unpack_from('<i', m, 0xa6)[0], 'motion': cstr(b[0x15f:0x15f + 25]),
        'heading': round(math.degrees(math.atan2(rot[3], rot[4])), 1), 'yaw': struct.unpack_from('<h', m, 0x25)[0],
        'base_heading': round(math.degrees(math.atan2(base_rot[3], base_rot[4])), 1),
        'root_base': list(struct.unpack_from('<3i', m, 0xd1)), 'blend': struct.unpack_from('<H', m, 0x128)[0],
        'frame': struct.unpack_from('<i', m, 0x119)[0], 'avoid': avoidance(dbg, b) if include_avoid else [],
        'in_trig': [f'{i}:{triggers[i]}' for i, v in enumerate(in_trig) if v],
    }


def avoidance(dbg, b):
    """ADDAVOIDANCEPOINT list: [(object name, radius cm)]."""
    out = []
    for i in range(min(max(struct.unpack_from('<h', b, 0x1f3)[0], 0), 8)):
        po, ps = struct.unpack_from('<HH', b, 0x1f5 + 4 * i)
        name = cstr(dbg.dump(f'{ps:04X}', po + 2, 9)) if po or ps else None
        out.append([name, struct.unpack_from('<h', b, 0x215 + 2 * i)[0]])
    return out


TRIGGERS = []


def sample(dbg, only=None):
    if only is not None:
        f = figure(dbg, only, (), include_avoid=False)
        f['ptr'] = only
        return {'figures': [f]}
    g = dbg.dump(DGROUP, 0x1d19, 0x10)
    count = struct.unpack_from('<H', g, 0)[0]
    aoff, asel = struct.unpack_from('<HH', g, 8)
    player = struct.unpack_from('<HH', dbg.dump(DGROUP, 0x2a66, 4), 0)
    ptrs = []
    if count and asel and count < 200:
        arr = dbg.dump(f'{asel:04X}', aoff, 4 * count)
        ptrs = [struct.unpack_from('<HH', arr, 4 * i) for i in range(count)]
    count = struct.unpack('<H', dbg.dump(DGROUP, 0x1ce9, 2))[0]
    if len(TRIGGERS) != count:                       # the level's IMAG names, read again only when the count changes
        TRIGGERS[:] = object_names(dbg, 0x1ce9, 0x1cf1)
    triggers = TRIGGERS
    out = []
    for p in ptrs:
        f = figure(dbg, p, triggers)
        f['ptr'] = p
        f['player'] = p == player
        out.append(f)
    coff, csel = struct.unpack('<HH', dbg.dump(DGROUP, 0x63ce, 4))
    camera = cstr(dbg.dump(f'{csel:04X}', coff, 11)[2:]) if csel else ''
    return {'camera': camera, 'figures': out}


def launch_background(argv, work, control):
    """Detach the controller's process group and retain diagnostics in its workdir."""
    os.makedirs(work, exist_ok=True)
    log_path = os.path.join(work, 'controller.log')
    command = [sys.executable, '-I', os.path.abspath(__file__),
               *(arg for arg in argv if arg != '--background')]
    with open(log_path, 'a') as output:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.STDOUT, start_new_session=True)
    state = {'pid': proc.pid, 'control': os.path.abspath(control), 'log': log_path}
    with open(os.path.join(work, 'controller.json'), 'w') as output:
        json.dump(state, output)
    return state


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('workdir')
    ap.add_argument('--port', type=int, default=7000)
    ap.add_argument('--seconds', type=float, default=150)
    ap.add_argument('--start', type=float, default=40)
    ap.add_argument('--every', type=float, default=1.0)
    ap.add_argument('--keys', help='AUTOTYPE keys (defaults to New Game)')
    ap.add_argument('--hold', help='SCAN@SECONDS+DURATION, e.g. 48@84+10 holds up for 10 s')
    ap.add_argument('--phys', help='NAME=STATE, e.g. DR3=1 closes the cell door')
    ap.add_argument('--set-z', help='NAME=VALUE: set one figure position z at --start (controlled live experiment)')
    ap.add_argument('--load-save', help='copy a native save into scratch Bioforge/GAME1.IM1 before boot')
    ap.add_argument('--control', help='persistent JSON request directory (in/ and out/)')
    ap.add_argument('--background', action='store_true', help='detach the controller; log to WORKDIR/controller.log')
    ap.add_argument('--attach', action='store_true', help='serve an already-running DOSBox-X connection; never launch or stop it')
    ap.add_argument('--app-bundle', action='store_true', help='launch a CUA-visible scratch DOSBox-X.app wrapper')
    ap.add_argument('--print-config', action='store_true', help='print the generated DOSBox-X config and exit')
    ap.add_argument('--only', help='instance name of the one figure to sample, e.g. FIRSTBOT')
    ap.add_argument('--boxes', help='NAME,NAME: print the in-memory lo/hi of those PHYS and IMAG objects once at --start')
    a = ap.parse_args(argv)
    only_name = a.only.upper() if a.only else None
    work = os.path.abspath(a.workdir)
    if os.path.realpath(work).startswith(os.path.realpath(os.path.join(ROOT, 'game'))):
        sys.exit('refusing to run inside game/')
    if a.background:
        if not a.control or a.print_config:
            ap.error('--background requires --control and cannot use --print-config')
        if a.attach and not os.path.isdir(work):
            ap.error('--attach requires an existing WORKDIR')
        print(json.dumps(launch_background(argv, work, a.control)), flush=True)
        return
    if a.attach:
        if not a.control:
            ap.error('--attach requires --control')
        if not os.path.isdir(work):
            ap.error('--attach requires an existing WORKDIR')
        attach_control(work, a.port, a.control)
        return
    c = os.path.join(work, 'c')
    conf_text = config_text(a.port, c, a.keys or 'esc esc enter enter', 30, 6)
    if a.print_config:
        print(conf_text, end='')
        return
    if not os.path.isdir(os.path.join(c, 'Bioforge')):
        os.makedirs(c, exist_ok=True)
        shutil.copytree(os.path.join(GAME, 'Bioforge'), os.path.join(c, 'Bioforge'))
        shutil.copytree(os.path.join(GAME, 'GAMEDAT'), os.path.join(c, 'Bioforge', 'GAMEDAT'))
    if a.load_save:
        shutil.copy2(a.load_save, os.path.join(c, 'Bioforge', 'GAME1.IM1'))
    conf = os.path.join(work, 'live.conf')
    with open(conf, 'w') as f:
        f.write(conf_text)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', a.port))
    srv.listen(1)
    log = open(os.path.join(work, 'dosbox.log'), 'w')
    binary = os.environ.get('BIOFORGE_DOSBOX_BIN', 'dosbox-x')
    if a.app_bundle:
        binary = app_bundle(work, binary)
    command = [binary, '-conf', conf]
    master = None
    if a.control or a.set_z:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
        env = dict(os.environ, TERM='xterm')
        proc = subprocess.Popen(command, cwd=work, stdin=slave, stdout=slave, stderr=slave, env=env)
        os.close(slave)
        def drain():
            try:
                while data := os.read(master, 4096):
                    log.write(data.decode('latin1', 'replace'))
                    log.flush()
            except OSError:
                pass
        threading.Thread(target=drain, daemon=True).start()
    else:
        proc = subprocess.Popen(command, cwd=work, stdout=log, stderr=subprocess.STDOUT)
    try:
        srv.settimeout(60)
        conn, _ = srv.accept()
        conn.settimeout(20)
        def reconnect():
            if proc.poll() is not None:
                raise EOFError(f'DOSBox-X exited with status {proc.returncode}')
            srv.settimeout(20)
            connection, _ = srv.accept()
            connection.settimeout(20)
            return connection
        dbg, t0, prev = Debugger(conn, work, reconnect), time.time(), None
        hold = None
        if a.hold:
            scan, rest = a.hold.split('@')
            at, dur = rest.split('+')
            hold = [int(scan, 16), float(at), float(at) + float(dur), 0]
        phys = a.phys.split('=') if a.phys else None
        set_z = a.set_z.rsplit('=', 1) if a.set_z else None
        while (a.control or time.time() - t0 < a.seconds) and proc.poll() is None:
            t = time.time() - t0
            if a.control and t >= a.start:
                dbg.pause()
                print(json.dumps({'control': os.path.abspath(a.control), 'paused': True}), flush=True)
                control_loop(dbg, a.control, owns_emulator=True)
                break
            if phys and t >= a.start:
                print(json.dumps({'t': round(t, 1), 'phys': phys, 'set': set_phys_state(dbg, phys[0], int(phys[1]))}),
                      flush=True)
                phys = None
            if set_z and t >= a.start:
                dbg.pause()
                verify_ready(dbg)
                before = set_figure_z(dbg, set_z[0], int(set_z[1], 0))
                if before is None:
                    print(json.dumps({'t': round(t, 1), 'set_z': set_z, 'set': False}), flush=True)
                else:
                    verify_set_z(dbg, before, int(set_z[1], 0))
                    print(json.dumps({'t': round(t, 1), 'set_z': {'name': set_z[0], 'value': int(set_z[1], 0)},
                                      'before': before, 'set': True}), flush=True)
                    a.only = before['ptr'] if a.only else None
                    prev = None
                dbg.run()
                set_z = None
            if a.boxes and t >= a.start:
                print(json.dumps({'t': round(t, 1), 'boxes': boxes(dbg, a.boxes.upper().split(','))}), flush=True)
                a.boxes = None
            if hold and hold[3] < 2 and t >= hold[1 + hold[3]]:
                key(dbg, hold[0] | (0x80 if hold[3] else 0))
                print(json.dumps({'t': round(t, 1), 'release' if hold[3] else 'press': f'{hold[0]:02X}'}), flush=True)
                hold[3] += 1
            if t >= a.start:
                if a.only and not isinstance(a.only, tuple):
                    found = [f for f in sample(dbg)['figures'] if f['name'].upper() == a.only.upper()]
                    if not found:
                        time.sleep(a.every)
                        continue
                    a.only = found[0]['ptr']
                state = sample(dbg, a.only)
                # A save/load replaces all figure allocations. Drop a cached pointer
                # as soon as it no longer identifies the requested figure.
                if isinstance(a.only, tuple) and state['figures'][0]['name'].upper() != only_name:
                    a.only = only_name
                    prev = None
                    continue
                if state != prev:
                    print(json.dumps({'t': round(t, 1), **state}), flush=True)
                    prev = state
            time.sleep(a.every)
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        # On macOS, closing a PTY while the drain thread is blocked in read can
        # wait for that read. Stop the writer first so the reader receives EOF.
        if master is not None:
            try:
                os.close(master)
            except OSError:
                pass


if __name__ == '__main__':
    main(sys.argv[1:])
