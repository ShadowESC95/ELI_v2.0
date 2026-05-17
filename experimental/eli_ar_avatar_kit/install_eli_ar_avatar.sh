#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
SYSTEM_DEPS=0
WITH_MEDIAPIPE=0
RECREATE=0

for arg in "$@"; do
  case "$arg" in
    --system-deps) SYSTEM_DEPS=1 ;;
    --with-mediapipe|--gaze) WITH_MEDIAPIPE=1 ;;
    --recreate) RECREATE=1 ;;
    *) echo "[!] Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$SYSTEM_DEPS" == "1" ]]; then
  if command -v apt >/dev/null 2>&1; then
    sudo apt update
    sudo apt install -y python3-venv python3-dev python3-pip v4l-utils x11-xserver-utils libgl1 libglib2.0-0 libxcb-xinerama0 libxkbcommon-x11-0 fonts-dejavu-core
  else
    echo "[!] --system-deps only knows apt. Install camera/X11/Python dev packages manually."
  fi
fi

if [[ "$RECREATE" == "1" ]]; then
  rm -rf "$VENV"
fi

python3 -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install -U pip wheel setuptools
python -m pip install --force-reinstall -r "$ROOT/requirements.txt"

if [[ "$WITH_MEDIAPIPE" == "1" ]]; then
  echo "[+] Installing MediaPipe iris tracker..."
  python -m pip uninstall -y mediapipe >/dev/null 2>&1 || true
  python -m pip install --force-reinstall -r "$ROOT/requirements_optional_mediapipe.txt"
fi

echo
cat <<EOF2
[+] ELI AR/avatar v5.2 environment ready.
    Root: $ROOT
    Activate: source "$VENV/bin/activate"

For desktop gaze control, MediaPipe must be active:
    ./install_eli_ar_avatar.sh --with-mediapipe
    python scripts/eli_gaze_verify_tracker.py --camera auto

If tracker verification still reports opencv_haar_fallback, run the pinned reinstall block in README.md.
EOF2
