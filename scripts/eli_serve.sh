#!/usr/bin/env bash
# ELI API / web-app server launcher.
#
#   Safe by default: binds 127.0.0.1 (this machine only), tokenless — zero friction
#   for local use. Inference runs HERE on your hardware; nothing reaches the cloud.
#
#   --lan        expose to your local network so a phone/tablet browser can reach it.
#                Binds 0.0.0.0 AND requires an access token (auto-generated, printed
#                below with the exact URL to open on the device).
#   --port N     listen port (default 8081, or $ELI_API_PORT)
#   --token X    use a specific token instead of a generated one
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "[eli-serve] .venv not found — run install.sh first."; exit 1; }
export ELI_PROJECT_ROOT="$ROOT"
export ELI_DATA_DIR="${ELI_DATA_DIR:-$ROOT/artifacts}"
export ELI_CONFIG_DIR="${ELI_CONFIG_DIR:-$ROOT/config}"
export ELI_MODELS_DIR="${ELI_MODELS_DIR:-$ROOT/models}"
export ELI_CACHE_DIR="${ELI_CACHE_DIR:-$ROOT/cache}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

HOST="127.0.0.1"
PORT="${ELI_API_PORT:-8081}"
TOKEN="${ELI_API_TOKEN:-}"
LAN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --lan)        LAN=1 ;;
    --port)       PORT="$2"; shift ;;
    --port=*)     PORT="${1#*=}" ;;
    --token)      TOKEN="$2"; shift ;;
    --token=*)    TOKEN="${1#*=}" ;;
    -h|--help)    sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "[eli-serve] unknown arg: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

if [ "$LAN" -eq 1 ]; then
  HOST="0.0.0.0"
  [ -n "$TOKEN" ] || TOKEN="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(16))')"
  LANIP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$LANIP" ] || LANIP="$(ipconfig getifaddr en0 2>/dev/null || echo '<this-host-ip>')"
  echo "======================================================================"
  echo " ELI server — LAN mode (token-protected, still 100% local)"
  echo "   On a phone/tablet on the SAME network, open:"
  echo ""
  echo "     http://$LANIP:$PORT/#token=$TOKEN"
  echo ""
  echo "   The page stores the token; afterwards just http://$LANIP:$PORT/ works."
  echo "   Inference runs on THIS machine — nothing leaves it to any cloud."
  echo "======================================================================"
else
  echo "[eli-serve] local-only at http://127.0.0.1:$PORT/   (use --lan for phone access)"
fi

export ELI_API_HOST="$HOST" ELI_API_PORT="$PORT"
[ -n "$TOKEN" ] && export ELI_API_TOKEN="$TOKEN"
cd "$ROOT"
exec "$PY" -m api.server
