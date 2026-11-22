# Contributing

Bug reports, fixes and checks against the original game are welcome. This page explains how the repository works, because it is set
up differently from most projects.

## Where to post what

- **Bugs and differences from the DOS game:** open an issue with the bug report template. On the Mac, attach the zip from
  Help > Report a Bug…. It holds a save and a replay of your last minutes, which lets the bug be replayed exactly.
- **Questions, ideas, help with setup:** use Discussions.
- **Code:** open a pull request (below).

Check [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md) first. Many differences from the original are known and written down there.

## How pull requests get in

This repository is a published copy of a private working repository, which also holds the reverse-engineering material that can't be
made public. Each sync replaces this repository's files with a fresh snapshot, so a pull request is never merged here directly:

1. You open a pull request here.
2. The maintainer reviews it here, in the open.
3. Once accepted, the maintainer applies the change in the working repository, with you as the commit's co-author.
4. The next sync publishes it, and the maintainer closes the pull request with a link to that sync.

Your name stays on the change in both places.

## What a change needs

The port is faithful to the original first. Every change in behaviour needs a reason from the original game: its code, or a check
against the DOS version running in DOSBox-X. Say which one in the pull request. An inferred behaviour is fine if it is marked as
inferred.

The two ports change together. `re/interp` (Python) is the reference, and `native/` (Swift) has to match it. A change to game logic
touches both, and the tests compare them.

You need your own copy of BioForge to run the tests. The GOG release 2.1.0.14 is the known one. Never commit game files, extracted
data or anything decompiled from the game.

## Running the checks

```bash
re/.venv/bin/python -I re/tools/run_tests.py
cd native && BIOFORGE_DATA=/path/to/Bioforge swift test
```

Changes to game logic also run the playthrough checks: `re/tools/run_seeds.py --seeds 26` (24 of 27 streams or more finish the game)
and `re/tools/save_resume_check.py`, with and without `--control`. README.md has the setup.

## Licence

By contributing you agree that your contribution is licensed under the MIT licence in [LICENSE](LICENSE).
