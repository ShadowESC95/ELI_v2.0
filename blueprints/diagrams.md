# Blueprint — ELI ASCII Diagrams

> **Updated for v2.5.36.** CHAT uses a gradient orchestrator for all modes; retrieval
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
            │  CognitiveEngine.process()       │  kernel/engine.py
            │  input guard                     │  injection filter · fit to window
            └───────────────┬─────────────────┘
                            ▼
            ┌─────────────────────────────────┐
            │  ROUTER                          │  execution/router_enhanced.py
            │  priority pipeline (regex-first) │  → {action, args, conf, matched_by}
            │  LLM-intent fallback             │     cognition/llm_intent.py
            └───────────────┬─────────────────┘
                            ▼  authority check (runtime/authority_gate.py)
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
 S01 PERCEIVE_INGEST ─► S02 INPUT_GUARDS ─► S03 ROUTER ─► S04 GROUNDING_GATE
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
 conversation  memories_fts  index.faiss documents   kg_entities(+_fts)
 _turns        memories      (vectors/)  .sqlite3    kg_relations
 (user.sqlite3)              embedder:
                             nomic-embed-…Q4_K_M.gguf
        └──────────┴────┬─────┴───────────┴───────────┘
                        ▼
              HYBRID MERGE ─► HEURISTIC RERANK ─► assembled context
                        │
              retrieve_for_turn() — shared bus + orchestrator owner
              FAISS tombstones hide deleted vectors at once; compact_tombstones()
              takes them out of the files after a forget and in the daily upkeep
                        ▼
                 situation brief ─► generation (persona handoff)

 ┌──────────────────────── STORES (artifacts/) ───────────────────────────┐
 │ db/user.sqlite3   memories, memories_archive, memory_meta, memory_lineage,│
 │                   semantic, memory_claims,                               │
 │                   conversation_turns, conversations, session_summaries,   │
 │                   kg_entities(+_fts), kg_relations, recall_log,           │
 │                   runtime_events, learning_replay, observations,          │
 │                   habits/habit_events/habit_rules, user_patterns,         │
 │                   user_model, eli_stances, belief_revisions,              │
 │                   news_articles(+_fts), news_reflections                  │
 │ db/agent.sqlite3  agent_dispatches, agent_metrics, improvements,          │
 │                   failures, corrections, capability_proposals,            │
 │                   error_tracking, code_patches, lessons                   │
 │                   (self-improvement lives here only)                      │
 │ db/system_index.sqlite3 · db/coding_memory.sqlite3                        │
 │ db/documents.sqlite3 (document index) · db/agenda.sqlite3                 │
 │ db/orchestrator_audit.sqlite3 · db/capability_state.sqlite3               │
 │ vectors/index.faiss   semantic index                                      │
 └──────────────────────────────────────────────────────────────────────────┘

 A question that names a period ("last week") is filtered by date FIRST
 (Memory.memories_between + dated conversation turns), then ranked by topic.
 A message that supplies its own facts opens no window on the user's history
 (supplied_in_message.holds_its_own_answer).

 WRITE PATH:  turn ─► PERSISTENCE GATE (drop junk/report-dumps) ─► STORAGE POLICY
               (origin · dedupe · importance) ─► store;  daily upkeep decays and archives
 FORGET:      memory ─► claims resting only on it, summaries holding its words,
               its vectors (Memory.forget)
```

---

## 3. Gating stack (in path order — every guard the request passes)

```
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 1 ░ NETGUARD  (process-wide, always-on)        core/netguard.py            │
  │      any outbound socket ──► offline? ──► OfflineError (FAIL-CLOSED)        │
  │      allow_network(): scoped window (downloads, self-upgrade, LAN scan)     │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 2 ░ INPUT GUARDS  (S02)                        kernel/engine.py             │
  │      role-override prefixes ──► [filtered]; message fitted to the window    │
  │      API member/viewer asks for an owner-only action ──► REFUSED            │
  │        (runtime/authority_gate.py; ELI's own turns carry no role)           │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 3 ░ PHASE45 FAST-PATH GATE                     kernel/engine.py             │
  │      deterministic action (volume/media/date/job/status)?                   │
  │        ──► execute_action() VERBATIM, no LLM  (cannot confabulate)          │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 4 ░ SHELL GATE                                 execution/shell_gate.py      │
  │      RUN_CMD / SHELL_EXEC: every command in the line, through wrappers      │
  │        denied program or destructive pattern ──► REFUSED                    │
  │        (a denylist: anything else runs; Full Control lifts it)              │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 5 ░ PERSISTENCE GATE                           runtime/persistence_gate.py  │
  │      about to write to memory? junk / internal report-dump?                 │
  │        ──► DROP (so it can't be stored and replayed as fact later)          │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 6 ░ GROUNDING GATE                             runtime/deterministic_…gate  │
  │      answer requires evidence? unbacked or raw packet?                       │
  │        ──► BLOCK raw evidence/telemetry leak; require grounded synthesis     │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 7 ░ GROUNDING ESCALATION                       runtime/grounding_escalation │
  │      checkable fact  AND  grounding < threshold ?                            │
  │        external fact ─► WEB tier ────┐                                       │
  │        self/project  ─► LOCAL tier ──┼─► first tier that grounds ─► answer   │
  │        exhausted, or offline and ────┘─► HEDGE  ("can't check that now")     │
  │          about what changes                                                  │
  │        offline, what does not change ─► the model answers from what it knows │
  │      (trigger = GROUNDING, not the response score — which lies when wrong)   │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 8 ░ LEARNING / STATE COMMIT  (S12)             learning_coordinator.py      │
  │      finalize_turn(): store assistant turn · publish meta · learn from result │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 9 ░ OUTPUT GOVERNOR / SANITISER                cognition/output_governor.py │
  │      final text ──► strip leaks, persona hygiene, no raw JSON ──► user       │
  └──────────────────────────────────────────────────────────────────────────┘

  Legend:  FAIL-CLOSED = denies by default;  VERBATIM = returned without an LLM
           pass;  HEDGE = honest "can't verify" instead of a guess.
```

---

## 4. One-screen overview (how it all connects)

```
  INPUT ─► ENGINE ─► ROUTER ─┬─ FAST-PATH ─────────────► (verbatim) ─► OUTPUT
                             └─ ORCHESTRATOR (all CHAT modes, gradient depth)
                                    │
                                    ├─ retrieve_for_turn() ──► memory/FAISS/KG
                                    ├─ dispatch_specialists() ──► 15-agent bus
                                    └─ broker.infer() ──► finalize_turn() (S12)
                                                          ▼
                          GATES: netguard · input · shell · persistence ·
                                 grounding · governor
                                                          ▼
                                                    OUTPUT
                                                          ▼
                          background: proactive · self-improve · habits ·
                                      learning(LoRA) · world · scheduler
```
