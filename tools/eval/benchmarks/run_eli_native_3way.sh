#!/usr/bin/env bash
# Overnight GSM8K head-to-head through ELI's OWN inference (the path that drives
# the Qwen3 thinking models correctly, where lm-eval/llama.cpp could not).
# Each model runs in its own process (loads → scores → exits, freeing GPU/RAM).
# Fastest first so data lands progressively. Results + per-question logs under
# artifacts/eval/benchmarks/eli_native/.
set -u
cd "$(dirname "$0")/../../.."
PY=.venv/bin/python

run () {  # $1 = gguf stem, $2 = label
  echo "######## $2 ########  $(date -Iseconds)"
  $PY tools/eval/benchmarks/run_eli_native.py \
    --model "models/$1.gguf" --name "$2" --limit 20 --max-tokens 4096
  sleep 10   # let the process fully release GPU/RAM before the next model loads
}

run DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M  R1-distill-1.5B   # small reasoning reference
run Qwen3.6-35B-A3B-UD-Q4_K_M             Qwen3-A3B          # MoE, ~3B active
run Qwen3-32B-Q4_K_M                       Qwen3-32B          # dense, the slow one

echo "######## 3-WAY DONE ########  $(date -Iseconds)"
cat artifacts/eval/benchmarks/eli_native/ledger.jsonl
