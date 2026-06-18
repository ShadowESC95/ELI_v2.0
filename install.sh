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
ASSUME_YES=0     # --yes/-y: no prompts, use detected defaults (CI / piped installs)
FETCH_MODEL=""   # --model=KEY or --auto-model: download a model after install
NO_MODEL=0       # --no-model: never download a model
HAS_NVIDIA=0     # set by the system report below

for arg in "$@"; do
    case "$arg" in
        --cpu-only)    CPU_ONLY=1 ;;
        --gpu)         CPU_ONLY=0 ;;
        --skip-torch)  SKIP_TORCH=1 ;;
        --latest)      USE_LATEST=1 ;;
        --install-cuda|--cuda) INSTALL_CUDA=1 ;;
        --yes|-y)      ASSUME_YES=1 ;;
        --auto-model)  FETCH_MODEL="--auto" ;;
        --model=*)     FETCH_MODEL="${arg#*=}" ;;
        --no-model)    NO_MODEL=1 ;;
    esac
done
[ -t 0 ] || ASSUME_YES=1   # not a TTY (piped install) → never block on prompts

# ── colours + log helpers (only when stdout is a terminal) ───────────────────
if [ -t 1 ]; then
    B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'
    GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'; REDC=$'\033[31m'; MAG=$'\033[35m'
else
    B=; D=; R=; GRN=; YEL=; CYN=; REDC=; MAG=
fi
ok(){   echo "${GRN}[OK]${R} $*"; }
info(){ echo "${CYN}[..]${R} $*"; }
warn(){ echo "${YEL}[WARN]${R} $*"; }
section(){ echo; echo "${B}${MAG}━━━ $* ━━━${R}"; }

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
    echo "[..] Installing runtime tools (media + desktop control + OCR + audio)..."
    "$PIP" install --quiet yt-dlp 2>/dev/null && echo "[OK] yt-dlp (venv)" \
        || echo "     pip install yt-dlp   (direct media playback)"
    # Per-manager package names differ. tesseract = OCR (screen reading); portaudio = mic
    # (voice input); ffmpeg = media + whisper; libnotify = notifications; xclip/wl-clipboard
    # = clipboard; mpv/playerctl = media; wmctrl/xdotool/scrot = desktop control + screenshot.
    local APT="mpv playerctl wmctrl xdotool scrot ffmpeg xclip wl-clipboard tesseract-ocr portaudio19-dev libnotify-bin"
    local DNF="mpv playerctl wmctrl xdotool scrot ffmpeg xclip wl-clipboard tesseract portaudio-devel libnotify"
    local PAC="mpv playerctl wmctrl xdotool scrot ffmpeg xclip wl-clipboard tesseract portaudio libnotify"
    local BREW="mpv playerctl ffmpeg tesseract portaudio"
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &>/dev/null; then brew install $BREW 2>/dev/null || true; echo "[OK] runtime tools (brew)"
        else echo "     brew install $BREW   (media + OCR + audio)"; fi
        return 0
    fi
    if command -v apt-get &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo apt-get install -y $APT 2>/dev/null && echo "[OK] runtime tools (apt)"
        else echo "     Run: sudo apt-get install -y $APT"; fi
    elif command -v dnf &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo dnf install -y $DNF 2>/dev/null && echo "[OK] runtime tools (dnf)"
        else echo "     Run: sudo dnf install -y $DNF"; fi
    elif command -v pacman &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo pacman -S --noconfirm $PAC 2>/dev/null && echo "[OK] runtime tools (pacman)"
        else echo "     Run: sudo pacman -S $PAC"; fi
    else
        echo "     Install (media + desktop control + OCR + audio): $APT"
    fi
    return 0
}

echo "${B}${CYN}╔══════════════════════════════════════════════╗${R}"
echo "${B}${CYN}║  ELI MKXI · Installer                         ║${R}"
echo "${B}${CYN}║  ${R}${D}100% local · private · offline-by-default${R}${B}${CYN}    ║${R}"
echo "${B}${CYN}╚══════════════════════════════════════════════╝${R}"

# Detect Python
if ! command -v "$PYTHON" &>/dev/null; then
    echo "${REDC}[ERROR]${R} Python 3.10+ required. Install from python.org."
    exit 1
fi
PY_VER=$("$PYTHON" -c "import sys; print(sys.version_info[:2])")
OS="$(uname -s)"

# ── System report — full info BEFORE we touch anything ───────────────────────
section "Your system"
ok "Python      ${B}$("$PYTHON" --version 2>&1)${R}"
ok "Platform    ${B}${OS}${R} ($(uname -m 2>/dev/null || echo '?'))"
if [ "$OS" = "Darwin" ]; then
    _CPUS="$(sysctl -n hw.ncpu 2>/dev/null || echo '?')"
    _RAMGB="$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))"
else
    _CPUS="$(nproc 2>/dev/null || echo '?')"
    _RAMGB="$(free -g 2>/dev/null | awk '/^Mem:/{print $2}')"
fi
ok "CPU         ${B}${_CPUS}${R} cores      RAM ${B}${_RAMGB:-?} GB${R}"
ok "Disk free   ${B}$(df -h "$SCRIPT_DIR" 2>/dev/null | awk 'NR==2{print $4}')${R}   ${D}(a model is ~2-5 GB)${R}"
if command -v nvidia-smi &>/dev/null; then
    _NGPU="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | grep -c . || echo 0)"
    if [ "${_NGPU:-0}" -ge 1 ]; then
        _GPU0="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
        _VRAMTOT="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | awk '{s+=$1} END{printf "%d", s}')"
        if [ "$_NGPU" -gt 1 ]; then
            ok "GPU         ${B}${GRN}${_NGPU}× ${_GPU0}${R}  (${_VRAMTOT} MiB total VRAM)   ${D}— scales to multi-GPU${R}"
        else
            ok "GPU         ${B}${GRN}${_GPU0}${R}  (${_VRAMTOT} MiB)"
        fi
        HAS_NVIDIA=1
    fi
fi
if [ "$HAS_NVIDIA" -eq 0 ]; then
    if [ "$OS" = "Darwin" ]; then ok "GPU         ${B}Apple Metal${R} ${D}(unified memory)${R}"
    else warn "GPU         none detected — ELI will run on ${B}CPU${R} (much slower)"; fi
fi

# Default the build to the hardware unless the user forced it.
if [ "$CPU_ONLY" -eq 0 ] && [ "$HAS_NVIDIA" -eq 0 ] && [ "$OS" != "Darwin" ]; then
    CPU_ONLY=1
fi
if   [ "$CPU_ONLY" -eq 1 ]; then BUILD_LABEL="CPU-only"
elif [ "$OS" = "Darwin" ];  then BUILD_LABEL="GPU (Metal)"
else                             BUILD_LABEL="GPU (CUDA)"; fi

# ── Plan — what is about to happen ───────────────────────────────────────────
section "Plan"
echo "  • llama-cpp build : ${B}${BUILD_LABEL}${R}"
echo "  • dependencies    : ${B}$([ "$USE_LATEST" -eq 1 ] && echo 'latest ranges' || echo 'frozen lock (reproducible)')${R}"
echo "  • a model         : ${B}$([ "$NO_MODEL" -eq 1 ] && echo 'skip (add one later)' || echo 'offered after install')${R}"
echo "  • data            : ${B}offline-by-default${R}, fresh local databases"

if [ "$ASSUME_YES" -eq 0 ]; then
    echo
    _ans=""; read -r -p "  Proceed? [${B}Y${R}/n]  " _ans || true
    case "${_ans:-Y}" in [Nn]*) echo "Aborted — nothing changed."; exit 0 ;; esac
    if [ "$NO_MODEL" -eq 0 ] && [ -z "$FETCH_MODEL" ]; then
        _m=""; read -r -p "  Download a model now, sized to your hardware? [${B}Y${R}/n]  " _m || true
        case "${_m:-Y}" in [Nn]*) NO_MODEL=1 ;; *) FETCH_MODEL="--auto" ;; esac
    fi
fi

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

# ── Initialise data directories + FULL database architecture (idempotent) ────
# Build EVERY store + table up front (user/agent/system_index/coding_memory) so a
# fresh install runs at full efficiency with nothing for the user to fix — yet it
# stays a true blank slate: schema only, ZERO personal memories/profile/history.
echo "[..] Initialising data directories and full database architecture..."
if "$PYTHON_VENV" -m eli.core.init_data; then
    echo "[OK] Full database architecture ready (blank slate — no personal data)."
else
    echo "[WARN] Some stores deferred to first launch (they self-build on first use)."
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

# ── Optional model download — the single online step (offline by default otherwise) ──
MODEL_STATUS="none yet"
if ls "$SCRIPT_DIR"/models/*.gguf >/dev/null 2>&1; then
    MODEL_STATUS="already present"
elif [ "$NO_MODEL" -eq 0 ] && [ -n "$FETCH_MODEL" ]; then
    section "Model download"
    info "Fetching a model (${FETCH_MODEL}) — the one online step, sized to your VRAM..."
    if "$PYTHON_VENV" -m eli.core.model_download $FETCH_MODEL; then
        MODEL_STATUS="downloaded"
    else
        warn "Model download failed — fetch later with: python -m eli.core.model_download --auto"
        MODEL_STATUS="download failed (fetch later)"
    fi
fi

# Required support model: the text embedder (memory/RAG/knowledge-graph). Tiny
# (~85 MB) and not optional, so fetch it whenever we're allowed online — even if a
# chat model was already present or skipped. (download_aux is idempotent.)
if [ "$NO_MODEL" -eq 0 ]; then
    info "Ensuring the text embedder (required for memory/RAG) is present..."
    if "$PYTHON_VENV" -m eli.core.model_download --aux; then
        ok "Embedder ready."
    else
        warn "Embedder fetch deferred — get it later with: python -m eli.core.model_download --aux"
    fi
fi

echo
if [ "$VERIFY_OK" -eq 1 ]; then
    echo "${B}${GRN}╔══════════════════════════════════════════════╗${R}"
    echo "${B}${GRN}║  ELI MKXI — installation complete             ║${R}"
    echo "${B}${GRN}╚══════════════════════════════════════════════╝${R}"
else
    echo "${B}${YEL}╔══════════════════════════════════════════════╗${R}"
    echo "${B}${YEL}║  ELI MKXI — finished WITH ERRORS (see above)  ║${R}"
    echo "${B}${YEL}╚══════════════════════════════════════════════╝${R}"
fi

section "Summary"
ok "Build       ${B}llama-cpp ${BUILD_LABEL}${R}"
ok "Model       ${B}${MODEL_STATUS}${R}   ${D}(${SCRIPT_DIR}/models/)${R}"
ok "Data        ${B}fresh local databases${R}, offline-by-default"

section "Launch"
echo "  ${B}./scripts/eli_launch.sh${R}              ${D}# desktop app (GUI)${R}"
echo "  ${B}./scripts/eli_launch.sh serve --lan${R}  ${D}# web app for phone / tablet${R}"
echo "  ${B}./eli.sh${R}                             ${D}# also launches the desktop app${R}"
echo "  ${B}./scripts/install_desktop_apps.sh${R}    ${D}# add ELI Pro + ELI Server to your app menu (Linux/macOS)${R}"
echo
if [ "$MODEL_STATUS" = "none yet" ] || [ "$MODEL_STATUS" = "download failed (fetch later)" ]; then
    echo "  ${D}No model yet — the first-run wizard offers a download, or run:${R}"
    echo "    ${B}.venv/bin/python -m eli.core.model_download --list${R}   ${D}# options${R}"
    echo "    ${B}.venv/bin/python -m eli.core.model_download --auto${R}   ${D}# by detected VRAM${R}"
    echo
fi
echo "${D}Tip: launch via the scripts / 'eli' command — not the GUI .py with system python.${R}"
echo "${D}ELI stays offline by default; model downloads are a deliberate one-time action.${R}"
echo
