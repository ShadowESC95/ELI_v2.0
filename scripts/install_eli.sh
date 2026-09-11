#!/usr/bin/env bash
# Compatibility alias → scripts/eli_setup.sh (unified GUI wizard).
# Prefer: ./ELI_Setup.sh
#
# Historical pip-only behaviour is removed — it skipped hardware scan and
# produced pin conflicts. There is no --legacy-pip escape hatch.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "[install_eli] Redirecting to the unified installer (eli_setup → GUI wizard)…"
exec bash "$ROOT/scripts/eli_setup.sh" "$@"
