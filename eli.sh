#!/usr/bin/env bash
# ELI v2.0 — Linux launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/eli_isolate_env.sh"
eli_isolate_env "$SCRIPT_DIR"
VENV="$SCRIPT_DIR/.venv"
# GNOME/KDE often set QT_STYLE_OVERRIDE=adwaita — PySide6 only ships Fusion/Windows.
unset QT_STYLE_OVERRIDE 2>/dev/null || true

if [ ! -d "$VENV" ]; then
    echo "[ELI] Virtual environment not found. Run ./scripts/eli_setup.sh or bash install.sh first."
    exit 1
fi

exec "$VENV/bin/python" -m eli "$@"
