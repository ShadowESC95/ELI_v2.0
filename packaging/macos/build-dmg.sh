#!/usr/bin/env bash
# ELI v2 — package the PyInstaller .app into a drag-to-Applications .dmg.
#
# Prerequisite: `pyinstaller --noconfirm ELI.spec` (produces dist/ELI.app).
# Usage:        bash packaging/macos/build-dmg.sh
# Output:       dist/ELI_v2-<version>-macos-<arch>.dmg  (+ .sha256)
#
# Signing: the app is ad-hoc signed (required on Apple Silicon). Distribution
# without Gatekeeper warnings needs a Developer ID certificate + notarization —
# see docs/RELEASE_PIPELINE.md for the manual steps.
set -euo pipefail

fail() { echo "[build-dmg] ERROR: $*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "this script must run on macOS (uname: $(uname -s))"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/dist/ELI.app"
VERSION="$(python3 -c "
import sys, pathlib
sys.path.insert(0, r'$ROOT/packaging/pyinstaller')
import gen_version_info; print(gen_version_info.project_version(pathlib.Path(r'$ROOT')))
")"
[ -n "$VERSION" ] || fail "could not read version from pyproject.toml"
ARCH="$(uname -m)"
DMG="$ROOT/dist/ELI_v2-${VERSION}-macos-${ARCH}.dmg"

[ -d "$APP" ] || fail "dist/ELI.app not found — run: pyinstaller --noconfirm ELI.spec"
[ -x "$APP/Contents/MacOS/ELI" ] || fail "ELI.app is missing its executable — the PyInstaller build is incomplete"

echo "[build-dmg] ad-hoc signing ELI.app (required on Apple Silicon)"
codesign --force --deep --sign - "$APP" || fail "ad-hoc codesign failed"
codesign --verify --deep "$APP" || fail "codesign verification failed"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

echo "[build-dmg] creating $DMG"
rm -f "$DMG"
hdiutil create -volname "ELI v2.0 $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG" \
    || fail "hdiutil create failed"

shasum -a 256 "$DMG" > "$DMG.sha256"
echo "[build-dmg] done: $DMG ($(du -h "$DMG" | cut -f1))"
