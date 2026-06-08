# ELI Blueprints

Grounded architecture documentation for ELI MKXI. Each doc reads the real code,
states what's there, and gives an honest strength/weakness assessment. Written
from deep reads of the core + a full structural/code-health sweep — a deep read this session covering every package's structure + the algorithm-bearing bodies; claims are grounded in what was inspected.

## Index

- **[what_eli_can_do.md](what_eli_can_do.md)** — the capability showcase: every
  thing ELI can actually do (conversation, OS/window control, gaze, voice, vision,
  image generation, media, web/news, files, Report Builder, File Chat, coding,
  memory, self-improvement, proactivity), the 12 tabs, and full customisability.
  Strengths only, grounded, no embellishment. The "what you get" doc.
- **[what_eli_is.md](what_eli_is.md)** — the human-first portrait: what ELI is and
  what it does for your actual day (layman + tech head), with the genuine selling
  points foregrounded — ownership, model-agnosticism, self-honesty,
  self-improvement, embodiment. Read this for the "why it matters."
- **[complete_findings.md](complete_findings.md)** — the definitive deep-read
  record (2026-06-07): corrected numbers, every correction to earlier statements,
  verified subsystem facts, the fixes shipped this session, and the honest limits.
  Unbiased, just facts.
- **[capability_catalogue.md](capability_catalogue.md)** — exhaustive, ground-truth
  catalogue of all actions (205) + every package's modules (5 parts).
- **[project_overview.md](project_overview.md)** — start here for the engineering
  view. What ELI is, scale (126,619 LOC / 336 files), architecture by layer, the
  honest verdict on "frontier", and the highest-leverage work.
- **[orchestration_and_agents.md](orchestration_and_agents.md)** — the real
  topology: `AgentOrchestrator` (12-stage pipeline) vs the 14-agent `AgentBus`,
  the ReAct loop, the typed `ExecutionPlan`, selection, timeouts, trust.
- **[memory.md](memory.md)** — SQLite/FTS5 + FAISS + knowledge graph, the
  `recall_memory` hybrid retriever, weight decay, the `Memory` god-class.
- **[grounding_and_evidence.md](grounding_and_evidence.md)** — the
  anti-confabulation layer: deterministic grounding gate, evidence ledger/
  arbitration, control contracts, output governor, grounded remediation.
- **[security.md](security.md)** — fail-closed shell/path/app gates, prompt-
  injection guard, SQL identifier validation, agent trust registry, vetted-script
  approach.
- **[perception.md](perception.md)** — local vision (hot-swap + co-resident),
  STT (+ output ducking), TTS (Piper/espeak), cross-platform OS control.
- **[inference_and_hardware.md](inference_and_hardware.md)** — model-agnostic
  GGUF inference + broker + lock, free-VRAM-aware hardware profiling, adaptive
  boot, settings, paths.
- **[learning.md](learning.md)** — the LoRA self-training pipeline (human-gated,
  PII-redacted, operator-invoked; trains a separate Phi-3 base).
- **[gui.md](gui.md)** — the PySide6 desktop app, launcher/first-boot, Labs
  scientific workspace.
- **[runtime_planning_world.md](runtime_planning_world.md)** — runtime response/
  introspection surfaces, the proactive planning layer, the world/autonomy model,
  tools, and the plugin system.
- **[coding_agent.md](coding_agent.md)** — the frontier coding agent (`eli/coding/`):
  planner/implementer, mandatory execution feedback, UCB tree search, verification
  gating, test synthesis, semantic bug classification, long-term bug/fix memory,
  patch-based refinement. Wired as the `CODE_SOLVE` action.
- **[coding_agent_test_prompts.md](coding_agent_test_prompts.md)** — runnable prompt
  suite for exercising the coding agent against the live model.
- **[dag.md](dag.md)** — the project-wide DAG engine (`eli/core/dag.py`) and how the
  **agent bus** and the **coding engine** both run on it (topological layers,
  upstream→downstream, subtask graphs).
- **[background_tasks.md](background_tasks.md)** — unified code generation (GENERATE_SCRIPT
  + self-upgrade route through the coding agent) and the in-process background task
  manager (heavy work runs on threads; `CHECK_JOB`/`BACKGROUND_JOBS`).
- **[state_snapshot.md](state_snapshot.md)** — **authoritative current-state snapshot**
  (measured): scale, capabilities (205), tests, GPU, and every recent change. Start here
  for "what is true right now".
- **[dag_orchestrator.md](dag_orchestrator.md)** — the DAG elevated to a full execution
  orchestrator (parallel/retries/fallback/cache/telemetry), wired through agents +
  evidence gather; Test & Review; SELF_IMPROVE/GENERATE_PROJECT on the coding/planner DAG;
  multi-command + timed commands.
- **[lora_pipeline.md](lora_pipeline.md)** — LoRA audit + the wired, model-agnostic
  training pipeline (preflight→build→train→eval) + `LORA_STATUS`/`LORA_TRAIN`.
- **[installation.md](installation.md)** — one-click cross-platform installers
  (Linux/macOS/Windows/Android), frozen lock, GPU verify, DB init, CUDA-toolkit option.
- **[decomposition_plan.md](decomposition_plan.md)** — full code-review + god-file
  decomposition plan (keep good code; fix real problems) — **plan only**.
- **[proposal_total_awareness.md](proposal_total_awareness.md)** — dated proposal
  (test→report→ELI loop, total-awareness roadmap, GPU erratum).

## Cross-cutting themes (recurring across docs)

1. **Strong ideas, several genuinely frontier subsystems** — the grounding/
   evidence layer, fully-local model-agnostic inference, fail-closed security,
   integrated multimodality.
2. **The dominant weakness is engineering discipline, not vision:**
   - **God-files** — `executor_enhanced.py` (12k), `engine.py` (12k), the GUI
     (10k), and large files in grounding/STT/labs.
   - **Over-fragmentation / "added beside, not folded in"** — ~15 overlapping
     `runtime/` response surfaces, two image engines, seven stacked
     `render_action` overrides in the grounding gate, multiple plan/queue
     representations.
   - **~2,565 `except Exception:`** swallowing failures into silent fallbacks —
     the reason bugs only surface via runtime logs.
   - **Repo hygiene** — root junk, committed binaries/diag outputs, a non-green
     test suite.
3. **The gap to "ground-breaking" is subtraction + observability**, in order:
   tame error-swallowing → split god-files → delete duplication/clutter + green
   the tests → consolidate the `runtime/` surfaces.


---

## Update Advisory — 2026-06-01
- Index extended this session: added `agent_algorithms.md`, `dag.md`, `background_tasks.md`, `coding_agent.md`, `coding_agent_test_prompts.md`. Cross-cutting verdict still holds; the DAG engine + coding agent + background workers are net-new components layered on top.
- TODO next pass: keep this index in sync as files grow; re-run the LOC sweep (project_overview table predates `eli/coding/`, `eli/core/dag.py`, `eli/runtime/background_tasks.py`, `eli/gui/coding_tab.py`).


---

## Update Advisory — 2026-06-07
- **Stats refreshed:** 126,619 LOC / 336 Python files / 128 test files / 193 capabilities / 14 bus agents / ~2,565 `except Exception` / 231 commits.
- **Landed since last advisory (all on `main`, tested):** governance consolidation (3 overlapping normalizer modules → canonical `output_governor` + shims; `normalize_response` signature collision fixed → `clean_gguf_artifacts`); failure logging consolidated into ONE store (`agent.sqlite3`; executor dual-write removed; `mark_failure_resolved` + status-filtered reads); context-bloat **quality cap** on the synthesis prompt (`ELI_SYNTH_MAX_PROMPT_CHARS`) that fixed the `-`/`-G` degeneration; **user-tunable cognition** (new `eli/core/cognition_tunables.py` + a GUI ‘🧠 Cognition’ tab exposing every gather limit); agent gathering deepened (file_code searches the whole repo; memory multi-hop; capability/voice triggers broadened); habit scheduler now actually runs active app-launch habits + self-heals legacy `00:00` rows; action-synonym normalisation (NEWS_SEARCH→NEWS_FETCH, DAILY/WEEKLY_REPORT→MORNING_REPORT, …); plugin-manager NameError fixed; folder drag-drop inserts a bare path; runtime-audit gained **live health probes**; the grounding gate's one provably-dead v10 fragment was removed (oracle-verified).
- **Cross-cutting verdict update:** the eval suite is now **green and runs under `pytest`** (`tests/test_eval_cases.py`); two of the listed debts are materially reduced (governance over-fragmentation; the dual-DB failure split). The god-files and the `except Exception` count remain the top open items.

## Update Advisory — 2026-06-07 (continued)
- **Stats refreshed:** ~128.8k LOC / 343 files / ~110 test files / **194 capabilities**
  (155 SUPPORTED_ACTIONS, 164 routable) / 14 bus agents + CodeAgent / **12 main GUI tabs**.
- **Test suite GREEN:** `pytest tests/` = 2356 passed / 45 skipped / 1 xfailed / 0 failed.
- **Landed (all on `main`, tested):** evidence-planner + multi-stage `report_pipeline`
  for grounded doc/script/project generation (confidence→deeper-tier re-gather);
  Report Builder promoted to a main tab; Files-tab document converter (pandoc+lualatex+
  LibreOffice: pdf/docx/doc/odt/rtf/html/md/tex/epub/txt); autonomy/self-awareness tick
  wired into the proactive daemon (governed); introspection gather-then-summarise for
  identity/awareness; grounded vision for "what's on screen"; habit 00:00 fix;
  EXAMINE_CODE/GUI_RUNTIME_AUDIT route disambiguation; new reference
  `capabilities_and_actions.md` (auto-generated, in sync with the manifest).

## Update Advisory — 2026-06-08
- **Stats:** 132,969 LOC / **351** files / **205** capabilities (166 SUPPORTED_ACTIONS) /
  151 test files. New actions: `WAKE_TRAIN`/`WAKE_ENROLL`/`WAKE_SET`/`TRAIN_VOICE`.
- **Reliability:** MULTI_COMMAND + FIX_FILE crash fixes; LoRA `build_job` builds the
  dataset (no more ×30 error); vision **VRAM cliff** fixed (reload restores full-GPU).
- **Routing by intelligence, not hardcodes:** the model-grounded intent resolver
  (`cognition/llm_intent.py`) now actually runs on unmatched phrasings (the engine gate
  was dead), pulling factual near-misses into grounded actions (date→DATE). See
  `grounding_and_evidence.md`, `runtime_planning_world.md`.
- **Bypass claim corrected:** the deterministic verbatim return is **mode-gated/partial**,
  not a blanket "no LLM" — see the correction box in `grounding_and_evidence.md` and
  `what_eli_is.md`.
- **Voice (new subsystems, see `perception.md`):** self-trained **wake word robust over
  music** (`perception/wakeword.py`) with a user-settable phrase; **voice-profile/tone**
  (`perception/voice_profile.py`) — pitch/energy/rate, question-vs-statement, and a
  labelled-emotion classifier; the per-turn tone is **wired into cognition** (the engine
  adapts its delivery). Duration-adaptive STT pause (0.5s commands / 2s after 12s).
- **Media/installer:** honest "install mpv+yt-dlp" on the play fallback; `install.sh`
  now bundles the runtime/OS-control tools.
