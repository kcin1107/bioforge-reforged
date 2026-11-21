"""Compare original nurse wall-contact records with the port's collision response.

This checks the response to the observed pose/displacement, not a free-running timeline.
    re/.venv/bin/python -I re/tools/nurse_bounce.py TRACE --out REPORT
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'interp'))
import world as worldmod


def compare(states):
    world = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
    figure = world.figure('FIRSTBOT')
    figure.no_collide, figure.bouncy = False, True
    checked = []
    for state in states:
        bot = next((f for f in state['figures'] if f['name'] == 'FIRSTBOT'), None)
        if not bot or not bot['flags'] & 0x10 or not any(bot['move_delta'][:2]):
            continue
        if bot['velocity'] != [0, 0, 0] or bot['bounce_loss'] != 0:
            raise ValueError('capture needs the nurse root-motion case with zero persistent velocity/loss')
        start = np.array(bot['frame_start'], float)
        blocked = start + bot['move_delta']
        if blocked[2] != bot['pos'][2]:
            continue                         # full 3D rebound remains outside this XY response check
        # World keeps the root Z in the pose; the original record includes it in position.
        figure.frames, figure.idx = [(np.array([0, 0, bot['R']]), 0, [])], 0
        figure.heading = bot['base_heading']
        start[2] = blocked[2] = bot['pos'][2] - bot['R']
        figure.pos = np.array(bot['pos'], float)
        figure.pos[2] -= bot['R']
        lo, hi, _ = world.query_hull(figure, figure.pos)
        if list(lo) + list(hi) != bot['hull']:
            raise ValueError(f"port hull does not match capture at clock {state['clock']}")
        if not world.figure_blocked(figure, blocked):
            raise ValueError(f"reconstructed collision is clear at clock {state['clock']}")
        figure.pos, figure.prev_pos, figure.falling = blocked.copy(), start.copy(), False
        figure.vx = figure.vy = figure.vz = 0
        figure.elasticity = bot['bounce_loss']
        world.bounce_collision(figure, start)       # FUN_10a0_0ead's bouncy branch: step = blocked - start, then the rebound
        actual = figure.pos
        checked.append({'clock': state['clock'], 'original': bot['pos'][:2],
                        'port': actual[:2].tolist(), 'heading_unchanged': figure.heading == bot['base_heading'],
                        'error': float(np.max(np.abs(actual[:2] - bot['pos'][:2])))})
    return {'passed': bool(checked) and all(r['error'] == 0 and r['heading_unchanged'] for r in checked),
            'contacts': len(checked), 'checks': checked,
            'scope': 'XY collision response at observed poses; not free-running motion or general velocity physics'}


def load_states(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    for row in rows:
        if 'figures' in row:
            yield row
        elif row.get('kind') == 'snapshot':
            yield row['state']
        elif 'samples' in row:
            yield from row['samples']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    report = compare(load_states(args.trace))
    Path(args.out).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
