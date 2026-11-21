#!/bin/bash
# Builds the Linux AppImage of BioForgeSDL on a Mac, in Apple's container tool (`container system start` first), and smoke-tests it in a
# clean container: Arch Linux for x86_64 (the Steam Deck's), Debian for arm64. Output: native/dist/BioForge-<commit>-<arch>.AppImage
# (native/dist is ignored by git). No game data goes into the package; the smoke run reads your own copy.
#   native/package-linux.sh [--arch amd64|arm64|both] [--data <folder that holds Bioforge>] [--no-smoke]
# --data defaults to the repository's game/app. The build runs package/linux/build.sh in swift:6.4-jammy.
set -euo pipefail

SDL_VERSION=3.4.20
SDL_SHA256=f3bb06f55bed9557227a700af2ea62e49497ebdf58037732a731a5fb3ef8581f
RUNTIME_TAG=20251108             # github.com/AppImage/type2-runtime: the static AppImage runtime (FUSE mount, or APPIMAGE_EXTRACT_AND_RUN=1)
RUNTIME_SHA256_x86_64=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
RUNTIME_SHA256_aarch64=00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444
SMOKE_LINE="smoke: level TITLE tick 900 camera NONE frame 50e055142d28b295"
BUILD_IMAGE=docker.io/library/swift:6.4-jammy

cd "$(dirname "$0")"
native=$PWD
arches=both; data="$native/../game/app"; smoke=1
while [ $# -gt 0 ]; do
    case $1 in
        --arch) arches=$2; shift 2 ;;
        --data) data=$2; shift 2 ;;
        --no-smoke) smoke=0; shift ;;
        *) echo "usage: $0 [--arch amd64|arm64|both] [--data <folder that holds Bioforge>] [--no-smoke]" >&2; exit 2 ;;
    esac
done
case $arches in both) arches="amd64 arm64" ;; amd64|arm64) ;; *) echo "--arch: amd64, arm64 or both" >&2; exit 2 ;; esac
if [ $smoke = 1 ] && [ ! -f "$data/Bioforge/BIOFORGE.EXE" ]; then echo "no game at $data/Bioforge (pass --data, or --no-smoke)" >&2; exit 2; fi

dist=$native/dist; cache=$dist/cache
mkdir -p "$cache"

# A pinned download, kept in the cache and checked every time.
fetch() {   # url sha256 file
    local url=$1 sum=$2 file=$cache/$3
    if [ ! -f "$file" ] || [ "$(shasum -a 256 "$file" | cut -d' ' -f1)" != "$sum" ]; then
        curl -fsSL -o "$file.part" "$url"
        mv "$file.part" "$file"
    fi
    if [ "$(shasum -a 256 "$file" | cut -d' ' -f1)" != "$sum" ]; then echo "checksum mismatch: $file" >&2; rm -f "$file"; exit 1; fi
}
fetch "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VERSION/SDL3-$SDL_VERSION.tar.gz" $SDL_SHA256 "SDL3-$SDL_VERSION.tar.gz"
sips -z 256 256 "$native/Resources/AppIcon.png" --out "$cache/bioforge-256.png" >/dev/null     # the original-artwork icon, never GOG's

commit=$(git rev-parse --short HEAD)
git diff --quiet HEAD -- . 2>/dev/null || commit="$commit-dirty"

for arch in $arches; do
    if [ "$arch" = amd64 ]; then machine=x86_64; flags=(--arch amd64 --rosetta); smoke_image=docker.io/library/archlinux:latest
    else machine=aarch64; flags=(--arch arm64); smoke_image=docker.io/library/debian:bookworm-slim; fi
    sum_var=RUNTIME_SHA256_$machine
    fetch "https://github.com/AppImage/type2-runtime/releases/download/$RUNTIME_TAG/runtime-$machine" "${!sum_var}" "runtime-$machine"
    out="BioForge-$commit-$machine.AppImage"

    echo "=== build $out"
    container run --rm --cpus 10 --memory 16g "${flags[@]}" -v "$native:/src:ro" -v "$dist:/dist" \
        -e SDL_VERSION=$SDL_VERSION -e RUNTIME="runtime-$machine" -e OUT="$out" -e COMMIT="$commit" \
        $BUILD_IMAGE bash /src/package/linux/build.sh

    [ $smoke = 1 ] || continue
    echo "=== smoke $out in $smoke_image"
    # Rosetta refuses an x86_64 ELF whose header padding is not zero ("Exec format error"), and an AppImage marks itself with "AI\2" at
    # bytes 8-10 there; so under Rosetta a copy with those three bytes cleared runs. x86_64 hardware ignores them; the runtime never reads them.
    run="/dist/$out"
    [ "$arch" = amd64 ] && run="cp /dist/$out /tmp/a.AppImage && printf '\\0\\0\\0' | dd of=/tmp/a.AppImage bs=1 seek=8 conv=notrunc status=none && /tmp/a.AppImage"
    got=$(container run --rm "${flags[@]}" -v "$dist:/dist:ro" -v "$data:/app:ro" \
        -e APPIMAGE_EXTRACT_AND_RUN=1 -e SDL_VIDEO_DRIVER=offscreen -e SDL_AUDIO_DRIVER=dummy \
        -e BIOFORGE_SDL_SMOKE=900 -e BIOFORGE_DATA=/app/Bioforge \
        $smoke_image sh -c "cd /tmp && $run") || true      # its stderr shows here; only stdout is compared
    echo "$got"
    if [ "$got" != "$SMOKE_LINE" ]; then echo "smoke failed: expected '$SMOKE_LINE'" >&2; exit 1; fi
done
echo "=== done: $(cd "$dist" && ls BioForge-"$commit"-*.AppImage | tr '\n' ' ')"
