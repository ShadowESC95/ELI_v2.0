# ELI eval & profiling

Local, offline, no-cloud-judge tooling for **measuring** ELI — both *behaviour*
(does it answer/route correctly?) and *runtime shape* (what actually executes?).
One shared driver (`eli_driver.py`) underlies everything.

```
tools/eval/
├── eli_driver.py        # shared core: route_only() + run_engine()
├── assertions.py        # deterministic checks
├── cases.yaml           # behavioural regression cases (seeded from real bugs)
├── run_eval.py          # ① behavioural board  (PASS/FAIL)
├── profile_runtime.py   # ② runtime-graph profiler (what executes / dead code)
└── promptfoo/           # ③ optional Node UI front-end
```

| Tool | Answers | Needs a model? | Speed |
|---|---|---|---|
| `run_eval.py` | "does ELI behave correctly?" | router cases no · engine cases yes | ms / model-speed |
| `profile_runtime.py` | "what does ELI actually run? what's dead?" | route/agents no · engine yes | seconds |
| `promptfoo/` | UI board + model A/B + diffs | yes | model-speed |

---

## Quick start

```bash
cd ~/Desktop/ELI_MKXI-main_MAY_NEWEST && source .venv/bin/activate

# ① behavioural board — routing regressions, no model (~60ms)
python tools/eval/run_eval.py

# ② runtime profiler — what the routing layer touches + action coverage (~12s)
python tools/eval/profile_runtime.py
```

Neither needs a model. Both have deeper modes that do (below).

---

## ① Behavioural eval — `run_eval.py`

Drives ELI's real pipeline and asserts on its **own telemetry** (action,
matched_by, grounding, response_mode, latency) + answer text.

```bash
python tools/eval/run_eval.py                    # router cases only (fast, no model)
python tools/eval/run_eval.py --smoke            # router board + a few quick engine sanity gens
python tools/eval/run_eval.py --target all       # + engine cases (needs a model)
python tools/eval/run_eval.py --target engine
python tools/eval/run_eval.py --filter media     # subset by case id
python tools/eval/run_eval.py --target all --json out.json
python tools/eval/run_eval.py --target all --history   # + trend + regressions (below)
python tools/eval/run_eval.py || echo "EVAL FAILED"   # non-zero exit → CI/pre-push
```

`--history` appends `artifacts/eval/history/<ts>.json` (full records) + one line to
`artifacts/eval/history/trend.jsonl` (ts · **model** · pass_rate · mean_latency ·
mean_grounding) and writes `artifacts/eval/regressions.json` (failed case ids). The
trend records the loaded model name, so swapping models and re-running gives a direct
quality/latency A-B over time. The nightly `eval` job runs with `--history`.

**Cases** live in `cases.yaml`. Each (`smoke: true` opts a case into `--smoke`):
```yaml
- id: next_track_real
  target: router            # router (fast, model-free) | engine (needs a model)
  prompt: "next track"
  network: on               # optional: force net state (non-persisting)
  smoke: true               # optional: include in the fast --smoke board
  assert:
    - {type: action_is, value: [NEXT_MEDIA, MEDIA_CONTROL]}
```
Assertion types (`assertions.py`): `contains`, `not_contains`, `regex`,
`action_is`, `action_not`, `matched_by`, `response_mode`, `grounding_min`,
`grounding_max`, `hedged`, `max_latency_s`, `arg_equals`/`arg_not_contains`/
`arg_empty` (router `args[key]`), and `rubric` (a **local** judge — ELI's own
model — scores the answer 0-1 against `value` criteria; passes `>= min`, default
0.7; soft-passes when no model is loaded so the model-free board still runs).

> **Add a case for every bug a log reveals.** The seeded set already guards this
> dev cycle's fixes (prose-not-media, bare-search, meta-question routing,
> no-confabulated-name, factual-offline-hedges, …). Engine cases **SKIP cleanly**
> if no model is loaded — the router board always runs.

---

## ② Runtime-graph profiler — `profile_runtime.py`

Replays **real turns** — `artifacts/conversations/*.json` (your stored sessions)
+ `cases.yaml` — through ELI under a `sys.settrace` line tracer (no external
dependency) and reports:

- **% of statement-lines hit** across `eli/` (denominator = AST statements)
- **per-module hot/cold heatmap**, ranked by line-hit count
- **which executor actions ever route** (action coverage vs the ~133 known)
- **which of the 14 bus agents ever fire** (agents/engine modes)
- **cold files** (0 lines hit) ranked by size → the precise cut/refactor list

```bash
# routing-layer graph: what route() touches + action coverage (fast, no model)
python tools/eval/profile_runtime.py

python tools/eval/profile_runtime.py --mode agents --limit 300   # + agent firing (offline)
python tools/eval/profile_runtime.py --mode engine --limit 20    # full pipeline (NEEDS a model, slow)
python tools/eval/profile_runtime.py --json profile.json
```

**Modes — read each per its mode:**
| `--mode` | Exercises | Needs model | Use for |
|---|---|---|---|
| `route` (default) | `router.route()` only | no | action coverage + routing-layer heatmap |
| `agents` | + `AgentBus.dispatch()` | no (offline) | which agents fire + memory/retrieval path |
| `engine` | full `CognitiveEngine.process()` | **yes** | the complete runtime graph incl. inference |

> The `route` heatmap shows the **routing layer** (so the executor/engine appear
> COLD — routing doesn't execute actions; that's correct). `engine` mode shows
> the full graph. `--limit N` caps turns (settrace adds overhead; engine mode is
> slow). Library stderr (embedder `init:` lines, agent logs) is normal — pipe
> through `grep -v` if you want a clean board.

**What you get:** "~10–20% hot path" becomes an exact number per mode, plus a
ranked list of cold files — the defensible input to the god-file refactor
(carve the hot parts out of the cold bulk) and to deleting genuinely dead code.

---

## ③ promptfoo (optional, Node)

```bash
cd tools/eval/promptfoo
npx promptfoo@latest eval      # runs cases through ELI via eli_provider.py
npx promptfoo@latest view      # web UI: pass/fail table + run diffs
```
Thin adapter over the same `eli_driver`. Keep any `llm-rubric` judge pointed at a
**local** model — never a cloud API.

---

## Comparing models ("is the 24B worth the latency?")

Set the model in `config/settings.json` (or via the GUI picker), then:
```bash
python tools/eval/run_eval.py --target all --json qwen7b.json     # 7B configured
# swap model in settings, then:
python tools/eval/run_eval.py --target all --json mistral24b.json
# diff: grounding · hedged · correctness · latency_s
```

---

## Recommended cadence
- **Every change:** `python tools/eval/run_eval.py` (router board, instant).
- **Before a refactor:** `profile_runtime.py --mode engine --limit N --json before.json`,
  refactor, re-run → confirm the hot path is unchanged and nothing newly broke.
- **New bug from a log:** add a `cases.yaml` case, fix, confirm green.

See also: `blueprints/eval_harness.md` (harness internals) and
`blueprints/operations.md` (why this exists).
```

## Model-swap smoke test

After swapping the GGUF model, run a one-command "did anything break" check
(loads the real engine; catches crashes, empty replies, and degenerate output
from a wrong chat template):

    python tools/eval/model_swap_smoke.py

Exit code is non-zero on any failure; skips cleanly (exit 0) if no model loads.
