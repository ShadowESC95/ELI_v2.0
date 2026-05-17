#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

echo "=== ELI MKXI installer ==="
echo "Project: $ROOT"
echo "Python : $($PYTHON_BIN --version 2>&1)"

echo
echo "=== Creating virtual environment ==="
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo
echo "=== Activating virtual environment ==="
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo
echo "=== Upgrading pip tooling ==="
python -m pip install --upgrade pip setuptools wheel

echo
echo "=== Installing runtime requirements ==="
if [ ! -f requirements.txt ]; then
  echo "❌ Missing requirements.txt"
  exit 1
fi
python -m pip install -r requirements.txt

if [ -f requirements-learning.txt ]; then
  echo
  echo "=== Installing optional learning requirements ==="
  python -m pip install -r requirements-learning.txt
fi

echo
echo "=== Preparing launcher ==="
chmod +x "$ROOT/bin/elix" 2>/dev/null || true
chmod +x "$ROOT/bin/elix.real" 2>/dev/null || true

mkdir -p "$HOME/.local/bin"
ln -sfn "$ROOT/bin/elix" "$HOME/.local/bin/elix"

echo
echo "=== Installer complete ==="
echo "Run:"
echo "  cd \"$ROOT\""
echo "  source .venv/bin/activate"
echo "  elix"
