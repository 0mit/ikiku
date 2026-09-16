#!/bin/sh
# Fetch Vazirmatn (SIL OFL) into the portal's static/fonts.
#
# Run this ONCE on a machine that can reach GitHub, then commit the .woff2 files.
# They are committed on purpose: production must not depend on any CDN answering
# from inside Iran. See the build map, "Deployment".
set -eu
DEST="$(dirname "$0")/../addons/ikiku_portal/static/src/fonts"
VER="33.003"
BASE="https://github.com/rastikerdar/vazirmatn/releases/download/v${VER}/vazirmatn-v${VER}.zip"
TMP="$(mktemp -d)"
echo "fetching Vazirmatn v${VER} ..."
curl -fL "$BASE" -o "$TMP/v.zip"
unzip -q "$TMP/v.zip" -d "$TMP"
# The Farsi-Digits build draws 0-9 as Persian digits, so stored Latin digits display in Persian.
find "$TMP" -path '*Farsi-Digits*' -name 'Vazirmatn-FD-Regular.woff2' -exec cp {} "$DEST/" \;
find "$TMP" -path '*Farsi-Digits*' -name 'Vazirmatn-FD-Bold.woff2'    -exec cp {} "$DEST/" \;
rm -rf "$TMP"
echo "done. files in $DEST:"
ls -la "$DEST"
