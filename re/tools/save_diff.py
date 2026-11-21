"""At chosen leg boundaries of the full run: settle, save and load, and diff the saved world with the loaded one.

    re/.venv/bin/python -I -W ignore re/tools/save_diff.py tanks-back,beach

Plays the full run once; at each named boundary a child settles (save_resume_check.settle), snapshots every placed figure, item,
global, live process and plain world attribute, saves, loads with World.from_native_state and writes the differences to
re/out/save_diff/<leg>.txt. It shows only what differs at the save point; save_trace.py follows the two games on from there."""
import os
import sys
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, 're', 'tools'), os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats')]
import numpy as np
import save_resume_check as src  # noqa: E402
import playthrough_full as pf  # noqa: E402
import savegame  # noqa: E402
from world import World  # noqa: E402

FAIL = set(sys.argv[1].split(','))
OUT = os.path.join(ROOT, 're', 'out', 'save_diff')
os.makedirs(OUT, exist_ok=True)

def norm(v, depth=0):
    if isinstance(v, np.ndarray): return [round(float(x), 1) for x in v.ravel()]
    if isinstance(v, (int, float, bool, str, type(None))): return round(v, 1) if isinstance(v, float) else v
    if isinstance(v, (list, tuple)) and depth < 2: return [norm(x, depth + 1) for x in v][:20]
    if isinstance(v, dict) and depth < 2: return {str(k): norm(x, depth + 1) for k, x in list(v.items())[:30]}
    if isinstance(v, (bytes, bytearray)): return bytes(v).hex()
    return '<%s>' % type(v).__name__

SKIP_F = {'assets', 'frames', 'anim', 'decals'}
def fig_state(f):
    return {k: norm(v) for k, v in vars(f).items() if k not in SKIP_F}

def snap(w, vm):
    s = {}
    for k, f in w.figures.items():
        if f.pos is not None: s['fig ' + k.upper()] = fig_state(f)
    for k, i in w.items.items():
        s['item ' + k.upper()] = {a: norm(getattr(i, a, None)) for a in ('type', 'owner', 'slot', 'pos', 'hidden', 'vel', 'gravity')}
    s['globals'] = {k.upper(): v for k, v in vm.globals.items() if isinstance(v, (int, str))}
    s['procs'] = sorted(f'{p.block.name}' for p in vm.procs.values() if not p.done)
    s['world'] = {k: norm(v) for k, v in vars(w).items() if isinstance(v, (int, float, bool, str, type(None))) }
    return s

def diff(a, b):
    out = []
    for k in sorted(set(a) | set(b)):
        if k not in a: out.append(f'+ {k} only after load'); continue
        if k not in b: out.append(f'- {k} lost on load'); continue
        if isinstance(a[k], dict):
            for f in sorted(set(a[k]) | set(b[k])):
                if a[k].get(f) != b[k].get(f):
                    out.append(f'  {k}.{f}: {str(a[k].get(f))[:80]} -> {str(b[k].get(f))[:80]}')
        elif a[k] != b[k]:
            out.append(f'  {k}: lost {sorted(set(a[k]) - set(b[k]))[:15]} new {sorted(set(b[k]) - set(a[k]))[:15]}')
    return out

run = pf.pp.play(run_class=pf.Full)
for name, leg in pf.LEGS[:-1]:
    if not run.passed: break
    leg(run)
    if name not in FAIL: continue
    pid = os.fork()
    if pid == 0:
        try:
            src.settle(run, name, '/dev/null')
            before = snap(run.world, run.vm)
            d = tempfile.mkdtemp(); run.world.saves_dir = d
            path = run.world.save_native(1)
            up = os.path.join(d, 'GAME1.d'); os.makedirs(up)
            savegame.Im1.unpack(open(path, 'rb').read(), up)
            w, vm = World.from_native_state(up); w.vm = vm
            after = snap(w, vm)
            with open(os.path.join(OUT, name + '.txt'), 'w') as fh:
                fh.write('\n'.join(diff(before, after)))
        finally:
            os._exit(0)
    os.waitpid(pid, 0)
    print('done', name, flush=True)
