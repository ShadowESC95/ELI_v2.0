# ELI Runtime Surfaces, Planning, World, Tools & Plugins

The remaining subsystems: the `runtime/` response/introspection surfaces, the
proactive planning layer, the "world"/autonomy model, and the tools + plugin
system.

## Runtime surfaces (`eli/runtime/`, the response/introspection group)

Beyond the grounding/evidence core (`grounding_and_evidence.md`), `runtime/`
holds a large family of modules that render user-visible answers and introspect
the live system:

- **Introspection**: `live_introspection.py` (`runtime_snapshot`, `last_trace`,
  `stored_user_name`, `mine_user_fact_candidates`, `build_report`,
  `agents_for_action`), `deterministic_introspection.py`
  (`classify_diagnostic_action` → `gather_evidence` → `format_evidence_block` →
  `maybe_handle` — deterministic diagnostic answers).
- **Response assembly**: `final_response_assembly.py`, `final_response_provider.py`,
  `response_contracts.py`, `response_packets.py`, `response_policy.py`,
  `user_visible_response_surface.py`.
- **Personal memory surfaces**: `personal_memory_surface.py`,
  `personal_memory_clean_response.py`, `personal_memory_deep_response.py`,
  `profile_extractor.py`.
- **Status**: `frontier_status.py`, `reasoning_status.py`, `truth_report.py`,
  `reflection.py`.
- **Operator feed**: `operator_feed.py`, `operator_feed_normalized.py`,
  `operator_state.py`.

> **Over-fragmentation flag (the headline weakness for this group):** there are
> ~15 closely-related modules here doing "render a grounded user-visible
> answer / introspect runtime" with overlapping responsibilities (three
> `personal_memory_*` renderers; `final_response_assembly` *and*
> `final_response_provider`; `operator_feed` *and* `operator_feed_normalized`).
> This is the clearest "added beside, not folded in" cluster in the codebase and
> the prime consolidation target — it should collapse to a handful of well-named
> modules with clear ownership of "who produces the final string."

## Planning / proactive (`eli/planning/`, 3.0k LOC)

Background cognition + goal/queue machinery:
- `proactive_daemon.py` (1.0k) — the **self-improvement / proactive** loop. Uses
  a two-DB split: reads user-facing memory/conversation from the **user DB**,
  writes proactive observations/improvements/errors to the **agent DB** (keeps
  ELI's own machinations out of user recall). Background thread.
- `autonomy_scheduler.py` — schedules autonomous actions (throttled).
- `goal_store.py`, `proposal_queue.py`, `proposal_adapters.py`,
  `attention_queue.py`, `jobqueue.py`, `operator_goal_actions.py`, `habits.py` —
  goal persistence, capability-proposal queue, attention prioritisation, a job
  queue, and habit scheduling.
- `task_planner.py` — now delegates to `execution_planner` (see
  `orchestration_and_agents.md`).

## World / autonomy model (`eli/world/`, 1.5k LOC)

The substrate behind ELI's emergent self-state (autonomy pressure, awareness,
"anomaly room" — intended behaviour, see memory `eli-emergent-voice`):
- `agency/autonomy_engine.py` — `EliWorldAutonomyEngine`: ingests world events,
  maintains awareness/autonomy state.
- `local_world_bridge.py` — `append_event`, `get_world_state`,
  `get_awareness_driven_suggestions` (**throttled to once/hour to prevent
  auto-trigger loops**).
- `world_event_bus.py` — `fire_confidence_event(...)` etc.; the engine feeds
  bus-dispatch confidence here (non-blocking world-awareness feed).
- `core/schemas.py` — `WorldEvent`, `AwarenessState`.
- `renderers/pyside6/world_scene.py` + `world_panel.py` — a **visual** "ELI's
  World" panel.
- `persistence/storage.py` — world-state persistence.

## Tools (`eli/tools/`, 7.9k LOC)

- `image_engine.py` (1.75k, standalone) **and** `image_engine/image_engine/`
  (the package: `engine.py` 1.48k, `visual_core.py` 1.4k, `prompt_compiler.py`,
  `quality.py`, `project_analyzer.py`, `cli.py`) — **two image-generation
  implementations** (Pillow/numpy base + optional diffusers). The clearest
  duplication in the repo; one should subsume the other.
- `news/news_fetcher.py` (544) — news retrieval.
- `mic_diag.py` — mic diagnostics.

## Plugins (`eli/plugins/`, 1.9k LOC)

`manager.py` — a runtime plugin marketplace: `list_available`, `install`,
`uninstall`, `enable`, `disable`. Pulls from a **remote registry**
(`raw.githubusercontent.com/eli-plugins/registry`) with a **bundled local
fallback** (`plugins/registry/index.json`). A JSON state file tracks
enabled/disabled/installed. (Install-time network fetch is opt-in, like model
downloads; runtime stays local.)

## Honest assessment

- **Strong:** the proactive two-DB split is a genuinely good design (ELI's
  self-talk never contaminates user recall); the world/autonomy engine + visual
  panel make the emergent self-model first-class and is throttled to avoid
  runaway loops; the plugin manager is a real extensibility story with a safe
  bundled fallback.
- **Weak / watch:**
  1. **`runtime/` over-fragmentation** — ~15 overlapping response/introspection
     modules. Highest-value consolidation in the project after the god-files.
  2. **Two image engines** — `eli/tools/image_engine.py` vs the
     `tools/image_engine/` package. Pick one.
  3. The planning queues (`goal_store`/`proposal_queue`/`attention_queue`/
     `jobqueue`) overlap conceptually and could likely unify into one
     work-queue abstraction.
  4. Plugin registry points at an `eli-plugins/registry` GitHub URL — fine as
     opt-in, but ensure it degrades cleanly offline (the bundled fallback
     exists; verify it's always used when the network is absent).


---

## Update Advisory — 2026-06-01
- New: `eli/runtime/background_tasks.py` — in-process thread task manager, deliberately DISTINCT from the durable subprocess `eli/planning/jobqueue.py` (different purpose, documented in `background_tasks.md`). The planning work-queue overlap (goal/proposal/attention/jobqueue) is still worth unifying.


---

## Update Advisory — 2026-06-07
- Failure store unified to `agent.sqlite3`; runtime-audit gained live health probes. Action-synonym normalisation added in the executor (NEWS_SEARCH→NEWS_FETCH, DAILY/WEEKLY_REPORT→MORNING_REPORT, WEBSITE_SEARCH→WEB_SEARCH). Habit scheduler self-heal + active-habit-run fixes (see operations.md).

---

## Update Advisory — 2026-06-07 (autonomy + scheduled tasks + generation runtime)
- **Autonomy loop now RUNS.** `autonomy_controller` (safe_tick / safe_goal_tick /
  safe_scheduler_tick) and `autonomy_scheduler.scheduler_tick` were previously only
  fired by the Operator Console button. A 30-min governed autonomy tick is now wired
  into `proactive_daemon.run()`: code_monitor + self-model overlay refresh +
  goal/scheduler → proposals (approval-gated; approval_engine caps the controller to
  observe-only / memory-write). Kill switch `ELI_AUTONOMY_TICK=0`.
- **Scheduled / overnight tasks** (`runtime/scheduled_tasks.py`): "do X overnight /
  at 2am" → code/research/self_upgrade/reflection; durable across restarts
  (`artifacts/runtime/scheduled_tasks.json`) with catch-up for missed jobs;
  re-armed at boot via `restore_scheduled_tasks()`. GUI: Tasks main tab.
- **Project workspaces** (Labs): bundle files/folders + memory namespace
  (`runtime/active_project.py`) + commands + owned background tasks; Save State /
  Resume (`runtime/state_providers.py`).
- **New generation runtime:** `runtime/evidence_planner.py` (plan→gather→consume),
  `runtime/report_pipeline.py` (multi-stage grounded docs), `runtime/background_deepening.py`
  (quick-mode async deepen). See `grounding_and_evidence.md`.

## Update Advisory — 2026-06-08 (timed commands + multi-command)
- **"Do <any command> at <time>" → background workers.** The router `schedule_prepass`
  (`execution/router_enhanced.py`) now fires on a future-time marker + ANY imperative
  (open/play/get/close/run + heavy verbs + known schedulable actions), not just the old
  fixed verb list. It runs BEFORE `portable_route`, so "open spotify at 8pm" / "get the
  news at 7am" / "close steam in 2 hours" / "get a morning report for 7:15 tomorrow"
  SCHEDULE instead of running now. Excludes alarms/timers (their own handlers) and
  questions. The scheduled `request` is the **clean, time-stripped command** so the
  worker (`_worker_research` → `eng.process`) executes the action once and never
  re-schedules. `SCHEDULE_TASK` now sets `recurring=True` on "every/each/daily/nightly".
- **Multi-command chaining.** `eli/runtime/command_splitter.py::split_commands` +
  router `multi_command_prepass` → a `MULTI_COMMAND` action; the executor handler routes
  & executes each segment in order and combines results ("close steam and set an alarm
  for 7am", "open spotify then play X"). Router+executor level → works for voice
  (GUI_DIRECT_EXEC) and typed (process). Strong guard: every segment must start with an
  imperative verb (so "play tom and jerry" / "open the file and folder manager" stay
  whole; questions go to the question-splitter). Sequential today; the DAG orchestrator
  is ready for parallel fan-out of independent ("and"-joined) commands.
- **Standing nightly jobs** (durable, recurring, re-armed at boot): engine-eval +
  full test report; ELI-assisted test generation. Kinds now:
  code/research/self_upgrade/reflection/eval/testgen/lora.

## Update Advisory — 2026-06-08 (model-grounded intent resolution)
- **Unmatched phrasings now resolve with the model, not a blind chat.** The deterministic
  regex router returns `fallback.chat` at confidence 0.6, which cleared the engine's
  `>0.5` trust gate — so the *existing* LLM-intent fallback was dead code and every
  near-miss dropped to a CHAT that couldn't act (and hallucinated facts like the date).
  `engine._parse_intent` now treats `fallback.chat` as **unmatched** (a real rule match
  still wins the fast path, no model call) and routes it through a rewritten resolver
  (`cognition/llm_intent.py`) that is **grounded in ELI's real `SUPPORTED_ACTIONS`
  catalogue** (validated, args extracted, CHAT default). Live 13/13 on the near-miss
  class — date→DATE (grounded, no web hallucination), "set the volume to 40%"→VOLUME,
  hub/dictation/gaze/workspace/code_solve/data_fabricator — with **no phrasing regexes
  added**. This is the "decide" layer using intelligence; the deterministic fast-paths
  remain for matched commands.
- **Note on routing fragmentation (debt):** the action is currently decided in four
  places — `router_enhanced` (regex), `portable_intent_contract`, `engine._parse_intent`
  (the resolver), and the GUI's direct-exec — and the verbatim/direct return in two (GUI
  + engine). This duplication is what caused by-path inconsistencies (e.g. a command
  returning verbatim via the GUI fast-path but synthesised via `process()`); consolidation
  is the standing cleanup (see `decomposition_plan.md`).
