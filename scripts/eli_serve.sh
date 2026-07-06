#!/usr/bin/env bash
# ELI API / web-app server launcher.
#
#   Safe by default: binds 127.0.0.1 (this machine only), tokenless — zero friction
#   for local use. Inference runs HERE on your hardware; nothing reaches the cloud.
#
#   --lan        expose to your local network so a phone/tablet browser can reach it.
#                Binds 0.0.0.0 AND requires an access token (auto-generated, printed
#                below with the exact URL to open on the device).
#   --https      also serve HTTPS on port 8443 — required for phone microphone
#                (browsers block getUserMedia on plain http://LAN-IP).
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
# Default port: explicit env wins, else the user's saved api_port setting, else 8081.
PORT="${ELI_API_PORT:-$("$PY" -c 'from eli.runtime.server_util import effective_api_port; print(effective_api_port())' 2>/dev/null || echo 8081)}"
TOKEN="${ELI_API_TOKEN:-}"
LAN=0
HTTPS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --lan)        LAN=1 ;;
    --https)      HTTPS=1 ;;
    --port)       PORT="$2"; shift ;;
    --port=*)     PORT="${1#*=}" ;;
    --token)      TOKEN="$2"; shift ;;
    --token=*)    TOKEN="${1#*=}" ;;
    -h|--help)
      sed -n '2,13p' "$0"
      echo "  --https      enable HTTPS voice port (phone mic over LAN)"
      exit 0
      ;;
    *) echo "[eli-serve] unknown arg: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

SERVER_ARGS=()
[ "$LAN" -eq 1 ] && SERVER_ARGS+=(--lan)
[ "$HTTPS" -eq 1 ] && SERVER_ARGS+=(--https)
[ -n "$TOKEN" ] && SERVER_ARGS+=(--token "$TOKEN")
SERVER_ARGS+=(--port "$PORT")

if [ "$LAN" -eq 1 ]; then
  HOST="0.0.0.0"
  LANIP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$LANIP" ] || LANIP="$(ipconfig getifaddr en0 2>/dev/null || echo '<this-host-ip>')"
  echo "======================================================================"
  echo " ELI server — LAN mode (token-protected, still 100% local)"
  echo "   On a phone/tablet on the SAME network, open:"
  echo ""
  echo "     http://$LANIP:$PORT/"
  echo ""
  if [ "$HTTPS" -eq 1 ]; then
    echo "   Phone microphone (voice) — HTTPS:"
    echo "     https://$LANIP:8443/"
    echo "   (accept the one-time self-signed cert warning on the phone)"
  else
    echo "   Tip: add --https to enable the phone microphone (voice)."
  fi
  echo "   Token URL is printed below once the server starts."
  echo "   Inference runs on THIS machine — nothing leaves it to any cloud."
  echo "======================================================================"
else
  echo "[eli-serve] local-only at http://127.0.0.1:$PORT/   (use --lan for phone access)"
fi

export ELI_API_HOST="$HOST" ELI_API_PORT="$PORT"
[ -n "$TOKEN" ] && export ELI_API_TOKEN="$TOKEN"
[ "$HTTPS" -eq 1 ] && export ELI_API_HTTPS=1
cd "$ROOT"

# Web mic + TTS need whisper/piper on disk; offline mode blocks huggingface.co mid-request.
_need_voice=0
if ! "$PY" -c "from eli.perception.local_whisper_stt import whisper_cache_ready; import sys; sys.exit(0 if whisper_cache_ready() else 1)" 2>/dev/null; then
  _need_voice=1
fi
if ! "$PY" -c "from eli.runtime.voice_assets import piper_voice_ready; import sys; sys.exit(0 if piper_voice_ready() else 1)" 2>/dev/null; then
  _need_voice=1
fi
if [ "$_need_voice" -eq 1 ]; then
  echo "[eli-serve] Voice models not cached — fetching once (brief network via netguard)…"
  if ! "$PY" -m eli.runtime.voice_assets; then
    echo "[eli-serve] WARN: Voice may fail until you run: $PY -m eli.runtime.voice_assets"
  fi
fi

exec "$PY" -m api.server "${SERVER_ARGS[@]}"
