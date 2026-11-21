"""The `newGameSave` digests of native/Tests/BioForgeCoreTests/SaveLoadTests.swift: a new game booted through the intro, run to the same state the
pre-intro port had after 1100 ticks (scenarios.old_ticks), saved to slot 2 and unpacked. Prints the Swift line.
    re/.venv/bin/python -I re/tools/newgame_save_digest.py"""
import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 're', 'interp'))
import scenarios  # noqa: E402
import savegame  # noqa: E402


def main():
    world, vm = scenarios.boot_opening()
    scenarios.tick(world, vm, scenarios.old_ticks(1100))
    with tempfile.TemporaryDirectory() as tmp:
        world.saves_dir = tmp
        path = world.save_native(2)
        data = open(path, 'rb').read()
        out = os.path.join(tmp, 'unpacked')
        os.makedirs(out)
        savegame.Im1.unpack(data, out)
        files = {n: hashlib.sha256(open(os.path.join(out, n), 'rb').read()).hexdigest() for n in sorted(os.listdir(out))}
    body = ', '.join(f'"{n}": "{h}"' for n, h in files.items())
    print(f'let newGameSave = (level: "{world.level}", camera: "{world.current_camera()}", im1: "{hashlib.sha256(data).hexdigest()}", files: [{body}])')


if __name__ == '__main__':
    main()
