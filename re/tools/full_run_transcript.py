"""The Python full run as a transcript the Swift port replays (FullRunTests.swift): every call the harnesses make into the engine, every
state they edit directly between those calls (found by comparing snapshots), and a checkpoint of the world every 200 ticks.
    re/.venv/bin/python -I -W ignore re/tools/full_run_transcript.py"""
import hashlib
import json
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats'), os.path.join(ROOT, 're', 'tools')]
import monitor as monitor_mod  # noqa: E402
import resume_digest  # noqa: E402
import savegame  # noqa: E402
import playthrough_full  # noqa: E402
import vm as vm_mod  # noqa: E402
import world as world_mod  # noqa: E402

OUT = os.path.join(ROOT, 'native', 'Tests', 'BioForgeCoreTests', 'Fixtures', 'full_run.json')
HARNESS = {'playthrough_full.py', 'playthrough_base.py', 'playthrough_prison.py', 'playthrough_surface.py', 'scenarios.py'}
EVERY = 200
TRACE = []


class Recorder:
    def __init__(self):
        self.ops, self.checkpoints = [], []
        self.world = self.vm = None
        self.base = None
        self.depth = 0

    def tick(self):
        return self.vm.tick if self.vm is not None else -1

    def snapshot(self):
        w, vm = self.world, self.vm
        figures = {}
        for name, f in w.figures.items():
            figures[name] = {'pos': None if f.pos is None else [float(c) for c in f.pos], 'heading': float(f.heading), 'gravity': f.gravity,
                             'no_collide': f.no_collide, 'combat': f.combat, 'hold': f.hold, 'enemy': f.enemy, 'vz': f.vz}
        items = {k: {'owner': i.owner, 'slot': i.slot} for k, i in w.items.items()}
        return {'global': dict(vm.globals), 'object': {k: list(v) for k, v in vm.objects.items()}, 'figure': figures, 'item': items}

    def flush(self):
        """Log what changed since the base as edits."""
        if self.vm is None or self.world is None:
            return
        now = self.snapshot()
        if self.base is not None:
            for section, values in now.items():
                old = self.base[section]
                for key, value in values.items():
                    if old.get(key) != value:
                        self.ops.append([self.tick(), 'edit', section, key, value])
        self.base = now

    def rebase(self):
        if self.vm is not None and self.world is not None:
            self.base = self.snapshot()

    def op(self, name, *args):
        self.ops.append([self.tick(), name, *args])

    def checkpoint(self):
        w, vm = self.world, self.vm
        lex = w.player()
        self.checkpoints.append({
            'tick': vm.tick, 'level': w.level, 'camera': w.current_camera(), 'motion': lex.motion if lex else None,
            'lex': None if lex is None or lex.pos is None else [round(float(c), 3) for c in lex.pos], 'heading': None if lex is None else round(float(lex.heading), 3),
            'hp': vm.objects[w.player_name][0] if lex is not None and w.player_name in vm.objects else None,
            'figures': {n: None if f.pos is None else [int(f.pos[0]), int(f.pos[1]), int(f.pos[2]), f.motion] for n, f in sorted(w.figures.items())},
            'globals': hashlib.sha256('\n'.join(f'{k}={v}' for k, v in sorted(vm.globals.items()) if not k.startswith('_time')).encode()).hexdigest()[:12],
            'handle': vm.next_handle, 'monitor': w.monitor.name if w.monitor is not None else None})


REC = Recorder()


def followed(w):
    f = w.figures.get(w.resolve(w.follow))
    return [','.join(str(int(c)) for c in f.pos), f'{f.heading:.3f}', f.motion, f.idx] if f is not None and f.pos is not None else []


def from_harness():
    return sys._getframe(2).f_code.co_filename.rsplit('/', 1)[-1] in HARNESS


def wrap(cls, name, encode):
    """Log a call that comes straight from a harness, in order with the edits around it."""
    original = getattr(cls, name)

    def call(self, *args, **kwargs):
        if not from_harness():
            return original(self, *args, **kwargs)
        REC.flush()
        REC.op(*encode(self, *args, **kwargs))
        result = original(self, *args, **kwargs)
        REC.rebase()
        return result
    setattr(cls, name, call)


def install():
    wrap(world_mod.World, 'key_down', lambda s, scan, mods=0: ('key_down', scan, mods))
    wrap(world_mod.World, 'key_up', lambda s, scan, mods=0: ('key_up', scan, mods))
    wrap(world_mod.World, 'set_pos', lambda s, fig, pos, raw=False: ('set_pos', fig.name, [float(c) for c in pos], bool(raw)))
    wrap(world_mod.World, 'cmd_ai', lambda s, fig, on, *a, **k: ('ai', fig.name, bool(on)))
    wrap(world_mod.World, 'fire_event', lambda s, name, *a, **k: ('fire_event', name))
    wrap(world_mod.Figure, 'set_motion', lambda s, name, loop, **k: ('set_motion', s.name, str(name), bool(loop)))
    wrap(world_mod.World, 'key_event', lambda s, scan, mods=0: ('key_event', scan, mods))
    wrap(monitor_mod.Monitor, 'pointer_move', lambda s, x, y: ('pointer_move', x, y))
    wrap(monitor_mod.Monitor, 'settle_pointer', lambda s: ('settle_pointer',))
    wrap(monitor_mod.Monitor, 'mouse_down', lambda s: ('mouse_down',))
    wrap(monitor_mod.Monitor, 'mouse_up', lambda s: ('mouse_up',))
    wrap(monitor_mod.Monitor, 'press', lambda s, name: ('press', name))
    wrap(monitor_mod.Monitor, 'release', lambda s, name: ('release', name))
    wrap(vm_mod.VM, 'fire', lambda s, name, *a, **k: ('fire', name, a[0] if a else k.get('owner', 'level')))
    wrap(vm_mod.VM, 'spawn', lambda s, name, args=(), ctx=None, **k: ('spawn', name, list(args), getattr(ctx, 'cur_fig', None), getattr(ctx, 'cur_item', None)))

    seed = random.Random.__init__

    def init(self, x=None):
        if sys._getframe(1).f_code.co_filename.rsplit('/', 1)[-1] in HARNESS:
            REC.op('seed', x)
        seed(self, x)
    random.Random.__init__ = init

    init_world = world_mod.World.__init__

    def world_init(self, *a, **k):
        init_world(self, *a, **k)
        REC.world = self
    world_mod.World.__init__ = world_init

    tick_once = vm_mod.VM.tick_once

    def tick(self, *a, **k):
        REC.vm = self
        REC.flush()
        return tick_once(self, *a, **k)
    vm_mod.VM.tick_once = tick

    step = world_mod.World.step

    def world_step(self, *a, **k):
        result = step(self, *a, **k)
        if REC.vm is not None:
            REC.rebase()
            if REC.vm.tick % EVERY == 0:
                REC.checkpoint()
            if TRACE and TRACE[0] <= REC.vm.tick <= TRACE[1]:
                lex, t = self.player(), f'{REC.vm.tick} {self.level} {self.current_camera() or "-"}'
                p = lex.pos if lex is not None else None
                print('TR', t, lex.motion if lex else '-', ','.join(str(int(c)) for c in p) if p is not None else '-',
                      f'{lex.heading if lex else 0:.3f}', self.monitor.name if self.monitor else '-', self.follow, *followed(self), 'h', REC.vm.next_handle, [p.block.name for p in REC.vm.procs.values() if not p.done][-3:], flush=True)
                if REC.vm.tick == TRACE[1]:
                    for k, v in sorted(REC.vm.globals.items()):
                        print('TG', f'{k}={v}', flush=True)
        return result
    world_mod.World.step = world_step


def save_check(name):
    """At a leg's end: save the live world, unpack and load it, and record the loaded state's digest (resume_digest.state_lines) for the Swift
    replay to match. The run goes on untouched: the loaded world is dropped, and the world the harness hooks follow and saves_dir are put back."""
    REC.flush()
    world, saves_dir = REC.world, REC.world.saves_dir
    with tempfile.TemporaryDirectory() as d:
        world.saves_dir = d
        unpacked = os.path.join(d, 'GAME1.d')
        os.makedirs(unpacked)
        savegame.Im1.unpack(open(world.save_native(1), 'rb').read(), unpacked)
        loaded, vm = world_mod.World.from_native_state(unpacked)
        lines = resume_digest.state_lines(loaded, vm)
    world.saves_dir, REC.world = saves_dir, world
    if os.environ.get('SAVE_CHECK_LINES') == name:
        print('\n'.join(lines))
    REC.op('save_check', name, len(lines), resume_digest.sha('\n'.join(lines)))
    REC.rebase()


def check_legs():
    """Every leg but the last ends with a save_check op."""
    def wrapped(name, leg):
        def run_leg(run):
            leg(run)
            save_check(name)
        return run_leg
    playthrough_full.LEGS[:-1] = [(n, wrapped(n, leg)) for n, leg in playthrough_full.LEGS[:-1]]


def main():
    if '--trace' in sys.argv:              # print these ticks and write nothing: diff with FULL_RUN_TRACE=a-b swift test --filter FullRunTests
        i = sys.argv.index('--trace')
        TRACE[:] = [int(sys.argv[i + 1]), int(sys.argv[i + 2])]
    install()
    check_legs()
    run = playthrough_full.play()
    assert run.passed and run.world.exit_requested, [p['message'] for p in run.problems if p['severity'] != 'minor']
    if TRACE:
        return
    REC.checkpoint()
    with open(OUT, 'w') as f:
        json.dump({'ops': REC.ops, 'checkpoints': REC.checkpoints}, f, separators=(',', ':'), default=lambda v: v.item())
    kinds = {}
    for op in REC.ops:
        kinds[op[1]] = kinds.get(op[1], 0) + 1
    print(f'{OUT}: {len(REC.ops)} ops {kinds}, {len(REC.checkpoints)} checkpoints, {os.path.getsize(OUT)} bytes, tick {run.vm.tick}')


if __name__ == '__main__':
    main()
