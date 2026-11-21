"""Run the unittest suites of re/interp, re/formats and re/tools in parallel, one process per test class.

Same tests as `python -m unittest discover -s <dir> -p 'test_*.py'` for each directory, spread over the CPU cores. Classes run
longest first, using the times of the last run (re/out/test_times.json; a class not seen yet counts as slow). Prints one summary
line per directory and the output of every class that failed; exits 1 if any did.

    re/.venv/bin/python -I re/tools/run_tests.py [--workers N] [dir ...]
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIRS = ['re/interp', 're/formats', 're/tools']
TIMES = os.path.join(ROOT, 're', 'out', 'test_times.json')


def classes(directory):
    """(directory, module, class) for every test class discovery finds, in discovery order."""
    found, seen = [], set()

    def walk(suite):
        for t in suite:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            else:
                key = (type(t).__module__, type(t).__name__)
                if isinstance(t, unittest.loader._FailedTest):
                    key = (t.id().split('.')[-1], None)      # an import error: run the module so its error is shown
                if key not in seen:
                    seen.add(key)
                    found.append((directory,) + key)
    start = os.path.join(ROOT, directory)
    sys.path.insert(0, start)
    try:
        walk(unittest.TestLoader().discover(start, pattern='test_*.py', top_level_dir=start))
    finally:
        sys.path.remove(start)
    return found


def run(job):
    directory, module, cls = job
    cmd = [sys.executable, '-I', '-W', 'ignore', '-m', 'unittest', 'discover', '-s', directory, '-p', module + '.py']
    if cls:
        cmd += ['-k', f'{module}.{cls}.']
    t = time.monotonic()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = p.stdout + p.stderr
    m = re.search(r'^Ran (\d+) tests?', out, re.M)
    return job, p.returncode, int(m.group(1)) if m else 0, time.monotonic() - t, out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workers', type=int, default=os.cpu_count())
    parser.add_argument('dirs', nargs='*', default=DIRS)
    args = parser.parse_args(argv)
    try:
        with open(TIMES) as f:
            times = json.load(f)
    except (OSError, ValueError):
        times = {}
    jobs = [j for d in args.dirs for j in classes(d)]
    jobs.sort(key=lambda j: -times.get('.'.join(filter(None, j)), 1e9))
    start = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(run, jobs))
    failed = False
    for d in args.dirs:
        mine = [r for r in results if r[0][0] == d]
        bad = [r for r in mine if r[1] != 0]
        print(f'{d}: {sum(r[2] for r in mine)} tests in {len(mine)} classes, {"FAILED" if bad else "OK"}')
        for job, _, _, _, out in bad:
            failed = True
            print(f'---- {".".join(filter(None, job[1:]))}\n{out.rstrip()}')
    print(f'{time.monotonic() - start:.0f} s with {args.workers} workers')
    times.update({'.'.join(filter(None, r[0])): round(r[3], 2) for r in results})
    os.makedirs(os.path.dirname(TIMES), exist_ok=True)
    with open(TIMES, 'w') as f:
        json.dump(times, f, indent=0, sort_keys=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
