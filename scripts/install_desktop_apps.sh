#!/usr/bin/env bash
# Install desktop-app launchers (Linux) for ELI surfaces:
#   • ELI Setup        → first-time / one-click full setup (install + models + launch)
#   • ELI v2.0         → the full desktop GUI
#   • ELI Server (Web) → self-hosted web app for phone/tablet/browser (LAN + token)
#
# One-click: ./scripts/install_desktop_apps.sh   (re-run to refresh).
# macOS/Windows: use the launchers directly (scripts/eli_launch.sh / install.bat) — .desktop
# files are a Linux convention; this script no-ops elsewhere with a hint.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -x "$ROOT/.venv/bin/python" ] || { echo "[eli] .venv not found — run install.sh first."; exit 1; }
PYTHON="$ROOT/.venv/bin/python"

OS="$(uname -s)"
chmod +x "$ROOT/scripts/eli_launch.sh" "$ROOT/scripts/eli_serve.sh" "$ROOT/scripts/eli_setup.sh" 2>/dev/null || true

if [ "$OS" = "Darwin" ]; then
    # macOS: double-clickable .command launchers (open in Terminal from Finder).
    APPS="$HOME/Applications"
    mkdir -p "$APPS"
    cat > "$APPS/ELI Setup.command" <<EOF
#!/bin/bash
cd "$ROOT" && exec "$ROOT/scripts/eli_setup.sh"
EOF
    cat > "$APPS/ELI v2.0.command" <<EOF
#!/bin/bash
cd "$ROOT" && exec "$ROOT/scripts/eli_launch.sh" gui
EOF
    cat > "$APPS/ELI Server (Web App).command" <<EOF
#!/bin/bash
cd "$ROOT" && exec "$ROOT/scripts/eli_serve.sh" --lan --https
EOF
    rm -f "$APPS/ELI Pro.command"
    chmod +x "$APPS/ELI Setup.command" "$APPS/ELI v2.0.command" "$APPS/ELI Server (Web App).command"
    echo "[OK] Installed launchers to $APPS :"
    echo "       • ELI Setup.command          (first-time one-click setup)"
    echo "       • ELI v2.0.command           (desktop GUI)"
    echo "       • ELI Server (Web App).command (prints the phone URL + token)"
    echo "     Double-click from Finder. Inference stays 100% local."
    exit 0
elif [ "$OS" != "Linux" ]; then
    echo "[eli] Windows: run  powershell -ExecutionPolicy Bypass -File scripts\\install_desktop_apps.ps1"
    echo "      to add 'ELI v2.0' and 'ELI Server (Web App)' Start Menu shortcuts."
    exit 0
fi

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
chmod +x "$ROOT/scripts/eli_launch.sh" "$ROOT/scripts/eli_serve.sh" "$ROOT/scripts/eli_setup.sh" 2>/dev/null || true

# Install Freedesktop theme icon (eli) + blueprints/ runtime copy.
ICON="eli"
if ! ICON="$("$PYTHON" -c "from eli.gui.branding import prepare_launcher_icons; print(prepare_launcher_icons())")"; then
    echo "[WARN] Could not install theme icon — falling back to bundled PNG path." >&2
    for c in "$ROOT/packaging/desktop/Eli_Icon.png" "$ROOT/blueprints/Eli_Icon.png"; do
        [ -f "$c" ] && { ICON="$c"; break; }
    done
fi
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true

cat > "$APPS/eli-setup.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI Setup
GenericName=First-time ELI setup
Comment=One-click install — models, database, shortcuts, then launch ELI v2.0
Exec=$ROOT/scripts/eli_setup.sh
Path=$ROOT
Icon=$ICON
Terminal=true
Categories=Utility;Settings;
StartupNotify=true
Keywords=setup;install;first;run;eli;
EOF

cat > "$APPS/eli-v2.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI v2.0
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
Exec=$ROOT/scripts/eli_serve.sh --lan --https
Path=$ROOT
Icon=$ICON
Terminal=true
Categories=Utility;Network;
StartupNotify=true
EOF

rm -f "$APPS/eli-pro.desktop" "$APPS/eli-v2-0.desktop"
chmod +x "$APPS/eli-setup.desktop" "$APPS/eli-v2.desktop" "$APPS/eli-server.desktop" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true

echo "[OK] Installed desktop launchers to $APPS :"
echo "       • ELI Setup          (first-time one-click setup)"
echo "       • ELI v2.0           (desktop GUI, icon: $ICON)"
echo "       • ELI Server (Web App) (runs in a terminal; prints the phone URL + token)"
echo "     They should now appear in your application menu. Inference stays 100% local."
