# ELI Blueprints

Grounded architecture documentation for ELI MKXI. Each doc reads the real code,
states what's there, and gives an honest strength/weakness assessment. Written
from deep reads of the core + a full structural/code-health sweep — not a
line-by-line read of all 315 files; claims are grounded in what was inspected.

## Index

- **[project_overview.md](project_overview.md)** — start here. What ELI is,
  scale (116,958 LOC / 315 files), architecture by layer, the honest verdict on
  "frontier", and the highest-leverage work.
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
   - **~2,322 `except Exception:`** swallowing failures into silent fallbacks —
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
