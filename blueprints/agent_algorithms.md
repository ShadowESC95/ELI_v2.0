# ELI Agent Algorithms — what each of the 15 agents actually computes

> **Updated for v2.5.36.** The orchestrator runs CHAT turns in every mode and composes the bus
> at S06; other actions go to the bus directly. `_aggregate_confidence` and `critic`'s
> corroboration score both have a query-relevance term.

Your framing is the right lens: **the DAG structures the reasoning steps; RAG is
the engine that pulls the raw information during those steps.** ELI maps onto
this cleanly —

- **DAG layer (structure):** the `AgentOrchestrator` 12-stage pipeline + the
  `AgentBus` topological layers (`eli/core/dag.py`) + the coding subtask DAG.
  This is the "search → summarize → check" skeleton.
- **RAG layer (raw information):** a *subset* of the agents are retrievers
  (`memory`, `knowledge_graph`, `file_code`) plus the orchestrator's own
  HyDE→FAISS→RAG→rerank pipeline. These pull evidence.
- **Effectors / reporters:** the rest act (`system`, `plugin`) or report grounded
  runtime facts (`capability`, `introspection`, `frontier`, …).

So there are **15 specialist agents in `_ALL_AGENTS`** plus the **`AgentOrchestrator`**
that sequences them. `SpecAgent` instances and custom agents register on top.

## Roles at a glance

| Role | Agents |
|---|---|
| **Retriever (RAG engine)** | `memory`, `knowledge_graph`, `file_code` |
| **Effector (acts on the world)** | `system`, `plugin` |
| **Grounded reporter (read-only facts)** | `capability`, `voice`, `introspection`, `frontier`, `reflection`, `proactive`, `self_improvement`, `habit` |
| **Verifier (checks the others)** | `critic` |
| **Planner (emits structure)** | `orchestrator` (bus-level, descriptive) + the real `AgentOrchestrator` |

Every agent shares the same skeleton: a **relevance gate** (cheap keyword/action
test → skip with `confidence=0` if irrelevant, so the bus stays fast) → its
algorithm → an `AgentResult(ok, confidence, data)`. The bus runs them in
**topological layers** with **per-agent timeouts** (hard on the layered and flat paths; on
the default orchestrated path a slow agent is waited for and its result kept), then
`_aggregate_confidence`
fuses them: `contribution = evidence_quality × evidence_density × learned
calibration × query relevance`, single-agent-capped, corroboration-bonused. The
query-relevance term (2026-09-29, distinct from the per-agent gate above) is
`relevance_gate(term_overlap(user_input, representative_text))` — a fluent,
evidence-dense result with nothing to do with what was actually asked no longer
scores as highly as an on-topic one; `CriticAgent`'s corroboration score gets the
same discount (two sources agreeing with each other doesn't mean either is
on-topic). Env `ELI_AGENT_BUS_RELEVANCE_GATE` disables it.

---

## The 15 specialist algorithms

### 1. `memory` — hybrid dense+sparse retriever (RAG core)  · 5.0s
- **Gate:** `_eli_memory_should_run` (explicit memory actions, memory markers, a reply
  accepting an offer, or ≥4-word CHAT, minus self-contained knowledge questions with nothing
  personal in them; blocks stale context bleeding into commands). Skipped when the
  orchestrator has already fetched memory for the turn.
- **Algorithm:** `retrieve_for_turn` (`memory/retrieval.py`, shared with the orchestrator):
  `recall_memory` runs **FAISS vector search** (dense) and **FTS5 keyword search** (sparse)
  on every query, with a LIKE search only when FTS5 finds nothing, fused by reciprocal rank
  (`reranker.fuse_ranked_lists`); ELI's own records and unverified rows are filtered out.
  Plus `search_conversations` (FTS5), recent turns, session summaries, a second recall hop
  when the first finds fewer than five hits, claim and exact-token hits, then a rerank and a
  check for conflicting facts.
- **Out:** `{results, conv_hits, memory_context, contradictions}`. The primary RAG retriever.

### 2. `system` — deterministic action effector  · 8.0s
- **Gate:** `action ∈ SYSTEM_ACTIONS` (122 OS and runtime actions); the 14 `LLM_ACTIONS`
  (GENERATE_SCRIPT, FIX_FILE, the document and PDF/CSV analyses, CHAT, etc.) are
  **deferred** (never run inside the timed parallel phase — they'd time out +
  double-execute) and run in the engine after the bus returns.
- **Algorithm:** delegates to `executor_enhanced.execute(action, args)`, so every executor
  gate applies; a shell command (RUN_CMD, SHELL_EXEC) passes the shell gate
  (`eli/execution/shell_gate.py::check_command`) first. Confidence 0.92 ok / 0.20 fail. The
  hands.

### 3. `habit` — pattern-store reader  · 3.0s
- **Gate:** habit/routine/schedule keywords or `OPEN_APP`.
- **Algorithm:** reads `habit_rules` (all), the habits the proactive daemon detected
  (`get_detected_habits`, seen three or more times) and `habit_events('app_launch', 14d)`;
  confidence 0.70 when there are rules or detected habits, else 0.30. Detected habits become a
  `summary` line for the chat context. (Frequency mining itself lives in the proactive
  daemon; the agent surfaces what it found.)

### 4. `self_improvement` — failure-cluster surfacer  · 3.0s
- **Gate:** improve/failure/error/fix/suggest/learn keywords, or SELF_ANALYZE, SELF_IMPROVE,
  SELF_PATCH or MORNING_REPORT.
- **Algorithm:** `analyze_failures` over the last 14 days (`DEFAULT_ANALYSIS_DAYS`, up to 10
  clusters) + pending capability proposals + the self-repair goals the background proposer
  saved (tagged `self_improve`). Feeds the self-upgrade loop (see `background_tasks.md`).

### 5. `proactive` — artifact reader  · 3.0s
- **Gate:** proactive/morning-report/insight keywords or PROACTIVE_* actions.
- **Algorithm:** leads with the insight the background synthesis cached
  (`insight_synthesis.get_cached_insight`, no model call on the turn), then reads
  `artifacts/proactive/latest_{context,summary,action}.txt` + `PROACTIVE_STATUS`. Surfaces the
  background daemon's findings.

### 6. `frontier` — cross-system introspection report  · 5.0s
- **Gate:** FRONTIER_STATUS / ELI_IDENTITY_AUDIT or "full system status".
- **Algorithm:** `build_frontier_status_report` / `build_eli_identity_audit` — an
  import + wiring matrix across runtime/memory/self/proactive/image/world/labs/chatflow.
  Deterministic whole-system audit.

### 7. `plugin` — plugin effector  · 6.0s
- **Gate:** `action ∈ PLUGIN_ACTIONS` (ADD_EVENT, GET_WEATHER, LIST_EVENTS, REMOVE_EVENT).
- **Algorithm:** `execute(action, args)` into the plugin layer; silent skip
  otherwise.

### 8. `capability` — capability-manifest reader  · 6.0s
- **Gate:** capability/awareness/"what can you do" or LIST_CAPABILITIES etc.
- **Algorithm:** `execute(LIST_CAPABILITIES | AWARENESS_STATUS | CODE_CHANGES)` →
  grounded capability surface (no confabulated feature lists).

### 9. `voice` — config reporter  · 5.0s
- **Gate:** voice/tts/stt/mic keywords.
- **Algorithm:** asks the TTS router what is actually loaded
  (`tts_router.available_backends()`: the active voice and model, else espeak-ng or espeak),
  falling back to `ELI_TTS_ENGINE` only when nothing resolves; reads `ELI_MUTE` and probes the
  `faster_whisper` import. Reports, never emits audio (that's the TTS router).

### 10. `orchestrator` (bus-level) — descriptive planner  · 3.0s
- **Gate:** multi-step trigger groups (e.g. {document, save, open}), a chained request
  that splits into two or more steps (`_decompose_multistep`), the generate actions
  (GENERATE_SCRIPT, GENERATE_DOCUMENT, DOC_GENERATE, DATA_FABRICATOR) or
  GROUNDED_SYNTHESIS_ACTIONS.
- **Algorithm:** emits a structured `plan` dict, stored in the trace as
  `orchestrator_plan` (the typed `ExecutionPlan` the bus builds carries the agent selection,
  not this plan). Only its `post_actions` run (an `OPEN_IN_IDE` after a generated script or
  document, through `engine._execute_post_actions`). **Excluded from confidence aggregation**
  (it plans, it isn't evidence). Chained commands are executed by `MULTI_COMMAND`, not by this
  plan.

### 11. `file_code` — source-code RAG (grep retriever)  · 4.0s
- **Gate:** grounded query or code/file/pipeline/db keywords.
- **Algorithm:** builds query-derived regex patterns, **greps a canonical
  `files_map`** of ELI's own modules (agent_bus, engine, orchestrator, memory,
  router, …), returns `file:line: content` snippets. Lets ELI answer "which file
  does X" from real source, not memory.

### 12. `reflection` — reflection-log reader  · 4.0s
- **Gate:** reflection/pattern/noticed/insight keywords or grounded query.
- **Algorithm:** leads with the cached synthesised insight (`get_cached_insight`), then the
  recent `observations` (`cog.mem_observations`, 10 by default) and half as many dated session
  summaries → an insight list of up to 12. ELI's "what I've noticed about how you use me."

### 13. `introspection` — self-model reporter  · 4.0s
- **Gate:** architecture/pipeline/"how do you work", identity and awareness questions, or
  EXPLAIN_*_RUNTIME, RUNTIME_STATUS, COGNITION_STATUS, SELF_REPORT, ELI_IDENTITY_AUDIT,
  AWARENESS_STATUS.
- **Algorithm:** for an identity or awareness question it runs `ELI_IDENTITY_AUDIT` /
  `AWARENESS_STATUS` and returns their reports; otherwise `IntrospectionAgent` →
  `get_pipeline()` + `get_memory_stats()` + `get_runtime()` → grounded pipeline description.
  Powers honest self-explanation.

### 14. `knowledge_graph` — graph retriever (structured RAG)  · 3.0s
- **Gate:** non-empty KG.
- **Algorithm:** `context_for_prompt(query)` over `kg_entities`/`kg_relations`
  (FTS5 fuzzy entity match + relation context). **DAG edge `memory → knowledge_graph`:**
  it now seeds the query with `intent["_upstream"]["memory"]` hits (topological
  layering), so the graph lookup is conditioned on what memory just surfaced. It then walks
  two hops out from the best-matching entities (`kg.related(name, hops=2)`) and adds the
  connected relation chains as "Connected facts (multi-hop)".

### 15. `critic` — second-tier verifier (corroboration check)  · 2.0s
- **Gate:** ≥2 grounded upstream sources — self-gates to nothing on trivial turns, so it
  never fires when there's nothing to cross-check.
- **Algorithm:** the one bus agent that reasons over **other agents' output**
  (`intent["_upstream"]`) rather than the raw query — **deterministic, no LLM**. It pulls the
  representative text of every agent that finished before it this turn, measures **pairwise
  term agreement**, and emits a **corroboration-vs-contradiction** signal (mean agreement below
  0.08 counts as contradiction, confidence 0.25). Corroboration alone isn't enough
  (2026-09-29): two sources can agree strongly with EACH OTHER while both being off-topic for
  what was actually asked, so on the non-contradiction branch, agreement is additionally
  discounted by how well the sources match the *query* (`relevance_gate` over their average
  `term_overlap(user_input, text)`), not just each other. `_representative_text` moved from a
  `CriticAgent` staticmethod to a module-level function, since `_aggregate_confidence` now
  needs it too — one owner. **DAG edges:** depends on
  `memory`, `file_code`, `knowledge_graph` and `system`, so it runs in a **downstream topological layer** and
  sees their results — giving the agent DAG a real second tier instead of a flat fan-out.

---

## How the DAG sequences the RAG (your "search → summarize → check")

1. **Route** → action + reasoning mode.
2. **`AgentOrchestrator`** runs for **CHAT turns in every mode** (gradient depth): retrieval,
   then the bus's specialists. Other actions go from the engine to the **bus** directly; the
   orchestrator's **ReAct loop** (tool → observe → decide → next tool) runs only when a
   non-CHAT action is forced through it (`ELI_FORCE_ORCHESTRATOR_ALL_ACTIONS=1`).
3. **`AgentBus`** builds the **agent DAG** (`_AGENT_DEPENDENCIES`), runs agents in
   **topological layers**, passing each layer's results downstream
   (`memory` → `knowledge_graph` → `critic`). Retrievers pull evidence; reporters ground it;
   effectors act; the critic checks what the earlier layers found against each other.
4. **Grounding/evidence layer** gates the synthesis (`output_violates_evidence`).
5. **Coding tasks** decompose into a **subtask DAG** (`plan_graph`) and heavy ones
   run on **background workers** — see `dag.md` + `background_tasks.md`.

That is the literal realisation of "DAG structures the autonomous reasoning steps
while RAG pulls the raw information."

---

## Aspirational next steps (genuinely novel combinations)

These are the "never-before-put-together" moves the current architecture is one
step away from:

1. **Bias/verification agent as an explicit DAG layer.** ✅ **Shipped** — this is now the
   `critic` agent (#15 above): it depends on the retrievers (`memory`/`system`/
   `knowledge_graph`/`file_code`) and runs *after* them as a topological layer — literally "search →
   summarize → **check for corroboration/contradiction**" — feeding the grounding signal.
   (Originally proposed here as future work; now built.)
2. **A `web` retriever agent** (WEB_SEARCH as a first-class RAG node) so external
   retrieval joins memory/KG/file_code in the same layer, with the verify layer
   cross-checking sources.
3. **Calibration-aware selection.** The bus already learns per-(agent,action)
   calibration; feed it back into *selection* so chronically-zero agents are
   dropped from the DAG for that action (today the calibration only weights
   aggregation; `_select_agents_for_intent` and the mode profiles never read it).
4. **Bus↔coding bug-memory unification.** The coding engine's `bug_memory` and the
   agents' `self_improvement` failure log are two halves of one "what went wrong
   and how we fixed it" store — merging them gives ELI a single experiential
   memory across chat and code.
5. **Orchestrator stage-dict → typed `ExecutionPlan` DAG.** Fold the engine's rich
   stage plan into `ExecutionPlan.steps` as a true DAG so one plan type drives the
   whole pipeline end-to-end.


## `SpecAgent` and the measurable-agent contract

A further agent class joins the fifteen built-ins. `SpecAgent` is not hand-written
Python — it is an interpreter for an `AgentSpec` (see `orchestration_and_agents.md`),
and its algorithm is deliberately small:

```
run(user_input, intent):
    if not spec.should_run(user_input, intent.action):     # trigger gate
        return skipped                                     # costs one regex/substring
    for cap in spec.permissions:                           # capability gate
        if not permissions.check(agent, cap).allowed:
            return denied
    if not broker.gguf_ready:                              # no local model loaded
        return failed
    output = broker.infer(prompt=user_input,
                          system=spec.system_prompt,
                          max_tokens=spec.max_tokens,
                          temperature=spec.temperature,
                          background=not in_user_turn())
    verdict = spec.evaluate(output)                        # the measure
    return AgentResult(ok=verdict.ok,
                       confidence=verdict.score,
                       data={"content": output if verdict.ok else ""})
```

Three properties worth stating:

- **The trigger gate runs first and is cheap.** An untriggered turn costs a substring
  or regex test, not an inference call.
- **Confidence is earned, not asserted.** Every other agent picks its own confidence
  number. A `SpecAgent`'s confidence *is* its score against its own declared success
  criteria — the fraction of checks its output actually passed.
- **Failing its own test yields no evidence.** `data["content"]` is emptied when the
  verdict fails, so a misbehaving custom agent cannot feed unchecked text into the
  bus's evidence fusion. This directly addresses the long-standing weakness that
  evidence density "only counts known keys", by making the agent's own contract the
  arbiter.

Because a spec contains no code, `SpecAgent` bypasses the custom-agent trust chain
entirely — there is nothing to hash, scan or approve.

Inside the user's turn (`request_context.in_user_turn()`) the call is foreground work, with the
spec's own `max_tokens`. Outside one (a background deepening pass, the GUI's proactive
analysis) it stays background work: the broker returns an empty reply while a foreground
generation ran within the last `ELI_BG_DEFER_WINDOW` seconds (30 by default, longer after a
slow turn) and caps the output at `ELI_BG_MAX_TOKENS` (256).
