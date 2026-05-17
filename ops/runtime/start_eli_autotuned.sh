#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="${ELI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$PROJECT" || exit 1

source .venv/bin/activate || true

mkdir -p artifacts ops/reports/startup

: "${ELI_CTX_FRACTION:=0.65}"
: "${ELI_TARGET_BATCH:=256}"

echo "[STARTUP] Running universal hardware optimizer..."
python3 -m eli.core.startup_hardware_optimizer \
  | tee "ops/reports/startup/hardware_profile_$(date +%Y%m%d_%H%M%S).json"

export ELI_N_CTX="$(jq -r '.n_ctx' artifacts/runtime_hardware_profile.json)"
export ELI_GGUF_N_CTX="$ELI_N_CTX"

export ELI_N_GPU_LAYERS="$(jq -r '.n_gpu_layers' artifacts/runtime_hardware_profile.json)"
export ELI_GGUF_N_GPU_LAYERS="$ELI_N_GPU_LAYERS"
export ELI_GPU_LAYERS="$ELI_N_GPU_LAYERS"

export ELI_BATCH_SIZE="$(jq -r '.batch_size' artifacts/runtime_hardware_profile.json)"
export ELI_N_BATCH="$ELI_BATCH_SIZE"
export ELI_GGUF_N_BATCH="$ELI_BATCH_SIZE"

export ELI_N_THREADS="$(jq -r '.n_threads' artifacts/runtime_hardware_profile.json)"
export ELI_MAX_TOKENS="$(jq -r '.max_tokens' artifacts/runtime_hardware_profile.json)"

echo "[STARTUP] Runtime authority:"
cat artifacts/runtime_hardware_profile.json | jq '{
  hostname,
  cpu,
  ram_total_gb,
  gpus,
  selected_gpu,
  model_path,
  model_size_gb,
  model_train_ctx,
  ctx_fraction,
  n_ctx,
  n_gpu_layers,
  batch_size,
  n_threads,
  max_tokens,
  reasoning
}'

echo "[STARTUP] Launching ELI..."
python3 eli/gui/eli_pro_audio_gui_MKI.py 2>&1 \
  | tee "ops/reports/startup/eli_autotuned_$(date +%Y%m%d_%H%M%S).log"
