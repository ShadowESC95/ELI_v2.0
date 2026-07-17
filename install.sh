#!/usr/bin/env bash
# ELI v2.0 — Linux / macOS installer
# Usage: bash install.sh [--cpu-only] [--skip-torch]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="${PYTHON:-python3}"
export ELI_PROJECT_ROOT="$SCRIPT_DIR"
export ELI_DATA_DIR="${ELI_DATA_DIR:-$SCRIPT_DIR/artifacts}"
export ELI_CONFIG_DIR="${ELI_CONFIG_DIR:-$SCRIPT_DIR/config}"
export ELI_MODELS_DIR="${ELI_MODELS_DIR:-$SCRIPT_DIR/models}"
export ELI_CACHE_DIR="${ELI_CACHE_DIR:-$SCRIPT_DIR/cache}"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
CPU_ONLY=0
SKIP_TORCH=0
USE_LATEST=0     # default: install the frozen lock (reproducible). --latest = version ranges.
INSTALL_CUDA=0   # --install-cuda: best-effort install the CUDA toolkit (nvcc) for users
                 # who don't have it, then source-build llama-cpp with CUDA if needed.
ASSUME_YES=0     # --yes/-y: no prompts, use detected defaults (CI / piped installs)
FETCH_MODEL=""   # --model=KEY or --auto-model: download a model after install
NO_MODEL=0       # --no-model: never download a model
HAS_NVIDIA=0     # set by the system report below
HAS_AMD=0        # set by the system report below (AMD ROCm/HIP GPUs)

for arg in "$@"; do
    case "$arg" in
        --cpu-only)    CPU_ONLY=1 ;;
        --gpu)         CPU_ONLY=0 ;;
        --skip-torch)  SKIP_TORCH=1 ;;
        --latest)      USE_LATEST=1 ;;
        --install-cuda|--cuda) INSTALL_CUDA=1 ;;
        --yes|-y)      ASSUME_YES=1 ;;
        --auto-model|--auto) FETCH_MODEL="--auto" ;;
        --choose-model|--choose) FETCH_MODEL="--choose" ;;
        --model=*)     FETCH_MODEL="${arg#*=}" ;;
        --no-model)    NO_MODEL=1 ;;
    esac
done
[ -t 0 ] || ASSUME_YES=1   # not a TTY (piped install) → never block on prompts
# Non-interactive: VRAM-sized default chat model unless --no-model.
if [ "$ASSUME_YES" -eq 1 ] && [ "$NO_MODEL" -eq 0 ] && [ -z "$FETCH_MODEL" ]; then
    FETCH_MODEL="--auto"
fi

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
        if sudo -n true 2>/dev/null; then sudo pacman -S --noconfirm --needed cuda && return 0; fi
        echo "     Run: sudo pacman -S cuda"
    elif command -v zypper &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo zypper --non-interactive install cuda-toolkit && return 0; fi
        echo "     Run: sudo zypper install cuda-toolkit"
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
    # Package names differ per manager, and so do their contents:
    #   • Debian's tesseract-ocr pulls English data; Arch's tesseract and Fedora's
    #     ship NO language data, so OCR silently reads nothing without the -data/
    #     -langpack package.
    #   • grim + slurp are the Wayland screenshot path (os_controller uses them).
    #     Wayland is the default on Arch/Hyprland and modern GNOME, so without
    #     these, screenshots fail on a stock install.
    local APT="mpv playerctl wmctrl xdotool scrot grim slurp ffmpeg xclip wl-clipboard tesseract-ocr portaudio19-dev libnotify-bin"
    local DNF="mpv playerctl wmctrl xdotool scrot grim slurp ffmpeg xclip wl-clipboard tesseract tesseract-langpack-eng portaudio-devel libnotify"
    local PAC="mpv playerctl wmctrl xdotool scrot grim slurp ffmpeg xclip wl-clipboard tesseract tesseract-data-eng portaudio libnotify"
    local ZYP="mpv playerctl wmctrl xdotool scrot grim slurp ffmpeg xclip wl-clipboard tesseract-ocr tesseract-ocr-traineddata-english portaudio-devel libnotify-tools"
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
        # -S on an already-installed package is not an error, but --needed skips
        # the pointless reinstall on a rolling distro where most of this is present.
        if sudo -n true 2>/dev/null; then sudo pacman -S --noconfirm --needed $PAC 2>/dev/null && echo "[OK] runtime tools (pacman)"
        else echo "     Run: sudo pacman -S --needed $PAC"; fi
    elif command -v zypper &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo zypper --non-interactive install $ZYP 2>/dev/null && echo "[OK] runtime tools (zypper)"
        else echo "     Run: sudo zypper install $ZYP"; fi
    elif command -v apk &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo apk add $PAC 2>/dev/null && echo "[OK] runtime tools (apk)"
        else echo "     Run: sudo apk add $PAC"; fi
    elif command -v xbps-install &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo xbps-install -y $PAC 2>/dev/null && echo "[OK] runtime tools (xbps)"
        else echo "     Run: sudo xbps-install $PAC"; fi
    else
        echo "     Install (media + desktop control + OCR + audio): $APT"
    fi
    return 0
}

echo "${B}${CYN}╔══════════════════════════════════════════════╗${R}"
echo "${B}${CYN}║  ELI v2.0 · Installer                         ║${R}"
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
# AMD GPU (ROCm) — checked only when there's no NVIDIA + not macOS. rocminfo/rocm-smi or the
# /dev/kfd kernel node means a ROCm-capable AMD GPU is present.
if [ "$HAS_NVIDIA" -eq 0 ] && [ "$OS" != "Darwin" ]; then
    if command -v rocminfo &>/dev/null || command -v rocm-smi &>/dev/null || [ -e /dev/kfd ]; then
        _AGPU="$(rocm-smi --showproductname 2>/dev/null | grep -m1 -iE 'series|card' | sed 's/.*: *//' || true)"
        [ -z "$_AGPU" ] && _AGPU="$(lspci 2>/dev/null | grep -iE 'vga|display|3d' | grep -iE 'amd|radeon|advanced micro' | head -1 | sed 's/.*: //')"
        ok "GPU         ${B}${GRN}AMD ROCm${R}  ${D}${_AGPU:-detected}${R}"
        HAS_AMD=1
    fi
fi
if [ "$HAS_NVIDIA" -eq 0 ] && [ "$HAS_AMD" -eq 0 ]; then
    if [ "$OS" = "Darwin" ]; then ok "GPU         ${B}Apple Metal${R} ${D}(unified memory)${R}"
    else warn "GPU         none detected — ELI will run on ${B}CPU${R} (much slower)"; fi
fi

# Default the build to the hardware unless the user forced it. AMD boxes now get a ROCm build
# instead of being silently dropped to CPU.
if [ "$CPU_ONLY" -eq 0 ] && [ "$HAS_NVIDIA" -eq 0 ] && [ "$HAS_AMD" -eq 0 ] && [ "$OS" != "Darwin" ]; then
    CPU_ONLY=1
fi
if   [ "$CPU_ONLY" -eq 1 ]; then BUILD_LABEL="CPU-only"
elif [ "$OS" = "Darwin" ];  then BUILD_LABEL="GPU (Metal)"
elif [ "$HAS_AMD" -eq 1 ];  then BUILD_LABEL="GPU (AMD ROCm)"
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
        _m=""; read -r -p "  Choose model(s) to download now? [${B}Y${R}/n]  " _m || true
        # --choose opens a multi-select menu (pick any number, or 'auto'/'all'/'none').
        # Declining here skips only the (large) CHAT model — it must NOT set
        # NO_MODEL, or the tiny REQUIRED embedder (nomic, ~85 MB; memory/RAG can't
        # work without it) is skipped too. NO_MODEL stays reserved for the explicit
        # `--no-model` CLI flag (a deliberate fully-offline install).
        # Saying Y opens the full catalog picker (--choose); decline skips chat model only.
        case "${_m:-n}" in [Yy]*) FETCH_MODEL="--choose" ;; *) FETCH_MODEL="" ;; esac
    fi
fi

# Create venv. A venv is machine- and path-specific (its bin/ scripts hard-code an
# absolute python path in their shebang), so one copied from another machine — or from
# the build host, or left over in the extract folder — will "exist" but its python/pip
# cannot execute ("required file not found"). Validate it actually runs; rebuild if not.
_venv_ok() { [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import sys" >/dev/null 2>&1; }
if [ -d "$VENV" ] && _venv_ok; then
    echo "[OK] Virtual environment already exists."
else
    if [ -d "$VENV" ]; then
        echo "[..] Existing .venv is broken (built for a different machine/path) — rebuilding..."
        rm -rf "$VENV"
    else
        echo "[..] Creating virtual environment..."
    fi
    "$PYTHON" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
PYTHON_VENV="$VENV/bin/python"

echo "[..] Upgrading pip..."
# Use `python -m pip` (not the bin/pip shebang) so a freshly-repaired venv is used
# reliably even before pip's own launcher is regenerated.
"$PYTHON_VENV" -m pip install --quiet --upgrade pip wheel
# torch wheels currently require setuptools<82; cap before PyTorch install.
"$PIP" install --quiet 'setuptools>=68,<82'

# Optional bundled wheels (Windows portable always; Linux portable may include CPU torch fallback).
_WHEELHOUSE=""
for _wh in "$SCRIPT_DIR/wheelhouse" "$SCRIPT_DIR/dist/wheelhouse"; do
    if [ -d "$_wh" ] && compgen -G "$_wh/*.whl" > /dev/null 2>&1; then
        _WHEELHOUSE="$_wh"
        break
    fi
done
_PIP_LINKS=()
if [ -n "$_WHEELHOUSE" ]; then
    echo "[OK] Bundled wheelhouse: $_WHEELHOUSE"
    _PIP_LINKS=(--find-links "$_WHEELHOUSE" --prefer-binary)
fi

_pip_quiet() {
    "$PIP" install --quiet "${_PIP_LINKS[@]}" "$@" && return 0
    return 1
}

_install_pytorch_cpu() {
    _pip_quiet torch --index-url https://download.pytorch.org/whl/cpu \
        || _pip_quiet torch
}

_install_pytorch_cuda() {
    echo "[..] Installing PyTorch (CUDA 12.1)..."
    if _pip_quiet torch --index-url https://download.pytorch.org/whl/cu121; then
        return 0
    fi
    warn "CUDA PyTorch download failed (network/SSL/firewall on download.pytorch.org)."
    warn "Falling back to CPU PyTorch — ELI still installs; GPU torch can be retried later."
    if _install_pytorch_cpu; then
        CPU_ONLY=1
        return 0
    fi
    warn "PyTorch install failed — continuing without torch."
    SKIP_TORCH=1
    return 1
}

# Install PyTorch
if [ "$SKIP_TORCH" -eq 0 ]; then
    echo ""
    if [ "$CPU_ONLY" -eq 1 ]; then
        echo "[..] Installing PyTorch (CPU)..."
        _install_pytorch_cpu || { warn "CPU PyTorch failed — continuing without torch."; SKIP_TORCH=1; }
    elif [ "$OS" = "Darwin" ]; then
        echo "[..] Installing PyTorch (macOS / MPS)..."
        _pip_quiet torch torchvision torchaudio || _pip_quiet torch
    elif [ "$HAS_AMD" -eq 1 ]; then
        echo "[..] Installing PyTorch (AMD ROCm)..."
        _pip_quiet torch --index-url https://download.pytorch.org/whl/rocm6.2 || {
            warn "ROCm PyTorch wheel unavailable — falling back to CPU PyTorch."
            _install_pytorch_cpu; }
    else
        _install_pytorch_cuda || true
    fi
fi

# llama-cpp-python publishes wheels only for the interpreters its maintainers build
# for (currently up to ~3.12). A rolling distro defaults to whatever python is newest
# — Arch ships 3.14 — where pip finds NO wheel and quietly falls back to a SOURCE
# build. That build needs cmake + a C++ toolchain, which a bare Arch/Fedora install
# does not have, so it failed and (under `set -e`) took the whole installer with it:
# ELI's inference engine never installed and the app could not start at all. Ubuntu
# 24.04 ships 3.12, has a wheel, and never hit this. Detect it and provide the tools.
_llama_wheel_available() {
    "$PIP" install --only-binary=:all: --dry-run llama-cpp-python >/dev/null 2>&1
}

ensure_build_toolchain() {
    # pip's cmake/ninja wheels need no sudo and cover the build system; only the
    # C++ compiler has to come from the OS.
    "$PIP" install --quiet cmake ninja scikit-build-core 2>/dev/null || true
    if command -v c++ &>/dev/null || command -v g++ &>/dev/null || command -v clang++ &>/dev/null; then
        return 0
    fi
    echo "[..] Installing a C++ toolchain for the llama-cpp source build..."
    if [ "$OS" = "Darwin" ]; then
        xcode-select -p &>/dev/null || xcode-select --install 2>/dev/null || true
    elif command -v pacman &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo pacman -S --noconfirm --needed base-devel cmake git
        else warn "Run: sudo pacman -S --needed base-devel cmake git"; fi
    elif command -v apt-get &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo apt-get install -y build-essential cmake git
        else warn "Run: sudo apt-get install -y build-essential cmake git"; fi
    elif command -v dnf &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo dnf install -y gcc-c++ make cmake git
        else warn "Run: sudo dnf install -y gcc-c++ make cmake git"; fi
    elif command -v zypper &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo zypper --non-interactive install gcc-c++ make cmake git
        else warn "Run: sudo zypper install gcc-c++ make cmake git"; fi
    elif command -v apk &>/dev/null; then
        if sudo -n true 2>/dev/null; then sudo apk add build-base cmake git
        else warn "Run: sudo apk add build-base cmake git"; fi
    fi
}

# Install llama-cpp-python
echo "[..] Installing llama-cpp-python..."
if ! _llama_wheel_available; then
    warn "No prebuilt llama-cpp-python wheel for $("$PYTHON_VENV" -V 2>&1) — building from source."
    warn "This is normal on a rolling distro (Arch ships a newer python than upstream builds for)."
    warn "It takes several minutes. A python with a prebuilt wheel (3.10-3.12) installs instantly:"
    warn "  PYTHON=python3.12 bash install.sh"
    ensure_build_toolchain
fi
if [ "$OS" = "Darwin" ]; then
    echo "     (with Metal GPU acceleration)"
    CMAKE_ARGS="-DLLAMA_METAL=on" "$PIP" install llama-cpp-python --prefer-binary --quiet || true
elif [ "$CPU_ONLY" -eq 1 ]; then
    "$PIP" install llama-cpp-python --prefer-binary --quiet || true
elif [ "$HAS_AMD" -eq 1 ]; then
    echo "     (AMD — ROCm/hipBLAS, then Vulkan, then CPU)"
    if CMAKE_ARGS="-DGGML_HIPBLAS=on" "$PIP" install llama-cpp-python --no-cache-dir --quiet 2>/dev/null; then
        :
    elif CMAKE_ARGS="-DGGML_VULKAN=on" "$PIP" install llama-cpp-python --no-cache-dir --quiet 2>/dev/null; then
        echo "[OK] llama-cpp built with Vulkan (AMD GPU via Mesa/Vulkan)."
    else
        echo "[WARN] AMD GPU builds failed (ROCm toolkit or Vulkan dev libs missing)."
        echo "       Installing CPU build. For AMDGPU later:"
        echo "         ROCm:  CMAKE_ARGS=\"-DGGML_HIPBLAS=on\" \"$PIP\" install --force-reinstall --no-cache-dir llama-cpp-python"
        echo "         Vulkan: CMAKE_ARGS=\"-DGGML_VULKAN=on\" \"$PIP\" install --force-reinstall --no-cache-dir llama-cpp-python"
        "$PIP" install llama-cpp-python --prefer-binary --quiet
    fi
else
    "$PIP" install llama-cpp-python --prefer-binary \
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121 --quiet || true
fi

# llama-cpp IS the inference engine — without it ELI has no local model at all, so
# say precisely what went wrong instead of dying on a raw pip traceback.
if ! "$PYTHON_VENV" -c "import llama_cpp" 2>/dev/null; then
    warn "llama-cpp-python is NOT installed — ELI cannot run a local model yet."
    if ! _llama_wheel_available; then
        warn "Cause: no prebuilt wheel for $("$PYTHON_VENV" -V 2>&1), and the source build failed."
        warn "Fix (fastest): re-run with a python that has wheels —"
        warn "    PYTHON=python3.12 bash install.sh"
        warn "Fix (build here): install a toolchain, then re-run —"
        if command -v pacman &>/dev/null; then warn "    sudo pacman -S --needed base-devel cmake git"
        elif command -v dnf &>/dev/null; then warn "    sudo dnf install -y gcc-c++ make cmake git"
        elif command -v zypper &>/dev/null; then warn "    sudo zypper install gcc-c++ make cmake git"
        else warn "    sudo apt-get install -y build-essential cmake git"; fi
    else
        warn "A wheel exists for this python — re-run: \"$PIP\" install llama-cpp-python"
    fi
    VERIFY_LLAMA=0
else
    ok "llama-cpp-python ready ($("$PYTHON_VENV" -c 'import llama_cpp;print(llama_cpp.__version__)' 2>/dev/null))."
    VERIFY_LLAMA=1
fi

# Verify GPU offload actually compiled into llama-cpp (catch a silent CPU-only wheel —
# this is exactly the trap where ELI runs 30-50x slower without anyone noticing).
if [ "$SKIP_TORCH" -eq 0 ] && [ "$CPU_ONLY" -eq 0 ] && [ "$OS" != "Darwin" ]; then
    _GPU_KIND="$([ "$HAS_AMD" -eq 1 ] && echo ROCm || echo CUDA)"
    if "$PYTHON_VENV" -c "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" 2>/dev/null; then
        echo "[OK] llama-cpp-python has ${_GPU_KIND} GPU offload."
    elif [ "$HAS_AMD" -eq 1 ]; then
        echo "[WARN] llama-cpp is CPU-only — ROCm/Vulkan GPU builds did not compile."
        echo "       ELI runs on CPU for now. For AMD GPU offload:"
        echo "         ROCm:  CMAKE_ARGS=\"-DGGML_HIPBLAS=on\" \"$PIP\" install --force-reinstall --no-cache-dir llama-cpp-python"
        echo "         Vulkan: CMAKE_ARGS=\"-DGGML_VULKAN=on\" \"$PIP\" install --force-reinstall --no-cache-dir llama-cpp-python"
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

# Install ELI v2.0 wheel (or editable from source checkout)
# NOT --quiet: this step resolves the full dependency tree (torch, PySide6, faiss, …)
# and can take several minutes. Suppressing output made it look frozen, so users killed
# it here — before the requirements install below (which brings in PySide6) ever ran,
# leaving a GUI-less venv ("please install PySide6"). Show progress instead.
echo "[..] Installing ELI v2.0 (editable) — resolving dependencies, this can take a few minutes..."
WHEEL=""
# Pick the HIGHEST version wheel (sort -V), not the first — a plain glob returns the
# oldest first, which would install a stale version if several wheels are present.
WHEEL="$(ls "$SCRIPT_DIR"/dist/eli_v2_0-*.whl 2>/dev/null | sort -V | tail -1)"
# Install ELI EDITABLE from the source tree, so the tree is the SINGLE runtime authority
# (site-packages links to it — nothing shadows a duplicate wheel copy; the launchers'
# PYTHONPATH becomes redundant belt-and-suspenders). Fall back to the bundled wheel only
# if an editable install can't be created on this machine. The `|| true` keeps `set -e`
# from aborting the install if neither path succeeds — the pinned requirements install
# below is the real dependency gate and still runs.
if ! ( cd "$SCRIPT_DIR" && "$PIP" install -e ".[full]" ); then
    echo "[!] Editable install failed; falling back to the bundled wheel, then the pinned lock."
    { [ -n "$WHEEL" ] && "$PIP" install "${WHEEL}[full]"; } || true
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
# ${_PIP_LINKS[@]} points pip at the bundled wheelhouse (--find-links) when the release
# shipped one, so a full-wheelhouse build installs with zero network; otherwise it's empty.
#
# The frozen lock pins exact versions captured on ONE python/distro. A rolling distro
# (Arch) or any newer interpreter can lack a wheel for even one of those pins — and under
# `set -e` that aborted the whole install, so ELI simply would not install there. The lock
# is a reproducibility nicety, not a requirement: fall back to the version RANGES in
# requirements.txt, which resolve against whatever python the host actually ships.
if ! "$PIP" install "${_PIP_LINKS[@]}" -r "$REQ" --quiet --ignore-installed; then
    if [ "$REQ" != "$SCRIPT_DIR/requirements.txt" ] && [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        warn "Pinned install failed on $("$PYTHON_VENV" -V 2>&1) — some pins have no wheel for it."
        warn "Retrying with version ranges (requirements.txt) so the install completes."
        REQ="$SCRIPT_DIR/requirements.txt"
        "$PIP" install "${_PIP_LINKS[@]}" -r "$REQ" --ignore-installed \
            || warn "Some dependencies failed — ELI may be missing features. See the log above."
    else
        warn "Some dependencies failed to install — ELI may be missing features."
    fi
fi

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

# Local copy of the desktop icon under blueprints/ (PDF-only in git; icon lives in packaging/)
_ICON_SRC="$SCRIPT_DIR/packaging/desktop/Eli_Icon.png"
_ICON_DST="$SCRIPT_DIR/blueprints/Eli_Icon.png"
if [ -f "$_ICON_SRC" ]; then
    mkdir -p "$SCRIPT_DIR/blueprints"
    cp "$_ICON_SRC" "$_ICON_DST" 2>/dev/null || true
fi

# ── Runtime tools (media playback + desktop control) ─────────────────────────
attempt_runtime_tools || true

# ── Seed blank DB templates when artifacts/db is empty (schema-only, no personal data) ─
TEMPLATE_DB_DIR="$SCRIPT_DIR/config/templates/db"
ARTIFACT_DB_DIR="$SCRIPT_DIR/artifacts/db"
if [ -d "$TEMPLATE_DB_DIR" ]; then
    mkdir -p "$ARTIFACT_DB_DIR"
    if [ -z "$(find "$ARTIFACT_DB_DIR" -maxdepth 1 -name '*.sqlite3' -print -quit 2>/dev/null)" ]; then
        cp "$TEMPLATE_DB_DIR"/*.sqlite3 "$ARTIFACT_DB_DIR"/ 2>/dev/null || true
        if [ -n "$(find "$ARTIFACT_DB_DIR" -maxdepth 1 -name '*.sqlite3' -print -quit 2>/dev/null)" ]; then
            echo "[OK] Seeded blank database templates from config/templates/db/"
        fi
    fi
fi

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

# Capability manifest + command reference (idempotent — refreshes if code changed)
echo "[..] Ensuring capability manifest and command reference..."
if "$PYTHON_VENV" -c "from eli.tools.registry.capability_updater import update_capability_manifest; r=update_capability_manifest(); assert r.get('ok'), r; print(f\"[OK] {r.get('total',0)} capabilities indexed\")"; then
    :
    else
        if [ -f "$SCRIPT_DIR/capability_manifest.json" ]; then
            echo "[OK] Using shipped capability_manifest.json (regeneration skipped)."
        else
            echo "[WARN] Capability manifest missing — run: .venv/bin/python -m eli.tools.registry.capability_updater"
        fi
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
        EMB_PATH="$SCRIPT_DIR/models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
        if [ -f "$EMB_PATH" ]; then
            EMB_MB=$(du -m "$EMB_PATH" 2>/dev/null | awk '{print $1}')
            ok "Embedder ready at models/embeddings/ (${EMB_MB:-~80} MiB)."
        else
            ok "Embedder ready."
        fi
    else
        warn "Embedder fetch deferred — get it later with: python -m eli.core.model_download --aux"
    fi
fi

# Voice weights (browser voice + TTS): the faster-whisper STT model and a Piper
# voice. Required for web-server mic (phone/PC browser) — always fetch, not gated
# on chat-model download. Best-effort + idempotent — never fatal.
VOICE_STATUS="skipped"
info "Ensuring voice models (local STT + TTS, for browser/desktop voice) are present..."
if "$PYTHON_VENV" -m eli.runtime.voice_assets; then
    ok "Voice models ready."
    VOICE_STATUS="ready"
else
    warn "Voice models deferred — fetch later with: .venv/bin/python -m eli.runtime.voice_assets"
    VOICE_STATUS="deferred (fetch later)"
fi

echo
if [ "$VERIFY_OK" -eq 1 ]; then
    echo "${B}${GRN}╔══════════════════════════════════════════════╗${R}"
    echo "${B}${GRN}║  ELI v2.0 — installation complete             ║${R}"
    echo "${B}${GRN}╚══════════════════════════════════════════════╝${R}"
else
    echo "${B}${YEL}╔══════════════════════════════════════════════╗${R}"
    echo "${B}${YEL}║  ELI v2.0 — finished WITH ERRORS (see above)  ║${R}"
    echo "${B}${YEL}╚══════════════════════════════════════════════╝${R}"
fi

section "Summary"
ok "Build       ${B}llama-cpp ${BUILD_LABEL}${R}"
ok "Model       ${B}${MODEL_STATUS}${R}   ${D}(${SCRIPT_DIR}/models/)${R}"
ok "Voice       ${B}${VOICE_STATUS}${R}   ${D}(local STT + TTS weights)${R}"
ok "Data        ${B}fresh local databases${R}, offline-by-default"

section "Launch"
if [ "$OS" = "Linux" ] && [ -x "$PYTHON_VENV" ]; then
    info "Installing app-menu icons (ELI v2.0 + ELI Server)…"
    if bash "$SCRIPT_DIR/scripts/install_desktop_apps.sh"; then
        ok "Desktop launchers installed with ELI icon."
    else
        warn "Desktop icons deferred — run: ./scripts/install_desktop_apps.sh"
    fi
fi
echo "  ${B}./scripts/eli_setup.sh${R}               ${D}# first-time one-click setup (grandparent-ready)${R}"
echo "  ${B}./scripts/eli_launch.sh${R}              ${D}# desktop app (GUI)${R}"
echo "  ${B}./scripts/eli_launch.sh serve --lan --https${R}  ${D}# web app for phone / tablet (mic)${R}"
echo "  ${B}./eli.sh${R}                             ${D}# also launches the desktop app${R}"
echo "  ${B}./scripts/install_desktop_apps.sh${R}    ${D}# ELI Setup + ELI v2.0 + ELI Server icons${R}"
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
