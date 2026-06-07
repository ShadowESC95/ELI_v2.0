#!/data/data/com.termux/files/usr/bin/bash
# ELI MKXI — Android / Termux installer (headless runtime, no GUI/CUDA).
# Usage (in Termux):  bash scripts/install_android.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "=================================="
echo "  ELI MKXI — Android / Termux setup"
echo "=================================="
echo ""
echo "Android runs the HEADLESS runtime only: no desktop GUI, no CUDA (CPU"
echo "inference), no global screen/mouse control. Use a small model (e.g. qwen2.5-3b)."
echo ""

# System packages Termux needs to build the Python deps + llama-cpp (CPU).
if command -v pkg &>/dev/null; then
    echo "[..] Installing Termux build packages..."
    pkg update -y || true
    pkg install -y python clang cmake git ninja libjpeg-turbo libpng rust binutils || \
        echo "[WARN] some pkg installs failed — continuing."
else
    echo "[WARN] 'pkg' not found — are you in Termux? Continuing with python only."
fi

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" &>/dev/null || PYTHON=python

echo "[..] Creating virtual environment..."
"$PYTHON" -m venv "$VENV"
PIP="$VENV/bin/pip"
PYV="$VENV/bin/python"

"$PIP" install --quiet --upgrade pip setuptools wheel

# CPU llama-cpp (Termux/arm64 — build from source via clang).
echo "[..] Installing llama-cpp-python (CPU, source build — may take a while)..."
"$PIP" install llama-cpp-python --quiet || \
    echo "[WARN] llama-cpp-python build failed — install build deps and retry."

# Android profile deps (no torch/PySide6/CUDA).
REQ="$SCRIPT_DIR/requirements-android.txt"
[ -f "$REQ" ] || REQ="$SCRIPT_DIR/requirements.txt"
echo "[..] Installing dependencies from $(basename "$REQ")..."
"$PIP" install -r "$REQ" --quiet || echo "[WARN] some deps failed (expected on Android)."

# Install ELI (no [full] extras — headless).
"$PIP" install -e "$SCRIPT_DIR" --quiet || "$PIP" install -e "$SCRIPT_DIR" --quiet --no-deps

# Seed offline config + data dirs/databases.
SETTINGS="$SCRIPT_DIR/config/settings.json"
TEMPLATE="$SCRIPT_DIR/config/templates/settings.template.json"
if [ ! -f "$SETTINGS" ] && [ -f "$TEMPLATE" ]; then
    mkdir -p "$SCRIPT_DIR/config"; cp "$TEMPLATE" "$SETTINGS"
fi
mkdir -p "$SCRIPT_DIR/models"
"$PYV" -c "from eli.core.paths import get_paths; get_paths()" 2>/dev/null && \
    echo "[OK] Data dirs ready." || echo "[WARN] data dir init deferred."

echo ""
echo "=================================="
echo "  Android setup complete."
echo "=================================="
echo "Get a small model:"
echo "  $PYV -m eli.core.model_download qwen2.5-3b   # ~2 GB (CPU-friendly)"
echo "Run headless:"
echo "  $PYV -m eli.cli.headless"
echo ""
