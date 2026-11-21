# Blueprint — Operational Realities

What the structural diagrams (`architecture.md`, `diagrams.md`,
`architecture_ascii.md`) **don't** show: cold-start, concurrency/contention,
memory eviction, failure recovery, and the testing strategy. Grounded in the
code + runtime logs. Estimates are marked *(est.)*; everything else is read from
source or measured timings.

---

## 1. Startup / cold-start latency

No wall-clock delta is printed at boot (a `window._debug_boot_ts = time.time()`
hook exists in `gui/eli_pro_audio_gui_v2_0.py` but nothing measures against it),
so the number below is reasoned from the boot sequence, not measured.

**Cost breakdown (boot order):**
| Component | Cost | Notes |
|---|---|---|
| **embedder (nomic) + FAISS** | low–med | loaded **before** the model: the window builds the vector store first, so the load plan sees the memory the embedder takes |
| **GGUF model load** | **dominant** | the model file off disk (e.g. 4.36 GB for a 7B, **15.6 GB for a 24B**) + GPU offload |
| Vision (Moondream) | none by default | loads with the text model only when `vision_coresident` is on (then first, so the text model's plan is sized to what is left); otherwise a vision request loads it when needed |
| faster-whisper `small.en` | low–med | CPU int8, or GPU int8_float16 only when the card holds it beside the language model's planned layers |
| daemons + 231-cap manifest + persona_updater | low | DB/CPU |

**Estimate *(est.)*:** ~15–40 s warm-cache on the 7B (dominated by the model load);
materially worse cold and on the 24B (15.6 GB).

**Cheap wins:** (a) lazy vision — done: nothing loads a vision model at boot unless
`vision_coresident` is set; (b) instrument `_debug_boot_ts`
to print per-stage deltas so this stops being an estimate.

---

## 2. Resource contention (daemons vs interactive)

**One shared model behind one lock** — every generation serialises on
`gguf_inference._LLM_CALL_LOCK` (the native llama.cpp lock); the engine's own
`engine.py::_gguf_lock` (an `RLock`) also guards its chat calls.

**Verified mitigation:** model-using background work uses **non-blocking acquire
+ defer**. Reflection: `self._gguf_lock.acquire(blocking=False)`, 4 retries,
then `"Reflection deferred (GGUF busy)"` and backs off → **yields to interactive
turns**. Correct pattern, and real.

**Central defer:** a generation marked as background (`set_background_inference`, or
`broker.infer(background=True)`) gets an empty reply while a conversation is live or has just
ended (`ELI_BG_DEFER_WINDOW`, 30 s by default); a background job waits instead of being
blanked (`set_job_inference`). A foreground call raises a priority flag and background
generation yields at its next token (`ELI_FG_PREEMPT=0` turns that off). Background broker
calls are also capped at `ELI_BG_MAX_TOKENS` (256). The proactive daemon, scheduled tasks,
self-improvement and the background job runner mark their calls.

**Risks (honest):**
- A model call made off the user's turn without either mark waits for the lock like a turn
  and holds it until it finishes.
- On the **24B-CPU a turn is minutes**, so a deferred daemon waits minutes for a
  window, and any unmarked background call would block your reply for minutes.
- **Non-model contention** (cheap but ever-present): the persona overlay is rebuilt at most
  once every 120 s (`persona_updater`); the proactive daemon scans the DB; the embedder is a
  *separate* model — so vector search and generation compete for the same cores or card.
  Ambient vision is off by default; when on, each glance (every 300 s by default) skips while
  the text model is generating, and swaps the text model out unless the vision model runs
  beside it (`vision_fast_no_swap`), waiting for 15 quiet minutes first when that model is
  over 8 GB.

---

## 3. Memory limits & eviction (two distinct policies)

**(a) Working-memory pins** — `cognition/working_memory.py`:
- `MAX_PINS = 20` hard cap; importance-weighted.
- `MAX_AGE_TURNS = 40` — `_evict_stale()` drops facts unreferenced for 40 turns, or for
  three days of wall-clock time (`MAX_AGE_SECONDS`), whichever comes first.
- `_evict_one()` drops lowest-importance-oldest at cap.
- Persisted `ORDER BY importance DESC LIMIT 20`.
→ a principled **importance/age LRU**, bounded.

**(b) Context-window fill (`n_ctx`)** — a *different* mechanism, and the one that
actually bites under pressure:
- `engine.py::_build_enhanced_system` budget-trims the **persona**.
- `_get_chat_response` fits `memory_context` to `n_ctx` with
  `context_budget.trim_memory_context`, which drops **whole lines, block by block**: the
  blocks lowest in `_BLOCK_PRIORITY` go first (retrieval diagnostics, the turn record and the
  period log are kept longest), and inside a block the weakest ranked hits and the oldest turns
  go first. On a recall question memory keeps at least a third of the window.
- The 20 small pins almost always fit, so **retrieved memory is what gets
  evicted under pressure, by block priority and rank** — not the pins.

**(c) Long-term store** — SQLite `memories` / `conversation_turns` grow on disk and
never fill the window directly; nothing the user said is deleted by a cap. The daily
upkeep (`Memory.run_upkeep`) moves derived rows that have faded unused to
`memories_archive` and compacts deleted memories out of the vector files; ELI's own
observations are pruned per category; the FAISS index keeps at most `MAX_ENTRIES` (50,000)
vectors. Retrieval (FTS5/FAISS/rerank top-k) gates what enters context. The real "limit" is
**retrieval selection + the context trim**, not a store cap.

---

## 4. Failure recovery — degradation, not rollback

**Grounding escalation** (`runtime/grounding_escalation.py`): each tier is
wrapped in `try/except`; a failing tier **falls through to the next**
(web → hedge for an external fact, local re-dispatch → hedge for anything else); the
engine hook is itself wrapped
(`"grounding escalation skipped"`) so total failure **degrades to the normal
CHAT answer**. **No rollback — and none needed — because the tiers are
side-effect-free reads** (web search reads; local re-dispatch is read-only).
Nothing mutates, so there's nothing to undo.

**System-wide:** failure handling is **graceful degradation** throughout
(broker → direct GGUF → failed-executor surface; failures logged to the
`failures` table). 

**Gap (honest):** **multi-step write actions** (CREATE_FILE, memory writes, a
multi-action plan) are individually atomic but **not transactional as a group** —
if step 3 fails, steps 1–2 are not rolled back. Rare on the current action set,
but real.

---

## 5. Testing strategy (two layers + the gaps)

**Layer 1 — code correctness:** **572 pytest files in `tests/` (593 with its
subfolders)** — routing patterns, contracts, executor gates, memory, kernel,
perception/voice, packaging. The full suite runs locally; CI runs a subset (below).

**Layer 2 — behavioural eval:** `tools/eval/` (see `tools/eval/README.md`) drives the
**real pipeline** and asserts on telemetry (action / grounding / response_mode /
latency) + text. Cases seeded from fixed bug-logs as permanent regression guards.

**Where each gap stands:**
1. **CI covers a subset.** `.github/workflows/cross-platform-smoke.yml` runs on every push
   to `main` and every pull request, on Linux, macOS and Windows and several Python
   versions: a list of self-contained test files, the claims suite and the eval router
   cases. Installer, GPU-pack and release workflows sit beside it. The full suite is not run
   in CI.
2. **Runtime coverage, not pytest coverage.** `tools/eval/profile_runtime.py` replays stored
   conversations and the eval cases under `sys.settrace` and reports the lines executed per
   file, which actions route and which agents fire (route, agents or engine mode). Nothing
   measures pytest coverage.
3. **Behavioural eval has 93 cases** (`tools/eval/cases.yaml`); keep adding one per bug fixed
   from a log.
4. **Latency and model comparison are recorded, not enforced.** `run_eval.py --history`
   appends pass rate and mean latency per model to `artifacts/eval/history/trend.jsonl`
   (the nightly `eval` job runs it), and `tools/eval/benchmarks/` holds the model
   benchmarks; nothing fails a release on a latency regression.

---

## 6. Recommended cheap, high-value fixes (grounded in §1–§2)

| Fix | Why | Where |
|---|---|---|
| ~~Lazy vision load~~ | done: no vision model at boot unless `vision_coresident` is on | `perception/vision.py`, `cognition/gguf_inference.py` |
| **Mark every background model call** | an unmarked call still waits for and holds the lock like a turn (minutes on 24B) | any `broker.infer` / `gguf_inference` call made off the user's turn |
| **Boot-timing instrumentation** | turns "cold start" from estimate → measured | `gui/eli_pro_audio_gui_v2_0.py` `_debug_boot_ts` |
| ~~Coverage profiler over stored conversations~~ | done: `tools/eval/profile_runtime.py` | `tools/eval/` |

> Companion docs: `architecture.md` · `architecture_ascii.md` · `diagrams.md` ·
> `tools/eval/README.md` (the measurement layer).

---

## Update — 2026-06-09 (scheduled-task dedup; clean shutdown; STT VRAM)
- **Scheduled-task dedup.** Standing nightly jobs (testgen/eval/report) were re-armed on every boot
  AND on completion with no dedup, accumulating copies (observed: 4× testgen / 3× eval).
  `schedule_request` now keeps ONE entry per (kind, request) for recurring jobs, and
  `restore_scheduled_tasks` collapses existing duplicates on boot. With the model-load VRAM
  interlock (a background worker waits for `gguf_inference.is_loaded()` and skips rather than
  cold-loading a second model), background jobs can no longer pile up or starve the main model at
  boot.
- **Clean shutdown (no segfault).** The GUI exited via `sys.exit(app.exec())`, so CPython ran
  llama.cpp + FAISS C++ destructors at interpreter teardown and segfaulted — AFTER state was
  already flushed (session summary written), so nothing was lost, but it dumped core. `main()` now
  runs the shutdown/atexit flush (memory + session summary + explicit model unload) then
  `os._exit(rc)`, bypassing the destructor pass.
- **STT no longer starves the main model:** faster-whisper is VRAM-aware. It goes on the GPU
  only when the card holds its measured footprint beside every layer the language model's
  plan puts there, else on the CPU (`ELI_WHISPER_DEVICE` overrides), so the main model keeps
  its GPU layers (on the 8 GB development card at the time, gpu_layers went from 11 to 99).
  See `perception.md`.
