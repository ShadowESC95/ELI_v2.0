#!/usr/bin/env bash
# Build a grandma-friendly Linux AppImage from the existing portable package.
#
# First launch copies ELI into ~/.local/share/ELI_v2, runs one-click setup once,
# then launches. Requires Python 3.10+ on the host (same as the portable tarball).
#
# Usage:
#   bash packaging/linux/build-appimage.sh [version]
#   # or via build_packages.sh appimage
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-$(grep -E '^version' "$ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')}"
OUT_DIR="$ROOT/dist/app_packages"
WORK="$ROOT/build/appimage"
APPDIR="$WORK/ELI_v2.AppDir"
APPIMAGE="$OUT_DIR/ELI_v2-${VERSION}-x86_64.AppImage"
PORTABLE="$OUT_DIR/ELI_v2-${VERSION}-linux-portable.tar.gz"

mkdir -p "$OUT_DIR" "$WORK"

if [ ! -f "$PORTABLE" ]; then
  echo "[appimage] portable package missing — building it first"
  SKIP_TESTS="${SKIP_TESTS:-1}" bash "$ROOT/scripts/package_desktop_app.sh"
fi

echo "[appimage] staging AppDir from $(basename "$PORTABLE")"
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
tar -xzf "$PORTABLE" -C "$WORK"
STAGING="$(find "$WORK" -maxdepth 1 -type d -name 'ELI_v2-*-linux-portable' | head -1)"
if [ -z "$STAGING" ] || [ ! -d "$STAGING" ]; then
  echo "[appimage] could not find extracted portable tree" >&2
  exit 1
fi
cp -a "$STAGING/." "$APPDIR/"
rm -rf "$STAGING"

ICON="$APPDIR/packaging/desktop/eli-256.png"
[ -f "$ICON" ] || ICON="$APPDIR/packaging/desktop/Eli_Icon.png"
[ -f "$ICON" ] || ICON="$ROOT/packaging/desktop/Eli_Icon.png"

cat > "$APPDIR/AppRun" <<'APPRUN_EOF'
#!/usr/bin/env bash
# ELI v2 AppImage — first double-click installs to ~/.local/share/ELI_v2, then launches.
set -euo pipefail
HERE="$(dirname "$(readlink -f "${0}")")"
INSTALL_ROOT="${ELI_INSTALL_ROOT:-$HOME/.local/share/ELI_v2}"
MARKER="$INSTALL_ROOT/.eli_appimage_ready"
LOG="$INSTALL_ROOT/setup.log"

mkdir -p "$INSTALL_ROOT"
export ELI_PROJECT_ROOT="$INSTALL_ROOT"
export ELI_DATA_DIR="${ELI_DATA_DIR:-$INSTALL_ROOT/artifacts}"
export ELI_CONFIG_DIR="${ELI_CONFIG_DIR:-$INSTALL_ROOT/config}"
export ELI_MODELS_DIR="${ELI_MODELS_DIR:-$INSTALL_ROOT/models}"
export ELI_CACHE_DIR="${ELI_CACHE_DIR:-$HOME/.cache/ELI_v2}"
export PYTHONPATH="$INSTALL_ROOT${PYTHONPATH:+:$PYTHONPATH}"

_notify() {
  command -v zenity >/dev/null 2>&1 || return 0
  zenity --info --title="ELI Setup" --width=420 --text="$1" 2>/dev/null || true
}

_progress() {
  command -v zenity >/dev/null 2>&1 || return 0
  zenity --progress --pulsate --auto-close --title="ELI Setup" --text="$1" 2>/dev/null || true
}

if [ ! -f "$MARKER" ]; then
  _progress "First launch — preparing ELI on your computer (a few minutes)…" &
  _ZPID=$!
  {
    echo "=== ELI AppImage first-run setup $(date -Iseconds) ==="
    rsync -a --delete --exclude=.venv --exclude='artifacts/db/*.sqlite3' \
      "$HERE/" "$INSTALL_ROOT/" 2>&1 || cp -a "$HERE/." "$INSTALL_ROOT/"
    if [ -x "$INSTALL_ROOT/ELI_Setup.sh" ]; then
      bash "$INSTALL_ROOT/ELI_Setup.sh" >>"$LOG" 2>&1
    elif [ -x "$INSTALL_ROOT/INSTALL_ELI.sh" ]; then
      bash "$INSTALL_ROOT/INSTALL_ELI.sh" >>"$LOG" 2>&1
    else
      bash "$INSTALL_ROOT/install.sh" --yes >>"$LOG" 2>&1
    fi
    touch "$MARKER"
  } || {
    kill "$_ZPID" 2>/dev/null || true
    _notify "ELI setup failed.\n\nSee log:\n$LOG"
    exit 1
  }
  kill "$_ZPID" 2>/dev/null || true
  wait "$_ZPID" 2>/dev/null || true
  _notify "ELI is ready.\n\nNext launches open ELI directly.\nSetup log: $LOG"
fi

cd "$INSTALL_ROOT"
exec "$INSTALL_ROOT/RUN_ELI.sh" "$@"
APPRUN_EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/eli-v2.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI v2.0
GenericName=Local AI Assistant
Comment=Private local AI assistant — runs on your machine
Exec=AppRun
Icon=eli
Categories=Utility;
Terminal=false
StartupNotify=true
EOF

cp "$ICON" "$APPDIR/eli.png"
cp "$ICON" "$APPDIR/.DirIcon" 2>/dev/null || true

APPIMAGETOOL=""
if command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL="appimagetool"
elif [ -x "$ROOT/build/appimagetool-x86_64.AppImage" ]; then
  APPIMAGETOOL="$ROOT/build/appimagetool-x86_64.AppImage"
else
  echo "[appimage] downloading appimagetool…"
  curl -fsSL -o "$ROOT/build/appimagetool-x86_64.AppImage" \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$ROOT/build/appimagetool-x86_64.AppImage"
  APPIMAGETOOL="$ROOT/build/appimagetool-x86_64.AppImage"
fi

export ARCH="${ARCH:-x86_64}"
export VERSION="$VERSION"
rm -f "$APPIMAGE"
echo "[appimage] building $APPIMAGE"
"$APPIMAGETOOL" "$APPDIR" "$APPIMAGE"
( cd "$OUT_DIR" && sha256sum "$(basename "$APPIMAGE")" > "$(basename "$APPIMAGE").sha256" )
echo "[appimage] complete: $APPIMAGE"
