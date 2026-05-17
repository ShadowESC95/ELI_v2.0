#!/usr/bin/env bash
# ELI MKXI — Linux launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "[ELI] Virtual environment not found. Run install.sh first."
    exit 1
fi

exec "$VENV/bin/python" -m eli "$@"
