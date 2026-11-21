#!/bin/sh
# Notarizes build/BioForge.app (built with ./build-app.sh --sign "<Developer ID>"), staples the ticket and zips it as
# dist/BioForge-<version>-mac.zip. Needs notarytool credentials in the keychain, stored once with
#   xcrun notarytool store-credentials <profile> --apple-id <Apple ID> --team-id <Team ID>
# and NOTARY_PROFILE=<profile> (default bioforge-notary). The dSYM (build/BioForge.app.dSYM) stays here, for symbolicating crash reports.
set -eu
cd "$(dirname "$0")"
app=build/BioForge.app
version="$(cat VERSION)"
mkdir -p dist
zip="dist/BioForge-$version-mac.zip"
codesign --verify --deep --strict "$app"
rm -f "$zip"
ditto -c -k --keepParent "$app" "$zip"
xcrun notarytool submit "$zip" --keychain-profile "${NOTARY_PROFILE:-bioforge-notary}" --wait
xcrun stapler staple "$app"
# Zip again so the download carries the stapled ticket and opens without a network check.
rm -f "$zip"
ditto -c -k --keepParent "$app" "$zip"
xcrun stapler validate "$app"
spctl --assess --type execute --verbose "$app"
echo "Notarized $PWD/$zip"
