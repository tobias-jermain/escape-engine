#!/usr/bin/env bash
# Build a self-contained `escape` (no Python needed) for this machine's CPU, then smoke-test it.
set -euo pipefail
cd "$(dirname "$0")/../.."

ARCH="$(uname -m)"
OUT="build/macos/$ARCH"
rm -rf "$OUT" build/pyinstaller

uv run --with "pyinstaller>=6.10" pyinstaller --noconfirm --clean --onedir --name escape \
  --collect-data escape_engine --collect-submodules escape_engine \
  --distpath "$OUT" --workpath build/pyinstaller/work --specpath build/pyinstaller \
  packaging/entry.py

"$OUT/escape/escape" --version
"$OUT/escape/escape" airports LON > /dev/null

tar -C "$OUT" -czf "build/escape-macos-$ARCH.tar.gz" escape
echo "built build/escape-macos-$ARCH.tar.gz"
