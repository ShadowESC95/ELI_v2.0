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

Spins up a llama.cpp OpenAI-compatible server for a GGUF, runs the official
academic tasks over it, tears the server down, writes results +a one-line entry
to the bake-off ledger (`artifacts/eval/benchmarks/lm_eval/bakeoff.jsonl`).

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
   Fair options: run them in **no-think mode** (`--model local-chat-completions
   --apply_chat_template --system_instruction "/no_think"`), or benchmark them via
   the promptfoo/ELI route (ELI strips `<think>` and grades with the local judge).
   The `gen` suite IS valid for non-thinking models (Qwen2.5, Mistral, …).

```bash
# fast: instruction-following + math on a candidate model
python tools/eval/benchmarks/run_lm_eval.py \
    --model models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --suite gen --limit 50

# anti-confabulation + commonsense (loglikelihood → needs the HF tokenizer,
# which the script maps automatically for known models)
python tools/eval/benchmarks/run_lm_eval.py \
    --model models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --suite mc --limit 100
```

Notes / gotchas (already handled by the script):
- lm-eval's `local-completions` needs a **HF tokenizer**; `_TOKENIZER_MAP` resolves
  it from the GGUF file name (override with `--tokenizer <hf-repo>`). Tiny download,
  cached offline after first use.
- `tokenized_requests=False` — send string prompts; `llama_cpp.server` returns 500
  on token-id arrays.
- `--gpu-layers` defaults to 20 (fits an 8 GB card for a 7B). Bump for smaller models.

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
# start a local judge server (any GGUF), then:
python -m llama_cpp.server --model ../../../models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --port 8080 &
npx promptfoo@latest eval && npx promptfoo@latest view
```
- Load a **standard dataset** through ELI by pointing `tests:` at a HuggingFace
  dataset or a CSV — see the commented `truthful_qa` example in
  `promptfooconfig.yaml` and `datasets/truthfulqa_sample.csv`.
- For fully-offline, model-free grading, prefer the in-house board
  (`tools/eval/run_eval.py`) — its `rubric`/`semantic_min` assertions already grade
  locally via ELI's own broker + nomic embedder, no server needed.

---

## 3. What you already have

- **In-house regression board** — `tools/eval/run_eval.py` (router + executor + engine,
  93 cases) with trend tracking in `artifacts/eval/history/trend.jsonl`.
- **Model-swap smoke** — `tools/eval/model_swap_smoke.py` ("did this model break anything?").
- **Runtime profiler / coverage** — `tools/eval/profile_runtime.py` (which actions/agents fire).
- **Test report** — `tools/run_test_report.py` → `artifacts/test_report.md`.

The benchmarks here add the **external, comparable** numbers on top of those
in-house signals.
