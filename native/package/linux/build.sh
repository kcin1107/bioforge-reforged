#!/bin/bash
# Runs inside docker.io/library/swift:6.4-jammy, started by native/package-linux.sh: builds SDL3 and BioForgeSDL and packs the AppImage.
# Jammy's glibc 2.35 keeps the AppImage running on older systems than the build host (SteamOS included). The Swift runtime is linked in
# statically; libSDL3 is bundled and finds X11, Wayland, PipeWire, PulseAudio and ALSA on the player's system when it starts.
#   /src             native/ (read-only)
#   /dist            native/dist: cache/ holds the downloads package-linux.sh checked; the AppImage is written here
#   SDL_VERSION, RUNTIME, OUT, COMMIT   from package-linux.sh
set -euo pipefail

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends cmake ninja-build squashfs-tools desktop-file-utils file pkg-config \
    libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxfixes-dev libxi-dev libxss-dev libxtst-dev libxkbcommon-dev \
    libwayland-dev wayland-protocols libdecor-0-dev libegl1-mesa-dev libgl1-mesa-dev libgles2-mesa-dev libdrm-dev libgbm-dev \
    libpipewire-0.3-dev libpulse-dev libasound2-dev libdbus-1-dev libudev-dev >/dev/null

echo "== SDL $SDL_VERSION"
mkdir -p /work && cd /work
tar xzf "/dist/cache/SDL3-$SDL_VERSION.tar.gz"
cmake -S "SDL3-$SDL_VERSION" -B sdl-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/sdl3 -DCMAKE_INSTALL_LIBDIR=lib \
    -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF -DSDL_DEPS_SHARED=ON >sdl-configure.log
grep -E "^-- +(SDL_(X11|WAYLAND|PIPEWIRE|PULSEAUDIO|ALSA|DBUS|LIBUDEV|HIDAPI|OPENGL|VULKAN)\b)" sdl-configure.log || true
cmake --build sdl-build >/dev/null
cmake --install sdl-build >/dev/null

echo "== BioForgeSDL"
cd /src
PKG_CONFIG_PATH=/opt/sdl3/lib/pkgconfig swift build -c release --static-swift-stdlib --product BioForgeSDL --scratch-path /build \
    -Xlinker -rpath -Xlinker '$ORIGIN/../lib'

echo "== AppDir"
app=/work/AppDir
rm -rf "$app"
mkdir -p "$app/usr/bin" "$app/usr/lib" "$app/usr/share/applications" "$app/usr/share/icons/hicolor/256x256/apps" "$app/usr/share/doc/BioForge"
install -m 755 /build/release/BioForgeSDL "$app/usr/bin/BioForgeSDL"
cp -L /opt/sdl3/lib/libSDL3.so.0 "$app/usr/lib/libSDL3.so.0"
strip --strip-unneeded "$app/usr/bin/BioForgeSDL" "$app/usr/lib/libSDL3.so.0"
ln -s usr/bin/BioForgeSDL "$app/AppRun"               # no wrapper script: the environment (Steam's SteamDeck, SDL_GAMECONTROLLERCONFIG) reaches the game as is
install -m 644 /src/package/linux/bioforge.desktop "$app/bioforge.desktop"
install -m 644 /src/package/linux/bioforge.desktop "$app/usr/share/applications/bioforge.desktop"
install -m 644 /dist/cache/bioforge-256.png "$app/bioforge.png"
install -m 644 /dist/cache/bioforge-256.png "$app/usr/share/icons/hicolor/256x256/apps/bioforge.png"
ln -s bioforge.png "$app/.DirIcon"
cp /src/package/README.txt /src/package/NOTICES.txt "$app/usr/share/doc/BioForge/"
cp -r /src/package/licenses "$app/usr/share/doc/BioForge/licenses"
echo "$COMMIT" > "$app/usr/share/doc/BioForge/VERSION"

echo "== checks"
desktop-file-validate "$app/bioforge.desktop"
for f in "$app/usr/bin/BioForgeSDL" "$app/usr/lib/libSDL3.so.0"; do
    echo "$(basename "$f"): needs $(readelf -d "$f" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | tr '\n' ' ')"
    echo "  newest symbol versions: $(objdump -T "$f" | grep -oE 'GLIBC(XX)?_[0-9.]+' | sort -Vu | awk -F_ '{v[$1]=$0} END {for (k in v) printf "%s ", v[k]}')"
    if ldd "$f" | grep -q "not found"; then ldd "$f"; echo "missing libraries" >&2; exit 1; fi
done
# Only the system's C and C++ runtimes and the bundled SDL: no Swift runtime, no X11 or audio library linked directly.
extra=$(readelf -d "$app/usr/bin/BioForgeSDL" "$app/usr/lib/libSDL3.so.0" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' |
    grep -vE '^(libc|libm|libdl|libpthread|librt|libstdc\+\+|libgcc_s|ld-linux-[a-z0-9_-]+)\.so|^libSDL3\.so\.0$' || true)
if [ -n "$extra" ]; then echo "unexpected libraries: $extra" >&2; exit 1; fi

echo "== AppImage"
mksquashfs "$app" /work/app.squashfs -root-owned -noappend -comp zstd -quiet
cat "/dist/cache/$RUNTIME" /work/app.squashfs > "/dist/$OUT"
chmod 755 "/dist/$OUT"
ls -l "/dist/$OUT"
