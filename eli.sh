#!/usr/bin/env bash
# ELI v2.0 — Linux launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
export ELI_PROJECT_ROOT="$SCRIPT_DIR"
export ELI_DATA_DIR="${ELI_DATA_DIR:-$SCRIPT_DIR/artifacts}"
export ELI_CONFIG_DIR="${ELI_CONFIG_DIR:-$SCRIPT_DIR/config}"
export ELI_MODELS_DIR="${ELI_MODELS_DIR:-$SCRIPT_DIR/models}"
export ELI_CACHE_DIR="${ELI_CACHE_DIR:-$SCRIPT_DIR/cache}"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [ ! -d "$VENV" ]; then
    echo "[ELI] Virtual environment not found. Run install.sh first."
    exit 1
fi

exec "$VENV/bin/python" -m eli "$@"
