#!/usr/bin/env bash
# ELI MKXI v2.0 PRO startup entrypoint.
# Installs when needed, optionally restores GitHub model/voice assets, then launches ELI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_MKXI_v2.0_PRO}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.0}"
RUN_SETUP="auto"
RESTORE_ASSETS=0
TRACE=0
SAFE_MODE=0
LOG_TO_FILE=1
APP_ARGS=()

usage() {
  cat <<EOF_USAGE
Usage: scripts/eli_startup.sh [options] [-- ELI_ARGS...]

Options:
  --setup                 Force setup before launch.
  --no-setup              Do not run setup automatically.
  --with-github-assets    Restore model/voice assets from GitHub Release before launch.
  --repo OWNER/REPO       Asset repo. Default: $REPO
  --tag TAG               Asset release tag. Default: $TAG
  --trace                 Enable ELI_PIPELINE_TRACE=1.
  --safe-mode             Disable proactive/experimental startup hooks where supported.
  --no-log                Do not tee startup output to artifacts/startup/logs.
  -h, --help              Show help.

Examples:
  scripts/eli_startup.sh
  scripts/eli_startup.sh --setup --with-github-assets
  scripts/eli_startup.sh --trace -- --setup
EOF_USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --setup) RUN_SETUP="force" ;;
    --no-setup) RUN_SETUP="never" ;;
    --with-github-assets) RESTORE_ASSETS=1 ;;
    --repo)
      shift
      REPO="${1:?--repo requires OWNER/REPO}"
      ;;
    --tag)
      shift
      TAG="${1:?--tag requires a value}"
      ;;
    --trace) TRACE=1 ;;
    --safe-mode) SAFE_MODE=1 ;;
    --no-log) LOG_TO_FILE=0 ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      APP_ARGS+=("$@")
      break
      ;;
    *)
      APP_ARGS+=("$1")
      ;;
  esac
  shift
done

if [ "$TRACE" -eq 1 ]; then
  export ELI_PIPELINE_TRACE=1
fi
if [ "$SAFE_MODE" -eq 1 ]; then
  export ELI_SAFE_MODE=1
  export ELI_DISABLE_PROACTIVE=1
fi
export ELI_PROJECT_ROOT="$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"

need_setup=0
if [ "$RUN_SETUP" = "force" ]; then
  need_setup=1
elif [ "$RUN_SETUP" = "auto" ] && [ ! -x "$PY" ]; then
  need_setup=1
fi

if [ "$need_setup" -eq 1 ]; then
  echo "[startup] running setup"
  setup_args=(--no-desktop)
  if [ "$RESTORE_ASSETS" -eq 1 ]; then
    setup_args+=(--with-github-assets --repo "$REPO" --tag "$TAG")
  fi
  bash "$ROOT/scripts/eli_one_click_setup.sh" "${setup_args[@]}"
fi

if [ ! -x "$PY" ]; then
  echo "[startup] missing virtualenv python: $PY" >&2
  echo "[startup] run: bash scripts/eli_one_click_setup.sh" >&2
  exit 1
fi

if [ "$RESTORE_ASSETS" -eq 1 ] && [ "$need_setup" -eq 0 ]; then
  echo "[startup] restoring GitHub model/voice assets from $REPO@$TAG"
  "$PY" "$ROOT/scripts/restore_github_asset_files.py" --repo "$REPO" --tag "$TAG"
fi

if [ "$LOG_TO_FILE" -eq 1 ]; then
  LOG_DIR="$ROOT/artifacts/startup/logs"
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/eli_startup_$(date +%Y%m%d_%H%M%S).log"
  echo "[startup] log: $LOG_FILE"
  set +e
  "$PY" -m eli "${APP_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"
  status=${PIPESTATUS[0]}
  set -e
  exit "$status"
fi

exec "$PY" -m eli "${APP_ARGS[@]}"
