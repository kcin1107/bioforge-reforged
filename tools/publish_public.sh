#!/usr/bin/env bash
# Export a filtered snapshot of this private repo's HEAD into a clone of the public source repo,
# as one commit "Sync from <short sha>". Run it from main.
#
#   tools/publish_public.sh <public-repo-clone-dir | remote> [--push]
#
# A directory with a .git is used as the clone. Anything else (a URL, a bare repo path) is
# cloned into a temp dir first. The script leak-checks the snapshot, builds it and runs the
# Python tests in a temp copy, then replaces the clone's working tree (its .git is kept) and
# commits. It pushes only with --push.
set -euo pipefail

usage() { echo "usage: $0 <public-repo-clone-dir | remote> [--push]" >&2; exit 2; }
[[ $# -ge 1 && $# -le 2 ]] || usage
TARGET=$1
PUSH=0
if [[ $# -eq 2 ]]; then [[ $2 == --push ]] && PUSH=1 || usage; fi

ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
# The main checkout holds the git-ignored game data, venv and generated output the tests need.
MAIN=$(cd "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
SHA=$(git -C "$ROOT" rev-parse --short HEAD)
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)
[[ $BRANCH == main ]] || echo "warning: exporting $BRANCH, not main" >&2
[[ -z $(git -C "$ROOT" status --porcelain) ]] || echo "warning: uncommitted changes are not exported" >&2

WORK=$(mktemp -d "${TMPDIR:-/tmp}/publish_public.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
SNAP=$WORK/snapshot

# 1. Snapshot: tracked files only, minus the private parts.
#    re/decomp is decompiled game code and must never be public; re/out holds surveys with
#    game-script excerpts; AGENTS.md / CLAUDE.md / .claude are agent instructions.
mkdir "$SNAP"
git -C "$ROOT" archive HEAD | tar -x -C "$SNAP"
rm -rf "$SNAP/re/decomp" "$SNAP/re/out" "$SNAP/AGENTS.md" "$SNAP/CLAUDE.md" "$SNAP/.claude"
# One exception: re/out/script_tokens.txt, the engine's keyword/opcode table that re/interp and
# re/formats load on import. No script excerpts; the same table is public in ScriptTokens.swift.
mkdir "$SNAP/re/out"
git -C "$ROOT" show HEAD:re/out/script_tokens.txt >"$SNAP/re/out/script_tokens.txt"

# 2. Leak check: abort on any hit.
hits=0
report() { echo "LEAK ($1):"; sed 's/^/  /'; hits=1; }
scan() {  # scan <label> <regex> [dir to skip]: matching lines of text files, names of binary files
    local out skip="^${3:-/}"
    out=$(cd "$SNAP" && LC_ALL=C grep -rnIE -e "$2" . | grep -v "$skip" || true)
    [[ -z $out ]] || report "$1" <<<"$out"
    out=$(cd "$SNAP" && LC_ALL=C grep -rlE -e "$2" . | grep -v "$skip" | while read -r f; do
        LC_ALL=C grep -qI . "$f" || echo "$f (binary)"; done || true)
    [[ -z $out ]] || report "$1" <<<"$out"
}
scan "home path" '/[U]sers/'  # bracket so this line does not match itself
# Third-party license texts keep their authors' addresses verbatim.
scan "e-mail address" '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' ./native/package/licenses/
out=$(cd "$SNAP" && find . -type f | grep -iE '\.(iff|cam|smk|flc|exe|wav|im1)$' || true)
[[ -z $out ]] || report "game file" <<<"$out"
out=$(cd "$SNAP" && find . -path './re/decomp*' || true)
[[ -z $out ]] || report "re/decomp path" <<<"$out"
out=$(cd "$SNAP" && find . -type f -size +5242880c || true)
[[ -z $out ]] || report "file over 5 MB" <<<"$out"
if [[ $hits -ne 0 ]]; then echo "leak check failed: nothing committed" >&2; exit 1; fi
echo "leak check: clean ($(cd "$SNAP" && find . -type f | wc -l | tr -d ' ') files)"

# 3. Test the export in a temp copy, with only the git-ignored pieces linked in.
TEST=$WORK/test
cp -R "$SNAP" "$TEST"
ln -s "$MAIN/game" "$TEST/game"
for p in re/.venv re/dgroup.bin re/strings.tsv; do ln -s "$MAIN/$p" "$TEST/$p"; done
mkdir -p "$TEST/re/out"
tracked_out=$(git -C "$ROOT" ls-files re/out)
for e in "$MAIN"/re/out/*; do
    rel=re/out/$(basename "$e")
    # Tracked re/out files are excluded on purpose: linking them would hide a dependency on them.
    grep -qxF "$rel" <<<"$tracked_out" || [[ -e $TEST/$rel ]] || ln -s "$e" "$TEST/$rel"
done
(cd "$TEST/native" && swift build)
(cd "$TEST" && re/.venv/bin/python -I re/tools/run_tests.py)

# 4. Replace the clone's working tree and commit.
if [[ -d $TARGET/.git ]]; then
    CLONE=$(cd "$TARGET" && pwd)
else
    CLONE=$(mktemp -d "${TMPDIR:-/tmp}/publish_public_clone.XXXXXX")
    git clone -q "$TARGET" "$CLONE"
fi
git -C "$CLONE" rev-parse -q --verify HEAD >/dev/null || git -C "$CLONE" symbolic-ref HEAD refs/heads/main
# Contributions merged on GitHub since the last sync would be overwritten by this snapshot. Stop and list them, unless
# PUBLISH_ACCEPT_FOREIGN=1 says they were carried into this repository first (CONTRIBUTING.md).
git -C "$CLONE" fetch -q origin 2>/dev/null || true
if git -C "$CLONE" rev-parse -q --verify origin/main >/dev/null; then
    git -C "$CLONE" merge -q --ff-only origin/main
    last_sync=$(git -C "$CLONE" log -1 --format=%H --grep='^Sync from ' HEAD || true)
    foreign=$(git -C "$CLONE" log --format='  %h %an: %s' ${last_sync:+$last_sync..}HEAD)
    if [[ -n $foreign && ${PUBLISH_ACCEPT_FOREIGN:-0} != 1 ]]; then
        printf 'the public repo has commits since the last sync, which this snapshot would overwrite:\n%s\n' "$foreign" >&2
        echo "carry them into this repository first, then rerun with PUBLISH_ACCEPT_FOREIGN=1" >&2
        exit 1
    fi
fi
rsync -a --delete --exclude=/.git "$SNAP"/ "$CLONE"/
git -C "$CLONE" add -A
if git -C "$CLONE" diff --cached --quiet; then
    echo "no changes since the last sync"
else
    git -C "$CLONE" commit -q -m "Sync from $SHA"
    echo "committed in $CLONE: $(git -C "$CLONE" log --oneline -1)"
fi
if [[ $PUSH -eq 1 ]]; then
    git -C "$CLONE" push origin HEAD
else
    echo "not pushed (use --push); clone: $CLONE"
fi
