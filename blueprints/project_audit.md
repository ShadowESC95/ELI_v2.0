# ELI MK-XI — Full Project Audit (Engineering Reference)

**Purpose:** A durable, accurate map of the codebase to be used when **refactoring,
upgrading, and fixing**. It records what each subsystem is, where it lives, its entry
points, its current status, and every known issue — so future work starts from facts, not
guesses.

**Snapshot:** commit `a641471`, 2026-06-17. Counts marked *(runtime snapshot)* come from the
live `EXPLAIN_MEMORY_RUNTIME` dump in the 2026-06-17 session and drift over time.

**Companion docs:** `blueprints/adaptive_inference_governor.md` (deep-dive on the
think/budget/throughput policy), plus the existing `blueprints/*.md` set (indexed in §13).

### Accuracy policy (how to trust this document)
Every statement is one of:
- **[V]** verified this session by reading the code / running it (file:line given);
- **[L]** evidenced by the 2026-06-17 session log (quoted/derived);
- **[B]** sourced from an existing blueprint or the maintainer memory index, **not**
  re-verified line-by-line this session (flagged so it can be re-checked before relying on it).

If a statement has no tag it is a structural fact from the file tree / `wc` / `grep` run this
session **[V]**.

---

## 1. At a glance (verified this session)

| Metric | Value |
|---|---|
| Python files under `eli/` | **370** *(+ `api/server.py`, the FastAPI web app, ~3,884 lines)* |
| Python LOC under `eli/` | **143,432** *(measured 2026-07-01)* |
| Largest modules | executor_enhanced 14,294 · engine 13,326 · GUI `eli_pro_audio_gui_MKI` 10,985 · router 7,076 · labs_tab 5,562 · memory 4,415 · deterministic_grounding_gate 4,292 · agent_bus 3,073 · gguf_inference 2,538 |
| Capabilities (`capability_manifest.json`) | **208** |
| `SUPPORTED_ACTIONS` (`executor_enhanced.py`) | **174** |
| Specialist bus agents | **14** (named in §4.4) |
| Test files / suite | **189** files; full run **7,347 passed / 5 failed / 45 skipped / 2 xfailed** *(2026-07-01)* |
| Test groups | `tests/claims` (11), `tests/regression` (6), `tests/generated` (3) |
| SQLite stores | **4** (`user`, `agent`, `system_index`, `coding_memory`) |
| Vector index | FAISS, **1,228** vectors, `nomic-embed-text-v1.5.Q4_K_M` *(runtime snapshot)* |
| Knowledge graph | **50** entities / **49** relations *(runtime snapshot)* |
| Entry point | `python -m eli` → `eli/__main__.py:main()`; engine `CognitiveEngine.process` at `engine.py:8790` |

### Subpackage LOC map (`eli/`)
| Package | files | LOC | Role |
|---|---:|---:|---|
| `execution` | 14 | 23,082 | router + executor (the action surface) |
| `runtime` | 79 | 22,225 | grounding gate, guards, contracts, remediation — the catch-all |
| `gui` | 6 | 17,618 | PyQt app + tabs |
| `kernel` | 8 | 14,406 | `engine.py` cognition controller + state |
| `cognition` | 27 | 13,739 | agents, inference, persona, reasoning modes |
| `memory` | 13 | 6,936 | SQLite + FAISS + KG + recall |
| `perception` | 20 | 6,821 | vision, STT, TTS, screen, gaze |
| `core` | 23 | 6,073 | hardware, settings, paths, model tier, dag, netguard |
| `planning` | 24 | 3,795 | proactive daemon, jobqueue, scheduler, world-room |
| `learning` | 12 | 3,315 | self-model, habits, summaries |
| `coding` | 12 | 2,031 | frontier coding agent (plan→solve→verify) |
| `tools` | 4* | 1,903 | news fetcher, image engine (image_engine nested) |
| `utils`/`contracts`/`plugins`/`system`/`world`/`cli` | — | <1k each | logging, contracts, plugin host, world avatar |
| `guards`/`integrations` | 1 | 0 | **empty/dead** (see §10) |

---

## 2. Repository map (top level)
- `eli/` — the application (above).
- `blueprints/` — design docs (index §13). This audit + the governor plan live here.
- `artifacts/` — runtime state: `db/` (the 4 SQLite stores), `vectors/` (FAISS index+meta),
  `runtime_snapshot.json`, `runtime_hardware_profile.json`, `analyze_image_*`, eval outputs,
  world snapshots.
- `models/` — GGUF weights (text + embeddings + vision + LoRA); no model is baked into code.
- `tests/` — pytest suite (§11).
- `tools/`, `scripts/`, `ops/`, `packaging/`, `training/` — eval/build/train/ops.
- `config/` — trusted agents, settings.
- Install: `install.sh` / `install.bat` / `install.ps1`, `requirements*.txt`,
  `requirements.lock.txt`, `pyproject.toml`.

---

## 3. Control flow (the cognition pipeline)
Single entry: `CognitiveEngine.process()` (`engine.py:8790`). 12 logical stages **[L/V]**
(stage map verified live via `EXPLAIN_COGNITION_RUNTIME`):

1. Perceive + ingest — `gui/eli_pro_audio_gui_MKI.py` (text) / `perception/audio_stt.py` (voice).
2. Input normalization + guards — `engine.py` input guards (long-question, command, wake-word).
3. Router + task decomposer — `execution/router_enhanced.py:route()` → `{action,args,confidence,meta}`.
4. Truth / grounding gate — forbids a direct LLM answer when grounding is required.
5. Executive controller / planner — picks agent profile + order.
6. Agent bus — up to 14 specialist agents on a `ThreadPoolExecutor`, ordered by a dependency DAG.
7. Working-memory / context assembler.
8. **Single inference broker** — `cognition/inference_broker.py`; all model calls serialize on
   `_LLM_CALL_LOCK` (`gguf_inference.py:515`). llama.cpp is not concurrency-safe; vision
   hot-swap and the ambient daemon coordinate on this lock too. **[V]**
9. Reasoning / synthesis — pure chat / grounded / hybrid; reasoning-mode strategies in §7.
10. Output governor — `cognition/output_governor.py` (1,200 LOC) shape/evidence/confidence.
11. Delivery — GUI / TTS (`perception/tts_router.py`, Piper).
12. Learning + state update — `memory/memory.py` stores turns/memories/habits/failures.

**Fast path:** `_PHASE45_DIRECT_FAST_ACTIONS` (`engine.py:78`) — deterministic actions whose
executor result is authoritative are executed and returned verbatim, bypassing synthesis
(e.g. SCREENSHOT, ANALYZE_IMAGE, CHECK_JOB, and now CREATE_FILE after `a641471`). **[V]**

---

## 4. Subsystem audit

### 4.1 Router — `execution/router_enhanced.py (7076)
Deterministic, priority-ordered intent parser: explicit regex routes → `multi_command`
prepass (`runtime/command_splitter.py`) → LLM intent-resolver fallback (`cognition/llm_intent.py`).
Public entry `route(text)`. **Status:** the highest-churn correctness surface; regex
over/under-capture is the dominant bug class (see §9). Fixed in `a641471`: job-status,
LIST_DIR over-capture, CREATE_FILE dir capture, multi-command banter. **Refactor note:** the
file is a long if-ladder; a route-table + per-route unit fixtures (`tests/router_test_data.json`
already exists) would make ordering bugs (like the job-vs-list precedence) visible.

### 4.2 Executor — `execution/executor_enhanced.py (14340)
Implements **174** `SUPPORTED_ACTIONS` (`:1899`). Each action is an `if a == "X":` block
returning `{ok, action, content, response, …}`. Security-gated file writes
(`CREATE_FILE` `:8829` via `runtime/security.SecurityManager.is_path_allowed`). Background
work offloaded via `runtime/background_tasks.py` (`CHECK_JOB`/`BACKGROUND_JOBS` at `:8679`).
**Status:** largest file in the repo; the action-dispatch is a giant linear scan. **Refactor
note:** a dispatch dict `{ACTION: handler}` would cut the scan and make the action surface
enumerable for docs/tests.

### 4.3 Kernel / engine — `kernel/engine.py (13374)
`CognitiveEngine` owns the pipeline, mode contracts, grounded-control synthesis, and the
reasoning-strategy runners (`_run_chain_of_thought` `:6131`, `_run_tree_of_thoughts` `:6223`,
`_run_self_consistency` `:6506`). Grounded synthesis helpers `_compact_grounded_synthesis`
(≈12946) and `_synthesize_answer` (13118). **Status:** second-largest file; very high
coupling. The empty-`<think>` cascade originates here (synthesis call shapes) — see governor
doc. **Refactor note:** the synthesis/think/budget logic should move behind the Adaptive
Inference Governor (companion doc) rather than per-site flags.

### 4.4 Agent bus — `cognition/agent_bus.py (3138)
**14 agents** (verified classes): `memory` (723), `system` (942), `habit` (1061),
`self_improvement` (1117), `proactive` (1176), `frontier` (1243), `plugin` (1320),
`capability` (1362), `voice` (1408), `orchestrator` (1590), `file_code` (2316),
`introspection` (2641), `reflection` (2721), `knowledge_graph` (2816). Profiles selected per
action by `_select_profile` (default branch + keyword heuristics; this is what dropped
`system` on the compound CREATE_FILE turn — §9). Dependency DAG: `knowledge_graph ← memory`
(`_AGENT_DEPENDENCIES`, `:596`), executed in topological layers via `core/dag.py`. **[V]**
**Note [B]:** memory index records `FrontierAgent` as dormant and bus agents as
retrieval-level rather than frontier-quality — not re-verified this session.

### 4.5 Inference — `cognition/gguf_inference.py (2677) + `inference_broker.py`
llama.cpp wrapper. Model-agnostic resolution (`get_model_path`), family-aware templating
(`_is_chatml_model`/`_is_llama_model`/`_is_mistral_model`, filename-based), no-think prefill
(`_no_think_prefill`), thinking-model detection (`_is_thinking_model:219`, filename allowlist),
live decode-speed EMA (`record_speed`, non-stream path `:1162`). All calls serialize on
`_LLM_CALL_LOCK`. **Status:** the think/budget policy is incomplete for cross-hardware use —
full analysis + plan in `adaptive_inference_governor.md`. `force_no_think()` added in `a641471`
(one caller). **[V]**

### 4.6 Memory — `memory/memory.py (4461) + `memory/`
4 SQLite stores + FTS5 mirrors + FAISS + KG (§5). Hybrid recall: SQLite LIKE + FTS5 + FAISS +
KG, merged/reranked (`cognition/reranker.py`, `cognition/scoring.py`). Entry classes
`Memory`, `get_memory()`, `recall_memory()`, `store_memory()`, `VectorStore.search()`. **[L/V]**
**Note [B]:** memory index records 3 memory-ranking fusion weight sets that still differ
(deferred tuning) — not re-verified.

### 4.7 Perception — `perception/` (20 files)
- **Vision** `vision.py`: model-agnostic VLM via llama.cpp multimodal; mtmd encoder forced to
  CPU to avoid a CUDA clip segfault (`:459`). **Documented default Qwen2.5-VL; runtime in the
  log resolved Moondream2** (`MoondreamChatHandler`) — a discrepancy (§9). OCR path exists
  (`analyze_image.py`, tesseract) but "read the text" routed to captioning in the log. **[L/V]**
- **STT** audio_stt.py (1848): faster-whisper `small.en`, CPU, int8 *(runtime snapshot)*. **[L]**
- **TTS** `tts_router.py`: Piper-only, `en_US-amy-medium`, `aplay`. **[L]**
- Also: screen read/analyze, gaze engine, ambient vision daemon, PDF/CSV analysis.

### 4.8 Coding agent — `coding/` (12 files, 2,031)
Self-contained frontier coding subsystem: plan → DAG/tree search → execute → verify → repair
(`coding/__init__.py` docstring **[V]**), sandbox at `coding/sandbox.py`, `plan_graph.py`,
`cost.py` (`should_background`). Invoked by `CODE_SOLVE` and by self-improvement. **[V]**
**Note [L]:** the coding agent's fix-generation calls hit the same empty-`<think>` failure
(SELF_IMPROVE turn) — covered by the governor plan.

### 4.9 Planning / proactive — `planning/` (24 files)
proactive_daemon.py (1301): continuous habit/pattern learning, persona-overlay refresh,
autonomy tick (code-monitor + self-model + scheduler proposals), news synthesis. Also
`jobqueue.py` (durable subprocess jobs — distinct from in-process `runtime/background_tasks.py`),
schedulers, and the world-room avatar. **Status [L]:** the daemon emits very frequent
`persona_updater`/`kg sync` churn (§9 G). **[V/L]**

### 4.10 Learning / self-improvement — `learning/` (12) + `runtime/self_improvement.py (1206)
Self-model refresh, session summaries, habit detection/rules, failure analysis (`SELF_ANALYZE`),
fix proposals (`SELF_IMPROVE` → coding agent, propose-only). `self_improvement.py:641` uses
`broker.infer(max_tokens=700)` (small → already no-think). **[V]**
**Note [B]:** memory records `profile_extractor` as a regex→canned-phrase table with a
hard-coded `active_project="developing ELI"`, and `time_habit` as stale/unwindowed — not
re-verified this session.

### 4.11 Core — `core/` (23 files)
Hardware + runtime substrate: `hardware_profile.py` (1,040, free-VRAM sizing, compute reserve
`:69`), `startup_hardware_optimizer.py` (boot profile, `train_ctx_for_model:164`),
`model_tier.py` (size tier + **live tok/s EMA**), `runtime_settings.py` (1,034, portable
storage / path healing), `paths.py`/`portable_paths.py`/`legacy_paths.py`/`db_paths.py`,
`netguard.py` (204, offline-by-default socket failsafe), `dag.py` (474, orchestrator),
`crisis_guard.py`, `full_control.py`, `model_download.py`, `cognition_tunables.py`.
**Finding [V]:** `dynamic_runtime_budget.py` (`DynamicRuntimeBudget`) has **zero references
repo-wide** — a dead/unwired module that is a half-built hardware-budget the governor could
fold in (§10).

### 4.12 Runtime — `runtime/` (79 files, 22,225)
The catch-all: deterministic_grounding_gate.py (4292), grounded_remediation.py (1604),
generated_script_guard.py (1072), control_contracts.py (943), security.py (207),
approval_engine.py (103), `background_tasks.py`, `command_splitter.py`, evidence/identity/
operator/response sub-families. **Refactor note:** this package is the least cohesive; many
single-purpose guard/contract files. A pass to group by concern (grounding / guards / evidence
/ contracts) would improve navigability.

### 4.13 GUI — `gui/` (6 files, 17,618)
PyQt app `eli_pro_audio_gui_MKI.py` (10,985) + labs_tab.py (5696) + panels. 12 main tabs
**[B]** (Report Builder promoted; Proactive×6 / Labs×10 / Settings×5 sub-tabs per memory index).
`QScintilla` optional (falls back to basic editor). **Status:** large monolith GUI files.

### 4.14 World / plugins / tools / cli
- `world/` — avatar "rooms" (Reflection Chamber, Memory Archive); gated to world/activity
  queries (a greeting leaked a room narration in the log — §9). **[L]**
- `plugins/` — plugin host (3 files).
- `tools/` — `news/news_fetcher.py` (RSS/arXiv/HN/Reddit), `image_engine/` (SSD-1B + procedural).
- `cli/` — headless REPL pieces; `eli/__main__.py` `--headless`, `--trust-agent`.

---

## 5. Data & state stores *(table counts: runtime snapshot 2026-06-17)*
Path: `artifacts/db/`. **[L]** (from `EXPLAIN_MEMORY_RUNTIME`)

| Store | Size | Tables | Role |
|---|---|---|---|
| `user.sqlite3` | 58.32 MB | 38 | the real store: memories, conversation_turns, kg_entities/relations, news, habits, observations, recall_log, runtime_events, session_summaries, working_memory_pins, + FTS mirrors |
| `agent.sqlite3` | 2.66 MB | 25 | agent_dispatches, agent_metrics, code_patches, failures, improvements, observations |
| `system_index.sqlite3` | 0.566 MB | 4 | desktop_apps, executables, recent_files, user_dirs |
| `coding_memory.sqlite3` | 0.02 MB | 1 | coding_bug_fixes |

- **FTS5 mirrors:** `memories_fts`, `kg_entities_fts`, `news_fts`.
- **FAISS:** `artifacts/vectors/index.faiss` (+`meta.json`), 1,228 vectors, dim 768,
  embedder `models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf`.
- **KG:** `kg_entities` (50) / `kg_relations` (49).
- Live counts at snapshot: memories 1,265; conversation_turns ~4,426; distinct sessions 967;
  learning_replay 6,189; runtime_events 16,426; news_articles 1,801.
- **Note:** "active/user/memory DB roles alias the same `user.sqlite3` file" — 4 *physical*
  files, more logical roles. **[L]**

---

## 6. Action / capability surface
- `capability_manifest.json` — **208** capabilities (regenerated at startup; `generated_at`
  2026-06-17). `capability_inventory.generated.json` is the generated inventory.
- `executor_enhanced.SUPPORTED_ACTIONS` — **174** action strings (`:1899`). The gap between
  208 capabilities and 174 actions is expected (capabilities include GUI/registry items that
  aren't executor actions). **Note:** the maintainer-memory figure "155 actions / 194 caps" is
  **stale**; the verified current numbers are 174 / 208.
- Full human catalogue: `blueprints/capabilities_and_actions.md`, `capability_catalogue.md`. **[B]**

---

## 7. Reasoning modes & inference policy
- Modes (`cognition/reasoning_modes.py`): `quick`, `normal`, `advanced`, `research`, `expert`
  (visible names), plus strategy runners CoT / ToT / self-consistency / constitutional. **[V]**
- Per-mode budget (`:312–352`): derived from `n_ctx`, prompt pressure, query complexity, mode —
  **no throughput term**. Pass-count (not length) is capped by measured tok/s via
  `model_tier.speed_passes()` (engine `:6241`, `:6520`). **[V]**
- **This is the active work area.** The full analysis (think/no-think, throughput-blind budgets,
  filename-based capability detection, empty-`<think>` recovery, the unused
  `DynamicRuntimeBudget`) and the proposed **Adaptive Inference Governor** are in
  `blueprints/adaptive_inference_governor.md`. Treat that as the authority for this layer.

---

## 8. Cross-cutting invariants (must hold across all changes) **[B, maintainer policy]**
1. **Model-agnostic** — no hard-coded model name/size on the inference path; frontier-quality bar.
2. **No fake actions** — if ELI says it did X, the pipeline must actually do X (no narrated success).
3. **Offline-by-default** — all internet via `core/netguard`; process-wide socket failsafe.
4. **Redistributable / no personal data** — never hard-code a user name or `/home/<user>` path in
   source; runtime redaction exists. Settings are stored portably (`_portable_settings_for_storage`).
5. **Grounding** — grounded/self-referential questions must use real evidence, never CHAT-guessing;
   degenerate `-`/empty fragments are discarded, not surfaced.
6. **Single inference broker / serialized GGUF** — one model call at a time (`_LLM_CALL_LOCK`).
7. **Check the codebase before proposing** — features usually already exist; frame work as
   gap-analysis, not greenfield.

---

## 9. Consolidated known-issues register
Severity P0=integrity, P1=routing/exec, P2=quality. Status as of `a641471`.

| # | Issue | Where | Status |
|---|---|---|---|
| R1 | Job-status queries ("job #3") didn't reach CHECK_JOB (`#` broke regex) | router | **FIXED a641471** |
| R2 | CREATE_FILE dropped target dir + wasn't executed (profile dropped `system`) | router + engine fast-path | **FIXED a641471** |
| R3 | LIST_DIR over-capture (swallowed trailing clause; "my notes"→dir) | router | **FIXED a641471** |
| R4 | Multi-command banter folded into media title | `command_splitter` | **FIXED a641471** |
| R5 | EXPLAIN_* compact synthesis empty-`<think>` loop | engine + gguf | **PARTIAL (compact) a641471; governor plan for the rest** |
| I1 | Catastrophic latency (2–9 min/turn) — throughput-blind budgets on slow HW | inference policy | OPEN → governor |
| I2 | Standard-synthesis fallback + coding fix-gen still empty on `<think>` | engine + coding | OPEN → governor |
| I3 | Thinking-detection is a filename allowlist | `gguf_inference:219` | OPEN → governor |
| I4 | ctx table undershoots model `n_ctx_train` (32768 vs 262144) | `train_ctx_for_model` | OPEN → governor |
| I5 | LIST_NOTES success discarded by low-grounding downgrade→CHAT (wrong "just one") | engine | OPEN (parked) |
| I6 | Confidence gate checks response conf, not grounding (passes grounding=0.0) | engine stage 12 | OPEN |
| I7 | Vision = captioning, not OCR; "read the text" didn't OCR; Moondream2 vs documented Qwen2.5-VL | perception/vision | OPEN |
| I8 | Memory-count inconsistency (3295 vs grounded 1265) across phrasings | memory introspection | OPEN |
| I9 | Multi-part question half-answered (persona Q ignored) | engine/synthesis | OPEN |
| I10 | World-room narration leaked into a plain greeting | world + engine gate | OPEN |
| I11 | Proactive `persona_updater`/KG-sync churn (deterministic, redundant; CPU/DB, **not** LLM-lock) | proactive_daemon/persona_updater | OPEN → governor §G |
| I12 [B] | `profile_extractor` regex→canned, `active_project` hard-coded; `time_habit` stale; frequency-habits never become rules | learning/proactive | OPEN, not re-verified |
| I13 [B] | `FrontierAgent` dormant; bus agents retrieval-level not frontier | agent_bus | OPEN, not re-verified |

---

## 10. Dead / unwired / duplication (refactor targets)
- **`core/dynamic_runtime_budget.py`** — `DynamicRuntimeBudget` has **zero references**
  repo-wide. Dead; overlaps the governor's intended budget object. **[V]**
- **`eli/integrations/`** (1 file, 0 LOC) — empty package. (`eli/guards/` was the other empty package; it has been **removed**.) **[V]**
- **`eli/tools/image_engine`** appears both as a 1,750-LOC module and a nested
  `image_engine/image_engine/` package (engine 1,483 + visual_core 1,447) — possible duplication
  to reconcile. **[V]**
- **Two inference-broker concepts** — verified the live one is `cognition/inference_broker.py`;
  `core/inference_broker.py` does **not** exist. Don't reintroduce a second.
- **[B] duplication convergence** (memory): canonical `cognition/scoring.py` exists; topic-stopwords
  / FTS-splits / two-tier routing are distinct (not dup); 3 memory-ranking fusion weights still
  differ — deferred.
- Executor (174-way `if`) and router (long if-ladder) are the two biggest *structural* refactor
  candidates (dispatch table + route table).

---

## 11. Tests & verification
- 194 test files; full run **7,347 passed / 5 failed / 45 skipped / 2 xfailed** (2026-07-01). **[V]**
  The 5 remaining reds are the in-progress `smart_home` plugin removal + one stale blueprint
  ref — pre-existing, unrelated, fail identically on a clean tree.
- Groups: `tests/claims/` (project-vs-claims, symbol inventory, agent contracts),
  `tests/regression/`, `tests/generated/` (+ `_manifest.json`), plus the flat `test_*` suite.
- No-GGUF pattern: many tests assert engine/router behaviour without loading a model
  (`tests/test_*_no_gguf*.py`) — the right place to add governor decision tests.
- Isolation via in-project `ELI_ARTIFACTS_DIR` (no monkeypatch). **[B]**
- Report: `tools/run_test_report.py` → `artifacts/test_report.md`; `run_tests.sh`.
- **Baseline at `a641471`:** router/multi-command/background (239) + filesystem/think-stop/
  reasoning/runtime-status (61) green; full collection clean. **[V]**

---

## 12. Install / packaging / redistribution
- `install.sh` (+ `.bat`/`.ps1`): frozen lock (`requirements.lock.txt`) + GPU verify + DB init. **[B]**
- Platform requirement files: `requirements-{windows,macos,android,full,learning}.txt`.
- `pyproject.toml`, `eli-mkxi.desktop`, `build_packages.sh`, `packaging/`.
- Redistribution mechanics: portable settings storage + stale-path healing
  (`runtime_settings._heal_model_paths`, `_resolve_relative_model_paths`), dataset redaction.
  **Open risk [B]:** personal values (e.g. `user_name`) can still end up tracked; the
  cross-platform generalization mandate (Linux/macOS/Windows) is ongoing.

---

## 13. Blueprint index (existing design docs in `blueprints/`)
`architecture.md`, `architecture_ascii.md`, `agent_algorithms.md`, `orchestration_and_agents.md`,
`dag.md`/`dag_orchestrator.md`, `memory.md`, `grounding_and_evidence.md`,
`inference_and_hardware.md`, `coding_agent.md`, `code_mode_execution_layer.md`, `learning.md`,
`perception.md`, `gui.md`, `security.md`, `operations.md`, `installation.md`,
`capabilities_and_actions.md`/`capability_catalogue.md`, `what_eli_can_do.md`/`what_eli_is.md`,
`project_overview.md`, `state_snapshot.md`, `runtime_planning_world.md`, `eval_harness.md`,
`lora_pipeline.md`, `background_tasks.md`, `model_bakeoff_dossier.md`, `top2_head2head.md`,
`decomposition_plan.md`, `proposal_total_awareness.md`, `complete_findings.md`, `diagrams.md`.
**+ this audit** and **`adaptive_inference_governor.md`**.

---

## 14. Appendix — verification provenance
**Read this session [V]:** router (`route`, job/list/create_file routes, `_expand_common_dir`),
`command_splitter`, engine (`_PHASE45_DIRECT_FAST_ACTIONS`, `_run_chain_of_thought`,
`_compact_grounded_synthesis`, `_synthesize_answer`, replan, low-grounding downgrade),
`gguf_inference` (`_no_think_prefill`, `_is_thinking_model`, `record_speed`, broker legacy
paths), `reasoning_modes` budget, `model_tier` (EMA + `speed_passes`), `hardware_profile`
(reserve), `startup_hardware_optimizer.train_ctx_for_model`, `agent_bus` (14 agents +
`_select_profile` branches), `persona_updater`, `dynamic_runtime_budget` (dead),
executor CREATE_FILE / CHECK_JOB handlers, `SUPPORTED_ACTIONS`, structure/LOC/test counts.
**From the 2026-06-17 session log [L]:** model load, stage map, DB table dump, vision/STT/TTS
runtime, latency/empty-`<think>` timings.
**From blueprints / maintainer memory [B], not re-verified:** GUI tab inventory, install
internals, FrontierAgent dormancy, profile_extractor/time_habit specifics, memory-fusion
weights, duplication-convergence status. Re-verify any **[B]** item before relying on it for a fix.
