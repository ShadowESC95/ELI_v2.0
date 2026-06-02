# ELI eval

Behavioural regression + grounding eval for ELI MKXI. Drives ELI's **real
pipeline** (router / engine) and asserts on its **own telemetry** — action,
matched_by, grounding_confidence, response_mode, latency — plus the answer text.
100% local, offline by default, no cloud judge.

One shared driver (`eli_driver.py`), two front-ends:

| Front-end | What it's for | Cost |
|-----------|---------------|------|
| **Pure-Python harness** (`run_eval.py`) | the canonical board; CI/pre-push; in-stack, zero extra deps | router cases = ms, engine cases = model speed |
| **promptfoo** (`promptfoo/`) | optional: web UI, easy A/B between models, run-over-run diffs | needs Node + a model |

## Pure-Python harness (start here)

```bash
# fast: routing regressions only, no model needed (~60ms)
python tools/eval/run_eval.py

# full: + engine cases (grounding / hedging / latency) — needs a model loaded
python tools/eval/run_eval.py --target all

python tools/eval/run_eval.py --filter media          # subset by id
python tools/eval/run_eval.py --target all --json out.json
```
Exit code is non-zero if any case fails — drop it in CI / a pre-push hook.

### Cases
`cases.yaml`. Each case:
```yaml
- id: next_track_real
  target: router          # router (fast, model-free) | engine (needs a model)
  prompt: "next track"
  network: on             # optional: force net state (non-persisting)
  assert:
    - {type: action_is, value: [NEXT_MEDIA, MEDIA_CONTROL]}
```
Assertion types (see `assertions.py`): `contains`, `not_contains`, `regex`,
`action_is`, `action_not`, `matched_by`, `response_mode`, `grounding_min`,
`grounding_max`, `hedged`, `max_latency_s`.

The seeded cases are real bugs that were fixed during development — they're
permanent guards (prose-not-media, bare-search, meta-question routing,
no-confabulated-name, factual-offline-hedges, …). **Add a case for every new
bug a log reveals** — that's how the board grows.

## promptfoo (optional)

```bash
cd tools/eval/promptfoo
npx promptfoo@latest eval      # runs cases through ELI via eli_provider.py
npx promptfoo@latest view      # web UI: pass/fail table + diffs
```
`eli_provider.py` is a thin adapter over the same `eli_driver`. To compare two
models, load each and add it as a second provider / run. Keep any `llm-rubric`
judge pointed at a **local** model — never a cloud API.

## Comparing models (the "is the 24B worth it?" question)
Load model A, run `--target all --json a.json`; swap to model B, `--json b.json`;
diff the boards. Watch `grounding`, `hedged`, factual correctness, and
`latency_s` — that's how "the 24B is/ isn't worth the CPU latency on this box"
becomes a number instead of a vibe.
```
