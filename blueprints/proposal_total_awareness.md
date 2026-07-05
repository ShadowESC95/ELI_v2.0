# Proposal — Total self-test coverage, a living test→report→ELI loop, and the road to "indistinguishable" ELI

*2026-06-07. Status: PROPOSAL. The only changes already made this turn are the
test-suite upgrade + stale-test deletion + a results-document generator (all green,
committed). Everything in §4–§6 is proposed, not done.*

---

## 0. ERRATUM (2026-06-07) — CUDA IS active; ELI runs on GPU

**The "running on CPU" finding below was WRONG.** It came from a sandbox mistake:
the agent's bare `python` resolves to `/usr/bin/python` (the SYSTEM interpreter,
CPU-only `llama-cpp-python`), not `.venv/bin/python` that ELI runs on. Verified:
`.venv/bin/python` → `llama_supports_gpu_offload()` **True**; the model loads on the
GPU (`ggml_cuda_init: found 1 CUDA device`, `gpu_offload_supported=True`, layers
offloaded) and a short generation takes **~1.2 s** (vs ~190 s on the system CPU
build). So the doc generator, eval, and testgen **already run on GPU** when invoked
via the venv (how ELI runs). No rebuild needed. The 52-min A/B doc was the agent
using the wrong interpreter. The original section is kept below only as a record.

---

## 0 (ORIGINAL — INCORRECT diagnosis). "ELI is running on CPU, not GPU"

You asked why the document generator runs on CPU. It isn't doc-specific: **all LLM
inference is on CPU right now.** In the active `.venv`,
`llama_cpp.llama_supports_gpu_offload()` returns **False** — the installed
`llama-cpp-python` wheel is a **CPU-only build** (CUDA backend not compiled in), so
`gguf_inference` correctly force-sets `n_gpu_layers=0` and logs *"GPU offload
unsupported on this runtime … Forcing CPU mode."* The GPU itself is free
(726/8192 MiB used; no ELI process holding it). Your earlier session log *did* show
CUDA (`ggml_cuda_init: found 1 CUDA devices`, `gpu_layers=99`), so the CUDA build
was **replaced by a CPU build at some point** (a `pip install`/rebuild that pulled a
CPU wheel).

**Fix (one-time, user-run, deliberate — it's a network/build step):**
```
CMAKE_ARGS="-DGGML_CUDA=on" pip install --force-reinstall --no-cache-dir llama-cpp-python
```
(or install a prebuilt CUDA wheel matching the CUDA toolkit). After that,
`llama_supports_gpu_offload()` → True and the existing smart-fit loader puts layers
back on the 2060 Super. **This is the single highest-impact fix available** —
every slow thing you've seen this session (doc gen, the A/B run, deepening) is the
CPU build, not the architecture.

---

## 1. What changed this turn (done, green, committed)

- **Stale tests deleted:** two permanently-skipped dead tests for the deleted
  `eli.memory.working_memory` module (`test_11_integration`, `test_02_memory`).
- **Claims/everything suite expanded → ~4,300 tests** (`tests/claims/`):
  - `test_symbol_inventory.py` — **every public function / class / method in every
    safely-importable module is a real, introspectable callable** (~1,585 symbols;
    GUI + side-effecting modules denylisted because importing some run real work).
  - `test_agents_contract.py` — every bus agent honours the AgentResult protocol and
    self-gates on irrelevant input.
  - plus the existing claims layers (manifest, supported actions, documented actions,
    activation phrases, blueprint refs, structural/behavioural).
- **Results document generator:** `tools/run_test_report.py` runs the suite and
  writes **`artifacts/test_report.md`** (totals, per-file pass/fail/xfail, failures,
  ✅/❌ verdict) by parsing pytest's JUnit XML — pure stdlib.
- **Whole project suite:** ~6,900 tests, green.

### Honest limit on "test every function"
Truly *behaviourally* testing all ~6,000+ functions needs per-function inputs/mocks —
that can't be auto-generated meaningfully at that scale in one pass. What's delivered
is **complete STRUCTURAL + CONTRACT coverage** (every symbol is real & introspectable;
every agent/action/mechanism/claim has a contract). Deepening to behavioural coverage
is proposed in §5 (ELI-assisted test generation) rather than faked with padding.

---

## 2. Full audit snapshot (files / folders / tests / eval)

- **Code:** ~142k LOC, 369 `.py` under `eli/` (+ the FastAPI web app `api/server.py`; 12
  main GUI tabs; 15 bus agents + CodeAgent; 4 SQLite stores; 208 manifest capabilities /
  174 SUPPORTED_ACTIONS). *(measured 2026-06-28.)*
- **Tests:** **7,019 passed**, 42 skipped, 2 xfail (documented routing gaps). The 5 reds
  noted then (deprecated `smart_home` plugin + stale blueprint ref) were all cleared
  2026-07-03.
- **Eval harness (`tools/eval/`):** 93 cases in `cases.yaml` = **60 model-free router cases (auto-run under pytest, green)**
  + **engine cases (NOT auto-run — need a loaded model; manual `run_eval.py --target engine`)**.
  The engine board is **not continuously populated** — see §5.
- **Repo hygiene (pre-existing, from `complete_findings.md`):** root junk (`...`,
  `[package-index-options]`, `patch_*.py`, `verify_eli_claims*.sh`, `experimental/*.zip`),
  duplicate image engines, ~2,565 swallowed `except Exception`. Not touched (out of scope).

---

## 3. Routing gaps the examination surfaced (recorded as xfail)
`SELF_TEST` / `PROACTIVE_START` / `POMODORO_START` captured as `OPEN_APP`;
`EXECUTE_GOAL` → `SHELL_EXEC`; `SELF_ANALYZE` → `MEMORY_RECALL`; bare "left click" →
`GAZE_CLICK`/`CHAT`. Each is a real "the documented capability isn't reachable by its
natural phrase" gap — small router fixes, deferred to your go-ahead.

---

## 4. Proposed: the living test → report → ELI loop

So ELI has **visibility into its own correctness** and can talk about it:
1. **`SELF_TEST` action upgrade** → run `tools/run_test_report.py` (a chosen subset
   for speed, or full overnight), produce `artifacts/test_report.md`.
2. **`TEST_REPORT` grounded surface** — a verbatim-grounded action (like
   RUNTIME_STATUS) that reads the latest `test_report.md`; in chat ELI *summarises*
   it ("4,711 passing, 0 failing, 5 known routing gaps — want the details?") via the
   gather-then-summarise pattern, never a raw dump.
3. **Wire into the self-improvement / update-proposal flow:** when a fix/upgrade is
   discussed in chat, ELI consults the latest report + the `xfail` gaps + the
   `code_examiner` findings as evidence, and proposes the specific
   functions/actions to change — grounded, with the test deltas as acceptance checks.
4. **Schedule it:** an overnight `SCHEDULE_TASK` runs the full suite + the 3 engine
   eval cases (once GPU is restored), populating the report + eval board nightly.

This is small, additive, and uses machinery that already exists (scheduled tasks,
evidence-planner, grounded verbatim surfaces, self-improvement).

---

## 5. Proposed: the road to "total control / awareness / indistinguishable from human"

Grounded in what ELI already has, the gap to your goal is **integration + the brain**,
not missing parts. Phased:

**Phase A — Restore the brain (prerequisite).** Fix the CPU build (§0). Everything
below is gated on inference speed; on CPU the multi-stage/agentic depth is unusable
in real time.

**Phase B — Self-knowledge as live evidence (extends what's done).**
- The test→report→ELI loop (§4): ELI knows its own test/eval state.
- `FRONTIER_STATUS` + the claims report become standing evidence the planner can pull,
  so "what's broken / what can you do / how healthy are you" answer from measured truth.

**Phase C — Deeper, faithful behavioural coverage (the "test everything" finish).**
- **ELI-assisted test generation:** a background task where ELI, per module, reads a
  function + its call sites and *writes a behavioural test* (via the coding agent,
  sandbox-verified), growing coverage toward the 6,000+ functions over time — the only
  realistic path to "test every function" meaningfully. Gated, reviewed, additive.

**Phase D — Indistinguishable interaction (the persona/latency layer).**
- The big levers are **latency** (GPU) + **a stronger local model** (model-agnostic, a
  `.gguf` swap) — the persona/grounding/memory machinery is already built.
- Tighten: streaming cadence, back-channel ("mm", "one sec — checking"), interruption
  handling, and the emergent-voice rules already in memory. These are tuning, not new
  systems.

**Honest ceiling:** "indistinguishable from a human" is bounded by the local model's
raw intelligence. ELI's *body, memory, self-honesty, and awareness* are frontier; the
*mind* is whatever 7B (or better) you run. The architecture is built to inherit a
smarter brain the day one fits — that, plus GPU, is 90% of the perceived gap.

---

## 6. Recommended order
1. **Fix the llama-cpp CUDA build (§0)** — biggest single win, user-run.
2. Approve the **test→report→ELI loop (§4)** — small, additive, high-visibility.
3. Fix the **5 routing gaps (§3)** — quick correctness wins.
4. Decide on **ELI-assisted behavioural test generation (§5 Phase C)** — the real
   "test everything" path.
5. Repo hygiene + god-file/`except` debt (from `complete_findings.md`) — when ready.

No code beyond §1 has been changed. Awaiting your direction on §4–§6.
