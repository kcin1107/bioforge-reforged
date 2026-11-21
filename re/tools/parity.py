"""Compare a scripted DOSBox-X run with the Python interpreter.

    re/.venv/bin/python -I re/tools/parity.py run closed_door_walk
    re/.venv/bin/python -I re/tools/parity.py report closed_door_walk
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dosbox_live as live
import parity_core as core

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 're/out/parity'
sys.path.insert(0, str(ROOT / 're/interp'))
import scenarios  # noqa: E402


def clock(dbg):
    """The 60 Hz u32 at DGROUP 8330 (decomp/11d8.c increments the low word)."""
    return struct.unpack('<I', dbg.dump(live.DGROUP, 0x8330, 4))[0]


def trace_state(dbg, wanted, pointers, refresh=False):
    """Read each related figure field from the existing single-record dump."""
    if refresh:
        pointers.clear()
    if not wanted.issubset(pointers):
        g = dbg.dump(live.DGROUP, 0x1d19, 0x10)
        count = struct.unpack_from('<H', g)[0]
        off, sel = struct.unpack_from('<HH', g, 8)
        if 0 < count < 200 and sel:
            arr = dbg.dump(f'{sel:04X}', off, 4 * count)
            for po, ps in struct.iter_unpack('<HH', arr):
                name = live.cstr(dbg.dump(f'{ps:04X}', po + 0xf7, 25)).upper()
                if name in wanted:
                    pointers[name] = (po, ps)
    count = struct.unpack('<H', dbg.dump(live.DGROUP, 0x1ce9, 2))[0]
    if count != len(live.TRIGGERS):
        live.TRIGGERS[:] = live.object_names(dbg, 0x1ce9, 0x1cf1)
    coff, csel = struct.unpack('<HH', dbg.dump(live.DGROUP, 0x63ce, 4))
    camera = live.cstr(dbg.dump(f'{csel:04X}', coff + 2, 9)) if csel else ''
    return {
        'camera': camera,
        'figures': {name: {k: f[k] for k in (
            'pos', 'heading', 'motion', 'locals', 'in_trig', 'hull', 'flags')}
                    for name, ptr in pointers.items() if (f := live.figure(dbg, ptr, live.TRIGGERS, False))},
    }


def port_state(world, vm, wanted):
    figures = {}
    for name in wanted:
        fig = world.figures.get(name)
        if fig is None or fig.pos is None:
            continue
        lo, hi = world.hull(fig)
        flags = (int(fig.gravity) | (2 if fig.no_collide else 0)
                 | (4 if fig.hidden else 0))
        figures[name] = {
            'pos': [round(float(v)) for v in fig.pos],
            'heading': round(float(fig.heading), 1),
            'motion': fig.motion or '',
            'locals': list(vm.objects.get(world.object_key(name), [0] * 10)),
            'in_trig': [f'{i}:{world.triggers[i]["name"]}' for i, value in enumerate(fig.in_trig or []) if value],
            'hull': [int(v) for v in (*lo, *hi)],
            'flags': flags,
        }
    return {'camera': world.current_camera() or '', 'figures': figures}


def anchor_seen(state, anchor, seen_motion=False):
    fig = state['figures'].get(anchor['figure'])
    if fig is None:
        return False
    if anchor['type'] == 'motion':
        return seen_motion and fig['motion'].upper() == anchor['motion'].upper()
    return seen_motion and fig['motion'].upper() != 'OUT_OF_BED' and not (fig['flags'] & 2)


def apply_live_poke(dbg, poke):
    if poke['type'] == 'phys':
        if not live.set_phys_state(dbg, poke['name'], poke['state']):
            raise RuntimeError(f'PHYS {poke["name"]} not found')
        return
    if poke['type'] == 'position':
        raw = live.sample(dbg)
        match = next((f for f in raw['figures'] if f['name'].upper() == poke['name'].upper()), None)
        if match is None:
            raise RuntimeError(f'figure {poke["name"]} not found')
        off, sel = match['ptr']
        for i, value in enumerate(poke['pos']):
            for j, byte in enumerate(struct.pack('<i', value)):
                dbg.exec(f'SM {sel:04X}:{off + 0xb + 4 * i + j:04X} {byte:02X}')
        return
    raise ValueError(f'unknown poke {poke["type"]}')


def apply_port_poke(world, vm, poke):
    if poke['type'] == 'phys':
        vm.globals['_' + poke['name'].lower() + '_space'] = poke['state']
    elif poke['type'] == 'position':
        fig = world.figure(poke['name'])
        if fig is None:
            raise RuntimeError(f'figure {poke["name"]} not found')
        fig.pos[:] = poke['pos']
    else:
        raise ValueError(f'unknown poke {poke["type"]}')


def write_line(handle, value):
    handle.write(json.dumps(value, sort_keys=True) + '\n')
    handle.flush()


def live_run(scenario, folder, timeout=180):
    """Boot a scratch copy and schedule keys strictly by the game's own clock."""
    work = folder / 'workdir'
    if work.resolve().is_relative_to((ROOT / 'game').resolve()):
        raise ValueError('refusing game/ as a DOSBox workdir')
    c = work / 'c/Bioforge'
    if not c.exists():
        c.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(live.GAME + '/Bioforge', c)
        shutil.copytree(live.GAME + '/GAMEDAT', c / 'GAMEDAT')
    boot = scenario['boot']
    if isinstance(boot, dict):
        slot = int(boot.get('slot', 1))
        if not 1 <= slot <= 9 or 'save' not in boot:
            raise ValueError('save boot needs a save path and slot 1..9')
        shutil.copy2(boot['save'], c / f'GAME{slot}.IM1')
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    conf = work / 'live.conf'
    keys = boot.get('keys') if isinstance(boot, dict) else scenario.get('boot_keys', 'esc esc enter enter')
    if not keys:
        raise ValueError('save boot needs keys to open and choose its slot in DOSBox-X')
    conf.write_text(live.config_text(port, str(c.parent), keys))
    log = open(work / 'dosbox.log', 'w')
    proc = subprocess.Popen([os.environ.get('BIOFORGE_DOSBOX_BIN', 'dosbox-x'), '-conf', str(conf)], cwd=work, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        srv.settimeout(90)
        conn, _ = srv.accept()
        conn.settimeout(20)
        dbg = live.Debugger(conn, str(work))
        wanted = set(scenario['figures'])
        anchor = scenario['anchor']
        anchor_clock = None
        last_sample = -1
        seen_motion = False
        previous_keys = set()
        done_pokes = set()
        pointers = {}
        previous_clock = None
        start = time.monotonic()
        with open(folder / 'original.jsonl', 'w') as out:
            while time.monotonic() - start < timeout and proc.poll() is None:
                now = clock(dbg)
                # New-game reset briefly exposes a torn/cleared clock word while
                # the debugger reads memory. Do not let it end a scenario.
                if now > 10_000_000 or (previous_clock is not None and now > previous_clock + 1000):
                    time.sleep(0.1)
                    continue
                if previous_clock is not None and now < previous_clock:
                    last_sample = -1
                previous_clock = now
                # Before scene load, the clock may advance for menus; figures establish the scene.
                state = None
                if anchor_clock is None:
                    state = trace_state(dbg, wanted, pointers)
                    figure = state['figures'].get(anchor['figure'])
                    required_motion = anchor.get('after_motion', 'OUT_OF_BED')   # null: no earlier motion needed
                    if figure and (required_motion is None or figure['motion'].upper() == required_motion):
                        seen_motion = True
                    if anchor_seen(state, anchor, seen_motion):
                        anchor_clock = now
                        state = trace_state(dbg, wanted, pointers, refresh=True)
                        print(f'original anchor at clock {now}', flush=True)
                if anchor_clock is not None:
                    rel = now - anchor_clock
                    for i, poke in enumerate(scenario.get('pokes', [])):
                        if i not in done_pokes and rel >= poke.get('at', 0):
                            apply_live_poke(dbg, poke)
                            done_pokes.add(i)
                    active = set(core.scheduled_inputs(scenario, now, anchor_clock))
                    for scan in sorted(active - previous_keys):
                        live.key(dbg, scan)
                    for scan in sorted(previous_keys - active):
                        live.key(dbg, scan | 0x80)
                    previous_keys = active
                if anchor_clock is not None and now - last_sample >= scenario['sample_period']:
                    if state is None:
                        state = trace_state(dbg, wanted, pointers)
                    state['clock'] = now
                    write_line(out, state)
                    last_sample = now
                if anchor_clock is not None and now >= anchor_clock + scenario['duration_after_anchor']:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError('original did not finish; see workdir/dosbox.log')
            for scan in previous_keys:
                live.key(dbg, scan | 0x80)
            if anchor_clock is None:
                raise RuntimeError('original anchor never appeared')
    finally:
        # DOSBox-X has survived SIGTERM after a debugger hang; kill the whole process group.
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=10)
        log.close()
        srv.close()


def port_run(scenario, folder, max_ticks=5000):
    boot = scenario['boot']
    if boot == 'new_game':
        world, vm = scenarios.boot_opening()
    elif isinstance(boot, dict) and 'save' in boot:
        import savegame
        import world as worldmod
        state = folder / 'save_state'
        state.mkdir(exist_ok=True)
        savegame.Im1.unpack(Path(boot['save']).read_bytes(), str(state))
        world, vm = worldmod.World.from_native_state(str(state))
    else:
        raise ValueError('boot must be new_game or {save, slot, keys}')
    wanted = set(scenario['figures'])
    anchor = scenario['anchor']
    anchor_clock = None
    seen_motion = False
    previous_keys = set()
    done_pokes = set()
    last_sample = -1
    with open(folder / 'port.jsonl', 'w') as out:
        for _ in range(max_ticks):
            now = vm.tick * 2
            state = port_state(world, vm, wanted)
            fig = state['figures'].get(anchor['figure'])
            required_motion = anchor.get('after_motion', 'OUT_OF_BED')           # null: no earlier motion needed
            if fig and (required_motion is None or fig['motion'].upper() == required_motion):
                seen_motion = True
            if anchor_clock is None and anchor_seen(state, anchor, seen_motion):
                anchor_clock = now
                last_sample = -1
                print(f'port anchor at clock {now}', flush=True)
            rel = now - anchor_clock if anchor_clock is not None else None
            if rel is not None:
                for i, poke in enumerate(scenario.get('pokes', [])):
                    if i not in done_pokes and rel >= poke.get('at', 0):
                        apply_port_poke(world, vm, poke)
                        done_pokes.add(i)
                active = set(core.scheduled_inputs(scenario, now, anchor_clock))
                previous_keys = active
            world.set_player_input(forward=int(0x48 in previous_keys) - int(0x50 in previous_keys),
                                   turn=int(0x4d in previous_keys) - int(0x4b in previous_keys),
                                   run=0x2a in previous_keys or 0x36 in previous_keys)
            if anchor_clock is not None and now - last_sample >= scenario['sample_period'] and fig:
                state['clock'] = now
                write_line(out, state)
                last_sample = now
            if anchor_clock is not None and now >= anchor_clock + scenario['duration_after_anchor']:
                break
            vm.tick_once()
            world.step()
            world.choose_default_difficulty()
        else:
            raise TimeoutError('port anchor never appeared or run exceeded max_ticks')


def read_jsonl(path):
    with open(path) as handle:
        return [json.loads(line) for line in handle]


def reference_checks(scenario, original, port):
    """Attach the previously recorded live check beside each new endpoint."""
    checks = []
    for item in scenario.get('reference', []):
        axis = 'xyz'.index(item['axis'])
        row = dict(item)
        for label, trace in (('measured_original', original), ('measured_port', port)):
            figures = trace[-1]['figures'] if trace else {}
            pos = figures.get(item['figure'], {}).get('pos')
            row[label] = pos[axis] if pos is not None else None
        checks.append(row)
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'port', 'report'))
    parser.add_argument('scenario')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args(argv)
    scenario = core.load_scenario(HERE / 'parity_scenarios' / (args.scenario + '.json'))
    folder = OUT / scenario['name']
    folder.mkdir(parents=True, exist_ok=True)
    if args.command == 'run':
        live_run(scenario, folder, args.timeout)
    if args.command in ('run', 'port'):
        port_run(scenario, folder)
    original = read_jsonl(folder / 'original.jsonl')
    port = read_jsonl(folder / 'port.jsonl')
    summary = core.compare_traces(original, port, scenario)
    core.write_report(summary, folder, scenario)
    checks = reference_checks(scenario, original, port)
    report = folder / 'report.md'
    with open(report, 'a') as handle:
        handle.write('\n## Timeline\n\n')
        handle.write('| Relative clock | Original LEX (x, y, z) | Port LEX (x, y, z) | Original motion | Port motion |\n')
        handle.write('|---:|---|---|---|---|\n')
        for pair in summary['timeline']:
            old = pair['original']['figures'].get('LEX', {})
            new = pair['port']['figures'].get('LEX', {})
            handle.write(f'| {pair["clock"]} | {old.get("pos", "—")} | {new.get("pos", "—")} | '
                         f'{old.get("motion", "—")} | {new.get("motion", "—")} |\n')
        if checks:
            handle.write('\n## Recorded endpoint checks\n\n')
            handle.write('| Figure.axis | Original now | Port now | Original in NOTES | Port in NOTES |\n')
            handle.write('|---|---:|---:|---:|---:|\n')
            for row in checks:
                handle.write(f'| {row["figure"]}.pos.{row["axis"]} | {row["measured_original"]} | '
                             f'{row["measured_port"]} | {row.get("original", "—")} | '
                             f'{row.get("port", "—")} |\n')
    if checks:
        report_json = folder / 'report.json'
        content = json.loads(report_json.read_text())
        content['reference_checks'] = checks
        report_json.write_text(json.dumps(content, indent=2, sort_keys=True) + '\n')
    print(f'wrote {folder / "report.md"}')
    return int(summary['divergent'])


if __name__ == '__main__':
    sys.exit(main())
