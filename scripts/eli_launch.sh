#!/usr/bin/env bash
# ELI unified launcher — one entry point for every way to run ELI.
#
#   ./scripts/eli_launch.sh                 full ELI Pro DESKTOP app (GUI)  [default]
#   ./scripts/eli_launch.sh gui             same
#   ./scripts/eli_launch.sh serve [flags]   API + web-app SERVER (flags -> eli_serve.sh,
#                                           e.g. `serve --lan` for phone/tablet access)
#   ./scripts/eli_launch.sh both  [flags]   server in the background + the desktop app
#
# Everything runs locally on your hardware. See scripts/eli_serve.sh for server options.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/eli_isolate_env.sh"
eli_isolate_env "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "[eli] .venv not found — run ./scripts/eli_setup.sh or bash install.sh first."; exit 1; }

MODE="${1:-gui}"
[ $# -gt 0 ] && shift || true

case "$MODE" in
  gui|desktop|app)
    # Feedback for the ~20s first load (model warm-up) so the icon doesn't look dead.
    command -v notify-send >/dev/null 2>&1 && \
      notify-send "ELI v2.0" "Starting the desktop app… first load can take ~20s." 2>/dev/null || true
    cd "$ROOT"; exec "$PY" -m eli "$@" ;;
  serve|server|web)
    exec "$ROOT/scripts/eli_serve.sh" "$@" ;;
  both|all)
    "$ROOT/scripts/eli_serve.sh" "$@" &
    SERVE_PID=$!
    trap 'kill "$SERVE_PID" 2>/dev/null || true' EXIT
    echo "[eli] server started (pid $SERVE_PID); launching desktop app…"
    cd "$ROOT"; "$PY" -m eli ;;
  -h|--help)
    sed -n '2,10p' "$0"; exit 0 ;;
  *)
    echo "[eli] unknown mode: $MODE (use gui | serve | both)"; exit 2 ;;
esac
