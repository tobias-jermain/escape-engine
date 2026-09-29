#!/usr/bin/env bash
# Combine the arm64 and x86_64 builds into ONE installer for every Mac.
# Needs build/escape-macos-arm64.tar.gz and build/escape-macos-x86_64.tar.gz (from build_binary.sh).
set -euo pipefail
cd "$(dirname "$0")/../.."

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
ROOT=build/pkgroot
APP="$ROOT/Applications/Escape Engine.app"
rm -rf "$ROOT"
mkdir -p "$ROOT/usr/local/lib/escape-engine" "$ROOT/usr/local/bin" "$ROOT/Applications"

for arch in arm64 x86_64; do
  mkdir -p "$ROOT/usr/local/lib/escape-engine/$arch"
  tar -xzf "build/escape-macos-$arch.tar.gz" -C "$ROOT/usr/local/lib/escape-engine/$arch"
done

install -m 755 packaging/macos/escape-wrapper.sh "$ROOT/usr/local/bin/escape"
cp -R "packaging/macos/Escape Engine.app" "$ROOT/Applications/"
chmod 755 "$APP/Contents/MacOS/escape-engine"
sed -i '' "s/__VERSION__/$VERSION/g" "$APP/Contents/Info.plist"

# Stop Installer from "relocating" the app to some other copy it finds on the disk.
pkgbuild --analyze --root "$ROOT" build/components.plist
python3 - <<'PY'
import plistlib
path = "build/components.plist"
with open(path, "rb") as fh:
    components = plistlib.load(fh)
for c in components:
    c["BundleIsRelocatable"] = False
with open(path, "wb") as fh:
    plistlib.dump(components, fh)
PY

pkgbuild --root "$ROOT" \
  --component-plist build/components.plist \
  --identifier io.github.tobias-jermain.escape-engine \
  --version "$VERSION" \
  --install-location / \
  --scripts packaging/macos/scripts \
  "build/EscapeEngine-$VERSION.pkg"
echo "built build/EscapeEngine-$VERSION.pkg"
