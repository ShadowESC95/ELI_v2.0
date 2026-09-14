#!/usr/bin/env bash
# Install / refresh desktop launchers (Linux/macOS). Redistribution-safe:
# never embeds a versioned extract path in .desktop / .command files.
# One-click: ./scripts/install_desktop_apps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3 || echo python3)"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export ELI_PROJECT_ROOT="$ROOT"
export ELI_PRODUCT_LINE=v2
# Ensure launch scripts are executable even on fresh extracts.
chmod +x "$ROOT/scripts/eli_launch.sh" "$ROOT/scripts/eli_serve.sh" \
         "$ROOT/scripts/eli_setup.sh" "$ROOT/scripts/eli_term.sh" \
         "$ROOT/scripts/eli_uninstall.sh" 2>/dev/null || true

OS="$(uname -s)"
if [ "$OS" != "Linux" ] && [ "$OS" != "Darwin" ]; then
  echo "[eli] Windows: run  powershell -ExecutionPolicy Bypass -File scripts\\install_desktop_apps.ps1"
  exit 0
fi

exec "$PYTHON" -m eli.runtime.desktop_launchers install --root "$ROOT"
