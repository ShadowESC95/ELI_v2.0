# ELI Coding Agent (`eli/coding/`)

A self-contained, **additive** subsystem that lifts ELI's code generation,
analysis, and repair to frontier-grade. It touches nothing that already works:
it lives in its own package and is reached through a new `CODE_SOLVE` action.
The LLM is an *injected* `generate` callable (default = the local inference
broker), so the whole pipeline is model-agnostic and unit-testable without a
model.

## The loop

```
plan_task ──► seed implement ──► synthesize_tests ──► tree_search ──► best candidate
 (decompose)   (implementer)      (gate harness)       │                + provenance
                                                        ▼
                             beam of diverse roots  ─► verify (gate ladder) ─► score
                                                        ▼  (UCB selection of best imperfect node)
                             refine(feedback+prior) ─► verify ─► score ─► record fix to bug memory
```

## Components

| File | Capability |
|---|---|
| `sandbox.py` | **Mandatory execution-feedback substrate.** Runs code in a bounded, isolated subprocess (temp cwd, scrubbed env, `MPLBACKEND=Agg`, wall-clock timeout, POSIX `RLIMIT_CPU`; **no `RLIMIT_AS`** — it breaks numpy). Multi-language via a runner map (Python deepest). Crash detection is precise: only a genuine Python traceback counts; timeouts / signal kills / missing optional deps are tolerated so legitimate long/heavy/optional code isn't falsely failed. `smoke_import` verifies a patched module still loads. |
| `bug_memory.py` | **Semantic bug classification + long-term memory.** `classify_bug` maps a failure to a `BugClass` (null-handling, type, index/off-by-one, key-missing, name-undefined, import, zero-division, value, assertion, recursion, infinite-loop, logic-inversion, state-corruption, concurrency, resource-leak, io) with a stable, fuzzy-matchable *signature* (exception type + last frame + normalized message). `BugMemory` is a local SQLite store of (signature → class → fix) with exact-then-fuzzy (difflib) recall, so the agent learns from past fixes. |
| `verification.py` | **Explicit verification gating + scoring + test synthesis.** `verify_candidate` runs the ladder syntax → execution → tests, stopping at the first failure and attaching a `BugDiagnosis` + repair feedback. `score_candidate` aggregates a 0..1 score (tests dominate when present, else clean execution). `synthesize_tests` produces an executable harness (LLM-driven; deterministic smoke-harness fallback) that prints `ELI_TESTS: <passed>/<total>`. |
| `planner.py` | **Structured decomposition — planner/implementer separation.** `plan_task` → an approach + ordered steps (JSON, with a single-step fallback). `implement` writes/refines code against the plan; in refine mode it does **patch-based incremental refinement** (fix the specific feedback, keep prior code). |
| `search.py` | **Tree search over solutions (not single-shot).** A diverse beam of roots (temperature ladder = exploration), then iterative expansion choosing the node to refine by **UCB1** (`score + c·√(ln N / nᵢ)`) — exploitation vs exploration. Refinements pull matching prior fixes from bug memory into the feedback; successful repairs are written back as (bug → unified-diff fix) pairs. Stops on `target_score` or budget. |
| `agent.py` | **`CodeAgent` / `solve()`** — composes all of the above; default broker-backed generator; returns best code + full provenance (plan, search trace, score, bug class). |

## Capability checklist (as requested)

- structured decomposition (planner/implementer separation) — `planner.py` ✔
- execution feedback loop (mandatory) — `sandbox.py` + `verify_candidate` gate 2 ✔
- tree search over solutions (not single shot) — `search.py` beam + UCB ✔
- explicit verification gating — `verification.py` gate ladder ✔
- long-term memory of bugs and fixes — `bug_memory.py` ✔
- automated test synthesis — `verification.synthesize_tests` ✔
- patch-based incremental refinement — `planner.implement` refine mode + search expansion ✔
- semantic bug classification (null handling, logic inversion, state corruption, …) — `bug_memory.classify_bug` ✔
- scoring / "U-style" exploration / tree-of-code-solutions — `score_candidate` + UCB beam tree ✔
- multiple languages — `sandbox` runner map (Python deep; bash/js/ts/ruby/go/lua structural) ✔

## Wiring & control

- New executor action **`CODE_SOLVE`** (`args.description`, optional `args.language`)
  saves the solution to `artifacts/scripts/` and returns code + provenance. It is
  **additive** — `GENERATE_SCRIPT` and the self-patch engine are untouched.
- Env knobs: `ELI_CODING_SANDBOX` (default on; 0 disables execution),
  `ELI_CODING_RUN_TIMEOUT` (20s), `ELI_CODING_BEAM` (3), `ELI_CODING_MAX_ITERS` (6).
- Bug memory DB: `<db_dir>/coding_memory.sqlite3`.

## Honest scope (what's verified vs model-dependent)

- **Verified deterministically** (tests in `tests/test_coding_agent.py`, no model):
  the sandbox crash/tolerate logic, the bug classifier + memory recall, the gate
  ladder + scoring, and the full plan→search→repair→record loop driven by a stub
  generator (buggy seed → UCB refinement → correct, fix recorded).
- **Model-dependent quality:** the *content* of plans, implementations, and
  synthesized tests scales with the local model. The machinery is frontier-shaped
  regardless of model.
- **Depth:** execution-level verification is Python-first; other languages run if
  their interpreter is installed (structural support).
- **Subtask DAG (added):** decomposable tasks are solved as a dependency graph of
  subtasks on the shared `eli/core/dag` engine (`plan_graph.solve_dag`), composed
  into one module — see `dag.md`. Gated by `ELI_CODING_DAG` (default on); cohesive
  tasks fall back to single-shot.
- **Chat routing (added):** `CODE_SOLVE` is now reachable from chat for explicit
  intents ("solve this coding problem", "implement X and test it", "use the coding
  agent", "verified solution"). Generic "write a python function" still routes to
  the lighter `GENERATE_SCRIPT` (an earlier router path claims it — precedence is
  tunable but the router was intentionally left unreordered).
- **Not yet:** composition is single-module (ordered concat + import-dedupe), not
  true multi-file projects; test synthesis verifies against synthesized tests, not
  a user-supplied spec suite.


---

## Update Advisory — 2026-06-01
- Now reachable three ways: the `CODE_SOLVE` action, the router (verified-coding phrasings), and the new GUI **Coding tab** (`eli/gui/coding_tab.py`).
- `GENERATE_SCRIPT` + self-upgrade route through this engine; heavy tasks auto-background. See `dag.md` (subtask DAG) and `background_tasks.md`.


---

## Update Advisory — 2026-06-07
- Unchanged this cycle. Confirmed against source: UCB1 tree search, syntax→execution→tests gate ladder, weighted scoring (broken syntax hard-capped 0.05), DAG subtask decomposition, and (bug→fix) long-term memory are all live as documented.
