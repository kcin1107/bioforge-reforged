"""The `gamedatResume` and `nativeResume` digests of native/Tests/BioForgeCoreTests/SaveLoadTests.swift: canonical lines of a resumed state, then after 300 frames.
Prints the Swift lines. Regenerate them only with a change that is meant to move the resumed state, and check first that this reproduces the old digests on the old code.
    re/.venv/bin/python -I -W ignore re/tools/resume_digest.py [GAME1.IM1]"""
import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats')]
import savegame  # noqa: E402
import world as worldmod  # noqa: E402


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def f3(x):
    s = f'{x:.3f}'
    return '0.000' if s == '-0.000' else s


def opt(value):
    return 'None' if value is None else value


def state_lines(world, vm):
    lines = [f"world {world.level} {opt(world.current_camera())} {int(world.script_auto)} {opt(world.player_name)} {vm.tick} {vm.next_handle}"]
    for key, fig in world.figures.items():
        pos = 'None' if fig.pos is None else ','.join(f3(float(v)) for v in fig.pos)
        lines.append(f"fig {key} {fig.type} {pos} {f3(float(fig.heading))} {opt(fig.motion)} {int(bool(fig.combat))} {vm.objects[world.object_key(key)][0]} {opt(fig.enemy)} {opt(fig.ai_type)} "
                     f"{fig.ai_proc.handle if fig.ai_proc else '-'} {'-' if fig.view_cams is None else ','.join(fig.view_cams)}")
    for key, item in world.items.items():
        lines.append(f"item {key} {item.name} {item.type} {opt(item.owner)} {opt(item.slot)} {vm.objects.get(key)!r}")
    for p in vm.procs.values():
        lines.append(f"proc {p.handle} {p.block.name} {p.block.kind} {p.pc} {p.wake} {p.wait_on.handle if p.wait_on else '-'} {opt(p.cur_fig)} {opt(p.cur_item)} {int(p.suspended)} "
                     f"{list(p.locals)!r} {opt(p.origin)} {len(p.pending)} {[w.handle for w in p.waiters]!r} {p.owner}")
    lines.append('globals ' + sha('\n'.join(f'{k}={vm.globals[k]!r}' for k in sorted(vm.globals))))
    return lines


def run_lines(world, vm):
    return [f"log {len(world.log)} " + sha('\n'.join(f"{e[0]}|{e[1]}|{e[2]}|{e[3]}|{list(e[4])!r}" for e in world.log)),
            f"camera_changes {[(t, a, b, r) for t, a, b, r in world.camera_changes]!r}",
            f"changes {len(vm.changes)} " + sha('\n'.join(repr(tuple(c)) for c in vm.changes)),
            f"warnings {list(world.warnings) + list(vm.warnings)!r}",
            f"events {[tuple(e) for e in world.events]!r}",
            f"level_loads {[tuple(x) for x in world.level_loads]!r}",
            f"sound_log {len(world.sound_log)} music_log {len(world.music_log)}"]


def digest(lines):
    return f'(count: {len(lines)}, sha: "{sha(chr(10).join(lines))}")'


def one(label, path):
    world, vm = worldmod.World.from_native_state(path)
    start = state_lines(world, vm)
    for _ in range(300):
        vm.tick_once()
        world.step()
    after = state_lines(world, vm) + run_lines(world, vm)
    print(f'let {label} = (start: {digest(start)}, after300: {digest(after)}, camera: "{start[0].split()[2]}")')


def main(argv):
    one('gamedatResume', worldmod.GAMEDAT)
    if argv:
        with tempfile.TemporaryDirectory() as tmp:
            savegame.Im1.unpack(open(argv[0], 'rb').read(), tmp)
            one('nativeResume', tmp)


if __name__ == '__main__':
    main(sys.argv[1:])
