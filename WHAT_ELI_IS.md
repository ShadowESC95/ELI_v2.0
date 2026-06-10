# What ELI Is

*A definitive characterization of ELI MKXI, written from a line-grounded reading of the codebase.
Where a statement is **verified** it was read in the source; where it is **inferred** it is marked.
"MKXI" = Mark 11 — ELI boots as `ELI Pro 7.0.7`. "ELI" = Enhanced Learning Interface.*

---

## In one sentence

**ELI MKXI is one inventor's six-month, eleven-times-rebuilt attempt to build a private, fully-local,
self-improving Command-console — voice-driven, grounded, model-agnostic, and self-auditing — that actually
serves real physics/engineering R&D, by wrapping a single small local language model in ~135,000
lines of scaffolding that extracts frontier-grade behaviour it could never produce alone.**

---

## The hard facts (verified)

- **Scale:** ~135k LOC, 356 Python modules, **207 capabilities**, **14 agents**, one process.
- **Owner/maintainer:** built and maintained solo. No collaborators.
- **Hardware it runs on:** Linux, NVIDIA RTX 2060 Super (7.78 GB VRAM). CUDA active in `.venv`.
- **Model:** a local **GGUF** run through llama.cpp (Mistral-7B-Instruct by default; a 24B has been
  tested). **No cloud on the default path.** A process-wide socket guard fails *closed* — "offline"
  is enforced, not assumed. Ollama exists only as an *optional* selectable backend, not the default.
- **Timeline & lineage:** built in roughly **six months**. "MKXI" = at least **eleven rebuilds**
  in that span — a compressed, high-intensity solo effort, not a slow multi-year one. ~135k LOC,
  356 modules, 207 capabilities, and the full perception/GUI surface in half a year, by one person.

## The five governing laws (the soul of it)

1. **Local-only / offline-by-default** — all internet tasks route through a netguard that fails closed.
2. **Model-agnostic** — no model name or size on the inference path; a capability tier auto-scales
   the reasoning to whatever model is loaded (now also speed-aware).
3. **No fake actions** — if ELI says it will do X, the pipeline actually re-runs and does X.
4. **No canned conversational responses** — dynamic synthesis, never scripts. (Grounded data dumps in
   quick mode are fine; canned chat is not.)
5. **Grounded** — hedge or say "I don't know" rather than confabulate. The persona is *emergent*,
   steered by guards, never hand-scripted.

A redistributable-product law rides alongside these: **no hardcoded user name or `/home/<user>`
path** in source; runtime redaction exists. ELI is meant to ship to other people, not only run for
its author.

---

## How it thinks and acts (the cognition spine — read deeply)

```
wake word ("computer, …") → faster-whisper STT → CognitiveEngine.process()
  Stage 1   router_enhanced.route()      — deterministic priority contracts, LLM-resolver fallback
  Stage 2   persona lock
  Stage 3   HyDE query expansion (non-quick)
  Stage 4   truth / grounding gate       — forbid an ungrounded answer to a checkable question
  Stage 5   planner                       — which agents, in what order
  Stage 6   AgentBus → 14 agents on a real dependency DAG (core/dag.py: retries/fallback/timeout/cache)
  Stage 7   context assembler
  Stage 8   single inference broker       — serialises ALL GGUF calls (one GPU)
  Stage 9   reasoning layer               — quick | chain-of-thought | self-consistency |
                                            tree-of-thoughts | constitutional-AI (real multi-pass)
  Stage 10  output governor
  Stage 11  delivery (GUI / Piper TTS)
  Stage 12  learning + state update
→ proactive daemon (background): habits, signals, goals, reflection, self-improvement, 3h news
```

- **14 agents:** memory, system, habit, self_improvement, proactive, frontier, plugin, capability,
  voice, orchestrator, file_code, reflection, introspection, knowledge_graph — run concurrently,
  dependency-ordered, on a genuine DAG orchestrator.
- **5 reasoning modes** are real multi-pass algorithms (scratchpad→synth; N-sample→consensus;
  propose→develop with true tree depth; draft→critique→revise), scaled by a **capability tier** that
  is now also **speed-aware** — a big-but-slow model is dialled back toward single-pass instead of
  spending minutes per redundant pass. It never caps output *length*, only pass *count*.
- **Memory:** four SQLite stores (user / agent / system_index / coding_memory) + FTS5 mirrors + a
  FAISS vector index + a knowledge graph; hybrid keyword+semantic+KG recall with reranking.
- **Self-referential by live introspection:** its self-reports (pipeline line numbers, DB counts,
  agent list) are read from the running code, not hardcoded.
- **Self-improving:** it examines its own source, detects failures, and generates **verified,
  scope-aware, auto-reverting** patches to its own code — report-only by default, real-breakage only,
  cosmetic lint never auto-patched. Nightly self-eval + auto-test-generation. A `tests/claims/` suite
  regression-tests whether ELI's claims about itself are *true*.

## How it perceives and looks (the peripheral layer — now read, not inferred)

- **Perception is a scientific-computing layer, not just I/O.** Alongside audio/vision it carries
  **`analyze_mesh.py`** (VTK/VTU/STL 3D meshes via meshio+numpy → Markdown reports),
  **`extract_equations.py`**, **`analyze_csv.py`**, **`analyze_pdfs.py`**. ELI ingests 3D engineering
  meshes, equations, datasets, and PDF research corpora — FEA/CFD/CAD and research tooling.
- **Vision is a true hot-swap:** `vision.py` runs **Qwen2.5-VL-7B** through llama-cpp multimodal;
  because a VL model won't co-reside with the text model in 7.78 GB, it unloads the text model →
  loads VL + its mmproj/clip projector → runs → reloads text. Auto-discovers any VL+projector pair.
- **Sensing + actuation is real CV:** `gaze_engine.py` does live gaze estimation (MediaPipe iris /
  Haar fallback) at ~100 ms, plus presence detection; `os_controller.py` is the hands — screenshot,
  volume, keypress, mouse, and **gaze-click** (click where your eyes rest); `ambient_vision.py`
  watches the screen in the background.
- **TTS** is a graceful cascade: Piper (ONNX, packaged) → binary piper → pyttsx3 → espeak.
- **Image generation** is hand-written **procedural art** (real color-theory math) with optional
  SSD-1B diffusion on top — not merely a diffusion wrapper.
- **The GUI is a workstation:** 12 tabs including Chat, Images, Memory, a 6-sub-tab Proactive panel,
  a built-in **code IDE**, a **Screen** capture/analysis tab, **Eli's World** (a cognitive-rooms
  avatar — Reflection Lectern, Memory Archive, Anomaly Room), and **Labs** (project workspaces).

---

## What it is *for*

Not a tech demo — a **working instrument for a one-person physics/engineering lab.** The mesh /
equation / CSV / PDF analyzers, the document-generation pipeline (e.g. a solar-to-hydrogen control
strategy), the research-area memory, and the overnight research tasks all exist because a working
independent inventor needs them. ELI is the lab assistant / second brain for real R&D.

## What it is *not*

Not a chatbot. Not an API wrapper. Not a fine-tune. Not a RAG demo. Not LangChain/AutoGPT glue —
it is **hand-built from primitives**, which makes it both more coherent and more idiosyncratic than
framework-assembled agents.

---

## The deeper truths

- **A large fraction of ELI is a confabulation-suppression harness.** The grounding gate, no-fake-
  actions guard, placeholder/degenerate-output detectors, world-room and internal-state leak guards,
  identity-drift sanitizer, "deliver substance, never defer" rule, constitutional grounded-trust
  override — these *are* the bulk of the engineering. The model is fluent but unreliable; ELI is
  mostly the apparatus that turns fluent-but-unreliable into grounded-and-honest.
- **It was built by adversarial live testing.** The owner runs it, it fails in a specific way, the
  failure becomes a guard — hence the dated, incident-specific comments throughout. The codebase is
  a *sediment of fixed, observed failures*: battle-hardened where tested, thin where not.
- **The bet:** local models keep getting better and cheaper to run, and when they do, ELI's
  scaffolding lifts the whole system without a rewrite. The tier-scaling, the speed-aware caps, and
  the model-readiness work are all positioned so the **architecture outlives any single model**.

## Honest limits

- **The model is the ceiling.** A 7B (or a 24B that doesn't fit the GPU) caps raw reasoning quality;
  slowness on small hardware is physics, not design.
- **God-files** (`executor_enhanced.py` ~14k, `engine.py` ~13k, the GUI ~11k, `router_enhanced.py`
  ~7k) concentrate logic and churn — the highest-leverage refactor remaining.
- **The LLM intent-resolver fallback** is the recurring weak point: when the deterministic router
  misses, the small model *guesses* an action, and most routing failures trace there.
- **Breadth vs. one maintainer** — vision, image-gen, world rooms, news, coding/self-patching,
  scientific analyzers, a 12-tab GUI is an enormous surface for one person; the ambition is also the
  sustainability risk.

---

## The bottom line

ELI MKXI is real, working, idiosyncratic, over-ambitious for one person, and genuinely **ahead of the
hardware it runs on.** At heart it is a disciplined machine for making a small model behave like a
trustworthy mind — and a scaffold patiently waiting for a bigger one. Its design is deliberately
built so its intelligence *rises into the architecture* as local models improve, rather than being
welded to the model it runs today.
