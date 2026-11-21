"""Oracle fixtures for the native Swift port (native/Tests/BioForgeCoreTests/Fixtures/fixtures.json).

Contains ONLY derived data (counts, names, geometry, SHA-256 digests) - no game bytes. The Swift tests decode the
same files from $BIOFORGE_DATA and must match every value exactly. Deterministic: rerun to regenerate.

Stage 3a adds the script pipeline: per .SCP file the SHA-256 of the detokenized text, the parser's block/label/statement
summary, a canonical AST dump (one line per statement, see stmt_dump) hashed whole and in 100-line chunks, the statement byte
offsets (File.positions), the VM instruction lists (code_dump), and VM traces: TRACES run on the Python VM with a deterministic
stub engine (TraceEngine); the full engine-call log, variable changes and final state are hashed (chunk hashes locate the first
divergence).

Stage 2 adds the 3D character pipeline: per-mesh hashes (every BODY/*.EOR), skeleton/skin/motion data of sample figures,
posed vertices, and indexed (palette-index) 320x200 renders of INITGAME scenes with the level's figures placed as
world.py does at frame 0 of their initial motion, as a frame SHA-256 plus per-row fingerprints (8-pixel segment hashes,
no pixel data).

Stage 4a adds the sound effects: per sample the SHA-256 of the signed 8-bit PCM (E samples, with the loop points in the
sample metadata digest), and for the 1100-tick boot the SHA-256 plus per-second chunk hashes of movie.mix_audio's Int16 output
(effects only, no music).

Stage 3b adds the world binding (world.py): the Mersenne Twister / random.Random stream, key mapping, sound-name table, figure
extents and foot offsets, and the deterministic scenarios (scenarios.py: opening_escape, opening_revival, landpad_meetmech,
beach_tunnel_beach, plus opening_keys driving the key handler) and the 1100-tick new-game boot. Per run: the full engine-call log
(count, SHA-256, 100-entry chunk hashes), every engine-side log (cameras, level loads, hits, sound/subtitle/music, warnings ...),
checkpoint states, a final world state summary (figures, items, globals, processes) and indexed 320x200 framebuffers (SHA-256 and
per-row hashes; 8-pixel segment hashes for the checkpoint and boot frames) at ticks that are multiples of 100.
Floats are written with %.17g in the canonical lines.

Items add the floor / hand items and the Enter key (items.py): selection probes, the motion chosen for each hand state, a
pick-up / shoot / put-down run on CHAOS (event timing, owners, drop placement), indexed frames of Lex holding the blaster, and the
patched ITEM records of the save writer (key `items`).

usage: native_fixtures.py [GAME_DIR]      (default game/app/Bioforge)
"""
import collections, hashlib, itertools, json, os, shutil, struct, sys, tempfile, types
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 're', 'formats'))
sys.path.insert(0, os.path.join(ROOT, 're', 'interp'))
from flex import read_flex, read_flex_depths
from cam import palette, frames
from flc import load as load_flic
from level import load_level
from iff import parse
from eor import Mesh
from compose import compose
import world as W
import movie as MV
import script as SCRIPT
import parse as P
import vm as V

GAME = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'game', 'app', 'Bioforge')
OUT = os.path.join(ROOT, 'native', 'Tests', 'BioForgeCoreTests', 'Fixtures', 'fixtures.json')
sha = lambda b: hashlib.sha256(bytes(b)).hexdigest()

def cam_fixture(path):
    d, ents = read_flex(path)
    images = []
    for i, off, size, name in ents[1:]:
        if not size: continue
        fr = [dict(w=w, h=h, hotx=hx, hoty=hy, pixels=sha(px), mask=sha(m)) for w, h, hx, hy, px, m in frames(d[off:off + size])]
        images.append(dict(index=i, name=name, size=size, frames=fr))
    return dict(entries=len(ents), names=[e[3] for e in ents], palette=sha(palette(d[ents[0][1]:ents[0][1] + 768])),
                images=images)

def show_fixture(path):
    movie = load_flic(path)
    return dict(width=movie.width, height=movie.height, speed=movie.speed,
                frames=[[sha(frame.pixels), sha(frame.palette)] for frame in itertools.islice(movie.frames(), movie.frame_count)])

def pk(fmt, *a): return struct.pack('<' + fmt, *a)

def mesh_fixture(path):
    m = Mesh(path)
    first = lambda suffix: next((v for k, v in m.chunks.items() if k.endswith(suffix)), [(0, 0)])[0]
    (lp, ls), (ap, asz) = first('/DETA/LVL0'), first('/ATTR')
    polys = b''.join(pk('BBB', k, c, len(vi)) + pk(f'{len(vi)}H', *vi) + pk('h', -1 if t is None else t)
                     + (pk(f'{2 * len(vi)}H', *[x for pair in uv for x in pair]) if uv else b'') for k, c, vi, t, uv in m.polys)
    return dict(verts=len(m.verts), polys=len(m.polys), lines=len(m.lines), textures=len(m.textures), anim=len(m.anim),
                vert_sha=sha(b''.join(pk('3i', *v) for v in m.verts)), poly_sha=sha(polys),
                line_sha=sha(b''.join(pk('BBHH', *l) for l in m.lines)),
                tex_sha=sha(b''.join(n.encode('latin1') + b'\0' + pk('HH', w, h) + bytes(px) for n, w, h, px in m.textures)),
                anim_sha=sha(b''.join(pk('HH', i, len(f)) + b''.join(map(bytes, f)) for i, f in sorted(m.anim.items()))),
                lvl0_sha=sha(m.d[lp:lp + ls // 2 * 2]), attr_sha=sha(m.d[ap:ap + asz]), lvl0=ls // 2, attr=asz)

def motion_bytes(frames):
    return b''.join(pk('3i3h', *pos, *rang) + b''.join(pk('3h', *l) for l in limbs) for pos, rang, limbs in frames)

def figure_fixture(ftype):
    a = W.Assets(ftype)
    return dict(
        limbs=[[L.name, L.parent, list(L.rest), list(L.angle), L.length, list(L.offset)] for L in a.skel],
        links=len(a.links), links_sha=sha(pk(f'{len(a.links)}H', *a.links)),
        motions={k: dict(frames=len(v), limbs=len(v[0][2]) if v else 0, sha=sha(motion_bytes(v))) for k, v in a.motions.items()})

SAMPLE_FIGURES = ('LEX', 'NURSEBOT', 'FIDO', 'MECHO', 'GRDCELL', 'TOWERBOT', 'MARINE')
POSE_FIGURES = ('LEX', 'NURSEBOT', 'FIDO', 'MECHO', 'GRDCELL')

def pose_fixtures():
    out = []
    for ftype in POSE_FIGURES:
        a = W.Assets(ftype)
        names = sorted(k for k, v in a.motions.items() if v)
        stand = 'STAND' if 'STAND' in a.motions else names[0]
        other = names[len(names) // 2]
        for name, frame in ((stand, 0), (other, len(a.motions[other]) // 2)):
            V = a.pose(a.motions[name], frame)
            out.append(dict(figure=ftype, motion=name, frame=frame, verts=' '.join(f'{x:.3f}' for x in V.flatten())))
    return out

SCENES = (('CHAOS', 'CE33', 0), ('CHAOS', 'CE11', 0), ('CHAOS', 'CE12', 0), ('CHAOS', 'HAL5', 0), ('CHAOS', 'CE33', 14),
          ('LANDPAD', 'ARL2', 0), ('LANDPAD', 'PAD4', 0))

def scene_fixture(level, camname, tick):
    """Indexed render of an INITGAME level camera: every FIGR figure (heading 0) in its initial motion (STAND, else the first)
    at motion frame (tick // 2) % n, drawn when entirely in front of the camera; shade_mesh gives the prototype's lighting."""
    path = os.path.join(W.INITGAME, level + '.IFF')
    objs = load_level(path)
    cam = next(o for o in objs if o['tag'] == 'CAMR' and o['name'].upper() == camname)
    defs = {}
    for o in objs:
        if o['tag'] == 'FIGR': defs.setdefault(o['raw'][33:42].split(b'\0')[0].decode('latin1').upper(), (o['name'].upper(), o['pos']))
    figs, names, assets = [], [], {}
    for inst, (ftype, pos) in defs.items():
        a = assets.setdefault(ftype, W.Assets(ftype))
        fr = a.motions.get('STAND') or next(iter(a.motions.values()))
        V = W.place(a.pose(fr, (tick // 2) % len(fr)), pos, -0.0)
        if np.all(W.project(V, cam)[:, 2] > W.NEAR_DEPTH):
            figs.append((W.shade_mesh(a.mesh, V, np.asarray(cam['pos'], float)), V)); names.append(inst)
    img = compose(path, camname, figs, {}, indexed=True)
    segs = [''.join(sha(img[y, x:x + 8])[:4] for x in range(0, 320, 8)) for y in range(200)]
    return dict(level=level, camera=camname, tick=tick, figures=names, sha=sha(img), segments=segs)

# ---------------------------------------------------------------- stage 3a: script pipeline (detokenizer, parser, VM)

def qs(s):
    """Canonical string literal: printable ASCII as is, everything else (and \\ ") as \\xHH."""
    return '"' + ''.join(c if 0x20 <= ord(c) < 0x7f and c not in '\\"' else '\\x%02x' % ord(c) for c in s) + '"'

def val(v):
    return str(v) if isinstance(v, int) else qs(v) if isinstance(v, str) else '[' + ','.join(val(x) for x in v) + ']'

def ex(e):
    """Canonical expression text of a parser expression tuple."""
    k = e[0]
    if k == 'num': return str(e[1])
    if k == 'str': return qs(e[1])
    if k == 'name': return 'n:' + e[1]
    if k == 'var': return 'v:' + e[1]
    if k == 'const': return 'c:%d' % e[1]
    if k == 'local': return 'l:%d' % e[1]
    if k == 'mlocal': return 'm:%s.%d' % (e[1], e[2])
    if k == 'un': return '(un %s %s)' % (e[1], ex(e[2]))
    if k == 'bin': return '(%s %s %s)' % (e[1], ex(e[2]), ex(e[3]))
    if k == 'in': return '(%s %s %s)' % ('notin' if e[1] else 'in', ex(e[2]), ex(e[3]))
    if k == 'call': return '(call %s%s)' % (e[1], ''.join(' ' + ex(a) for a in e[2]))
    if k == 'list': return '[' + ' '.join(ex(i) for i in e[1]) + ']'
    if k == 'defid': return 'defid:%d' % e[1]
    raise ValueError(e)

def stmt_dump(stmts, depth, out):
    opt = lambda v: '-' if v is None else str(v)
    for s in stmts:
        if s.op == 'LABEL': args = 'n:' + s.args[0]
        elif s.op == 'ASSIGN': args = '%s %s %s' % (ex(s.args[0]), s.args[1], ex(s.args[2]))
        else: args = ' '.join(ex(a) for a in s.args)
        init = getattr(s, 'init', None)
        out.append('%d|%s|%d|ts=%s|col=%s|def=%s|idx=%s|init=%s|%s' % (
            depth, s.op, s.line, opt(s.ts), opt(s.col), opt(s.defid), opt(s.idx), '-' if init is None else ex(init), args))
        for tag, sub in (('THEN', s.then), ('ELSE', s.els)):
            if sub is not None:
                out.append('%d|%s' % (depth, tag))
                stmt_dump(sub, depth + 1, out)

def table_dump(tag, tables):
    return ['%s|%s|%s|%d' % (tag, name or '-', ','.join(val(v) for v in vals), line) for name, vals, line in tables]

def file_dump(f):
    """Canonical AST text lines of a parsed script file (one line per statement, see stmt_dump)."""
    out = ['FILE %s defs=%d claimed=%d' % (f.name, f.def_count, f.def_claimed)]
    for b in f.blocks:
        out.append('BLOCK|%s|%s|%d|%s' % (b.name, b.kind, b.line, '-' if b.defid is None else b.defid))
        stmt_dump(b.body, 0, out)
        out += table_dump('BT', b.tables)
    out += table_dump('FT', f.tables)
    out += ['DEF|%d|%s' % (k, v.name if v else '-') for k, v in sorted(f.defs.items())]
    out += ['FAIL|%d|%s' % (ln, msg) for _, ln, _, msg in f.failures]
    return out

def code_dump(c):
    """Canonical text of a generated VM instruction list (op, jump target, switch tables, labels, definition indices)."""
    out = []
    for n, i in enumerate(c.ins):
        t = ''
        if i.op in ('JZ', 'JMP'): t = str(i.b)
        elif i.op == 'BREAK': t = '%s %d' % (i.a[1], i.b)
        elif i.op == 'SWITCH': t = 'default=%d cases=%s' % (i.b['default'], ','.join(str(idx) for _, idx in i.b['cases']))
        elif i.op == 'STMT': t = i.a.op
        out.append('%d|%s|%s|ts=%s' % (n, i.op, t, '-' if i.ts is None else i.ts))
    out.append('LABELS ' + ','.join('%s=%d' % kv for kv in sorted(c.labels.items())))
    out.append('DEFIDX ' + ','.join('%s=%d' % kv for kv in sorted(c.defidx.items())))
    return out

def chunk_hashes(lines, n=100):
    return [sha('\n'.join(lines[i:i + n]).encode('latin1'))[:12] for i in range(0, len(lines), n)]

def script_fixture(game, tmp):
    """Detokenizer, parser and code-generation fixtures. `tmp`: scratch folder that receives the decoded <NAME>.scr files."""
    sd = os.path.join(game, 'SCRIPT')
    P.SCRIPT_DIR = sd
    syms = SCRIPT.load_symbols(sd)
    detok, parsed, code_lines, locates = {}, {}, [], []
    defs = P.Defs()
    files = {}
    for n in sorted(os.listdir(sd)):
        if not n.upper().endswith('.SCP'): continue
        st = collections.Counter()
        txt = SCRIPT.detokenize(open(os.path.join(sd, n), 'rb').read(), syms, st, n)
        base = os.path.splitext(n)[0]
        name = base + '.scr'
        detok[name] = dict(sha=sha(txt.encode('latin1')), lines=txt.count('\n') + 1, unresolved=len(st['unresolved']))
        with open(os.path.join(tmp, name), 'w', encoding='latin1', newline='\n') as fh: fh.write(txt)
        files[name] = P.parse_file(os.path.join(tmp, name), defs)
    vm = V.VM(defs=defs)
    for name, f in files.items():
        dump = file_dump(f)
        pos = f.positions()
        poslines = ['%d|%d|%s|%s' % (off, st.line, st.op, b.name) for off, st, b in pos]
        walk = [(b, s) for b in f.blocks for s in P.walk(b.body)]
        parsed[name] = dict(
            blocks=[[b.name, b.kind, b.line] for b in f.blocks],
            labels=[[b.name, s.args[0], s.defid] for b, s in walk if s.op == 'LABEL'],
            statements=len(walk), tables=len(f.tables) + sum(len(b.tables) for b in f.blocks),
            defs=f.def_count, claimed=f.def_claimed, failures=[[ln, msg] for _, ln, _, msg in f.failures],
            ast_lines=len(dump), ast_sha=sha('\n'.join(dump).encode('latin1')), chunks=chunk_hashes(dump),
            pos_count=len(pos), pos_sha=sha('\n'.join(poslines).encode('latin1')), pos_head=[p[0] for p in pos[:8]])
        vm.files.append(f)
        for b in f.blocks:
            code_lines += ['CODE %s|%s' % (name, b.name)] + code_dump(vm.code(b))
    # statements_from / locate: instruction index of the first statement at or after sampled raw offsets
    for name in ('AIRHALL.scr', 'START.scr', 'CHAOS.scr'):
        f = files[name]
        for b in f.blocks[:30]:
            offs = [p[0] for p in f.positions() if p[2] is b]
            for off in offs[::5] + [offs[-1] + 1 if offs else 0, 0]:
                code, idx = vm.locate(b, off)
                locates.append([name, b.name, off, idx])
    return dict(detok=detok, parse=parsed, code_sha=sha('\n'.join(code_lines).encode('latin1')), code_lines=len(code_lines),
                locate=locates)


LEVELS = ('BEACH', 'CHAOS', 'CONTROL', 'DIGSITE', 'LANDPAD', 'PLATFORM', 'TANKS', 'TITLE', 'TOWER', 'TUNROOM')

class TraceEngine(V.RecordingEngine):
    """Deterministic stub engine for the VM traces (the Swift test engine implements exactly the same rules).
    Function results: SOUND-like calls return a timed handle (20 + 10 * (k % 5) ticks, k = per-name call index), RANDOM
    (lo, hi) returns lo + (7k + 3) % (hi - lo + 1), COUNTBITS(v, lo, hi) counts the set bits lo..hi, other names return spec[name] (an int, or a list cycled by k), else spec['*'], else 0.
    Statements: LOADLEVEL swaps the level as world.py does; MON_JUMP blocks the process for 2 ticks (wait_pred)."""

    def __init__(self, returns, script_dir):
        super().__init__(returns)
        self.script_dir, self.counts, self.paused = script_dir, collections.Counter(), False

    def call(self, kind, name, args, proc):
        vm = self.vm
        self.log.append((vm.tick, proc.block.name, kind, name, args))
        k = self.counts[name]
        self.counts[name] += 1
        if kind == 'stmt':
            if name == 'LOADLEVEL' and args and str(args[0]).upper() in LEVELS:
                vm.kill_level_owned(proc)
                vm.unload_scripts()
                V.load_level(vm, str(args[0]), self.script_dir)
                vm.end_unloaded(proc)
            elif name == 'MON_JUMP':
                until = vm.tick + 2
                proc.wait_pred = lambda: vm.tick >= until
            return 0
        if name in ('SOUND', 'GETSOUNDHANDLE', 'SUBTITLE', 'MINORSUBTITLE'):
            return vm.timed_handle(20 + 10 * (k % 5))
        if name == 'RANDOM' and len(args) >= 2 and all(isinstance(a, int) for a in args[:2]):
            lo, hi = min(args[:2]), max(args[:2])
            return lo + (7 * k + 3) % (hi - lo + 1)
        if name == 'COUNTBITS' and len(args) >= 3 and all(isinstance(a, int) for a in args[:3]):
            return sum((args[0] >> b) & 1 for b in range(args[1], args[2] + 1))
        r = self.returns.get(name, self.returns.get('*', 0))
        return r[k % len(r)] if isinstance(r, list) else r

CYCLE = {'*': [0, 1, 2, 0, 3, 1]}       # default function results, cycled per name: drives IF/SWITCH down varied branches

# name, level, fires [(tick, block[, owner[, label]])], ticks, globals set before the run, function results, engine pause window
# (loop iterations during which the engine reports paused)
TRACES = (
    dict(name='game_boot', level='TITLE', fires=[(0, 'GAME', 'global')], ticks=3000, returns=dict(ISMONITORRUNNING=[1, 1, 1, 0])),
    dict(name='game_boot_paused', level='TITLE', fires=[(0, 'GAME', 'global')], ticks=700, pause=(100, 160),
         returns=dict(ISMONITORRUNNING=[1, 1, 1, 0])),
    dict(name='start_label', level='TITLE', fires=[(0, 'STARTPLAYING', 'global', 'WAITHERE'), (5, 'GAME', 'level')], ticks=1500,
         returns=dict(ISMONITORRUNNING=[1, 1, 0])),
    dict(name='landpad_meetmech', level='LANDPAD', fires=[(0, 'MEETMECH')], ticks=420, returns={}),
    dict(name='ani_fire_frame', level='LANDPAD', fires=[(0, 'ANI_FIRE_FRAME')], ticks=240, globals={'_airmecho_dead': '_true'}, returns={}),
    dict(name='airlock_monitor', level='LANDPAD', fires=[(0, 'AIRLOCK_MONITOR')], ticks=60, returns=CYCLE),
    dict(name='city_monitor', level='PLATFORM', fires=[(0, 'CITY_MONITOR')], ticks=120, returns=CYCLE),
    dict(name='tomb_monitor', level='DIGSITE', fires=[(0, 'TOMB_MONITOR')], ticks=300, returns=CYCLE),
    dict(name='nursebot_ai', level='CHAOS', fires=[(0, 'NURSEBOT_AI')], ticks=400, returns=CYCLE),
    dict(name='grav_asteroids', level='TUNROOM', fires=[(0, 'GRAV_ASTEROIDS'), (3, 'GRV_LOAD'), (9, 'GRENADELEAVETUBEROOM')],
         ticks=500, returns=CYCLE),
    dict(name='elite_stimulus', level='PLATFORM', fires=[(0, 'ELITE_STIMULUS'), (60, 'SHIP_HOVER')], ticks=300, returns=CYCLE),
    dict(name='fire_gun', level='TOWER', fires=[(0, 'FIREGUN'), (40, 'TOWERBOT_STIMULUS')], ticks=400, returns=CYCLE),
    dict(name='cr_freezer', level='CHAOS', fires=[(0, 'CR_FREEZERMONITOR'), (7, 'CC_CIRCUITBOARD'), (11, 'FIDO_WAKENS')], ticks=200, returns=CYCLE),
    dict(name='switch_level', level='TOWER', fires=[(0, 'SWITCHTOTOWERLEVEL'), (2, 'SWITCHTOCHAOSLEVEL')], ticks=300, returns=dict(ISLEVEL=[0, 1], ISAION=1)),
)

def trace_fixture(game, scripts, spec):
    """Run one TRACES entry against the decoded scripts in `scripts`; -> the spec plus digests of everything observable."""
    P.SCRIPT_DIR = os.path.join(game, 'SCRIPT')
    eng = TraceEngine(spec.get('returns', {}), scripts)
    vm = V.VM(eng)
    V.load_level(vm, spec['level'], scripts)
    for k, v in spec.get('globals', {}).items():
        vm.globals[k] = vm.defs.consts[v] if isinstance(v, str) else v
    fires = sorted(spec['fires'])
    pause = spec.get('pause')
    for i in range(spec['ticks'] + (pause[1] - pause[0] if pause else 0)):
        eng.paused = bool(pause and pause[0] <= i < pause[1])
        while fires and fires[0][0] <= vm.tick and not eng.paused:
            _, block, *owner = fires.pop(0)
            if len(owner) == 2:
                vm.spawn_at(block, owner[1], ctx=types.SimpleNamespace(cur_fig='LEX', cur_item=None, owner=owner[0]))
            else:
                vm.fire(block, *owner)
        vm.tick_once()
    log = ['%d|%s|%s|%s|%s' % (t, b, kind, n, val(a)) for t, b, kind, n, a in eng.log]
    changes = ['%d|%s|%s|%s' % (t, n, val(o), val(v)) for t, n, o, v in vm.changes]
    glob = ['%s=%s' % kv for kv in sorted((k, val(v)) for k, v in vm.globals.items())]
    objs = ['%s=%s' % (k, val(v)) for k, v in sorted(vm.objects.items())]
    procs = ['%d|%s|%d|%d|%s|%s' % (p.handle, p.block.name, p.pc, p.wake, p.suspended, '-' if p.origin is None else p.origin)
             for p in vm.procs.values()]
    warnings = [w.replace(scripts, '<scripts>') for w in vm.warnings]
    joined = lambda lines: sha('\n'.join(lines).encode('latin1'))
    return dict(spec=dict(spec, fires=[list(f) for f in spec['fires']], pause=list(spec['pause']) if 'pause' in spec else None),
                name=spec['name'], log_len=len(log), log_sha=joined(log), log_chunks=chunk_hashes(log),
                changes_len=len(changes), changes_sha=joined(changes), changes_chunks=chunk_hashes(changes),
                globals_sha=joined(glob), objects_sha=joined(objs), objects=len(objs), procs=procs,
                warnings=warnings, tick=vm.tick, next_handle=vm.next_handle, blocks=len(vm.blocks),
                duplicates=len(vm.duplicates), head=log[:12])


SWITCH_SRC = """{ MAIN
	SWITCH ( _x )
		{
		CASE 1
			_r = 10
			BREAK 0
		CASE 2
			_r = 20
		CASE 3
			_r = _r + 5
			BREAK 0
		CASE 4:
			_r = 40
			BREAK 0
		DEFAULT
			_r = 99
			BREAK 0
		}
	_a = 1
}"""
IF_SRC = """{ MAIN
	IF _x = 1 THEN _a = 1
	ELSE _a = 2
	IF _x == 1 THEN
		_b = 1
	ELSE
		_b = 2
	IF _x = 1 THEN
		{
		_c = 1
		}
	ELSE
		{
		_c = 2
		}
	IF _x != 1 THEN
		_d = 1
	ELSE _d = 2
	_x = 5
	_e = _x
}"""
IN_SRC = """{ MAIN
	IF _x IN 1, 2 THEN _a = 1
	IF _x NOTIN ( 5 , 6 ) THEN _b = 1
	IF ( _x IN -3,-1 ) AND ( _x NOTIN 2,3 ) THEN _c = 1
}"""
ARITH_SRC = """{ MAIN
	_a = 7 / 2
	_b = -7 / 2
	_c = 7 % 3
	_d = -7 % 3
	_e = 5 / 0
	_f = 3 - -2
	_g = (1 + 2) * 3
	_h = 2 * 3 + 4 * 5
	_n = 9 % 0
	_x = ( 10 > 3 ) + ( 2 >= 2 ) + ( 1 < 1 ) + ( 3 != 3 ) + ( 4 <= 4 )
	DEBUG _a _b _c _d _e _f _g _h _n _x
	_a += 4
	_b -= 3
	_c *= 5
	_d /= 2
	_e ++
	_f --
	_r = ( _a AND 0 ) OR ( _b && 1 )
	DEBUG _a _b _c _d _e _f _r "text"
}"""
TIMELINE_SRC = """[ MAIN
	00:01 _a = 1
	00:02 _b = 1
	00:03
	RESETREALTIME
	00:01 _c = 1
	00:02 JUMP DONE
	:DONE
	_d = 1
]"""
# name, source, entry block, ticks, globals set before the run
SYNTHETIC = [
    ('call_return_args', "{ MAIN\n\t_r = CALL ADD 3 4\n\t_a = 1\n}\n{ ADD\n\tLOCALVAR ~0 ~1\n\tWAIT 5\n\tRETURN ~0 + ~1\n}", 'MAIN', 20, {}),
    ('call_no_return', "{ MAIN\n\t_r = 5\n\t_r = CALL CHILD\n}\n{ CHILD\n\t_a = 1\n}", 'MAIN', 20, {}),
    ('process_valid_kill', "{ MAIN\n\t_h = PROCESS FOREVER\n\t_a = ISPROCESSVALID ( _h )\n\tSUSPEND\n\tKILLPROCESS _h\n\t_b = ISPROCESSVALID ( _h )\n}\n"
     "{ FOREVER\n\t:TOP\n\t_c ++\n\tSUSPEND\n\tJUMP TOP\n}", 'MAIN', 20, {}),
    ('suspendwhile_process', "{ MAIN\n\tSUSPENDWHILE PROCESS SLOW\n\t_a = 1\n}\n{ SLOW\n\tWAIT 10\n}", 'MAIN', 20, {}),
    ('suspendwhile_modifyvar', "{ MAIN\n\tSUSPENDWHILE MODIFYVAREVERYNTH ( _b , +1, 1, 5, 4 )\n\t_a = 1\n}", 'MAIN', 40, {}),
    ('waiter_later_in_walk', "{ MAIN\n\t_h = PROCESS SLOW\n\t_g = PROCESS WAITER\n\tSUSPENDWHILE _h\n\t_b = 1\n}\n{ SLOW\n\tWAIT 3\n}\n"
     "{ WAITER\n\tSUSPENDWHILE _h\n\t_a = 1\n}", 'MAIN', 10, {}),     # woken during the walk: both run at the next one (1230:177a)
    ('timeline_process', "[ MAIN\n\t00:01 _h = PROCESS CHILD\n\t00:02 _b = 1\n]\n{ CHILD\n\t_a = 1\n}", 'MAIN', 90, {}),
    ('wait_forms', "{ MAIN\n\t_x = 7\n\tWAIT _x\n\t_a = 1\n\tWAIT 2 SECONDS\n\t_b = 1\n}", 'MAIN', 100, {'_x': 0}),
    ('loop', "{ MAIN\n\t:L\n\t_a ++\n\tLOOP L 5\n\t_b = 1\n}", 'MAIN', 20, {}),
    ('flags', "{ MAIN\n\tSETFLAG ( _a , 3 )\n\tSETFLAG _a 1\n\tTOGGLEFLAG ( _a , 0 )\n\tCLEARFLAG ( _a , 3 )\n\t_b = GETFLAG ( _a , 1 )\n\t_c = GETFLAG ( _a , 3 )\n}",
     'MAIN', 20, {}),
    ('suspend_resume_process', "{ MAIN\n\t_h = PROCESS COUNT\n\tSUSPEND\n\tSUSPENDPROCESS _h\n\tWAIT 5\n\tRESUMEPROCESS _h\n\tWAIT 3\n\tKILLPROCESS _h\n}\n"
     "{ COUNT\n\t:T\n\t_a ++\n\tSUSPEND\n\tJUMP T\n}", 'MAIN', 40, {}),
    ('member_locals', "{ MAIN\n\tSETCURRENTFIGURE FOO\n\tCURFIG.~3 = 9\n\t_a = CALL CHILD\n\tSETCURRENTITEM BAR\n\tCURITEM.~4 = 2\n\tPLAYER.~1 = 6\n}\n"
     "{ CHILD\n\tRETURN CURFIG.~3\n}", 'MAIN', 20, {}),
    ('jump_defid_other_block', "{ MAIN\n\t_a = 0\n\tSWITCH ( _x )\n\t\t{\n\t\tCASE 5:\n\t\t\t_a = 7\n\t\t\tBREAK 0\n\t\tCASE 6:\n\t\t\t_a = 8\n\t\t\tBREAK 0\n\t\t}\n}\n"
     "{ OTHER\n\tJUMP #2\n}", 'OTHER', 20, {}),
    ('jump_unresolved', "{ MAIN\n\tJUMP NOWHERE\n\t_a = 1\n\tJUMP OTHER\n\t_b = 1\n}\n{ OTHER\n\t_c = 1\n\t:LBL\n\t_d = 1\n}", 'MAIN', 20, {}),
    ('unknown_block', "{ MAIN\n\t_a = CALL NOPE 1\n\t_b = PROCESS NOPE2\n\t_c = 1\n}", 'MAIN', 20, {}),
    ('arithmetic', ARITH_SRC, 'MAIN', 20, {}),
    ('timeline', TIMELINE_SRC, 'MAIN', 120, {}),
]
for _x in (1, 2, 3, 4, 9): SYNTHETIC.append(('switch_%d' % _x, SWITCH_SRC, 'MAIN', 5, {'_x': _x}))
SYNTHETIC.append(('bare_break', "{ MAIN\n\tSWITCH ( _x )\n\t\t{\n\t\tCASE 1\n\t\t\tIF _x == 1 THEN BREAK\n\t\t\t_r = 10\n\t\t\tBREAK 0\n\t\t}\n\t_a = 1\n}",
                  'MAIN', 5, {'_x': 1}))           # an operand-less BREAK does nothing (FUN_10d0_0b77): _r is set
for _x in (1, 0): SYNTHETIC.append(('if_else_%d' % _x, IF_SRC, 'MAIN', 5, {'_x': _x}))
for _x in (1, 5, -2, 7): SYNTHETIC.append(('in_notin_%d' % _x, IN_SRC, 'MAIN', 5, {'_x': _x}))

def synthetic_fixture(tmp, name, src, block, ticks, globs):
    """Small inline scripts (the Python unit tests' idioms) run on the Python VM with a RecordingEngine."""
    defs = P.Defs()
    defs.vars.update(globs)
    for n in 'abcdefghrnx': defs.vars.setdefault('_' + n, 0)
    path = os.path.join(tmp, 'SYN_%s.scr' % name)
    with open(path, 'w', encoding='latin1', newline='\n') as fh: fh.write(src)
    vm = V.VM(defs=defs)
    f = vm.load(path)
    assert not f.failures, (name, f.failures)
    vm.fire(block)
    vm.run_ticks(ticks)
    return dict(name=name, src=src, block=block, ticks=ticks, globals=globs,
                log=['%d|%s|%s|%s|%s' % (t, b, kind, n, val(a)) for t, b, kind, n, a in vm.engine.log],
                changes=['%d|%s|%s|%s' % (t, n, val(o), val(v)) for t, n, o, v in vm.changes],
                vars={k: val(vm.globals[k]) for k in sorted(defs.vars) if k in ['_' + c for c in 'abcdefghrnx']},
                objects={k: val(v) for k, v in sorted(vm.objects.items())}, warnings=vm.warnings,
                procs=['%d|%s|%d|%d' % (p.handle, p.block.name, p.pc, p.wake) for p in vm.procs.values()], tick=vm.tick)

# ---------------------------------------------------------------- stage 3b: world binding (world.py)

import copy, random
import keys as KEYS
import scenarios as SC

def cv(x):
    """Canonical text of a log value (the Swift tests build the same text): None -, bool T/F, ints, floats %.17g, strings quoted."""
    if x is None: return '-'
    if isinstance(x, (bool, np.bool_)): return 'T' if x else 'F'
    if isinstance(x, (int, np.integer)): return str(int(x))
    if isinstance(x, (float, np.floating)): return '%.17g' % x
    if isinstance(x, str): return qs(x)
    if isinstance(x, np.ndarray): x = x.tolist()
    return '[' + ','.join(cv(i) for i in x) + ']'

def row(*xs): return '|'.join(cv(x) for x in xs)

def digest(lines, keep=40):
    """Count, hash, 100-line chunk hashes and (for short logs) the lines themselves."""
    d = dict(len=len(lines), sha=sha('\n'.join(lines).encode('latin1')), chunks=chunk_hashes(lines))
    d['lines'] = lines if len(lines) <= keep else lines[:keep]
    return d

def rng_fixture():
    out = []
    for seed in (0, 1, 12345, 2 ** 40 + 7):
        r = random.Random(seed)
        raw = [r.getrandbits(32) for _ in range(6)]
        r = random.Random(seed)
        spans = [(1, 6), (0, 99), (1, 1), (0, 1), (5, 5), (0, 255), (-3, 3), (1, 100000), (0, 5 * 10 ** 9), (7, 8), (0, 2 ** 31)]
        draws = [[lo, hi, r.randint(lo, hi)] for _ in range(40) for lo, hi in spans]
        out.append(dict(seed=seed, raw=raw, draws=draws))
    return out

def keys_fixture():
    lines = []
    for scan in range(0x59):
        for mods in (0, KEYS.SHIFT, KEYS.CTRL, KEYS.ALT):
            for combat in (False, True):
                for playing in (None, 'ATK_M4', 'RUN', 'WALK'):
                    lines.append(row(scan, mods, combat, playing, list(KEYS.action(scan, mods, combat, playing) or ('-',))))
    return digest(lines, 0)

def sound_fixture():
    sm, ids = W.sound_bank()
    lines = [row(k, v) for k, v in sorted(ids.items())]
    meta = [row(i, s.name, s.rate, s.loop_start, s.loop_end, len(s.pcm)) for i in range(len(sm)) for s in [sm.get(i)]]
    pcm = [row(i, sha(sm.get(i).pcm.tobytes())) for i in range(len(sm))]
    return dict(ids=digest(lines, 0), samples=digest(meta, 0), pcm=digest(pcm, 0))

def audio_fixture(world, vm):
    """movie.mix_audio of the run (22050 Hz Int16), the window from the first CHAOS LOADLEVEL to the end (735 samples per tick): whole-output
    and per-second hashes. The intro's sounds before it are mixed in the same pass but not part of the window."""
    pcm = MV.mix_audio(world, vm.tick)[world.level_loads[0][0] * 735:]
    b = pcm.tobytes()
    return dict(frames=len(pcm), sha=sha(b), seconds=[sha(b[i * 2:(i + 22050) * 2]) for i in range(0, len(pcm), 22050)])

def asset_fixture():
    out = {}
    for t in sorted(os.listdir(os.path.join(GAME, 'BODY'))):
        if not t.endswith('.BED'): continue
        t = t[:-4]
        try: a = W.Assets(t)
        except Exception: continue
        names = sorted(k for k, v in a.motions.items() if v)
        other = names[len(names) // 2]
        bits = lambda name, f: sha(b''.join(struct.pack('<3d', *v) for v in a.pose(a.motions[name], f)))
        out[t] = dict(foot='%.17g' % a.foot_offset,
                      pose_bits=[bits('STAND' if 'STAND' in a.motions else names[0], 0), bits(other, len(a.motions[other]) // 2)])
    return dict(assets=out, extents={k: [float(x) for x in v] for k, v in sorted(W.figure_extents().items())})

def frame_fixture(world, tick, segments=False):
    img = world.render(indexed=True)
    d = dict(tick=tick, camera=world.current_camera(), sha=sha(img), rows=[sha(img[y])[:8] for y in range(200)])
    if segments: d['segments'] = [''.join(sha(img[y, x:x + 8])[:4] for x in range(0, 320, 8)) for y in range(200)]
    return d

def cp_lines(c):
    """Canonical lines of a scenarios.checkpoint dict."""
    out = [row('CP', c['name'], c['tick'], c['level'], c['camera'])]
    p = c['player']
    out.append(row('P', *( ['-'] if p is None else [p['name'], p['position'], p['motion'], p['collisions']])))
    for n, f in sorted(c['figures'].items()):
        out.append(row('F', n, f['type'], f['position'], f['motion'], f['collisions'], f['view_cams']))
    for n, i in sorted(c['items'].items()):
        out.append(row('I', n, i['type'], i['owner'], i['slot']))
    return out

def world_lines(world, vm):
    """Canonical lines of the final world state (figures in dict order, items, scalars)."""
    out = [row('W', world.level, world.camera, world.default_camera, world.current_camera(), world.script_auto, world.follow,
               world.candidate, world.selected, world.loaded_cam, world.player_name, sorted(world.disabled),
               world.current_music, world.exit_requested, world.paused, vm.tick, vm.next_handle)]
    for n, f in world.figures.items():
        out.append(row('F', n, f.name, f.type, None if f.pos is None else f.pos.tolist(), f.heading, f.motion, f.idx, f.loop, f.phase,
                       f.finished, f.frozen, f.combat, f.spar, f.collisions, f.hit_done, f.manual_control, f.go is not None,
                       f.enemy, f.ai_type, f.ai_proc is not None and not f.ai_proc.done, f.view_cams))
    for n, i in world.items.items():
        out.append(row('I', n, i.name, i.type, i.owner, i.slot))
    for n, v in world.log_entries.items():
        out.append(row('L', n, v, world.log_entry_times.get(n)))
    return out

def run_lines(world, vm):
    """Every engine-side log of a finished run as {name: lines}."""
    L = lambda xs: [row(*x) for x in xs]
    pos = lambda p: None if p is None else p.tolist()
    return {
        'camera_changes': L(world.camera_changes), 'level_loads': L([(t, l, a, pos(p)) for t, l, a, p in world.level_loads]),
        'hits': L(world.hits), 'events': L(world.events), 'sound_log': L(world.sound_log), 'sound_stops': L(world.sound_stops), 'sound_releases': L(world.sound_releases),
        'sound_drops': L(world.sound_drops), 'sound_volumes': L(world.sound_volumes), 'subtitle_log': L(world.subtitle_log),
        'music_log': L(world.music_log), 'warnings': [row(w) for w in world.warnings + vm.warnings], 'key_log': L(world.key_log),
        'option_actions': L(world.option_actions), 'monitor_codes': L(world.monitor_codes),
        'world': world_lines(world, vm),
        'globals': [row(k, v) for k, v in sorted(vm.globals.items())],
        'objects': [row(k, v) for k, v in sorted(vm.objects.items())],
        'procs': [row(p.handle, p.block.name, p.pc, p.wake, p.suspended, p.origin) for p in vm.procs.values()],
    }

def scenario_runner(name, fn, boot=False, ticks=0, anchored=False):
    """Run one scenario (scenarios.py function, or the plain boot) recording the engine-call log, frames and checkpoint states. `anchored`
    (the new-game scenarios): frames are keyed by ticks after the first CHAOS LOADLEVEL (0 = the end of its tick), none before it; the boot
    run is that many ticks after the load, i.e. `ticks` ticks of the intro-free part."""
    frames, cps = {}, {}
    seen = {}
    orig_step, orig_cp = W.World.step, SC.checkpoint
    def step(self):
        orig_step(self)
        seen['world'], seen['vm'] = self, self.vm
        rel = self.vm.tick if not anchored else (self.vm.tick - (self.level_loads[0][0] + 1) if self.level_loads else -1)
        if rel >= 0 and (rel % 100 == 0 or (boot and rel in (1, 400, 700, 900, 1100))):
            frames[rel] = frame_fixture(self, self.vm.tick, segments=boot)
    def cp(world, vm, nm, frame=False):
        r = orig_cp(world, vm, nm, frame)
        if frame: cps[nm] = frame_fixture(world, vm.tick, segments=True)
        return r
    W.World.step, SC.checkpoint = step, cp
    try:
        if boot:
            world, vm = SC.boot_opening()
            SC.tick(world, vm, ticks)
            result = None
        else:
            result = fn()
    finally:
        W.World.step, SC.checkpoint = orig_step, orig_cp
    world, vm = seen['world'], seen['vm']
    log = [row(t, b, k, n, a) for t, b, k, n, a in world.log]
    r = copy.deepcopy(world.rng)
    logs = {k: digest(v, 60 if k != 'globals' else 0) for k, v in run_lines(world, vm).items()}
    out = dict(name=name, ticks=vm.tick, log=digest(log, 12), logs=logs, frames={str(k): v for k, v in sorted(frames.items())},
               checkpoint_frames=cps, rng_next=[r.randint(0, 99) for _ in range(3)],
               command_counts=dict(sorted(collections.Counter(rec[3] for rec in world.log).items())))
    if boot: out['audio'] = audio_fixture(world, vm)
    if result is not None:
        out['checkpoints'] = [digest(cp_lines(c), 100) for c in result['checkpoints']]
        out['final_globals'] = result['final_globals']
        out['input_events'] = result['input_events']
        out['result_warnings'] = result['warnings']
    else:
        out['checkpoints'] = []
    return out

def opening_keys():
    """Key handler path: the opening cell, walk with the up key, combat toggle, shoot and use (like scenarios.opening_escape)."""
    world, vm = SC.boot_opening()
    SC.tick(world, vm, SC.opening_ticks(1170))
    world.script_auto = True
    world.set_camera('CE31', 'scenario handoff')
    cps = [SC.checkpoint(world, vm, 'keys-ready', frame=True)]
    world.key_down(0x48)                       # up arrow: walk
    SC.tick(world, vm, 90)
    world.key_down(0x4b, KEYS.SHIFT)           # + shift-left: fast turn
    SC.tick(world, vm, 20)
    world.key_up(0x4b)
    world.key_down(0x4d)                       # right turn while walking
    SC.tick(world, vm, 10)
    world.key_up(0x4d); world.key_up(0x48)
    SC.tick(world, vm, 5)
    cps.append(SC.checkpoint(world, vm, 'keys-walked', frame=True))
    world.key_down(0x2e); world.key_up(0x2e)   # C: combat on
    SC.tick(world, vm, 10)
    world.key_down(0x4c); world.key_up(0x4c)   # keypad 5: shoot (script-gated)
    SC.tick(world, vm, 10)
    world.key_down(0x48, KEYS.SHIFT)           # combat + shift-up: run
    SC.tick(world, vm, 30)
    world.key_up(0x48)
    world.key_down(0x4b)                       # combat M4
    SC.tick(world, vm, 15)
    world.key_up(0x4b)
    world.key_down(0x39); world.key_up(0x39)   # Space: use
    SC.tick(world, vm, 5)
    world.key_down(0x2e); world.key_up(0x2e)   # C: combat off
    SC.tick(world, vm, 20)
    cps.append(SC.checkpoint(world, vm, 'keys-end', frame=True))
    return SC.scenario_result('opening_keys', world, vm, cps, [])

def items_world(level='CHAOS', lex=(495.0, -28827.0), heading=0.0):
    """A level at its INITGAME state with Lex placed as the player (the Swift test builds the same)."""
    w = W.World(level, state_dir=W.INITGAME)
    vm = V.VM(w)
    V.load_level(vm, level)
    fig = w.figures['LEX'] = W.Figure('LEX', 'LEX', w.asset('LEX'))
    w.player_name, fig.view_cams = 'LEX', None
    fig.pos, fig.heading = np.array([lex[0], lex[1], -5000.0]), float(heading)
    w.settle(fig)
    return w, vm, fig

def items_fixture():
    f6 = lambda x: f'{x:.6f}' if abs(x) >= 5e-7 else '0.000000'
    def run(w, vm, n):
        for _ in range(n):
            vm.tick_once(); w.step()
    def press(w, scan=0x1c):
        w.key_down(scan); w.key_up(scan)
    def until(w, vm, pred, limit=200):
        for n in range(1, limit + 1):
            run(w, vm, 1)
            if pred(): return n
        return None
    lines, frames = [], {}
    # selection: Lex facing the CHAOS blaster at distances and bearings, and the nearer of two items ahead
    w, vm, lex = items_world()
    pick = lambda: (lambda c: c.name if c else None)(w.pickup_candidate(lex))
    for d in (500, 1000, 2000, 2303, 2304, 2500):
        lex.pos[:2] = (495.0, -29827.0 + d); lex.heading = 0.0
        lines.append(row('S', 'dist', d, pick()))
    lex.pos[:2] = (495.0, -28827.0)
    for h in (0, 30, 59, 61, -59, -61, 90, 180):
        lex.heading = float(h)
        lines.append(row('S', 'heading', h, pick()))
    lex.pos[:2], lex.heading = (-1000.0, -6900.0), 90.0
    lines.append(row('S', 'two', pick()))
    # the motion for every hand state (LANDPAD has no LEX_PUT_DOWN_* script gate)
    w, vm, lex = items_world('LANDPAD', (0.0, 0.0))
    for left, right, near in ((None, None, None), (None, None, 'BLASTER'), (None, None, 'FORK'), (None, 'BLASTER', None),
                              (None, 'BLASTER', 'FORK'), (None, 'BLASTER', 'CAYARM'), ('FORK', None, None), ('FORK', None, 'BLASTER'),
                              ('FORK', None, 'MEAT1'), ('FORK', 'BLASTER', None), ('FORK', 'BLASTER', 'BLASTER')):
        w.items.clear(); lex.set_motion('STAND', True); w.pick_targets.clear()
        for hand, t in (('LTHAND', left), ('RTHAND', right)):
            if t:
                it = w.items['HELD_' + hand] = W.Item('HELD_' + hand, t, 'LEX', hand)
        if near:
            it = w.items['NEAR'] = W.Item('NEAR', near); it.pos, it.matrix = np.array([0.0, -1000.0, -7280.0]), np.eye(3)
        w.player_pickup(lex)
        lines.append(row('M', left, right, near, None if lex.motion == 'STAND' else lex.motion, sorted(w.pick_targets.items())))
    # CHAOS: pick up the blaster, shoot, walk to the fork, pick it up, put it down, put the blaster down
    w, vm, lex = items_world()
    w.script_auto = False
    w.set_camera('CE24', 'items')
    frames['floor'] = frame_fixture(w, vm.tick)
    b, fork = w.items['BLASTER'], w.items['FORK']
    press(w)
    n = until(w, vm, lambda: b.owner is not None)
    lines.append(row('T', 'grab', n, lex.motion, lex.idx, b.owner, b.slot, w.is_carrying(lex, 'RTHAND', 'BLASTER'),
                     w.is_carrying(lex, 'LTHAND'), [a for _, a, d in w.key_log if a == 'item'], len(w.subtitle_log)))
    frames['held'] = frame_fixture(w, vm.tick)
    run(w, vm, 40)
    lines.append(row('T', 'end', lex.motion, lex.loop))
    press(w, 0x4c); run(w, vm, 3)
    lines.append(row('T', 'shoot', lex.motion, lex.loop, lex.idx))
    run(w, vm, 8)
    frames['shoot'] = frame_fixture(w, vm.tick)
    run(w, vm, 40)
    lex.set_motion('STAND', True)
    lex.pos[:2], lex.heading = (-2466.0, -6717.0), 0.0
    press(w)
    n = until(w, vm, lambda: fork.owner is not None)
    lines.append(row('T', 'grab-left', n, lex.motion, lex.idx, fork.owner, fork.slot, w.is_carrying(lex, 'LTHAND', 'FORK')))
    run(w, vm, 40)
    lex.pos[:2], lex.heading = (5000.0, -20000.0), 0.0
    press(w)                                                          # both hands full: the left item goes down
    n = until(w, vm, lambda: fork.owner is None)
    lines.append(row('T', 'drop-left', n, lex.motion, fork.owner, fork.slot, b.owner, b.slot,
                     [f6(v) for v in fork.pos], [f6(v) for r in fork.matrix for v in r]))
    run(w, vm, 40)
    lex.pos[:2], lex.heading = (5000.0, -20000.0), 0.0
    press(w)                                                          # a free left hand and nothing in front but the dropped fork behind
    run(w, vm, 5)
    lines.append(row('T', 'again', lex.motion, sorted(w.pick_targets.items())))
    frames['dropped'] = frame_fixture(w, vm.tick)
    # the save writer: ITEM records patched to a carried / dropped state
    objs = [d for t, d in ((o['tag'], o['raw']) for o in W.load_level_objs(os.path.join(W.INITGAME, 'CHAOS.IFF'))) if t == 'ITEM']
    import savewrite
    rec = next(r for r in objs if r[:9].startswith(b'BLASTER'))
    states = [('LEX', 'RTHAND', None, None), ('LEX', 'LTHAND', None, None), ('LEX', 'INVENTORY', None, None), ('LEX', 'RTHAND', None, None),
              (None, None, [1.0, -2.0, 3.0], np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], float).tolist()), (None, None, None, None)]
    for st in states:
        lines.append(row('R', st[0], st[1], sha(savewrite.patch_item(rec, st, {'LEX': 260}))))
    lines.append(row('R', 'unknown', sha(savewrite.patch_item(rec, ('LEX', 'RTHAND', None, None), {}))))
    return dict(lines=digest(lines, 200), frames=frames)

def inventory_fixture():
    """The PIMM item list, READY hand transfer, and I-key stow from the Python oracle."""
    def screen_frame(world, tick):
        pixels, _ = world.monitor.render()
        return dict(tick=tick, camera=None, sha=sha(pixels),
                    rows=[sha(pixels[y * 320:(y + 1) * 320])[:8] for y in range(200)])

    def run(n):                                  # the VM and the world tick together, as the Swift session does
        for _ in range(n):
            vm.tick_once()
            w.step()

    w, vm, lex = items_world()
    vm.fire('GIVELEXSTARTINGBATT')
    run(1)
    w.items['FORK_CARRIED'] = W.Item('FORK_CARRIED', 'FORK', 'LEX', 'INVENTORY')
    w.open_pimm('INVENTORY')
    for _ in range(80):                          # PIMM's `MOTION LOOK_AT_PIM FREEZE` blocks until the motion has played (about 36 ticks)
        if w.monitor is not None:
            break
        run(1)
    m = w.monitor
    frames = {'battery': screen_frame(w, vm.tick)}
    lines = [row('initial', m.elements['INMT'].items, m.elements['INMT'].sel,
                 m.elements['DEST'].entries[0][0], m.elements['IITA'].frame)]
    w.monitor_tap('IPDB')
    m = w.monitor
    frames['fork'] = screen_frame(w, vm.tick)
    lines.append(row('selected', m.elements['INMT'].items, m.elements['INMT'].sel,
                     m.elements['DEST'].entries[0][0], m.elements['IITA'].frame))
    w.monitor_tap('RDYB')
    run(4)
    fork = w.items['FORK_CARRIED']
    lines.append(row('ready', fork.owner, fork.slot, w.monitor is None))
    w.key_down(0x17); w.key_up(0x17)
    lines.append(row('stowed', fork.owner, fork.slot, w.monitor is None))
    w.key_down(0x17); w.key_up(0x17)
    for _ in range(80):
        if w.monitor is not None:
            break
        run(1)
    frames['stowed'] = screen_frame(w, vm.tick)
    lines.append(row('reopened', w.monitor.elements['INMT'].items, w.monitor.elements['INMT'].sel))
    return dict(lines=digest(lines), frames=frames)

INTRO_FRAME_TICKS = (20, 800, 1700, 2500)     # inside the movie: INTROSPACE (rate 6, from tick 0), INTROCRATER (1578-2095), INTROOPENING (2410-3704)

def intro_fixture():
    """The intro movie of a new game, from tick 0 to the end of the tick of the first CHAOS LOADLEVEL: indexed frames at INTRO_FRAME_TICKS
    (the flic frame, or black before the first RUNFLIC draw) and the engine-side sound / subtitle / music / camera / level logs, handles included."""
    world = W.World('TITLE', state_dir=W.INITGAME)
    vm = V.VM(world)
    V.load_level(vm, 'TITLE')
    world.fire_event('TITLE_LOAD')
    vm.fire('GAME', 'global')
    frames = {}
    while not world.level_loads:
        SC.tick(world, vm, 1)
        if vm.tick in INTRO_FRAME_TICKS: frames[vm.tick] = frame_fixture(world, vm.tick)
    lines = run_lines(world, vm)
    keep = ('sound_log', 'sound_stops', 'sound_volumes', 'subtitle_log', 'music_log', 'camera_changes', 'level_loads', 'events')
    return dict(ticks=vm.tick, frames={str(k): v for k, v in sorted(frames.items())}, logs={k: digest(lines[k], 20) for k in keep})

def stage3b_fixture():
    # NOTE: Python key_down(I/P/D/J) starts the PIMM scripts; the native port only logs those keys, so no run presses them
    runs = [scenario_runner('boot', None, boot=True, ticks=1100, anchored=True),
            scenario_runner('opening_escape', SC.opening_escape, anchored=True),
            scenario_runner('opening_revival', SC.opening_revival, anchored=True),
            scenario_runner('landpad_meetmech', SC.landpad_meetmech), scenario_runner('beach_tunnel_beach', SC.beach_tunnel_beach),
            scenario_runner('opening_keys', opening_keys, anchored=True)]
    return dict(rng=rng_fixture(), keys=keys_fixture(), sounds=sound_fixture(), assets=asset_fixture(), runs=runs, intro=intro_fixture())


def nurse_push_fixture():
    """Replay inputs and explicit attack setup only; no game assets are embedded."""
    result = SC.opening_nurse_defeat()
    encounter = result['encounter']
    assert encounter['nurse_removed'] and encounter['escaped'] and encounter['lex_health'] == 100
    # ticks are counted from the end of the tick of the first CHAOS LOADLEVEL (0), as the Swift test replays them
    base = result['level_loads'][0][0] + 1
    shift = lambda rows: [dict(r, tick=r['tick'] - base) for r in rows]
    return dict(input_events=shift(result['input_events']), fixtures=shift(encounter['fixtures']),
                checkpoints=shift(result['checkpoints']))


def main():
    rooms = sorted(os.listdir(os.path.join(GAME, 'ROOMS')))
    sample = {'CE11.CAM', 'CE33.CAM'} | set(rooms[::8])
    sample = sorted(sample)[:30] if len(sample) > 30 else sorted(sample)
    sample = sorted(set(sample) | {'CE11.CAM', 'CE33.CAM'})
    cams = {f'ROOMS/{n}': cam_fixture(os.path.join(GAME, 'ROOMS', n)) for n in sample}
    for n in ('PIMM.CAM', 'OPTS.CAM', 'MLBT.CAM', 'POINTER.CAM', 'KYPD.CAM'):
        cams[f'MONITORS/{n}'] = cam_fixture(os.path.join(GAME, 'MONITORS', n))
    # every ROOMS and MONITORS .CAM: frame counts (together 8446, as check_cams.py reports)
    def count_frames(sub):
        total = files = 0
        for n in sorted(os.listdir(os.path.join(GAME, sub))):
            if not n.endswith('.CAM'): continue
            files += 1
            d, ents = read_flex(os.path.join(GAME, sub, n))
            for i, off, size, name in ents[1:]:
                if size: total += struct.unpack_from('<H', d, off + 4)[0]
        return total, files
    total, nrooms = count_frames('ROOMS')
    mon_total, nmon = count_frames('MONITORS')
    flex = {}
    for rel in ('MUSIC/MUSIC.FLX', 'ROOMS/CE11.CAM', 'ROOMS/TWR1.CAM'):
        d, ents = read_flex(os.path.join(GAME, rel))
        flex[rel] = dict(count=len(ents), entries=[[o, s, n] for _, o, s, n in ents],
                         depths=read_flex_depths(os.path.join(GAME, rel)))
    levels = {}
    for n in ('CHAOS', 'BEACH', 'TUNROOM'):
        p = os.path.join(GAME, 'INITGAME', n + '.IFF')
        objs = load_level(p)
        counts = {}
        for o in objs: counts[o['tag']] = counts.get(o['tag'], 0) + 1
        levels[f'INITGAME/{n}.IFF'] = dict(
            counts=dict(sorted(counts.items())),
            names=[[o['tag'], o['name']] for o in objs],
            pos2=[[int(v) for v in o['pos2']] for o in objs if 'pos2' in o][:20],
            cameras=[dict(name=o['name'], pos=[int(v) for v in o['pos']], flag=o['flag'],
                          rot=[int(v) for v in o['R'].flatten() * 256], vec=[int(v) for v in o['vec']],
                          extra=list(o['extra'])) for o in objs if o['tag'] == 'CAMR'])
    iffd = open(os.path.join(GAME, 'INITGAME', 'CHAOS.IFF'), 'rb').read()
    top = parse(iffd)[0]
    levels['iff_top'] = dict(type=top[1].decode(), kids=[[c[0].decode(), c[3]] for c in top[4]][:40])
    body = os.path.join(GAME, 'BODY')
    meshes = {n: mesh_fixture(os.path.join(body, n)) for n in sorted(os.listdir(body)) if n.endswith('.EOR')}
    stage2 = dict(meshes=meshes, figures={t: figure_fixture(t) for t in SAMPLE_FIGURES}, poses=pose_fixtures(),
                  scenes=[scene_fixture(*sc) for sc in SCENES])
    tmp = tempfile.mkdtemp()
    try:
        scripts = script_fixture(GAME, tmp)
        scripts['traces'] = [trace_fixture(GAME, tmp, spec) for spec in TRACES]
        scripts['synthetic'] = [synthetic_fixture(tmp, *args) for args in SYNTHETIC]
    finally:
        shutil.rmtree(tmp)
    stage3b = stage3b_fixture()
    shows = {n: show_fixture(os.path.join(GAME, 'SHOW', n)) for n in ('INTRO.SHO', 'INTROF.SHO', 'INTROG.SHO', 'ENDGAME.SHO', 'DEMO1.SHO', 'PLT0.SHO')}
    fx = dict(cams=cams, shows=shows, stage2=stage2, stage3=scripts, stage3b=stage3b, items=items_fixture(), inventory=inventory_fixture(), rooms_total_frames=total, rooms_files=nrooms,
              monitors_total_frames=mon_total, monitors_files=nmon, flex=flex, levels=levels)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f: json.dump(fx, f, indent=1, sort_keys=True); f.write('\n')
    nurse_out = os.path.join(os.path.dirname(OUT), 'nurse_push.json')
    with open(nurse_out, 'w') as f:
        json.dump(nurse_push_fixture(), f, indent=1, sort_keys=True)
        f.write('\n')
    print(f'{OUT}: {len(scripts["detok"])} scripts, {len(scripts["traces"])} traces, {len(meshes)} meshes, {len(stage2["scenes"])} scenes, {len(cams)} cams, {total} frames in {len(rooms)} room files, {len(levels)-1} levels')

if __name__ == '__main__':
    main()
