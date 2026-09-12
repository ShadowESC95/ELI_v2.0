#!/usr/bin/env bash
# ELI v2.0 — one-click setup (GUI wizard first on every machine with a display).
#
# Canonical entry for portable + source installs:
#   ./ELI_Setup.sh  /  ./INSTALL_ELI.sh  /  ./scripts/eli_setup.sh
#
# Hardware policy (same as install.sh --yes):
#   NVIDIA / AMD / Apple → GPU path
#   Intel Arc → Vulkan
#   Intel iGPU / ≤8 GB / no discrete GPU → CPU-only
# Override: ELI_INSTALL_CPU_ONLY=0|1
#
# The GUI wizard owns the single full install.sh run. This script only
# bootstraps a minimal .venv + PySide6 so the wizard can open.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
# shellcheck disable=SC1091
source "$ROOT/scripts/eli_isolate_env.sh"
eli_isolate_env "$ROOT"
# GNOME/KDE often set QT_STYLE_OVERRIDE=adwaita — PySide6 only ships Fusion/Windows.
unset QT_STYLE_OVERRIDE 2>/dev/null || true

cd "$ROOT"

# ── Hardware policy (Python is the source of truth) ───────────────────────────
# Falls back to CPU-only only if policy import fails before any tree is usable.
_eli_apply_hw_policy() {
  case "${ELI_INSTALL_CPU_ONLY:-}" in
    0|false|FALSE|no|NO|off|OFF)
      export ELI_INSTALL_CPU_ONLY=0
      return 0
      ;;
    1|true|TRUE|yes|YES|on|ON)
      export ELI_INSTALL_CPU_ONLY=1
      return 0
      ;;
  esac
  local _decision
  _decision="$(python3 -m eli.setup.hardware_policy 2>/dev/null || true)"
  if [ "$_decision" = "gpu" ]; then
    export ELI_INSTALL_CPU_ONLY=0
  else
    # "cpu" or empty/unavailable → safe default for laptops
    export ELI_INSTALL_CPU_ONLY=1
  fi
}
_eli_apply_hw_policy

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

_real_qt_ok() {
  _venv_python || return 1
  "$PY" -c "from eli.gui.qt_compat import real_qt_available; import sys; sys.exit(0 if real_qt_available() else 1)" 2>/dev/null
}

_install_complete() {
  _venv_python || return 1
  # Must import from THIS checkout's .venv — a foreign portable on PYTHONPATH
  # used to make setup claim "complete" while runtime still used the old tree.
  "$PY" -c "
import sys
from pathlib import Path
root = Path(r'$ROOT').resolve()
venv = root / '.venv'
import eli, llama_cpp, requests

def under(p, base):
    try:
        Path(p).resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False

eli_f = Path(eli.__file__).resolve()
llama_f = Path(llama_cpp.__file__).resolve()
if not under(eli_f, root):
    raise SystemExit('eli imported from outside this checkout: ' + str(eli_f))
if not under(llama_f, venv):
    raise SystemExit('llama_cpp imported from outside this .venv: ' + str(llama_f))
from llama_cpp import llama_cpp as _lc
_lc.llama_backend_init()
" 2>/dev/null
}

_gui_import_ok() {
  _real_qt_ok
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
  _qt_install_ok=0
  if [ -f "$ROOT/requirements-portable-bootstrap.txt" ]; then
    if "$PY" -m pip install "${PIP_WH_ARGS[@]}" -r "$ROOT/requirements-portable-bootstrap.txt"; then
      _qt_install_ok=1
    elif "$PY" -m pip install "${PIP_WH_ARGS[@]}" 'PySide6>=6.6.0'; then
      _qt_install_ok=1
    fi
  elif "$PY" -m pip install "${PIP_WH_ARGS[@]}" 'PySide6>=6.6.0'; then
    _qt_install_ok=1
  elif "$PY" -m pip install -e "$ROOT[gui]"; then
    _qt_install_ok=1
  fi
  if [ "$_qt_install_ok" -eq 0 ] && [ -t 1 ]; then
    echo "  [setup] PySide6 bootstrap failed for $($PY --version 2>&1)."
    if [ -d "$ROOT/wheelhouse" ]; then
      echo "  [setup] Bundled wheelhouse may lack wheels for this Python — install.sh will try next."
    else
      echo "  [setup] No wheelhouse/ in this package — install.sh needs network for PySide6."
    fi
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
    echo "  [setup] Opening one-click GUI installer (hardware-aware)…"
    echo "  [setup] ELI_INSTALL_CPU_ONLY=${ELI_INSTALL_CPU_ONLY}  log: $_log"
    echo "  [setup] The wizard runs install.sh once, then embedder / voice / model."
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

# ── Preferred path: GUI wizard owns the full install ──────────────────────────
if _gui_available; then
  if _try_gui_installer; then
    exit 0
  fi
  # Wizard failed but core may already be complete (e.g. assets-only retry left).
  if _install_complete && _real_qt_ok; then
    echo ""
    echo "  [OK] Core install complete. Launch ELI with: bash \"$ROOT/RUN_ELI.sh\""
    echo "  Tip: re-run ./ELI_Setup.sh to finish remaining assets in the wizard."
    exit 0
  fi
fi

# ── Terminal fallback (headless / no Qt / GUI wizard incomplete) ─────────────
if [ -t 1 ]; then
  B=$'\033[1m'; R=$'\033[0m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'
else
  B=; R=; GRN=; YEL=; CYN=
fi

echo
echo "${B}${CYN}ELI v2.0 setup (terminal mode)${R}"
echo "  GUI wizard did not finish — completing install in the terminal."
echo "  Hardware policy: ELI_INSTALL_CPU_ONLY=${ELI_INSTALL_CPU_ONLY}"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "${YEL}[!]${R} Python 3.10+ required."
  exit 1
fi

if ! _install_complete; then
  echo "  Installing core environment (install.sh) — llama_cpp + runtime deps…"
  # Hide dual-failure under set -e so we can print an actionable message.
  if [ "${ELI_INSTALL_CPU_ONLY:-0}" = "1" ]; then
    bash "$ROOT/install.sh" --yes --cpu-only --auto-model \
      || bash "$ROOT/install.sh" --yes --auto-model \
      || true
  else
    bash "$ROOT/install.sh" --yes --auto-model \
      || bash "$ROOT/install.sh" --yes --cpu-only --auto-model \
      || true
  fi
fi

if ! _install_complete; then
  echo "${YEL}[!]${R} Core install incomplete (need llama_cpp + requests in .venv)."
  echo "  Run: bash \"$ROOT/install.sh\" --yes"
  echo "  Or use the AppImage (no venv build): GitHub Releases → ELI_v2-*-x86_64.AppImage"
  exit 1
fi

if ! _real_qt_ok; then
  echo "${YEL}[!]${R} PySide6 is not installed for $($PY --version 2>&1)."
  echo "  Re-run with network: bash \"$ROOT/install.sh\" --yes"
  echo "  Or use the AppImage (no venv build): see GitHub Releases → ELI_v2-*-x86_64.AppImage"
  exit 1
fi

echo "  [OK] Launch ELI with: bash \"$ROOT/RUN_ELI.sh\""
exec "$PY" -m eli.setup --run-remaining
