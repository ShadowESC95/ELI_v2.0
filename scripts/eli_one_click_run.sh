#!/usr/bin/env bash
# One-click launcher: install if needed, then run ELI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "[run] ELI environment missing; running one-click setup first."
  bash "$ROOT/scripts/eli_one_click_setup.sh" "$@"
fi

exec "$ROOT/eli.sh"
