# Benchmarking ELI

Two *different* things can be benchmarked, and they answer different questions.
Don't conflate them.

| Layer | What it measures | Tool | Folder |
|---|---|---|---|
| **Model** | the raw GGUF's capability ceiling (knowledge, reasoning, truthfulness) | **lm-evaluation-harness** | `tools/eval/benchmarks/` (this dir) |
| **Assistant** | ELI's *delivered* behaviour on top of a model (routing, grounding, tool use, no-confabulation) | **promptfoo** + the in-house board | `tools/eval/promptfoo/`, `tools/eval/run_eval.py` |

Everything here is **100% local** — no cloud judge, no API. Results land under
`artifacts/eval/benchmarks/`.

---

## 1. Model benchmarks — `run_lm_eval.py` (lm-evaluation-harness)

Spins up a llama.cpp OpenAI-compatible server (`llama_cpp.server`) for a GGUF, runs
the official academic tasks over it, tears the server down, and writes results
(`artifacts/eval/benchmarks/lm_eval/<model>/`) + a one-line entry to the bake-off
ledger (`artifacts/eval/benchmarks/lm_eval/bakeoff.jsonl`).

ELI-aligned task suites (`--suite`):

| suite | tasks | scoring | maps to |
|---|---|---|---|
| `gen` *(default)* | `ifeval`, `gsm8k` | generation | instruction-following, multi-step reasoning |
| `mc` | `truthfulqa_mc2`, `arc_easy`, `hellaswag` | loglikelihood | **anti-confabulation** (ELI's core goal), commonsense |
| `knowledge` | `mmlu` | loglikelihood | broad knowledge (large — use `--limit`) |

### ⚠️ Two backend limitations (verified 2026-06-12) — read before trusting numbers
1. **Loglikelihood suites (`mc`, `knowledge`) do NOT work over `llama_cpp.server`.**
   That server returns broken echo/prompt-logprobs (it ranks " Berlin" above
   " Paris" for the capital of France), so loglikelihood scoring is garbage (~0
   acc). The runner **refuses** these suites unless `ELI_BENCH_ALLOW_LOGLIKELIHOOD=1`.
   To run them properly you need a backend with correct prompt logprobs (the
   compiled `llama.cpp` `llama-server`, or a transformers/`hf` backend — which
   needs the model in HF format and dequantises to fp, infeasible for 32B here).
   For truthfulness, prefer the **promptfoo + ELI** route (generation + local judge).
2. **`gen` under-measures reasoning/"think" models (Qwen3: A3B, 32B).** Their
   `<think>` output trips the few-shot stop-sequences before the answer is
   emitted (e.g. Qwen3-A3B "scored" 0/20 on GSM8K — an artifact, not capability).
   Fair options: run them through the chat endpoint with the runner's `--chat`
   (chat template, turn-boundary stops, a 2048-token generation budget unless
   `--max-gen-toks` says otherwise), adding `--no-think` (the `/no_think` system
   instruction) to switch Qwen3's reasoning off; score GSM8K through ELI's own
   inference with `run_eli_native.py` (§3); or benchmark them via the promptfoo/ELI
   route (ELI strips `<think>` and grades with the local judge).
   The `gen` suite IS valid for non-thinking models (Qwen2.5, Mistral, …).

```bash
# fast: instruction-following + math on a candidate model
python tools/eval/benchmarks/run_lm_eval.py \
    --model models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --suite gen --limit 50

# anti-confabulation + commonsense (loglikelihood: refused unless you override it,
# and over llama_cpp.server the scores are not meaningful — limitation 1 above)
ELI_BENCH_ALLOW_LOGLIKELIHOOD=1 python tools/eval/benchmarks/run_lm_eval.py \
    --model models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --suite mc --limit 100
```

Notes / gotchas (already handled by the script):
- lm-eval's `local-completions` needs a **HF tokenizer** for every suite;
  `_TOKENIZER_MAP` resolves it from the GGUF file name (override with
  `--tokenizer <hf-repo>`), and a model it does not know stops with an error until
  you pass one. Tiny download, cached offline after first use.
- `tokenized_requests=False` — send string prompts; `llama_cpp.server` returns 500
  on token-id arrays.
- `--gpu-layers` defaults to 20 (or `ELI_BENCH_GPU_LAYERS`); set it to what your card
  holds. `--ctx` defaults to 4096.
- The server listens on `--port`, default 8081 — the port ELI's web server uses, so
  pick another while that is running.
- `--tasks` overrides the suite with an explicit lm-eval task list, `--limit` caps
  examples per task, `--fewshot` overrides the task's shot count, `--name` labels the run.

### The model bake-off (pick a model for redistribution)
Run the same suite across candidates and compare the ledger:
```bash
for m in SmolLM2-1.7B-Instruct-Q4_K_M Qwen2.5-3B-Instruct-Q4_K_M \
         Qwen2.5-7B-Instruct-Q4_K_M mistral-7b-instruct-v0.2.Q3_K_M; do
  python tools/eval/benchmarks/run_lm_eval.py --model models/$m.gguf --suite gen --limit 50
done
cat artifacts/eval/benchmarks/lm_eval/bakeoff.jsonl   # one line per model
```
This is the objective, data-driven way to decide whether a fast 7B holds enough
quality to retire the slow 35B-A3B on modest hardware.

---

## 2. Assistant benchmarks — promptfoo (`tools/eval/promptfoo/`)

`eli_provider.py` runs each prompt through ELI's **real** route→ground→execute
pipeline and returns the answer + metadata (action / grounding / response_mode),
so you assert on behaviour, not just text. Model-graded (`llm-rubric`) asserts use
a **local** judge.

```bash
cd tools/eval/promptfoo
# start a local judge server (any GGUF):
python -m llama_cpp.server --model ../../../models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --port 8080 &
# uncomment the judge `provider` block under `defaultTest` in promptfooconfig.yaml
# (it points at http://localhost:8080/v1), then:
npx promptfoo@latest eval && npx promptfoo@latest view
```
- Load a **standard dataset** through ELI by pointing `tests:` at a HuggingFace
  dataset or a CSV — `promptfooconfig.benchmark.yaml` runs
  `datasets/truthfulqa_sample.csv` and carries the commented
  `huggingface://datasets/truthful_qa` line for the full set
  (`npx promptfoo@latest eval -c promptfooconfig.benchmark.yaml`).
- For fully-offline grading without a judge server, prefer the in-house board
  (`tools/eval/run_eval.py`) — its `rubric` (ELI's own loaded model, through the
  broker) and `semantic_min` (the local nomic embedder) assertions grade locally.

---

## 3. Head-to-head runs and dossiers

- `run_eli_native.py` — scores GSM8K through ELI's **own** inference (`gguf_inference`,
  with its chat-template detection and `<think>` handling) instead of lm-eval over
  `llama_cpp.server`, which cannot drive the Qwen3 thinking GGUFs. Writes
  `artifacts/eval/benchmarks/eli_native/<name>.result.json` (+ `.samples.jsonl`),
  incrementally.
- `run_3way.sh` / `run_eli_native_3way.sh` — fixed three-model runs of the two
  harnesses, with one methodology for all three.
- `build_dossier.py`, `build_dossier_native.py`, `build_head2head.py` — turn those
  results into reports with charts, written into `blueprints/`
  (`model_bakeoff_dossier.md`, `top2_head2head.md`).

## 4. What you already have

- **In-house regression board** — `tools/eval/run_eval.py` (router + executor + engine,
  93 cases) with trend tracking in `artifacts/eval/history/trend.jsonl`.
- **Model-swap smoke** — `tools/eval/model_swap_smoke.py` ("did this model break anything?").
- **Memory benchmark** — `tools/eval/memory_bench.py` (model-free, temporary database).
- **Runtime profiler / coverage** — `tools/eval/profile_runtime.py` (which actions/agents fire).
- **Test report** — `tools/run_test_report.py` → `artifacts/test_report.md`.

The benchmarks here add the **external, comparable** numbers on top of those
in-house signals.
