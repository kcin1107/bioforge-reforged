"""Plays the full run on several RANDOM streams and says how far each got: the milestone 4 measure, since no fight is seeded any more.

    re/.venv/bin/python -I -W ignore re/tools/run_seeds.py [--seeds 24] [--workers 8] [--difficulty easy|medium|hard]

Stream "default" is the one `playthrough_full.py` plays with no --seed, and so the one the Swift fixture holds. Output goes under re/out/run_seeds/
(Medium and Hard under re/out/run_seeds/medium/ and hard/: the level is set after the prison, playthrough_full's `difficulty` shortcut)."""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 're', 'out', 'run_seeds')


def summary(result):
    """playthrough_full's report -> (passed, the first segment that did not pass, its first blocker)."""
    bad = [segment['name'] for segment in result['segments'] if segment['status'] != 'passed']
    blockers = [problem['message'].splitlines()[0] for problem in result['problems'] if problem['severity'] != 'minor']
    return not bad, bad[0] if bad else None, blockers[0] if blockers else None


def one(seed, difficulty='easy'):
    folder = os.path.join(OUT, str(seed)) if difficulty == 'easy' else os.path.join(OUT, difficulty, str(seed))
    command = [sys.executable, '-I', '-W', 'ignore', os.path.join(ROOT, 're', 'interp', 'playthrough_full.py'), '--out', folder]
    if seed != 'default':
        command += ['--seed', str(seed)]
    if difficulty != 'easy':
        command += ['--difficulty', difficulty]
    subprocess.run(command, capture_output=True)
    path = os.path.join(folder, 'playthrough_full.json')
    if not os.path.exists(path):
        return seed, None
    with open(path, encoding='utf-8') as handle:
        return seed, json.load(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=23)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--difficulty', choices=('easy', 'medium', 'hard'), default='easy')
    args = parser.parse_args(argv)
    seeds = ['default'] + list(range(1, args.seeds + 1))
    passed = 0
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        for seed, result in pool.map(lambda seed: one(seed, args.difficulty), seeds):
            if result is None:
                print(f'{seed}: crashed')
                continue
            ok, segment, blocker = summary(result)
            passed += ok
            print(f"{seed}: {'passed' if ok else f'{segment}: {blocker}'} (tick {result['final_tick']}, Lex {result['lex_health']})", flush=True)
    print(f'{passed} of {len(seeds)} streams finish the game')


if __name__ == '__main__':
    main()
