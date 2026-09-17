#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
  echo "ELI launch failed: missing project venv at:"
  echo "  $ROOT/.venv"
  exit 1
fi

# Same env isolation as the other launchers (eli_launch.sh / eli_serve.sh) —
# unsets stale ELI_DATA_DIR/CONFIG_DIR/MODELS_DIR/CACHE_DIR and strips other
# checkouts' .venv entries from PATH before this checkout's own venv activates.
# shellcheck source=scripts/eli_isolate_env.sh
# shellcheck disable=SC1091
source "$ROOT/scripts/eli_isolate_env.sh"
eli_isolate_env "$ROOT"

# Project-local Python environment.
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

# Optional project environment flags are allowed,
# but model choice must remain picker-owned.
if [[ -f "$ROOT/.env.eli_v2_0" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.env.eli_v2_0"
fi

# Never allow stale shell vars to bypass the model picker.
unset ELI_GGUF_MODEL_PATH
unset ELI_MODEL_PATH
unset ELI_MODEL
unset GGUF_MODEL_PATH

# Normal ELI launch must always enter:
# model picker -> live model-specific hardware tuning -> load
exec python3 -m eli.gui.app --setup "$@"
