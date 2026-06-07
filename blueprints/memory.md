# ELI Memory Subsystem

`eli/memory/` — 6.8k LOC, 13 files. The persistent substrate: relational +
full-text + vector + graph, all local SQLite/FAISS. Companion to
`project_overview.md`.

## Files

| File | LOC | Role |
|---|---|---|
| `memory.py` | 4.1k | the `Memory` god-class + `DBPaths` + module facade |
| `knowledge_graph.py` | 564 | entity/relation graph (KG) |
| `habits_memory_db.py` | 454 | habit rules/events store |
| `vector_store.py` | 411 | FAISS vector index + embedder |
| `__init__.py` | 275 | module facade (`get_memory`, `recall_memory`, …) |
| `system_index.py` | 238 | indexed apps/executables/files |
| `memory_truth.py` | 173 | inspection/authority (truth report) |
| `memory_adapter.py` | 131 | compat adapter |
| `memory_service.py`, `sqlite_memory.py`, `stores.py`, `populate_memories.py` | small | helpers/compat |

## The `Memory` class (`memory.py`)

A single metaclass-backed class (~50 public methods) that owns essentially every
persistent concern:

- **Semantic memory**: `store_memory`, `add_memory`, `recall_memory`,
  `search_memory(ies)`, `get_recent_semantic_memories`, `adjust_weight`,
  `apply_weight_decay`.
- **Conversation**: `add_conversation_turn`, `store_conversation`,
  `get_conversation_history`, `get_recent_conversation`, `get_recent_turns_since`,
  `search_conversations`, `get_turns_for_day`, `save_session_summary`,
  `get_session_summaries`.
- **Habits**: `log_habit_event`, `get_habit_events`, `add_habit_rule`,
  `get_habit_rules`, `record_habit_run`.
- **Self-improvement / learning**: `log_learning_event`, `log_failure`,
  `log_correction`, `add_observation`, `log_improvement`,
  `add_capability_proposal`, `propose_capability`, `get_pending_proposals`,
  `get_recent_failures/improvements/observations`.
- **Episodic/semantic/reflective aliases**: `store_episodic`, `store_semantic`,
  `recall_semantic`, `store_reflective`.
- **Stats / routing**: `get_stats`, `get_dashboard_counts`,
  `get_db_routing_info`.

`vector_store` is a lazy property; the KG is integrated via
`knowledge_graph.get_knowledge_graph()`.

## Schema (≈24 tables)

`memories` (+ legacy `memory`), `conversation_turns` (+ `conversations`),
`session_summaries`, `kg_entities`, `kg_relations`, `habit_rules`,
`habit_events`, `habits`, `failures`, `corrections`, `improvements`,
`observations`, `capability_proposals`, `learning_replay`, `user_patterns`,
`desktop_apps`, `executables`, `recent_files`, `user_dirs`, `error_tracking`,
`recall_log`, `events`, `semantic`. FTS5 virtual tables back conversation and KG
search.

## `recall_memory` — the hybrid retriever (memory.py:1722)

The shared retrieval foundation (see `orchestration_and_agents.md` for the two
strategies on top):

1. **FAISS first** (Stage 5 vector primary). FTS5/LIKE runs only as a
   *supplement* when the vector index is empty/cold or returns `< limit//2`
   hits. `keyword_only=True` skips FAISS entirely (the orchestrator runs its own
   `semantic_search`, so running FAISS here would double-search with a mislabeled
   source).
2. **Noise filtering** (important): excludes `assistant_insight`/`episodic`/
   `reflection` kinds, `orchestrator` source, and `reflection`/`assistant_insight`/
   `session_summary` tags, and rows longer than 1500 chars — so ELI's own old
   responses/reflections never resurface as "recalled user memories". This was
   the fix for the "Immutable Techniques" contamination class of bug.
3. **Importance-weighted ordering** via `COALESCE(importance, 0.5)`.

Heavy inline column-detection (`_memory_table_columns`) guards against schema
drift across versions — defensive, but a sign the schema has churned.

## Vector store (`vector_store.py`)

FAISS `IndexFlat`, embeddings via a local nomic embedder (llama_cpp). Notable:
- `_embed_lock` (RLock) serializes embedding — the embedder is **not
  thread-safe** and concurrent calls segfault (this is why the orchestrator
  retrieval is sequential).
- Metadata canonicalized to **`meta.json`** (migrated from legacy `meta.pkl`).
- Singleton via `get_vector_store()`; shutdown-aware (skips embedding during
  teardown); `reset_vector_store()` for rebuilds.

## Knowledge graph (`knowledge_graph.py`)

`kg_entities(name,type,aliases,description,confidence)` +
`kg_relations(subject_id, predicate, object_id, weight, source)` — a
subject-predicate-object graph. FTS5 over entities (with insert/update/delete
triggers) for fuzzy `search_entities`. `upsert_entity`, `context_for_prompt`
(lightweight SQLite-only prompt context — no embedding). Stop-word list prevents
common words becoming entities.

## Truth layer (`memory_truth.py`)

`inspect_sqlite` / `inspect_vector_store` — read-only authority/inspection used
by status surfaces; reads `vectors/meta.json` preferentially, falls back to
legacy pickle. Backs `truth_report` and the memory-status surfaces.

## Weight decay & consolidation

`apply_weight_decay(decay_factor=0.98, min_weight=0.05, older_than_days=7)` —
a multiplicative SQL update (`weight = MAX(min, weight*factor)` for old,
low-importance rows). **There is no real episodic→semantic→KG consolidation**:
decay is the only forgetting mechanism, and promotion across stores is manual
(`store_episodic`/`store_semantic` are aliases, not a pipeline). This is a known
gap ELI's own grounding admits.

## Honest assessment

- **Strong:** genuinely hybrid (vector + FTS5 + KG) on one local SQLite
  foundation; the noise-filtering in `recall_memory` is the right instinct and
  fixed real contamination; embedder serialization correctly avoids the segfault.
- **Weak:**
  1. `memory.py` is a **4.1k-line god-class** spanning ~8 unrelated concerns
     (semantic, conversation, habits, learning, failures, capabilities, system
     index). Wants to be split along those seams.
  2. **Schema sprawl / redundancy** — `memories` *and* `memory`, `conversations`
     *and* `conversation_turns`, plus a standalone `semantic` table. The inline
     column-detection everywhere is compensating for schema instability.
  3. **No consolidation pipeline** — only multiplicative decay; memories don't
     graduate into the KG automatically.


---

## Update Advisory — 2026-06-01
- `recall_memory` output now also feeds the `knowledge_graph` agent via the bus DAG upstream edge (memory → KG). No change to memory internals; just a new consumer.
- The coding engine added a separate experiential store, `coding_memory.sqlite3` (`eli/coding/bug_memory.py`: bug→fix). Consider unifying it with the `failures`/`improvements`/`corrections` tables here into one experiential memory (flagged in `agent_algorithms.md` aspirational #4).


---

## Update Advisory — 2026-06-07
- **DB roles (4 stores):** `user.sqlite3` (conversations/memories/KG/news/habits/patterns), `agent.sqlite3` (agent/self-improvement: dispatches, metrics, code_patches, **failures**, improvements), `system_index.sqlite3` (OS app/exe index), `coding_memory.sqlite3` (coding bug-fixes; live but empty until fixes recorded).
- **Failures consolidated:** previously dual-written to both user+agent DBs; now logged ONCE to `agent.sqlite3`. New `Memory.mark_failure_resolved(error_like=/id=)`; `analyze_failures`/`get_recent_failures` exclude `resolved`/`closed`.
- **Gather limits user-tunable:** the `BusMemoryAgent` recall/show counts, chars-per-item, summaries, multi-hop pool and merge cap now come from `cognition_tunables` (GUI ‘Cognition’ tab); defaults unchanged. Personal-memory report cap raised 20→40.
