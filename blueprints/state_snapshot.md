# ELI MKXI — Current State Snapshot (2026-06-07)

Authoritative, freshly-measured summary of the whole project after this session's
work. Numbers are measured on ELI's real interpreter (`.venv/bin/python`), not the
agent's system python. Deeper detail lives in the companion blueprints
(`project_overview.md`, `architecture.md`, `orchestration_and_agents.md`,
`grounding_and_evidence.md`, `capabilities_and_actions.md`, `complete_findings.md`).

## Scale (measured)
- **129,955 LOC** across **346** `.py` files under `eli/`.
- **196** manifest capabilities (`capability_manifest.json`): **157** in the
  executor `SUPPORTED_ACTIONS`, **151** routable, **13** plugin-backed.
- **12 main GUI tabs**; **14** bus agents + the CodeAgent; **4** SQLite stores
  (user / agent / system_index / coding_memory).
- ~277 commits.

## Tests & eval (measured on `.venv`)
- **6,415 tests collected; 6,371 passed, 0 failed, 2 xfailed, 42 skipped.**
- Composition: original unit/regression/integration (~2,350) + **`tests/claims/`**
  (~3,970 — examines the project vs its claims: every module compiles + core imports;
  every manifest capability well-formed + flags match the live executor; every
  SUPPORTED_ACTION handled; every documented action reachable; activation phrases;
  blueprint refs resolve; structural/behavioural claims; **symbol inventory** = every
  public function/class/method is a real introspectable callable) + the meta-tests
  for the doc pipeline, evidence planner, and test generator + generated tests.
- **Eval harness:** 41 cases = **38 router (auto-run under pytest)** + **10 engine
  (model-backed)**. The engine board + full report now refresh **nightly** (scheduled
  `eval` task), as does ELI-assisted test generation (`testgen`).
- **2 xfail = documented, intentional:** `MOUSE_CONTROL` bare "left click" → GAZE_CLICK
  by design; one grounding-mode case.

## GPU / inference (corrected this session)
ELI runs on the **GPU**. `.venv/bin/python` → `llama_cpp.llama_supports_gpu_offload()`
= **True** (llama-cpp-python 0.3.23, CUDA; driver 595.71.05, CUDA 13.2, nvcc 12.8).
Model loads with `ggml_cuda_init: found 1 CUDA device`, layers offloaded to the 2060
Super; a short generation ≈ **1.2 s**. (An earlier "CPU-only" finding was a sandbox
error — the agent's bare `python` is the *system* interpreter with a CPU wheel, not
the venv ELI uses. No rebuild needed.)

## What this session added / fixed (all on `main`, green)
- **Grounded generation:** evidence-planner (plan→gather→consume across code/web/
  memory/runtime agents) + multi-stage `report_pipeline` (outline→sections→review)
  for documents/scripts/projects, with confidence-driven deeper-tier re-gather.
- **Grounded perception/introspection:** "what's on screen" → real vision glance;
  identity/awareness/cognition queries gather-then-summarise (no data dumps, no
  weights-only answers).
- **Autonomy/self-awareness tick** wired into the proactive daemon (governed, 30-min:
  code-monitor + self-model refresh + goal/scheduler proposals).
- **Self-correctness loop:** auto test report on every pytest run
  (`artifacts/test_report.md`); `RUN_TESTS` + `GENERATE_TESTS` actions ELI can run
  and summarise; the report is an evidence channel for upgrade proposals; nightly
  `eval` + `testgen` scheduled (durable + recurring).
- **GUI:** Report Builder promoted to a main tab; Files-tab document converter
  (pdf/docx/doc/odt/rtf/html/md/tex/epub/txt + lualatex).
- **Fixes:** habit 00:00 offer; EXAMINE_CODE↔GUI_RUNTIME_AUDIT route collision;
  grounding quick-mode hedge regression; 4 router-gap fixes; venv test-collection
  error; scheduled-store test isolation. All prior known failures resolved.

## Honest weaknesses (unchanged; from `complete_findings.md`)
- **God-files:** `executor_enhanced.py`, `engine.py` (~12k each) + the GUI (~10k).
- **~2,565 swallowed `except Exception`** — failures are absorbed, not surfaced.
- **~15 load-bearing `globals()`/install-time wrappers** (netguard, adaptive GGUF
  loader, middleware table) — architecture, not test-maskers, but a fold-in target.
- **Duplication:** two image engines; overlapping `runtime/*_response`/`*_surface`.
- **Repo hygiene:** root junk (`...`, one-off `patch_*.py`, `verify_*.sh`, zips).
- **The real ceiling is the local model** — the body/memory/grounding/awareness are
  frontier; the *mind* is whatever local GGUF is loaded (model-agnostic → a swap).

## Verdict
The architecture is genuinely frontier for a local, model-agnostic, self-honest
personal AI — and it now **tests itself, evals itself nightly, writes its own tests,
and grounds its generation in real evidence**, on the GPU. The open work is
engineering debt (god-files, swallowed exceptions, dup/hygiene) and the model
ceiling — both known, both phased, neither blocking.
