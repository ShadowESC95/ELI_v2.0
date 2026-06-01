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
- `agent_bus.md` — *superseded* by `orchestration_and_agents.md` (bus-only,
  earlier draft; kept for now).

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
