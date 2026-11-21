"""Run a script block against the recording engine.

    re/.venv/bin/python -I re/interp/run.py LEVEL BLOCK [--ticks N] [--set VAR=VAL ...] [--limit N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vm as vmmod  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('level')
    ap.add_argument('block')
    ap.add_argument('--ticks', type=int, default=300)
    ap.add_argument('--set', nargs='*', default=[], metavar='VAR=VAL')
    ap.add_argument('--limit', type=int, default=0, help='print only the first N log lines / variable changes')
    a = ap.parse_args(argv[1:])
    eng = vmmod.RecordingEngine()
    vm = vmmod.VM(eng)
    files = vmmod.load_level(vm, a.level)
    print(f'level {a.level.upper()}: {len(files)} scripts, {len(vm.blocks)} blocks')
    for kv in a.set:
        k, v = kv.split('=', 1)
        k = k.lower() if k.startswith('_') else '_' + k.lower()
        v = v.strip()
        vm.globals[k] = vm.defs.consts.get(v.lower(), None) if v.startswith('_') else int(v)
        if vm.globals[k] is None:
            sys.exit(f'unknown constant {v}')
    if a.block.upper() not in vm.blocks:
        sys.exit(f'block {a.block} not found in level {a.level}')
    h = vm.fire(a.block)
    vm.run_ticks(a.ticks)
    print(f'started {a.block.upper()} (handle {h}); ran {a.ticks} ticks; '
          f'{len(vm.procs)} process(es) still alive: {sorted({p.block.name for p in vm.procs.values()})}')
    print('--- engine calls (tick, process, kind, name, args)')
    for n, (t, pb, kind, name, args) in enumerate(eng.log):
        if a.limit and n >= a.limit:
            print(f'... {len(eng.log) - a.limit} more')
            break
        print(f'{t:5d}  {pb:<20} {kind:<4} {name} {args}')
    print(f'--- global variable changes ({len(vm.changes)})')
    for t, name, old, new in vm.changes[:a.limit or None]:
        print(f'{t:5d}  {name}: {old} -> {new}')
    if a.limit and len(vm.changes) > a.limit:
        print(f'... {len(vm.changes) - a.limit} more')
    if vm.warnings:
        print(f'--- warnings ({len(vm.warnings)})')
        for w in vm.warnings[:20]:
            print(' ', w)


if __name__ == '__main__':
    main(sys.argv)
