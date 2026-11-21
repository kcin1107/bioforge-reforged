"""Engine binding: lets the script VM drive real figures, cameras and room sprites.

    world = World('LANDPAD'); vm = VM(world); load_level(vm, 'LANDPAD'); vm.fire(block)
    each tick:  vm.tick_once(); world.step();   to draw:  world.render() -> 200x320x3 RGB

Everything the executable does not tell us is an ASSUMPTION; each is a named constant or a
commented branch below.

Conventions
  * Heading is in degrees; the figure's forward direction (the local -Y axis of the mesh, the
    direction the WALK motion's root travels) in the world is (-sin h, -cos h); heading 0 = mesh
    as authored. Rendering yaw = -heading (scene.place rotates counter-clockwise). Chosen so that
    LEX at FACE -90 walks toward +x (LEX_POS -> LEX_POS2) and AIRMECHO at FACE 90 toward -x
    (-> AIR_POS), as in MEETMECH.
  * Figure position = the figure origin (pelvis), same z convention as FIGR records. Waypoint z is
    the floor, so a GO target puts the origin at waypoint z + foot_offset(type), where
    foot_offset = the engine's F: the rest-pose depth of the lowest joint below the root from its fixed-point FK
    (FUN_1040_0cf8; salsa.foot_depth). A grounded figure's rendered origin is support + F + the motion's root z.
"""
import copy
import math
import os
import random
import re
import struct
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'formats'))
import parse  # noqa: E402
import vm as vmmod  # noqa: E402
import bed  # noqa: E402
import salsa  # noqa: E402
from eor import Mesh  # noqa: E402
from level import load_level as load_level_objs  # noqa: E402
import level as levelmod  # noqa: E402
from flex import read_flex  # noqa: E402
import sound as sound_mod  # noqa: E402
import keys as keys_mod  # noqa: E402
import items as items_mod  # noqa: E402
import missiles as missiles_mod  # noqa: E402
import effects as effects_mod  # noqa: E402
import floors as floors_mod  # noqa: E402
import audio as audio_mod  # noqa: E402
import mechanics as mechanics_mod  # noqa: E402
import presentation as presentation_mod  # noqa: E402
import show as show_mod  # noqa: E402
import monitor as monitor_mod  # noqa: E402
import options as options_mod  # noqa: E402
import settings as settings_mod  # noqa: E402
import subtitles as subtitles_mod  # noqa: E402
from scene import place, project  # noqa: E402
import compose as compose_mod  # noqa: E402
from compose import compose  # noqa: E402

CLOCK_PER_TICK = 2 << 8   # the 60 Hz clock [8330] << 8 advances 512 per 30 Hz VM tick (FUN_1088_1854's time base)
DEFAULT_SPEED = 512       # MY_SPEED default [249c]; FUN_1088_22ba stores MY_SPEED at model+0xea
FACE_IS_ABSOLUTE = True   # ASSUMPTION: FACE <number> = absolute heading in degrees
DEFAULT_TYPE_PLAYER = 'LEX'
STAND, LOOP_KEYWORD = 'STAND', 'CONTINUE'
MOTION_DEFERRED_DURING_GO = True   # ASSUMPTION: MOTION issued while a GO walk runs plays after arrival
                                   # (for direct callers; scripted GO waits before the next statement)
GAMEDAT = os.path.join(parse.ROOT, 'game', 'app', 'GAMEDAT')
INITGAME = os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'INITGAME')     # initial state, used when booting a new game
BODY = os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'BODY')
SAVES = os.path.join(parse.ROOT, 're', 'out', 'saves')      # prototype GAMEn.IM1 files (the original uses C:\Bioforge)
ROOMS = os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'ROOMS')
compose_mod.rooms_dir = lambda level_path: ROOMS      # compose derives it from the level path, which breaks for INITGAME/ (same dir for GAMEDAT/)
MAX_VIEW_CAMS = 30
MAX_AVOID = 8            # FUN_1098_0b88: avoidance points per figure (+0x1f3 count, +0x1f5 objects, +0x215 radii)
# Shading ramps of DATA/PALETTE.IFF RANG (start, last offset): a colour c belongs to a ramp if start <= c <= start + last
# (FUN_1150_1ef4, inclusive)
RAMPS = [(0x70, 9), (0x7a, 5), (0x80, 31), (0xa0, 31), (0xc0, 15), (0xd0, 15), (0xe0, 15), (0xf0, 14)]
CYCLE_TOLERANCE = 20      # ASSUMPTION: a CONTINUE motion loops only if its last frame's limb angles are within this of its first
UNITS_PER_CM = 20.0       # ASSUMPTION from data: Lex's STAND mesh is ~3,590 units tall for ~180 cm (MONSTER_MOVE's ranges are cm)
DEFAULT_EXTENT_CM = np.array([10.0, 10.0, 10.0])
EXE = os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'BIOFORGE.EXE')
NO_FLOOR = -819200        # floor queries FUN_1060_0871/03f2 start from -0xc8000 ("nothing below")
FALL_DV = 512 // 5        # FUN_1088_39ef: vz -= frame time [83a0] / 5 per frame; [83a0] = 512 (8.8 ticks) at 30 fps
FALL_VMIN = -0x500        # ... applied only while vz > -0x500 (-1280; disassembly 1088:3d22: CMP hi,-1 / CMP lo,0xfb00), so
                          # vz stops at -1326 (30 fps). The old -0x10500 was a misread of that compare
FRAME_TIME8 = 512         # [83a0]: frame time in 8.8 ticks of the 60 Hz clock; 512 = 30 fps (the prototype's one tick per frame)
GO_RADIUS = 0x266         # 1098:11c0: a GO ends once the figure is within this many units of its target (10e0:1a4c)
LAND_REVERT = 0x1000      # FUN_10a0_0ead: support more than this above the hull bottom restores the previous position
AREA_GROW = 0x1000        # FUN_1138_131c grows an area anchor box by this before collecting its physical_objs
ENGINE_ONESHOTS = ('LAND_HARD', 'LAND_MEDIUM', 'LAND_SOFT', 'WHOAH_FORWARD', 'WHOAH_BACKWARD', 'WHOAH_LEFT', 'WHOAH_RIGHT',
                   'MANTLE_3', 'MANTLE_6', 'MANTLE_9')
ROOT_Z_KEEP_MIN = 100.0   # ASSUMPTION: a finished motion's last root z at least this large is kept as height by a gravity-less figure
GESTURES = ('TAUNT1', 'TAUNT2', 'TAUNT3', 'TAUNT4')   # ASSUMPTION: a CONTINUE taunt plays once although its last pose equals its first
                          # (TAUNT2 / TAUNT3 / TAUNT4 / C_TAUNT*: limb difference 0 passes is_cycle). GREET_GUARD1 starts Lex's TAUNT2 with CONTINUE
                          # and never ends it: its 23 frames last about as long as the two subtitles that follow, after which the player is free
TURN_STEP = 10.0          # TURNTOENEMY TEN_DEGREES: degrees per call
CONFRONT_DONE = 8 * 360 / 256     # FUN_10e8_0079: within 8/256 of a turn the task snaps to the enemy
PLAYER_TURN_PER_TICK = 4.0  # 10a8:0541: a held turn key adds [83a0] << 1 (2 degrees per 60 Hz clock tick) while moving. Live: 113-117 degrees/s walking
TURN_WHILE_MOVING = ('WALK', 'WALK_BACK', 'RUN', 'ATK_M8', 'ATK_M2')    # the motions that take it; standing, TURN_LEFT / RIGHT turn by their root yaw (live: about 45 degrees/s)
TURN_KEYS = {0x4b: -1, 0x47: -1, 0x4d: 1, 0x49: 1}   # 10a8:0541: Left and Home turn left, Right and PgUp turn right
TURN_MOTIONS = ('TURN_RIGHT', 'TURN_LEFT', 'TURN_RIGHT_FAST', 'TURN_LEFT_FAST')   # turning motions: the root yaw turns the figure
MANUAL_MOVES = {'WALK', 'RUN', 'WALK_BACK', 'SIDESTEP_LEFT', 'SIDESTEP_RIGHT'} | {f'ATK_M{n}' for n in (1, 2, 3, 4, 6, 7, 8, 9)}
SOUND_TICKS = 90          # ASSUMPTION: a sound whose name has no sample plays for 3 s
VOICES = 8                # sound voice slots
LOOP_TICKS = 10 ** 9      # a looped sample's handle stays valid until STOPSOUND / STOPALLSOUNDS
AUTO_CAMERA = True        # the camera manager (FUN_1130_0fa3) switches cameras every frame
FOLLOW_DEFAULT = 'PLAYER'
NEAR_DEPTH = 200          # figures with any vertex closer than this to the camera plane are not drawn

WAYPOINT_FUNCS = ('DISTFROMWAYPOINT', '2DDISTFROMWAYPOINT', 'ANGLEFROMWAYPOINT', 'AMINWAYPOINT')
# Statements and functions World.call acts on (MON_* by prefix). Anything else that reaches the engine is dropped and listed in
# World.unmodelled (a "NAME: unmodelled statement (ignored)" entry per name), so a gap shows up in the scenario manifests
# instead of vanishing.
MODELLED_STMTS = frozenset((
    'ADDAVOIDANCEPOINT', 'ADDENTRY', 'ADDLOGENTRY', 'ADDTOPITCH', 'ADDVIEWINGCAMS', 'AI', 'ANIMATE', 'APPLY', 'BANKINSFX', 'BOUNCINESS',
    'CAMERA', 'CAMERAAUTOACTIVATE', 'CAMERAFOLLOW', 'CAPTUREKEYBOARD', 'CHANGEMYFORM', 'COLLISIONS', 'COMBATMODE', 'CONFRONTENEMY',
    'CREATEFIGURE', 'CREATEITEM', 'DAMAGE', 'DEBUG', 'DEBUGINFO', 'DEFINEENEMY', *presentation_mod.STMTS, *show_mod.STMTS, 'JUMPON', 'DEFINEVIEWINGCAMS', 'EXPLODE', 'FACE', 'FINDFIRSTFIGURE', 'FLOATATHEIGHT',
    'FORCERELOAD', 'FREEHAND', 'GO', 'GRABCRITTER', 'GRAVITY', 'INCVIRTUALSECONDS', 'INDIVIDUALIZE', 'INVULNERABLE', 'KILL', 'KILLCURITEM',
    'LEAP', 'LINKMETOCAMERAS', 'LOADLEVEL', 'MAKEFLATOBJECT', 'MOTION', 'MUSIC', 'PLACEITEM', 'RELEASEFROMLIMB', 'RELEASEKEYBOARD',
    'REMOVEAVOIDANCEPOINT', 'REMOVEENTRY', 'REMOVELOGENTRY', 'REPLACESOUND', 'REVERTSOUND', 'REVERTSOUNDCACHE', 'SETAI', 'SETFLOOROFPHYS',
    'SETPITCH', 'SETREFERENT', 'SETSOUNDCACHE', 'SETVELOCITY', 'SETVOLUME', 'SNAPTOPOSE', 'SPARWITHPLAYER', 'STOPALLSOUNDS', 'STOPAMBIENT',
    'STOPMOTION', 'STOPSOUND', 'STOPVELOCITY', 'TELEPORTALLONPHYS', 'THROWCURITEM', 'TURN', 'TURNTOENEMY'))
MODELLED_FUNCS = frozenset((
    'AMBIENT', 'AMINEXTENT', 'AMINTRIGGER', 'ANGLEFROMENEMY', 'ATTACKRADIUS', 'COMPASS', 'COORDX', 'COORDY', 'COORDZ', 'COUNTBITS',
    'DISTFROMENEMY', 'DISTFROMEXTENT', 'DISTFROMITEM', 'DISTFROMTRIGGER', '2DDISTFROMCOORDS', '2DDISTFROMITEM', *show_mod.FUNCS, 'FADE', 'FINDNEXTFIGURE', 'FIRE', 'MAKEMISSILE',
    'GETCAMERAAMBIENT', 'GETROOMAMBIENT', 'GETSOUNDHANDLE', 'HEADING', 'ISAION', 'ISGRAVITYON', 'ISKEYBOARDCAPTURED', 'ISCARRYING', 'ISCARRYINGANYTHING', 'ISCURRENTCAMERA', 'ISHANDLEPLAYING', 'ISHIDDEN',
    'ISINCOMBATMODE', 'ISINVULNERABLE', 'ISKEYPRESSED', 'ISLEVEL', 'ISMONITORRUNNING', 'ISMYFORM', 'ISMYMOTION', 'ISPLAYERSMOTION', 'ISSOUNDPLAYING', 'MINORSUBTITLE', 'MODIFYPITCHOVERTIME', 'MODIFYVOLUMEOVERTIME', 'MOTIONEXISTS', 'RANDOM',
    'SETCURRENTFIGURE', 'SETCURRENTITEM', 'SOUND', 'SUBTITLE', 'VELOCITYX', 'VELOCITYY', 'VELOCITYZ') + WAYPOINT_FUNCS)

_FIGURE_EXTENTS = None
_FIGURE_PROPS = None
_COS_TABLE = None
_SOUNDS = {}


def sound_bank(language='E'):
    """-> (Samples, {lower-case sound name: sample index}) for SOUND/<language>SAMPLES.FLX, loaded once per language."""
    if language not in _SOUNDS:
        sm = sound_mod.Samples(os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'SOUND', language + 'SAMPLES.FLX'))
        _SOUNDS[language] = (sm, {k: v for k, v in sound_mod.load_sound_ids().items() if v < len(sm)})
    return _SOUNDS[language]


def cos_table():
    global _COS_TABLE
    if _COS_TABLE is None:
        _COS_TABLE = salsa.cos_table(EXE)
    return _COS_TABLE


def hull_units(cm):
    """FUN_1070_08df: script centimetres to world units, (cm << 3 << 8) / 100 truncated toward zero."""
    v = int(cm) * 2048
    return v // 100 if v >= 0 else -((-v) // 100)


def cm_from_units(units):
    """The script distance functions' unit conversion (DISTFROMENEMY 10d8:1278, DISTFROMWAYPOINT 16a6, 2DDISTFROMWAYPOINT 0534,
    ATTACKRADIUS 0e28): (units * 100 + 0x80) / 0x800 as a signed long divide (truncates toward zero), i.e. world units / 20.48
    (the inverse of hull_units). Replaces the earlier `units / 20` assumption."""
    v = int(units) * 100 + 0x80
    return v // 2048 if v >= 0 else -((-v) // 2048)


def u32(value):
    return int(value) & 0xffffffff


def s32(value):
    value = u32(value)
    return value - 0x100000000 if value & 0x80000000 else value


def abs_s32(value):
    """16-bit NEG low/high sequence used after the fixed collision products."""
    value = s32(value)
    return s32(-value) if value < 0 else value


def collision_volume(size):
    """FUN_1058_12c7/FUN_1058_142d: x*y then z, low-32 unsigned MUL and signed >>8 after each multiply."""
    x, y, z = (int(v) for v in size)
    xy = s32(s32(u32(x) * u32(y)) >> 8)
    return abs_s32(s32(s32(u32(xy) * u32(z)) >> 8))


def fix_div(a, b):
    """FUN_1210_0c24: 24.8 fixed-point divide, trunc((a << 8) / b) in 32 bits."""
    q = abs(int(a) << 8) // abs(int(b))
    return s32(q if (a < 0) == (b < 0) else -q)


def approx_length(v):
    """FUN_1210_0f9b: |v| without a square root. With |v| sorted a >= b >= c:
    a + (c >> 2) - (b >> 5) + (b >> 3) + (b >> 2)."""
    a, b, c = sorted((abs(int(x)) for x in v), reverse=True)
    return a + (c >> 2) - (b >> 5) + (b >> 3) + (b >> 2)


def move_steps(d, min_span):
    """FUN_10a0_22e1: steps = the integer part of the 24.8 ratio |d| / smallest hull span (16 bits). The length takes all
    three axes (a 2-vector is a move with dz = 0)."""
    n = (fix_div(approx_length((d[0], d[1], d[2] if len(d) > 2 else 0)), min_span) >> 8) & 0xffff
    return n - 0x10000 if n & 0x8000 else n


def fix_mul(a, b):
    """FUN_1210_0c42: (a * b) >> 8 on the 64-bit product (arithmetic shift = floor), low 32 bits."""
    return s32((int(a) * int(b)) >> 8)


def velocity_step(v, dt8=FRAME_TIME8):
    """FUN_1088_384e: the per-frame step (+0xd2/+0xd6/+0xda) from the velocity (+0xc6/+0xca/+0xce, units per 30 fps frame).
    fps = (0x3c00 // [83a0]) << 8 (unsigned divide, whole frames per second; at least 1), scale = 0c24(30 << 8, fps) =
    30 / fps in 8.8, step = 0c42(v, scale) per axis. At 30 fps ([83a0] = 512) scale = 256 and step == v."""
    dt8 = int(dt8) or 1                                  # a zero frame time is replaced by 1
    fps8 = max(1, s32((0x3c00 // dt8) << 8))
    scale = fix_div(0x1e00, fps8)
    return [fix_mul(c, scale) for c in v]


def scale_step(step, i, n):
    """FUN_10a0_22e1, a blocked (or trigger-stopped) in-loop step i of n: each step component becomes
    0c24(0c42(c, i << 8), n << 8) = trunc(c * i / n) (the IDIV truncates toward zero)."""
    return [fix_div(fix_mul(c, i << 8), n << 8) for c in step]


def length2d(x, y):
    """FUN_1210_000d: fixed-point |(x, y)|. Normalise until the larger component reaches 0x1000 (FUN_1208_0b86) or
    falls to 0x40000 (FUN_1208_0c65), square through the 24.8 multiply, square-root isqrt(v << 8) (FUN_1210_1047),
    then undo the normalising shift."""
    x, y = abs(int(x)), abs(int(y))
    if x == 0 and y == 0:
        return 0
    up = down = 0
    while x < 0x1000 and y < 0x1000:
        x, y, up = x << 1, y << 1, up + 1
    if not up:
        while x > 0x40000 or y > 0x40000:
            x, y, down = x >> 1, y >> 1, down + 1
    r = math.isqrt(s32(((x * x) >> 8) + ((y * y) >> 8)) << 8)
    return r >> up if up else r << down


def push_out(target, other, r):
    """FUN_1098_096e: move a target closer than r to ``other`` out to r along the line between them
    (q = (r << 4) / |d|, then other - d * q >> 4 through the 24.8 multiply); z is kept."""
    dx, dy = int(other[0]) - int(target[0]), int(other[1]) - int(target[1])
    dist = length2d(dx, dy)
    if dist >= r:
        return target
    q = (r << 4) // (dist or 1)
    out = np.array(target, float)
    out[0] = int(other[0]) - (s32(((dx << 8) * (q << 8)) >> 8) >> 12)
    out[1] = int(other[1]) - (s32(((dy << 8) * (q << 8)) >> 8) >> 12)
    return out


def figure_props():
    """FIGURES.SCP data tables per block: {block: {property: values}}. `< MAX HPS = n >` parses as an unnamed row."""
    global _FIGURE_PROPS
    if _FIGURE_PROPS is None:
        data = parse.parse_file(os.path.join(parse.ROOT, 'game', 'app', 'Bioforge', 'SCRIPT', 'FIGURES.SCP'), parse.Defs())
        props = {}
        for block in data.blocks:
            rows = props.setdefault(block.name.upper(), {})
            for name, values, _ in block.tables:
                if name is None and '=' in values:
                    k = values.index('=')
                    name, values = ' '.join(str(v) for v in values[:k]).upper(), values[k + 1:]
                if name is not None:
                    rows.setdefault(name.upper(), values)
        _FIGURE_PROPS = props
    return _FIGURE_PROPS


def figure_prop(name, ftype, prop, default):
    """FUN_1120_0763 looks a property up under the figure's instance name (+0xf7). ASSUMPTION: a figure without
    a block of its own falls back to its type's block."""
    props = figure_props()
    for block in (str(name).upper(), str(ftype).upper()):
        values = props.get(block, {}).get(prop)
        if values:
            return values[0]
    return default


def form_prop(fig, prop, default):
    """The properties FUN_1088_2a87 reads by the type name (+0x1ea, 1088.c:1936-1966: IMPACT_ARMOR, ENERGY_ARMOR, IS_REFLECTIVE, AUTO_TURN_SPEED,
    PERSONAL_RADIUS), at creation and on CHANGEMYFORM, not by the instance name: DROGG3 is a DROGGMIR, IMPACT_ARMOR 8, though a DROGG3 block says 100."""
    return figure_prop(fig.type, fig.type, prop, default)


def personal_radius(fig):
    """FUN_1088_2a87: PERSONAL_RADIUS (default 45 cm) in world units at the hull scale, fig+0x1e3."""
    return hull_units(int(form_prop(fig, 'PERSONAL_RADIUS', 45)))


def figure_extents():
    """Type-specific EXTENT tables from FIGURES.SCP."""
    global _FIGURE_EXTENTS
    if _FIGURE_EXTENTS is None:
        _FIGURE_EXTENTS = {block: np.array(rows['EXTENT'][:3], float)
                           for block, rows in figure_props().items() if len(rows.get('EXTENT', ())) >= 3}
    return _FIGURE_EXTENTS


def figr_ai_name(raw):
    """A FIGR record's AI name (figure +0x178, the char[25] that ends 4 bytes before the viewing-camera count): SETAI (10d0:6e8c) writes
    it and the AI start (1088:33d4) runs the block `<it>_AI`, so a level figure has an AI without a script SETAI. None if unknown."""
    cams = figr_view_cams(raw)
    if cams is None:
        return None
    o = len(raw) - 79 - 9 * len(cams) - 2 - 4 - 25
    name = raw[o:o + 25].split(b'\0')[0]
    return name.decode('latin1').upper() if re.fullmatch(rb'[A-Za-z0-9_]+', name) else None


def figr_ai_off(raw):
    """A FIGR record's AI-off counter (figure +0x229, the s16 after the viewing-camera list; the loader 1088:3325 reads it for records of
    version >= 0x10, all of the shipped ones). 0 = the AI runs by default: only CHAOS's USE_BOT has 1 (BEACH's MARINE3A has junk there, and its
    saved AI name has no block anyway)."""
    return struct.unpack_from('<h', raw, len(raw) - 79)[0]


def figr_view_cams(raw):
    """Initial viewing-camera list of a FIGR record: u16 count c + c 9-byte names + 79 trailing bytes.
    Several c can satisfy the count check (c=0 also matches when the last name's padding is zero);
    candidates need printable names, and a c > 0 wins over c = 0. -> list of names, or None if no c fits."""
    cands = []
    for c in range(MAX_VIEW_CAMS + 1):
        o = len(raw) - 79 - 9 * c - 2
        if o < 0 or struct.unpack_from('<H', raw, o)[0] != c:
            continue
        names = [raw[o + 2 + 9 * i:o + 11 + 9 * i].split(b'\0')[0] for i in range(c)]
        if all(re.fullmatch(rb'[A-Za-z0-9_]+', n) for n in names):
            cands.append([n.decode('latin1').upper() for n in names])
    nonempty = [c for c in cands if c]
    return nonempty[0] if len(nonempty) == 1 else (cands[0] if len(cands) == 1 else None)


def cam_boxes(objs):
    """CAM_xxxx IMAG records -> [{'name', 'camera', 'lo', 'hi'}]: the axis-aligned box pos..pos2
    (min/max per axis). The camera is the name suffix (the field @45 repeats it)."""
    out = []
    for o in objs:
        if o['tag'] == 'IMAG' and o['name'].upper().startswith('CAM_'):
            out.append({'name': o['name'].upper(), 'camera': o['name'][4:].upper(),
                        'lo': np.minimum(o['pos'], o['pos2']), 'hi': np.maximum(o['pos'], o['pos2'])})
    return out


def box_contains(box, p):
    return bool(np.all(p >= box['lo']) and np.all(p <= box['hi']))


def box_volume(box):
    return float(np.prod(box['hi'] - box['lo']))


def accepts(cam, P):
    """Camera acceptance test (FUN_1110_1a95) for the followed object's position P.
    d = approx_length(P - eye) (FUN_1210_0f9b, not the Euclidean length) must lie in [NEARMARK, FARMARK] (raw CAMR values compared with world
    units);
    rel = bearing(eye -> P) - camera heading (both atan2 in the xy plane, degrees, mod 360) must be
    < half_fov - fovr2 or > 360 - half_fov + fovr1. -> (accepted, d)."""
    half, _, far, near, fovr1, fovr2 = cam['extra']
    d = float(approx_length(P - cam['pos']))
    if not near <= d <= far:
        return False, d
    fwd = cam['R'][1]
    heading = math.degrees(math.atan2(fwd[1], fwd[0]))
    bearing = math.degrees(math.atan2(P[1] - cam['pos'][1], P[0] - cam['pos'][0]))
    rel = (bearing - heading + 1080) % 360
    return rel < half - fovr2 or rel > 360 - half + fovr1, d


def is_cycle(frames, turning=False):
    """True if a motion's last pose is close to its first (limb angle difference <= CYCLE_TOLERANCE), i.e. it can loop."""
    if len(frames) < 2:
        return True
    difference = np.abs(np.array(frames[0][2], float) - np.array(frames[-1][2], float))
    if turning:
        difference[0, 2] = 0       # a turning motion bakes the root limb's yaw at its wrap
    return difference.max() <= CYCLE_TOLERANCE


def motion_loops(assets, name):
    """Whether a CONTINUE motion loops: its header's frame event list holds the 0xfe end marker (1088:1854; data-checked on all
    227 LEX motions), else (no list) the port's is_cycle rule."""
    loops = assets.motion_info[name][5]
    return is_cycle(assets.motions[name], assets.motion_info[name][1] & 1) if loops is None else loops


def shade_mesh(mesh, V, eye, anim=None):
    """Copy of `mesh` with the original flat/Gouraud face lighting and the animated texture frames of the drawing object's ANIMATE
    state `anim` ({texture name: {'frame', ...}}, cmd_animate's key: upper case, 8 characters): a record starts at frame 0 and only
    ANIMATE steps it (1168:055e), so a texture without state shows frame 0.
    A ramp face's colour is ramp_start + ((offset * I + 128) >> 8) (FUN_1150_1eb2), with I from the global light
    1290:cb84 (FUN_1158_09d7/0ade). That light keeps its constructor state for the whole game (FUN_1158_067f: point light,
    zero position and strength, ambient 0; its setters have no callers, confirmed in DOSBox-X memory), so I = 0 for every
    face and vertex: flat and Gouraud ramp faces draw at their ramp start. Other untextured colours are kept, and
    textured faces keep their source indices, as the original textured rasterizer copies each texel directly.
    V and eye are unused; the signature is kept for callers."""
    textures = list(mesh.textures)
    for ti, frames in getattr(mesh, 'anim', {}).items():       # animated textures: pick the frame for this tick
        name, tw, th, _ = textures[ti]
        st = (anim or {}).get(name.upper()[:8])
        textures[ti] = (name, tw, th, frames[min(max(st['frame'], 0), len(frames) - 1) if st else 0])
    ntex = len(mesh.textures)
    polys = []
    for poly in mesh.polys:
        kind, color, vi, t, uv = poly
        ramp = None if uv and t is not None and 0 <= t < ntex else \
            next((r for r in RAMPS if r[0] <= color <= r[0] + r[1]), None)
        polys.append(poly if ramp is None else (kind, ramp[0], vi, t, uv))
    m = copy.copy(mesh)
    m.polys, m.textures = polys, textures
    return m


class Assets:
    """Mesh, skeleton, skin and motions of one figure type (BODY/<type>.BED)."""

    def __init__(self, ftype):
        b = bed.read_bed(os.path.join(BODY, ftype + '.BED'))
        self.type = ftype
        self.mesh = Mesh(b['REAL'][0])
        self.skel = salsa.load_skel(b['SKEL'][0])
        self.links = salsa.load_links(b['SKIN'][0])
        self.motions, self.motion_info = {}, {}
        for f in b.get('LIST', b['MOTN']):
            if os.path.exists(f):
                for k, v in salsa.load_motions(f).items():
                    self.motions.setdefault(k.upper(), v)       # first file wins on duplicates
                for k, v in salsa.load_motion_headers(f).items():
                    self.motion_info.setdefault(k.upper(), v)
        col = os.path.join(BODY, ftype + '.COL')       # collision cubes, same base name as the BED
        self.col = salsa.load_col(col) if os.path.exists(col) else []
        self._cache = {}
        self.foot_offset = salsa.foot_depth(self.skel, cos_table())    # F, model+0x88 (whole units)

    def pose(self, frames, i):
        """Posed local vertices (root x,y zeroed, root z kept), cached per (motion, frame)."""
        key = (id(frames), i)
        if key not in self._cache:
            p, r, l = frames[i]
            self._cache[key] = np.array(salsa.pose_vertices(self.mesh.verts, self.links, self.skel, ((0, 0, p[2]), r, l)))
        return self._cache[key]

    def interpolated_pose(self, frames, i, alpha):
        """Pose between adjacent motion frames.  The engine blends limb angles and root z; root x/y stay simulation-only."""
        if alpha <= 0 or i + 1 >= len(frames):
            return self.pose(frames, i)
        p0, r0, l0 = frames[i]
        p1, _, l1 = frames[i + 1]
        limbs = [tuple(math.trunc(a + (b - a) * alpha) for a, b in zip(a0, a1)) for a0, a1 in zip(l0, l1)]
        frame = ((0, 0, math.trunc(p0[2] + (p1[2] - p0[2]) * alpha)), r0, limbs)
        return np.array(salsa.pose_vertices(self.mesh.verts, self.links, self.skel, frame))


class Figure:
    def __init__(self, name, ftype, assets, pos=None, heading=0.0):
        self.name, self.type, self.assets = name, ftype, assets
        self.pos = None if pos is None else np.array(pos, float)      # None = not placed yet
        self.heading = float(heading)
        self.motion, self.frames, self.idx, self.loop, self.phase = None, None, 0, True, 0.0
        self.go = None            # {'target': xy array, 'kind': 'WALK'|'RUN', 'motion': name}
        self.after_go = None      # (motion, loop) requested while walking
        self.task_name = None     # +0x15f: the name of the scripted MOTION that is still running (set by cmd_motion, cleared by the next motion)
        self.view_cams = None     # cameras this figure may be seen in; None = always visible (PLAYER)
        self.ai_type, self.ai_proc = None, None     # SETAI <type> -> block <type>_AI; its running process
        # FUN_1088_31fb only enables/resumes AI.  FUN_1088_3371 creates the
        # process later, from the visible figure update.
        self.enemy = None         # DEFINEENEMY target name (PLAYER = the player keyword)
        self.combat, self.spar = False, False
        self.invulnerable = False   # flag bit 0x08 at +0x34 (INVULNERABLE ON/OFF, ISINVULNERABLE)
        self.hidden = False         # flag bit 0x04 at +0x34 (ISHIDDEN; the engine's hide method sets it, no script command does)
        self.exploded = False       # EXPLODE hid the figure (effects.py): stays hidden, whatever the viewing cameras say
        self.hit_done = False     # this play of an attack motion already did its hit check
        self.hover_motion = False  # the current motion started with gravity off (its final root z is then carried, see set_motion)
        self.mot_id = 0           # increments on every motion start (lets MOTION waits notice a replacement)
        self.finished = False     # the current non-looping motion has played its last frame
        self.frozen = False       # holding the current frame until the next MOTION / SNAPTOPOSE (STOPMOTION, SNAPTOPOSE ... FREEZE)
        self.no_idle = False      # MOTION ... FREEZE (10d0:5e8b clears only the idle-fallback bit 0x80 of +0x34): the motion plays to its end and
                                  # its last pose is held, with no STAND / ATK_STAND fallback (1088:508d, 1088:4167); every accepted set_motion clears it
        self.rises = False        # the current motion's header flag 2 (+0x1e8, 1098.c:274): its root z is committed to pos.z at each wrap and at
                                  # its end (commit_rise); settle / set_pos do not stand the figure on its support meanwhile
        self.stopped = False      # the hold comes from STOPMOTION / a hit's motion cancel, not from FREEZE: the player's keys still work
        self.unwaited = False     # the current motion is a script's MOTION ... CONTINUE / FREEZE that no process waits on
        self.held_pose = None     # (frames, frame, blend) drawn until the next update after an end-of-update idle (World.posed)
        self.idle_request = False # stopped by FUN_1098_0789 with the idle-fallback bit set: the update's end requests the idle (World.stop_figure)
        self.pending_idle = None  # (motion, tick) of an idle requested during a scheduler walk: FUN_1098_0745 -> 1098:0e49(fig, name, 1, 0) makes
                                  # the motion task without running it, and its first run (10e0:0055) starts the motion: in the next walk (World.start_pending_idles)
        self.manual_control = False  # true after the input API has put this figure into a player-control motion
        self.gravity = True          # flag bit 0x01 at +0x34 (GRAVITY CURFIG ON/OFF, ISGRAVITYON). CREATEFIGURE: on unless the
                                     # type's HAS_GRAVITY property is 0 (FUN_1088_22ba); level figures: the FIGR flags byte
        self.bouncy = bool(figure_prop(name, ftype, 'IS_BOUNCY', 0))  # flag bit 0x10 (+0x34); level figures override it below
        self.vz = 0                  # z velocity (+0xce), world units per 30 fps frame
        self.vx, self.vy = 0, 0      # x/y velocity (+0xc6/+0xca): persistent (no friction); the frame move adds velocity_step() of
                                     # (vx, vy, vz) to the root motion. Written by knockback, SETVELOCITY, LEAP and the bounce
        self.step = [0, 0, 0]        # +0xd2/+0xd6/+0xda: this frame's step (the velocity at 30 fps); the mover rescales it on a blocked step
        self.elasticity = int(figure_prop(name, ftype, 'ELASTICITY', 200))   # +0xde, 8.8 loss fraction per bounce (FUN_1088_22ba; 256 = all)
        self.root_start = False          # the current motion's frame 0 root is not applied yet (World.apply_first_root)
        self.applied_root_z = 0          # the previous motion's root z, which R (model+0xa6) still holds while root_start is set
        self.root_delta = np.zeros(2)    # root motion of this frame's motion steps, applied by the frame move (World.frame_move)
        self.root_moved = False
        self.arriving = False        # a GO stride reached its target; the arrival is applied when the frame move completes
        self.prev_pos = self.last_good = None   # +0xba (frame start position) and +0xe2 (last position the mover accepted)
        self.raw_setpos = False      # +0x1e8: set while FUN_10a0_2158 runs SetPos, which then skips the gravity floor snap
        self.engine_request = False  # the current motion was requested by the engine (lower case in the original: "walk")
        self.hold = 0                # +0x229, the AI-off counter (AI OFF, a fall, the die method FUN_1088_3196): script process and player input suspended
        self.auto_turn_count = 0     # +0x1e1, FUN_1088_3419's call counter
        self.confront = None         # the running turn_to_enemy task of a CONFRONTENEMY (FUN_10e8_0000)
        self.falling = False         # +0x1e9, set by FUN_10a0_0072
        self.stored_hull = None      # (tick, lo, hi): the stale fig+0x65 hull SETFLOOROFPHYS leaves behind (floors.py)
        self.teeter = False          # +0x146, set while a whoah probe failed (FUN_10a0_009b)
        self.z_cap = 0               # +0x14e: FLOATATHEIGHT <waypoint> MAXIMUM, a z limit above the area anchor's base z (0 = none); see World.mover
        self.area = None             # PHYS index selected by FUN_1138_1a93; retained when no candidate covers this figure
        self.in_area = False         # compatibility flag for the selected-area state (+0x35)
        self.in_trig = None          # InTrig (+0x191): one byte per level IMAG, allocated zeroed on first use (FUN_1088_536a)
        self.carrier = None          # +0x2c: key (World.items) of the missile this figure is attached to by FIRE ... CARRY; see missiles.py
        self.anim = {}               # ANIMATE state per animated texture, see mechanics.py
        self.foot_override = None    # +0x225: F set by FLOATATHEIGHT <waypoint> (None = the type's F); see World.foot
        self.limb_holder = None      # +0x2c/+0x30: (holder figure name, limb) GRABCRITTER attached this figure to; see mechanics.py
        self.no_collide = False      # flag bit 0x02 at +0x34: COLLISIONS CURFIG OFF sets it, ON clears it (FUN_10d0_1aa4); while
                                     # set, FUN_1088_39ef neither stands the figure on its support nor lands it, and the mover
                                     # (FUN_10a0_22e1) skips the PHYS test. All 49 FIGR figures start with it clear; created
                                     # figures and the player too (ASSUMPTION: CREATEFIGURE sets no flags bit 0x02)
        # MY_SPEED (FIGURES.SCP, read when the figure is made): frame duration = MY_SPEED x the motion's frame time
        self.speed = int(figure_prop(name, ftype, 'MY_SPEED', DEFAULT_SPEED))
        self.recoil_id = None        # mot_id of the recoil a hit started (FUN_1090_09b9 sets ~3 = 1 for its duration)
        self.decals = {}             # APPLY state: {texture name: (mode, picture frame, picture prefix)}, see World.apply_decal
        self.avoid = []              # ADDAVOIDANCEPOINT [(object name, radius cm)], at most MAX_AVOID
        self.duration, self.dur_id = None, -1   # the current motion's frame duration (model+0x102), set at its start
        self.combo_name, self.combo_count = '', 0   # the player's repeated attack (+0x12a, +0x13e)
        self.set_motion(STAND, True, quiet=True)

    def frame_duration(self):
        """FUN_1098_0088: model+0x102 = MY_SPEED x motion+0x52 (in 1/256 ticks of the 60 Hz clock), adjusted when the
        motion starts (World.motion_duration); before that, the plain product."""
        if self.duration is not None and self.dur_id == self.mot_id:
            return self.duration
        return self.speed * self.assets.motion_info[self.motion][0]

    def turning(self):
        """Motion flag +0x24 bit 0x01: the root limb's yaw is added to the heading (FUN_10a0_1c83)."""
        return self.frames is not None and bool(self.assets.motion_info[self.motion][1] & 1)

    def bake_turn(self):
        """FUN_10a0_1c83: rotate the figure by the root limb's yaw since the motion's first frame (256 units per turn,
        d * 45 / 32 degrees; a negative yaw turns right)."""
        if self.turning():
            self.heading -= (self.frames[self.idx][2][0][2] - self.frames[0][2][0][2]) * 45 / 32

    @property
    def ai_enabled(self):
        return self.hold == 0

    def stop_motion(self):
        """STOPMOTION (10d0:77d6 -> FUN_1098_0789(fig, 1, 1)): end the motion with the current pose held (FUN_1040_0c07
        copies each limb's target angles into its current ones). A turning motion's yaw goes into the heading
        (FUN_10a0_1c83), so the held pose keeps frame 0's root yaw; the figure's motion and GO tasks (0x108/0x109,
        FUN_1088_3229) end, and ISMYMOTION no longer matches. The figure is still updated (pushed, grounded)."""
        self.pending_idle = None            # FUN_1088_3229 ends the motion task before its first run: the idle never starts
        if self.frames is None:
            return
        held = self.frames[min(self.idx, len(self.frames) - 1)]
        if self.turning():
            self.bake_turn()
            limbs = list(held[2])
            limbs[0] = tuple(limbs[0][:2]) + (self.frames[0][2][0][2],) + tuple(limbs[0][3:])
            held = (held[0], held[1], limbs)
        if self.rises and self.pos is not None:
            # Stopping a rising motion mid-cycle commits the current root z (UPLADDER's STOPMOTION at the ladder top keeps the height
            # climbed); the held pose then carries no root z of its own. FUN_1098_0789 clears +0x1e8 and R and sets the teeter (+0x146)
            self.pos[2] += held[0][2]
            held = ((held[0][0], held[0][1], 0),) + tuple(held[1:])
            self.rises, self.teeter = False, True
        self.frames, self.idx, self.loop, self.phase = [held], 0, False, 0.0
        self.frozen, self.finished, self.go = True, True, None
        self.stopped = True
        self.drop_deferred()
        self.mot_id += 1

    def drop_deferred(self):
        """Abandon a MOTION that was deferred behind a GO (`after_go`) because the GO is cancelled (STOPMOTION, a hit, a new GO or pose):
        its blocked caller resumes as if the motion had been replaced (the token's id can never equal a motion id). ASSUMPTION: without
        this the caller waits for an arrival that no longer comes (CAYNAN_AI hung in `MOTION ATK_H8` after the first punch took away
        its pacing GO)."""
        if self.after_go is not None:
            tok = self.after_go[2]
            if tok is not None and tok['id'] is None:
                tok['id'] = -1
            self.after_go = None

    def motion_gate_refuses(self, name):
        """FUN_1098_12bd (vtable +0x8c), the scripted MOTION's gate: while a scripted motion task and its name (+0x15f) still exist (the
        motion has not finished) a request is refused when that name starts with RECOIL / DIE / SUPER_REC or equals the requested name
        (it is not restarted).  Refused = a non-blocking zero handle."""
        if self.task_name is None or self.finished:
            return False
        return self.task_name.startswith(('RECOIL', 'DIE', 'SUPER_REC')) or self.task_name == name

    def set_motion(self, name, loop, quiet=False, freeze=False, engine=False, no_idle=False):
        fr = self.assets.motions.get(str(name).upper())
        if fr is None:
            return False
        if self.motion == 'DIE' and not self.finished:
            # FUN_1098_0394 tests only the current motion's name: no motion change while DIE is current, SNAP_TO or not (a finished
            # motion is no longer current: 1088:2035 -> 0789 clears it at the last frame, so GET_UP_FORWARD and the rest work then).
            # REVIVELEX (AWAKEN.scr) runs after the nurse's blocking `MOTION DIE`, which resumes once DIE has finished
            return False
        self.bake_turn()                    # FUN_1098_0789 (motion stop/change) keeps a turning motion's yaw
        if self.frames is not None and not self.root_start:
            self.applied_root_z = int(self.frames[min(self.idx, len(self.frames) - 1)][0][2])   # model+0xa6 keeps it until the new motion's first update
        if self.rises and self.finished and self.pos is not None and self.frames is not None:
            # A rising motion that played out commits its last root z (INFERRED for once-motions: design intent and the script
            # calibration, MANTLE_6 / ON_LADDER end on the ledge / rung); the loop wrap commits in World.advance. Done when the
            # next motion starts, so the held last pose and the hull keep the height until then.
            self.pos[2] += self.frames[-1][0][2]
        if self.rises:
            self.teeter = True              # FUN_1098_0789: ending a rising motion marks the teeter, so the landing plays no whoah until all the probes are fine
        if not self.gravity and self.finished and self.pos is not None and self.frames is not None \
                and not self.rises and self.hover_motion and self.frames[-1][0][2] >= ROOT_Z_KEEP_MIN:
            # A finished motion's root z (OUT_OF_BED +742, NURSEBOT ACTIVATE +1700) stays in the figure's height when the next motion
            # starts (FUN_1088_0581 re-bases the root frame per motion): hovering FIRSTBOT ends at BOTLOC z + 1722 = native -4534.
            # ASSUMPTION: only large offsets are kept (small ones are absorbed by the engine's float/ground code), and only without
            # gravity (a grounded figure's height comes from its support). ASSUMPTION: only when the finished motion also started
            # without gravity (hover_motion): under gravity its root z lived in the pose (z = support + F), so GUARD1, switched to
            # gravity off while it lies in WAKE_UP (root z -1780), does not sink 1780 units into the floor when it starts to fight.
            # INFERRED: only a lift. Live, GUARD1 with gravity off goes WAKE_UP (z base - 1780), GET_UP (z back to base + its root z), atk_stand (base + its root z), so -1780 and GET_UP's -360 do not stay.
            self.pos[2] += self.frames[-1][0][2]
        self.frozen, self.finished, self.hit_done = freeze, False, False
        self.no_idle = no_idle
        self.task_name = None               # +0x15f: a new motion ends the scripted one's name (cmd_motion sets it again after the request)
        self.pending_idle = None            # a newer request supersedes an idle whose task has not run yet (INFERRED)
        self.stopped = False
        self.unwaited = False               # a script MOTION ... CONTINUE / FREEZE nobody waits on (cmd_motion): yields to keys
        self.idle_request = False
        self.hover_motion = not self.gravity
        self.engine_request = engine
        self.mot_id += 1
        self.motion, self.frames, self.idx, self.loop, self.phase = str(name).upper(), fr, 0, loop, 0.0
        self.root_start = True
        self.rises = bool(self.assets.motion_info[self.motion][1] & 2)
        return True

    @property
    def collisions(self):
        """The mover (FUN_10a0_22e1) and the figure push (FUN_1088_3629) run when flag 0x02 is CLEAR."""
        return not self.no_collide

    def forward(self):
        h = math.radians(self.heading)
        return np.array([-math.sin(h), -math.cos(h)])

    def is_moving(self):
        return self.go is not None


class Item:
    """The small item record needed for script inventory predicates.

    The full item engine is still unimplemented.  Scripts need an item's type, its
    individual name, owner, and attachment/inventory slot before they can decide
    whether an attack is available.
    """
    missile = False                 # True for a Missile (missiles.py): never a floor item to pick up

    def __init__(self, name, item_type, owner=None, slot=None):
        self.name = name            # the instance name (+0xf7); several items may share it (CREATEITEM names it after the type)
        self.key = name             # the unique key in World.items (ItemsMixin.add_item); script CURITEM, objects and menus hold this
        self.type = item_type
        self.owner = owner
        self.slot = slot
        self.pos = None             # floor items: position and orientation rows (items.py); None while carried or never placed
        self.matrix = None
        self.hidden = False         # flag bit 0x04 of the ITEM record: not drawn
        self.vel, self.step = [0, 0, 0], [0, 0, 0]      # persistent velocity (+0xc6..) and the last move's step (+0xd2..), s32 per tick
        self.extent = [0, 0, 0]     # EXTENT half sizes in units
        self.no_collide = self.bouncy = self.reflective = False     # flag bits 0x02, 0x10, 0x20
        self.gravity = True         # flag bit 0x01
        self.elasticity = 200
        self.anim = {}              # ANIMATE state per animated texture, see mechanics.py
        self.physics_loaded = False  # the type's HAS_GRAVITY / IS_BOUNCY / ... properties are read once, when the item first moves (effects.py)

    vx = property(lambda self: self.vel[0], lambda self, v: self.vel.__setitem__(0, v))     # so VELOCITYX / LEAP / SETVELOCITY treat
    vy = property(lambda self: self.vel[1], lambda self, v: self.vel.__setitem__(1, v))     # figures and items alike
    vz = property(lambda self: self.vel[2], lambda self, v: self.vel.__setitem__(2, v))


class Missile(Item):
    """A FIRE / MAKEMISSILE shot (missiles.py): the engine's missile task and its figure in one record. It lives in World.items under a
    unique key, so CURITEM can name it in the hit scripts; `type` is the missile type (the script block <TYPE> and ITEMS/<TYPE>.IFF)."""
    missile = True

    def __init__(self, name, missile_type):
        super().__init__(name, missile_type)
        self.pos = np.zeros(3)         # integer world units; velocity / step are s32 per tick (+0xc6.. / +0xd2..)
        self.set_rows([[256, 0, 0], [0, 256, 0], [0, 0, 256]])
        self.gravity = False
        self.dist = 0                  # +0x48: remaining range, units
        self.spin = (0, 0, 0)          # +0x4c..: degrees per tick about X, Y, Z
        self.owner_fig = None          # +0x44 (CURFIG for MAKEMISSILE, none for FIRE)
        self.handle = 0                # the VM handle (+0x38)
        self.sound = 0                 # the looped _<TYPE>_TRAVEL handle (+0x40)
        self.carried = None            # the object FIRE ... CARRY attached
        self.hit = None                # +0x135: the figure the last move overlapped
        self.dead = False

    def set_rows(self, rows):
        """The orientation (+0x110) in 24.8; ``matrix`` is the drawing form (rows are the local axes, row 1 backward)."""
        self.rows = rows
        self.matrix = np.array(rows, float) / 256


def declared_locals(block, values):
    """The local count a saved process record carries (object+0x70): the block's LOCALVAR declarations, the count the original
    allocates and copies CALL arguments into (10c0:3968, definition +0x23; both original saves agree), and at least up to the
    last nonzero local the port holds (the port copies every CALL argument, so a value past the declared ones would be lost)."""
    n = sum(1 for st in parse.walk(block.body) if st.op == 'LOCALVAR')
    used = max((i + 1 for i, v in enumerate(values) if v), default=0)
    return min(max(n, used), 10)


class World(items_mod.ItemsMixin, missiles_mod.MissilesMixin, effects_mod.EffectsMixin, floors_mod.FloorsMixin, audio_mod.AudioMixin,
            mechanics_mod.MechanicsMixin, presentation_mod.PresentationMixin, show_mod.ShowMixin, vmmod.RecordingEngine):
    def __init__(self, level, camera=None, state_dir=GAMEDAT):
        super().__init__()
        self.state_dir = state_dir
        self.assets, self.figures, self.items = {}, {}, {}
        self.fragments = []                    # EXPLODE's shrapnel (effects.py Fragment); a level change drops it
        self.dead_figures = {}                 # KILLed figure objects by name, kept until the level changes: EXPLODE reads the dying pose from one
        self.killed_figures = set()            # removed FIGR names; blocks lazy recreation from the current level's definitions
        self.player_name = None                # figure flagged by `CREATEFIGURE <type> [name] PLAYER` (or lazily 'PLAYER')
        self.combo_timer = 0                   # [2958]: clock when an ATK_F9 attack started the repeat-count reset timer
        self.camera = None                     # set by CAMERA / automatic switching
        self.shown_picture = None              # CAMERA SHOW <cam> (10d0:115c): the full-screen picture camera, until the next switch or level load
        self.default_camera = camera.upper() if camera else None
        self.auto_camera = AUTO_CAMERA
        self.script_auto = True                # 1290:63da: 1 at boot / new game (1128.c:524, 646); CAMERA <cam> / SHOW / AT set 0, CAMERA UNLOCK 1; a level load keeps it
        self.disabled = set()                  # ASSUMPTION: CAMERAAUTOACTIVATE <cam> OFF/ON sets/clears the disabled bit (0x08)
        self.follow = FOLLOW_DEFAULT           # ASSUMPTION: CAMERAFOLLOW <obj> sets the followed figure
        self.candidate = None                  # winner of the previous frame (debounce)
        self.selected = False                  # an automatic selection has happened since load
        self.camera_changes = []               # (tick, from, to, reason)
        self.level_loads = []                  # (tick, level, arrival, resolved position or None)
        self.hits = []                         # (tick, attacker, target, motion, dispatched block/label)
        self.events = []                       # (tick, block fired by the engine)
        self.loaded_cam = None                 # [63e9]: the camera whose events ran last; a level load keeps it (1130:0048 clears only [63e1] / [63e5])
        self.loaded_room = None                # [63ed]: its room, the camera name's first 3 characters
        self.switching_to = None               # [63e1] while 1130:0114 runs the events ([63ce], World.camera, changes after them)
        self.sound_log = []                    # (tick, sample index, name, volume, pitch, handle) per SOUND / SUBTITLE
        self.sound_stops = []                  # (tick, handle) for STOPSOUND / STOPALLSOUNDS ending a sound handle
        self.sound_handles = {}                # handle -> sample index of every sound handle issued
        self.sound_loops = set()               # handles of looped samples (what STOPAMBIENT releases)
        self.sound_releases = []               # (tick, handle) for STOPAMBIENT: the loop plays on to the end of its sample
        self.sound_drops = []                  # (tick, sample index, name) for sounds dropped with all 8 voices busy
        self.sound_volumes = []                # (tick, handle, volume) for positional sounds: start value + every change
        self.sound_pos = {}                    # handle -> (figure key, last volume) of live positional sounds
        self.sound_rates = []                  # (tick, handle, rate) for SETPITCH / ADDTOPITCH / the pitch ramp: the playback rate in Hz from then on
        self.voice_state = {}                  # handle -> audio.Voice (level, rate, position model) of every sound handle issued
        self.sound_overrides = {}              # REPLACESOUND: lower-case sound name -> sample id (audio.py)
        self.room_ambient = self.camera_ambient = 0    # [63f6] / [63f2]: the room / camera `_%s_AMBIENT` loop handles (0 = none)
        self.ambient_pending = False           # [63f1]: a camera switch awaits its loops (update_ambients)
        self.ambient_bindings = {}             # camera name -> audio.Binding (camera+0x7e, the `_<CAM>_VOLUME` tracker)
        self.subtitle_log = []                 # (tick, handle, colour, text, end tick); the end moves up when replaced
        self.subtitle_voice = None             # the live subtitle's voice handle (+0x44, stopped by 10e8:08a4)
        self.caption_handles = set()           # CAPTION's entries in subtitle_log, which ignore the subtitles switch
        self.cur_subtitle = None               # (handle, index into subtitle_log) of the live subtitle object
        self.voices = [None] * VOICES          # per voice slot: (handle, priority) or None (FUN_1028_18f4)
        self.music_log = []                    # (tick, MUSIC argument; -1 = stop)
        self.current_music = None
        self.dialog_song = -1                  # [4e30]: the song playing when a dialog (not the credits page) last opened; -1 after a load (FUN_1100_09cb, 1148:0473)
        self.settings = settings_mod.Settings()    # persisted options (INSTALL.OPT values; play.py loads the user's file)
        self.gamma = self.settings.gamma       # gamma in force (FUN_1100_0e6f); a presentation step, see settings.gamma_lut
        self.sfx_log = [(0, self.settings.sound)]   # (tick, effect level 0..100): in force for sounds starting at or after the tick
        self.music_initial = self.settings.music    # music level at tick 0; music_vol_log holds the later changes
        self.music_vol_log = []                # (tick, music level 0..100)
        self.warnings = []
        self.unmodelled = []                   # "NAME: unmodelled statement|function (ignored)" for every engine call World.call drops
                                               # (kept apart from `warnings`: the opening scripts alone hit about twenty such names)
        self.monitor = None                    # running monitor (monitor.Monitor) or None; MON_START replaces it
        self._unknown_viewports = set()        # remote monitor cameras with no ROOMS art, warned once
        self._remote_cameras = {}              # camera name -> (GAMEDAT path, CAMR object), including misses
        self.monitor_codes = []                # MON_CODE / MON_SIMULATE / MON_DESTROYOPTIONS trace
        self.options = None                    # native-style dialog, separate from script monitors
        self.option_actions = []               # (tick, selected action)
        self.speed_factor = 0                  # [66c6]: INCVIRTUALSECONDS 0 raises it (timer rate and persistence not ported)
        self.forcing_reload = False            # FUN_1100_06d4: a forced reload is running; a credits dialog then does not pause
        self.keyboard_captured = False         # [6530]: between CAPTUREKEYBOARD and RELEASEKEYBOARD (the block is not run, keys not routed to it)
        self.save_busy = False                 # FUN_1140_0fc0: a save or load is running (the ports save synchronously: never set)
        self.exit_requested = False
        self.new_game_requested = False       # the dialog's Load > New > Yes: the host starts a new game
        self.saves_dir = SAVES
        self.pending_load = None               # (world, vm) from a confirmed load dialog; the caller's loop swaps to it
        self.log_entries = {}                  # named ADDLOGENTRY stores, in award order; persists across LOADLEVEL
        self.log_entry_times = {}              # VM ticks parallel to log_entries; used to format %time% at award time
        self.start_tick = 0                     # StartTick config is a 60-Hz engine-clock offset (default recovered from 10f0)
        self.start_date = 0                     # StartDate config, expressed as the displayed day number
        self.rng = random.Random(0)            # deterministic RANDOM
        self.player_input = {'forward': 0, 'turn': 0, 'run': False, 'attack': False}
        self.keys_captured = []                # keys pressed while captured: the key state table (1290:7bbe, set from the keyboard interrupt, 11d8:1561) has them, the normal handler does not
        self.keys_held, self.key_mods, self.key_pending = [], 0, []     # key_down/key_up state: held PC scan codes in press order
        self.input_was_active = False          # the player's input was active in the previous apply_player_input (rising edge)
        self.pick_targets = {}                 # figure name -> item name stored by Enter for the grab event (figure +0x199)
        self.cue_seen = {}                     # figure name -> (motion id, list position, frame) of the frame event walk (items.event_walk)
        self.key_log = []                      # (tick, action, detail) of key actions that are only logged (gamma/version) or used
        self.level_items = {}                  # level -> [(Item, locals)] kept with a level the player left (items.py stash_level_items)
        self.level_figures = {}                # level -> {name: Figure} kept with a level the player left (stash_level_figures)
        self.load_objects(level)

    _boxes = None
    _areas = None                          # (boxes, area_candidates) cached with `_boxes`

    def load_objects(self, level, travelling=(), carry_items=()):
        """(Re)load the object file of `level` from state_dir: waypoints, cameras, placed figures.
        PLAYER (and carried figures, re-added by the caller) survive; other figures are dropped.  The old level's items stay with
        it (stash_level_items); the player's and the `travelling` figures' come along."""
        self.stash_level_items(travelling, carry_items)
        self.stash_level_figures(travelling)
        self.level = level.upper()
        self.killed_figures.clear()
        self.fragments, self.dead_figures = [], {}
        self.level_path = os.path.join(self.state_dir, self.level + '.IFF')
        self.objs = load_level_objs(self.level_path)
        self.phys = [
            {'name': o['name'].upper(), 'lo': np.minimum(o['pos'], o['pos2']),
             'hi': np.maximum(o['pos'], o['pos2']), 'raw': o['raw']}
            for o in self.objs if o['tag'] == 'PHYS'
        ]
        self._boxes = self._areas = None       # a LOADLEVEL inside step() must not keep ranking the old level's PHYS for the rest of the frame
        # IMAG trigger volumes in level order (the InTrig index): box, flag bit 0x01 (+0x34: fire on entry only, else every
        # frame inside) and the camera name at record +45 (+0x41) that CAM_xxxx triggers force
        self.triggers = [
            {'name': o['name'].upper(), 'lo': [int(v) for v in np.minimum(o['pos'], o['pos2'])],
             'hi': [int(v) for v in np.maximum(o['pos'], o['pos2'])], 'once': bool(o['raw'][21] & 1),
             'camera': o['raw'][45:54].split(b'\0')[0].decode('latin1').upper()}
            for o in self.objs if o['tag'] == 'IMAG'
        ]
        self._area_triggers = {}
        for index in range(len(self.phys)):    # the area lists are built with the level (ASSUMPTION): a moved anchor (ELV in SETFLOOROFPHYS) keeps its own
            self.area_triggers(index)
        self.forced_camera = None              # [63d6], set by a trigger (FUN_1130_0f85) and applied by the next camera frame
        self.cameras = {o['name'].upper(): o for o in self.objs if o['tag'] == 'CAMR'}
        self.waypoints = {}                    # WAYP objects by name, first of a name wins (the list at 1290:1cdd)
        for o in self.objs:
            if o['tag'] == 'WAYP':
                self.waypoints.setdefault(o['name'].upper(), o['pos'])
        self.points = {}                       # WAYP first, then every other named object
        for o in sorted(self.objs, key=lambda o: o['tag'] != 'WAYP'):
            self.points.setdefault(o['name'].upper(), o['pos'])
        self.fig_defs, self.record_locals = {}, {}
        self.fig_recs, self.rec_names = {}, None        # each FIGR record's decoded view by instance name, and the level's object ids for it
        for o in self.objs:
            if o['tag'] == 'FIGR':
                inst = o['raw'][33:42].split(b'\0')[0].decode('latin1').upper()
                self.fig_defs.setdefault(inst, (o['name'].upper(), o['pos'], figr_view_cams(o['raw']), o['raw'][21], figr_ai_name(o['raw']), figr_ai_off(o['raw'])))
                self.record_locals.setdefault(inst, list(struct.unpack_from('<10i', o['raw'], 106)))
                try:
                    self.fig_recs.setdefault(inst, levelmod.ObjRec('FIGR', o['raw']))
                except ValueError:
                    pass                           # a record the decoded layout does not fit keeps the port's defaults
        if self.fig_recs:
            import resume
            recs = []
            for o in self.objs:
                try:
                    rec = levelmod.ObjRec(o['tag'], o['raw']) if o['tag'] in levelmod.RECORD_TAGS else None
                except ValueError:
                    rec = None
                recs.append((o['tag'], o['name'], o['raw'], rec))
            self.rec_names = resume.Names(recs)
        self.figures = {k: v for k, v in self.figures.items() if k == self.player_name}
        for fig in self.figures.values():
            fig.area, fig.in_area, fig.in_trig = None, False, None
        self.camera, self.disabled, self.candidate, self.selected = None, set(), None, False
        # script_auto (1290:63da) is not reset: only a new game / boot, CAMERA UNLOCK (1) and CAMERA <cam> / SHOW / AT (0) write it
        self.ambient_bindings = {}             # the camera objects are rebuilt (1110:19cc)
        self._sprite_names = {}
        self.flat_objects = []                 # MAKEFLATOBJECT sprites (effects.py); a level change drops them
        self.load_floor_items()
        self.seed_object_locals()
        kept = self.level_figures.pop(self.level, None)
        if kept is not None:                       # a return: the figures come back from the level's IFF as the player left them; the killed
            self.figures.update(kept)              # and carried-off ones have no record, so the lazy figure() must not rebuild them
            self.killed_figures.update(n for n in self.fig_defs if n not in kept)
            return
        for inst in self.fig_defs:                 # the level loader builds every FIGR figure (1148:18d3), AI and all (FUN_1088_3371)
            self.figure(inst)

    def stash_level_figures(self, travelling=()):
        """A level change keeps the old level's figures with that level, as its items (stash_level_items): every object left in the list is
        written to the level's IFF (FUN_1148_1232) and read back on a return (FUN_1148_1386), the AI restarted from the record's name
        (FUN_1088_3371). KILLFIGURE destroyed its figure, so a killed one has no record; the player and the `travelling` figures are not
        left behind. What a record does not keep is reset (as resume.py `_figures`): the processes end with the level, a one-off motion
        with no task is held on its last pose, a dead body stays frozen on DIE's last pose."""
        if not getattr(self, 'level', None):
            return
        keep = {self.player_name, 'PLAYER'} | {str(n).upper() for n in travelling}
        stay = {}
        for key, fig in self.figures.items():
            if key in keep or fig.name in keep:
                continue
            fig.ai_proc, fig.go, fig.after_go, fig.confront, fig.area, fig.in_area = None, None, None, None, None, False
            fig.unwaited, fig.task_name, fig.idle_request, fig.held_pose = False, None, False, None
            if fig.frames is not None and fig.motion and not motion_loops(fig.assets, fig.motion):
                fig.loop, fig.idx, fig.finished = False, len(fig.frames) - 1, True
            if fig.motion == 'DIE' and self.vm is not None and self.vm.objects.get(self.object_key(key), [1])[0] <= 0 and fig.frames is not None:
                fig.loop, fig.idx, fig.finished = False, len(fig.frames) - 1, True
                fig.frozen = fig.stopped = fig.no_idle = True
            stay[key] = fig
        self.level_figures[self.level] = stay

    def seed_object_locals(self):
        """A level figure's script object locals `~0..~9` are its FIGR record's (figure +0x92; ~0 = hit points,
        ~5 = MAX HPS), unless the VM already holds that object."""
        if self.vm is not None:
            for inst, rec in self.record_locals.items():
                if inst not in self.vm.objects:
                    self.vm.objects[inst] = list(rec)

    def vm_attached(self):
        self.seed_object_locals()

    # ---- figures
    def asset(self, ftype):
        if ftype not in self.assets:
            self.assets[ftype] = Assets(ftype)
        return self.assets[ftype]

    def resolve(self, name):
        """Figure key for a script name: PLAYER is an argument keyword meaning the current player figure
        (the one flagged by CREATEFIGURE ... PLAYER), anything else is an instance name."""
        name = str(name).upper()
        return self.player_name if name == 'PLAYER' and self.player_name else name

    def player(self):
        return self.figures.get(self.player_name)

    def figure(self, name):
        """Figure by instance name (lazy). PLAYER = LEX (not in level data); None if unknown."""
        if not name:
            return None
        name = self.resolve(name)
        if name in self.killed_figures:
            return None
        if name not in self.figures:
            if name in self.fig_defs:
                ftype, pos, cams, flags, ai_name, ai_off = self.fig_defs[name]
                rec = self.fig_recs.get(name)
                self.figures[name] = Figure(name, ftype, self.asset(ftype), pos, rec.heading if rec is not None else 0.0)
                self.figures[name].ai_type = ai_name
                self.figures[name].hold = ai_off
                self.figures[name].hidden = bool(flags & 4)           # no hide event: the flag comes with the record (1130:050d only hides a shown figure)
                self.figures[name].view_cams = list(cams or [])
                self.figures[name].gravity = bool(flags & 1)          # the record's +0x34 flags (byte 21)
                self.figures[name].no_collide = bool(flags & 2)
                self.figures[name].bouncy = bool(flags & 0x10)
                if rec is not None:                                   # the level reader restores the rest of the record too (FUN_1148_0d46),
                    import resume                                     # on a first visit as on a return: motion, velocity, enemy, avoid list...
                    resume.apply_figure_record(self, self.figures[name], rec, self.rec_names, name)
            elif name == 'PLAYER' and self.player_name is None:     # backward compat: a LEX figure flagged as player
                self.player_name = name
                self.figures[name] = Figure(name, DEFAULT_TYPE_PLAYER, self.asset(DEFAULT_TYPE_PLAYER))
            else:
                return None
        return self.figures[name]

    def is_moving(self, fig):
        f = fig if isinstance(fig, Figure) else self.figure(fig)
        return bool(f and f.is_moving())

    def set_player_input(self, forward=0, turn=0, run=False, attack=False):
        """Set held player controls for the next world tick.

        `forward` and `turn` are -1, 0, or +1; positive turn is right.  `attack` is
        an edge, supplied true only on the tick that starts an attack.  The input is
        ignored until the player is placed, and while a script GO, AI, frozen pose, or
        scripted non-locomotion motion owns that figure.
        """
        self.player_input = {
            'forward': max(-1, min(1, int(forward))),
            'turn': max(-1, min(1, int(turn))),
            'run': bool(run),
            'attack': bool(attack),
        }

    def phys_state(self, phys):
        """Current PHYS state: scripts can override the final on-disk state through _<name>_SPACE."""
        key = '_' + phys['name'].lower() + '_space'
        if self.vm is not None and key in self.vm.globals:
            return int(self.vm.globals[key]) & 0xff
        return phys['raw'][-1]

    def figure_bounds(self, fig, pos=None):
        """A figure's collision box at ``pos``.

        Movement and grounding both use the figure hull built by
        FUN_10a0_0000/FUN_1070_08df: script EXTENT values use 20.48 units/cm,
        and its lower z face comes from the model's F-derived foot depth.
        """
        lo, hi = self.hull(fig, pos=pos)
        return np.asarray(lo, float), np.asarray(hi, float)

    def figure_blocked(self, fig, pos):
        """Whether a candidate figure hull hits its selected area's solid PHYS members.

        Recovered movement calls FUN_1058_1a1b after rebuilding the figure hull:
        FUN_1058_192f/FUN_1058_1a1b start with the fixed-point hull score, add
        state-1 overlap, subtract state-0 overlap, and ignore state 2.
        FUN_10a0_21b2 first raises a hull bottom lying below its support by no more
        than -R onto the support; FUN_10a0_22e1 then also blocks while the support
        is above the hull bottom (a step too high).
        """
        self.select_area(fig, pos)
        lo, hi, sup = self.query_hull(fig, pos)
        area = self.area_members(fig.area)
        if self.collision_score(np.array(lo), np.array(hi), self._phys_boxes() if area is None else area) > 0:
            return True
        return sup > lo[2]

    def query_hull(self, fig, pos=None):
        """The hull FUN_10a0_21b2 stores at fig+0x65 -> (lo, hi, support): the figure hull, its bottom raised onto the support
        when it lies below it by no more than -R."""
        lo, hi = (list(v) for v in self.hull(fig, pos=pos))
        sup = self.support(fig, lo, hi, self.area_of(fig))        # FUN_10a0_21b2 passes fig+0x35 (10a0:221c..2235)
        if sup + self.root_z(fig) <= lo[2] < sup < hi[2]:
            lo[2] = sup
        return lo, hi, sup

    def null_area_blocked(self, lo, hi):
        """FUN_1058_192f when no PHYS area is selected."""
        return self.collision_score(lo, hi, self._phys_boxes()) > 0

    @staticmethod
    def collision_score(lo, hi, boxes):
        """Signed 32-bit fixed-point collision score shared by FUN_1058_192f and 1a1b."""
        score = collision_volume(np.asarray(hi, int) - np.asarray(lo, int))
        for _, state, plo, phi in boxes:
            overlap = np.minimum(hi, phi) - np.maximum(lo, plo)
            if np.all(overlap > 0):
                volume = collision_volume(overlap)
                score = s32(score + volume if state == 1 else score - volume if state == 0 else score)
        return score

    def figure_move(self, fig, delta, push=True):
        """Move a figure by ``delta`` (x, y or x, y, z) through the engine mover and its collision response, returning whether
        the move completed (False: blocked or stopped by a trigger)."""
        target = np.array(fig.pos, float)
        target[:len(delta)] += delta
        if push:
            target = self.push_target(fig, target)       # FUN_1088_3629 runs whatever the collisions flag
        return self.move_and_respond(fig, target)

    def move_and_respond(self, fig, target):
        """FUN_1088_39ef's mover call and what follows it: FUN_10a0_22e1 to ``target``, then FUN_10a0_0ead (vtable +0x5c) when the
        hull collides or the support is above its bottom where the mover left the figure. A bouncy figure rebounds (bounce),
        any other takes collision_response (which zeroes the velocity)."""
        start = np.array(fig.pos, float)
        completed = self.mover(fig, target)
        if fig.collisions and self.figure_blocked(fig, fig.pos):
            if fig.bouncy:
                self.bounce_collision(fig, start)
            else:
                self.collision_response(fig, start, fig.pos.copy(), fig.last_good.copy())      # sets fig.pos itself
            return False
        return completed

    def mover(self, fig, target):
        """FUN_10a0_22e1: move to ``target`` (x, y, z) in steps, True when the whole move completed unobstructed.
        +0xe2 (last good) := the position at entry, before the delta is read. A delta with any axis at or over the local hull
        span is cut into n = |d| / smallest span steps (3D length, z included); each step rebuilds the hull, and a blocked one
        leaves the figure on that step (and rescales the step by trunc(step * i / n)); a trigger stop at a passing step leaves it
        there too. Otherwise the figure goes to the target and the final check may fail there (it stays AT the target, last good
        unchanged). Collisions off skip every check. First the +0x14e z cap (FLOATATHEIGHT ... MAXIMUM): with an area (+0x35) and a
        non-zero cap the target z is limited to the area anchor's base z (PHYS +0x13, the box bottom) + cap. NOT PORTED: the
        attached branch (+0x2c)."""
        start = np.array(fig.pos, float)
        target = np.array(target, float)
        if fig.z_cap and fig.area is not None:
            target[2] = min(target[2], s32(int(self.phys[fig.area]['lo'][2]) + fig.z_cap))
        fig.last_good = start.copy()
        if fig.collisions:
            d = [int(v) for v in target - start]
            lo, hi = self.hull(fig, pos=start)
            spans = [hi[k] - lo[k] for k in range(3)]        # the local hull spans +0x51/55/59
            if not all(abs(d[k]) < spans[k] for k in range(3)):
                n = move_steps(d, min(spans))
                inc = np.array([fix_div(d[k], n << 8) for k in range(3)], float) if n > 0 else None
                for i in range(1, n + 1):
                    candidate = start + inc * i
                    if self.figure_blocked(fig, candidate):
                        fig.pos = candidate
                        fig.step = scale_step(fig.step, i, n)
                        return False
                    fig.last_good = candidate.copy()
                    if self.trigger_stop(fig, candidate):
                        fig.pos = candidate
                        fig.step = scale_step(fig.step, i, n)
                        return False
        fig.pos = target
        if fig.collisions and self.figure_blocked(fig, target):
            return False
        self.select_area(fig)
        fig.last_good = fig.pos.copy()
        return True

    def bounce_collision(self, fig, start):
        """FUN_10a0_0ead's bouncy branch: step := position - frame start (+0xba; the move's start without a frame), a falling
        figure stops falling (fall-end method), then the rebound."""
        prev = fig.prev_pos if fig.prev_pos is not None else start
        fig.step = [int(fig.pos[k] - prev[k]) for k in range(3)]
        if fig.falling:
            fig.falling = False
            self.fall_end(fig)
        self.bounce(fig)

    def bounce(self, fig):
        """FUN_1070_0fa7, generic 3D. P = the blocked position. Six candidates in order X, Y, Z, XY, XZ, YZ, each P minus the step
        on those axes (the step is re-read for every candidate: a mover call can rescale it) and each moved to by the mover from
        wherever the previous attempt left the figure. The first whose hull bottom is strictly above the support with a zero PHYS
        score, where the figure ends up, is accepted and the velocity components of its axes are negated. If none is, the
        mover is called with the pointer to last good (+0xe2), which the mover overwrites with the current position before it
        reads the target, so the figure stays where the YZ attempt left it and all three components are negated. Always after:
        v -= (v * ELASTICITY) >> 8 for the velocity and the step, and `_<TYPE>_BOUNCE` plays when the sound exists."""
        p = np.array(fig.pos, float)
        for axes in ((0,), (1,), (2,), (0, 1), (0, 2), (1, 2)):
            target = p.copy()
            for a in axes:
                target[a] = p[a] - fig.step[a]
            self.mover(fig, target)
            lo, _, sup = self.query_hull(fig)
            if lo[2] > sup and not self.hull_collides(fig):
                break
        else:
            axes = (0, 1, 2)
            self.mover(fig, fig.pos.copy())
        v = [fig.vx, fig.vy, fig.vz]
        for a in axes:
            v[a] = -v[a]
        e = fig.elasticity
        fig.vx, fig.vy, fig.vz = (c - fix_mul(c, e) for c in v)
        fig.step = [c - fix_mul(c, e) for c in fig.step]
        idx = self.sound_index(f'_{fig.type}_BOUNCE')
        if idx is not None:
            self.play_sound(idx, fig=fig)

    def velocity_figure(self, ref, cur, proc=None):
        """The object a velocity statement / function addresses: CURFIG (``cur``), CURITEM (the process's item) or a figure / item
        name; None for an unknown one. Items keep their velocity like figures (effects.py moves the free ones)."""
        ref = str(ref).upper()
        if ref == 'CURITEM':
            item = self.items.get(proc.cur_item) if proc is not None and proc.cur_item else None
        else:
            fig = cur if ref == 'CURFIG' else self.figure(ref)
            item = self.item_by_type(ref)
            if fig is not None or item is None:
                return fig
        if item is not None:
            self.load_item_physics(item)
        return item

    def orientation(self, fig):
        """The figure's matrix (+0x110) rows in 8.8 (256 = 1.0) for a pure yaw: row 0 = (cos h, -sin h), row 1 = (sin h, cos h) =
        -forward(), row 2 = up. ASSUMPTION: the engine's persistent matrix equals the FK table rotation of the heading."""
        if isinstance(fig, Item):                # an item has its own matrix
            return [[round(256 * c) for c in r] for r in fig.matrix] if fig.matrix is not None else [[256, 0, 0], [0, 256, 0], [0, 0, 256]]
        m = [[256, 0, 0], [0, 256, 0], [0, 0, 256]]
        salsa._rot8(cos_table(), m, int(round(-fig.heading * 256)), 0, 1, 1)
        return m

    def leap(self, fig, pitch, speed, target=None):
        """LEAP <obj> [target] <pitch> <speed> (FUN_10d0_42c4): v += row1 * k, k = (speed << 3 << 8) / 100 (signed, truncating; speed
        is cm per frame, 20.48 units per cm) through 0c42, row1 of the matrix after an X rotation by pitch degrees (the pitch tilts
        row 1 toward row 2, up). Without a target the matrix is the object's own: row 1 is BACKWARD, so a positive speed pushes
        backward (the zero-g gun recoil) and a negative one forward (ledge leaps). With a target the matrix is built toward it:
        row 1 = normalised (target - object), so a positive speed pulls toward it (LEAP CURFIG GRAVPT 0 2). An unknown target does
        nothing. ASSUMPTIONS: row 0 = normalised (dy, -dx, 0) and row 2 = row 0 x row 1 (the cross-product order of 1208:0154 is not
        decoded; shipped scripts only use pitch 0 with a target, which it does not affect); the +/-0x38 renormalise after the
        rotation is not modelled."""
        if target is None:
            m = self.orientation(fig)
        else:
            t = self.target(target)
            if t is None or fig.pos is None:
                self.warn(f'LEAP {target}: no such object')
                return
            d = [float(t[0][0] - fig.pos[0]), float(t[0][1] - fig.pos[1]), float(t[1] - fig.pos[2])]
            unit = lambda v: [int(round(256 * c / n)) for c in v] if (n := math.sqrt(sum(c * c for c in v))) else [0, 0, 0]
            r1 = unit(d)
            r0 = unit([d[1], -d[0], 0.0]) if d[0] or d[1] else [256, 0, 0]
            r2 = unit([r0[1] * r1[2] - r0[2] * r1[1], r0[2] * r1[0] - r0[0] * r1[2], r0[0] * r1[1] - r0[1] * r1[0]])
            m = [r0, r1, r2]
        self.add_leap(fig, m, pitch, speed)

    def add_leap(self, obj, m, pitch, speed):
        """The tail of LEAP and THROWCURITEM: ``m`` (8.8 rows, modified) turned about X by ``pitch`` degrees, then
        v += row1 * k with k = trunc((speed << 11) / 100)."""
        salsa._rot8(cos_table(), m, int(pitch) << 8, 1, 2, 1)
        x = s32(int(speed) << 11)
        k = abs(x) // 100 * (1 if x >= 0 else -1)
        obj.vx += fix_mul(m[1][0], k)
        obj.vy += fix_mul(m[1][1], k)
        obj.vz += fix_mul(m[1][2], k)

    def push_target(self, fig, target):
        """FUN_1088_3629: before a living figure (~0 > 0) moves, every other figure that is visible, alive and
        colliding pushes a colliding target out of the circle of their summed PERSONAL_RADIUS; then each
        ADDAVOIDANCEPOINT object pushes it out of (r << 11) / 100 (r in cm), whatever its collisions flag."""
        if self.hit_points(fig) <= 0:
            return target
        if fig.collisions:
            for other in self.figures.values():
                if other is fig or other.pos is None or other.hidden or not other.collisions or self.hit_points(other) <= 0:
                    continue
                target = push_out(target, other.pos, personal_radius(fig) + personal_radius(other))
        for name, r in fig.avoid:
            point = self.target(name) if name else None   # a saved entry whose object is gone stays listed
            if point is not None:
                target = push_out(target, point[0], (r << 11) // 100)
        return target

    def add_avoidance(self, fig, name, radius):
        """ADDAVOIDANCEPOINT <object> <radius cm> (10d0:0178 -> FUN_1098_0b88): the radius must be > 0 and the object
        must exist; a full list (8) refuses, an object already listed keeps its old radius."""
        name = self.resolve(name)
        if not isinstance(radius, int) or radius <= 0 or self.target(name) is None or len(fig.avoid) >= MAX_AVOID:
            self.warn(f'ADDAVOIDANCEPOINT {name} {radius}: refused')
            return
        if all(n != name for n, _ in fig.avoid):
            fig.avoid.append((name, radius))

    def remove_avoidance(self, fig, name):
        """REMOVEAVOIDANCEPOINT <object> (FUN_1098_0c52): later entries shift down; the scan covers slots 0..6 only."""
        name = self.resolve(name)
        for i, (n, _) in enumerate(fig.avoid[:MAX_AVOID - 1]):
            if n == name:
                del fig.avoid[i]
                return

    def kill_figure(self, fig, caller=None):
        """FUN_1090_135a: retire a figure while letting the issuing script continue."""
        key = fig.name
        if self.vm is not None:
            record = self.vm.objects.setdefault(self.object_key(key), [0] * 10)
            record[0] = -666
            if fig.ai_proc is not None and fig.ai_proc is not caller and not fig.ai_proc.done:
                self.vm.finish(fig.ai_proc)
            for handle, (name, _) in list(self.sound_pos.items()):
                if name == key:
                    self.stop_sound(handle)
                    self.sound_pos.pop(handle, None)
        fig.ai_proc, fig.go, fig.after_go, fig.in_trig = None, None, None, None
        fig.avoid.clear()
        self.figures.pop(key, None)
        self.dead_figures[key] = fig
        self.killed_figures.add(key)

    def motion_duration(self, fig):
        """FUN_1098_0088, once per motion start: MY_SPEED x frame time, then for any figure but the player
        - (level << 6) at difficulty level 1..2 ([a36e] = _difficulty_level) or + 0x80 at level 0, so enemies animate
        faster on harder levels; for the player, repeating the same ATK_H*/ATK_F* attack (not ATK_F2*, ATK_SHO*,
        ATK_F9*) adds count * 64 * level * 16 per repeat, ATK_F9* starts a reset timer ([2958]) and any other motion
        clears the count; the count also clears 0x2d clock ticks after the timer starts."""
        if fig.dur_id == fig.mot_id and fig.duration is not None:
            return fig.duration
        dur = fig.speed * fig.assets.motion_info[fig.motion][0]
        level = int(self.vm.globals.get('_difficulty_level', 0)) if self.vm is not None else 0
        if fig is self.player():
            clock = self.game_tick * 2 if self.vm is not None else 0       # [8330]
            if self.combo_timer and clock - self.combo_timer > 0x2d:
                fig.combo_name, fig.combo_count, self.combo_timer = '', 0, 0
            name = fig.motion.upper()
            if name.startswith(('ATK_H', 'ATK_F')) and not name.startswith(('ATK_F2', 'ATK_SHO', 'ATK_F9')):
                if name == fig.combo_name:
                    fig.combo_count = (fig.combo_count + 1) & 0xff
                    p = ((fig.combo_count << 6) * (level << 4)) & 0xffff      # 16-bit IMUL, low word sign-extended
                    dur += p - 0x10000 if p & 0x8000 else p
                else:
                    fig.combo_count = 0
                fig.combo_name, self.combo_timer = name, 0
            elif name.startswith('ATK_F9'):
                if not self.combo_timer:
                    self.combo_timer = clock
            else:
                fig.combo_name, fig.combo_count, self.combo_timer = '', 0, 0
        else:
            dur += 0x80 if level == 0 else -(level << 6)
        fig.duration, fig.dur_id = dur, fig.mot_id
        return dur

    def set_pos(self, fig, pos, raw=False):
        """vtable +0x58 (FUN_10a0_1ff0 via FUN_10a0_2158 when `raw`): position, last good (+0xe2) and previous (+0xba) all
        become `pos`; the hull, area and support are rebuilt (select_area / query_hull on demand) and every velocity is zeroed
        (FUN_1070_1e9d). Unless raw, a gravity figure inside an area is then stood on its floor: z = support + F (the engine's
        floor + F + R; the port keeps R in the pose). `raw` sets the +0x1e8 guard around the call, which skips that snap, and so
        does a rising motion (header flag 2, whose +0x1e8 stays set while it runs; 10a0:1ff0 needs +0x1e8 == 0)."""
        fig.raw_setpos = raw
        fig.stored_hull = None                  # the engine rebuilds the hull here
        fig.pos = np.array(pos, float)
        fig.prev_pos = fig.last_good = fig.pos.copy()
        self.select_area(fig)
        fig.vx = fig.vy = fig.vz = 0
        fig.step = [0, 0, 0]                    # FUN_1070_1e9d zeroes +0xc6..+0xdc
        if not raw and not fig.rises and fig.gravity and fig.in_area and fig.frames is not None:
            lo, hi = self.hull(fig)
            fig.pos[2] = self.support(fig, lo, hi) + self.foot(fig)      # global: SetPos passes a null area (10a0:1ff0)
            fig.prev_pos = fig.last_good = fig.pos.copy()
        fig.raw_setpos = False

    def collider(self, fig):
        """FUN_1070_0f68: the PHYS of the largest state-1 overlap with the hull (what FUN_1058_1a1b leaves at +0x8d), else the
        area's anchor PHYS, else None."""
        lo, hi, _ = self.query_hull(fig)
        area = self.area_members(fig.area)
        best, vol = None, 0
        for phys, state, plo, phi in (self._phys_boxes() if area is None else area):
            overlap = np.minimum(hi, phi) - np.maximum(lo, plo)
            if state == 1 and np.all(overlap > 0) and collision_volume(overlap) > vol:
                best, vol = (phys, plo, phi), collision_volume(overlap)
        if best is None and fig.area is not None:
            p = self.phys[fig.area]
            best = (p, [int(v) for v in p['lo']], [int(v) for v in p['hi']])
        return best

    def hull_collides(self, fig, pos=None):
        """FUN_1058_1a1b != 0 for the figure's rebuilt hull in its selected area (FUN_1058_192f without one)."""
        self.select_area(fig, pos)
        lo, hi, _ = self.query_hull(fig, pos)
        area = self.area_members(fig.area)
        return self.collision_score(np.array(lo), np.array(hi), self._phys_boxes() if area is None else area) > 0

    def collision_response(self, fig, start, blocked, good):
        """FUN_10a0_0ead for a non-bouncy figure at its blocked position (the bouncy path is bounce_collision). Sets fig.pos.
        z velocity non-zero: vertical_response. Otherwise: step-up (support above the hull bottom by less than k - R, where
        k = fig+0x14a = hull dz / 4 and R = model+0xa6 = the frame's root z, lifts z onto the support and returns); then,
        unless the +0x1e8 guard is set or the last good position is the zero vector, the slide (keep the blocked y with the
        start x, else the blocked x with the start y, else the last good position); then the tail: velocity zeroed, the mantle
        and the BONK sound."""
        fig.pos = np.array(blocked, float)
        lo, hi, sup = self.query_hull(fig)
        bottom0 = lo[2]
        c = self.collider(fig)                  # FUN_1070_0f68 at the blocked hull (ASSUMPTION: not the slide's last candidate)
        if fig.vz != 0:
            return self.vertical_response(fig, start, good, bottom0)
        if sup > bottom0 and sup < bottom0 + (hi[2] - lo[2]) // 4 - self.root_z(fig):
            fig.pos[2] += sup - bottom0
            return self.set_pos(fig, fig.pos, raw=True)
        # +0x1e8 is also the running motion's header flag 2 (1098.c:274), so a rising motion (mantle, ladder, iris entry) takes the same
        # guard: the blocked position stands, no slide, no restore, no new mantle. That is how MANTLE_* carries Lex through the ledge's
        # box (INFERRED from the shared field; the mover otherwise blocks every frame of the climb)
        guard = fig.raw_setpos or fig.rises
        if not guard and np.any(np.asarray(good) != 0):         # B3: the engine's zero-vector compare skips the slide
            for keep in (1, 0):
                candidate = np.array(start, float)
                candidate[keep] = blocked[keep]
                if not self.figure_blocked(fig, candidate):
                    fig.pos = candidate
                    break
            else:
                self.set_pos(fig, good, raw=True)
        fig.vx = fig.vy = fig.vz = 0
        if guard or fig.area is None:
            return
        if c is None or fig.frames is None:
            return
        phys, plo, phi = c
        if len(phys['raw']) > 21 and phys['raw'][21] & 2 and phys is not self.phys[fig.area] and fig.motion == 'WALK' and fig.engine_request \
                and phi[2] > self.query_hull(fig)[0][2] and self.mantle_fits(fig, plo, phi):
            self.mantle(fig, abs(phi[2] - self.query_hull(fig)[2]))
        material = phys['raw'][45:54].split(b'\0')[0].decode('latin1')
        self.hit_sound(f'_{fig.type}_BONK_{fig.motion}_{material}', fig)     # FUN_1100_1ce4; silent in the shipped data

    def vertical_response(self, fig, start, good, bottom0):
        """FUN_10a0_0ead with a z velocity (fig.pos is the new position, `bottom0` the hull bottom there). Not falling: back
        to the last good position, velocity zeroed. The player tries the previous x, y at the new z: if that hull is free it
        drops its horizontal velocity and keeps falling. Otherwise it lands: falling cleared, the fall-end method, the previous
        position when the support is over 0x1000 above the entry hull bottom (else the hull bottom goes onto the support),
        FUN_1130_1a2d's unstick, a raw SetPos and the landing motion for the (by then zero) velocity."""
        if not fig.falling:
            return self.set_pos(fig, good, raw=True)
        if fig is self.player():
            fig.pos[:2] = np.asarray(start)[:2]
            if not self.hull_collides(fig):
                fig.vx = fig.vy = 0
                return
        sup = self.query_hull(fig)[2]
        fig.falling = False
        self.fall_end(fig)
        if sup > bottom0 + LAND_REVERT:
            fig.pos = np.array(start, float)
        else:
            fig.pos[2] += sup - bottom0
        self.unstick(fig)
        self.set_pos(fig, fig.pos, raw=True)
        self.request_motion(fig, self.landing_motion(fig.vz), False)

    @staticmethod
    def landing_motion(vz):
        """FUN_10a0_0e24: land_hard at vz <= -0x280, land_medium at <= -0x140, else land_soft."""
        return 'LAND_HARD' if vz <= -0x280 else 'LAND_MEDIUM' if vz <= -0x140 else 'LAND_SOFT'

    def unstick(self, fig):
        """FUN_1130_1a2d: SetPos (floor snap) at the position, then up to 40 nudges (i << 8 units, x + for i & 3 in (0, 2), y - for
        1 and 3 as the bytes read) from the original position, each followed by a snapping SetPos, until the hull is clear of
        the global PHYS list (FUN_1058_192f) with z equal to the original z; after 40 it returns to the original position."""
        p0 = fig.pos.copy()
        self.set_pos(fig, p0)
        i = 0
        while i < 40 and (self.null_area_blocked(*self.query_hull(fig)[:2]) or fig.pos[2] != p0[2]):
            q = p0.copy()
            if i & 3 in (0, 2):
                q[0] += i << 8
            else:
                q[1] -= i << 8
            self.set_pos(fig, q)
            i += 1
        if i >= 40:
            self.set_pos(fig, p0)

    def request_motion(self, fig, name, loop):
        """FUN_1098_0e49(fig, name, 1, 1, ...): run the script block `<TYPE>_<NAME>` if the level defines it, else play the motion
        (an engine request, so the name is lower case in the original)."""
        if not self.spawn_for(fig, f'{fig.type.upper()}_{name}') and name in fig.assets.motions:
            fig.manual_control = False
            fig.set_motion(name, loop, engine=True)

    def mantle_fits(self, fig, plo, phi):
        """FUN_10a0_0ae5: the support within 0x1000 of the collider's top and the facing within 15 degrees of an axis with the hull
        inside the collider box shrunk by 0x266 (strict for the 0-degree case); then the facing snaps onto that axis (matrix
        identity / rotZ). ASSUMPTION: the engine's yaw is the port's heading, so rounding it to a multiple of 90 is the snap."""
        lo, hi, sup = self.query_hull(fig)
        if abs(phi[2] - sup) > 0x1000:
            return False
        ax0, ax1, ay0, ay1 = plo[0] + 0x266, phi[0] - 0x266, plo[1] + 0x266, phi[1] - 0x266
        h = (fig.heading + 180) % 360 - 180
        if -15 < h < 15:
            ok = lo[0] > ax0 and hi[0] < ax1
        elif 75 < h < 105 or -105 < h < -75:
            ok = lo[1] >= ay0 and hi[1] <= ay1
        elif h > 165 or h < -165:
            ok = lo[0] >= ax0 and hi[0] <= ax1
        else:
            return False
        if ok:
            fig.heading = float(round(h / 90) * 90)
        return ok

    def mantle(self, fig, height):
        """FUN_10a0_0d93: request mantle_3 under 0x800, mantle_6 under 0x1000, else mantle_9."""
        self.request_motion(fig, 'MANTLE_3' if height < 0x800 else 'MANTLE_6' if height < 0x1000 else 'MANTLE_9', False)

    def fall_start(self, fig):
        """FUN_10a0_0072's call of the fall-start method (vtable +0x9c, FUN_1088_3196): +0x229 raised, script process suspended."""
        self.die_method(fig, False)

    def fall_end(self, fig):
        """vtable +0xa0 (FUN_1088_31fb): +0x229 lowered and, whatever its value, the script process resumed."""
        fig.hold = max(0, fig.hold - 1)
        if fig.ai_proc is not None and not fig.ai_proc.done:
            fig.ai_proc.suspended = False

    def player_bounds(self, fig, pos=None):
        """Backward-compatible name for the current figure collision AABB."""
        return self.figure_bounds(fig, pos)

    def player_blocked(self, fig, pos):
        """Backward-compatible name for the current figure PHYS test."""
        return self.figure_blocked(fig, pos)

    def player_move(self, fig, delta):
        """Backward-compatible manual player root-motion helper."""
        return self.figure_move(fig, delta)

    def root_z(self, fig):
        """R (model+0xa6): the current motion frame's root z, kept in the pose rather than in fig.pos."""
        return int(fig.frames[min(fig.idx, len(fig.frames) - 1)][0][2]) if fig.frames else 0

    def model_root_z(self, fig):
        """R as the engine holds it: a motion's frame 0 only reaches model+0xa6 at its first update, until then the previous motion's root z stays."""
        return fig.applied_root_z if fig.root_start else self.root_z(fig)

    def hull(self, fig, z=None, pos=None):
        """The engine's figure hull (fig+0x65) as integer (lo, hi): FUN_10a0_0000 -> FUN_1070_08df builds x, y = +-EXTENT and
        z from -s to +EXTENT z around the engine position (origin + root z), where s = (F * 100 + 128) / 2048 cm and cm
        become units through hull_units (2048 / 100 per cm)."""
        ex, ey, ez = (int(v) for v in figure_extents().get(fig.type, DEFAULT_EXTENT_CM))
        s = (int(self.foot(fig)) * 100 + 128) // 2048
        pos = np.asarray(fig.pos if pos is None else pos, float)
        x, y = int(round(pos[0])), int(round(pos[1]))
        zz = int(round(pos[2] if z is None else z)) + self.root_z(fig)
        hx, hy = hull_units(ex), hull_units(ey)
        return (x - hx, y - hy, zz - hull_units(s)), (x + hx, y + hy, zz + hull_units(ez))

    def _phys_boxes(self):
        if self._boxes is not None:          # cached while step() runs the figures
            return self._boxes
        return [(p, self.phys_state(p), [int(v) for v in p['lo']], [int(v) for v in p['hi']]) for p in self.phys]

    def support(self, fig, lo, hi, area=None):
        """Floor under a hull box (FUN_1060_03f2, stored at fig+0xee). A solid (state 1) whose xy range overlaps the box
        offers its top when the box top is above its bottom, and the last such solid tells whether the box overlaps it
        in z; a space (state 0) offers its bottom, and a space named Q... marks a pit. With a pit and no solid overlap,
        every Q space reaching the box bottom may lower the result to its bottom if the box fits there. `area` is the
        figure's area candidate (area_of; 1060:0405-045c): the loop ranks only its member list and the result is seeded
        with the anchor's floor slot (lo.z for a space, hi.z for a solid, none for state 2; not xy-gated), and the Q pass
        fit test is scoped to the members too. None (a null area, or a global caller) ranks every PHYS, unseeded. A solid
        whose top is far above the hull bottom offers its top all the same (03f2 has no such clause: the earlier port-only
        LAND_REVERT rule that offered its bottom blocked the LANDPAD jetson tube and the TANKS catwalk)."""
        best, inside, pit = NO_FLOOR, False, False
        boxes = self._phys_boxes() if area is None else area[4]
        if area is not None:
            best = self.area_seed(area)
        xy = lambda plo, phi: plo[0] <= hi[0] and lo[0] <= phi[0] and plo[1] <= hi[1] and lo[1] <= phi[1]
        for p, st, plo, phi in boxes:
            if st == 1 and xy(plo, phi):
                if phi[2] > best and hi[2] > plo[2]:
                    best = phi[2]
                inside = plo[2] <= hi[2] and lo[2] <= phi[2]
            elif st == 0 and xy(plo, phi):
                best = max(best, plo[2])
                pit = pit or p['name'].startswith('Q')
        if pit and not inside:
            for p, st, plo, phi in boxes:
                if st == 0 and p['name'].startswith('Q') and phi[2] >= lo[2] and plo[2] < best and xy(plo, phi):
                    d = plo[2] - lo[2]
                    if self.collision_score((lo[0], lo[1], lo[2] + d), (hi[0], hi[1], hi[2] + d), boxes) <= 0:    # FUN_1058_1a1b over the same list
                        best = plo[2]
        return best

    @staticmethod
    def area_seed(area):
        """The anchor's floor slot (anchor+0x4b+4*state, 1060:040d-045c): lo.z for a space, hi.z for a solid, NO_FLOOR for state 2."""
        return area[2][2] if area[5] == 0 else area[3][2] if area[5] == 1 else NO_FLOOR

    def point_floor(self, x, y, z, zq, area=None):
        """FUN_1060_0871: the same query for a point (x, y), solids counted when zq is above their bottom; the Q pass
        takes any Q space whose top reaches z (no fit test). `area` scopes and seeds it as in support."""
        best, inside, pit = NO_FLOOR, False, False
        boxes = self._phys_boxes() if area is None else area[4]
        if area is not None:
            best = self.area_seed(area)
        xy = lambda plo, phi: plo[0] <= x <= phi[0] and plo[1] <= y <= phi[1]
        for p, st, plo, phi in boxes:
            if st == 1 and xy(plo, phi):
                if phi[2] > best and zq > plo[2]:
                    best = phi[2]
                inside = plo[2] <= zq and z <= phi[2]
            elif st == 0 and xy(plo, phi):
                best = max(best, plo[2])
                pit = pit or p['name'].startswith('Q')
        if pit and not inside:
            for p, st, plo, phi in boxes:
                if st == 0 and p['name'].startswith('Q') and phi[2] >= z and plo[2] < best and xy(plo, phi):
                    best = plo[2]
        return best

    @staticmethod
    def boxes_touch(lo, hi, plo, phi):
        """Inclusive PHYS-box overlap used to construct an area's ordered member list."""
        return all(lo[k] <= phi[k] and plo[k] <= hi[k] for k in range(3))

    def area_candidates(self):
        """Ordered selectable PHYS areas: spaces and script-controlled PHYS volumes (FUN_1138_1853).

        Each anchor's physical_objs (FUN_1138_131c) holds every PHYS of the level, solids included, whose box
        touches the anchor box grown by 0x1000 on each side. Each entry is (index, phys, lo, hi, members, state). The
        engine builds the lists once at level load (1138:1853 / 131c); the port recomputes them live (in CONTROL they stay
        identical at every elevator step) and caches them with the step's `_boxes` (rebuilt whenever that list is)."""
        boxes = self._phys_boxes()
        if self._boxes is not None and self._areas is not None and self._areas[0] is boxes:
            return self._areas[1]
        globals_ = self.vm.globals if self.vm is not None else {}
        areas = []
        for index, (phys, state, lo, hi) in enumerate(boxes):
            if state == 0 or '_' + phys['name'].lower() + '_space' in globals_:
                glo, ghi = [v - AREA_GROW for v in lo], [v + AREA_GROW for v in hi]
                areas.append((index, phys, lo, hi, [box for box in boxes if self.boxes_touch(glo, ghi, box[2], box[3])], state))
        if self._boxes is not None:
            self._areas = (boxes, areas)
        return areas

    def area_members(self, index):
        """The selected area's inclusive PHYS-member list, or None without an area."""
        return next((area[4] for area in self.area_candidates() if area[0] == index), None)

    def area_of(self, fig):
        """The figure's area candidate (fig+0x35 as passed to FUN_1060_03f2 / 0871), or None for a null area."""
        return None if fig.area is None else next((area for area in self.area_candidates() if area[0] == fig.area), None)

    def select_area(self, fig, pos=None):
        """FUN_1138_1a93: keep the current area while its origin contains the figure,
        otherwise select the first candidate containing the origin or overlapping its hull.
        A miss retains the previous area index."""
        pos = np.asarray(fig.pos if pos is None else pos, float)
        lo, hi = self.hull(fig, pos=pos)
        origin = (int(round(pos[0])), int(round(pos[1])), int(round(pos[2])) + self.root_z(fig))
        candidates = self.area_candidates()
        current = next((area for area in candidates if area[0] == fig.area), None)
        contains = lambda area: all(area[2][k] <= origin[k] <= area[3][k] for k in range(3))
        if current is not None and contains(current):
            chosen = current
        else:
            chosen = next((area for area in candidates if contains(area)), None)
            if chosen is None:
                chosen = next((area for area in candidates if self.boxes_touch(lo, hi, area[2], area[3])), None)
        if chosen is not None:
            if chosen[0] != fig.area and fig.in_trig is not None:
                # FUN_1138_1b8a: a new area clears the InTrig bytes of triggers missing from its trigger list
                keep = set(self.area_triggers(chosen[0]))
                for i in range(len(fig.in_trig)):
                    if i not in keep:
                        fig.in_trig[i] = 0
            fig.area = chosen[0]
        fig.in_area = fig.area is not None
        return fig.area

    # ---- IMAG triggers (LIVING.C FUN_1088_51c3 / 50c1, PHYSICAL.C IMAG class 1290:2077)
    def area_triggers(self, index):
        """RoomType->triggers of the area anchored at PHYS `index` (FUN_1138_131c): the level's IMAG objects whose boxes touch
        (FUN_1068_0934, inclusive) the anchor's box, as InTrig indices in level order."""
        if index not in self._area_triggers:
            p = self.phys[index]
            lo, hi = [int(v) for v in p['lo']], [int(v) for v in p['hi']]
            self._area_triggers[index] = [i for i, t in enumerate(self.triggers) if self.boxes_touch(lo, hi, t['lo'], t['hi'])]
        return self._area_triggers[index]

    def trigger_block(self, trig, fig):
        """The block a trigger runs for a figure (FUN_1068_0d45): `<trigger>` for the player, else `<trigger>_<figure>` (DR_ZAP3_FIRSTBOT,
        DR_ZAP1_CAYNAN; "%s_%s" at DGROUP 0x2071)."""
        return trig['name'] if fig is self.player() else f"{trig['name']}_{fig.name}"

    def trigger_has_block(self, trig):
        """IMAG +0x4a (FUN_1068_0e7a): the trigger has a block for the player or for some other figure."""
        blocks = self.vm.blocks
        return trig['name'] in blocks or any(f"{trig['name']}_{f.name}" in blocks
                                            for f in self.figures.values() if f is not self.player())

    def fire_trigger(self, trig, fig):
        """IMAG vtable +0x5c (FUN_1068_0d45): a camera trigger entered by the followed figure forces its camera
        (FUN_1130_0f85; a name with no camera forces nothing), then the trigger's block starts with the figure current and
        runs its first slice at once (FUN_1120_0000)."""
        if trig['camera'] in self.cameras and fig.name == self.resolve(self.follow):
            self.forced_camera = trig['camera']
        block = self.trigger_block(trig, fig)
        if block in self.vm.blocks:
            self.events.append((self.vm.tick, block))
            self.spawn_for(fig, block)

    def update_triggers(self, fig):
        """FUN_1088_51c3, at the end of each figure's frame after FUN_1138_1b8a re-selected its area: for each trigger of the
        area, a hull (+0x65) outside clears the InTrig byte; inside, the trigger fires every frame, or only on entry when its
        flag bit 0x01 is set. Skipped for a dead player and for figures with collisions off; stops if a block moved the
        figure to another area (or level)."""
        self.select_area(fig)
        if self.vm is None or (fig is self.player() and self.hit_points(fig) <= 0):
            return
        if fig.in_trig is None:
            fig.in_trig = bytearray(len(self.triggers))
        if fig.area is None or fig.no_collide:
            return
        area, level = fig.area, self.level
        lo, hi, _ = self.query_hull(fig)
        for i in self.area_triggers(area):
            t = self.triggers[i]
            if not self.boxes_touch(lo, hi, t['lo'], t['hi']):
                fig.in_trig[i] = 0
            elif not t['once'] or not fig.in_trig[i]:
                fig.in_trig[i] = 1
                self.fire_trigger(t, fig)
            if fig.area != area or self.level != level or fig.in_trig is None:
                return

    def trigger_stop(self, fig, pos):
        """FUN_1088_50c1, after each passing step of the mover's loop: stop the move (the figure stays at the step) when the
        hull enters a trigger of its area that has a block (+0x4a) and whose InTrig byte is clear, so the frame's trigger
        pass fires it with the figure just inside."""
        if self.vm is None:
            return False
        if fig.in_trig is None:
            fig.in_trig = bytearray(len(self.triggers))
        if fig.area is None or fig.no_collide:
            return False
        lo, hi, _ = self.query_hull(fig, pos)
        for i in self.area_triggers(fig.area):
            t = self.triggers[i]
            if self.boxes_touch(lo, hi, t['lo'], t['hi']) and not fig.in_trig[i] and self.trigger_has_block(t):
                return True
        return False

    def object_pos(self, obj):
        """The object's +0xb position: a figure's own, an item's `item_engine_pos` (floor position, hand pose or holder). None if unplaced."""
        return self.item_engine_pos(obj) if isinstance(obj, Item) else obj.pos

    def object_hull(self, obj):
        """The object's hull (+0x65) -> (lo, hi) or None.  A figure: `query_hull`.  An item (1078:08f6 -> FUN_1058_0f95): its `item_engine_pos`
        (whole units) +- the EXTENT box (1070:08df, `hull_units`, no rotation; no EXTENT property = a zero box, a point)."""
        if isinstance(obj, Item):
            pos = self.item_engine_pos(obj)
            if pos is None:
                return None
            self.load_item_physics(obj)
            p = [int(round(c)) for c in pos[:3]]
            return [p[k] - obj.extent[k] for k in range(3)], [p[k] + obj.extent[k] for k in range(3)]
        if obj.pos is None or obj.frames is None:
            return None
        lo, hi, _ = self.query_hull(obj)
        return lo, hi

    def am_in_trigger(self, proc, obj, trig):
        """AMINTRIGGER <object> <trigger> (FUN_10d8_07fa -> 1070:0aba): whether the object's hull (+0x65) touches the first IMAG of that
        name (FUN_1058_173c, inclusive).  The object is CURFIG, CURITEM or a figure / item-type name (`script_object`); an item's hull is
        `object_hull` (a held item's box follows the hand, an inventory item's the holder's origin)."""
        sel = str(obj).upper()
        o = self.script_object(proc, sel)
        t = next((t for t in self.triggers if t['name'] == str(trig).upper()), None)
        hull = self.object_hull(o) if o is not None else None
        if hull is None or t is None:
            return 0
        return int(self.boxes_touch(hull[0], hull[1], t['lo'], t['hi']))

    def figure_by_type(self, name):
        """SETCURRENTFIGURE's fallback (FUN_10c0_3e14): it walks the figure list comparing the name with the instance name
        (+0xf7), then +0x178 (an upper-cased copy of the creation name at +2, written by FUN_1088_2608) and +2 itself, i.e. the
        figure's type name. So `SETCURRENTFIGURE (GRDCELL)` still finds GUARD1 after `INDIVIDUALIZE CURFIG GUARD1`.
        ASSUMPTION: +2 is the FIGR record's name field (the BODY type); the first figure in list order wins."""
        name = str(name).upper()
        for fig in self.figures.values():
            if fig.type.upper() == name:
                return fig
        for inst, (ftype, *_rest) in self.fig_defs.items():
            if ftype.upper() == name and inst not in self.killed_figures:
                return self.figure(inst)
        return None

    def compass(self, fig):
        """COMPASS (FUN_10d8_0f68 -> FUN_1208_39a8 -> 1208:0574): the current figure's facing in whole degrees, the integer part
        (>> 8, floor) of the 8.8 angle atan2(m[1][0], m[1][1]) of the orientation matrix row 1 (vtable +0x20; z is zeroed and the
        vector normalised first). 0 along +y, positive toward +x; equal to Figure.heading wrapped to -180..180 (see `orientation`).
        No current figure: the original reports an error and returns 0; the port returns 0 silently (a script process may still name a
        figure the port has retired, e.g. FIRSTBOT in DR_ZAP3_FIRSTBOT). ASSUMPTION: exact atan2 instead of the engine's sine-table inverse (1210:0e6b / 0f2f), which may
        differ by a degree near the cut points; a row with x = y = 0 would give 720 (0x2d000), unreachable for a yaw matrix."""
        if fig is None:
            return 0
        m = self.orientation(fig)[1]
        if m[0] == 0 and m[1] == 0:
            return 720
        return int(round(math.degrees(math.atan2(m[0], m[1])) * 256)) >> 8

    def motion_heading(self, proc, ref):
        """HEADING <object> (FUN_10d8_26f2): the direction the object moved in its last frame, in the COMPASS convention. d = frame
        start position (+0xba, `prev_pos`) minus the position (+0xb), x and y as 32-bit differences. When the 16-bit sum of the
        absolute low words is 0 or negative (the original tests only the low words) it returns 666 (0x29a). Else a = atan(dy / dx)
        in whole degrees (FUN_1200_097a: the 24.8 divide dy / dx through the atan table 1210:0f2f, or -90 / 90 by the sign of dy when
        dx = 0) and the result is -(a + 90) for dx < 0, 90 - a otherwise: 0 = moving toward -y, 90 = toward -x, -90 = toward +x,
        180 = toward +y, so a forward-walking figure's HEADING equals its COMPASS. Unknown object: error, 0. Items keep no frame
        start position in the ports (-> 0). ASSUMPTION: exact atan instead of the table (floor of the 8.8 angle)."""
        sel = str(ref).upper()
        obj = self.figure(proc.cur_fig if sel == 'CURFIG' else sel)
        if obj is None:
            if sel != 'CURITEM' and self.item_by_type(sel) is None:
                self.warn(f'HEADING {ref}: no such object')
            return 0
        if obj.pos is None:
            return 0
        prev = obj.prev_pos if obj.prev_pos is not None else obj.pos
        dx, dy = (s32(int(round(prev[k])) - int(round(obj.pos[k]))) for k in (0, 1))
        low_abs = lambda v: abs(((v & 0xffff) ^ 0x8000) - 0x8000)         # |int16(low word)|, the CWD / XOR / SUB idiom
        total = (low_abs(dx) + low_abs(dy)) & 0xffff
        if total == 0 or total & 0x8000:
            return 0x29a
        if dx:
            deg = int(round(math.degrees(math.atan(fix_div(dy, dx) / 256)) * 256)) >> 8
        else:
            deg = -90 if dy < 0 else 90
        return -(deg + 90) if dx < 0 else 90 - deg

    def am_in_extent(self, proc, obj, extent):
        """AMINEXTENT <object> <extent> (FUN_10d8_06ef): AMINWAYPOINT's twin against the first PHYS (DGROUP list 1cf5/1cfd, FUN_1050_0996)
        of that name: whether the object's hull (+0x65) touches the PHYS box (FUN_1070_0aba -> FUN_1058_173c, inclusive; an item's hull is
        `object_hull`). A missing argument, object or PHYS reports an error and returns 0."""
        sel, name = str(obj).upper(), str(extent).upper()
        f = self.script_object(proc, sel)
        if not name or f is None:
            self.warn(f'AMINEXTENT {obj} {extent}: no such object')
            return 0
        p = next((p for p in self.phys if p['name'].upper() == name), None)
        if p is None:
            self.warn(f'AMINEXTENT {obj} {extent}: no such extent')
            return 0
        hull = self.object_hull(f)
        if hull is None:
            return 0
        return int(self.boxes_touch(hull[0], hull[1], [int(v) for v in p['lo']], [int(v) for v in p['hi']]))

    def cmd_floatatheight(self, fig, args):
        """FLOATATHEIGHT <waypoint> [MAXIMUM] (FUN_10d0_2f91). No current figure: nothing. A missing waypoint name or an unknown
        waypoint (WAYP list 1cdd): error. With MAXIMUM (any other second word is an error; the figure needs an area, +0x35):
        +0x14e := waypoint z - the area anchor's base z (PHYS +0x13), a z limit World.mover applies. Without it the original
        sets the figure's F (model +0x88 and +0x225) to waypoint z - the support under the waypoint (FUN_1060_0d9a), zeroes
        model +0xa6 and re-places the figure at support + F with vtable +0x2c (`float_at_height`; R lives in the pose)."""
        wp = self.waypoints.get(str(args[0]).upper())
        if wp is None:
            self.warn(f'FLOATATHEIGHT {args[0]}: no such waypoint')
        elif len(args) < 2 or not str(args[1]):
            self.float_at_height(fig, wp)
        elif str(args[1]).upper() != 'MAXIMUM':
            self.warn(f'FLOATATHEIGHT {args[0]} {args[1]}: expected MAXIMUM')
        elif fig.area is None and (fig.pos is None or self.select_area(fig) is None):   # ASSUMPTION: a placed figure has its area (the port selects it lazily)
            self.warn(f'FLOATATHEIGHT {args[0]} MAXIMUM: {fig.name} has no area')
        else:
            fig.z_cap = s32(int(wp[2]) - int(self.phys[fig.area]['lo'][2]))

    def foot(self, fig):
        """This figure's F (model +0x88 / fig+0x225): the FLOATATHEIGHT override if one was set, else its type's."""
        override = getattr(fig, "foot_override", None)     # test stubs are bare namespaces
        return fig.assets.foot_offset if override is None else override

    def float_at_height(self, fig, wp):
        """FLOATATHEIGHT <waypoint> (10d0:2f91, one word): F := waypoint z - the floor under the waypoint (FUN_1060_0d9a, global null
        area); then z := the figure's support + F, re-placed without the gravity floor snap, velocities zeroed (steps 3-5 of the spec).
        ASSUMPTION: the support is the area-scoped one grounding uses, under the figure's hull with the new F (the engine reads the
        +0xee cached by its last hull rebuild; equal after the `GO <waypoint>` that precedes every use). No floor under the figure: z kept."""
        x, y, z = (int(c) for c in wp[:3])
        fig.foot_override = s32(z - self.point_floor(x, y, z, z))
        if fig.pos is None:
            return
        self.select_area(fig)
        lo, hi = self.hull(fig)
        sup = self.support(fig, lo, hi, self.area_of(fig))
        pos = np.array(fig.pos, float)
        if sup > NO_FLOOR:
            pos[2] = sup + fig.foot_override
        self.set_pos(fig, pos, raw=True)

    def waypoint_query(self, proc, name, ref, waypoint):
        """DISTFROMWAYPOINT (10d8:16a6), 2DDISTFROMWAYPOINT (0534), ANGLEFROMWAYPOINT (0d10) and AMINWAYPOINT (0905) for
        `<object> <waypoint>`. The object is CURFIG, CURITEM or a figure / floor item name (FUN_10c0_16a8); the waypoint comes from the
        WAYP list (1290:1cdd) and its position from vtable +0x50. Distances are `cm_from_units` of the object's +0xb position
        against the waypoint: DISTFROMWAYPOINT the 3D length (FUN_1208_13e3 = approx_length of the three differences),
        2DDISTFROMWAYPOINT the exact 2D length (FUN_1210_000d, the DISTFROMENEMY pair); ANGLEFROMWAYPOINT is the figure's bearing
        of the point (vtable +0x60, the same value as ANGLEFROMENEMY); AMINWAYPOINT is FUN_1070_0aba, the hull box against the
        point (inclusive, the AMINTRIGGER test). Unknown object or waypoint: the original reports an error and returns 0."""
        sel, wp = str(ref).upper(), str(waypoint).upper()
        obj = self.script_object(proc, sel)
        point = self.waypoints.get(wp)
        if obj is None or point is None:
            self.warn(f'{name} {ref} {waypoint}: no such {"waypoint" if obj is not None else "object"}')
            return 0
        opos = self.object_pos(obj)
        if opos is None:
            return 0
        d = [int(round(c)) for c in np.asarray(opos, float)[:3] - np.asarray(point, float)[:3]]
        if name == 'DISTFROMWAYPOINT':
            return cm_from_units(approx_length(d))
        if name == '2DDISTFROMWAYPOINT':
            return cm_from_units(length2d(d[0], d[1]))
        if name == 'ANGLEFROMWAYPOINT':
            return int(round(self.rel_angle(obj, point))) if isinstance(obj, Figure) else 0     # items have no facing in the ports
        hull = self.object_hull(obj)
        return 0 if hull is None else int(self.boxes_touch(hull[0], hull[1], point, point))

    def script_object(self, proc, ref):
        """The `<object>` argument of the position functions (FUN_10c0_16a8): CURFIG, CURITEM or a figure / floor item name.
        -> the Figure / Item, or None."""
        sel = str(ref).upper()
        obj = self.figure(proc.cur_fig if sel == 'CURFIG' else sel)
        if sel == 'CURITEM' or (obj is None and self.item_by_type(sel) is not None):
            obj = self.items.get(proc.cur_item) if sel == 'CURITEM' else self.item_by_type(sel)
        return obj

    def box_distance(self, proc, name, ref, box_name):
        """DISTFROMEXTENT (10d8:136a) and DISTFROMTRIGGER (10d8:1566) for `<object> <name>`: the 3D length (FUN_1208_13e3 =
        approx_length) in `cm_from_units` from the object's +0xb position to the centre of the first PHYS / IMAG of that name
        (the lists AMINEXTENT / AMINTRIGGER search). The centre is vtable +0x50 (FUN_1068_02cb for a PHYS, FUN_1068_0f4c for an
        IMAG): per axis (lo + hi) << 8 / 0x200 = trunc((lo + hi) / 2). Unknown object or name: error, 0."""
        boxes = self.phys if name == 'DISTFROMEXTENT' else self.triggers
        obj = self.script_object(proc, ref)
        box = next((b for b in boxes if b['name'].upper() == str(box_name).upper()), None)
        if obj is None or box is None:
            self.warn(f'{name} {ref} {box_name}: no such {"object" if obj is None else "extent" if boxes is self.phys else "trigger"}')
            return 0
        opos = self.object_pos(obj)
        if opos is None:
            return 0
        centre = [fix_div(int(lo) + int(hi), 0x200) for lo, hi in zip(box['lo'], box['hi'])]
        return cm_from_units(approx_length([int(round(c)) - m for c, m in zip(np.asarray(opos, float)[:3], centre)]))

    def item_distance(self, proc, name):
        """DISTFROMITEM (10d8:14aa, 3D: approx_length) and 2DDISTFROMITEM (10d8:02d0, exact length2d of x, y): the process's current
        item against its current figure, in `cm_from_units` of item position - figure position. No current item or figure: error, 0."""
        item, fig = self.items.get(proc.cur_item), self.figure(proc.cur_fig)
        if item is None or fig is None:
            self.warn(f'{name}: no current {"item" if item is None else "figure"}')
            return 0
        ipos = self.item_engine_pos(item)               # floor position, hand pose or the holder's origin
        if ipos is None or fig.pos is None:
            return 0
        d = [int(round(a)) - int(round(b)) for a, b in zip(np.asarray(ipos, float)[:3], np.asarray(fig.pos, float)[:3])]
        return cm_from_units(approx_length(d) if name == 'DISTFROMITEM' else length2d(d[0], d[1]))

    def distance_from_coords(self, proc, ref, x, y):
        """2DDISTFROMCOORDS <object> <x> <y> (10d8:0000): x and y are script integers in COORDX units (<< 8 gives world units);
        the exact 2D length from the object to that point in `cm_from_units`. Unknown object: error, 0."""
        obj = self.script_object(proc, ref)
        if obj is None:
            self.warn(f'2DDISTFROMCOORDS {ref}: no such object')
            return 0
        opos = self.object_pos(obj)
        if opos is None:
            return 0
        dx, dy = ((int(v) << 8) - int(round(c)) for v, c in zip((x, y), np.asarray(opos, float)[:2]))
        return cm_from_units(length2d(dx, dy))

    def find_figure(self, proc, first):
        """FINDFIRSTFIGURE (statement, 10d0:2f1a): the process's current figure := entry 0 of the engine figure list and its
        index (+0x42) := 0. FINDNEXTFIGURE (10d8:181c): while index < count - 1, index += 1, current figure := that entry and
        return 1; otherwise return 0 and leave the current figure. ASSUMPTION: the list is `self.figures` in dict order. The
        original (DGROUP 0x1d19 / 0x1d21) is the level's FIGR records then the created figures with the player last (live CHAOS:
        USE_BOT, FIRSTBOT, FIDO, HALMECHO, CAYNAN, GUARD1, LEX), so the order differs; the only users (COMMON.scr quake loops)
        act on every figure, so the outcome does not. An empty list leaves the current figure unchanged."""
        names = list(self.figures)
        if first:
            proc.fig_index = 0
            if names:
                proc.cur_fig = names[0]
            return 0
        index = getattr(proc, 'fig_index', 0)
        if index >= len(names) - 1:
            return 0
        proc.fig_index = index + 1
        proc.cur_fig = names[index + 1]
        return 1

    def apply_decal(self, fig, args):
        """APPLY <object> <mode> <texture> [PICTURE <frame> [<flic prefix>]] (FUN_10d0_0843 -> SCANNER.C FUN_10f8_08a9): the texture
        decal system. The scanner walks the object's model textures (the name or ALL) and FUN_10f8_0712 switches on the mode name
        (table at 1290:4ce8): DRAW and DRAWONLY restore the texture from its backup copy (made on first use, FUN_1168_027c) and then
        draw a frame of the picture FLIC over it; RESTORE only restores; CLEAR backs the texture up, fills it with 0xff (transparent)
        and draws the frame. The picture is `<prefix>0PIC.FLC` ("CAY0PIC.FLC", "GRD0PIC.FLC" in the script comments). Those FLICs are
        not in the shipped data, so a draw is recorded but cannot be rendered; the port keeps the state in `Figure.decals`
        ({texture: (mode, frame, prefix)}; absent = original texture) and the renderer does not use it (a CLEAR drawn without its
        picture would only make the hands vanish). Warns for an unknown mode or texture."""
        if fig is None:
            return
        words = [a for a in args[1:] if isinstance(a, str)]
        nums = [a for a in args[1:] if isinstance(a, int)]
        mode = words[0].upper() if words else ''
        texture = words[1].upper() if len(words) > 1 else ''
        if mode not in ('DRAW', 'DRAWONLY', 'RESTORE', 'CLEAR'):
            self.warn(f'APPLY {mode}: unknown mode')
            return
        names = [t[0].upper() for t in fig.assets.mesh.textures]
        targets = names if texture == 'ALL' else [texture] if texture in names else []
        if not targets:
            self.warn(f'APPLY {fig.name} {texture}: no such texture')
            return
        for tex in targets:
            if mode == 'RESTORE':
                fig.decals.pop(tex, None)
            elif len(words) > 2:                                # a PICTURE argument follows: draw its frame
                prefix = words[3].upper() if len(words) > 3 else fig.type[:3].upper()   # ASSUMPTION: the default prefix is the figure's first three letters (CAY, GRD)
                fig.decals[tex] = (mode, nums[0] if nums else 0, prefix)
            elif mode == 'CLEAR':
                fig.decals[tex] = (mode, None, None)
            else:
                fig.decals.pop(tex, None)                       # DRAW without a picture: restored, nothing to draw

    def enter_area(self, fig, lo, hi):
        """Grounding's area gate (FUN_1088_3bd1: a figure without an area gets no gravity or whoah processing). Its support
        query is area-scoped by the caller (settle / query_hull pass the figure's area)."""
        self.select_area(fig)
        return fig.in_area

    def settle(self, fig):
        """One figure's physics for a 30 fps frame (FUN_1088_39ef after the animation): gravity, then the frame move.

        Gravity, for figures with the gravity flag inside an area: the hull's floor (support) more than half the hull height
        (2 * (dz / 4), fig+0x14a) below the hull bottom starts a fall (FUN_10a0_0072); otherwise the whoah edge probes run
        (FUN_10a0_009b). A falling figure gains -[83a0]/5 of z velocity per frame while vz > -0x500 (so down to -1326). A figure
        at rest (vz == 0) stands on its support: origin z = support + F (the root z stays in the pose). Then frame_move moves
        every figure, gravity flag or not. A rising motion (header flag 2, `rises`) skips the fall start, the whoah probes and
        the stand on the support: its root z is committed at its wraps and end instead (World.advance, Figure.set_motion).
        ASSUMPTIONS: one prototype tick is one engine frame at 30 fps; the fall does not suspend scripts.
        """
        if fig.pos is None or fig.frames is None:
            return
        if fig.gravity and not fig.rises:
            lo, hi = self.hull(fig)
            if self.enter_area(fig, lo, hi):
                area = self.area_of(fig)
                sup = self.support(fig, lo, hi, area)
                thr = lo[2] - 2 * ((hi[2] - lo[2]) // 4)
                if sup < thr:
                    if fig.vz == 0 and not fig.falling:
                        fig.falling = True
                        self.fall_start(fig)
                elif fig.vz == 0 and not fig.falling and not fig.invulnerable:
                    self.whoah(fig, lo, hi, thr, area)
                if fig.falling and fig.vz > FALL_VMIN:
                    fig.vz -= FALL_DV
                if fig.vz == 0 and not fig.no_collide:
                    fig.pos[2] = sup + self.foot(fig)
        self.frame_move(fig)

    def frame_move(self, fig):
        """FUN_1088_39ef's single mover call per frame: target = the root-motion position (root_delta, accumulated by advance)
        plus the velocity step, pushed (FUN_1088_3629), then move_and_respond. The step is velocity_step of the persistent
        velocity: it moves figures without the gravity flag too, there is no friction, and every non-bouncy collision zeroes
        the velocity. A figure with nothing to move only moves when the push displaces it. A GO stride that reached its target
        (``arriving``) ends the GO once this move completes: the figure stays where it is, there is no snap to the target."""
        delta, moved = fig.root_delta, fig.root_moved
        fig.root_delta, fig.root_moved = np.zeros(2), False
        fig.step = velocity_step((fig.vx, fig.vy, fig.vz))
        target = np.array(fig.pos, float)
        target[:2] += delta
        target += fig.step
        target = self.push_target(fig, target)
        if not (moved or any(fig.step)) and target[0] == fig.pos[0] and target[1] == fig.pos[1]:
            fig.arriving = False
            return
        completed = self.move_and_respond(fig, target)
        if fig.arriving:
            fig.arriving = False
            if completed and fig.go is not None:
                fig.go = None
                m, loop, tok = fig.after_go or (STAND, True, None)
                fig.after_go = None
                if not fig.set_motion(m, loop):
                    fig.idx = 0
                if tok is not None:
                    tok['id'] = fig.mot_id

    def whoah(self, fig, lo, hi, thr, area=None):
        """FUN_10a0_009b with FUN_1060_006e: probes at the hull centre -+ the facing vector and -+ the side vector, each
        half the hull's x width long, ask point_floor (scoped to the figure's area, set from fig+0x35 at 1088:3c43) with the hull top as query z. A floor that exists but lies below the
        fall threshold plays whoah_forward / backward / left / right and marks the teeter (+0x146); while marked, the
        probes repeat and clear it once all four are fine. ASSUMPTION: float facing vectors (the engine uses its 8.8
        matrix and renormalises the side vector)."""
        cx, cy, h = (lo[0] + hi[0]) // 2, (lo[1] + hi[1]) // 2, (hi[0] - lo[0]) // 2
        hd = math.radians(fig.heading)
        dx, dy = int(math.sin(hd) * h), int(math.cos(hd) * h)        # row1 (local +Y) * h; forward is -row1
        sx, sy = int(math.cos(hd) * h), int(-math.sin(hd) * h)       # row0 (local +X) * h
        probes = (('WHOAH_FORWARD', cx - dx, cy - dy), ('WHOAH_BACKWARD', cx + dx, cy + dy),
                  ('WHOAH_LEFT', cx + sx, cy + sy), ('WHOAH_RIGHT', cx - sx, cy - sy))
        for name, x, y in probes:
            f = self.point_floor(x, y, lo[2], hi[2], area)
            if NO_FLOOR < f < thr:
                if not fig.teeter:
                    fig.teeter = True
                    fig.set_motion(name, False)
                return
        fig.teeter = False

    # ---- original key mapping (keys.py): held motions are evaluated every tick, edge actions are queued
    def key_down(self, scan, mods=0):
        """A PC scan code went down with modifier flags `mods`. Ignored while a monitor runs, except the global L / Alt+X hook."""
        self.key_mods = mods
        fig = self.player()
        if scan in self.keys_held:
            return
        self.screen_key(scan, mods)
        act = keys_mod.action(scan, mods, bool(fig and fig.combat), fig.motion if fig else None)
        if act is not None and act[0] in ('load', 'exit'):        # FUN_1128_0f7f: also reachable while a monitor is open
            self.keys_held.append(scan)
            self.global_hotkey(act[0], mods)
            return
        if self.monitor is not None or (self.options is not None and not self.options.closed):
            return
        self.keys_held.append(scan)
        if act is None or act[0] == 'motion':
            return
        if fig is not None and (fig.falling or fig.vz or fig.hold):
            # FUN_10a8_0541 (10a8:0548-058a): while +0x229 (AI OFF, a fall) or the z velocity is set (the test of the motion keys) the handler only answers S,
            # with CANNOT_SAVE. Without it a second I while PIMM_INVENTORY raises the wrist starts a second block whose AI OFF is never undone.
            if act[0] == 'save' and not self.save_busy:
                self.run_as_player('CANNOT_SAVE')
            return
        if act[0] == 'pimm' and self.vm is not None:
            held = self.held_item(fig, 'LTHAND') if fig is not None else None
            if held is not None:
                self.stow_item(fig, held)
            else:
                self.open_pimm(act[1])
        elif act[0] in ('options', 'credits', 'save'):            # FUN_10a8_0541: R, O, S
            if not self.keyboard_captured:
                self.open_options({'options': options_mod.DEFAULT, 'credits': options_mod.CREDITS, 'save': options_mod.SAVE}[act[0]])
            elif act[0] == 'save' and not self.save_busy:         # a captured keyboard: the handler only answers S, with CANNOT_SAVE
                self.run_as_player('CANNOT_SAVE')
        elif act[0] in ('oneshot', 'use', 'combat_toggle', 'pickup'):
            self.key_pending.append(act)
        else:
            self.key_log.append((self.vm.tick if self.vm else 0, act[0], act[1] if len(act) > 1 else None))
            if act[0] == 'gamma':
                self.adjust_gamma(act[1])
            elif act[0] == 'version':
                self.show_version()

    def show_version(self):
        """Alt+V (0x2f): FUN_10a8_0541 case 0x2f calls FUN_10b0_0e12 with the format string "%s  %s~%s" (1290:2c35) and
        the three static strings at 1290:4faa/4fb3/4fbd ("BioForge", "ver f1.01", "(C) 1994, 1995 Origin Systems"),
        guarded on [50d6]/[50d8] both zero (no caption process already showing). FUN_10b0_0e12/0e5a build a bare caption
        task, not a SUBTITLE/MINORSUBTITLE sound object; the port models it as a MINORSUBTITLE with no sound, which the
        existing `subtitle()` guard (`minor and live -> return 0`) already refuses while one is showing. ASSUMPTION:
        default colour 0x75, since the original's caption task does not set one explicitly."""
        self.subtitle((None, 0x75, 0xff, 'BioForge  ver f1.01~(C) 1994, 1995 Origin Systems'), minor=True)

    def global_hotkey(self, kind, mods):
        """FUN_1128_0f7f: L opens the load screen when a game runs, nothing is loading or saving, the player is alive and no
        monitor is up (Alt overrides the monitor); Alt+X opens "EXIT TO DOS?"."""
        if self.save_busy:
            return
        if kind == 'exit':
            if mods & keys_mod.ALT:
                self.open_options(options_mod.EXIT)
            return
        p = self.player()
        alive = p is None or self.hit_points(p) > 0
        monitor_up = self.monitor is not None or (self.options is not None and not self.options.closed)
        if self.vm is not None and alive and (not monitor_up or mods & keys_mod.ALT):     # ASSUMPTION: [50b8] = a game is running
            self.open_options(options_mod.LOAD)

    def hit_points(self, fig):
        """Hit points of a figure: object local ~0 (ASSUMPTION, as for DAMAGE)."""
        return self.vm.objects.get(self.object_key(fig.name), [0])[0] if self.vm is not None else 0

    def save_safe(self):
        """FUN_1128_0858: saving is unsafe while a script holds the keyboard, while a visible living figure is invulnerable
        or while a GRENADE exists."""
        if self.keyboard_captured:
            return False
        if any(f.invulnerable and not f.hidden and self.hit_points(f) > 0 for f in self.figures.values()):
            return False
        return not any(i.type == 'GRENADE' for i in self.items.values())

    def forcing_reload_on(self):
        """FUN_1100_06d4 is the negation: the script variable _forcing_reload (or the world's flag) is nonzero."""
        return bool(self.forcing_reload or (self.vm is not None and self.vm.globals.get('_forcing_reload', 0)))

    def run_as_player(self, block):
        """FUN_1120_0000(block, player): start a script block with the player figure as its object."""
        ctx = types.SimpleNamespace(cur_fig=self.player_name, cur_item=None, owner='level')
        return self.vm.spawn(block, ctx=ctx) if self.vm is not None else None

    def open_options(self, flags):
        """FUN_10a8_02cc (R / O / S / L / Alt+X keys and MON_CODE): open the options dialog with `_OPTS_*` flags unless
        a dialog already pauses the game (except _OPTS_MUST_RELOAD) or _IsExitMonRunning is set.  When saving is unsafe or
        a reload is forced, S fires CANNOT_SAVE instead, and O fires it and opens the main panel with Save disabled.
        NOT PORTED: [4e3d] / [a36a] == 0x200 dialog states and FUN_1100_0f02, which can also stop the call."""
        flags = int(flags)
        if self.vm is not None and self.vm.globals.get('_isexitmonrunning', 0):
            return None
        if self.paused and not flags & options_mod.MUST_RELOAD:
            return None
        if not self.save_safe() or self.forcing_reload_on():
            if flags & options_mod.SAVE:
                if not self.save_busy:
                    self.run_as_player('CANNOT_SAVE')
                return None
            if flags & options_mod.DEFAULT and not self.save_busy:
                self.run_as_player('CANNOT_SAVE')
            flags |= options_mod.NO_SAVE
        if self.options is not None and self.options.closed and self.options.language != self.settings.language:
            self.options = None                            # the language changed: read the texts again
        if self.options is None:
            self.options = options_mod.Options(settings=self.settings, apply_audio=self.apply_audio,
                                               apply_gamma=self.apply_gamma,
                                               slot_used=lambda n: os.path.exists(os.path.join(self.saves_dir, f'GAME{n}.IM1')))
        self.options.on_credits_page = self.credits_page_opened
        self.keys_held.clear()                             # the dialog owns the keyboard: the key that opened it gets no key_up here
        if not flags & options_mod.CREDITS:
            self.dialog_song = self.current_song()         # FUN_1100_09cb: [4e30] = the song playing now (not for the credits mode)
        return self.record_option_action(self.options.open(flags))

    def credits_page_opened(self):
        """FUN_1280_221e's tail, for the flag and the main panel's Credits button alike: unless _forcing_reload, FUN_1100_0716 (clear [50be] / [50bf]:
        FREEZE's world stop too) then FUN_1100_0740. Nothing in 1280.c / 1280_callbacks.c pauses again (only FUN_10a8_02cc sets [50be]), so leaving
        the page for the main panel leaves that panel over a running game."""
        if not self.forcing_reload_on():
            self.options.resumed = True
            self.resume_world()
            self.restart_dialog_song()

    def current_song(self):
        """FUN_1198_0029: the song playing (the last MUSIC argument), -1 when none."""
        return self.current_music if isinstance(self.current_music, int) and self.current_music >= 0 else -1

    def restart_dialog_song(self):
        """FUN_1100_0740: when a different song plays than [4e30], stop the music and restart [4e30] if it is 0 or more."""
        if self.current_song() != self.dialog_song:
            tick = self.vm.tick if self.vm else 0
            self.music_log.append((tick, -1))
            self.current_music = -1
            if self.dialog_song >= 0:
                self.music_log.append((tick, self.dialog_song))
                self.current_music = self.dialog_song

    def resume_world(self):
        """FUN_1100_0716: [50be] cleared, which ends FREEZE's stop of the world update, camera selection and the game clock. The processes FREEZE
        suspended stay so until THAW, and nothing freezes the world again when the dialog closes."""
        if self.frozen:
            now = self.vm.tick if self.vm is not None else 0
            if self.frozen_since is not None:
                self.frozen_ticks += now - self.frozen_since
                self.frozen_since = None
            self.frozen = False

    def screen_key(self, scan, mods, down=True):
        """The keys a running monitor or the options dialog takes (FUN_10e8_11e3 hands them to FUN_1250_0cf9): Tab, Shift+Tab, Return, Space,
        the arrows and Home / End / Page keys, keypad 5, L and the letter shortcuts glide the pointer or press; Escape is the dialog's own
        (option_key). Key up ends a held press."""
        dialog = self.options is not None and not self.options.closed
        mon = self.options.monitor if dialog else self.monitor
        if mon is None:
            return
        if not down:
            mon.key_release(scan)
            return
        code = monitor_mod.key_code(scan, bool(mods & keys_mod.SHIFT))
        if code is not None and not (dialog and code == monitor_mod.KEY_ESCAPE):
            mon.key_event(code, scan)

    def key_up(self, scan, mods=None):
        self.screen_key(scan, 0, down=False)
        if mods is not None:
            self.key_mods = mods
        if scan in self.keys_held:
            self.keys_held.remove(scan)
        if scan in self.keys_captured:
            self.keys_captured.remove(scan)

    def held_motion(self, fig):
        """Motion (upper case) of the most recently pressed held key that asks for one, else None. A turn request yields to a key that
        moves: 10a8:0541 tests Up and Down before Left and Right, and turn keys only ask for a motion from stand or atk_stand (1098:13e1)."""
        turn = None
        for scan in reversed(self.keys_held):
            act = keys_mod.action(scan, self.key_mods, fig.combat, fig.motion)
            if act and act[0] == 'motion':
                name = act[1].upper()
                if name not in TURN_MOTIONS and name not in ('ATK_M4', 'ATK_M6'):
                    return name
                turn = turn or name
        return turn

    def spawn_for(self, fig, block, item=None):
        if self.vm is None or block not in self.vm.blocks:
            return False
        self.vm.spawn(block, ctx=types.SimpleNamespace(cur_fig=fig.name, cur_item=item.key if item else None, owner='level'))
        return True

    def usable_objects(self, fig):
        """The IMAGs Space tries, in level order: FUN_10a8_0541 walks the figure's area list (+0x35) and tests its hull against each box
        (1070:0aba -> 1058:173c, inclusive). There is no distance, and figures are not in the list. Live, CRYO_BTN (box edge x -13939, Lex's
        hull 368 out): nothing with the hull edge at -13935, the button works with it at -13943."""
        if fig.area is None:
            return []
        lo, hi, _ = self.query_hull(fig)
        return [t['name'] for t in (self.triggers[i] for i in self.area_triggers(fig.area)) if self.boxes_touch(lo, hi, t['lo'], t['hi'])]

    def player_use(self, fig):
        """FUN_10a8_0541 Space: try left then right hand against each nearby object, then the object alone, then each item alone.
        The blocks are named after the item instance (+0xf7), not its type: "%s_%s_USE" (DS:0x2bf9) with the object and the item
        (10a8:16d0-16f1) and "%s_USE" (DS:0x2bfc) with the item alone (10a8:17f0-1803), so DANELOG (a LOGBOOK) runs DANELOG_USE.
        The type is tried next."""
        if self.vm is None:
            return None
        held = [self.held_item(fig, hand) for hand in ('LTHAND', 'RTHAND')]
        for obj in self.usable_objects(fig):
            for item in held:
                if item is None:
                    continue
                for blk in dict.fromkeys((f'{obj}_{item.name}_USE', f'{obj}_{item.type}_USE', f'{item.type}_{obj}_USE')):
                    if self.spawn_for(fig, blk, item):
                        self.key_log.append((self.vm.tick, 'use', blk))
                        return blk
            if self.spawn_for(fig, obj + '_USE'):
                self.key_log.append((self.vm.tick, 'use', obj + '_USE'))
                return obj + '_USE'
        for item in held:
            if item is not None:
                for blk in dict.fromkeys((f'{item.name}_USE', f'{item.type}_USE')):
                    if self.spawn_for(fig, blk, item):
                        self.key_log.append((self.vm.tick, 'use', blk))
                        return blk
        return None

    def toggle_combat(self, fig):
        fig.combat = not fig.combat
        blk = f'{fig.name}_{"ENTER" if fig.combat else "LEAVE"}_COMBAT'
        started = self.spawn_for(fig, blk) or self.spawn_for(fig, blk.replace(fig.name, fig.type, 1))
        self.key_log.append((self.vm.tick if self.vm else 0, 'combat', fig.combat))
        return started

    def apply_player_input(self):
        """Apply the held input without taking ownership away from scripts or AI."""
        fig = self.player()
        pending, self.key_pending = self.key_pending, []
        if self.monitor is not None or (self.options is not None and not self.options.closed):
            self.keys_held.clear()
        raw = bool(self.player_input['forward'] or self.player_input['turn'] or self.player_input['attack'] or pending or self.keys_held)
        fresh, self.input_was_active = raw and not self.input_was_active, raw     # the original's motion requests are key-down events
        if fig is None or fig.pos is None or fig.go is not None or self.ai_active(fig):
            return
        if fig.falling or fig.vz or fig.hold:   # FUN_10a8_0541: no player keys while +0x229 or the z velocity is set
            return
        for act in [a for a in pending if a[0] == 'combat_toggle']:     # the key handler toggles whatever Lex is doing; LEX_ENTER_COMBAT's first slice takes him
            pending.remove(act)
            # then FUN_1098_0745 (10a8:1065): the idle of the new mode, so leaving combat lowers the fists (LEX_LEAVE_COMBAT only
            # restores the hand textures). A block's own MOTION (LEX_ENTER_COMBAT's ENTER_COMBAT) still follows. ASSUMPTION: only from an idle.
            self.toggle_combat(fig)
            if fig.motion in (STAND, 'ATK_STAND') and self.idle_motion(fig) in fig.assets.motions:
                fig.set_motion(self.idle_motion(fig), True, engine=True)
        inp = self.player_input
        if inp['attack']:
            pending.append(('oneshot', 'shoot'))
        want = self.held_motion(fig)
        active = inp['forward'] or inp['turn'] or pending or want
        # A held pose (SNAPTOPOSE ... FREEZE) or a FREEZE'd motion (MOTION LOOK_AT_MON FREEZE at a monitor: it plays out, then its last
        # pose stays, no_idle) yields to fresh input like a finished one, and so does a script's looping MOTION ... CONTINUE nobody
        # waits on (CRYO_BTN_USE's PUSH_BUTTON): the key handler's motion gate (vtable +0x8c = 1098:12bd) refuses only during RECOIL /
        # DIE / SUPER_REC and stops any other current motion (FUN_1098_0789) for the key's motion; it tests neither the freeze flag
        # (task +0x4c, 10e0:0000) nor the end of the motion.
        # The request is made on a key-down event (FUN_10a8_0541), so only a fresh press breaks such a motion, not a key still held
        # from before (the opening's held Up through BLOCK_DRIP's DRIPPED_ON). Walk and run keys test only that gate, so they break any other
        # scripted motion too; turn and sidestep keys ask for a motion only from stand or atk_stand (1098:13e1).
        held = fig.finished or (fresh and (((fig.frozen and not fig.stopped) or fig.no_idle)
                                            or (fig.unwaited and fig.loop and fig.motion not in ('RECOIL', 'DIE', 'SUPER_REC'))
                                            or (want in TURN_WHILE_MOVING and not fig.motion_gate_refuses(want))))
        if fig.frozen and not fig.stopped and not active:
            return
        # Otherwise a script-set motion keeps the keys out, except STAND and a loop of one of the player's own key moves, which never
        # finishes (AIRMECHO's death leaves Lex in `MOTION ATK_M2 CONTINUE` with AI ON, AI_AMECH.scr:95-115)
        if not fig.manual_control and fig.motion not in (STAND, 'ATK_STAND') and fig.motion not in MANUAL_MOVES:      # (atk_stand: the combat-mode idle, FUN_1098_0745)
            if not (active and held):
                return
        if active:
            fig.manual_control = True
            if held:
                fig.set_motion(STAND, True)
        if not fig.manual_control:
            return
        playing_oneshot = (fig.motion.startswith('ATK_') and fig.motion not in MANUAL_MOVES and fig.motion != 'ATK_STAND') or fig.motion in items_mod.ITEM_MOTIONS
        if playing_oneshot and not fig.finished:
            return
        if playing_oneshot and fig.finished:
            fig.set_motion(self.idle_motion(fig), True)
        if not (fig.motion in MANUAL_MOVES or fig.motion in (STAND, 'ATK_STAND', 'ATK_SHOOT') or fig.motion in TURN_MOTIONS):
            return
        if fig.motion in TURN_WHILE_MOVING:
            turn = inp['turn'] + sum(TURN_KEYS.get(scan, 0) for scan in self.keys_held)
            fig.heading += PLAYER_TURN_PER_TICK * max(-1, min(1, turn))
        for act in pending:
            if act[0] == 'use':
                was = fig.mot_id
                self.player_use(fig)
                if fig.go is not None or self.ai_active(fig) or fig.mot_id != was:    # the use block's first slice took Lex (BIKE_USE: GO HOOD WALK; TO_TMPL_GRENADE_USE: MOTION GRENADE_TOSS)
                    return
            elif act[0] == 'pickup':
                self.player_pickup(fig)
                return
            elif act[1].upper() in ('SHOOT', 'ATK_SHOOT'):      # script-gated: LEX_ATK_SHOOT decides (unarmed = no-op)
                # the motion request FUN_1098_0e49 runs `%s_%s` (1290:299e) of the instance name +0xf7, not the form: a HARD Lex
                # still shoots through LEX_ATK_SHOOT (there is no HARD_ATK_SHOOT)
                self.spawn_for(fig, fig.name + '_ATK_SHOOT')
                return
            elif act[1].upper() in fig.assets.motions:
                fig.set_motion(act[1], False, engine=True)
                return
            else:
                self.warn(f'{fig.type} has no motion {act[1].upper()}')
        if want:
            motion = want
        elif inp['forward'] > 0:
            motion = 'RUN' if inp['run'] else 'WALK'
        elif inp['forward'] < 0:
            motion = 'WALK_BACK'
        else:
            motion = self.idle_motion(fig)
        if motion in fig.assets.motions and fig.motion != motion:
            fig.set_motion(motion, True, engine=True)    # the player's keys request lower-case names ("walk") in the original
        elif motion not in fig.assets.motions and want:
            self.warn(f'{fig.type} has no motion {motion}')

    def idle_motion(self, fig):
        """FUN_1098_0745: `atk_stand` in combat mode, else `stand`."""
        return 'ATK_STAND' if fig.combat and 'ATK_STAND' in fig.assets.motions else STAND

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def target(self, name):
        """-> (xy, z, is_figure) of a waypoint/object/figure name, or None."""
        name = self.resolve(name)
        if name in self.figures and self.figures[name].pos is not None:
            p = self.figures[name].pos
            return p[:2].copy(), p[2], True
        if name in self.points:
            p = self.points[name]
            return np.array(p[:2], float), float(p[2]), False
        f = self.figure(name)
        if f is not None and f.pos is not None:
            return f.pos[:2].copy(), f.pos[2], True
        return None

    def go_target(self, name):
        """GO's named target (FUN_10d0_33c8): a figure, else a waypoint, else an IMAG trigger, each at its reference point (vtable
        +0x50: a WAYP's position, an IMAG's box centre per axis, trunc((lo + hi) / 2)), else the remaining lists by their +0xb position."""
        key = self.resolve(name)
        if key not in self.figures and key not in self.waypoints:
            box = next((o for o in self.objs if o['tag'] == 'IMAG' and o['name'].upper() == key and 'pos2' in o), None)
            if box is not None:
                c = [int((int(a) + int(b)) / 2) for a, b in zip(box['pos'], box['pos2'])]
                return np.array(c[:2], float), float(c[2]), False
        return self.target(name)

    # ---- Sound
    def sound_index(self, ref):
        """Script sound name (or number) -> sample index, or None."""
        sm, ids = sound_bank(self.settings.language)
        if isinstance(ref, str):
            if ref.lower() in self.sound_overrides:       # REPLACESOUND / REVERTSOUND (audio.py)
                ref = self.sound_overrides[ref.lower()]
                return ref if 0 <= ref < len(sm) else None
            return ids.get(ref.lower())
        return ref if isinstance(ref, int) and 0 <= ref < len(sm) else None

    def listener_pos(self):
        """Position of the 3D view's camera (CAMR 'pos', the same level space as figure positions), or None."""
        cam = self.cameras.get(self.current_camera())
        return None if cam is None else np.asarray(cam['pos'], float)

    def positional_volume(self, fig, script_volume=255):
        """FUN_1030_04db: min(255, 65536 // q**2), q = max(1, d // 128), d = integer distance camera -> figure;
        without a camera the script volume halved."""
        cam = self.listener_pos()
        if cam is None:
            return script_volume >> 1
        q = max(1, int(np.linalg.norm(fig.pos - cam)) // 128)
        return min(255, 65536 // (q * q))

    def refresh_sound_volumes(self):
        """Per-frame refresh (FUN_1030_07cf): re-evaluate every live positional sound; log changes."""
        for h, (key, last) in list(self.sound_pos.items()):
            fig = self.figures.get(key) or self.items.get(key)      # a figure, or a missile's looped travel sound
            if self.vm is None or h not in self.vm.procs or fig is None or fig.pos is None:
                del self.sound_pos[h]
                continue
            v = self.positional_volume(fig)
            if v != last:
                self.sound_pos[h] = (key, v)
                self.log_volume(h, v)

    def play_sound(self, idx, volume=255, pitch=0, loop=False, priority=1, fig=None):
        """Log a sound event and start its handle: valid for the sample duration, or (looped sample, loop=True)
        until stopped. Takes a voice slot like FUN_1028_18f4: the first free one; with all busy, the lowest-priority
        voice (strict <, lowest index) is stopped and reused unless the new priority is lower (sound dropped).
        -> handle (0 without a VM, or dropped)"""
        sm, _ = sound_bank(self.settings.language)
        s = sm.get(idx)
        volume = min(volume, 255)
        if fig is not None:                               # positional: the script volume is replaced by the distance rule
            volume = self.positional_volume(fig, volume)
        ticks = LOOP_TICKS if loop and s.loop_end > 0 else math.ceil(sm.duration(idx, pitch) * vmmod.TPS)
        slot = None
        if self.vm is not None:
            live = lambda v: v is not None and v[0] in self.vm.procs
            slot = next((i for i, v in enumerate(self.voices) if not live(v)), None)
            if slot is None:
                slot = 0
                for i, v in enumerate(self.voices):
                    if v[1] < self.voices[slot][1]:
                        slot = i
                if priority < self.voices[slot][1]:
                    self.sound_drops.append((self.vm.tick, idx, s.name))
                    return 0
                self.stop_sound(self.voices[slot][0])
        h = self.vm.timed_handle(ticks) if self.vm is not None else 0
        if h and ticks == LOOP_TICKS:
            self.sound_loops.add(h)
        if slot is not None:
            self.voices[slot] = (h, priority)
        self.sound_log.append((self.vm.tick if self.vm else 0, idx, s.name, volume, pitch, h))
        if h:
            self.sound_handles[h] = idx
            self.voice_start(h, idx, volume, pitch, ticks == LOOP_TICKS, len(s.pcm))
            if fig is not None:
                self.sound_pos[h] = (fig.name, volume)
                self.sound_volumes.append((self.vm.tick, h, volume))
        return h

    def subtitle(self, args, minor=False, ticks=None):
        """SUBTITLE / MINORSUBTITLE (10d8:3b26 / 10d8:36ed -> FUN_10e8_0529): (sound, colour=0x75, [volume=0xff,] text).
        The voice plays non-positionally at priority 2; the subtitle object is its own handle and lives
        sample_len * 30 // 11025 + len(text) ticks. -> subtitle handle"""
        if self.vm is None:
            return 0
        live = self.cur_subtitle is not None and self.cur_subtitle[0] in self.vm.procs
        if minor and live:
            return 0
        text = max((a for a in args if isinstance(a, str) and a != args[0]), key=len, default='')
        text = presentation_mod.caption_text(text, self.settings.language)    # FUN_1120_03d2 (10e8:0529); the length counts the copy in the language in force
        num = lambda k: args[k] if len(args) > k and isinstance(args[k], int) and args[k] else None
        colour = num(1) or 0x75
        volume = (num(2) or 0xff) if len(args) > 3 else 0xff
        idx = self.sound_index(args[0]) if args else None
        sm, _ = sound_bank(self.settings.language)
        n = len(sm.get(idx).pcm) if idx is not None else 0    # ASSUMPTION: unresolved sound = sample length 0
        if live:                                          # the new subtitle replaces the old one and stops its voice (10e8:08a4)
            self.stop_sound(self.subtitle_voice)
        self.subtitle_voice = self.play_sound(idx, volume, 0, loop=False, priority=2) if idx is not None else None
        if live:
            self.vm.finish(self.vm.procs[self.cur_subtitle[0]])
            i = self.cur_subtitle[1]
            self.subtitle_log[i] = self.subtitle_log[i][:4] + (self.vm.tick,)
        if ticks is None:                                 # CAPTION passes its own lifetime
            ticks = n * 30 // 11025 + len(text)           # engine: len*60/11025 + 2*strlen in 1/60 s (11025 even for 11111 Hz)
        h = self.vm.timed_handle(ticks)
        self.cur_subtitle = (h, len(self.subtitle_log))
        self.subtitle_log.append((self.vm.tick, h, colour, text, self.vm.tick + max(ticks, 1)))
        return h

    def stop_sound(self, handle):
        p = self.vm.procs.get(handle)
        if p is not None and not p.done:
            self.vm.finish(p)
            if handle in self.sound_handles:
                self.sound_stops.append((self.vm.tick, handle))

    # ---- Engine
    def call(self, kind, name, args, proc):
        r = super().call(kind, name, args, proc)          # logs
        if name not in (MODELLED_FUNCS if kind == 'func' else MODELLED_STMTS) and not name.startswith('MON_'):
            msg = f'{name}: unmodelled {"function" if kind == "func" else "statement"} (ignored)'
            if msg not in self.unmodelled:
                self.unmodelled.append(msg)
        fig = None if name == 'CREATEFIGURE' else self.figure(proc.cur_fig)    # CREATEFIGURE must not lazily make 'PLAYER'
        if kind == 'func':
            if name in ('ANGLEFROMENEMY', 'DISTFROMENEMY', 'ATTACKRADIUS'):
                return self.combat_query(fig, name)
            if name in ('SUBTITLE', 'MINORSUBTITLE') and self.vm is not None:
                return self.subtitle(args, minor=name == 'MINORSUBTITLE')
            if name in ('SOUND', 'AMBIENT') and args:         # AMBIENT (10d8:06b2 -> FUN_10c0_32e1 -> FUN_1028_0f0a) is SOUND's twin that loops
                idx = self.sound_index(args[0])
                if idx is None:
                    return self.vm.timed_handle(SOUND_TICKS) if self.vm is not None else 0
                if proc.cur_fig and fig is None:              # FUN_1100_196c: a current figure that does not resolve = error, no sound
                    self.warn(f'{name} {args[0]}: current figure {proc.cur_fig} not found')
                    return -1
                num = lambda k, d: args[k] if len(args) > k and isinstance(args[k], int) else d   # ASSUMPTION: a non-numeric volume/pitch (e.g. an object name) means the default
                pos = fig if fig is not None and fig.pos is not None else None   # ASSUMPTION: an unplaced figure has no position -> not positional
                return self.play_sound(idx, num(1, 255), num(2, 0), loop=name == 'AMBIENT', fig=pos)     # 1028:09d3 clears the voice's loop flag +0x1d, 1028:0f0a sets it
            if name == 'GETSOUNDHANDLE' and self.vm is not None:
                idx = self.sound_index(args[0]) if args else None
                live = [h for h, i in self.sound_handles.items() if i == idx and h in self.vm.procs]
                if live:                                      # the newest live handle of that sample
                    return live[-1]
                return self.vm.timed_handle(SOUND_TICKS)
            if name == 'ISSOUNDPLAYING' and args and self.vm is not None:
                idx = self.sound_index(args[0])
                return int(idx is not None and any(i == idx and h in self.vm.procs for h, i in self.sound_handles.items()))
            if name == 'ISHANDLEPLAYING':
                return int(bool(args) and self.vm is not None and args[0] in self.vm.procs)
            if name == 'RANDOM' and len(args) >= 2 and all(isinstance(a, int) for a in args[:2]):
                return self.rng.randint(min(args[:2]), max(args[:2]))          # inclusive range (ASSUMPTION)
            if name == 'COUNTBITS' and len(args) >= 3 and all(isinstance(a, int) for a in args[:3]):
                return sum((args[0] >> b) & 1 for b in range(args[1], args[2] + 1))   # set bits lo..hi (matches GETFLAG bit n = 1 << n)
            if name == 'ISMONITORRUNNING':
                return int(self.monitor is not None or (self.options is not None and not self.options.closed))
            if name in ('MON_INVITEMFRAME', 'MON_LISTGETINDEX') and args:
                return self.monitor_func(name, str(args[0]))
            if name == 'ISLEVEL':
                return int(bool(args) and str(args[0]).upper() == self.level)
            if name == 'SETCURRENTFIGURE':                  # the VM already set the context; result = figure exists
                n = self.resolve(args[0]) if args else ''
                if n not in self.killed_figures and (n in self.figures or n in self.fig_defs):
                    return 1
                alt = self.figure_by_type(n)                # FUN_10c0_3e14: the name may also be the figure's type name
                if alt is not None:
                    proc.cur_fig = alt.name
                    return 1
                return 0
            if name in WAYPOINT_FUNCS and len(args) >= 2:
                return self.waypoint_query(proc, name, args[0], args[1])
            if name == 'SETCURRENTITEM':                    # 10c0:3fd9; the VM leaves CURITEM alone for an engine that models it
                return self.set_current_item(proc, fig, args[0]) if args else 0
            if name == 'ISCARRYING' and args:
                return int(self.is_carrying_item(fig, args[0], args[1] if len(args) > 1 else None))
            if name == 'ISCARRYINGANYTHING' and args:
                return int(self.is_carrying(fig, str(args[0]).upper()))
            if name in ('ISMYMOTION', 'ISPLAYERSMOTION', 'MOTIONEXISTS') and args:
                f = self.player() if name == 'ISPLAYERSMOTION' else fig
                if f is None:
                    return 0
                m = str(args[0]).upper()
                if name == 'MOTIONEXISTS':
                    return int(m in f.assets.motions)
                return int(f.motion == m and not f.finished)      # ASSUMPTION: a finished one-shot motion no longer counts
            if name in ('VELOCITYX', 'VELOCITYY', 'VELOCITYZ') and args:
                f = self.velocity_figure(args[0], fig, proc)     # a missing object -> 0
                if f is None:
                    return 0
                v = (f.vx, f.vy, f.vz)['XYZ'.index(name[-1])]
                low = v & 0xffff                  # FUN_10d8_3c04/3c43/3c82 return the low 16 bits (AX only)
                # ASSUMPTION: the script value is a signed 16-bit int (sign-extended back into SETVELOCITY's s32 argument)
                return low - 0x10000 if low & 0x8000 else low
            if name in ('ISHIDDEN', 'ISINVULNERABLE'):
                return int(fig is not None and getattr(fig, name[2:].lower()))
            if name == 'AMINTRIGGER' and len(args) >= 2:
                return self.am_in_trigger(proc, args[0], args[1])
            if name == 'ISCURRENTCAMERA':
                # 10d8:2aea: stricmp of the argument with the camera name [63e1] or the room name [63e5] (scripts ask ISCURRENTCAMERA BCH);
                # 1130:0114 writes both before it runs the events, so a _LOAD block already sees the new camera here
                cam = self.switching_to or self.camera or self.default_camera      # none between a level load and its first switch (1130:0048 empties [63e1])
                return int(bool(args) and cam is not None and str(args[0]).upper() in (cam, cam[:3]))
            if name in ('COORDX', 'COORDY', 'COORDZ') and args:   # 10d8:0fc6 / 100a / 104e: the object (FUN_10c0_16a8: CURFIG, CURITEM, a
                obj = self.script_object(proc, args[0])            # figure / floor item name) +0xb position component; no object: 0, no error
                opos = self.object_pos(obj) if obj is not None else None
                if opos is None:
                    return 0
                root = self.model_root_z(obj) if name == 'COORDZ' and not isinstance(obj, Item) else 0     # +0xf is origin + R; the port's origin leaves R out
                return (int(opos['XYZ'.index(name[-1])]) + root) >> 8     # FUN_1000_2727: long SAR by 8 (floor)
            if name in ('DISTFROMEXTENT', 'DISTFROMTRIGGER') and len(args) >= 2:
                return self.box_distance(proc, name, args[0], args[1])
            if name in ('DISTFROMITEM', '2DDISTFROMITEM'):
                return self.item_distance(proc, name)
            if name == '2DDISTFROMCOORDS' and len(args) >= 3:
                return self.distance_from_coords(proc, args[0], args[1], args[2])
            if name == 'FINDNEXTFIGURE':
                return self.find_figure(proc, False)
            if name == 'ISAION':                              # 10d8:27e8: the current figure's +0x229 == 0
                if fig is None:
                    self.warn('ISAION: no current figure')
                    return 0
                return int(fig.hold == 0)
            if name == 'ISGRAVITYON' and args:                # 10d8:2b57: flags (+0x34) bit 0x01
                obj = self.script_object(proc, args[0])
                if obj is None:
                    self.warn(f'ISGRAVITYON {args[0]}: no such object')
                    return 0
                return int(obj.gravity) if isinstance(obj, Figure) else 0   # the ports do not keep an item's flags byte
            if name == 'ISKEYBOARDCAPTURED':                  # 10d8:2cf3
                return int(self.keyboard_captured)
            if name in ('GETROOMAMBIENT', 'GETCAMERAAMBIENT'):   # 10d8:26a8 / 10d8:21b4: [63f6] / [63f2], -1 = none (a dead voice's handle stays)
                return (self.room_ambient if name == 'GETROOMAMBIENT' else self.camera_ambient) or -1
            if name in ('MODIFYVOLUMEOVERTIME', 'MODIFYPITCHOVERTIME'):
                return self.cmd_overtime(name, args)
            if name == 'COMPASS':
                return self.compass(fig)
            if name == 'HEADING':
                return self.motion_heading(proc, args[0] if args else 'CURFIG')
            if name == 'ISINCOMBATMODE':
                if fig is None:                               # the original reports an error; silent here, as for COMPASS
                    return 0
                return 0x40 if fig.combat else 0              # FUN_10d8_2c4f returns flags (+0x34) & 0x40, not 1
            if name == 'ISKEYPRESSED':
                # FUN_10d8_2d17: the byte at DGROUP 1290:7bbe + the argument's low byte is the key state table; the ports keep the
                # held PC scan codes (keys_held, keys_captured). ASSUMPTION: a key held while a monitor is open is not recorded (key_down drops it).
                return int(bool(args) and isinstance(args[0], int) and ((args[0] & 0xff) in self.keys_held or (args[0] & 0xff) in self.keys_captured))
            if name == 'ISMYFORM':
                # FUN_10d8_2d98: stricmp (FUN_1000_5a06) of the argument with the figure's form name at +0x1ea. An empty argument or
                # no current figure is an error (-> 0; silent for a missing figure, as for COMPASS). ASSUMPTION: +0x1ea holds the FIGR
                # record's type name, Figure.type.
                if fig is None:
                    return 0
                if not args or not str(args[0]):
                    self.warn('ISMYFORM: no form name')
                    return 0
                return int(fig.type.upper() == str(args[0]).upper())
            if name == 'AMINEXTENT' and len(args) >= 2:
                return self.am_in_extent(proc, args[0], args[1])
            if name == 'FADE':
                return self.cmd_fade(proc, args)
            if name in show_mod.FUNCS:
                return self.cmd_show_func(name, args, proc)
            if name == 'FIRE':
                return self.cmd_fire(proc, args)
            if name == 'MAKEMISSILE':
                return self.cmd_makemissile(proc, args)
            return r
        if name.startswith('MON_') or name in ('ADDENTRY', 'REMOVEENTRY'):
            self.cmd_monitor(name, args, proc)
        elif name == 'ADDLOGENTRY' and len(args) >= 2:
            log, key = args[0], args[1]
            fig = self.figure(log)
            if self.add_log_entry(log, key) and fig is not None:
                self.spawn_for(fig, str(log).upper() + '_LOG_ADDED')
        elif name == 'REMOVELOGENTRY' and len(args) >= 2:
            # MAINTMON supplies (log, current-list, key); refresh that list immediately.
            self.remove_log_entry(args[0], args[-1], args[1] if len(args) >= 3 else None)
        elif name == 'CAMERA' and args and isinstance(args[0], str):
            kw = args[0].upper()
            if kw == 'UNLOCK':                                # FUN_10d0_12f9: auto flag (1290:63da) = 1
                self.script_auto, self.candidate = True, None
            elif len(args) > 1 and str(args[1]).upper() == 'LOAD':
                pass                                          # FUN_1110_024a: loads <cam>.CAM into the resource cache and reloads the current one; no event, no switch
            elif kw in ('SHOW', 'AT') or (len(args) > 1 and str(args[1]).upper() == 'UNLOAD'):
                if kw == 'SHOW' and len(args) > 1:
                    self.shown_picture = str(args[1]).upper()     # the screen (play.to_rgb) and the options dialog's underlay (shown_picture_rgb)
                self.warn(f'CAMERA {" ".join(map(str, args))}: logged only, no switch')
            else:                                             # CAMERA <cam>: auto OFF (locked) and switch now
                self.script_auto, self.candidate = False, None
                self.set_camera(kw, 'script CAMERA (locked)')
        elif name == 'LOADLEVEL' and args:
            self.cmd_loadlevel(args, proc)
        elif name == 'KILL':
            target = fig if not args or str(args[0]).upper() == 'CURFIG' else self.figure(args[0])
            if target is not None:
                self.kill_figure(target, proc)
        elif name == 'CREATEFIGURE' and args:
            # CREATEFIGURE <type> [name] [PLAYER]: PLAYER is an argument keyword that flags the figure as the player
            words = [str(x).upper() for x in args if isinstance(x, str)]
            is_player = 'PLAYER' in words
            words = [x for x in words if x != 'PLAYER']
            if words:
                ftype, fname = words[0], (words[1] if len(words) > 1 else words[0])
                if fname not in self.figures:                 # unplaced until positioned (GO / LOADLEVEL arrival)
                    try:
                        self.figures[fname] = Figure(fname, ftype, self.asset(ftype))
                        self.figures[fname].ai_type = fname    # 1088:2608: +0x178 starts as the upper-cased name; the counter +0x229 as 0
                    except (OSError, KeyError):
                        self.warn(f'CREATEFIGURE {ftype}: no such figure type')
                    else:
                        self.killed_figures.discard(fname)     # explicit creation replaces the retired instance
                        if self.vm is not None:                # FUN_1088_22ba: a new figure's ~0 = ~5 = MAX HPS
                            hps = int(figure_prop(fname, ftype, 'MAX HPS', 100))
                            self.vm.objects[self.object_key(fname)] = [hps, 0, 0, 0, 0, hps, 0, 0, 0, 0]
                if fname in self.figures:
                    proc.cur_fig = fname                           # the created figure becomes current
                if is_player and fname in self.figures:
                    self.player_name = fname
                    self.figures[fname].view_cams = None
        elif name == 'CREATEITEM' and args:
            item_type = str(args[0]).upper()
            # 10d0:21c8 -> 1078:0130 -> vtable +0x6c: the instance name is the type; duplicates are normal (add_item keys them apart)
            proc.cur_item = self.add_item(Item(item_type, item_type, fig.name if fig else None)).key
            if self.vm is not None:
                self.vm.objects.pop(proc.cur_item, None)       # a new object starts with zeroed locals, not those of a destroyed item
        elif name == 'INDIVIDUALIZE' and len(args) >= 2 and str(args[0]).upper() == 'CURITEM':
            item = self.items.get(proc.cur_item)
            if item is not None:
                self.rename_item(item, str(args[1]).upper())
                proc.cur_item = item.key
        elif name == 'PLACEITEM' and args:
            item = self.items.get(proc.cur_item)
            if item is not None:
                self.place_item(fig, item, args[0], *args[1:])
        elif name == 'MAKEFLATOBJECT':
            self.cmd_makeflatobject(proc, args)
        elif name == 'EXPLODE':
            self.cmd_explode(proc, args)
        elif name == 'THROWCURITEM':
            self.cmd_throwcuritem(proc, args)
        elif name == 'SETFLOOROFPHYS':
            self.cmd_setfloorofphys(proc, args)
        elif name == 'TELEPORTALLONPHYS':
            self.cmd_teleportallonphys(proc, args)
        elif name in audio_mod.STMTS:
            self.cmd_audio(name, args)
        elif name == 'ANIMATE':
            self.cmd_animate(proc, args)
        elif name == 'SETREFERENT':
            self.cmd_setreferent(proc, args)
        elif name == 'INCVIRTUALSECONDS':
            self.cmd_incvirtualseconds(args)
        elif name == 'FORCERELOAD':
            self.cmd_forcereload(proc)
        elif name == 'CHANGEMYFORM':
            self.cmd_changemyform(proc, args)
        elif name == 'GRABCRITTER':
            self.cmd_grabcritter(proc, args)
        elif name == 'RELEASEFROMLIMB':
            self.cmd_releasefromlimb(proc, args)
        elif name == 'FREEHAND':
            self.cmd_freehand(proc, args)
        elif name in presentation_mod.STMTS:
            self.cmd_presentation(name, args, proc)
        elif name in show_mod.STMTS:
            self.cmd_show(name, args, proc)
        elif name == 'KILLCURITEM':
            self.kill_item_referents(self.items.pop(proc.cur_item, None), proc)
            proc.cur_item = None
        elif name == 'CAMERAAUTOACTIVATE' and len(args) >= 2 and isinstance(args[0], str):
            (self.disabled.add if str(args[1]).upper() == 'OFF' else self.disabled.discard)(args[0].upper())
        elif name == 'CAMERAFOLLOW' and args:
            a0 = args[0]
            self.follow = str(a0).upper() if isinstance(a0, str) else self.follow
        elif name == 'FINDFIRSTFIGURE':
            self.find_figure(proc, True)
        elif name == 'GRAVITY' and args:
            if str(args[0]).upper() == 'CURFIG' and fig is not None and len(args) >= 2:
                fig.gravity = str(args[1]).upper() == 'ON'      # FUN_1070_2232 / 223f only set the bit
            elif str(args[0]).upper() == 'CURITEM' and proc.cur_item in self.items and len(args) >= 2:
                item = self.items[proc.cur_item]                # the same method on an item (TEMPLE: GRAVITY CURITEM OFF)
                self.load_item_physics(item)
                item.gravity = str(args[1]).upper() == 'ON'
        elif name == 'COLLISIONS' and args:
            target = str(args[0]).upper()
            enabled = len(args) >= 2 and str(args[1]).upper() == 'ON'
            if target == 'CURFIG' and fig is not None:
                fig.no_collide = not enabled
        elif name == 'BOUNCINESS' and len(args) >= 2:
            target = str(args[0]).upper()
            target_fig = fig if target == 'CURFIG' else self.figure(target)
            if target_fig is not None:
                target_fig.bouncy = str(args[1]).upper() == 'ON'
        elif name == 'STOPVELOCITY' and args:
            target_fig = self.velocity_figure(args[0], fig, proc)
            if target_fig is not None:      # FUN_10d0_787c zeroes the velocity and the step
                target_fig.vx = target_fig.vy = target_fig.vz = 0
                target_fig.step = [0, 0, 0]
        elif name == 'SETVELOCITY' and len(args) >= 4 and all(isinstance(a, int) for a in args[1:4]):
            target_fig = self.velocity_figure(args[0], fig, proc)
            if target_fig is not None:      # FUN_10d0_7493: the three s32 arguments raw, units per 30 fps frame; the step is untouched
                target_fig.vx, target_fig.vy, target_fig.vz = (s32(a) for a in args[1:4])
        elif name == 'LEAP' and len(args) >= 3 and all(isinstance(a, int) for a in args[-2:]):
            target_fig = self.velocity_figure(args[0], fig, proc)
            if target_fig is not None:
                self.leap(target_fig, args[-2], args[-1], args[1] if len(args) >= 4 else None)
        elif name == 'LINKMETOCAMERAS' and args:
            self.link_to_cameras(proc, args)
        elif name in ('DEFINEVIEWINGCAMS', 'ADDVIEWINGCAMS') and fig is not None and fig.view_cams is not None:
            new = [str(a).upper() for a in args if isinstance(a, str)]
            if name == 'DEFINEVIEWINGCAMS':
                fig.view_cams = []
            for c in new:
                if c not in fig.view_cams and len(fig.view_cams) < MAX_VIEW_CAMS:
                    fig.view_cams.append(c)
        elif name == 'STOPSOUND' and args and self.vm is not None:
            h = self.vm.procs.get(args[0]) if isinstance(args[0], int) else None
            if h is not None and h.block.name == 'TIMED':
                self.stop_sound(h.handle)
        elif name == 'STOPAMBIENT' and args and self.vm is not None:
            # FUN_10d0_777a -> FUN_1028_10c9: a voice with the loop flag (+0x3a) is released and plays to the end of its sample
            # (audio.release_loop) while any other voice is left alone, unlike STOPSOUND (FUN_1028_0ddc), which stops it at once.
            h = self.vm.procs.get(args[0]) if isinstance(args[0], int) else None
            if h is not None and h.block.name == 'TIMED' and h.handle in self.sound_loops:
                self.release_loop(h.handle)
        elif name == 'STOPALLSOUNDS' and self.vm is not None:
            for h in list(self.sound_handles):
                self.stop_sound(h)
        elif name == 'MUSIC' and args:
            self.current_music = args[0]
            self.music_log.append((self.vm.tick if self.vm else 0, args[0]))
        elif name == 'CAPTUREKEYBOARD':                            # [6530]: show.py
            self.cmd_capturekeyboard(proc, args)
        elif name == 'RELEASEKEYBOARD':
            self.cmd_releasekeyboard()
        elif name == 'APPLY' and args:
            self.apply_decal(fig if str(args[0]).upper() == 'CURFIG' else self.figure(args[0]), args)
        elif name == 'AI' and args:
            words = [str(a).upper() for a in args]
            target = fig                                      # 10d0:04b3: the second word names the figure, or is NO_STOP_MOTION; so is a third
            if len(words) > 1 and words[1] != 'NO_STOP_MOTION':
                target = self.figure(words[1])
            if target is not None:
                self.cmd_ai(target, words[0] == 'ON', 'NO_STOP_MOTION' not in words[1:], proc)
            elif fig is not None or len(words) > 1:
                self.warn(f'AI {" ".join(words)}: no such figure')
        elif fig is None:
            pass
        elif name == 'FLOATATHEIGHT' and args:
            self.cmd_floatatheight(fig, args)
        elif name == 'SETAI' and args:
            fig.ai_type = str(args[0]).upper()
        elif name == 'INDIVIDUALIZE' and len(args) >= 2 and str(args[0]).upper() == 'CURFIG':
            self.rename_figure(fig, str(args[1]).upper(), proc)
        elif name == 'ADDAVOIDANCEPOINT' and len(args) >= 2:
            self.add_avoidance(fig, args[0], args[1])
        elif name == 'REMOVEAVOIDANCEPOINT' and args:
            self.remove_avoidance(fig, args[0])
        elif name == 'DEFINEENEMY' and args:
            fig.enemy = str(args[0]).upper()
        elif name == 'INVULNERABLE' and args:
            fig.invulnerable = str(args[0]).upper() == 'ON'
        elif name == 'COMBATMODE' and args:
            fig.combat = str(args[0]).upper() == 'ON'
        elif name == 'SPARWITHPLAYER':
            fig.spar = True
            player = self.player()
            if player is not None and player is not fig:
                fig.enemy, player.enemy = 'PLAYER', fig.name   # FUN_10d0_76c9 writes both +0x195 target pointers
        elif name == 'CONFRONTENEMY':
            self.start_confront(fig, proc)
        elif name == 'TURNTOENEMY':
            self.turn_to_enemy(fig, TURN_STEP if args else None)
        elif name == 'DAMAGE' and args:
            # FUN_10d0_230e: FUN_1090_09b9(current figure, no attacker, n, 1 with ENERGY else 0, zone 6, not heavy)
            n = next((a for a in args if isinstance(a, int)), 0)
            if fig is not None and self.vm is not None:
                self.damage(fig, None, n, int(any(str(a).upper() == 'ENERGY' for a in args if isinstance(a, str))), 6, False)
        elif name == 'GO' and args:
            self.cmd_go(fig, args, proc)
        elif name == 'FACE' and args:
            self.cmd_face(fig, args[0])
        elif name == 'TURN' and args and isinstance(args[0], int):
            fig.heading -= args[0]          # 10d0:8841 -> 10a0:19e6(fig, n << 8): n degrees, the auto-turn's routine and sign (positive = left = ANGLEFROMENEMY's sign)
        elif name == 'MOTION' and args:
            self.cmd_motion(fig, args[0], [str(a).upper() for a in args[1:]], proc)
        elif name == 'SNAPTOPOSE' and args:
            self.cmd_snaptopose(fig, args)
        elif name == 'STOPMOTION' and fig is not None:
            fig.confront = None                         # FUN_1098_0789(fig, 1, 1)
            fig.stop_motion()
        return r

    # ---- monitors (re/interp/monitor.py)
    def add_log_entry(self, log, key):
        """ADDLOGENTRY's persistent named-key store.

        The recovered handler gives the persistent store the current clock
        when it adds a key. ``*KEY`` remains one earned key and is expanded
        to repeated TEXT.FLX records by Monitor.
        """
        log, key = str(log).upper(), str(key).upper()
        entries = self.log_entries.setdefault(log, [])
        if key in entries:
            return False
        entries.append(key)
        self.log_entry_times.setdefault(log, []).append(self.game_tick)     # the award stamp is the game clock [8330]
        return True

    def remove_log_entry(self, log, key, visible_list=None):
        """REMOVELOGENTRY removes an earned key and refreshes its named open list."""
        log, key = str(log).upper(), str(key).upper()
        entries = self.log_entries.get(log, [])
        times = self.log_entry_times.get(log, [])
        kept = [(entry, stamp) for entry, stamp in zip(entries, times) if entry != key]
        self.log_entries[log] = [entry for entry, _ in kept]
        self.log_entry_times[log] = [stamp for _, stamp in kept]
        if self.monitor is not None and visible_list:
            self.monitor.set_list_entries(visible_list, self.log_entries[log], self.log_entry_times[log])

    def monitor_variable(self, name):
        """Lookup used by monitor text at render time; script variables default to zero."""
        if self.vm is None:
            return None
        name = str(name).lower()
        for key, value in self.vm.globals.items():
            if str(key).lower() == name:
                return value
        return 0

    def monitor_time(self, stamp=None):
        """Current monitor time, or the saved VM tick of an awarded journal entry."""
        tick = self.game_tick if stamp is None and self.vm is not None else (stamp or 0)        # [8330]
        return monitor_mod.format_game_time(tick, self.start_tick, self.start_date)

    def cmd_monitor(self, name, args, proc):
        """MON_* statements (handlers in seg 10d0, element code in 1250/1258).  Without a running monitor they do
        nothing, except MON_JUMP which ends the process (FUN_10d0_5896)."""
        mon = self.monitor
        strs = [str(a) for a in args if isinstance(a, str)]
        nums = [a for a in args if isinstance(a, int)]
        state = lambda: (nums[0] - 1) if nums and nums[0] else monitor_mod.NORMAL     # script value - 1, 0 -> normal
        if name == 'MON_START' and strs:
            try:
                self.monitor = monitor_mod.Monitor(strs[0], self.monitor_variable, self.monitor_time, self.monitor_viewport_frame, self.settings.language)
            except FileNotFoundError:
                self.warn(f'MON_START {strs[0]}: no such monitor')
            return
        if name == 'MON_JUMP':
            if mon is None:
                proc.ended = True
                return
            label, wait = mon.poll()
            proc.goto = label
            if wait:
                until = self.vm.tick + (1 if wait is True else wait)
                proc.wait_pred = lambda: self.vm.tick >= until
            return
        if name == 'MON_STOP':
            self.monitor = None
            return
        if name in ('MON_CODE', 'MON_SIMULATE', 'MON_DESTROYOPTIONS'):
            self.monitor_codes.append((name, nums[0] if nums else None))
            if name == 'MON_CODE' and nums:
                self.open_options(nums[0])
            elif name == 'MON_DESTROYOPTIONS' and self.options is not None:
                self.options.closed = True
            elif name == 'MON_SIMULATE' and mon is not None and nums:      # FUN_1258_017f: the key goes to the event handler with input forced on (_KB_TAB = 9)
                mon.key_event(nums[0] & 0xff, force=True)
            return
        if mon is None or not strs and name not in ('MON_HIDEALL', 'MON_ENABLEINPUT', 'MON_SET_TAB_STOPS', 'MON_SETPTRFRAME', 'MON_SETPTRPOS'):
            return
        if name == 'MON_HIDEALL':
            mon.hide_all()
        elif name == 'MON_DEFINEBUTTON':
            mon.define_button(strs[0], monitor_mod.localize(strs[1], self.settings.language) if len(strs) > 1 else None, state(), nums[1] if len(nums) > 1 else 0)
        elif name == 'MON_DEFINETEXT':
            mon.define_text(strs[0], monitor_mod.localize(strs[1], self.settings.language) if len(strs) > 1 else '', state())
        elif name == 'MON_DEFINELIST' and len(strs) > 1:
            log = strs[1].upper()
            mon.define_list(strs[0], strs[1], self.log_entries.get(log, ()), self.log_entry_times.get(log, ()))
        elif name == 'MON_DEFINETEXTAREA' and len(strs) > 1:
            mon.define_textarea(strs[0], strs[1], nums)
        elif name == 'MON_DEFINEVIEWPORT' and len(strs) > 1:
            mon.define_viewport(strs[0], strs[1])
        elif name == 'MON_SETFRAME' and nums:
            mon.set_frame(strs[0], nums[0])
        elif name == 'MON_SETSCALE' and len(nums) >= 2:
            mon.set_scale(strs[0], nums[0], nums[1])
        elif name == 'MON_SCROLLLIST' and nums:
            mon.scroll_list(strs[0], nums[0])
        elif name == 'MON_MAKEINVENTORY':
            mon.make_inventory(strs[0], [(i.name, i.type, i.key) for i in self.inventory_items()])
        elif name == 'MON_SETITEM':
            e = mon.el(strs[0])
            if e is not None and e.items and e.sel < len(e.items):
                proc.cur_item = e.items[e.sel]
        elif name == 'MON_SETPTR':
            mon.pointer['name'] = strs[0]
        elif name == 'MON_SETPTRFRAME' and nums:
            mon.pointer['frame'] = nums[0]
        elif name == 'MON_SETPTRPOS' and len(nums) >= 2:
            mon.place_pointer(nums[0], nums[1])
        elif name == 'MON_ENABLEINPUT' and nums:
            mon.set_input(nums[0])
        elif name == 'MON_SET_TAB_STOPS':
            mon.tabs = tuple(nums)
        elif name == 'ADDENTRY' and len(strs) > 1:
            mon.add_entry(strs[0], strs[1])
        elif name == 'REMOVEENTRY' and len(strs) > 1:
            mon.remove_entry(strs[0], strs[1])
        for w in mon.warnings:
            self.warn(w)
        mon.warnings.clear()

    def inventory_items(self):
        """The player's items that are in the INVENTORY slot (FUN_10d0_0000: owned by the player, not in hand), in creation order."""
        return [i for i in self.items.values() if i.owner == self.player_name and i.slot == 'INVENTORY']

    def monitor_func(self, name, list_name):
        mon = self.monitor
        if mon is None:
            return 0
        if name == 'MON_LISTGETINDEX':
            return mon.list_index(list_name)
        e = mon.elements.get(list_name.upper())          # MON_INVITEMFRAME: the selected item's `MONITOR ART FRAME`
        if e is None or e.sel >= len(e.items):
            return 0
        item = self.items.get(e.items[e.sel])
        for key in (item.name if item else e.items[e.sel], item.type if item else None):
            blk = self.vm.blocks.get(key) if key and self.vm else None
            for _, vals, _ in (blk.tables if blk else ()):
                if vals[:3] == ['MONITOR', 'ART', 'FRAME'] and isinstance(vals[-1], int):
                    return vals[-1]
        return 0

    def monitor_press(self, name):
        return self.monitor is not None and self.monitor.press(name)

    def monitor_release(self, name):
        return self.monitor is not None and self.monitor.release(name)

    def monitor_hover(self, name):
        return self.monitor is not None and self.monitor.hover(name)

    def monitor_right_click(self):
        """The right mouse button on a running monitor (monitor.Monitor.right_click): ESCAPE_BUTTON, like the Escape key. Nothing in plain play."""
        if self.monitor is not None:
            self.monitor.right_click()

    def monitor_key(self, name):
        if self.monitor is not None:
            self.monitor.key(name)

    def record_option_action(self, action):
        if action is None:
            return None
        self.option_actions.append((self.vm.tick if self.vm else 0, action))
        o = self.options
        if o is not None and o.closed and o.credits_mode:  # FUN_1100_0ae6 on a credits dialog: CREDITSSTATE is 0 (credits_state()), then CreditsRolling
            o.credits_mode = False                         # on the player; a paused (forced reload) dialog loads TITLE instead: NOT PORTED
            if not self.forcing_reload_on() and self.vm is not None and 'CREDITSROLLING' in self.vm.blocks:
                self.run_as_player('CREDITSROLLING')
        if action.startswith('difficulty:') and self.vm is not None:
            self.vm.globals['_difficulty_level'] = int(action.split(':', 1)[1])
        elif action == 'exit':
            self.exit_requested = True
        elif action.startswith(('save:', 'load:')):
            kind, slot = action.split(':')
            if kind == 'save':
                self.save_native(int(slot))
            elif self.load_native(int(slot)) is None and self.forcing_reload_on():
                self.open_options(options_mod.MUST_RELOAD)   # a failed load after a death: the reload dialog comes back
        elif action == 'unsupported:new':
            self.new_game_requested = True
        elif action.startswith('unsupported:'):
            self.warn('options ' + action.replace(':', ' ', 1) + ': not implemented in preview')
        return action

    # ---- options settings (settings.py): audio levels, gamma, subtitles
    def configure_settings(self, settings):
        """Start with `settings` (the INSTALL.OPT values, shared with the options dialog): the engine applies them at startup
        (1150.c ~830 FUN_1100_0dc2, 10f0.c ~205 FUN_1100_0e6f).  Resets the level logs."""
        self.settings, self.gamma = settings, settings.gamma
        self.sfx_log, self.music_initial, self.music_vol_log = [(0, settings.sound)], settings.music, []

    def apply_audio(self, sfx, music):
        """FUN_1100_0dc2(sfx, music), called by the audio panel for every change.  Effects: sfx < 1 stops every voice and
        disables them (FUN_1028_08f6; the mixer plays nothing), otherwise the master-volume table is rebuilt from sfx
        (settings.master_table) and scales the volume of sounds that start from the next tick on.  Music: the sequencer
        gets the level (musicseq: 0 stops and disables, > 0 enables and sets the relative volume)."""
        tick = self.vm.tick if self.vm else 0
        if sfx != self.sfx_log[-1][1]:
            if sfx < 1 and self.vm is not None:
                for h in list(self.sound_handles):
                    self.stop_sound(h)
            self.sfx_log.append((tick + 1, sfx))
        if music != (self.music_vol_log[-1][1] if self.music_vol_log else self.music_initial):
            self.music_vol_log.append((tick, music))

    def apply_gamma(self, g):
        """FUN_1100_0e6f(g): the offset (settings.gamma_offset) is added to every presented 6-bit palette channel."""
        self.gamma = g
        self.cancel_changepalette()                           # 1100:0e6f also calls 18c1(0, 0, 0)

    def adjust_gamma(self, step):
        """Shift/Alt + , . or numpad - + (FUN_10a8_0541 ~1080-1215): +-10, not above 100 / below 0 (the original refuses
        only at the limits), applied and persisted at once."""
        g = self.settings.gamma
        if step > 0 and g >= 100 or step < 0 and g <= 0:
            return
        self.settings.gamma = g + step
        self.apply_gamma(self.settings.gamma)

    def save_native(self, slot):
        """Write saves_dir/GAME<slot>.IM1 (savewrite.py): thumbnail = the room frame at save time (the native sample shows the
        room, not the dialog art), MISC/VARS/SOUNDS/LISTS/level files from the prototype state.  Limits: VM processes are not
        serialised (SCRIPT.DAT is re-emitted from the native base state, or holds only the system tasks), figure record tails
        are kept from the base, FIGR/PLAY positions and the level's ITEM records (holder, hand, floor position) are updated;
        items without a record, and a carried item when the level file has no PLAY record (a new game), are not.  Returns the path."""
        import savegame, savewrite
        base = savegame.SaveState.load(self.state_dir) if all(
            os.path.exists(os.path.join(self.state_dir, n)) for n in ('MISC.DAT', 'SCRIPT.DAT', 'VARS.DEF', 'SOUNDS.DEF', 'LISTS.FLX')) else None
        st = self.export_state()
        template = None
        shipped = os.path.join(savegame.GAMEDAT, 'CHAOS.IFF')
        if os.path.exists(shipped):                         # the new-game state's PLAY record, for a level whose file has none
            template = next((d for c, d, _ in savegame.LevelIff.parse(open(shipped, 'rb').read()).chunks if c == b'PLAY'), None)
        files = savewrite.build_files(f'GAME{slot}.IM1', self.level, self.current_camera(), self.script_auto, st['vars'],
                                      st['lists'], self.state_dir, {k: f.pos for k, f in self.figures.items() if f.pos is not None}, base,
                                      st['items'], self.figure_states(), self.player_name, template, self.process_states(),
                                      {**{n.upper(): (i.type, list(self.vm.objects.get(i.key, [0] * 10)) if self.vm else [0] * 10)
                                          for n, i in self.items.items() if not getattr(i, 'missile', False)},
                                       **{n.upper(): (m.type, [0] * 10, ([int(v) for v in m.vel], self.missile_flags(m)))
                                          for n, m in self.saved_missiles()}}, self.killed_figures,
                                      self.level_item_states())
        path = os.path.join(self.saves_dir, f'GAME{slot}.IM1')
        savewrite.write_im1(path, files, self.render())
        return path

    def load_native(self, slot):
        """Unpack saves_dir/GAME<slot>.IM1 to GAME<slot>.d and boot it with from_native_state; the result is left in
        `pending_load` for the caller's loop (a world cannot replace itself).  A missing file only warns."""
        import savegame
        path = os.path.join(self.saves_dir, f'GAME{slot}.IM1')
        if not os.path.exists(path):
            self.warn(f'load: no save in slot {slot}')
            return None
        out = os.path.join(self.saves_dir, f'GAME{slot}.d')
        savegame.Im1.unpack(open(path, 'rb').read(), out)
        self.pending_load = self.from_native_state(out)
        self.pending_load[0].configure_settings(self.settings)
        return self.pending_load

    def option_activate(self, button):
        return self.record_option_action(self.options.activate(button)) if self.options is not None else None

    def option_right_click(self):
        return self.record_option_action(self.options.right_click()) if self.options is not None else None

    def option_key(self, name):
        return self.record_option_action(self.options.key(name)) if self.options is not None else None

    def option_click(self, x, y):
        return self.record_option_action(self.options.click(x, y)) if self.options is not None else None

    def choose_default_difficulty(self):
        """Select Medium for a noninteractive opening replay, if it is waiting."""
        if self.options is not None and not self.options.closed and self.options.screen == 'difficulty':
            return self.option_activate('MEDX')
        return None

    def monitor_tap(self, name, ticks=2):
        """Press, let the script run `ticks` ticks, release, then run past the repeat delay so the script has seen
        the RELEASED event (test/CLI hook; a click that outlasts one MON_JUMP poll)."""
        ok = self.monitor_press(name)
        self.vm.run_ticks(ticks)
        self.monitor_release(name)
        self.vm.run_ticks(monitor_mod.REPEAT_DELAY + 2)
        return ok

    def open_pimm(self, screen='INVENTORY'):
        """What the key handler does for I / P / D / J (FUN_1120_0000): start block PIMM[_<screen>] as the player."""
        block = 'PIMM' + ('_' + screen.upper() if screen else '')
        ctx = types.SimpleNamespace(cur_fig=self.player_name, cur_item=None, owner='level')
        return self.vm.spawn(block, ctx=ctx)

    def start_script(self, script, block, args=()):
        if block.upper() not in self.vm.blocks and script:
            self.vm.load(os.path.join(parse.ROOT, 're', 'out', 'scripts', script.upper() + '.scr'))
        ctx = types.SimpleNamespace(cur_fig=self.player_name, cur_item=None, owner='level')
        return self.vm.spawn(block, list(args), ctx)

    # ---- combat / AI
    def object_key(self, name):
        """Key of the script object record (`NAME.~n`, `CURITEM.~n`) for a figure name; PLAYER -> the flagged player."""
        return self.resolve(name) if name else name

    def objects_for(self, fig):
        return self.vm.objects[self.object_key(fig.name)]

    def is_carrying(self, fig, slot, item_type=None):
        """Whether the current figure has a matching item in `slot`.

        `ANYWHERE` means any slot owned by the figure, as used by the original
        inventory scripts.  This deliberately models only item placement, not UI
        selection or physics attachments.
        """
        if fig is None:
            return False
        return any(item.owner == fig.name and (slot == 'ANYWHERE' or item.slot == slot)
                   and (item_type is None or item.type == item_type)
                   for item in self.items.values())

    def enemy_of(self, name):
        f = self.figures.get(self.resolve(name)) if name else None
        return f.enemy if f and f.enemy else None

    def enemy_fig(self, fig):
        return self.figure(fig.enemy) if fig is not None and fig.enemy else None

    def radius_cm(self, fig):
        """ATTACKRADIUS (10d8:0e28): the current figure's PERSONAL_RADIUS (+0x1e3, hull-scale world units, see personal_radius)
        converted like every distance function, cm_from_units. (Earlier versions assumed half the STAND pose's horizontal extent.)"""
        return cm_from_units(personal_radius(fig))

    def rel_angle(self, fig, pos):
        """Signed bearing of `pos` relative to the figure's facing in degrees: positive = to the figure's LEFT
        (counter-clockwise seen from above, +z up), which is what MONSTER_MOVE's `~2 > 0 -> TURN LEFT` expects."""
        d = np.asarray(pos[:2], float) - fig.pos[:2]
        f = fig.forward()
        return math.degrees(math.atan2(f[0] * d[1] - f[1] * d[0], f @ d))

    def combat_query(self, fig, name):
        e = self.enemy_fig(fig) if name != 'ATTACKRADIUS' else fig
        if fig is None or e is None or fig.pos is None or e.pos is None:
            return 0
        if name == 'ATTACKRADIUS':
            return self.radius_cm(fig)
        if name == 'DISTFROMENEMY':       # FUN_10a0_1e61: the 2D fixed-point length of (enemy - figure) +0xb/+0xf, then cm_from_units
            return cm_from_units(length2d(*(int(round(c)) for c in e.pos[:2] - fig.pos[:2])))
        return int(round(self.rel_angle(fig, e.pos)))

    def start_confront(self, fig, proc):
        """CONFRONTENEMY (10d0:1c9b): a turn_to_enemy task (FUN_10e8_0000), and the caller waits for it (FUN_1238_0f48). No enemy: an error, nothing happens. ASSUMPTION: a figure
        without its turning motions (the error path of vtable +0x7c is not read) faces the enemy at once, as does a call outside a process."""
        if self.enemy_fig(fig) is None or fig.pos is None:
            return
        wanted = ('ATK_M4', 'ATK_M6') if fig.combat else ('TURN_LEFT', 'TURN_RIGHT')
        if proc is None or fig.frames is None or not all(m in fig.assets.motions for m in wanted):
            self.turn_to_enemy(fig, None)
            return
        task = fig.confront = {'settled': False, 'count': 0}
        proc.wait_pred = lambda: fig.confront is not task or self.figures.get(fig.name) is not fig

    def update_confront(self, fig):
        """FUN_10e8_0079, once per update: a bearing under 8/256 of a turn ends the motion (FUN_1098_0789(fig, 0, 0)) and turns the rest at once; two updates later the task ends.
        Otherwise it asks for atk_m4 / atk_m6 (turn_left / turn_right out of combat, flag 0x40) through vtable +0x7c unless that already plays; the motion gate holds it off during
        a recoil. The bearing counts the turning motion's yaw so far, as the task reads it from the model (+0x25)."""
        task = fig.confront
        if task['settled']:
            task['count'] += 1
            if task['count'] == 2:
                fig.confront = None
            return
        enemy = self.enemy_fig(fig)
        if enemy is None or enemy.pos is None:
            fig.confront = None
            return
        yaw = (fig.frames[fig.idx][2][0][2] - fig.frames[0][2][0][2]) * 45 / 32 if fig.turning() else 0
        angle = self.rel_angle(fig, enemy.pos) - yaw
        if abs(angle) < CONFRONT_DONE:
            self.stop_figure(fig, tasks=False)
            self.turn_to_enemy(fig, None)
            task['settled'] = True
            return
        left, right = ('ATK_M4', 'ATK_M6') if fig.combat else ('TURN_LEFT', 'TURN_RIGHT')
        want = left if angle > 0 else right
        if fig.motion != want and not fig.motion_gate_refuses(want):
            fig.set_motion(want, True, engine=True)

    def turn_to_enemy(self, fig, step):
        """TURNTOENEMY TEN_DEGREES turns up to `step` degrees per call toward the enemy; without argument the figure faces it at once (ASSUMPTION, 10d0:8c53 not read)."""
        e = self.enemy_fig(fig)
        if e is None or fig.pos is None or e.pos is None:
            return
        a = self.rel_angle(fig, e.pos)
        fig.heading -= a if step is None else max(-step, min(step, a))      # +heading turns clockwise (right), a > 0 is to the left

    def auto_turn(self, fig):
        """FUN_1088_3419, called by FUN_1088_39ef for the player in combat mode (flag 0x40) while a game runs: every
        AUTO_TURN_SPEED (FIGURES.SCP, +0x1df; Lex 1) calls, during atk_stand or shoot, turn
        min(|a| >> 1, 6) degrees toward the enemy when its bearing a (rel_angle, positive = left) has 3 <= |a| < 55.
        ASSUMPTIONS: a is rounded to whole degrees like DISTFROMENEMY's bearing; the counter resets whenever it reaches the
        speed, whether or not the motion allows a turn."""
        e = self.enemy_fig(fig)
        if self.vm is None or fig is not self.player() or not fig.combat or e is None or e.pos is None or fig.pos is None:
            return
        speed = int(form_prop(fig, 'AUTO_TURN_SPEED', 0))
        if speed < 1:
            return
        fig.auto_turn_count += 1
        if fig.auto_turn_count < speed:
            return
        fig.auto_turn_count = 0
        m = fig.motion.lower()
        if m not in ('atk_stand', 'shoot'):    # 1088:3419 also tests for "atk_m" (DS:2595) with a case-sensitive compare, but the keys name them "atk_M8" (DS:2b34), so it never matches
            return
        a = int(round(self.rel_angle(fig, e.pos)))
        if 2 < abs(a) < 0x37:
            step = min(abs(a) >> 1, 6)
            fig.heading -= step if a > 0 else -step      # +heading turns right; a > 0 is to the left

    def cmd_ai(self, fig, on, stop=True, proc=None):
        """AI ON / OFF (10d0:04b3). The counter +0x229 is what counts: ON is vtable +0xa0 (FUN_1088_31fb; refused without hit points, 0xea),
        OFF is vtable +0x9c (FUN_1088_3196), which pauses the AI process rather than ending it, and at the first OFF stops the figure as
        STOPMOTION does (FUN_1098_0789(fig, 1, 1)) unless NO_STOP_MOTION. A process that turned off its own figure's AI yields at once."""
        if on:
            rec = self.vm.objects.get(self.object_key(fig.name)) if self.vm is not None else None
            if rec is not None and rec[0] <= 0:
                # ASSUMPTION: a figure with no object record at all (the lazily made PLAYER of a scenario that never CREATEFIGUREd Lex: the
                # original always has its MAX HPS) counts as alive
                self.warn(f'AI ON: {fig.name} is dead')
                return
            self.fall_end(fig)
            if fig is self.player() and fig.hold == 0:        # the player's +0xa0 (10a8:1f2e) then requests its idle (FUN_1098_0745)
                self.request_idle(fig)
            return
        self.die_method(fig, stop)
        if fig.hold == 1 and stop:
            self.stop_figure(fig)
        if proc is not None and proc is fig.ai_proc:
            proc.yield_now = True

    def request_idle(self, fig):
        """FUN_1098_0745 from a script command: vtable +0x7c = 1098:0e49(fig, "atk_stand" / "stand", 1, 0) creates the motion task without
        running it (param 5 is 0), and only its run (10e0:0055) starts the motion on the model. Made during a walk, the task first runs in
        the next walk (1238:024c -> 1230:177a), so the figure update in between keeps the old motion and its R (live: LEAVETUBEROOM's AI ON
        before TO_0G_USE's STOPMOTION and GO, re/NOTES.md "Lex's height in the zero-g room"). Outside a walk it starts at once."""
        name = 'ATK_STAND' if fig.combat else STAND
        if self.vm is not None and self.vm.walking:
            fig.pending_idle = (name, self.vm.tick)
        else:
            fig.set_motion(name, True, engine=True)

    def start_pending_idles(self):
        """At the end of a walk (VM.tick_once): an idle requested in an earlier walk has had its task's first run in this one (its slot
        among the scripts is not modelled: a STOPMOTION or a new motion earlier in the walk has already dropped it)."""
        for fig in self.figures.values():
            if fig.pending_idle is not None and fig.pending_idle[1] < self.vm.tick:
                name, fig.pending_idle = fig.pending_idle[0], None
                fig.set_motion(name, True, engine=True)

    def stop_figure(self, fig, tasks=True):
        """FUN_1098_0789 as AI OFF and the hide pass use it: does nothing while DIE is the current, unfinished motion, else ends the motion
        and GO. Unlike STOPMOTION it keeps the idle-fallback bit 0x80 (Figure.no_idle), so a living figure with a motion goes to its idle
        at its update's end (1088:4167, FUN_1098_0745: atk_stand in combat mode, else stand); READY_MONSTER_TAUNT waits for that."""
        if (fig.motion == 'DIE' and not fig.finished) or fig.frames is None:
            return
        if tasks:
            fig.confront = None                         # the first argument, 1: FUN_1088_3229 also ends the class 0x109 tasks; turn_to_enemy's own stop passes 0
        fig.idle_request = not fig.no_idle
        fig.stop_motion()

    def start_enabled_ai(self, fig):
        """FUN_1088_3371, the figure update's AI start: visible, alive, counter 0 and no process yet runs "<+0x178>_AI"; a name without a
        block starts nothing, silently (FUN_1120_0000), and is tried again next frame. An ended process clears +0x152 (10c0:4098)."""
        p = fig.ai_proc
        block = f'{fig.ai_type}_AI'
        if self.vm is None or fig.hold or not fig.ai_type or block not in self.vm.blocks or fig.hidden or fig.pos is None \
                or self.hit_points(fig) <= 0 or (p is not None and not p.done):
            return
        ctx = types.SimpleNamespace(cur_fig=fig.name, cur_item=None, owner='level')
        fig.ai_proc = self.vm.spawn(block, ctx=ctx, run=False)

    def update_hidden(self, fig, cam):
        """1130:050d-..., the camera switch's show / hide pass over the figures but the followed one and the player: not viewed by the camera
        (FUN_1088_54e0, so an empty list hides) stops the motion (FUN_1098_0789(fig, 1, 0)), hides and pauses the AI process; viewed again
        shows and, with the counter at 0, resumes it. ASSUMPTION kept from "STOPMOTION and hidden figures": evaluated per frame."""
        hidden = fig.exploded or (fig.view_cams is not None and cam is not None and cam not in fig.view_cams)
        if fig.exploded:
            fig.hidden = True
        if fig.name == self.resolve(self.follow) and not fig.exploded:
            fig.hidden = False                            # CAMERAFOLLOW shows the figure it follows (1130:00c1, vtable +0x68)
        if hidden == fig.hidden or fig.name in (self.resolve(self.follow), self.player_name) or (self.camera is None and fig.view_cams is not None):
            return                                        # (no camera switched to yet: current_camera()'s fallbacks are the port's)
        fig.hidden = hidden
        p = fig.ai_proc if fig.ai_proc is not None and not fig.ai_proc.done else None
        if hidden:
            self.stop_figure(fig)
            if p is not None:
                p.suspended = True
        elif p is not None and fig.hold == 0:
            p.suspended = False
        if p is not None and p.cameras:                   # 1130:0549 runs the camera links after this pass (the bot AIs link themselves): the list decides
            p.suspended = cam not in p.cameras

    def ai_active(self, fig):
        return fig.ai_proc is not None and not fig.ai_proc.done

    def rename_figure(self, fig, new, proc):
        old = fig.name
        if new == old:
            return
        self.figures = {(new if k == old else k): v for k, v in self.figures.items()}
        fig.name = new
        if self.player_name == old:
            self.player_name = new
        proc.cur_fig = new
        if self.vm is not None:
            self.vm.rename_object(old, new)

    HIT_ZONES = ('TL', 'TR', 'ML', 'MR', 'BL', 'BR')

    def limb_geometry(self, fig):
        """-> (limb end positions in world units, unit limb directions): salsa.solve of the figure's current frame, placed
        like the renderer places its vertices (posed: root x,y zeroed, root z kept, rotated by -heading, plus pos).
        (The frame record's bytes 12..17 are the guard table, not a rotation; salsa.solve ignores them.)"""
        p, _, l = fig.frames[min(fig.idx, len(fig.frames) - 1)]
        _, R, end = salsa.solve(fig.assets.skel, ((0, 0, p[2]), (0, 0, 0), l))
        return (place(np.array(end), fig.pos, -fig.heading),
                place(np.array([m[1] for m in R]), np.zeros(3), -fig.heading))

    def col_hit(self, fig, pt, geom):
        """FUN_10b0_0031: `pt` against the figure's .COL cubes (centre = the limb's end for mode 0, else its midpoint,
        end - row1 x scaled length / 2; hit when all three axis offsets are below the half-size)."""
        ends, dirs = geom
        for limb, mode, half in fig.assets.col:
            if limb >= len(ends):
                continue
            c = ends[limb] if mode == 0 else ends[limb] - dirs[limb] * (fig.assets.skel[limb].length / 2)
            if np.all(np.abs(pt - c) < half):          # scale 0x100 = 1: the port has no per-limb scale
                return True
        return False

    def update_hit(self, fig):
        """FUN_1088_0708, run each figure update after the frame advance: a kind-1 (strike) motion with an enemy checks
        the striking limb against the enemy's .COL volumes on frames 4 .. nframes-5, until one hit lands in this play
        (fig.hit_done, cleared by set_motion). ASSUMPTION: a looping motion's restart also clears the flag (advance());
        a frozen (held) figure does not strike. The start-blend condition (+0x128) is not modelled (the port has none)."""
        info = fig.assets.motion_info.get(fig.motion)
        if self.vm is None or fig.hit_done or fig.frozen or fig.pos is None or info is None or info[4] != 1:
            return
        n, f = len(fig.frames), fig.idx
        e = self.enemy_fig(fig)
        if not (f > 3 and n - (f + 1) > 3) or e is None or e.pos is None or e.frames is None:
            return
        player = self.player()
        if player is not None and fig is not player:
            player.enemy = fig.name                    # the engine writes the player's enemy pointer (+0x195)
        limb = info[3]
        geom = self.limb_geometry(fig)
        if limb >= len(geom[0]):
            return
        egeom = self.limb_geometry(e)
        end = geom[0][limb]
        # the limb's end, else one more limb length along the limb
        pt = next((q for q in (end, end + geom[1][limb] * fig.assets.skel[limb].length) if self.col_hit(e, q, egeom)), None)
        if pt is None:
            return
        fig.hit_done = True
        zone = self.hit_zone(e, fig, pt[2], egeom)
        # the enemy's current frame record bytes 12..17 are the guard table (the "root angle" words), one byte per zone
        guard = struct.pack('<3h', *e.frames[min(e.idx, len(e.frames) - 1)][1])[zone] & 3
        if guard == 2 and abs(self.rel_angle(e, fig.pos)) < 110:
            self.hit_sound('_metal_clank_1')           # blocked: no damage dispatch (1088:0708 -> FUN_1100_1d34: not positional)
            self.hits.append((self.vm.tick, fig.name, e.name, fig.motion, 'BLOCKED'))
            return
        self.damage(e, fig, info[2], 0, zone, guard == 1 or info[2] > 19)

    def hit_zone(self, e, attacker, z, egeom):
        """Zone index of a hit at height `z` on enemy `e`: h = F x 0.16 in the engine's integer form; z above the enemy's
        root limb end z + h is top (0), below root z - h bottom (4), else middle (2); +1 when the attacker is on the
        enemy's right (negative bearing, FUN_1088_5ee1). Names: HIT_ZONES."""
        h = int(((self.foot(e) * 0x1000 // 256) << 8) / 0x6400)
        rootz = egeom[0][0][2]
        return (0 if z > rootz + h else 4 if z < rootz - h else 2) + int(self.rel_angle(e, attacker.pos) < 0)

    def raise_label(self, fig, label, dmg):
        """FUN_1090_12a6: run `<figure>_STIMULUS` at `label` with _DAMAGE = dmg; True iff the label exists (a block without
        it is not run)."""
        ctx = types.SimpleNamespace(cur_fig=fig.name, cur_item=None, owner='level')
        return self.vm.spawn_at(fig.name + '_STIMULUS', label, [dmg], ctx) is not None

    def material(self, fig):
        """FIGURES.SCP MATERIAL of the figure's TYPE block (fig+2 is the type name), or None."""
        values = figure_props().get(fig.type.upper(), {}).get('MATERIAL')
        return str(values[0]).upper() if values else None

    def hit_sound(self, name, fig=None):
        """FUN_1100_1ce4 (positional at `fig`) / FUN_1100_1d34 (fig None: not positional) -> 1100:1c3e: the name goes through 1118:0044
        (`ambient_id`: cut at the last `_` until the bank has it, so `_CAYNAN_HITS_LEX_CE31` plays `_CAYNAN_HITS_LEX`; nothing left plays
        nothing), priority 1, volume 255, pitch 0."""
        idx = self.ambient_id(name)
        if idx >= 0:
            self.play_sound(idx, fig=fig if fig is not None and fig.pos is not None else None)

    def run_figure_block(self, fig, block):
        """FUN_1120_0000: run script block `block` with `fig` as the current figure; a missing block does nothing."""
        return self.spawn_for(fig, block)

    def die_method(self, fig, end_task):
        """FUN_1088_3196 (figure vtable +0x9c, the same call FUN_10a0_0072 makes when a fall starts): +0x229++, the figure's
        script process suspended and player input ignored (apply_player_input). NOT PORTED: with `end_task` the engine also ends
        the figure's task +0x15b (not identified)."""
        fig.hold += 1
        if fig.ai_proc is not None and not fig.ai_proc.done:
            fig.ai_proc.suspended = True

    def damage(self, target, attacker, dmg, type, zone, heavy):
        """FUN_1090_09b9(target, attacker, dmg, type, zone, heavy): type 0 impact, 1 energy; `attacker` may be None (the DAMAGE
        statement) and zone 6 means no zone. Appends to self.hits. Without an attacker the ELITE check, knockback and every label
        raised on the attacker are skipped and its motion name reads "Unknown".
        NOT PORTED: FUN_1258_0f8b() for a player target (a HUD refresh, as far as known)."""
        zname, ran = (self.HIT_ZONES[zone] if zone < 6 else None), []

        def raise_(fig, label):
            ok = self.raise_label(fig, label, dmg)
            if ok:
                ran.append(label)
            return ok

        def record():
            self.hits.append((self.vm.tick, attacker.name if attacker else None, target.name,
                              attacker.motion if attacker else 'Unknown', ran[-1] if ran else ''))

        is_player = target is self.player()
        tmat = self.material(target)
        if attacker is not None and 'ELITE' in (attacker.name.upper(), attacker.type.upper()):
            if not target.invulnerable:
                raise_(attacker, 'HIT_PLAYER_FOR_ZERO')
            record()
            return
        hp = self.objects_for(target)
        if hp[0] <= 0:
            return
        if attacker is not None and target.bouncy and not target.invulnerable:
            # knockback: velocity (+0xc6/+0xca/+0xce) -= the attacker's orientation row 1 (FUN_1090_09b9; 256 = 1.0). Row 1 is the
            # figure's BACKWARD vector (-forward()), so the target is pushed away from the attacker at 256 units per frame
            row1 = self.orientation(attacker)[1]
            target.vx -= row1[0]
            target.vy -= row1[1]
            target.vz -= row1[2]
        d = int(self.vm.globals.get('_difficulty_level', 0))
        dmg += (-4 if d == 0 else 4 * d) if is_player else -4 * d
        if target.invulnerable or dmg < 1:
            te = self.enemy_fig(target)
            if te is not None:
                raise_(te, 'HIT_PLAYER_FOR_ZERO')
            raise_(target, 'HIT_FOR_ZERO')
            amat = self.material(attacker) if attacker is not None else None
            self.hit_sound(f'_BLOCK_{tmat}_{amat}' if attacker is not None else f'_BLOCK_{tmat}')     # FUN_1100_1d34: not positional
            record()
            return
        armor = 'ENERGY_ARMOR' if type == 1 else 'IMPACT_ARMOR'
        dmg = max(0, dmg - int(form_prop(target, armor, 0)))
        prev = hp[0]
        hp[0] -= dmg
        hp[7] = max(0, hp[7] - dmg)
        tmotion, amotion = target.motion, attacker.motion if attacker else 'Unknown'      # names before the cancel
        cancel = not (tmotion == 'DIE' and not target.finished)
        if cancel:
            target.stop_motion()        # FUN_1098_0789(target, 1, 0): ends the script-started motion task (STOPMOTION's equivalent)
        if type == 1:
            raise_(target, 'ENERGY_DAMAGE')
            pe = self.enemy_fig(target) if is_player else None
            if pe is not None:
                raise_(pe, 'KILLED_PLAYER' if hp[0] <= 0 else 'PLAYER_ENERGY_DAMAGE')
        if attacker is not None:
            self.hit_sound(f'_{self.material(attacker)}_HITS_{tmat}_{self.current_camera()}', target)
        if is_player and attacker is not None and hp[0] <= 0:
            self.die_method(attacker, True)             # 1090:0e36: the player's killer gets the die method too (AI suspended, hold++)
        if hp[0] > 0:
            if zname is None or not raise_(target, f'GOT_HIT_{zname}_{tmotion}'):
                if zname is not None:
                    raise_(target, f'GOT_HIT_{zname}')
            raise_(target, 'GOT_HIT')
            for limit in (75, 50, 25):                  # crossing below a quarter threshold
                if prev > limit - 1 and hp[0] < limit:
                    raise_(target, f'MY_HPS_{limit}')
                    if is_player and attacker is not None:
                        raise_(attacker, f'PLAYERS_HPS_{limit}')
            if heavy:
                if is_player:
                    if attacker is not None:
                        raise_(attacker, 'PLAYER_SUPER_RECOILED')
                else:
                    raise_(target, 'SUPER_RECOIL')
            if is_player and attacker is not None:
                raise_(attacker, 'HIT_PLAYER')
                raise_(attacker, f'HIT_PLAYER_{amotion}')
            if cancel and hp[3] == 0 and zname is not None:   # a motion task still running (an unfinished DIE) blocks the recoil
                kind = 'SUPER_REC' if heavy else 'RECOIL'
                name = next((m for m in (f'{kind}_{zname}', 'RECOIL_TL' if zname[1] == 'L' else 'RECOIL_TR')
                             if m in target.assets.motions), None)
                if name is not None and target.go is None:     # ASSUMPTION: a walking figure (GO) is not interrupted
                    target.manual_control = False
                    target.confront = None                      # FUN_1098_0789(target, 1, 0) -> FUN_1088_3229: the hit ends its class 0x109 tasks, turn_to_enemy too
                    target.set_motion(name, False)              # plays once (cmd_motion would loop the turning RECOIL_*)
                    target.task_name = name                     # +0x15f: what the motion gate (FUN_1098_12bd) refuses a script's MOTION for, as a taunt's tail asks
                    target.recoil_id, hp[3] = target.mot_id, 1
        # <TYPE>_WOUNDS runs for a living and a dead target alike; a dead one then gets the death method and <INSTANCE>_DEATH
        self.run_figure_block(target, f'{target.type.upper()}_WOUNDS')
        if hp[0] <= 0:
            if is_player and attacker is not None:
                raise_(attacker, 'KILLED_PLAYER')
            self.die_method(target, True)
            target.invulnerable = True
            self.run_figure_block(target, f'{target.name.upper()}_DEATH')
        record()

    def fire_event(self, block):
        """Engine-raised script event: start `block` if the loaded scripts define it (logged in self.events)."""
        if self.vm is not None and block in self.vm.blocks:
            self.events.append((self.vm.tick, block))
            self.vm.fire(block)

    def arrival_point(self, name):
        """-> (xy, floor z) of a WAYP, else of any other named object (ASSUMPTION: a volume such as IMAG
        FRM_PAD arrives at the centre of its box in x/y, on its lowest z), else None."""
        objs = [o for o in self.objs if o['name'].upper() == name]
        o = next((o for o in objs if o['tag'] == 'WAYP'), objs[0] if objs else None)
        if o is None:
            return None
        if 'pos2' not in o:
            return o['pos'][:2].copy(), float(o['pos'][2])
        lo, hi = np.minimum(o['pos'], o['pos2']), np.maximum(o['pos'], o['pos2'])
        return (lo[:2] + hi[:2]) / 2, float(lo[2])

    def level_volume(self, name):
        """The volume word 2 of an elevator LOADLEVEL names (FUN_10d0_4d46, 10d0.c:4336): the IMAG of that name, else the PHYS. -> (lo, hi) or None."""
        for tag in ('IMAG', 'PHYS'):
            o = next((o for o in self.objs if o['tag'] == tag and o['name'].upper() == name and 'pos2' in o), None)
            if o is not None:
                return np.minimum(o['pos'], o['pos2']), np.maximum(o['pos'], o['pos2'])
        return None

    def place_after_level_change(self, fig, x, y, z, zq, dest, first_done=False):
        """FUN_1088_2dfc after the attach (1070:0755): unless collisions are off, up to 21 tries of SetPos (FUN_10a0_1ff0, GO's floor rule:
        gravity on = the floor under the point + F, else z as is) and, while the hull is blocked by the PHYS (FUN_1058_1a1b), a step of 204
        units in x and in y toward the destination point `dest` (x <= Dx steps +, else -). `z` is the position's own z, `zq` the z the floor
        is looked up from; `first_done`: the position already is the first SetPos's result (the arrival code below)."""
        fig.pos = np.array([x, y, z], float)
        fig.go, fig.manual_control, fig.vx, fig.vy, fig.vz, fig.step = None, False, 0, 0, 0, [0, 0, 0]
        if fig.no_collide:
            return
        for i in range(21):
            if fig.gravity and not (i == 0 and first_done):
                floor = self.point_floor(int(fig.pos[0]), int(fig.pos[1]), int(zq), int(zq))
                fig.pos[2] = (floor if floor > NO_FLOOR else zq) + self.foot(fig)
            self.select_area(fig)                    # SetPos places the figure in an area (FUN_1138_1a93): the PHYS test is that area's
            lo, hi, _ = self.query_hull(fig)         # the hull at +0x65 as FUN_10a0_21b2 stores it
            area = self.area_members(fig.area)
            if self.collision_score(np.array(lo), np.array(hi), self._phys_boxes() if area is None else area) <= 0:
                break
            fig.pos[0] += 204 if fig.pos[0] <= dest[0] else -204
            fig.pos[1] += 204 if fig.pos[1] <= dest[1] else -204
            zq = fig.pos[2]

    def cmd_loadlevel(self, args, proc):
        """LOADLEVEL <level> [<arrival> | <volume> <destination>] (handler FUN_10d0_4d46): first destroys every missile (end_missiles_for_level_change).
        The elevator form looks the volume up (IMAG, then PHYS; neither: error 0x8b, the caller ends and nothing loads), and every non-player figure
        and every floor item whose hull / EXTENT box overlaps it, and the player (whether or not he is inside), keep their offset from the volume
        (x, y from its centre, z from its floor): they arrive at the destination point + that offset (1060:0df8 detach, 1070:0755 attach).
        Stops every sound handle but the one the first numeric argument names (FUN_1028_12d2, 10d0.c:4401: ELEVATOR.scr's `_sfx_5` hum keeps
        playing across the ride; the original runs it after the load and before the kill walk, the port before the walk: no script runs in
        between), then kills every script process but the caller's CALL chain (FUN_10b0_13fb: no exemption for the boot chain; the caller
        continues only if its script file is part of the new level: VM.end_unloaded), swaps in the new level's scripts and objects, places PLAYER at the arrival point (as GO
        places him) or at his offset, then fires <LEVEL>_LOAD."""
        self.end_missiles_for_level_change()
        level = str(args[0]).upper()
        if not os.path.exists(os.path.join(self.state_dir, level + '.IFF')):
            self.warn(f'LOADLEVEL {level}: no such level')
            return
        arrival = str(args[1]).upper() if len(args) > 1 and isinstance(args[1], str) else None
        carried, carried_items, rel_player = [], [], None
        if len(args) > 2 and arrival and isinstance(args[2], str):       # LOADLEVEL <level> <volume> <x> (a number here is the kept sound handle): the volume's figures and items travel at their offsets
            vol = self.level_volume(arrival)
            if vol is None:
                self.warn(f'LOADLEVEL {level} {args[1]} {args[2]}: no volume {arrival} (error 0x8b): the caller ends, no level change')
                if proc is not None and self.vm is not None:
                    self.vm.finish(proc)
                return
            lo, hi = vol
            ref = np.array([int((lo[0] + hi[0]) / 2), int((lo[1] + hi[1]) / 2), int(lo[2])], float)     # the volume's vt+0x50 point, its floor
            def touches(blo, bhi):
                return all(blo[k] <= hi[k] and bhi[k] >= lo[k] for k in range(3))        # FUN_1058_173c, inclusive
            for k, f in self.figures.items():
                if k != self.player_name and f.pos is not None and touches(*self.query_hull(f)[:2]):
                    carried.append((f, f.pos - ref))
            for it in self.items.values():
                if it.owner is None and it.pos is not None and not it.missile:
                    self.load_item_physics(it)
                    if touches([it.pos[k] - it.extent[k] for k in range(3)], [it.pos[k] + it.extent[k] for k in range(3)]):
                        carried_items.append((it, it.pos - ref))
            if self.player() is not None and self.player().pos is not None:
                rel_player = self.player().pos - ref
            if isinstance(args[2], str):    # 10d0:4d46 hands the third word (+700), not the volume, to 1148:15c7 as the destination (1050:0c65)
                arrival = args[2].upper()
        self.pal_installed = np.zeros((256, 3), np.int32)    # 1148:1a76 -> 1130:147c -> 10e8:1a9e(0, 0): an all-black palette is pending until the camera's (palette_cut)
        if arrival is None:
            self.warn(f'LOADLEVEL {level}: no arrival point (engine requires one); PLAYER keeps its position')
        keep_voice = next((a for a in args if isinstance(a, int)), None)         # 10d0:4d46's first numeric argument (ctx+0xe2b): the voice to keep
        for h in list(self.sound_handles):
            if h != keep_voice:
                self.stop_sound(h)                    # FUN_1028_12d2: every other voice stops; the mixer ends it (sound_stops)
        self.vm.kill_level_owned(proc, keep_voice if keep_voice in self.sound_handles else None)
        self.vm.unload_scripts()
        vmmod.load_level(self.vm, level)
        self.vm.end_unloaded(proc)
        keep = {f.name: f for f, _ in carried}
        self.load_objects(level, keep, {it.key for it, _ in carried_items})
        self.figures.update(keep)
        pos = None
        player = self.player()
        t = self.arrival_point(arrival) if arrival is not None else None
        if arrival is not None and t is None:
            self.warn(f'LOADLEVEL {level}: arrival {arrival} not found (error 0x136); PLAYER keeps its position')
        if carried or carried_items or rel_player is not None:
            dest = np.array([t[0][0], t[0][1], t[1]]) if t is not None else np.zeros(3)      # no destination: a dummy at the origin (1148:1061)
            for f, rel in carried:
                p = dest + rel
                self.place_after_level_change(f, p[0], p[1], p[2], p[2], dest)
            for it, rel in carried_items:        # 1078:07c3 -> 1070:1e9d: a plain SetPos, the velocity zeroed
                it.pos, it.vel, it.step = dest + rel, [0, 0, 0], [0, 0, 0]
        if t is not None and player is not None:
            if rel_player is not None:
                p = dest + rel_player
                self.place_after_level_change(player, p[0], p[1], p[2], p[2], dest)
            else:
                # As GO (FUN_10a0_1ff0). Live: gravity off, ENTR_TNK's low z as is (-3584); gravity on, the floor under BTM_LDR + F (-13996 + 2312)
                # Collisions off (CRYTOTNK FALL): no floor. Live (re/out/tank_fall_live), the original left Lex far below every floor
                # there and he fell on into the acid; the port stood him on the TANKS walkway and FALL's COORDZ loop never ended.
                snap = player.gravity and not player.no_collide
                floor = self.point_floor(int(t[0][0]), int(t[0][1]), int(t[1]), int(t[1])) if snap else NO_FLOOR
                z = t[1] - self.model_root_z(player) if not snap else (floor if floor > NO_FLOOR else t[1]) + self.foot(player)
                self.place_after_level_change(player, t[0][0], t[0][1], z, z, np.array([t[0][0], t[0][1]]), first_done=True)
            pos = player.pos.copy()
        self.shown_picture = None
        self.level_loads.append((self.vm.tick, level, arrival, pos))
        self.fire_event(level + '_LOAD')

    def _go_snap(self, fig, xy, zt):
        """A GO that places at once: SetPos (FUN_10a0_1ff0) zeroes every velocity (FUN_1070_1e9d). Live (re/out/tank_fall_live):
        TANKDETH's GO DROWN leaves the falling Lex with z velocity 0."""
        fig.pos = np.array([xy[0], xy[1], zt])
        fig.vx = fig.vy = fig.vz = 0
        fig.step = [0, 0, 0]
        fig.go = None

    def cmd_go(self, fig, args, proc=None):
        fig.manual_control = False
        nums = [a for a in args if isinstance(a, int)]
        numeric = isinstance(args[0], int) and len(nums) >= 3
        if numeric:
            # FUN_10d0_33c8 numeric form: (x, y, z) = the first three numbers << 8 (COORDX units); a 4th number is the arrival
            # radius in cm (go['radius'] below; 0 or absent = the default); any word other than WALK / RUN is error 0x120
            bad = next((str(a) for a in args if isinstance(a, str) and a.upper() not in ('WALK', 'RUN')), None)
            if bad is not None:
                self.warn(f'GO {bad}: unknown modifier (error 0x120)')
                return
            t = np.array([nums[0] << 8, nums[1] << 8], float), float(nums[2] << 8), False
        else:
            t = self.go_target(args[0])
        if t is None:
            self.warn(f'GO {args[0]}: unknown target')
            return
        xy, z, is_fig = t
        mode = next((str(a).upper() for a in args[1:] if str(a).upper() in ('WALK', 'RUN')), None)
        # FUN_10a0_1ff0 (SetPos): with gravity the origin goes to the floor under the target point (FUN_1060_0d9a ->
        # FUN_1060_0871) + F (+ the root z, kept in the pose); without gravity the target z is used as is (PLAYLOC is the
        # lying pelvis height above the bed, UBOTLOC the saved hover height of USE_BOT).
        if is_fig or not fig.gravity:
            # z is the engine's, origin + R (live: Lex at PLAYLOC reads -5754 with R -40, then -5714 once WAKE_UP's R 0 applies); the port's origin leaves R out
            zt = z - (0 if is_fig else self.model_root_z(fig))
        else:
            zt = self.point_floor(int(xy[0]), int(xy[1]), int(z), int(z)) + self.foot(fig)
        if numeric and fig.gravity and zt <= NO_FLOOR + self.foot(fig):
            zt = z                  # ASSUMPTION: no floor under a numeric point (GO 6666 6666 6666 parks a figure off the map): keep z
        if mode is None or fig.pos is None or fig.assets.motions.get(mode) is None:
            if mode and fig.pos is not None:
                self.warn(f'{fig.type} has no {mode} motion; snapping')
            self._go_snap(fig, xy, zt)
            return
        d = xy - fig.pos[:2]
        if np.hypot(*d) <= 1e-6:
            self._go_snap(fig, xy, zt)
            return
        fig.heading = math.degrees(math.atan2(-d[0], -d[1]))     # inverse of forward()
        # Arrival radius (1098:11c0): the default 0x266 = 614 units; the numeric form's 4th number N, when nonzero, is N cm
        # (N * 2048 // 100). INFERRED: the named forms never read that slot, so they always use the default.
        radius = nums[3] * 2048 // 100 if numeric and len(nums) > 3 and nums[3] else GO_RADIUS
        go = {'target': xy, 'z': zt, 'motion': mode, 'radius': radius}
        fig.go = go
        fig.drop_deferred()
        fig.set_motion(mode, True)
        if proc is not None:
            # FUN_10d0_33c8 returns the mover's handle to the script scheduler.  The
            # process continues after this specific walk arrives, or if another GO /
            # motion replaces it.  Direct callers still start the same asynchronous
            # figure movement; only VM processes install a wait predicate.
            proc.wait_pred = lambda: fig.go is not go
        # the first motion frame is shown at once without travel; later frames add their root delta

    def steer_go(self, fig):
        """The GO task's walking state (FUN_10e0_1a4c case 4) calls FUN_10a0_1f0a every update while the figure walks or runs: the
        figure turns toward the target, by the whole angle when it is within 10 degrees and by 10 degrees (0xa00 in 8.8) otherwise.
        Without it a figure pushed off its line (PERSONAL_RADIUS, avoidance points) could miss the arrival circle and run on for
        ever (Drogg 1 after GO DCENTER RUN, stream 16). ASSUMPTIONS: one task update per tick, before the figure's update; the angle
        test of the integer angle is read as |diff| < 11 degrees. NOT PORTED: case 4 ending the GO when the motion is none of
        WALK, RUN, ATK_M8 (here a figure in another motion is only not steered)."""
        if fig.go is None or fig.arriving or fig.pos is None or str(fig.motion).upper() not in ('WALK', 'RUN', 'ATK_M8'):
            return
        d = fig.go['target'] - fig.pos[:2]
        if not d.any():
            return
        want = math.degrees(math.atan2(-d[0], -d[1]))             # as cmd_go aims: the inverse of forward()
        diff = (want - fig.heading + 180) % 360 - 180
        if diff == 0:
            return
        fig.heading = want if abs(diff) < 11 else fig.heading + (10 if diff > 0 else -10)

    def cmd_face(self, fig, a):
        if isinstance(a, (int, float)):
            fig.heading = float(a) if FACE_IS_ABSOLUTE else fig.heading + float(a)
            return
        t = self.target(a)
        if t is None:
            self.warn(f'FACE {a}: unknown object')
            return
        d = t[0] - (fig.pos[:2] if fig.pos is not None else np.zeros(2))
        if np.hypot(*d) > 1e-6:
            fig.heading = math.degrees(math.atan2(-d[0], -d[1]))

    def cmd_motion(self, fig, name, flags, proc=None):
        """MOTION name [CONTINUE|FREEZE|SNAP_TO|NO_SCRIPT] [start frame] (handler FUN_10d0_5e8b):
          plain     start now (replacing the current motion), play once, and BLOCK the calling process until it
                    finishes (resumes the tick after the last frame) or the figure gets another motion;
          CONTINUE  start now, no wait; it loops if the motion's header event list holds the 0xfe marker (motion_loops,
                    1088:1854), else it plays once and ends (so `MOTION ACTIVATE CONTINUE ... IF ISMYMOTION(ACTIVATE) JUMP` in
                    AWAKEN.scr terminates);
          FREEZE    clears only the idle-fallback bit (10d0:5e8b): the motion plays to its end, blocking like a plain MOTION unless
                    CONTINUE is also given, and its last pose is held with no STAND / ATK_STAND fallback (Figure.no_idle) until the
                    next MOTION/SNAPTOPOSE;
          SNAP_TO   no blending (we never blend); NO_SCRIPT is ignored.
        During a GO walk, CONTINUE motions are deferred to arrival (last one wins, MOTION_DEFERRED_DURING_GO); a
        blocking MOTION is deferred the same way and its caller stays blocked until it has played after arrival."""
        name = str(name).upper()
        fig.manual_control = False
        if name not in fig.assets.motions:
            self.warn(f'{fig.type} has no motion {name}')
            return
        scripted = 'NO_SCRIPT' not in flags
        if scripted and fig.motion_gate_refuses(name):
            return                                       # 1098:12bd refused: no change, no wait
        continuing, freeze = LOOP_KEYWORD in flags, 'FREEZE' in flags
        loop = continuing and motion_loops(fig.assets, name) and not name.endswith(GESTURES)
        start = next((int(f) for f in flags if f.lstrip('-').isdigit()), 0)
        block = not continuing                           # only CONTINUE skips the wait (10d0:6083), FREEZE alone blocks
        tok = {'id': None} if block and proc is not None else None
        if fig.go is not None and MOTION_DEFERRED_DURING_GO:
            fig.drop_deferred()                              # a deferred motion replaced by a later one releases its caller
            fig.after_go = (name, loop, tok)
        else:
            fig.go = None
            if fig.set_motion(name, loop, no_idle=freeze):
                fig.task_name = name if scripted else None
                fig.unwaited = not block
                fig.idx = max(0, min(start, len(fig.frames) - 1))
                if tok is not None:
                    tok['id'] = fig.mot_id
            else:
                tok = None          # refused (DIE is current, 1098:0394 returns 0): a zero handle, so 10d0:5e8b does not wait
        if tok is not None:
            proc.wait_pred = lambda: tok['id'] is not None and (fig.mot_id != tok['id'] or fig.finished)

    def cmd_snaptopose(self, fig, args):
        """SNAPTOPOSE motion frame [FREEZE]: show that frame now, queue cleared; FREEZE holds it."""
        fig.manual_control = False
        name = str(args[0]).upper()
        if name not in fig.assets.motions:
            self.warn(f'{fig.type} has no motion {name}')
            return
        frame = args[1] if len(args) > 1 and isinstance(args[1], int) else 0
        fig.go = None
        fig.drop_deferred()
        # 10d0:76xx: 0789(fig, 0, 0) (which returns early on an unfinished DIE), then 1098:1421 -> 06e0 -> 0394, which refuses while DIE is
        # current: no exception for SNAPTOPOSE either (INFERRED: the pose-at-frame step that follows the refusal is not ported)
        if fig.set_motion(name, False, freeze=any(str(a).upper() == 'FREEZE' for a in args[2:])):
            fig.idx = max(0, min(frame, len(fig.frames) - 1))

    def process_states(self):
        """[task] of the live script processes, in the terms savewrite.task_script_dat writes and resume.py reads: the block's definition
        number in its file, `pc` = the .SCP offset of the statement it runs next and `pc0` = of the one before (a timeline's last line, whose
        time resume measures from), both the same for a process blocked in a CALL expression (resume re-enters it); the locals, the current
        figure / item, the LINKMETOCAMERAS list, the ticks left of a WAIT, and the processes it waits for. MODIFYVAREVERYNTH's native ramps
        become ramp tasks and the TIMED ones (subtitle / sound handles) Wait tasks of their own; other native processes (fades, missiles)
        are not saved. ASSUMPTION: a process the
        engine holds in a blocking MOTION / GO (wait_pred) is saved at that statement and re-runs it on load."""
        vm = self.vm
        if vm is None:
            return []
        out = []
        for p in vm.procs.values():
            if p.done:
                continue
            if p.code is None or p.block.file is None:
                if p.block.name == 'TIMED' and p.wait_on is None:   # a SUBTITLE / sound handle: a Wait task of the ticks left (ASSUMPTION)
                    out.append({'handle': p.handle, 'timed': max(int(p.wake - vm.tick), 1)})
                    continue
                if p.block.name == 'MODIFYVAREVERYNTH' and p.gen is not None and getattr(p.gen, 'gi_frame', None) is not None:
                    loc = p.gen.gi_frame.f_locals
                    if all(k in loc for k in ('v', 'step', 'end', 'start', 'n')):
                        out.append({'handle': p.handle, 'ramp': (int(loc['v']), int(loc['step']), int(loc['end']), int(loc['start']), int(loc['n']),
                                                                  max(int(p.wake - vm.tick), 0))})
                continue
            f = p.block.file
            own = p.block.defid
            if own is None or f.scp is None or f.defs.get(own) is not p.block:
                continue
            offs = {id(st): o for o, st, b in f.positions()}
            ins = p.code.ins
            nxt = next((i.stmt for i in ins[p.pc:] if i.stmt is not None and id(i.stmt) in offs), None)
            prev = next((i.stmt for i in reversed(ins[:p.pc]) if i.stmt is not None and id(i.stmt) in offs), None)
            if nxt is None and prev is None:
                continue
            pc = offs[id(nxt)] if nxt is not None else offs[id(prev)] + 1
            pc0 = pc if p.pending or p.wait_pred is not None else (offs[id(prev)] if prev is not None else pc)
            blockers = list(dict.fromkeys([c.handle for c in p.pending.values()] + ([p.wait_on.handle] if p.wait_on is not None else [])))
            out.append({'handle': p.handle, 'script': os.path.basename(f.scp), 'block': own + 1, 'pc': pc, 'pc0': pc0,
                        'locals': [int(v) if isinstance(v, (int, float)) else 0 for v in p.locals], 'cur': (p.cur_item or p.cur_fig or '').upper(),
                        'cameras': [c.upper() for c in p.cameras], 'wait': max(int(p.wake - vm.tick), 0) if p.wait_on is None and not p.pending else 0,
                        'blockers': blockers, 'calls': [c.handle for c in p.pending.values()], 'nlocals': declared_locals(p.block, p.locals),
                        'fig_index': p.fig_index, 'suspended': bool(p.suspended)})
        for n, m in self.saved_missiles():                  # a missile in flight is a task of its own (MISSILE_VTABLE): the original keeps it
            owner = next((k for k, f in self.figures.items() if f is m.owner_fig), None)
            out.append({'handle': m.handle, 'missile': {'item': n.upper(), 'owner': owner.upper() if owner else None, 'range': int(m.dist),
                                                         'spin': [int(c) for c in m.spin]}})
        hook = vm.blocks.get(self.key_hook) if self.keyboard_captured and self.key_hook else None
        if hook is not None and hook.file is not None and hook.file.scp is not None and hook.defid is not None:
            # CAPTUREKEYBOARD's hook is a process of its own (DAT_1290_6530) that every key event restarts (FUN_1138_1da6 -> 10c0:0ea4); the
            # PLAY record links its slot. The port spawns it per key, so it is written idle at the block's first statement (ASSUMPTION).
            first = min((o for o, st, b in hook.file.positions() if b is hook), default=None)
            if first is not None:
                out.append({'handle': max([t['handle'] for t in out] + [vm.next_handle]) + 1, 'script': os.path.basename(hook.file.scp),
                            'block': hook.defid + 1, 'pc': first, 'pc0': first, 'locals': [0, 0, 0], 'cur': '', 'cameras': [], 'wait': 0,
                            'blockers': [], 'hook': True, 'calls': [], 'nlocals': declared_locals(hook, []), 'fig_index': 0, 'suspended': False})
        return out

    def saved_missiles(self):
        """[(key, Missile)] of the missiles a save keeps: in flight, with a live handle. NOT PORTED: what one carries (FIRE ... CARRY: the
        player cannot save on a zip line, CANNOT_SAVE) is not linked back on a load."""
        procs = self.vm.procs if self.vm is not None else {}
        return [(n, m) for n, m in self.items.items() if getattr(m, 'missile', False) and not m.dead and m.pos is not None
                and m.handle in procs and not procs[m.handle].done]

    @staticmethod
    def missile_flags(m):
        """The missile item's flag byte (+0x34) as its record keeps it: gravity, collisions off (CARRY), bouncy, reflective."""
        return (levelmod.F_GRAVITY if m.gravity else 0) | (levelmod.F_COLLISIONS if m.no_collide else 0) | (levelmod.F_BOUNCY if m.bouncy else 0) | (0x20 if m.reflective else 0)

    def figure_states(self, figures=None):
        """{FIGURE NAME: the record fields savewrite.patch_figure writes} of the placed figures (`figures`, default the level's): the saved z adds the motion's root z
        back (resume.py takes it off), flags as the record's bit set, the object locals, the enemy's name (PLAYER for the player)."""
        out = {}
        for key, f in (self.figures if figures is None else figures).items():
            if f.pos is None:
                continue
            flags = ((levelmod.F_GRAVITY if f.gravity else 0) | (levelmod.F_COLLISIONS if f.no_collide else 0) | (levelmod.F_HIDDEN if f.hidden else 0)
                     | (levelmod.F_INVULNERABLE if f.invulnerable else 0) | (levelmod.F_BOUNCY if f.bouncy else 0) | (levelmod.F_COMBAT if f.combat else 0))
            motion = f.motion or ''
            task = bool(motion) and f.unwaited and f.task_name == motion and not f.finished    # a running MOTION ... CONTINUE: its task
            dead = bool(motion) and motion == 'DIE' and (self.vm.objects.get(self.object_key(key), [1])[0] if self.vm else 1) <= 0
            idle = 'ATK_STAND' if f.combat else 'STAND'
            if motion and not f.loop and not task and not dead and idle in f.assets.motions:     # a type with no idle keeps its held pose                  # resume loops the saved motion from frame 0 (the original keeps no phase either,
                motion = idle                                       # FUN_1088_489f): a one-off midway or held on its last frame would repeat for
                                                                    # ever, so it is saved as the idle it ends in (ASSUMPTION); a blocking MOTION
                                                                    # comes back with its process, which re-runs the statement
            frames = f.assets.motions.get(motion) if motion else None
            z = float(f.pos[2]) + (float(frames[0][0][2]) if frames else 0.0)
            enemy = f.enemy
            if enemy and enemy.upper() != 'PLAYER' and self.resolve(enemy) == self.player_name:
                enemy = 'PLAYER'
            out[key.upper()] = {'type': f.type, 'pos': [float(f.pos[0]), float(f.pos[1]), z], 'heading': float(f.heading), 'motion': motion,
                                'flags': flags, 'locals': list(self.vm.objects.get(self.object_key(key), [0] * 10)) if self.vm else [0] * 10,
                                'enemy': (enemy or '').upper(), 'hold': int(f.hold), 'in_trig': getattr(f, 'in_trig', None),
                                'motion_task': task, 'ai': (f.ai_type or '').upper(), 'teeter': bool(f.teeter), 'z_cap': int(f.z_cap),
                                'foot': int(self.foot(f)), 'avoid': [(n.upper(), int(r)) for n, r in f.avoid],
                                'ai_handle': f.ai_proc.handle if f.ai_proc is not None and not f.ai_proc.done else 0, 'vel': [int(round(v)) for v in (f.vx, f.vy, f.vz)], 'view_cams': None if f.view_cams is None else [c.upper() for c in f.view_cams]}
        return out

    @staticmethod
    def item_state(i):
        """(owner, slot, floor position, orientation rows) of an item, as savewrite.patch_item takes it."""
        return (i.owner, i.slot, None if i.pos is None else [float(x) for x in i.pos],
                None if i.matrix is None else [[float(x) for x in row] for row in i.matrix])

    def level_item_states(self):
        """{level: (item states, {name: (type, locals)}, figure states)} of the items and figures kept with the levels the player left
        (savewrite other_levels); the figure states are the kept figures', every other FIGR record of that level's file is a killed one."""
        return {lvl: ({i.key.upper(): self.item_state(i) for i, _ in kept}, {i.key.upper(): (i.type, list(l)) for i, l in kept},
                      self.figure_states(self.level_figures[lvl]) if lvl in self.level_figures else None)
                for lvl, kept in self.level_items.items()}

    # ---- native save state (re/formats/savegame.py)
    def export_state(self):
        """The pieces of the native GAMEDAT state this prototype can populate: MISC fields, VARS values, log lists and
        the placed-object positions and the items of the level's ITEM records (owner, hand, floor position; savewrite.patch_item).
        NOT exported (no prototype equivalent decoded): the kernel task table of SCRIPT.DAT (running processes, their
        pc/locals), items without a record in the level file and the per-figure record tails of the level IFFs."""
        return {'misc': {'level': self.level + '.IFF', 'camera': self.current_camera(), 'auto_camera': int(self.script_auto)},
                'vars': {k.upper(): v for k, v in self.vm.globals.items() if isinstance(v, int)} if self.vm else {},
                'lists': {l: list(zip(k, self.log_entry_times.get(l, []))) for l, k in self.log_entries.items()},
                'figures': {n: [float(x) for x in f.pos] for n, f in self.figures.items() if f.pos is not None},
                'items': {n: self.item_state(i) for n, i in self.items.items()}}

    @classmethod
    def from_native_state(cls, path=GAMEDAT):
        """-> (world, vm) booted from a native GAMEDAT: level + camera from MISC.DAT, VARS.DEF values, LISTS.FLX logs and
        the level IFF as the object file.  The saved figures, carried items and script processes are resumed from the
        level records and SCRIPT.DAT (resume.restore); `world.resumed` = {kernel slot: Process}."""
        import savegame
        st = savegame.SaveState.load(path)
        level = st.misc.level.upper().replace('.IFF', '')
        world = cls(level, camera=st.misc.camera or None, state_dir=path)
        vm = vmmod.VM(world)
        vmmod.load_level(vm, level)
        upper = {k.upper(): k for k in vm.globals}
        for name, value in st.vars.items:
            if name.upper() in upper:
                vm.globals[upper[name.upper()]] = value
        for log, items in st.lists.lists().items():
            world.log_entries[log] = [k for k, _ in items]
            world.log_entry_times[log] = [t for _, t in items]
        world.script_auto = bool(st.misc.auto_camera)
        if st.misc.camera:                                  # 1148:0490 fills [63e9] / [63ed] from the saved camera: restoring it runs no events
            world.loaded_cam = st.misc.camera.upper()
            world.camera = world.loaded_cam                 # ... and the restore's switch (1130:0114) makes it current ([63ce])
            world.loaded_room = world.loaded_cam[:3]
        import resume
        world.resumed = resume.restore(world, vm, st)       # figures, carried items, script processes (resume.py)
        world.ambient_pending = True                        # INFERRED: the engine re-requests the camera, so the ambient loops restart
        return world, vm

    # ---- automatic cameras
    def followed_pos(self):
        f = self.figures.get(self.resolve(self.follow))
        return None if f is None or f.pos is None else f.pos

    def set_camera(self, cam, reason):
        old = self.camera or self.default_camera
        if cam != old:
            self.camera_changes.append((self.vm.tick if self.vm else 0, old, cam, reason))
        self.camera_events(cam)
        if cam != self.camera:
            self.apply_camera_links(cam)                  # 1130:0549, after the events: a process their blocks started and linked is included. the first switch of a level always counts: [63ce] is 0 until then (1130:0048)
        if cam != self.camera:
            self.shown_picture = None                     # a real switch replaces the SHOW picture
        self.camera = cam                                 # [63ce] is assigned after the events (1130:065d): their blocks still see the old camera

    def link_to_cameras(self, proc, args):
        """LINKMETOCAMERAS (10d0:4c72): registers the running process with each named camera of the level (10c0:547d, list DS:2f1d). An unknown
        name is error 0x1e and more than 10 cameras error 0xe1 (10c0:533a); neither stops the statement. Linking alone pauses nothing, not even
        when the current camera is not listed: only the next camera switch looks at the list (10c0:5688)."""
        for c in args[:10]:
            c = str(c).upper()
            if c not in self.cameras:
                self.warn(f'LINKMETOCAMERAS {c}: unknown camera (error 0x1e)')
            elif len(proc.cameras) >= 10:
                self.warn(f'LINKMETOCAMERAS {c}: {proc.block.name} already has 10 cameras (error 0xe1)')
            else:
                proc.cameras.append(c)

    def apply_camera_links(self, cam):
        """10c0:5688 on a camera switch: flag bit 0 (+0xe) of every linked process is set unless `cam` is in its list (10c0:53fe) and cleared if it
        is. That bit is `Process.suspended`, shared with SUSPENDPROCESS / RESUMEPROCESS, AI OFF / ON and the show / hide pass, so a switch overrides
        them for a linked process. The kernel skips a flagged task (1230:0259). A WAIT or CALL child goes on while it is paused and a timeline's
        clock too (10c8:03e1 compares [8330] with origin + stamp): once resumed it runs every line that came due in one slice."""
        if self.vm is not None:
            for p in self.vm.procs.values():
                if p.cameras:
                    p.suspended = cam not in p.cameras

    def camera_events(self, cam):
        """1130:0307-044f, while the game runs ([50b8]; clear only in the new-game and restore loads, which the ports do not run through
        here): a different room (the name's first 3 characters, [63e5] vs [63ed]) runs <new room>_LOAD then <old room>_UNLOAD, a different
        camera ([63e1] vs [63e9]) <new cam>_LOAD then <old cam>_UNLOAD. Each block's first slice runs at once with CURFIG = the player
        (1120:0000 with run flag 1, no item). The names are copied only afterwards (1130:0459). No shipped script has an _UNLOAD block.
        The level's initial camera counts as loaded when first used."""
        room, old_cam, old_room = cam[:3], self.loaded_cam, self.loaded_room
        if cam == old_cam and room == old_room:
            return
        self.switching_to = cam
        if room != old_room:
            self.fire_camera_event(room + '_LOAD')
            if old_room:
                self.fire_camera_event(old_room + '_UNLOAD')
        if cam != old_cam:
            self.fire_camera_event(cam + '_LOAD')
            if old_cam:
                self.fire_camera_event(old_cam + '_UNLOAD')
        self.loaded_cam, self.loaded_room, self.switching_to = cam, room, None
        self.camera_switched()                            # 1130:0114 step e, after the events: the ambient loops restart next frame

    def fire_camera_event(self, block):
        if self.vm is not None and block in self.vm.blocks:
            self.events.append((self.vm.tick, block))
            player = self.player()
            self.vm.spawn(block, ctx=types.SimpleNamespace(cur_fig=player.name if player else None, cur_item=None, owner='level'))

    def update_camera(self):
        """One frame of the camera manager (FUN_1130_0fa3):
        0. a camera forced by a trigger ([63d6]) is taken once, without acceptance or debounce;
        1. nothing else runs while the script's auto flag is OFF (`CAMERA <cam>` locks, `CAMERA UNLOCK` resumes);
        2. the current camera keeps the followed object while it still accepts it;
        3. else the enabled accepting camera with the smallest d (approx_length: 1130:0fa3 ranks by FUN_1208_13e3 =
           FUN_1210_0f9b; the first camera wins a tie) wins; none accepts -> keep the current camera;
        4. debounce: switch only if the same candidate won the previous frame (or on the first selection)."""
        P = self.followed_pos()
        if self.forced_camera is not None and P is not None:
            # a trigger forced a camera: switch to it unless it is current, skipping acceptance and debounce; while the script
            # holds the camera the request is dropped (CAMERA UNLOCK resets the pending camera to the current one)
            cam, self.forced_camera, self.candidate = self.forced_camera, None, None
            if self.auto_camera and self.script_auto and cam != (self.camera or self.default_camera):
                self.selected = True
                self.set_camera(cam, f'trigger forces {cam}')
            return
        if not self.auto_camera or not self.script_auto or P is None:
            return
        cur = self.camera or self.default_camera          # a level load leaves no camera ([63ce] 0, 1130:0048), so its first frame takes the nearest accepting one; default_camera is the World(camera=) argument
        if cur in self.cameras and accepts(self.cameras[cur], P)[0]:
            self.candidate = None
            self.camera_events(cur)
            return
        best = None
        for name, cam in self.cameras.items():
            if name in self.disabled or name == cur:
                continue
            ok, d = accepts(cam, P)
            if ok and (best is None or d < best[1]):
                best = (name, d)
        if best is None:
            self.candidate = None
            return
        if best[0] == self.candidate or not self.selected:
            self.selected, self.candidate = True, None
            self.set_camera(best[0], f'{cur} rejects {self.follow}; {best[0]} nearest accepting (d={best[1]:.0f})')
        else:
            self.candidate = best[0]

    # ---- time
    @property
    def paused(self):
        """The open options dialog pauses the simulation (FUN_10a8_02cc -> FUN_10b0_136b(0), [50be] = [50bf] = 1): VM
        processes, figures, camera selection, the game clock and timers (vm.tick) stand still and subtitles are hidden;
        only the dialog UI runs. Exception: _OPTS_CREDITS, which does not pause (FUN_1280_221e resumes at once, FUN_1100_0716; the roll runs over the
        live world); 10a8:02cc pauses it while a forced reload runs (FUN_1100_06d4 false) and 221e then leaves it paused."""
        o = self.options
        return o is not None and not o.closed and not o.resumed

    def credits_rolling(self):
        """The credits page is open (the roll runs; it does not pause or hold the world)."""
        o = self.options
        return o is not None and not o.closed and o.screen == 'credits'

    def credits_state(self):
        """CREDITSSTATE [9ce5]: 0 none (or the page closed), 1 scrolling, 2 done."""
        return self.options.credits_state if self.credits_rolling() else 0

    def step_pointers(self):
        """Once per tick: the script monitor's and the options dialog's pointer (FUN_1270_02ef); a release that activates an option
        control takes effect here."""
        if self.monitor is not None:
            self.monitor.update()
        if self.options is not None:
            for action in self.options.update():
                self.record_option_action(action)

    def active_subtitle(self, tick):
        """The subtitle to draw at `tick` (FUN_1100_1538 hides it while paused; none are made with subtitles off, FUN_10e8_0529)."""
        if self.paused:
            return None
        log = self.subtitle_log if self.settings.subtitles else [e for e in self.subtitle_log if e[1] in self.caption_handles]    # 10d0:16cb -> 10b0:0f48 never reads [50bc]
        return subtitles_mod.active_subtitle(log, tick)

    def step(self):
        """Advance every placed figure by one VM tick, then update the automatic camera."""
        self.step_pointers()                               # the pointers' press animations run on, also while the options dialog pauses the game
        if self.paused:
            return
        self.step_show()                                   # the flic clock and ADDKEY run while FREEZE has stopped the world
        if self.frozen:
            return
        self.step_presentation()
        self.apply_player_input()
        self._boxes = None
        self._boxes = self._phys_boxes()
        self.move_missiles()                               # 1110:08bf updates the item list (missiles) before the figures
        self.move_free_items()                             # ... and its other items (thrown ones)
        cam = self.current_camera()
        for fig in list(self.figures.values()):            # a trigger block may create figures
            if self.figures.get(fig.name) is not fig:
                continue                                    # a trigger's LOADLEVEL dropped it with its level this frame
            self.update_hidden(fig, cam)
            self.start_enabled_ai(fig)                      # FUN_1088_3371, before this figure's update
            fig.held_pose = None                            # this update samples the current motion's pose (World.posed)
            if fig.confront is not None:
                self.update_confront(fig)
            if fig.pos is None or fig.frames is None:       # frames None: figure type with no motions
                continue
            if fig.hidden:
                # FUN_1088_39ef returns at once for a hidden figure (flag 0x04, +0xf6 clear): neither animated, moved
                # nor pushed, and excluded from other figures' PERSONAL_RADIUS pushes (push_target already checks
                # other.hidden). NOT PORTED: the HIDE/UNHIDE block event (FUN_1128_0569; no script in this game defines
                # one) and stopping the figure's ambient sound (FUN_1058_0c81 on +0x135; see NOTES "STOPMOTION and
                # hidden figures").
                continue
            fig.prev_pos = fig.last_good = fig.pos.copy()      # +0xba / +0xe2 at the frame start
            # FUN_1088_1854: frame = (clock << 8 - start) / (MY_SPEED x frame time); the clock runs at 60 Hz
            if fig.root_start:
                self.apply_first_root(fig)
            self.steer_go(fig)
            fig.phase += CLOCK_PER_TICK
            while fig.phase >= self.motion_duration(fig):
                fig.phase -= self.motion_duration(fig)
                self.advance(fig)
            if fig.carrier is not None and fig.carrier not in self.items:
                fig.carrier = None                         # its missile is gone (e.g. a level change)
            if fig.carrier is None and fig.limb_holder is None:
                self.settle(fig)                           # gravity, then the one mover call: root motion + velocity step
            else:
                # FUN_1088_39ef does nothing while attached (+0x2c): no velocity move, gravity, grounding or push; the motion
                # still plays, but its root travel is dropped (the missile or the holder's limb places the figure)
                fig.root_delta, fig.root_moved, fig.step, fig.arriving = np.zeros(2), False, [0, 0, 0], False
            self.update_hit(fig)
            self.auto_turn(fig)
            self.motion_events(fig)
            if fig.recoil_id is not None and (fig.mot_id != fig.recoil_id or fig.finished):
                # ASSUMPTION: ~3 (_ATK_STATUS_RECOIL = 1) returns to _ATK_STATUS_OK when the recoil motion ends or is replaced;
                # the clearing site is not recovered, but NURSEBOT_AI idles while ~3 != 0, so without it a hit nurse never acts again
                fig.recoil_id, objs = None, self.objects_for(fig)
                if objs[3] == 1:
                    objs[3] = 0
            if fig.idle_request and self.hit_points(fig) > 0:
                fig.idle_request = False                     # 1088:4167: no motion and no task left, at the end of the figure's update
                fig.held_pose = self.pose_state(fig)
                z = fig.pos[2]
                fig.set_motion('ATK_STAND' if fig.combat else STAND, True, engine=True)
                fig.pos[2] = z                               # the stopped pose's root z is the idle's own: nothing to commit
            if fig.finished and not fig.frozen and not fig.no_idle and fig.go is None \
                    and fig.motion != 'DIE' and self.hit_points(fig) > 0 and self.idle_motion(fig) in fig.assets.motions:
                # 1088:4155: at the end of its update a living figure, the player too, with no motion task left requests its idle
                # (FUN_1098_0745), lower case in the original. HALMECHO's TURN_WHILE_FIRING loops on ISMYMOTION(FIRE_GUN) until this ends its FIRE_GUN.
                fig.held_pose = self.pose_state(fig)
                fig.set_motion(self.idle_motion(fig), True, engine=True)
            if fig.finished and not fig.no_idle and fig.motion in ENGINE_ONESHOTS \
                    and (self.vm is None or self.hit_points(fig) > 0):      # 1088:508d: a dead figure never idles
                # ASSUMPTION: an engine-requested landing / whoah motion returns to STAND, or to the walk of a running GO
                fig.set_motion(fig.go['motion'] if fig.go else STAND, True)
            self.update_triggers(fig)
        self.step_textures()                               # ANIMATE: every animated texture with a mode steps (ASSUMPTION, mechanics.py)
        self.place_limb_held()                             # GRABCRITTER: figures held by a limb follow its current pose (ASSUMPTION, mechanics.py)
        self.tick_missiles()                               # the scheduler's missile tasks (1230:0259), after the world update
        self.tick_flat_objects()
        self.tick_fragments()
        self._boxes = None
        self.update_camera()
        self.refresh_sound_volumes()
        self.update_ambients()                             # 1130:0e6b

    def apply_first_root(self, fig):
        """A motion's first update moves the figure by frame 0's whole root x, y. FUN_1098_0000 clears the root base +0xd1..+0xd9 when a motion
        ends, FUN_1088_0581 moves by root minus base, and FUN_1098_0394 copies frame 0's root into the blend's start pose, so the blend
        (FUN_1088_0d63) holds the root at frame 0. Live, DOSBox-X: WALK_BACK (7, 241) moved Lex (7, 241) at its first update."""
        fig.root_start = False
        if fig.frozen or fig.arriving or not fig.frames:
            return
        x, y = fig.frames[0][0][:2]
        if x or y:
            fig.root_delta, fig.root_moved = fig.root_delta + self.root_step(fig, x, y), True

    def root_step(self, fig, x, y, updates=1):
        """The world move of a root change (x, y) spread over `updates` engine updates. FUN_1088_0581 multiplies each update's change by the
        figure's matrix in 8.8 and shifts each axis down (FUN_1210_15b4), so every update rounds toward -x, -y. Live, DOSBox-X at the GOG
        settings: this reproduces all 88 MANTLE_6 and 175 of 177 CLIMB_UP moves exactly (the other two are the loop wrap, which does not
        move). The drift grows with the update count, which is not fixed in the original: about 1 clock tick per update in the ladder
        shaft, 2 in a busier room, 3.7 at 8000 cycles. ASSUMPTION: one update per 30 Hz tick."""
        m = self.orientation(fig)
        out = np.zeros(2)
        for i in range(updates):
            dx = x * (i + 1) // updates - x * i // updates
            dy = y * (i + 1) // updates - y * i // updates
            out += ((m[0][0] * dx + m[1][0] * dy) >> 8, (m[0][1] * dx + m[1][1] * dy) >> 8)
        return out

    def advance(self, fig):
        """One motion frame. Its root motion is not moved here: it accumulates in fig.root_delta and World.frame_move performs
        the frame's single mover call (FUN_1088_39ef: root motion and velocity step in one move, one collision response)."""
        if fig.frozen or fig.arriving:
            return
        n = len(fig.frames)
        nxt = fig.idx + 1
        if nxt >= n:
            if not fig.loop and (fig.go is None or fig.motion in ENGINE_ONESHOTS):
                fig.finished = True
                return                                      # play once: hold the last frame
            nxt = 0
            fig.hit_done = False                            # a new cycle may hit again
            fig.bake_turn()                                 # FUN_1088_1854 -> FUN_10a0_1c83 at a turning motion's wrap
            if fig.rises:
                fig.pos[2] += fig.frames[-1][0][2]          # 1088:1286: a flag-2 motion adds R (C+0xa6) to the root limb's z at the wrap
            fig.idx = 0
        d = self.motion_duration(fig)
        updates = max(1, ((fig.idx + 1) * d >> 9) - (fig.idx * d >> 9))     # 30 Hz ticks this frame lasts: one engine update per tick, see root_step
        moving = (fig.go is not None or (self.ai_active(fig) and fig.pos is not None)
                  or (fig is self.player() and fig.manual_control
                      and fig.motion in MANUAL_MOVES))
        if moving:
            rp = [f[0] for f in fig.frames]
            prev = rp[fig.idx] if nxt else (0, 0, 0)        # a cycle restarts at displacement 0
            delta = self.root_step(fig, rp[nxt][0] - prev[0], rp[nxt][1] - prev[1], updates)
            rem = fig.go['target'] - (fig.pos[:2] + fig.root_delta) if fig.go is not None else None
            # without a GO target (AI-driven figure) the motion's root travel just moves it (ASSUMPTION)
            if rem is not None and np.hypot(*rem) < fig.go['radius']:      # 10e0:1a4c: length2d(target - pos) < radius ends the GO
                fig.root_moved = True
                fig.arriving = True            # frame_move ends the GO (no snap) and starts the after-GO motion once the move completes
            else:
                fig.root_delta, fig.root_moved = fig.root_delta + delta, True
        else:
            # FUN_1088_0581 (called per motion frame through FUN_1088_2035) moves the figure by the change of the frame's root
            # x,y for every motion, rotated into the heading, so scripted motions (OUT_OF_BED) carry the figure with them.
            # A turning motion's wrap re-bases the root at 0 (FUN_1088_1854 clears +0xd1..+0xdb), so its first frame moves
            # too. ASSUMPTION: other restarting loops add no displacement (non-travelling cycles return to their start).
            if nxt or fig.turning():
                rp = [f[0] for f in fig.frames]
                prev = rp[fig.idx] if nxt else (0, 0, 0)
                fig.root_delta, fig.root_moved = fig.root_delta + self.root_step(fig, rp[nxt][0] - prev[0], rp[nxt][1] - prev[1], updates), True
        fig.idx = nxt

    # ---- drawing
    def current_camera(self):
        return self.camera or self.default_camera or next(iter(self.cameras), None)

    def sprite_frames(self, cam):
        if cam not in self._sprite_names:
            _, ents = read_flex(os.path.join(ROOMS, cam + '.CAM'))
            self._sprite_names[cam] = [e[3].upper() for e in ents[1:] if e[2]]
        out = {}
        for n in self._sprite_names[cam]:
            out[n] = int(self.vm.globals.get('_' + n.lower() + '_frame', 0) or 0)   # missing variable = frame 0
        return out

    def pose_state(self, fig):
        """(frames, frame, blend) of the figure's current pose. FUN_1088_1854 -> FUN_1088_0d63 blends interior motion-frame segments.
        At a loop's final frame the engine holds that pose until simulation wraps and bakes its root motion."""
        return fig.frames, min(fig.idx, len(fig.frames) - 1), 0.0 if fig.frozen else fig.phase / self.motion_duration(fig)

    def posed(self, fig):
        """World vertices of a figure in its current pose. An idle requested at the end of an update (1088:4155, 4167) reaches the model
        only at the figure's next update, so until then the pose of the update is drawn (`held_pose`). Live, DOSBox-X 2026-11-12:
        FUN_1098_0745 runs for Lex at the end of WAKE_UP, the screen after that update still shows his last WAKE_UP pose, and the next
        update is already GOODMORNINGLEX's OUT_OF_BED: no standing pose in bed."""
        frames, i, alpha = fig.held_pose or self.pose_state(fig)
        V = fig.assets.interpolated_pose(frames, i, alpha)
        return place(V, fig.pos + self.subframe_root(fig, i, alpha, frames), -fig.heading)

    def subframe_root(self, fig, i, alpha, frames=None):
        """FUN_1088_0d63 blends the root x, y toward the next interior frame too, while the world mover steps the position once per
        frame: the drawn position is ahead of fig.pos by the blended part of the next frame's root change, through the figure's matrix.
        Without it a body that travels (OUT_OF_BED's step off the bed) slides back within each frame and jumps forward at the next."""
        frames = fig.frames if frames is None else frames
        if alpha <= 0 or i + 1 >= len(frames):
            return np.zeros(3)
        a, b = frames[i][0], frames[i + 1][0]
        dx = int(a[0] + (b[0] - a[0]) * alpha) - a[0]
        dy = int(a[1] + (b[1] - a[1]) * alpha) - a[1]
        m = self.orientation(fig)
        return np.array([(m[0][0] * dx + m[1][0] * dy) / 256, (m[0][1] * dx + m[1][1] * dy) / 256, 0.0])

    def monitor_viewport_frame(self, cam):
        """Render a monitor feed, reporting a missing remote camera once."""
        name = str(cam).upper()
        if not os.path.exists(os.path.join(ROOMS, name + '.CAM')):
            if name not in self._unknown_viewports:
                self._unknown_viewports.add(name)
                self.warn(f'monitor viewport {name}: no room art')
            return None
        return self.render_camera(name)

    def render_camera(self, cam, indexed=False):
        """Render a named room camera without selecting it or emitting camera events.
        `indexed=True` returns the 200x320 palette-index buffer (compose's indexed path) instead of RGB.

        Remote monitor feeds (for example ROBOCNTL's CTR4) can have room art
        without a local level ``CAMR`` record, so those feeds render their
        static room but omit local figures.
        """
        blank = lambda: np.zeros((200, 320) if indexed else (200, 320, 3), np.uint8)
        if cam is None:
            return blank()
        cam = str(cam).upper()
        if not os.path.exists(os.path.join(ROOMS, cam + '.CAM')):     # e.g. TITLE's camera has no room art
            return blank()
        source_level, camera = self.level_path, self.cameras.get(cam)
        if camera is None:
            remote = self._remote_cameras.get(cam)
            if remote is None:
                remote = next(((path, obj) for path in
                               (os.path.join(self.state_dir, filename) for filename in os.listdir(self.state_dir)
                                if filename.upper().endswith('.IFF'))
                               for obj in load_level_objs(path)
                               if obj['tag'] == 'CAMR' and obj['name'].upper() == cam), False)
                self._remote_cameras[cam] = remote
            if remote:
                source_level, camera = remote
            else:
                return blank()
        figs = []
        for fig in self.figures.values():
            if camera is None or fig.pos is None or fig.frames is None or fig.exploded or (fig.view_cams is not None and cam not in fig.view_cams):
                continue
            V = self.posed(fig)
            if np.all(project(V, camera)[:, 2] > NEAR_DEPTH):
                figs.append((shade_mesh(fig.assets.mesh, V, np.asarray(camera['pos'], float), fig.anim), V))
        figs += self.item_cels(cam, camera)
        figs += [(shade_mesh(m, V, np.asarray(camera['pos'], float)), V) for m, V in self.fragment_meshes(camera)]
        return compose(source_level, cam, figs, self.sprite_frames(cam), indexed=indexed, flats=self.flat_cels(camera))

    def options_underlay(self):
        """What the options dialog is drawn over: the CAMERA SHOW picture, else the screen as it was (a running monitor or the room with its
        caption). Live (DOSBox-X, 2026-11-11, O in CE31) the dialog shows the room dimmed; the world is paused, so a fresh render is that
        screen."""
        shown = self.shown_picture_rgb()
        if shown is not None:
            return shown
        if self.monitor is not None:
            return self.monitor.render_rgb()
        return self.render()

    def credits_rgb(self):
        """The credits page as the original shows it: the roll drawn straight over the undimmed current picture (a flic frame, a running monitor or
        the room), in that picture's palette. -> 200x320x3 RGB."""
        frame = np.array(self.options_underlay(), np.uint8)
        if self.flic is not None and self.flic.frame is not None:
            pal = (np.frombuffer(self.flic.frame.palette, np.uint8).reshape(256, 3).astype(np.int32) >> 2) * 255 // 63
        elif self.monitor is not None:
            pal = np.frombuffer(bytes(self.monitor.pal), np.uint8).reshape(256, 3)
        else:
            import cam as cammod
            path = os.path.join(ROOMS, str(self.current_camera()).upper() + '.CAM')
            if not os.path.exists(path):
                return frame
            d, ents = read_flex(path)
            pal = np.frombuffer(bytes(cammod.palette(d[ents[0][1]:ents[0][1] + ents[0][2]])), np.uint8).reshape(256, 3)
        idx, drawn = self.options.credits_pixels()
        frame[drawn] = pal[idx[drawn]]
        return frame

    def shown_picture_rgb(self):
        """The CAMERA SHOW picture (ROOMS/<cam>.CAM, through its own palette) as 200x320x3 RGB, or None (RTRW has a palette and no picture).
        FUN_10d0_115c switches the screen to that picture camera, so play.to_rgb shows it until a real switch or LOADLEVEL: START's TITLE stays
        up while CHAOS loads, until GOODMORNINGLEX's FADE HIDE. KILLLEX shows STITLE before FORCERELOAD, and live (DOSBox-X, 2026-11-11) the
        options dialog sits on it (Monitor.render underlay)."""
        path = os.path.join(ROOMS, (self.shown_picture or '') + '.CAM')
        if not self.shown_picture or not os.path.exists(path):
            return None
        import cam as cammod
        d, ents = read_flex(path)
        entry = next((x for x in ents[1:] if x[2]), None)
        if entry is None:
            return None
        pal = np.frombuffer(bytes(cammod.palette(d[ents[0][1]:ents[0][1] + ents[0][2]])), np.uint8).reshape(256, 3)
        w, h, hx, hy, px, mask = next(cammod.frames(d[entry[1]:entry[1] + entry[2]]))
        idx = np.zeros((200, 320), np.uint8)
        src, opaque = (np.frombuffer(bytes(b), np.uint8).reshape(h, w) for b in (px, mask))
        for r in range(h):
            y = r - hy
            if 0 <= y < 200:
                for c in np.nonzero(opaque[r])[0]:
                    if 0 <= c - hx < 320:
                        idx[y, c - hx] = src[r, c]
        return pal[idx]

    def render(self, indexed=False):
        if self.flic is not None:                          # 1100:0580: an open flic is drawn instead of the world
            if indexed:
                return np.frombuffer(self.flic.frame.pixels, np.uint8).reshape(200, 320).copy() if self.flic.frame else np.zeros((200, 320), np.uint8)
            return self.flic_rgb()
        return self.render_camera(self.current_camera(), indexed)


def camera_report(level, height=2200):
    """Text report: each CAM_ box (camera, size, ROOMS/<cam>.CAM exists) and, per WAYP, the boxes
    containing it at floor + height. Returns (text, {waypoint: [cameras]})."""
    objs = load_level_objs(os.path.join(GAMEDAT, level.upper() + '.IFF'))
    boxes, lines, cover = cam_boxes(objs), [], {}
    lines.append(f'{level.upper()}: {len(boxes)} CAM_ boxes')
    for b in boxes:
        size = (b['hi'] - b['lo']).astype(int)
        has = os.path.exists(os.path.join(ROOMS, b['camera'] + '.CAM'))
        lines.append(f"  {b['name']:9s} size {size[0]:6d} x {size[1]:6d} x {size[2]:6d}  z {int(b['lo'][2])}..{int(b['hi'][2])}  "
                     f"ROOMS/{b['camera']}.CAM {'yes' if has else 'MISSING'}")
    wps = [o for o in objs if o['tag'] == 'WAYP']
    lines.append(f'waypoints at floor+{height}:')
    for o in wps:
        p = o['pos'] + np.array([0, 0, height])
        cams = [b['camera'] for b in boxes if box_contains(b, p)]
        cover[o['name'].upper()] = cams
        lines.append(f"  {o['name']:10s} {o['pos'].astype(int).tolist()}  -> {', '.join(cams) or '(none)'}")
    lines.append(f'{sum(1 for c in cover.values() if c)}/{len(wps)} waypoints covered by at least one box')
    return '\n'.join(lines), cover


if __name__ == '__main__':
    print(camera_report(sys.argv[1] if len(sys.argv) > 1 else 'LANDPAD', int(sys.argv[2]) if len(sys.argv) > 2 else 2200)[0])
