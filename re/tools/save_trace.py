"""Side by side from one save point: the saved-and-loaded game against the animation-restart control (save_resume_check --control).

    re/.venv/bin/python -I -W ignore re/tools/save_trace.py LEG [--ticks 20000] [--out DIR]

Plays the full run to the boundary after LEG, settles (save_resume_check.settle), then forks two children: one only restarts the
animations (restart_animations), the other saves and loads (as resume_and_finish). Both play the remaining legs and write a line per
tick (level, every placed figure's rounded position / motion / hit points, the live processes with their pc, the globals) to
DIR/control.jsonl and DIR/loaded.jsonl. Then it prints the first tick where the two differ in each kind of state. Positions are
compared to 8 units, so rounding noise does not count."""
import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, 're', 'tools'), os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats')]
import playthrough_full as pf  # noqa: E402
import save_resume_check as src  # noqa: E402
import scenarios  # noqa: E402
import savegame  # noqa: E402
from world import World  # noqa: E402


def snap(w, vm):
    figs = {}
    for k, f in w.figures.items():
        if f.pos is None:
            continue
        figs[k.upper()] = [[int(v) // 8 for v in f.pos], f.motion, vm.objects[k.upper()][0] if k.upper() in vm.objects else None,
                           bool(f.combat), getattr(f, 'area', None)]
    procs = sorted(f'{p.block.name}@{p.pc}' + ('~' if p.suspended else '') for p in vm.procs.values() if not p.done)
    glob = {k: v for k, v in vm.globals.items() if isinstance(v, (int, str))}
    return {'level': w.level, 'figs': figs, 'procs': procs, 'globals': glob}


def trace(path, ticks):
    """Wrap scenarios.tick (every harness's frame step) so every tick writes a snapshot; stop the child after `ticks` lines."""
    fh, count, orig = open(path, 'w'), [0], scenarios.tick

    def tick(world, vm, n, controls=None):
        for i in range(n):
            orig(world, vm, 1, None if controls is None else (lambda _, i=i: controls(i)))
            fh.write(json.dumps(snap(world, vm)) + '\n')
            count[0] += 1
            if count[0] >= ticks:
                fh.close()
                os._exit(0)
    scenarios.tick = tick
    return fh


def child(run, mode, path, ticks):
    if mode == 'control':
        src.restart_animations(run.world)
    else:
        d = tempfile.mkdtemp()
        run.world.saves_dir = d
        save = run.world.save_native(1)
        unpacked = os.path.join(d, 'GAME1.d')
        os.makedirs(unpacked)
        savegame.Im1.unpack(open(save, 'rb').read(), unpacked)
        w, vm = World.from_native_state(unpacked)
        w.vm = vm
        w.rng.setstate(run.world.rng.getstate())
        w.level_loads = list(run.world.level_loads)
        run.world, run.vm, run.lex = w, vm, w.player()
    fh = trace(path, ticks)
    fh.write(json.dumps(snap(run.world, run.vm)) + '\n')
    names = [n for n, _ in pf.LEGS]
    try:
        for _, leg in pf.LEGS[names.index(run._leg) + 1:]:
            if not run.passed:
                break
            leg(run)
    except Exception as e:                          # noqa: BLE001
        fh.write(json.dumps({'error': repr(e)[:300]}) + '\n')
    fh.close()


def compare(a_path, b_path, limit=6):
    a, b = open(a_path).read().splitlines(), open(b_path).read().splitlines()
    first = {}
    for i, (la, lb) in enumerate(zip(a, b)):
        sa, sb = json.loads(la), json.loads(lb)
        if 'error' in sa or 'error' in sb:
            print(i, 'error', sa.get('error'), sb.get('error'))
            break
        if sa['level'] != sb['level'] and 'level' not in first:
            first['level'] = (i, sa['level'], sb['level'])
        for k in sorted(set(sa['figs']) | set(sb['figs'])):
            fa, fb = sa['figs'].get(k), sb['figs'].get(k)
            if fa == fb:
                continue
            if fa and fb and all(abs(x - y) <= 1 for x, y in zip(fa[0], fb[0])) and fa[1:] == fb[1:]:
                continue
            key = 'fig ' + k
            if key not in first:
                first[key] = (i, fa, fb)
        if sa['procs'] != sb['procs'] and 'procs' not in first:
            sa_set, sb_set = set(sa['procs']), set(sb['procs'])
            first['procs'] = (i, sorted(sa_set - sb_set)[:12], sorted(sb_set - sa_set)[:12])
        for k in sorted(set(sa['globals']) | set(sb['globals'])):
            if sa['globals'].get(k) != sb['globals'].get(k) and 'g ' + k not in first:
                first['g ' + k] = (i, sa['globals'].get(k), sb['globals'].get(k))
    print(f'{len(a)} control ticks, {len(b)} loaded ticks')
    for k, v in sorted(first.items(), key=lambda kv: kv[1][0])[:60]:
        print(v[0], k, 'control:', str(v[1:-1] if len(v) > 2 else '')[:200], '| loaded:', str(v[-1])[:200])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('leg')
    ap.add_argument('--ticks', type=int, default=20000)
    ap.add_argument('--out', default=os.path.join(ROOT, 're', 'out', 'save_trace'))
    ap.add_argument('--compare-only', action='store_true')
    a = ap.parse_args()
    out = os.path.join(a.out, a.leg)
    os.makedirs(out, exist_ok=True)
    if not a.compare_only:
        run = pf.pp.play(run_class=pf.Full)
        for name, leg in pf.LEGS[:-1]:
            leg(run)
            if name == a.leg:
                break
        run._leg = a.leg
        if not src.settle(run, a.leg, '/dev/null'):
            sys.exit('a monitor stays open')
        pids = []
        for mode in ('control', 'loaded'):
            pid = os.fork()
            if pid == 0:
                try:
                    child(run, mode, os.path.join(out, mode + '.jsonl'), a.ticks)
                finally:
                    os._exit(0)
            pids.append(pid)
        for pid in pids:
            os.waitpid(pid, 0)
    compare(os.path.join(out, 'control.jsonl'), os.path.join(out, 'loaded.jsonl'))


if __name__ == '__main__':
    main()
