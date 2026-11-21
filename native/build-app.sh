#!/bin/sh
# Builds native/build/BioForge.app, a double-clickable release build. The game data is never bundled: on first launch the app asks for
# your BioForge folder and remembers it.
#   ./build-app.sh                          ad-hoc signed, this Mac's architecture (development)
#   ./build-app.sh --sign "<Developer ID>"  a build to hand out: universal (Apple silicon and Intel), signed with the hardened runtime and a
#                                           secure timestamp (as notarization needs; then ./notarize.sh), the original-artwork icon and the
#                                           art model (shipped with its author's permission)
# The version is native/VERSION.
set -eu
cd "$(dirname "$0")"
identity=-
while [ $# -gt 0 ]; do
    case "$1" in
        --sign) identity="$2"; shift 2 ;;
        *) echo "usage: build-app.sh [--sign <identity>]" >&2; exit 1 ;;
    esac
done
version="$(cat VERSION)"
if [ "$identity" = - ]; then arch_flags=""; else arch_flags="--arch arm64 --arch x86_64"; fi
# shellcheck disable=SC2086
swift build -c release --product BioForgeApp $arch_flags
# shellcheck disable=SC2086
bin="$(swift build -c release --product BioForgeApp $arch_flags --show-bin-path)"
app=build/BioForge.app
build_number="$(git rev-list --count HEAD 2>/dev/null || echo 1)"
# The commit the app was built from, shown in About, the log and bug reports; "-dirty" when tracked files have uncommitted changes.
commit="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ "$commit" != unknown ] && [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then commit="$commit-dirty"; fi
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin/BioForgeApp" "$app/Contents/MacOS/BioForge"
# The debug symbols stay outside the bundle, so a crash report from this build can be symbolicated (keep BioForge.app.dSYM with the build you hand out).
rm -rf build/BioForge.app.dSYM
dsymutil "$bin/BioForgeApp" -o build/BioForge.app.dSYM 2>/dev/null
# The model for View > High-Resolution Art (4x_HDCube_200k by Venomalia, pinned to a commit and checked), converted to Core ML by
# re/tools/convert_model.py with BIOFORGE_ML_PYTHON (a Python with torch, spandrel and coremltools). Without it a development build has no
# model and can't build the art. Its licence allows redistributing the original file only, unmodified; the author, Venomalia, gave
# permission on 2026-11-21 to ship this converted copy in BioForge (README "High-resolution art"). A signed build must include it: from
# BIOFORGE_ML_PYTHON or, without it, the converted copy already in build/cache.
model_commit=dbbe8c0fbf348ddf032da8391f367e615e538ca1
model_sha256=c696eddb2fe313613978c4fe5a10a17e8670d85487e35b304d87fc16df4a7694
cache=build/cache
if [ "$identity" != - ] && [ -z "${BIOFORGE_ML_PYTHON:-}" ]; then
    if [ ! -d "$cache/model2/HDCube.mlmodelc" ] || [ ! -f "$cache/HDcube-LICENSE.txt" ]; then
        echo "A signed build needs the art model: set BIOFORGE_ML_PYTHON (README \"High-resolution art\")" >&2; exit 1
    fi
    cp -R "$cache/model2/HDCube.mlmodelc" "$cache/HDcube-LICENSE.txt" "$app/Contents/Resources/"
elif [ -n "${BIOFORGE_ML_PYTHON:-}" ]; then
    mkdir -p "$cache"
    if [ ! -f "$cache/4x_HDCube_200k.pth" ] || ! echo "$model_sha256  $cache/4x_HDCube_200k.pth" | shasum -a 256 -c - >/dev/null 2>&1; then
        curl -fsSL -o "$cache/4x_HDCube_200k.pth" "https://raw.githubusercontent.com/Venomalia/HDcube/$model_commit/v1/4x_HDCube_200k.pth"
        echo "$model_sha256  $cache/4x_HDCube_200k.pth" | shasum -a 256 -c - >/dev/null
    fi
    [ -f "$cache/HDcube-LICENSE.txt" ] || curl -fsSL -o "$cache/HDcube-LICENSE.txt" "https://raw.githubusercontent.com/Venomalia/HDcube/$model_commit/LICENSE"
    [ -d "$cache/model2/HDCube.mlmodelc" ] || "$BIOFORGE_ML_PYTHON" -I ../re/tools/convert_model.py "$cache/4x_HDCube_200k.pth" "$cache/model2" >/dev/null
    cp -R "$cache/model2/HDCube.mlmodelc" "$cache/HDcube-LICENSE.txt" "$app/Contents/Resources/"
else
    echo "BIOFORGE_ML_PYTHON is not set: building without the High-Resolution Art model" >&2
fi
# The icon: in a development build the GOG release's hand (Resources/gog_icon.py, from goggame-*.ico next to the BIOFORGE_DATA folder, default
# ../game/app/Bioforge) when it is there; else, and always in a signed build (no GOG/EA art is handed out), Resources/AppIcon.png (original
# artwork, Resources/make_icon.py) -> every size macOS wants -> AppIcon.icns
iconset="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$iconset"
icon=Resources/AppIcon.png
gog_ico="$(ls "$(dirname "${BIOFORGE_DATA:-$PWD/../game/app/Bioforge}")"/goggame-*.ico 2>/dev/null | head -n 1 || true)"
if [ "$identity" = - ] && [ -n "$gog_ico" ] && [ -x ../re/.venv/bin/python ] && ../re/.venv/bin/python -I Resources/gog_icon.py "$gog_ico" "$iconset/../AppIcon.png"; then
    icon="$iconset/../AppIcon.png"
else
    [ "$identity" != - ] || echo "No GOG icon found: using Resources/AppIcon.png" >&2
fi
for s in 16 32 128 256 512; do
    sips -z $s $s "$icon" --out "$iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s * 2)) $((s * 2)) "$icon" --out "$iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app/Contents/Resources/AppIcon.icns"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleExecutable</key><string>BioForge</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleIdentifier</key><string>io.github.kcin1107.BioForge</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleName</key><string>BioForge</string>
    <key>CFBundleDisplayName</key><string>BioForge</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$version</string>
    <key>CFBundleVersion</key><string>$build_number</string>
    <key>BioForgeCommit</key><string>$commit</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.adventure-games</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHumanReadableCopyright</key><string>Unofficial fan port, not affiliated with Electronic Arts. BioForge is a trademark of Electronic Arts Inc.</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict>
</plist>
PLIST
if [ "$identity" = - ]; then
    codesign --force --sign - "$app"
else
    codesign --force --options runtime --timestamp --sign "$identity" "$app"
fi
echo "$PWD/$app"
