#!/data/data/com.termux/files/usr/bin/bash
# ELI v2.0 — Android / Termux installer (headless runtime, no GUI/CUDA).
# Usage (in Termux):  bash scripts/install_android.sh
# Also invoked by: python -m eli.setup --full-install  (platform_profile routes here)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$SCRIPT_DIR/.venv"

eli_progress(){ echo "[ELI-PROGRESS] phase=$1 pct=$2 msg=${*:3}"; }

echo "=================================="
echo "  ELI v2.0 — Android / Termux setup"
echo "=================================="
echo ""
echo "Android runs the HEADLESS runtime only: no desktop GUI, no CUDA (CPU"
echo "inference), no global screen/mouse control. Use a small model (e.g. qwen2.5-3b)."
echo ""

eli_progress welcome 3 "Android headless profile"
eli_progress system 8 "Checking Termux environment"

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
eli_progress venv 14 "Creating virtual environment"
"$PYTHON" -m venv "$VENV"
PIP="$VENV/bin/pip"
PYV="$VENV/bin/python"

"$PIP" install --quiet --upgrade pip setuptools wheel

# CPU llama-cpp (Termux/arm64 — build from source via clang).
echo "[..] Installing llama-cpp-python (CPU, source build — may take a while)..."
eli_progress llama 35 "Building llama-cpp-python (CPU)"
"$PIP" install llama-cpp-python --quiet || \
    echo "[WARN] llama-cpp-python build failed — install build deps and retry."
eli_progress llama 55 "Inference engine ready"

# Android profile deps (no torch/PySide6/CUDA).
REQ="$SCRIPT_DIR/requirements-android.txt"
[ -f "$REQ" ] || REQ="$SCRIPT_DIR/requirements.txt"
echo "[..] Installing dependencies from $(basename "$REQ")..."
eli_progress eli 62 "Installing ELI headless dependencies"
"$PIP" install -r "$REQ" --quiet || echo "[WARN] some deps failed (expected on Android)."

# Install ELI (no [full] extras — headless).
eli_progress eli 70 "Installing ELI core package"
"$PIP" install -e "$SCRIPT_DIR" --quiet || "$PIP" install -e "$SCRIPT_DIR" --quiet --no-deps

# Seed offline config + data dirs/databases.
SETTINGS="$SCRIPT_DIR/config/settings.json"
TEMPLATE="$SCRIPT_DIR/config/templates/settings.template.json"
if [ ! -f "$SETTINGS" ] && [ -f "$TEMPLATE" ]; then
    mkdir -p "$SCRIPT_DIR/config"; cp "$TEMPLATE" "$SETTINGS"
fi
mkdir -p "$SCRIPT_DIR/models"
echo "[..] Initialising full database architecture (blank slate)..."
eli_progress database 78 "Initialising local databases"
if "$PYV" -m eli.core.init_data; then
    echo "[OK] Full database architecture ready (no personal data)."
else
    echo "[WARN] Some stores deferred to first launch."
fi

eli_progress finish 100 "Android headless setup complete"
echo ""
echo "=================================="
echo "  Android setup complete."
echo "=================================="
echo "Get a small model:"
echo "  $PYV -m eli.core.model_download qwen2.5-3b   # ~2 GB (CPU-friendly)"
echo "Run headless:"
echo "  $PYV -m eli.cli.headless"
echo ""
