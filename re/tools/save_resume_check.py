"""Save, reload and continue at every leg boundary of the full run (ROADMAP milestone 5).

    re/.venv/bin/python -I -W ignore re/tools/save_resume_check.py [--seed N] [--workers 8] [--legs guard1,tower] [--control] [--export DIR]

One pass of playthrough_full plays the route; after each leg it forks a child that saves the game (World.save_native), loads the save
into a fresh World / VM (World.from_native_state), puts it in the run's place and plays the remaining legs. A row per boundary: the
leg saved after, the tick, and how the continued run ended (the final level, its tick and its first major problems). Times out a
child after `--timeout` seconds. `--export DIR` also copies each save to DIR/<leg number> <leg>.IM1, for opening in the app (Debug > Open Save File…). Output lines are JSON.

--control does no save: at the same point it only does to the figures' animations what a load does (restart_animations), and rounds
positions to whole units and headings to the 8.8 matrix as the records do, then plays on (re/out/save_resume_control.jsonl). A boundary
that fails there too fails because the load restarts the animations, which the original's load also does (re/NOTES.md "The original
does not save the motion phase either"), or on the records' precision, which is the original's own (re/NOTES.md "Two save points failed
on the heading's last bits"); one that only fails with the save lost state."""
import argparse
import json
import math
import os
import shutil
import signal
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats')]
import playthrough_full as pf  # noqa: E402
import savegame  # noqa: E402
from world import World  # noqa: E402


def restart_animations(world):
    """What a load does to the running animations, without a save: each placed figure's motion starts again at frame 0 with no carried
    root (a fresh model, FUN_1088_2a87); a one-off that is not a running MOTION ... CONTINUE becomes the idle stance, as figure_states
    saves it, unless a process waits on it (the load re-runs that MOTION statement; here the wait is kept). Positions are rounded to
    whole units and headings to the record's 8.8 matrix (level.ObjRec.heading), as in the records. Nothing else changes: processes,
    timers and the RANDOM stream go on as they were."""
    for f in world.figures.values():
        if f.pos is None:
            continue
        f.pos[:] = [round(v) for v in f.pos]
        c, s = round(256 * math.cos(math.radians(f.heading))), round(256 * math.sin(math.radians(f.heading)))
        f.heading = math.degrees(math.atan2(s, c))
        if not f.motion:
            continue
        waited = f.task_name == f.motion and not f.unwaited and not f.finished
        task = f.task_name == f.motion and f.unwaited and not f.finished
        if not f.loop and not task and not waited:
            idle = 'ATK_STAND' if f.combat else 'STAND'
            if idle in f.assets.motions:
                f.motion, f.frames, f.loop, f.task_name, f.unwaited = idle, f.assets.motions[idle], True, None, False
                f.mot_id += 1                       # a new motion: nobody waits on the old one
                f.rises = bool(f.assets.motion_info[idle][1] & 2)
                f.no_idle = f.stopped = f.idle_request = f.engine_request = False
        f.idx, f.phase, f.finished, f.frozen, f.hit_done = 0, 0.0, False, False, False
        f.root_start, f.applied_root_z, f.duration, f.dur_id = True, 0, None, -1


def control_and_finish(run, name, out_path):
    """In a child: restart_animations at the save point and play on, with the row resume_and_finish writes."""
    if not settle(run, name, out_path):
        return
    tick = run.vm.tick
    restart_animations(run.world)
    finish(run, name, out_path, {'after': name, 'tick': tick, 'level': run.world.level, 'control': True})


def settle(run, name, out_path):
    """Play on until the save point (see resume_and_finish); False when a monitor stays open (a row is written)."""
    for _ in range(900):
        lex = run.world.player()
        if run.world.monitor is None and (lex is None or lex.loop or lex.finished):
            break
        run.tick(1)
    if run.world.monitor is not None:
        with open(out_path, 'a') as f:
            f.write(json.dumps({'after': name, 'skipped': 'a monitor stays open'}) + '\n')
        return False
    return True


def finish(run, name, out_path, row):
    """Play the legs after `name` and write `row` with how the run ended."""
    names = [n for n, _ in pf.LEGS]
    try:
        for leg_name, leg in pf.LEGS[names.index(name) + 1:]:
            if not run.passed:
                break
            leg(run)
    except Exception as error:                      # noqa: BLE001 (a leg's Stuck or a crash: either is a finding)
        row['error'] = repr(error)[:300]
        row['trace'] = traceback.format_exc().splitlines()[-6:]
    report = pf.report(run)
    row.update(final_level=run.world.level, final_tick=run.vm.tick, exit=bool(report.get('exit_requested')),
               problems=[p['message'].splitlines()[0][:200] for p in report['problems'] if p['severity'] != 'minor'][:3],
               detail=next((p['message'][-1500:] for p in report['problems'] if p['severity'] != 'minor'), None))
    with open(out_path, 'a') as f:
        f.write(json.dumps(row) + '\n')


def resume_and_finish(run, name, out_path, export=None, index=0):
    """In a child: save, load into a fresh world, continue the legs after `name`; write one JSON line to `out_path`. An open monitor is
    not save data: it saves once the leg's last monitor has closed and the player's one-off motion has ended; a monitor the next leg goes
    on using is no save point (INFERRED: the options screen, where the game is saved, does not open over a script monitor)."""
    if not settle(run, name, out_path):
        return
    tick = run.vm.tick
    d = tempfile.mkdtemp()                          # kept: the loaded world reads its levels back from the unpacked save
    run.world.saves_dir = d
    path = run.world.save_native(1)
    if export:
        os.makedirs(export, exist_ok=True)
        shutil.copyfile(path, os.path.join(export, f'{index:02d} {name}.IM1'))
    unpacked = os.path.join(d, 'GAME1.d')
    os.makedirs(unpacked)
    savegame.Im1.unpack(open(path, 'rb').read(), unpacked)
    w, vm = World.from_native_state(unpacked)
    w.vm = vm
    w.rng.setstate(run.world.rng.getstate())        # the port's RANDOM stream is not save data (the save has no RNG state; INFERRED), so a
                                                    # fresh stream would test another route, not the save: the check keeps the run's
    w.level_loads = list(run.world.level_loads)     # the harness's history of level loads (legs check how a level was entered), not game state
    run.world, run.vm, run.lex = w, vm, w.player()
    finish(run, name, out_path, {'after': name, 'tick': tick, 'level': w.level})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--timeout', type=int, default=1200)
    ap.add_argument('--legs', default='', help='comma-separated leg names to check (default: every leg but the last)')
    ap.add_argument('--control', action='store_true', help='no save: restart the animations only (restart_animations)')
    ap.add_argument('--export', default=None, metavar='DIR', help='also copy each written save to DIR/<NN> <leg>.IM1 (NN = the leg number)')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    a.out = a.out or os.path.join(ROOT, 're', 'out', 'save_resume_control.jsonl' if a.control else 'save_resume_check.jsonl')
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'w').close()
    wanted = set(a.legs.split(',')) if a.legs else None
    children = {}

    def kill_late():
        """Reap the children that have finished, then kill, reap and report each one still running past the timeout, once. (A child
        left in `children` after its kill, or one that had finished but was not reaped yet, used to be reported again on every pass.)"""
        while children:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            children.pop(pid, None)
        now = time.time()
        for pid, (start, name) in list(children.items()):
            if now - start > a.timeout:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                children.pop(pid)
                with open(a.out, 'a') as f:
                    f.write(json.dumps({'after': name, 'error': f'timeout after {a.timeout} s'}) + '\n')

    run = pf.pp.play(run_class=pf.Full, seed=a.seed)
    for index, (name, leg) in enumerate(pf.LEGS[:-1]):
        if not run.passed:
            break
        leg(run)
        if wanted is not None and name not in wanted:
            continue
        while len(children) >= a.workers:
            kill_late()
            if len(children) >= a.workers:
                time.sleep(1)
        sys.stdout.flush()
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                if a.control:
                    control_and_finish(run, name, a.out)
                else:
                    resume_and_finish(run, name, a.out, a.export, index)
                code = 0
            except BaseException as error:          # a child must never return into the parent's run
                with open(a.out, 'a') as f:
                    f.write(json.dumps({'after': name, 'error': repr(error)[:300],
                                        'trace': traceback.format_exc().splitlines()[-6:]}) + '\n')
            finally:
                os._exit(code)
        children[pid] = (time.time(), name)
    while children:
        kill_late()
        if children:
            time.sleep(1)
    rows = [json.loads(l) for l in open(a.out)]
    order = {n: i for i, (n, _) in enumerate(pf.LEGS)}
    for r in sorted(rows, key=lambda r: order.get(r['after'], 99)):
        print(json.dumps(r))
    ok = sum(1 for r in rows if r.get('exit') and not r.get('error') and not r.get('problems'))
    skipped = sum(1 for r in rows if r.get('skipped'))
    what = 'animation restarts (no save)' if a.control else 'saves'
    print(f'{ok} of {len(rows) - skipped} {what} continue to EXIT ({skipped} boundaries skipped: a monitor stays open)')


if __name__ == '__main__':
    main()
