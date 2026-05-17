#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase24_cuda_toolkit_llama_source_rebuild_${STAMP}"
mkdir -p "$OUT"

LOG="$OUT/FULL_CUDA_TOOLKIT_LLAMA_SOURCE_REBUILD.txt"

exec > >(tee "$LOG") 2>&1

echo "# Phase 24 — CUDA Toolkit + llama-cpp-python CUDA Source Rebuild"
echo "Generated: $(date -Is)"
echo "PWD: $ROOT"
echo

echo "=== 0. STOP ANY RUNNING ELI GUI / PYTHON FRONTENDS ==="
pkill -f "eli_pro_audio_gui_MKI.py" 2>/dev/null || true
pkill -f "run_eli_repo_venv.sh" 2>/dev/null || true
sleep 2
echo "ELI_PROCESS_STOP_PASS"
echo

echo "=== 1. HOST / VENV STATE ==="
which python3
python3 -V
echo "VIRTUAL_ENV=${VIRTUAL_ENV:-<unset>}"
echo

echo "=== 2. NVIDIA DRIVER VISIBILITY ==="
command -v nvidia-smi || true
nvidia-smi || true
echo

echo "=== 3. CURRENT CUDA COMPILER VISIBILITY ==="
if command -v nvcc >/dev/null 2>&1; then
  echo "NVCC_ALREADY_PRESENT=$(command -v nvcc)"
  nvcc --version || true
else
  echo "NVCC_MISSING"
fi
echo

echo "=== 4. BASE BUILD DEPENDENCIES ==="
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  cmake \
  ninja-build \
  pkg-config \
  python3-dev \
  python3-pip \
  wget \
  ca-certificates \
  gnupg \
  lsb-release
echo "BASE_BUILD_DEPS_OK"
echo

echo "=== 5. INSTALL CUDA TOOLKIT 13.2 ONLY IF NVCC IS MISSING ==="
if command -v nvcc >/dev/null 2>&1; then
  echo "SKIP_CUDA_TOOLKIT_INSTALL_NVCC_ALREADY_PRESENT"
else
  . /etc/os-release
  UBUNTU_ID="${ID:-}"
  UBUNTU_VERSION="${VERSION_ID:-}"

  if [ "$UBUNTU_ID" != "ubuntu" ]; then
    echo "FATAL: Expected Ubuntu. Found ID=$UBUNTU_ID VERSION_ID=$UBUNTU_VERSION"
    exit 1
  fi

  case "$UBUNTU_VERSION" in
    24.04)
      CUDA_REPO="ubuntu2404"
      ;;
    22.04)
      CUDA_REPO="ubuntu2204"
      ;;
    *)
      echo "FATAL: Unsupported Ubuntu version for this scripted CUDA repo path: $UBUNTU_VERSION"
      exit 1
      ;;
  esac

  echo "Detected Ubuntu $UBUNTU_VERSION -> CUDA repo $CUDA_REPO"

  KEYRING_DEB="$OUT/cuda-keyring_1.1-1_all.deb"
  KEYRING_URL="https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_REPO}/x86_64/cuda-keyring_1.1-1_all.deb"

  echo "Downloading CUDA keyring:"
  echo "$KEYRING_URL"
  wget -O "$KEYRING_DEB" "$KEYRING_URL"

  sudo dpkg -i "$KEYRING_DEB"
  sudo apt-get update

  echo "Installing cuda-toolkit-13-2..."
  sudo apt-get install -y cuda-toolkit-13-2
fi
echo

echo "=== 6. EXPORT CUDA ENVIRONMENT FOR THIS BUILD ==="
if [ -d /usr/local/cuda-13.2 ]; then
  export CUDA_HOME=/usr/local/cuda-13.2
  export PATH="$CUDA_HOME/bin:$PATH"
  export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
elif [ -d /usr/local/cuda ]; then
  export CUDA_HOME=/usr/local/cuda
  export PATH="$CUDA_HOME/bin:$PATH"
  export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
else
  echo "FATAL: CUDA install path not found under /usr/local/cuda-13.2 or /usr/local/cuda"
  exit 1
fi

echo "CUDA_HOME=$CUDA_HOME"
echo "PATH nvcc=$(command -v nvcc || true)"
nvcc --version
echo

echo "=== 7. BEFORE: CURRENT LLAMA GPU CAPABILITY ==="
python3 - <<'PY'
import llama_cpp
print("llama_cpp_version =", getattr(llama_cpp, "__version__", "<unknown>"))
print("gpu_offload =", llama_cpp.llama_supports_gpu_offload())
PY
echo

echo "=== 8. REMOVE CPU-ONLY LLAMA BUILD ==="
python3 -m pip uninstall -y llama-cpp-python || true

python3 - <<'PY'
from pathlib import Path
root = Path(".venv/lib")
removed = []
for p in root.rglob("*"):
    s = str(p)
    if (
        "/site-packages/llama_cpp" in s
        or "/site-packages/lib/libllama" in s
        or "/site-packages/lib/libggml" in s
    ):
        removed.append(p)

for p in sorted(removed, key=lambda x: len(str(x)), reverse=True):
    try:
        if p.is_dir():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    except Exception as exc:
        print("REMOVE_WARN", p, exc)

print("STALE_LLAMA_RELATED_PATHS_REMOVED =", len(removed))
PY
echo

echo "=== 9. BUILD llama-cpp-python==0.3.23 WITH CUDA ENABLED ==="
export FORCE_CMAKE=1
export CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75"

echo "FORCE_CMAKE=$FORCE_CMAKE"
echo "CMAKE_ARGS=$CMAKE_ARGS"
echo

python3 -m pip install \
  --upgrade \
  --force-reinstall \
  --no-cache-dir \
  --no-binary=:all: \
  "llama-cpp-python==0.3.23"

echo

echo "=== 10. AFTER: INSTALLED LLAMA PACKAGE ==="
python3 -m pip show llama-cpp-python || true
echo

echo "=== 11. DECISIVE GPU OFFLOAD CAPABILITY PROBE ==="
python3 - <<'PY'
import sys
import llama_cpp

ver = getattr(llama_cpp, "__version__", "<unknown>")
gpu = bool(llama_cpp.llama_supports_gpu_offload())

print("llama_cpp_version =", ver)
print("llama_supports_gpu_offload() =", gpu)
print("llama_supports_mmap() =", llama_cpp.llama_supports_mmap())
print("llama_supports_mlock() =", llama_cpp.llama_supports_mlock())
print("llama_max_devices() =", llama_cpp.llama_max_devices())

if not gpu:
    print("CUDA_SOURCE_REBUILD_FAILED_GPU_OFFLOAD_FALSE")
    sys.exit(2)

print("CUDA_SOURCE_REBUILD_GPU_OFFLOAD_TRUE")
PY
echo

echo "=== 12. CUDA / GGML SHARED LIBRARY INVENTORY ==="
find .venv/lib/python3.12/site-packages \
  \( -name 'libggml*' -o -name 'libllama*' \) \
  -type f \
  | sort \
  | tee "$OUT/12_llama_ggml_shared_libs.txt"

echo
echo "=== 13. CUDA SYMBOL / LINKAGE HITS ==="
while IFS= read -r lib; do
  [ -f "$lib" ] || continue
  echo
  echo "--- $lib ---"
  ldd "$lib" 2>/dev/null | rg -i 'cuda|cublas|cudart|nvrtc' || echo "No direct CUDA/CUBLAS ldd lines."
  strings "$lib" 2>/dev/null | rg -i 'ggml_cuda|cudaMalloc|cublas|cudart|nvrtc' | head -40 || echo "No CUDA symbol strings shown."
done < "$OUT/12_llama_ggml_shared_libs.txt"
echo

echo "=== 14. MINI MODEL LOAD CUDA SMOKE TEST ==="
python3 - <<'PY'
from pathlib import Path
import sys
from llama_cpp import Llama

candidates = [
    Path("models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"),
    Path("models/SmolLM2-1.7B-Instruct-Q4_K_M.gguf"),
    Path("models/ministral-3b-instruct-q4_k_m.gguf"),
]

model = next((p for p in candidates if p.exists()), None)
if model is None:
    print("CUDA_SMOKE_SKIPPED_NO_SMALL_GGUF_FOUND")
    sys.exit(0)

print("CUDA_SMOKE_MODEL =", model)
llm = Llama(
    model_path=str(model),
    n_ctx=512,
    n_batch=128,
    n_threads=6,
    n_gpu_layers=1,
    verbose=True,
)
print("CUDA_SMOKE_MODEL_LOAD_OK")
out = llm(
    "Reply with only: GPU smoke test OK",
    max_tokens=12,
    temperature=0.0,
)
print("CUDA_SMOKE_INFER_RESULT =", out["choices"][0]["text"].strip())
PY
echo

echo "=== 15. PIP CHECK ==="
python3 -m pip check
echo

echo "=== FINAL RESULT ==="
echo "CUDA_LLAMA_SOURCE_REBUILD_COMPLETE"
echo "Report directory: $OUT"
echo "Primary log: $LOG"
