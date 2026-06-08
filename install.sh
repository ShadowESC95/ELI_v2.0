#!/usr/bin/env bash
# ELI MKXI — Linux / macOS installer
# Usage: bash install.sh [--cpu-only] [--skip-torch]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="${PYTHON:-python3}"
CPU_ONLY=0
SKIP_TORCH=0
USE_LATEST=0     # default: install the frozen lock (reproducible). --latest = version ranges.
INSTALL_CUDA=0   # --install-cuda: best-effort install the CUDA toolkit (nvcc) for users
                 # who don't have it, then source-build llama-cpp with CUDA if needed.

for arg in "$@"; do
    case "$arg" in
        --cpu-only)    CPU_ONLY=1 ;;
        --skip-torch)  SKIP_TORCH=1 ;;
        --latest)      USE_LATEST=1 ;;
        --install-cuda|--cuda) INSTALL_CUDA=1 ;;
    esac
done

# Best-effort CUDA toolkit (nvcc) install — for non-technical users who have an NVIDIA
# GPU but no toolkit. Tries the no-sudo pip nvcc first, then the system package
# manager, then prints the exact manual step. Never fatal. (macOS has no CUDA → Metal.)
attempt_cuda_toolkit() {
    if command -v nvcc &>/dev/null; then
        echo "[OK] CUDA toolkit already present: $(nvcc --version 2>/dev/null | grep -i release || echo nvcc)"
        return 0
    fi
    if [ "$OS" = "Darwin" ]; then
        echo "[..] macOS uses Metal (no CUDA) — skipping CUDA toolkit."
        return 0
    fi
    echo "[..] Installing CUDA toolkit (nvcc)..."
    # 1) No-sudo: nvcc via pip, exposed through CUDACXX for the llama-cpp build.
    if "$PIP" install --quiet nvidia-cuda-nvcc-cu12 2>/dev/null; then
        local _nvcc
        _nvcc="$("$PYTHON_VENV" -c "import os,glob,nvidia;b=os.path.dirname(nvidia.__file__);m=glob.glob(b+'/cuda_nvcc/bin/nvcc');print(m[0] if m else '')" 2>/dev/null)"
        if [ -n "$_nvcc" ] && [ -x "$_nvcc" ]; then
            export CUDACXX="$_nvcc"; export PATH="$(dirname "$_nvcc"):$PATH"
            echo "[OK] nvcc installed via pip: $_nvcc"
            return 0
        fi
    fi
    # 2) System package manager (needs sudo; only if available non-interactively).
    if command -v apt-get &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo apt-get install -y nvidia-cuda-toolkit && return 0; fi
        echo "     Run: sudo apt-get install -y nvidia-cuda-toolkit"
    elif command -v dnf &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo dnf install -y cuda-toolkit && return 0; fi
        echo "     Run: sudo dnf install -y cuda-toolkit"
    elif command -v pacman &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo pacman -S --noconfirm cuda && return 0; fi
        echo "     Run: sudo pacman -S cuda"
    else
        echo "     Download the CUDA toolkit: https://developer.nvidia.com/cuda-downloads"
    fi
    return 1
}

attempt_runtime_tools() {
    # Desktop-control + media-playback tools ELI uses at runtime. Best-effort: uses
    # the system package manager when sudo is available, else prints the command.
    # yt-dlp goes in the venv (cross-distro) so "play X" can actually play audio
    # (mpv finds the venv's yt-dlp on PATH at runtime). Also installs the clipboard
    # backends (xclip / wl-clipboard) so GET_CLIPBOARD has a working fallback.
    echo "[..] Installing runtime tools (media playback + desktop control)..."
    "$PIP" install --quiet yt-dlp 2>/dev/null && echo "[OK] yt-dlp (venv)" \
        || echo "     pip install yt-dlp   (direct media playback)"
    local PKGS="mpv playerctl wmctrl xdotool ffmpeg xclip wl-clipboard"
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &>/dev/null; then brew install mpv playerctl 2>/dev/null || true
        else echo "     brew install mpv playerctl   (media playback)"; fi
        return 0
    fi
    if command -v apt-get &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo apt-get install -y $PKGS 2>/dev/null && echo "[OK] runtime tools (apt)"
        else echo "     Run: sudo apt-get install -y $PKGS"; fi
    elif command -v dnf &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo dnf install -y $PKGS 2>/dev/null && echo "[OK] runtime tools (dnf)"
        else echo "     Run: sudo dnf install -y $PKGS"; fi
    elif command -v pacman &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo pacman -S --noconfirm $PKGS 2>/dev/null && echo "[OK] runtime tools (pacman)"
        else echo "     Run: sudo pacman -S $PKGS"; fi
    else
        echo "     Install (for media + desktop control): $PKGS"
    fi
    return 0
}

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

# Verify GPU offload actually compiled into llama-cpp (catch a silent CPU-only wheel —
# this is exactly the trap where ELI runs 30-50x slower without anyone noticing).
if [ "$SKIP_TORCH" -eq 0 ] && [ "$CPU_ONLY" -eq 0 ] && [ "$OS" != "Darwin" ]; then
    if "$PYTHON_VENV" -c "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" 2>/dev/null; then
        echo "[OK] llama-cpp-python has CUDA GPU offload."
    elif [ "$INSTALL_CUDA" -eq 1 ]; then
        echo "[WARN] prebuilt llama-cpp is CPU-only — installing CUDA toolkit and rebuilding from source..."
        attempt_cuda_toolkit || true
        CUDACXX="${CUDACXX:-$(command -v nvcc || echo /usr/local/cuda/bin/nvcc)}" \
            CMAKE_ARGS="-DGGML_CUDA=on" "$PIP" install --force-reinstall --no-cache-dir llama-cpp-python --quiet || \
            echo "[WARN] CUDA source build failed — staying on CPU build."
        if "$PYTHON_VENV" -c "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" 2>/dev/null; then
            echo "[OK] llama-cpp-python rebuilt with CUDA GPU offload."
        else
            echo "[WARN] still CPU-only — check the CUDA toolkit/driver. ELI will run (slowly) on CPU."
        fi
    else
        echo "[WARN] llama-cpp-python installed as CPU-ONLY (no CUDA offload) — ELI will be slow."
        echo "       Re-run with --install-cuda to auto-install the CUDA toolkit + rebuild, or manually:"
        echo "         CUDACXX=\"\$(command -v nvcc || echo /usr/local/cuda/bin/nvcc)\" \\"
        echo "         CMAKE_ARGS=\"-DGGML_CUDA=on\" \"$PIP\" install --force-reinstall --no-cache-dir llama-cpp-python"
    fi
fi

# Install ELI MKXI wheel
echo "[..] Installing ELI MKXI..."
WHEEL=$(ls "$SCRIPT_DIR"/dist/eli_mkxi-*.whl 2>/dev/null | head -1)
if [ -n "$WHEEL" ]; then
    "$PIP" install "$WHEEL"[full] --quiet
else
    "$PIP" install -e "$SCRIPT_DIR"[full] --quiet
fi

# Install remaining runtime requirements. Default = the FROZEN LOCK (exact known-good
# versions captured from a working venv) for reproducible installs; --latest uses ranges.
if [ "$OS" = "Darwin" ]; then
    REQ="$SCRIPT_DIR/requirements-macos.txt"
elif [ "$USE_LATEST" -eq 0 ] && [ -f "$SCRIPT_DIR/requirements.lock.txt" ]; then
    REQ="$SCRIPT_DIR/requirements.lock.txt"
else
    REQ="$SCRIPT_DIR/requirements.txt"
fi

echo "[..] Installing dependencies from $(basename "$REQ")$([ "$REQ" = "$SCRIPT_DIR/requirements.lock.txt" ] && echo ' (frozen, reproducible)')..."
"$PIP" install -r "$REQ" --quiet --ignore-installed

# Make launchers executable
chmod +x "$SCRIPT_DIR/eli.sh" 2>/dev/null || true

# ── Seed a clean local config from the template (never overwrite) ─────────────
# A fresh clone has no config/settings.json (it is gitignored and per-user).
# Seed one from the clean template so first launch is offline-by-default with
# the setup wizard enabled. Existing config is left untouched.
SETTINGS="$SCRIPT_DIR/config/settings.json"
TEMPLATE="$SCRIPT_DIR/config/templates/settings.template.json"
if [ ! -f "$SETTINGS" ] && [ -f "$TEMPLATE" ]; then
    mkdir -p "$SCRIPT_DIR/config"
    cp "$TEMPLATE" "$SETTINGS"
    echo "[OK] Seeded clean config: config/settings.json (offline, wizard enabled)"
elif [ -f "$SETTINGS" ]; then
    echo "[OK] Existing config/settings.json kept."
fi

# Models dir exists so first-boot can drop/download a model into it.
mkdir -p "$SCRIPT_DIR/models"

# ── Runtime tools (media playback + desktop control) ─────────────────────────
attempt_runtime_tools || true

# ── Initialise data directories + databases (idempotent) ─────────────────────
# Create artifacts dirs and the SQLite stores so first launch is instant and the
# install is verifiably complete (not deferred to a possibly-failing first boot).
echo "[..] Initialising data directories and databases..."
if "$PYTHON_VENV" - <<'PYEOF'
from eli.core.paths import get_paths
get_paths()
try:
    import eli.memory as M
    if hasattr(M, "get_memory"):
        M.get_memory()
except Exception as e:
    print(f"   (memory init deferred: {e})")
print("   data dirs + databases ready")
PYEOF
then
    echo "[OK] Data directories and databases initialised."
else
    echo "[WARN] DB init deferred to first launch."
fi

# ── Verify the install actually imports and the entry point resolves ─────────
echo "[..] Verifying installation..."
VERIFY_OK=1
if ! "$PYTHON_VENV" -c "import eli" 2>/dev/null; then
    echo "[ERROR] 'import eli' failed in the venv — the package did not install."
    VERIFY_OK=0
fi
if ! "$PYTHON_VENV" -c "import eli.gui.app" 2>/dev/null; then
    echo "[WARN] GUI entry (eli.gui.app) not importable — GUI extras may be missing."
fi
if [ -x "$VENV/bin/eli" ]; then
    echo "[OK] 'eli' command installed at $VENV/bin/eli"
else
    echo "[WARN] 'eli' console script not found on the venv PATH."
fi

echo ""
echo "=============================="
if [ "$VERIFY_OK" -eq 1 ]; then
    echo "  Installation complete!"
else
    echo "  Installation finished WITH ERRORS — see above."
fi
echo "=============================="
echo ""
echo "Launch ELI (either works):"
echo "  ./eli.sh"
echo "  source .venv/bin/activate && eli"
echo ""
echo "NOTE: run ELI via the 'eli' command or ./eli.sh — do NOT run the GUI"
echo "      .py file directly with system python (that gives"
echo "      'ModuleNotFoundError: No module named eli' because the package"
echo "      lives in this project's .venv)."
echo ""
echo "First launch shows a setup wizard. With no model yet, you can download"
echo "one from the wizard, or fetch from the terminal:"
echo "  source .venv/bin/activate"
echo "  python -m eli.core.model_download --list      # see options"
echo "  python -m eli.core.model_download qwen2.5-7b  # ~4.7 GB (recommended)"
echo "  python -m eli.core.model_download --auto      # pick by detected VRAM"
echo ""
echo "Models location: $SCRIPT_DIR/models/"
echo "ELI stays offline by default; downloads are a deliberate one-time action."
echo ""
