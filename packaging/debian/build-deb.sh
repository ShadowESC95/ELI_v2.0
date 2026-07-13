#!/usr/bin/env bash
# Build a lean ELI .deb: source + a first-run-installing /usr/bin/eli-v2 launcher.
# The heavy Python venv + a model are set up on first launch (like the lean AppImage),
# so the package stays small (~6 MB). Requires dpkg-deb.
#
# Usage:  bash packaging/debian/build-deb.sh [version]     (or: build_packages.sh deb)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-$(grep -E '^version' "$ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')}"
OUT_DIR="$ROOT/dist/app_packages"; mkdir -p "$OUT_DIR"
DEB="$OUT_DIR/ELI_v2-${VERSION}-amd64.deb"
command -v dpkg-deb >/dev/null 2>&1 || { echo "[deb] dpkg-deb not found (install dpkg)" >&2; exit 1; }

STAGE="$(mktemp -d)/eli-deb"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/eli-v2" "$STAGE/usr/bin"
# Tracked files only (git archive) → lean; models/venv are excluded automatically.
( cd "$ROOT" && git archive --format=tar HEAD ) | tar -x -C "$STAGE/opt/eli-v2"

cat > "$STAGE/DEBIAN/control" <<CTRL
Package: eli-v2
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.10), python3-venv, python3-pip
Maintainer: ShadowESC95 <noreply@github.com>
Description: ELI v2.0 - local, private cognitive AI assistant
 ELI is a fully local AI assistant and desktop operator: chat, memory, voice,
 vision, code, and automation that run entirely on your machine. First launch
 sets up a Python environment in your home directory and offers to download a
 model sized to your GPU; nothing leaves your device unless you allow it.
 .
 Run with:  eli-v2
CTRL

cat > "$STAGE/usr/bin/eli-v2" <<'LAUNCH'
#!/usr/bin/env bash
# ELI v2 (.deb) — first launch self-installs to ~/.local/share/ELI_v2, then launches.
set -euo pipefail
SRC="/opt/eli-v2"
INSTALL_ROOT="${ELI_INSTALL_ROOT:-$HOME/.local/share/ELI_v2}"
MARKER="$INSTALL_ROOT/.eli_deb_ready"
mkdir -p "$INSTALL_ROOT"; export ELI_PROJECT_ROOT="$INSTALL_ROOT"
if [ ! -f "$MARKER" ]; then
  echo "First launch: preparing ELI in $INSTALL_ROOT (a few minutes)…"
  if command -v rsync >/dev/null 2>&1; then rsync -a --exclude='.venv' "$SRC/" "$INSTALL_ROOT/";
  else cp -a "$SRC/." "$INSTALL_ROOT/"; fi
  ( cd "$INSTALL_ROOT" && bash install.sh --yes ) && touch "$MARKER"
fi
cd "$INSTALL_ROOT"
for L in RUN_ELI.sh eli.sh scripts/eli_launch.sh; do
  [ -f "$INSTALL_ROOT/$L" ] && exec bash "$INSTALL_ROOT/$L" "$@"
done
exec "$INSTALL_ROOT/.venv/bin/python" -m eli.gui.app "$@"
LAUNCH
chmod 0755 "$STAGE/usr/bin/eli-v2"

dpkg-deb --root-owner-group --build "$STAGE" "$DEB"
rm -rf "$(dirname "$STAGE")"
echo "[deb] built: $DEB"
