#!/bin/sh
# Install this repository's versioned hooks.
#
# .git/hooks is NOT cloned, so a fresh clone has no gate at all until this runs.
# Same reasoning as bin/install.sh in the daftar garden.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$(git -C "$ROOT" rev-parse --git-path hooks)"
mkdir -p "$DEST"
for hook in "$ROOT"/tools/hooks/*; do
  name="$(basename "$hook")"
  cp "$hook" "$DEST/$name"
  chmod +x "$DEST/$name"
  echo "installed $name"
done
