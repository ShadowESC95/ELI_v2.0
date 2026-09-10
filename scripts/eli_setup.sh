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
# GNOME/KDE often set QT_STYLE_OVERRIDE=adwaita — PySide6 only ships Fusion/Windows.
unset QT_STYLE_OVERRIDE 2>/dev/null || true

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

_pip_wheelhouse_args() {
  PIP_WH_ARGS=()
  for _wh in "$ROOT/wheelhouse" "$ROOT/dist/wheelhouse"; do
    if [ -d "$_wh" ] && compgen -G "$_wh/*.whl" >/dev/null 2>&1; then
      PIP_WH_ARGS=(--find-links "$_wh" --prefer-binary)
      return 0
    fi
  done
  PIP_WH_ARGS=()
}

_venv_python() {
  if [ -x "$PY" ] && "$PY" -c "import sys" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

_gui_import_ok() {
  _venv_python || return 1
  "$PY" -c "from eli.gui.qt_compat import QApplication" >/dev/null 2>&1
}

_ensure_minimal_venv() {
  if ! _venv_python; then
    if [ -t 1 ]; then
      echo "  [setup] Creating virtual environment for the GUI installer…"
    fi
    python3 -m venv "$VENV"
  fi
}

_ensure_gui_in_venv() {
  _gui_import_ok && return 0
  _venv_python || return 1
  if [ -t 1 ]; then
    echo "  [setup] Installing GUI bindings into the project virtual environment…"
  fi
  _pip_wheelhouse_args
  "$PY" -m pip install --upgrade pip wheel >/dev/null 2>&1 || true
  if [ -f "$ROOT/requirements-portable-bootstrap.txt" ]; then
    "$PY" -m pip install "${PIP_WH_ARGS[@]}" -r "$ROOT/requirements-portable-bootstrap.txt" \
      || "$PY" -m pip install "${PIP_WH_ARGS[@]}" 'PySide6>=6.6.0' \
      || return 1
  else
    "$PY" -m pip install "${PIP_WH_ARGS[@]}" 'PySide6>=6.6.0' \
      || "$PY" -m pip install -e "$ROOT[gui]" \
      || return 1
  fi
  _gui_import_ok
}

_ensure_ready_for_gui() {
  _ensure_minimal_venv
  _ensure_gui_in_venv || return 1
}

_try_gui_installer() {
  local _log="$ROOT/artifacts/setup_gui.log"
  mkdir -p "$ROOT/artifacts"
  if ! _ensure_ready_for_gui; then
    return 1
  fi
  if [ -t 1 ]; then
    echo "  [setup] GUI installer — full install runs in the wizard below."
    echo "  [setup] Live output is mirrored here and saved to $_log"
    "$PY" -m eli.setup --full-install 2>&1 | tee -a "$_log"
    _code=${PIPESTATUS[0]}
    if [ "$_code" -eq 0 ]; then
      echo ""
      echo "  [OK] Setup complete. Launch ELI with: bash \"$ROOT/RUN_ELI.sh\""
      return 0
    fi
    return 1
  elif "$PY" -m eli.setup --full-install >>"$_log" 2>&1; then
    return 0
  fi
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

if ! _venv_python; then
  echo "  Installing core environment (install.sh)…"
  bash "$ROOT/install.sh" --yes --auto-model \
    || bash "$ROOT/install.sh" --yes --cpu-only --auto-model
fi

if ! _venv_python; then
  echo "${YEL}[!]${R} Virtual environment could not be created."
  exit 1
fi

echo "  [OK] Launch ELI with: bash \"$ROOT/RUN_ELI.sh\""
exec "$PY" -m eli.setup --run-remaining
