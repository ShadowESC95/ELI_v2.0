#!/usr/bin/env bash
# ELI v2.0 — one-click grandparent setup.
# Chains every first-run stage, then opens the graphical wizard and launches ELI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_v2.0}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.1}"
TOTAL=8

if [ -t 1 ]; then
  B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'
  GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'
else
  B=; D=; R=; GRN=; YEL=; CYN=
fi

stage() {
  echo
  echo "${B}${CYN}━━━ Step $1/$TOTAL — $2 ━━━${R}"
}

zenity_info() {
  command -v zenity >/dev/null 2>&1 || return 0
  zenity --info --title="ELI Setup" --width=420 --text="$1" 2>/dev/null || true
}

zenity_error() {
  command -v zenity >/dev/null 2>&1 || return 0
  zenity --error --title="ELI Setup" --width=420 --text="$1" 2>/dev/null || true
}

cd "$ROOT"
export ELI_PROJECT_ROOT="$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

stage 1 "Welcome"
echo "  ELI v2.0 runs entirely on your computer — private, local, no cloud account."
echo "  This setup prepares everything automatically. It is safe to run more than once."
zenity_info "Welcome to ELI v2.0 setup.\n\nWe will install what ELI needs, download a starter model if missing, add app-menu icons, then open ELI."

stage 2 "Python check"
if ! command -v python3 >/dev/null 2>&1; then
  echo "${YEL}[!]${R} Python 3 is required. Install it from your software centre or python.org."
  zenity_error "Python 3 is required before ELI can install.\n\nInstall Python 3.10+ then run ELI Setup again."
  exit 1
fi
echo "  ${GRN}OK${R}  $(python3 --version 2>&1)"

stage 3 "Python environment + dependencies"
if [ ! -x "$PY" ]; then
  echo "  Installing ELI (this may take several minutes)…"
  bash "$ROOT/install.sh" --yes --auto-model || bash "$ROOT/install.sh" --yes
else
  echo "  ${GRN}OK${R}  Virtual environment already present."
fi
if [ ! -x "$PY" ]; then
  zenity_error "ELI could not create its Python environment.\n\nCheck the terminal output above, then try again."
  exit 1
fi

stage 4 "Starter model pack"
need_model=1
if "$PY" -c "from eli.setup.status import has_chat_model; raise SystemExit(0 if has_chat_model() else 1)" 2>/dev/null; then
  need_model=0
  echo "  ${GRN}OK${R}  Chat model already present."
fi
if [ "$need_model" -eq 1 ]; then
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo "  Restoring starter models from GitHub Release ($TAG)…"
    if "$PY" "$ROOT/scripts/restore_github_asset_files.py" --repo "$REPO" --tag "$TAG"; then
      echo "  ${GRN}OK${R}  GitHub asset restore finished."
    else
      echo "  ${YEL}[!]${R}  Asset restore failed — trying automatic model download…"
      "$PY" -m eli.core.model_download --auto || true
    fi
  else
    echo "  Downloading a starter model sized to your hardware…"
    "$PY" -m eli.core.model_download --auto || true
  fi
fi

stage 5 "Local database"
"$PY" -m eli.core.init_data
echo "  ${GRN}OK${R}  Database architecture ready."

stage 6 "Memory + voice"
echo "  Ensuring embedder + voice models…"
"$PY" -c "from eli.core.model_download import download_aux; download_aux(required_only=True)" 2>/dev/null || true
"$PY" -m eli.runtime.voice_assets 2>/dev/null || true
echo "  ${GRN}OK${R}  Support assets checked."

stage 7 "App menu icons"
bash "$ROOT/scripts/install_desktop_apps.sh"
echo "  ${GRN}OK${R}  Desktop launchers installed (ELI v2.0, ELI Server, ELI Setup)."

stage 8 "Finish — open setup wizard"
echo
echo "${B}${GRN}╔══════════════════════════════════════════════╗${R}"
echo "${B}${GRN}║  ELI v2.0 setup complete — launching wizard   ║${R}"
echo "${B}${GRN}╚══════════════════════════════════════════════╝${R}"
echo
echo "  Next: the setup window confirms everything and opens ELI."
echo "  Later: use the ${B}ELI v2.0${R} icon in your app menu."

if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  exec "$PY" -m eli.setup --run-remaining --launch
fi

echo "  No graphical session detected — run:  $PY -m eli"
exec "$PY" -m eli
