#!/usr/bin/env bash
# ELI MKXI — Linux / macOS installer
# Usage: bash install.sh [--cpu-only] [--skip-torch]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="${PYTHON:-python3}"
CPU_ONLY=0
SKIP_TORCH=0

for arg in "$@"; do
    case "$arg" in
        --cpu-only)   CPU_ONLY=1 ;;
        --skip-torch) SKIP_TORCH=1 ;;
    esac
done

echo "=============================="
echo "  ELI MKXI Installer"
echo "=============================="
echo ""

# Detect Python
if ! command -v "$PYTHON" &>/dev/null; then
    echo "[ERROR] Python 3.10+ required. Install from python.org."
    exit 1
fi
PY_VER=$("$PYTHON" -c "import sys; print(sys.version_info[:2])")
echo "[OK] Python: $("$PYTHON" --version)"

# Detect OS
OS="$(uname -s)"
echo "[OK] Platform: $OS"

# Create venv
if [ -d "$VENV" ]; then
    echo "[OK] Virtual environment already exists."
else
    echo "[..] Creating virtual environment..."
    "$PYTHON" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
PYTHON_VENV="$VENV/bin/python"

echo "[..] Upgrading pip..."
"$PIP" install --quiet --upgrade pip setuptools wheel

# Install PyTorch
if [ "$SKIP_TORCH" -eq 0 ]; then
    echo ""
    if [ "$CPU_ONLY" -eq 1 ]; then
        echo "[..] Installing PyTorch (CPU)..."
        "$PIP" install torch --index-url https://download.pytorch.org/whl/cpu --quiet
    elif [ "$OS" = "Darwin" ]; then
        echo "[..] Installing PyTorch (macOS / MPS)..."
        "$PIP" install torch torchvision torchaudio --quiet
    else
        echo "[..] Installing PyTorch (CUDA 12.1)..."
        "$PIP" install torch --index-url https://download.pytorch.org/whl/cu121 --quiet
    fi
fi

# Install llama-cpp-python
echo "[..] Installing llama-cpp-python..."
if [ "$OS" = "Darwin" ]; then
    echo "     (with Metal GPU acceleration)"
    CMAKE_ARGS="-DLLAMA_METAL=on" "$PIP" install llama-cpp-python --prefer-binary --quiet
elif [ "$CPU_ONLY" -eq 1 ]; then
    "$PIP" install llama-cpp-python --prefer-binary --quiet
else
    "$PIP" install llama-cpp-python --prefer-binary \
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121 --quiet
fi

# Install ELI MKXI wheel
echo "[..] Installing ELI MKXI..."
WHEEL=$(ls "$SCRIPT_DIR"/dist/eli_mkxi-*.whl 2>/dev/null | head -1)
if [ -n "$WHEEL" ]; then
    "$PIP" install "$WHEEL"[full] --quiet
else
    "$PIP" install -e "$SCRIPT_DIR"[full] --quiet
fi

# Install remaining runtime requirements
if [ "$OS" = "Darwin" ]; then
    REQ="$SCRIPT_DIR/requirements-macos.txt"
else
    REQ="$SCRIPT_DIR/requirements.txt"
fi

echo "[..] Installing remaining dependencies..."
"$PIP" install -r "$REQ" --quiet --ignore-installed

# Make launchers executable
chmod +x "$SCRIPT_DIR/eli.sh" 2>/dev/null || true

echo ""
echo "=============================="
echo "  Installation complete!"
echo "=============================="
echo ""
echo "Launch ELI with:"
echo "  ./eli.sh"
echo ""
echo "Models location: $SCRIPT_DIR/models/"
echo ""
