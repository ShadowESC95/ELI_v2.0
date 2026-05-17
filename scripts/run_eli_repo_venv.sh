#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
  echo "ELI launch failed: missing project venv at:"
  echo "  $ROOT/.venv"
  exit 1
fi

# Project-local Python environment.
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

# Portable repo-root resolution for redistributable builds.
export ELI_PROJECT_ROOT="$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Optional project environment flags are allowed,
# but model choice must remain picker-owned.
if [[ -f "$ROOT/.env.mkxi" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.env.mkxi"
fi

# Never allow stale shell vars to bypass the model picker.
unset ELI_GGUF_MODEL_PATH
unset ELI_MODEL_PATH
unset ELI_MODEL
unset GGUF_MODEL_PATH

# Normal ELI launch must always enter:
# model picker -> live model-specific hardware tuning -> load
exec python3 -m eli.gui.app --setup "$@"
