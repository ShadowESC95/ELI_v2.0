# ELI Coding Agent (`eli/coding/`)

> **Updated for v2.5.36.** Invoked via `CODE_SOLVE`, `GENERATE_PROJECT`, `FIX_FILE` (Python
> files) and `SELF_IMPROVE` in propose mode; separate from the 15-agent chat bus (its own
> pipeline: plan → search → verify → repair). `GENERATE_SCRIPT` does not reach it (see
> *Wiring & control*).

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

Before planning, `repo_context.gather_repo_context` collects the existing project code the
task points at (the imports of files it names, the definitions of symbols it names), so the
plan and the code are written against real APIs. After the search, one self-critique pass
(`verification.critique_candidate`) asks the model for concrete issues in the best candidate;
if it names any, one more refinement is verified and kept only if it scores at least as well
(`ELI_CODING_CRITIQUE=0` turns it off).

## Components

| File | Capability |
|---|---|
| `sandbox.py` | **Mandatory execution-feedback substrate.** Runs code in a bounded, isolated subprocess (temp cwd, an environment with any variable named like a key, token, secret or password removed, `MPLBACKEND=Agg`, wall-clock timeout, POSIX `RLIMIT_CPU`; **no `RLIMIT_AS`** — it breaks numpy). `ELI_SANDBOX_ISOLATE=1` also wraps the run in firejail or nsjail with no network when one is installed. Multi-language via a runner map (Python deepest). Crash detection is precise: a genuine Python traceback counts, and so does a non-zero exit with no traceback (`sys.exit(1)`); timeouts / signal kills / missing optional deps are tolerated so legitimate long/heavy/optional code isn't falsely failed. `smoke_import` verifies a patched module still loads. |
| `bug_memory.py` | **Semantic bug classification + long-term memory.** `classify_bug` maps a failure to a `BugClass` (syntax, null-handling, type, index/off-by-one, key-missing, name-undefined, import, zero-division, value, assertion, recursion, infinite-loop, logic-inversion, state-corruption, concurrency, resource-leak, io) with a stable, fuzzy-matchable *signature* (exception type + last frame + normalized message). `BugMemory` is a local SQLite store of (signature → class → fix) with exact-then-fuzzy (difflib) recall, so the agent learns from past fixes. |
| `verification.py` | **Explicit verification gating + scoring + test synthesis.** `verify_candidate` runs the ladder syntax → execution → tests, stopping at the first failure and attaching a `BugDiagnosis` + repair feedback. `score_candidate` aggregates a 0..1 score (tests dominate when present, else clean execution). `synthesize_tests` produces an executable harness (LLM-driven; deterministic smoke-harness fallback) that prints `ELI_TESTS: <passed>/<total>`. `critique_candidate` is the self-review pass. |
| `repo_context.py` | **Grounding in the existing code.** Deterministic, offline and bounded: the imports of files the task names and the definitions of the symbols it names. |
| `planner.py` | **Structured decomposition — planner/implementer separation.** `plan_task` → an approach + ordered steps (JSON, with a single-step fallback). `implement` writes/refines code against the plan; in refine mode it does **patch-based incremental refinement** (fix the specific feedback, keep prior code). |
| `search.py` | **Tree search over solutions (not single-shot).** A diverse beam of roots (temperature ladder = exploration), then iterative expansion choosing the node to refine by **UCB1** (`score + c·√(ln N / nᵢ)`) — exploitation vs exploration. Refinements pull matching prior fixes from bug memory into the feedback; successful repairs are written back as (bug → unified-diff fix) pairs. Stops on `target_score` or budget. |
| `agent.py` | **`CodeAgent` / `solve()`** — composes all of the above; default broker-backed generator; returns best code + full provenance (plan, search trace, score, bug class). |
| `plan_graph.py` | **Subtask DAG** for decomposable tasks (see `dag.md`). |
| `cost.py` | **Foreground or background** — `should_background` / `estimate_cost` (see `background_tasks.md`). |
| `code_mode.py`, `restricted_exec.py` | **Code-mode** — a short program run in-process against `eli.api`, behind Full Control (see `code_mode_execution_layer.md`). |

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

- Executor action **`CODE_SOLVE`** (`args.description`, optional `args.language`, `mode`
  `quick` for a single pass with no DAG, or `use_dag` / `beam` / `max_iterations`) saves the
  solution to the artifacts `scripts/` folder (`ELI_ARTIFACTS_DIR` or `ELI_DATA_DIR` when set)
  and returns code + provenance. Python that does not parse is saved with a `.draft` suffix
  and marked not runnable. A heavy or "in the background" request runs as a background job
  (see `background_tasks.md`). `args.code_mode` switches to code-mode instead.
- Other callers: `GENERATE_PROJECT` (with the subtask DAG, saved under `projects/`),
  `FIX_FILE` on a Python file, and `SELF_IMPROVE` in propose mode. The self-patch engine's
  `generate_code_patch` reads this package's bug memory.
- `GENERATE_SCRIPT` does **not** reach the agent. The executor's portable script hook
  (`_eli_v3_generate_script` in `executor_enhanced.py`) answers GENERATE_SCRIPT, CREATE_SCRIPT
  and WRITE_SCRIPT before `_execute_impl` is reached: one model generation, refused when it
  is a stub, one standard-library-only retry when Python does not compile, saved under
  `scripts/`. The coding-agent branch inside `_execute_impl`'s GENERATE_SCRIPT handler and
  `ELI_GENERATE_SCRIPT_AGENT` are never reached.
- Env knobs: `ELI_CODING_SANDBOX` (default on; 0 disables execution),
  `ELI_CODING_RUN_TIMEOUT` (20s), `ELI_CODING_BEAM` (3), `ELI_CODING_MAX_ITERS` (6),
  `ELI_CODING_CRITIQUE` (default on), `ELI_CODING_DAG` (default on), `ELI_SANDBOX_ISOLATE`
  (default off).
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
  intents ("solve this coding problem", "write a script that renames files and test it",
  "implement X and test it", "use the coding agent", "verified solution"). Generic "write a
  python function" still routes to the lighter `GENERATE_SCRIPT`. Two router stages run before
  the code lane and claim generation requests first: `generate_script_prepass` (a message that
  opens with a creation verb — write, create, generate, make, build, code — and names code or a
  language) and the portable intent contract (a creation verb plus script, code, program,
  module, tool or app, when the message is not a question). Code that is to be tested or
  verified as well as written is `CODE_SOLVE` in both, by one test
  (`portable_intent_contract.asks_for_tested_code`, which the code lane's own rule uses too):
  `generate_script_prepass` routes it there before a message is divided into commands, so "and
  test it" is not run as a second command, and the portable contract leaves it alone. Writing
  the tests themselves ("write unit tests for the parser") stays `GENERATE_TESTS`. The Coding
  tab always uses `CODE_SOLVE`.
- **Not yet:** composition is single-module (ordered concat + import-dedupe), not
  true multi-file projects; test synthesis verifies against synthesized tests, not
  a user-supplied spec suite.

## FIX_FILE (`executor_enhanced.py`, not this package, but shares its safety net)

`FIX_FILE` — the directly user-triggered "fix/improve this file" action — routes
Python fixes through this package's `solve()` (syntax + lint + execution +
repo-context + self-critique; other languages, or a Python fix the agent could not produce,
get up to two direct model rewrites, a Python one checked for syntax and for library calls
that do not exist), then writes the result over the *existing* file the user named,
without asking first. By default it runs as a background job
(`ELI_FIX_FILE_BACKGROUND=0` keeps it in the foreground). It first writes a backup beside
the file (`<file>.bak.<timestamp>`) and carries the same safety net `self_improvement.py`'s
autonomous patcher has: refuses to touch the protected guardrail-file list
(`is_protected_patch_path`), and for one of ELI's own modules that imported cleanly before,
smoke-imports the patched module, runs targeted tests, and restores the original on either
failure — all reusing `self_improvement.py`'s own verification functions
rather than a second implementation. A file outside ELI's own package gets the backup only.
Worth stating plainly: since autonomous
self-patching is opt-in and off by default, FIX_FILE is almost certainly the
*more* exercised of the two real-file-editing paths, so it needed to be at
least as protected, not less.
