#!/usr/bin/env bash
# Install desktop-app launchers (Linux) for BOTH ELI surfaces, so they appear in your
# application menu like any installed app:
#   • ELI Pro          → the full desktop GUI
#   • ELI Server (Web)  → the self-hosted web app for phone/tablet/browser (LAN + token)
#
# One-click: ./scripts/install_desktop_apps.sh   (re-run to refresh).
# macOS/Windows: use the launchers directly (scripts/eli_launch.sh / install.bat) — .desktop
# files are a Linux convention; this script no-ops elsewhere with a hint.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -x "$ROOT/.venv/bin/python" ] || { echo "[eli] .venv not found — run install.sh first."; exit 1; }

if [ "$(uname -s)" != "Linux" ]; then
    echo "[eli] Desktop .desktop launchers are Linux-only."
    echo "      macOS/Windows: launch with  ./scripts/eli_launch.sh  (gui|serve --lan|both)."
    exit 0
fi

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
chmod +x "$ROOT/scripts/eli_launch.sh" "$ROOT/scripts/eli_serve.sh" 2>/dev/null || true

# Optional icon — use one if present, otherwise fall back to a stock icon name.
ICON="utilities-terminal"
for c in "$ROOT/blueprints/eli_logo2.png" "$ROOT/blueprints/Eli_Icon.png" "$ROOT/eli/gui/assets/eli.png"; do
    [ -f "$c" ] && { ICON="$c"; break; }
done

cat > "$APPS/eli-pro.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI Pro
Comment=Local, private AI assistant (desktop GUI)
Exec=$ROOT/scripts/eli_launch.sh gui
Path=$ROOT
Icon=$ICON
Terminal=false
Categories=Utility;Development;Office;
StartupNotify=true
EOF

cat > "$APPS/eli-server.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI Server (Web App)
Comment=Self-hosted ELI web app — open from any device on your network (LAN + token)
Exec=$ROOT/scripts/eli_serve.sh --lan
Path=$ROOT
Icon=$ICON
Terminal=true
Categories=Utility;Network;
StartupNotify=true
EOF

chmod +x "$APPS/eli-pro.desktop" "$APPS/eli-server.desktop" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true

echo "[OK] Installed desktop launchers to $APPS :"
echo "       • ELI Pro            (desktop GUI)"
echo "       • ELI Server (Web App) (runs in a terminal; prints the phone URL + token)"
echo "     They should now appear in your application menu. Inference stays 100% local."
