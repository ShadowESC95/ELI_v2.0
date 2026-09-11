#!/usr/bin/env bash
# Compatibility alias → scripts/eli_setup.sh (unified GUI wizard).
# Prefer: ./ELI_Setup.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Honour legacy --cpu-only without re-implementing install logic.
for arg in "$@"; do
  case "$arg" in
    --cpu-only) export ELI_INSTALL_CPU_ONLY=1 ;;
  esac
done
exec bash "$ROOT/scripts/eli_setup.sh"
