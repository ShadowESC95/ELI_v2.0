#!/usr/bin/env bash
# Reproducible 3-way head-to-head: Qwen2.5-7B vs Qwen3.6-35B-A3B vs Qwen3-32B.
# IDENTICAL methodology for all three (the only fair way to compare):
#   chat endpoint + chat template, 0-shot, 3072-token budget (so the reasoning
#   models can finish <think> and still emit the answer), tasks ifeval + gsm8k,
#   20 items/task, per-question outputs logged (--log_samples), wall-time recorded.
# GPU layers differ ONLY because the models differ in size vs the 8 GB card; the
# benchmark itself is identical. Fastest model first so data lands progressively.
set -u
cd "$(dirname "$0")/../../.."
PY=.venv/bin/python

run () {  # $1 = model stem, $2 = gpu layers
  echo "######## $1  (gpu_layers=$2) ########  $(date -Iseconds)"
  $PY tools/eval/benchmarks/run_lm_eval.py \
    --model "models/$1.gguf" --name "$1" \
    --tasks ifeval,gsm8k --limit 20 \
    --chat --fewshot 0 --max-gen-toks 3072 \
    --gpu-layers "$2" --ctx 6144 --port 8200
  sleep 8
}

run Qwen2.5-7B-Instruct-Q4_K_M 99      # ~4.7 GB → fully on the 8 GB GPU
run Qwen3.6-35B-A3B-UD-Q4_K_M 8        # 21 GB MoE (3B active) → 8 layers GPU, rest CPU
run Qwen3-32B-Q4_K_M 6                 # ~19 GB dense → 6 layers GPU, rest CPU

echo "######## 3-WAY DONE ########  $(date -Iseconds)"
cat artifacts/eval/benchmarks/lm_eval/bakeoff.jsonl
