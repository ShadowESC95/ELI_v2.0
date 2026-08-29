# Blueprint — ELI MKXI ASCII Diagrams

> **Updated for v2.3.39.** CHAT uses a gradient orchestrator for all modes; retrieval
> is unified in `eli/memory/retrieval.py`; Stage 12 = learning/state commit.

Visual companion to `architecture.md`. Three views: the full request pipeline,
the memory subsystem, and the gating stack. All grounded in the real modules
(file paths are clickable).

---

## 1. Full pipeline (request lifecycle)

```
        voice ──► STT (faster-whisper)          GUI text
          │        perception/local_whisper_stt     │
          └───────────────┬───────────────────────-─┘
                          ▼  raw text
            ┌─────────────────────────────────┐
            │  ROUTER                          │  execution/router_enhanced.py
            │  priority pipeline (regex-first) │  → {action, args, conf, matched_by}
            │  LLM-intent fallback             │     cognition/llm_intent.py
            └───────────────┬─────────────────┘
                            ▼
            ┌─────────────────────────────────┐
            │  CognitiveEngine.process()       │  kernel/engine.py
            └───────────────┬─────────────────┘
        ┌───────────────────┼────────────────────────────────┐
        ▼                   ▼                                 ▼
 ╔══════════════╗  ╔══════════════════════════════════════════════╗
 ║ [A] PHASE45  ║  ║ [B] CHAT + NON-CHAT COGNITION PATH            ║
 ║ FAST-PATH    ║  ║ AgentOrchestrator (gradient by mode)          ║
 ║ OS/media/    ║  ║ Quick→light · Expert→full  (see §1b)         ║
 ║ status/job   ║  ║ shared retrieval → dispatch_specialists()     ║
 ╚══════╤═══════╝  ╚═══════════╤══════════════════════════════════╝
        │ execute_action()     │ assembled context
        │ VERBATIM (no LLM)    │
        ▼                      ▼
     return          _build_enhanced_system() / broker.infer()
                               │
                               ▼
                    OUTPUT GOVERNOR / sanitiser
                               ▼
                        response ──► TTS / GUI

        Orchestrator None/raises ──► AgentBus.dispatch() fallback
```

### 1b. Orchestrator — canonical S01–S12  (`pipeline_trace.py`)

```
 S01 PERCEIVE ─► S02 INPUT_GUARDS ─► S03 ROUTER ─► S04 GROUNDING_GATE
        ─► S05 PLANNER (mode-aware budgets)
        ─► S06 AGENT_BUS: retrieve_for_turn() + dispatch_specialists()
        ─► S07 CONTEXT_ASSEMBLY (merge + heuristic rerank)
        ─► S08 INFERENCE_BROKER ─► S09 REASONING_SYNTHESIS (mode algo)
        ─► S10 OUTPUT_GOVERNOR ─► S11 RESPONSE_DELIVERY
        ─► S12 LEARNING_STATE_UPDATE (learning_coordinator.finalize_turn)
```

---

## 2. Memory subsystem  `eli/memory` + `cognition/working_memory.py`

```
                         query / turn
                              │
        ┌─────────────────────┼───────────────────────────────────┐
        ▼          ▼          ▼            ▼            ▼
   ┌─────────┐┌─────────┐┌──────────┐┌─────────┐┌──────────────┐
   │ keyword ││  FTS5   ││  FAISS   ││  RAG    ││ KnowledgeGraph│
   │ (SQL)   ││ full-txt││ vectors  ││ docs    ││ entities/rel  │
   └────┬────┘└────┬────┘└────┬─────┘└────┬────┘└──────┬───────┘
        │          │          │           │           │
        ▼          ▼          ▼           ▼           ▼
 conversation  memories_fts  index.faiss            kg_entities(+_fts)
 _turns        memories      (vectors/)              kg_relations
 (user.sqlite3)              embedder:
                             nomic-embed-…Q4_K_M.gguf
        └──────────┴────┬─────┴───────────┴───────────┘
                        ▼
              HYBRID MERGE ─► HEURISTIC RERANK ─► assembled context
                        │
              retrieve_for_turn() — shared bus + orchestrator owner
              FAISS tombstones skip deleted vectors without full rebuild
                        ▼
                 situation brief ─► generation (persona handoff)

 ┌──────────────────────── STORES (artifacts/) ───────────────────────────┐
 │ db/user.sqlite3   memories(+_fts), conversation_turns, conversations,   │
 │                   kg_entities(+_fts), kg_relations, recall_log,          │
 │                   runtime_events, news_articles(+_fts), news_reflections,│
 │                   habits/habit_events/habit_rules, observations,         │
 │                   learning_replay, working_memory_pins, user_patterns,   │
 │                   session_summaries, corrections, failures               │
 │ db/agent.sqlite3  agent_dispatches, agent_metrics, improvements,         │
 │                   failures, code_patches, error_tracking, observations   │
 │ vectors/index.faiss   semantic index                                     │
 │ runtime/users/<uuid>/user_profile…   per-user profile                    │
 └──────────────────────────────────────────────────────────────────────────┘

 WRITE PATH:  turn ─► PERSISTENCE GATE (drop junk/report-dumps) ─► store
```

---

## 3. Gating stack (in path order — every guard the request passes)

```
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 1 ░ NETGUARD  (process-wide, always-on)        core/netguard.py            │
  │      any outbound socket ──► offline? ──► OfflineError (FAIL-CLOSED)        │
  │      allow_network(): scoped opt-in window (model download, web tier)       │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 2 ░ PHASE45 FAST-PATH GATE                     kernel/engine.py             │
  │      deterministic action (volume/media/date/job/status)?                   │
  │        ──► execute_action() VERBATIM, no LLM  (cannot confabulate)          │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 3 ░ PERSISTENCE GATE                           runtime/persistence_gate.py  │
  │      about to write to memory? junk / internal report-dump?                 │
  │        ──► DROP (so it can't be stored and replayed as fact later)          │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 4 ░ GROUNDING GATE                             runtime/deterministic_…gate  │
  │      answer requires evidence? unbacked or raw packet?                       │
  │        ──► BLOCK raw evidence/telemetry leak; require grounded synthesis     │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 5 ░ GROUNDING ESCALATION                       runtime/grounding_escalation │
  │      checkable fact  AND  grounding < threshold ?                            │
  │        external fact ─► WEB tier ────┐                                       │
  │        self/project  ─► LOCAL tier ──┼─► first tier that grounds ─► answer   │
  │        exhausted / offline ──────────┘─► HEDGE  ("I won't guess")            │
  │      (trigger = GROUNDING, not the response score — which lies when wrong)   │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 6 ░ LEARNING / STATE COMMIT  (S12)             learning_coordinator.py      │
  │      finalize_turn(): store assistant turn · publish meta · learn from result │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 7 ░ OUTPUT GOVERNOR / SANITISER                cognition/output_governor.py │
  │      final text ──► strip leaks, persona hygiene, no raw JSON ──► user       │
  └──────────────────────────────────────────────────────────────────────────┘

  Legend:  FAIL-CLOSED = denies by default;  VERBATIM = returned without an LLM
           pass;  HEDGE = honest "can't verify" instead of a guess.
```

---

## 4. One-screen overview (how it all connects)

```
  INPUT ─► ROUTER ─► ENGINE ─┬─ FAST-PATH ─────────────► (verbatim) ─► OUTPUT
                             └─ ORCHESTRATOR (all CHAT modes, gradient depth)
                                    │
                                    ├─ retrieve_for_turn() ──► memory/FAISS/KG
                                    ├─ dispatch_specialists() ──► 15-agent bus
                                    └─ broker.infer() ──► finalize_turn() (S12)
                                                          ▼
                          GATES: netguard · persistence · grounding · governor
                                                          ▼
                                                    OUTPUT
                                                          ▼
                          background: proactive · self-improve · habits ·
                                      learning(LoRA) · world · scheduler
```
```
