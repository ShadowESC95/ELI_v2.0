#!/usr/bin/env bash
# One-click launcher: delegate to the startup pipeline.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec "$ROOT/scripts/eli_startup.sh" "$@"
