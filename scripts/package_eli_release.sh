#!/usr/bin/env bash
# Build installable Python package artifacts for ELI MKXI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

echo "[package] Building wheel/sdist"
"$PYTHON" -m pip install --quiet --upgrade build wheel setuptools
"$PYTHON" -m build "$ROOT"

echo "[package] Build artifacts:"
ls -lh "$ROOT/dist" | sed -n '1,80p'

echo ""
echo "Install from wheel:"
echo "  python -m pip install dist/eli_mkxi-*.whl[full]"
