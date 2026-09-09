#!/usr/bin/env bash
# ELI v2.0 — one-click setup (GUI-first on every platform with a display).
# Falls back to terminal-only when no graphical session or Qt is unavailable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
export ELI_PROJECT_ROOT="$ROOT"
export ELI_DATA_DIR="${ELI_DATA_DIR:-$ROOT/artifacts}"
export ELI_CONFIG_DIR="${ELI_CONFIG_DIR:-$ROOT/config}"
export ELI_MODELS_DIR="${ELI_MODELS_DIR:-$ROOT/models}"
export ELI_CACHE_DIR="${ELI_CACHE_DIR:-$ROOT/cache}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT"

# Android / Termux — unified installer routes to headless profile (install_android.sh).
if python3 -c "from eli.setup.platform_profile import is_android_headless; import sys; sys.exit(0 if is_android_headless() else 1)" 2>/dev/null; then
  exec python3 -m eli.setup --full-install --launch
fi

_gui_available() {
  if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    return 0
  fi
  return 1
}

_try_gui_installer() {
  local _py=""
  local _log="$ROOT/artifacts/setup_gui.log"
  mkdir -p "$ROOT/artifacts"
  for _py in python3 python; do
    if command -v "$_py" >/dev/null 2>&1; then
      if "$_py" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>/dev/null; then
        if ! "$_py" -c "from eli.gui.qt_compat import QApplication" 2>/dev/null; then
          "$_py" -m pip install --user 'PySide6>=6.6.0' >>"$ROOT/artifacts/setup_gui_fallback.log" 2>&1 || true
        fi
        if [ -t 1 ]; then
          echo "  [setup] GUI installer running — live output below (also saved to $_log)"
          if "$_py" -m eli.setup --full-install --launch 2>&1 | tee -a "$_log"; then
            return 0
          fi
        elif "$_py" -m eli.setup --full-install --launch >>"$_log" 2>&1; then
          return 0
        fi
      fi
    fi
  done
  return 1
}

if _gui_available && _try_gui_installer; then
  exit 0
fi

# ── Terminal fallback (headless / no Qt) ─────────────────────────────────────
if [ -t 1 ]; then
  B=$'\033[1m'; R=$'\033[0m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'
else
  B=; R=; GRN=; YEL=; CYN=
fi

echo
echo "${B}${CYN}ELI v2.0 setup (terminal mode)${R}"
echo "  Graphical installer unavailable — running full install in the terminal."
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "${YEL}[!]${R} Python 3.10+ required."
  exit 1
fi

if [ ! -x "$PY" ]; then
  echo "  Installing core environment (install.sh)…"
  bash "$ROOT/install.sh" --yes --auto-model \
    || bash "$ROOT/install.sh" --yes --cpu-only --auto-model
fi

if [ ! -x "$PY" ]; then
  echo "${YEL}[!]${R} Virtual environment could not be created."
  exit 1
fi

exec "$PY" -m eli.setup --run-remaining --launch
