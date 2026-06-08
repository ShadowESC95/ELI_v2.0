# ELI Grounding & Evidence Layer

The anti-confabulation system — a deterministic evidence scaffold wrapped around
the probabilistic model. This is ELI's most distinctive subsystem and the part
closest to genuinely frontier. Spans `eli/runtime/` and `eli/cognition/`.

## The core idea

For "grounded" actions (status, runtime, memory, identity, control), ELI does
**not** trust the LLM to state facts. It (1) gathers deterministic evidence from
the live system, (2) can answer directly from that evidence without the LLM at
all, and (3) when the LLM does generate, validates the output against the
evidence and rejects/repairs contradictions. The LLM becomes a phraser, not a
source.

> **Correction (2026-06-08): the "bypass" is PARTIAL and MODE-GATED — not a blanket
> bypass.** Earlier wording here and in `what_eli_is.md` ("bypasses the language model
> entirely", "without the LLM at all") overstated it. The running reality, verified
> against the engine: the deterministic verbatim return fires for a **subset** of
> actions and is **mode-gated** —
> - a small **`_verbatim_always_actions`** set (deep introspection like
>   `EXPLAIN_MEMORY_RUNTIME`) returns verbatim in **every** reasoning mode;
> - **`_deterministic_direct_payload_actions`** (status/reports + router-fast/command
>   actions: DATE/TIME, VOLUME, WRITE_NOTE, window/media/file ops, NEWS/MORNING_REPORT,
>   self-report …) return **verbatim in *quick* mode** and **synthesise in non-quick**
>   modes (`engine._bypass_persona` + `_is_grounded_control_nonquick`);
> - everything else is the model's to phrase.
>
> So the model IS in the loop for most conversational turns; the "phraser, not a source"
> principle holds where the deterministic path actually fires, not universally. A
> 2026-06-08 fix corrected the membership: the command actions were in the wrong set, so
> quick mode re-synthesised them, corrupting results ("Wrote note"→"Bought note") and
> adding latency. They are now verbatim in quick mode, synthesised in others.

## Components

### `runtime/deterministic_grounding_gate.py` (4.3k LOC)
The deterministic renderer. `render_action(action, args, user_input, mode_label)`
produces a grounded answer for control/status actions directly from runtime data
(settings, runtime snapshot, DB counts, GPU line) — bypassing the model.
`install(CognitiveEngine)` wires it into the engine. `_eli_v14_runtime_data()`
assembles the live config block (model_path, n_ctx, gpu_layers, …).

> **Code-health flag:** the file contains **seven** `render_action` definitions
> (lines 350, 1058, 2837, 3288, 3653, 3875, 4222), each marked
> `# type: ignore[override]`. They are stacked successive redefinitions where the
> last one wins — the file grew by appending new versions rather than editing in
> place. It works, but it's the single clearest example of the "added beside, not
> folded in" pattern, and it makes the effective code path hard to trace. Prime
> consolidation candidate.

### `runtime/control_contracts.py` (926 LOC)
The deterministic control path:
- `is_control_action` / `route_control_text` — recognise control/status intents.
- `build_control_evidence(engine, action, args, …)` — gather the evidence packet
  (runtime paths, DB state, bus result, trace).
- **`output_violates_evidence(text, evidence_text)`** — the gate that returns
  True when LLM output contradicts/omits the evidence; the engine uses this to
  reject a hallucinated answer.
- `compact_evidence_answer` / `finalise_control_result` — assemble the final
  grounded response.

### `runtime/evidence_ledger.py` (325 LOC)
A persistent SQLite ledger of evidence events: `record_event`, `recent_events`,
`repeated_event_signals` (detect recurring issues over N days), `status_evidence`,
`artifact_snapshot`. Gives ELI a durable, queryable record of what actually
happened.

### `runtime/evidence_arbitration.py` (195 LOC)
`EvidenceItem` + `arbitrate_evidence(limit)` + `build_evidence_context_text` —
scores and merges competing evidence into a single context block. Pairs with the
agent-bus confidence aggregation (`_score_tool_result`).

### `runtime/memory_evidence.py` + `runtime/retrieval_packets.py`
`collect_memory_evidence` / `build_memory_evidence_text` turn memory hits into an
evidence block. `retrieval_packets` builds `StagePacket`s for each retrieval
stage (parallel-retrieval, hybrid-merge, rerank, source-trace) — provenance so
the pipeline can show *where* a fact came from.

### `cognition/output_governor.py` (794 LOC)
Post-generation governor: `govern_output(text, is_grounded)`,
`normalize_assistant_text`, `validate_against_evidence`, plus a family of
drift-repair functions — `strip_generic_ai_identity_drift` (kills "As an AI
language model…"), `repair_local_persona_drift`, `repair_self_user_confusion`
(fixes the model conflating itself with the user), `clean_response_style`. The
last line of defence before text reaches the user.

### `cognition/grounded_status.py` (644 LOC)
`direct_grounded_answer(user_text)` — fully deterministic answers for identity /
memory-inventory / status questions, assembled from the DBs
(`format_user_identity`, `format_memory_inventory`, table distributions). No LLM.

### `runtime/grounded_remediation.py` (1.3k LOC)
The failure→repair loop. When an action fails (app won't open, path missing,
browser/IDE absent), it: `diagnose_app/path/browser/ide` → `build_repair_plan`
→ `offer_for_result` ("want me to install X?") → `handle_confirmation` (consumes
yes/no) → `execute_pending_plan`. Stateful pending-repair tracking +
`explain_last_failure`. This is what makes failures conversational and
recoverable instead of dead ends.

## How it fits the pipeline

1. Router classifies action. Control/grounded actions enter the deterministic
   path.
2. `build_control_evidence` / `collect_memory_evidence` gather facts.
3. PHASE45 deterministic bypass: for many status actions `render_action` /
   `direct_grounded_answer` answer **without** the LLM.
4. If the LLM generates, `output_violates_evidence` + `validate_against_evidence`
   gate it; `govern_output` cleans drift.
5. `grounded_remediation` handles action failures with an offer/confirm loop.
6. `evidence_ledger` records the event for future `repeated_event_signals`.

## Honest assessment

- **Strong (genuinely):** very few local-LLM projects build a deterministic
  evidence layer at all, let alone one this thorough — direct-answer bypass,
  output-vs-evidence rejection, drift repair, a persistent ledger, and a
  conversational remediation loop. This is the subsystem that most justifies the
  "frontier" label.
- **Weak:**
  1. The **seven stacked `render_action` overrides** in a 4.3k file — the
     effective behaviour is whatever the last definition does; the earlier six
     are dead weight that obscure the real path. Consolidate to one.
  2. **Overlapping surfaces** — `grounded_status`, `control_contracts`,
     `deterministic_grounding_gate`, and the `runtime/*_response` / `*_surface`
     modules all render grounded answers with partial overlap. The boundaries
     between "who renders the final grounded string" are blurry.
  3. Confidence/grounding is heuristic (additive score + threshold +
     `output_violates_evidence`), not a formal proof — fine, but it's a gate, not
     a guarantee.


---

## Update Advisory — 2026-06-01
- A parallel verification layer now exists in `eli/coding/` (sandbox execution + synthesized tests + bug classification). Grounded code generation (GENERATE_SCRIPT) routes through it. Consider exposing the coding sandbox as another evidence source for the grounding gate.
- The 7 stacked `render_action` overrides remain the top consolidation target here (unchanged).


---

## Update Advisory — 2026-06-07
- **Governance consolidated:** `output_governor.py` is now canonical; `response_governance.py` + `response_sanitizer.py` are shims. The `normalize_response` signature collision (two modules, swapped args) is fixed — the GGUF-artifact cleaner is now `clean_gguf_artifacts(response, user_input)`, distinct from the governor's `normalize_response(user_input, text)`; the engine's defensive try/except-TypeError was removed.
- **Gate cleanup (verified):** the v9–v14 `render_action` layers are an ACTIVE delegation chain (the policy engine delegates through them), NOT dead code. One genuinely-orphaned fragment (`_eli_v14_render_action_legacy`, never installed) was removed (−45 lines), proven safe with a regression oracle (78 action×mode×input cells byte-identical; only RUNTIME_AUDIT differed — and it differs without the edit too, being live GPU/timestamp data). The full 7-layer flatten is deliberately NOT done (risky, readability-only).
- **Runtime audit** now includes LIVE health probes (plugin_manager, memory, agent_bus, habit_integrity, recent_failures) so RUNTIME_AUDIT catches method-level faults + data corruption + logged failures, not just static source issues.

---

## Update Advisory — 2026-06-07 (evidence-routing + generation grounding)
- **Evidence planner** (`runtime/evidence_planner.py`) — the gather-before-generate
  step for generative tasks. `plan_channels()` is hybrid: a deterministic signal
  floor ∪ a model proposal (model only in non-quick modes) over a fixed set of REAL
  sources — `code` (code_examiner tier-1/2 always, tier-3 LLM review in deep modes
  + file_code scan + self_improvement signals + blueprint), `web` (net-gated
  WEB_SEARCH), `memory` (recall), `runtime` (RUNTIME_STATUS). `gather()` runs the
  real tool per channel; bounded, exception-isolated; kill switch
  `ELI_EVIDENCE_PLANNER=0`. A central hook at the top of `_execute_impl` attaches
  the evidence to every `_GENERATIVE_EVIDENCE_ACTIONS` call (docs/scripts/projects).
- **Multi-stage document pipeline** (`runtime/report_pipeline.py`) — chat
  "generate a document" runs PLAN (gather→outline) → DRAFT sections → REVIEW→REVISE,
  grounded in the gathered evidence. Confidence retries: a degenerate/short stage
  retries once; THIN evidence triggers a deeper re-gather across more agent tiers
  (`tree_of_thoughts`) before drafting. Single-pass is the fallback; kill switch
  `ELI_DOC_PIPELINE=0`.
- **Confidence → tiers (existing, reaffirmed):** `grounding_escalation.py` already
  escalates the reasoning-mode tier one step per iteration and scales the gather for
  low-grounding CHAT turns; EXTERNAL facts hit web→hedge in every mode, LOCAL facts
  in quick defer to async background-deepening.
- **Introspection gather-then-summarise:** identity/awareness queries
  ("audit your identity", "what are you aware of") now have the IntrospectionBusAgent
  RUN the grounded action (ELI_IDENTITY_AUDIT / AWARENESS_STATUS) and return it as
  EVIDENCE — the persona summarises it, never a verbatim data dump, never from weights.

---

## Update Advisory — 2026-06-08
- **Bypass claim corrected** (see the box under "The core idea"): the deterministic
  verbatim return is **mode-gated and partial** (verbatim-always set; quick-mode-only
  for the payload/command set; synthesis in deeper modes), not a blanket "no LLM". A
  set-membership fix put the command actions (WRITE_NOTE/VOLUME/window/media/file) into
  the quick-verbatim set — they were being re-synthesised in quick mode, which corrupted
  results ("Wrote"→"Bought") and added latency.
- **Anti-confabulation via routing** — the new model-grounded intent resolver
  (`cognition/llm_intent.py`, wired in `engine._parse_intent`) pulls near-miss factual
  phrasings INTO the grounded path instead of a blind CHAT: e.g. "what day is it" now
  resolves to the deterministic `DATE` action rather than falling to a chat/web turn that
  hallucinated the date. It resolves against ELI's real `SUPPORTED_ACTIONS` catalogue and
  defaults to CHAT — intelligence, not phrasing regexes.
