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
# Don't hard-fail if the venv is missing — we can still install working launchers + the
# guard (only the theme-icon step needs Python, and it already has a PNG fallback).
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    echo "[eli] note: .venv not found — installing launchers anyway (run install.sh to finish setup)."
    PYTHON="$(command -v python3 || echo python3)"
fi

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
    cat > "$APPS/ELI Uninstall.command" <<EOF
#!/bin/bash
exec "$ROOT/scripts/eli_uninstall.sh"
EOF
    rm -f "$APPS/ELI Pro.command"
    chmod +x "$APPS/ELI Setup.command" "$APPS/ELI v2.0.command" \
             "$APPS/ELI Server (Web App).command" "$APPS/ELI Uninstall.command"
    echo "[OK] Installed launchers to $APPS :"
    echo "       • ELI Setup.command          (first-time one-click setup)"
    echo "       • ELI v2.0.command           (desktop GUI)"
    echo "       • ELI Server (Web App).command (prints the phone URL + token)"
    echo "       • ELI Uninstall.command      (remove ELI; optionally delete the install)"
    echo "     Double-click from Finder. Inference stays 100% local."
    exit 0
elif [ "$OS" != "Linux" ]; then
    echo "[eli] Windows: run  powershell -ExecutionPolicy Bypass -File scripts\\install_desktop_apps.ps1"
    echo "      to add 'ELI v2.0' and 'ELI Server (Web App)' Start Menu shortcuts."
    exit 0
fi

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
chmod +x "$ROOT/scripts/eli_launch.sh" "$ROOT/scripts/eli_serve.sh" "$ROOT/scripts/eli_setup.sh" \
         "$ROOT/scripts/eli_term.sh" "$ROOT/scripts/eli_uninstall.sh" 2>/dev/null || true
TERM_RUN="$ROOT/scripts/eli_term.sh"   # opens a real terminal (GNOME/Wayland ignore Terminal=true)

# Guard wrapper in ~/.local/bin (OUTSIDE the install) so the icons fail LOUDLY — with a
# visible dialog — if the install is later moved/deleted or its scripts go missing,
# instead of silently doing nothing (the failure mode that kept biting).
BIN="$HOME/.local/bin"; mkdir -p "$BIN"; GUARD="$BIN/eli-run"
cat > "$GUARD" <<'GUARD_EOF'
#!/usr/bin/env bash
# ELI launcher guard. Args: <install_root> <gui|serve|setup|uninstall>
R="$1"; A="$2"
_err(){ command -v zenity >/dev/null 2>&1 && zenity --error --title="ELI" --width=420 --text="$1" 2>/dev/null \
    || { command -v notify-send >/dev/null 2>&1 && notify-send "ELI" "$1" 2>/dev/null; } \
    || { printf '%s\n' "$1"; sleep 6; }; }
[ -n "$R" ] && [ -d "$R" ] || { _err "ELI install not found at:
$R

Re-run ELI Setup, or reinstall the latest release."; exit 1; }
T="$R/scripts/eli_term.sh"
case "$A" in
  gui)       S="$R/scripts/eli_launch.sh";    RUN=(gui) ;;
  serve)     S="$R/scripts/eli_serve.sh";     RUN=(--lan --https) ;;
  setup)     S="$R/scripts/eli_setup.sh";     RUN=() ;;
  uninstall) S="$R/scripts/eli_uninstall.sh"; RUN=() ;;
  *) _err "Unknown ELI action: $A"; exit 2 ;;
esac
if [ "$A" = "gui" ]; then
  [ -x "$S" ] || { _err "ELI is damaged (missing launcher) at:
$R

Reinstall the latest release."; exit 1; }
  exec "$S" "${RUN[@]}"
fi
{ [ -x "$T" ] && [ -x "$S" ]; } || { _err "ELI is damaged (missing scripts) at:
$R

Re-run ELI Setup, or reinstall the latest release."; exit 1; }
exec "$T" "$S" "${RUN[@]}"
GUARD_EOF
chmod +x "$GUARD"

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
Exec=$GUARD "$ROOT" setup
Path=$ROOT
Icon=$ICON
Terminal=false
Categories=Utility;Settings;
StartupNotify=true
Keywords=setup;install;first;run;eli;
EOF

cat > "$APPS/eli-v2.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI v2.0
Comment=Local, private AI assistant (desktop GUI)
Exec=$GUARD "$ROOT" gui
Path=$ROOT
Icon=$ICON
Terminal=false
Categories=Utility;Development;Office;
StartupNotify=true
StartupWMClass=ELI
EOF

cat > "$APPS/eli-server.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI Server (Web App)
Comment=Self-hosted ELI web app — open from any device on your network (LAN + token)
Exec=$GUARD "$ROOT" serve
Path=$ROOT
Icon=$ICON
Terminal=false
Categories=Utility;Network;
StartupNotify=true
EOF

cat > "$APPS/eli-uninstall.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ELI Uninstall
GenericName=Remove ELI
Comment=Remove ELI's menu icons and the 'eli' command; optionally delete this install
Exec=$GUARD "$ROOT" uninstall
Path=$ROOT
Icon=$ICON
Terminal=false
Categories=Utility;Settings;
StartupNotify=true
Keywords=uninstall;remove;delete;eli;
EOF

rm -f "$APPS/eli-pro.desktop" "$APPS/eli-v2-0.desktop"
chmod +x "$APPS/eli-setup.desktop" "$APPS/eli-v2.desktop" "$APPS/eli-server.desktop" "$APPS/eli-uninstall.desktop" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true

echo "[OK] Installed desktop launchers to $APPS :"
echo "       • ELI Setup          (first-time one-click setup)"
echo "       • ELI v2.0           (desktop GUI, icon: $ICON)"
echo "       • ELI Server (Web App) (opens a terminal; prints the phone URL + token)"
echo "       • ELI Uninstall      (remove icons/command; optionally delete the install)"
echo "     They should now appear in your application menu. Inference stays 100% local."
