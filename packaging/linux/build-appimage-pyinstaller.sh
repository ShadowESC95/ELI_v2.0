#!/usr/bin/env bash
# ELI v2 — package the PyInstaller one-dir bundle into a Linux AppImage.
#
# This is the frozen-build counterpart of build-appimage.sh (which wraps the
# source-portable tarball and stays as-is). The AppImage is self-contained:
# no Python required on the host. Mutable state (settings, models, artifacts)
# is routed to ~/.local/share/ELI_v2 by the frozen runtime hook, because the
# mounted AppImage is read-only.
#
# Prerequisite: `pyinstaller --noconfirm ELI.spec` (produces dist/ELI/).
# Usage:        bash packaging/linux/build-appimage-pyinstaller.sh
# Output:       dist/ELI_v2-<version>-<arch>.AppImage  (+ .sha256)
set -euo pipefail

fail() { echo "[appimage] ERROR: $*" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE="$ROOT/dist/ELI"
VERSION="$(python3 -c "
import sys, pathlib
sys.path.insert(0, r'$ROOT/packaging/pyinstaller')
import gen_version_info; print(gen_version_info.project_version(pathlib.Path(r'$ROOT')))
")"
[ -n "$VERSION" ] || fail "could not read version from pyproject.toml"
ARCH="$(uname -m)"
OUT="$ROOT/dist/ELI_v2-${VERSION}-${ARCH}.AppImage"
WORK="$ROOT/build/appimage-pyinstaller"
APPDIR="$WORK/ELI.AppDir"

[ -d "$BUNDLE" ] || fail "dist/ELI not found — run: pyinstaller --noconfirm ELI.spec"
[ -x "$BUNDLE/ELI" ] || fail "dist/ELI/ELI executable missing — the PyInstaller build is incomplete"

ICON="$ROOT/packaging/desktop/eli-256.png"
[ -f "$ICON" ] || ICON="$ROOT/packaging/desktop/Eli_Icon.png"
[ -f "$ICON" ] || fail "app icon not found under packaging/desktop/"

echo "[appimage] staging AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -a "$BUNDLE" "$APPDIR/usr/app"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/app/ELI" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/eli.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI v2.0
GenericName=Local AI Assistant
Comment=Private local AI assistant — runs entirely on your machine
Exec=AppRun
Icon=eli
Categories=Utility;
Terminal=false
X-AppImage-Version=${VERSION}
EOF

cp "$ICON" "$APPDIR/eli.png"
cp "$ICON" "$APPDIR/.DirIcon"

# appimagetool: use one on PATH, else download it (current repo first, then
# the legacy AppImageKit 13 URL — upstream moved between these once already).
APPIMAGETOOL="$(command -v appimagetool || true)"
if [ -z "$APPIMAGETOOL" ]; then
    APPIMAGETOOL="$WORK/appimagetool-x86_64.AppImage"
    if [ ! -x "$APPIMAGETOOL" ]; then
        echo "[appimage] downloading appimagetool"
        curl -fsSL -o "$APPIMAGETOOL" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" \
        || curl -fsSL -o "$APPIMAGETOOL" \
            "https://github.com/AppImage/AppImageKit/releases/download/13/appimagetool-x86_64.AppImage" \
        || fail "could not download appimagetool — install it or place it at $APPIMAGETOOL"
        chmod +x "$APPIMAGETOOL"
    fi
fi

echo "[appimage] building $OUT"
rm -f "$OUT"
# --appimage-extract-and-run avoids needing FUSE on CI runners/containers.
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$OUT" \
    || fail "appimagetool failed"

[ -f "$OUT" ] || fail "appimagetool reported success but $OUT is missing"
sha256sum "$OUT" > "$OUT.sha256"
echo "[appimage] done: $OUT ($(du -h "$OUT" | cut -f1))"
