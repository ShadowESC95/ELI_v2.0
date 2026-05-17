#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

SYSTEM_DEPS=0
if [[ "${1:-}" == "--system-deps" ]]; then
  SYSTEM_DEPS=1
fi

if [[ "$SYSTEM_DEPS" == "1" ]]; then
  if command -v apt >/dev/null 2>&1; then
    sudo apt update
    sudo apt install -y python3-venv python3-dev python3-pip v4l-utils x11-xserver-utils libgl1 libglib2.0-0 libxcb-xinerama0 libxkbcommon-x11-0
  else
    echo "[!] --system-deps only knows apt. Install camera/X11/Python dev packages manually."
  fi
fi

python3 -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install -U pip wheel setuptools
python -m pip install -r "$ROOT/requirements.txt"

echo
cat <<EOF
[+] ELI AR/avatar v5 environment ready.
    Root: $ROOT
    Activate: source "$VENV/bin/activate"

Recommended optional iris tracker:
    python -m pip install -r "$ROOT/requirements_optional_mediapipe.txt"

If mediapipe fails on your Python version, create the venv with Python 3.11 and rerun this installer.
EOF
