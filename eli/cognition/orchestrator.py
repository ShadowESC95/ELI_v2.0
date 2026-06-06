# NOTE:
# AgentOrchestrator currently depends on the CognitiveEngine public contract surface
# (parse_intent / assemble_precise_context / generate_from_assembled_prompt /
# generate_stream_from_assembled_prompt). Do not remove those GUI methods
# until PATH2 is migrated onto CognitiveEngine-native equivalents.

from __future__ import annotations

import traceback
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Tuple

from eli.execution.executor_enhanced import execute as execute_action
from eli.execution.executor_enhanced import SUPPORTED_ACTIONS as _SUPPORTED_ACTIONS

# Normalized set for O(1) validation of ReAct-proposed tool actions.
_VALID_ACTIONS = {str(a).strip().upper() for a in (_SUPPORTED_ACTIONS or [])}



from eli.utils.log import get_logger
log = get_logger(__name__)

@dataclass
class OrchestratorContext:
    user_input: str
    intent: Dict[str, Any] = field(default_factory=dict)
    persona_ok: bool = False
    hyde_query: str = ""
    keyword_hits: List[Dict[str, Any]] = field(default_factory=list)
    semantic_hits: List[Dict[str, Any]] = field(default_factory=list)
    rag_hits: List[Dict[str, Any]] = field(default_factory=list)
    merged_hits: List[Dict[str, Any]] = field(default_factory=list)
    reranked_hits: List[Dict[str, Any]] = field(default_factory=list)
    assembled_context: str = ""
    final_prompt: str = ""
    final_response: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ShortTermEpisodic:
    session_id: str
    user_id: str
    recent_turns: List[Dict[str, Any]] = field(default_factory=list)
    scratchpad: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LongTermMemoryRefs:
    sqlite_ready: bool
    vector_ready: bool
    rag_ready: bool


class PlannerAgent:
    def __init__(self, engine):
        self.engine = engine

    def plan_retrieval(self, user_input: str,
                       intent: Dict[str, Any], hyde_query: str,
                       stm: ShortTermEpisodic,
                       reasoning_mode: Optional[str] = None) -> Dict[str, Any]:
        """
        Build a retrieval plan tuned to the active reasoning mode.

        fast     — skip HyDE, smaller search budgets, single ReAct pass
        balanced — current default: HyDE skipped for short queries
        deep     — full HyDE, large result sets, full ReAct loop
        """
        low = (user_input or "").lower()
        mode = (reasoning_mode or "balanced").lower()

        doc_query = any(k in low for k in ("document", "file", "pdf", "notes", "codebase"))
        identity  = any(k in low for k in ("who am i", "my name", "remember me"))
        runtime   = any(k in low for k in ("memory function", "memory work", "cognition", "how do you work"))

        if mode == "fast":
            return {
                "need_keyword":   True,
                "need_semantic":  False,      # skip FAISS embedding (saves one LLM call)
                "need_rag":       False,
                "need_kg":        identity,
                "keyword_limit":  6,
                "semantic_limit": 0,
                "rag_limit":      0,
                "prefer_identity": identity,
                "prefer_runtime":  runtime,
                "skip_hyde":       True,      # signals MemoryAgent to never run HyDE
                "max_react_iter":  1,
            }
        elif mode == "deep":
            return {
                "need_keyword":   True,
                "need_semantic":  True,
                "need_rag":       doc_query,
                "need_kg":        True,
                "keyword_limit":  20,
                "semantic_limit": 20,
                "rag_limit":      15,
                "prefer_identity": identity,
                "prefer_runtime":  runtime,
                "skip_hyde":       False,
                "max_react_iter":  3,
            }
        else:  # balanced (default)
            return {
                "need_keyword":   True,
                "need_semantic":  True,
                "need_rag":       doc_query,
                "need_kg":        True,
                "keyword_limit":  16,
                "semantic_limit": 16,
                "rag_limit":      12,
                "prefer_identity": identity,
                "prefer_runtime":  runtime,
                "skip_hyde":       False,
                "max_react_iter":  3,
            }


class ExecutorAgent:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, intent: Dict[str, Any],
                user_input: str) -> Dict[str, Any]:
        action = str(intent.get("action", "")).upper()
        args = intent.get("args", {})
        payload = args if isinstance(args, dict) else {"query": user_input}
        return execute_action(action, payload)


class OrchestratorMemoryAgent:
    def __init__(self, engine):
        self.engine = engine

    def build_hyde_query(self, query: str, skip_hyde: bool = False) -> str:
        """
        Build a HyDE-expanded query. Skipped when:
          - skip_hyde=True (FAST mode or planner flag)
          - query is short (< 8 words) — saves ~60s inference per turn
          - query is trivial/conversational
          - query is self-referential (no grounded hypothetical answer exists)
        """
        q = (query or "").strip()
        if not q:
            return ""
        if skip_hyde:
            return q
        if len(q.split()) < 8:
            return q
        _low = q.lower()
        _trivial = any(_low.startswith(p) for p in (
            "hello", "hi ", "hey", "ok ", "okay", "yes", "no", "thanks",
            "thank you", "sure", "got it", "sounds good",
        ))
        if _trivial:
            return q
        import re as _re
        _self_ref_words = {"me", "my", "mine", "myself", "our", "ours", "we", "us", "i"}
        _tokens = set(_re.findall(r"\b[a-z]+\b", _low))
        if _self_ref_words & _tokens:
            return q
        prompt = f"Write a brief factual answer to: {q}"
        try:
            hyde = self.engine.generate_from_assembled_prompt(
                prompt, None, reasoning_mode="quick", raw_direct=True)
            hyde = (hyde or "").strip()
            return q if not hyde else f"{q}\n\n{hyde}"
        except Exception as e:
            log.debug(f"[ORCHESTRATOR] Error: {e}")
            return q

    def parallel_retrieve(self, user_input: str, hyde_query: str,
                          retrieval_plan: Dict[str, Any], ltm: LongTermMemoryRefs):
        # Sequential — llama_cpp (nomic embedder) is not thread-safe across threads;
        # concurrent calls from daemon threads segfault the process.
        keyword_hits: List[Dict[str, Any]] = []
        semantic_hits: List[Dict[str, Any]] = []
        rag_hits: List[Dict[str, Any]] = []
        kg_hits: List[Dict[str, Any]] = []

        if retrieval_plan.get("need_keyword"):
            keyword_hits = self.keyword_search(
                user_input, retrieval_plan.get("keyword_limit", 12))

        if retrieval_plan.get("need_semantic"):
            semantic_hits = self.semantic_search(
                hyde_query or user_input, retrieval_plan.get("semantic_limit", 12))

        if retrieval_plan.get("need_rag") and ltm.rag_ready:
            rag_hits = self.document_rag_search(
                user_input, retrieval_plan.get("rag_limit", 8))

        # KG: always query when planner flagged identity preference, or as a
        # low-cost default (SQLite lookup, no embedding, no LLM).
        if retrieval_plan.get("prefer_identity") or retrieval_plan.get("need_kg", True):
            kg_hits = self.kg_search(
                user_input, retrieval_plan.get("kg_limit", 8))

        return keyword_hits, semantic_hits, rag_hits, kg_hits

    def kg_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Query the knowledge graph directly — no recall_memory pass-through.

        Previously called recall_memory and filtered to KG rows, which caused
        a full second FAISS+FTS5+recall pipeline run just to get KG facts.
        Now queries get_knowledge_graph().context_for_prompt() directly, which
        is a lightweight SQLite-only lookup with no embedding overhead.
        """
        try:
            from eli.memory.knowledge_graph import get_knowledge_graph
            _kg = get_knowledge_graph()
            # Scale max_chars roughly with limit (default ~600 at limit=6)
            _max_chars = max(400, min(2000, limit * 120))
            _ctx = _kg.context_for_prompt(query, max_chars=_max_chars)
            if not _ctx:
                return []
            return [{
                "source": "knowledge_graph",
                "score": 0.95,
                "text": _ctx,
                "meta": {"kind": "knowledge_graph", "query": query},
            }]
        except Exception as e:
            log.debug(f"[ORCHESTRATOR] Stage 5b: KG search error: {e}")
            return []

    def conversation_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Stage 5c: FTS5 search over conversation_turns.

        Filters out noise at query time (assistant runtime dumps, template tokens)
        on top of the index-time filter applied during backfill.
        """
        try:
            import sqlite3, re
            mem = getattr(self.engine, "memory", None)
            if mem is None:
                return []
            db_path = getattr(mem, "db_path", None) or getattr(mem, "_db_path", None)
            if db_path is None:
                try:
                    from eli.core.paths import user_db_path
                    db_path = str(user_db_path())
                except Exception:
                    return []
            con = sqlite3.connect(str(db_path))
            try:
                # Token-split so FTS5 doesn't choke on punctuation
                toks = [t for t in re.split(r"[^a-zA-Z0-9_]+", query or "") if len(t) > 1]
                if not toks:
                    return []
                fts_q = " OR ".join(f'"{t}"' for t in toks[:8])
                rows = con.execute(
                    """
                    SELECT ct.id, ct.role, ct.content, COALESCE(ct.timestamp, ct.ts, 0)
                    FROM conversation_turns_fts f
                    JOIN conversation_turns ct ON ct.id = f.rowid
                    WHERE conversation_turns_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_q, int(limit)),
                ).fetchall()
            finally:
                con.close()
            normalized: List[Dict[str, Any]] = []
            for (cid, role, content, ts) in rows:
                txt = (content or "").strip()
                if not txt:
                    continue
                # Role tag so the LLM understands provenance
                prefix = "User said: " if role == "user" else "Assistant said: " if role == "assistant" else ""
                normalized.append({
                    "source": "conversation",
                    "score": 0.85,  # conversation history is high-trust signal
                    "text": f"{prefix}{txt}",
                    "meta": {"id": cid, "role": role, "ts": ts},
                })
            return normalized
        except Exception as e:
            log.debug(f"[ORCHESTRATOR] Stage 5c: conversation search error: {e}")
            return []

    def keyword_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        # keyword_only=True: FAISS is skipped inside recall_memory so we don't
        # double-search vectors (semantic_search handles FAISS separately).
        # KG injection is also skipped — kg_search() below queries KG directly.
        hits = self.engine.recall_memory_query(
            query, limit=limit, keyword_only=True) or []
        normalized = []
        for h in hits:
            text = (h.get("text") or h.get("content") or "").strip()
            if text:
                normalized.append({
                    "source": "fts5",
                    "score": float(h.get("score", 0.0) or 0.0),
                    "text": text,
                    "meta": h,
                })
        return normalized

    def semantic_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """
        Stage 6: True FAISS vector semantic search.
        Uses the hyde_query (hypothetical answer + original query) as the
        embedding input so HyDE improves recall automatically.
        Also pulls recent conversation turns as a secondary source.
        """
        hits = []

        # ── Primary: FAISS vector store ──────────────────────────────────
        try:
            vs = getattr(self.engine.memory, "vector_store", None)
            if vs is None:
                from eli.memory.vector_store import get_vector_store
                vs = get_vector_store()

            idx = getattr(vs, "_index", None) if vs is not None else None
            ntotal = int(getattr(idx, "ntotal", 0) or 0)

            if vs is not None and ntotal > 0:
                raw = vs.search(query, top_k=limit) or []
                for h in raw:
                    text = (h.get("text") or "").strip()
                    if text:
                        hits.append({
                            "source": "vector",
                            "score": float(h.get("score", 0.0) or 0.0),
                            "text": text,
                            "meta": h,
                        })
                log.debug(f"[ORCHESTRATOR] Stage 6: FAISS → {len(hits)} vector hits (ntotal={ntotal})")
        except Exception as e:
            log.debug(f"[ORCHESTRATOR] Stage 6 FAISS error: {e}")

        # ── Secondary: conversation history search ────────────────────────
        try:
            conv = self.engine.memory.search_conversations(
                query, user_id=self.engine.user_id, limit=max(4, limit // 3),
                session_id=getattr(self.engine, "session_id", None)) or []
            for h in conv:
                text = (h.get("content") or h.get("text") or "").strip()
                if text:
                    hits.append({
                        "source": "conversation",
                        "score": 0.3,
                        "text": text,
                        "meta": h,
                    })
        except Exception as e:
            log.debug(f"[ORCHESTRATOR] Stage 6 conv search error: {e}")

        return hits

    def document_rag_search(
        self, query: str, limit: int) -> List[Dict[str, Any]]:
        try:
            if hasattr(self.engine, "document_rag") and self.engine.document_rag:
                hits = self.engine.document_rag.search(query, limit=limit) or []
                out = []
                for h in hits:
                    text = (h.get("text") or "").strip()
                    if text:
                        out.append({
                            "source": "rag",
                            "score": float(h.get("score", 0.0) or 0.0),
                            "text": text,
                            "meta": h,
                        })
                return out
        except Exception as e:
            log.debug(f"[ORCHESTRATOR] Error: {e}")
        return []

    def hybrid_merge(self, keyword_hits: List[Dict[str, Any]], semantic_hits: List[Dict[str, Any]],
                     rag_hits: List[Dict[str, Any]], kg_hits: Optional[List[Dict[str, Any]]] = None,
                     limit: int = 20) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        # KG first — identity/relation facts are authoritative and cheap to dedupe against.
        for bucket in ((kg_hits or []), keyword_hits, semantic_hits, rag_hits):
            for item in bucket:
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                key = text[:240].lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return merged
        return merged

    # Phrases that are deterministic lookup non-answers. They must never be
    # injected as retrieved context for a subsequent unrelated query — doing so
    # causes the LLM to echo them back verbatim for completely different questions.
    _CONTEXT_RESPONSE_BLACKLIST = {
        "i do not have a personal memory of the user's name",
        "no confirmed name/identity label is stored",
        "no confirmed name",
        "i have no memory of your name",
        "i don't have a record of your name",
        # Variants observed in session logs that were slipping through:
        "i don't have a personal name or identity stored",
        "i do not have a personal name or identity stored",
        "no memories found for your name",
        "i do not have a confirmed name/identity row",
        "i don't have a confirmed name",
        "no personal name or identity stored",
        "personal name or identity stored for the active user",
    }

    def rerank(self, query: str,
               hits: List[Dict[str, Any]], top_k: int = 12) -> List[Dict[str, Any]]:
        # Strip placeholder non-answers before scoring so they can never
        # contaminate context for an unrelated query.
        _bl = self._CONTEXT_RESPONSE_BLACKLIST
        hits = [
            h for h in hits
            if not any(p in (h.get("text") or "").lower() for p in _bl)
        ]

        def score(item: Dict[str, Any]) -> float:
            text = (item.get("text") or "").lower()
            q = (query or "").lower()
            overlap = sum(1 for tok in set(q.split()) if tok and tok in text)
            base = float(item.get("score", 0.0) or 0.0)
            src = str(item.get("source", "")).lower()
            # Source priority: KG facts are authoritative, conversation history is recent signal,
            # vector/fts are supplementary
            src_boost = {
                "knowledge_graph": 0.40,
                "kg": 0.40,
                "conversation": 0.22,
                "vector": 0.08,
                "fts5": 0.05,
                "fts": 0.05,
            }.get(src, 0.0)
            return base + overlap * 0.15 + src_boost
        return sorted(hits, key=score, reverse=True)[:top_k]


class AgentOrchestrator:
    def __init__(self, engine):
        self.engine = engine
        self.executor_agent = ExecutorAgent(engine)
        self.memory_agent = OrchestratorMemoryAgent(engine)
        self.planner_agent = PlannerAgent(engine)

    def run(self, user_input: Optional[str] = None, *, stream: bool = False,
            reasoning_mode: Optional[str] = None, **kwargs) -> Any:
        user_input = user_input or kwargs.pop("user_input", "")
        if not isinstance(user_input, str):
            user_input = str(user_input or "")

        # ---- Grounded remediation pre-intercept -----------------------------
        # YES/NO confirmations must consume pending repair state BEFORE the
        # router or LLM see them. try_handle_query() handles open/launch/check
        # phrasing that should bypass full pipeline planning.
        if user_input:
            try:
                from eli.runtime import grounded_remediation as _gr
                _conf = _gr.handle_confirmation(user_input)
                if _conf is not None:
                    log.debug(f"[GROUNDED_REMEDIATION] confirmation intercept consumed: {user_input!r}")
                    return _conf
                _handled = _gr.try_handle_query(user_input)
                if _handled:
                    return _handled
            except Exception as _gr_e:
                log.debug(f"[GROUNDED_REMEDIATION] orchestrator intercept failed: {_gr_e}")

        if getattr(self.engine, "_in_orchestrator", False):
            raise RuntimeError("Recursion detected in orchestrator.run()")
        self.engine._in_orchestrator = True
        _eli_pipeline_trace = str(__import__("os").environ.get("ELI_PIPELINE_TRACE", "")).strip().lower() in {"1", "true", "yes", "on"}
        _eli_pipeline_req = str(getattr(self.engine, "_pipeline_req_id", "") or "n/a")

        def _eli_pipe_orch(stage: str, **fields) -> None:
            if not _eli_pipeline_trace:
                return
            try:
                parts = [f"stage={stage}", f"req={_eli_pipeline_req}"]
                for k, v in fields.items():
                    parts.append(f"{k}={v}")
                log.debug("[PIPELINE][ORCH] " + " ".join(parts))
            except Exception:
                pass

        _eli_pipe_orch("begin", mode=(reasoning_mode or "quick"), stream=stream, chars=len(str(user_input or "")))

        wm = OrchestratorContext(user_input=user_input)
        def _eli_orch_complete_final_stage(status: str, note: str = "") -> None:
            # Ensure downstream consumers always see a complete stage trail:
            # stages that were not needed are explicitly marked as skipped,
            # and stage_12 records final completion/handoff status.
            defaults = {
                "stage_3": "skipped_not_required",
                "stage_4": "skipped_not_required",
                "stage_5_6_7": "skipped_not_required",
                "stage_8": "skipped_not_required",
                "stage_9": "skipped_not_required",
                "stage_10": "skipped_not_required",
                "stage_10_5": "skipped_not_required",
                "stage_11": "skipped_not_required",
            }
            for key, value in defaults.items():
                wm.trace.setdefault(key, value)
            wm.trace["stage_12"] = str(status or "completed")
            if note:
                wm.trace["stage_12_note"] = str(note)
            _eli_pipe_orch("stage_12", status=wm.trace["stage_12"], note=(note or "none"))

        stm = ShortTermEpisodic(
            session_id=self.engine.session_id,
            user_id=self.engine.user_id,
            recent_turns=self.engine.memory.get_recent_conversation(
                limit=12, user_id=self.engine.user_id) or [],
        )
        ltm = LongTermMemoryRefs(
            sqlite_ready=True,
            vector_ready=hasattr(self.engine.memory, "vector_store"),
            rag_ready=hasattr(self.engine, "document_rag"),
        )

        wm.trace["stage_1"] = "intent_routing"
        intent = self.engine.parse_intent(user_input, stm.recent_turns)
        wm.intent = intent
        log.debug(f"[ORCHESTRATOR] Stage 1: Intent Routing → {intent.get('action')}")
        _eli_pipe_orch("stage_1", action=intent.get("action"), confidence=float(intent.get("confidence") or 0.0))

        wm.trace["stage_2"] = "persona_lock_verify"
        wm.persona_ok = self.engine.verify_persona_lock()
        log.debug(f"[ORCHESTRATOR] Stage 2: Persona Lock → {wm.persona_ok}")
        _eli_pipe_orch("stage_2", persona_ok=wm.persona_ok)
        if not wm.persona_ok:
            self.engine.repair_persona_lock()

        action = str(intent.get("action", "CHAT")).upper()
        if action != "CHAT":
            synth_actions = {
                "RUNTIME_STATUS",
                "MEMORY_STATUS",
                "COGNITION_STATUS",
                "MEMORY_RECALL",
                "RESOLVE_RUNTIME_PATHS",
                "GUI_RUNTIME_AUDIT",
                "RUNTIME_AUDIT",
                "IMPORT_AUDIT",
                "EXPLAIN_MEMORY_RUNTIME",
                "EXPLAIN_COGNITION_RUNTIME",
                "PERSONAL_MEMORY_SUMMARY",
                "PERSONAL_MEMORY_DEEP_EXPLAIN",
                "ROUTING_FAULT_EXPLAIN",
                "NAME_SOURCE_AUDIT",
            }
            bus_result = None
            bus_context = ""

            try:
                from eli.cognition.agent_bus import get_bus
                bus_result = get_bus().dispatch(
                    user_input,
                    intent,
                    session_id=self.engine.session_id,
                    user_id=self.engine.user_id,
                )
                wm.bus_result = bus_result
                # Mirror the CHAT path's rotation. Non-CHAT turns
                # (RUNTIME_STATUS, MEMORY_STATUS, etc.) must also feed the
                # next turn's persona handoff, otherwise the LAST_TURN_TRACE
                # block will be stale when the user follows up.
                try:
                    self.engine._prev_bus_result = getattr(
                        self.engine, "_last_bus_result", None)
                    self.engine._last_bus_result = bus_result
                except Exception:
                    pass
                bus_context = (
                    bus_result.to_context_block()
                    if hasattr(bus_result, "to_context_block")
                    else str(getattr(bus_result, "memory_context", "") or "")
                ).strip()
                wm.trace["agent_bus_nonchat"] = {
                    "agents_used": list(getattr(bus_result, "agents_used", []) or []),
                    "aggregated_confidence": float(
                        getattr(bus_result, "aggregated_confidence", 0.0) or 0.0
                    ),
                }
            except Exception as _bus_err:
                wm.trace["agent_bus_nonchat"] = {"error": str(_bus_err)}
                log.debug(f"[ORCHESTRATOR] Non-chat AgentBus unavailable: {_bus_err}")

            # ── ReAct observation loop (mode-aware max iterations) ───────────
            _mode_for_react = (reasoning_mode or "balanced").lower()
            MAX_REACT_ITER = 1 if _mode_for_react == "fast" else 3
            observations: list = []
            result = {}
            for _react_i in range(MAX_REACT_ITER):
                result = self.executor_agent.execute(intent, user_input)
                obs_text = str(
                    result.get("content") or result.get("response") or result.get("error") or ""
                ).strip()
                if obs_text:
                    observations.append(f"[Tool:{action}] {obs_text[:1200]}")
                    try:
                        self.engine.memory.add_observation("executor", obs_text[:400])
                    except Exception:
                        pass

                if _react_i < MAX_REACT_ITER - 1 and obs_text:
                    _obs_ctx = "\n".join(observations)
                    _react_prompt = (
                        f"User asked: {user_input}\n\n"
                        f"Tool observations so far:\n{_obs_ctx}\n\n"
                        "Do you have enough information to answer the user, "
                        "or do you need to call another tool? "
                        "Reply ANSWER if done, or reply TOOL:<action> <args> if another tool call is needed."
                    )
                    try:
                        _broker = self.engine.inference_broker
                        _react_decision = _broker.infer(
                            _react_prompt, max_tokens=80, temperature=0.2
                        )
                        _react_decision = (_react_decision or "").strip().upper()
                    except Exception:
                        _react_decision = "ANSWER"

                    if _react_decision.startswith("ANSWER") or not _react_decision.startswith("TOOL:"):
                        break

                    try:
                        _tool_line = _react_decision[5:].strip()
                        _tok = _tool_line.split()[0] if _tool_line.split() else ""
                        # Strip stray punctuation the model may append (TOOL:DATE.)
                        _next_action = _tok.strip(" .,:;!?\"'`").upper()
                        # Only chain to a real, registered action. An unknown or
                        # hallucinated action ends the loop instead of switching
                        # to garbage the executor can't handle.
                        if not _next_action or (_VALID_ACTIONS and _next_action not in _VALID_ACTIONS):
                            log.debug(f"[ORCHESTRATOR] ReAct proposed unknown action {_next_action!r}; stopping loop")
                            break
                        # Merge args — preserve the original args, add observation context.
                        intent = dict(intent)
                        _merged_args = dict(intent.get("args") or {}) if isinstance(intent.get("args"), dict) else {}
                        _merged_args.setdefault("query", user_input)
                        _merged_args["observation_context"] = _obs_ctx
                        intent["action"] = _next_action
                        intent["args"] = _merged_args
                        action = _next_action
                    except Exception:
                        break
                else:
                    break

            if len(observations) > 1:
                result["observation_chain"] = observations

            if action in synth_actions:
                grounded_observations = "\n".join(observations).strip()
                if not grounded_observations:
                    grounded_observations = str(
                        result.get("content") or result.get("response") or result.get("error") or ""
                    ).strip()

                wm.trace["stage_nonchat"] = "executor_observation_loop"
                wm.trace["tool_action"] = action
                wm.trace["tool_observations"] = observations[:]
                _eli_pipe_orch("stage_nonchat", tool_action=action, obs_count=len(observations))
                wm.trace["stage_3"] = "skipped_nonchat_hyde"
                wm.trace["stage_4"] = "skipped_nonchat_planner"
                wm.trace["stage_5_6_7"] = "skipped_nonchat_retrieval"
                wm.trace["stage_8"] = "skipped_nonchat_hybrid_merge"
                wm.trace["stage_9"] = "skipped_nonchat_rerank"
                wm.trace["stage_10"] = "nonchat_executor_evidence_assembly"
                _eli_pipe_orch("stage_10", mode="nonchat_executor_evidence_assembly")
                log.debug(f"[ORCHESTRATOR] Stages 3-9 skipped → not required for {action}")
                wm.assembled_context = (
                    "You are ELI.\n"
                    "Answer the user's request using the executor observations below.\n"
                    "Stay direct and natural.\n"
                    "Do not invent values or details not present in the observations.\n"
                    "If information is missing from the observations, say so plainly.\n\n"
                    f"Executor observations for action {action}:\n"
                    f"{grounded_observations}"
                )
                wm.final_prompt = user_input

                wm.trace["stage_10_5"] = "persona_handoff"
                try:
                    if hasattr(self.engine, "_build_persona_handoff_once"):
                        wm.persona_handoff = self.engine._build_persona_handoff_once(
                            user_input=wm.final_prompt,
                            memory_context=wm.assembled_context,
                            bus_result=getattr(wm, "bus_result", None),
                            recent_turns=getattr(stm, "recent_turns", []),
                            working_memory=wm,
                        )
                    _ph = str(getattr(wm, "persona_handoff", "") or "")
                    log.debug(f"[ORCHESTRATOR] Stage 10.5: Persona Handoff → {len(_ph)} chars")
                except Exception as _ph_err:
                    log.debug(f"[ORCHESTRATOR] Stage 10.5: Persona Handoff unavailable: {_ph_err}")

                wm.trace["stage_11"] = "llm_generation"
                log.debug(f"[ORCHESTRATOR] Stage 11: LLM Generation → {'streaming' if stream else 'oneshot'}")
                _eli_pipe_orch("stage_11", mode=("streaming" if stream else "oneshot"), action=action)

                if stream:
                    result_stream = self.engine.generate_stream_from_assembled_prompt(
                        wm.final_prompt,
                        wm,
                        reasoning_mode=reasoning_mode,
                    )
                    _eli_orch_complete_final_stage(
                        "streaming_handoff",
                        note="nonchat_synth_stream",
                    )
                    self.engine._in_orchestrator = False
                    return result_stream

                response = self.engine.generate_from_assembled_prompt(
                    wm.final_prompt,
                    wm,
                    reasoning_mode=reasoning_mode,
                )
                wm.final_response = response

                _eli_orch_complete_final_stage(
                    "completed",
                    note="nonchat_synth",
                )
                self.engine._in_orchestrator = False
                return {
                    "ok": bool(result.get("ok", True)),
                    "action": "CHAT",
                    "content": response,
                    "response": response,
                    "trace": wm.trace,
                }

            wm.trace["stage_nonchat"] = "executor_direct_result"
            wm.trace["stage_10"] = "skipped_nonchat_direct_result"
            wm.trace["stage_10_5"] = "skipped_nonchat_direct_result"
            wm.trace["stage_11"] = "skipped_nonchat_direct_result"
            _eli_orch_complete_final_stage(
                "completed",
                note="nonchat_direct_result",
            )
            self.engine._in_orchestrator = False
            return result

        wm.trace["stage_4"] = "planner"
        retrieval_plan = self.planner_agent.plan_retrieval(
            user_input, intent, "", stm, reasoning_mode=reasoning_mode)
        log.debug("[ORCHESTRATOR] Stage 4: Planner → mode=%s %s" % (
            reasoning_mode or "balanced", retrieval_plan))
        _eli_pipe_orch("stage_4", mode=(reasoning_mode or "balanced"))

        wm.trace["stage_3"] = "hyde_query_expansion"
        wm.hyde_query = self.memory_agent.build_hyde_query(
            user_input, skip_hyde=retrieval_plan.get("skip_hyde", False))
        hyde_preview = wm.hyde_query[:60] + "..." if len(wm.hyde_query) > 60 else wm.hyde_query
        log.debug(f"[ORCHESTRATOR] Stage 3: HyDE Query → {hyde_preview}")
        _eli_pipe_orch("stage_3", hyde_chars=len(wm.hyde_query or ""))

        wm.trace["stage_5_6_7"] = "parallel_retrieval"
        keyword_hits, semantic_hits, rag_hits, kg_hits = self.memory_agent.parallel_retrieve(
            user_input=user_input,
            hyde_query=wm.hyde_query,
            retrieval_plan=retrieval_plan,
            ltm=ltm,
        )
        wm.keyword_hits = keyword_hits
        wm.semantic_hits = semantic_hits
        wm.rag_hits = rag_hits
        wm.kg_hits = kg_hits
        log.debug(f"[ORCHESTRATOR] Stage 5/6/7: Parallel Retrieval → keyword: {len(keyword_hits)} semantic: {len(semantic_hits)} rag: {len(rag_hits)} kg: {len(kg_hits)}")
        _eli_pipe_orch("stage_5_6_7", keyword=len(keyword_hits), semantic=len(semantic_hits), rag=len(rag_hits), kg=len(kg_hits))

        wm.trace["stage_8"] = "hybrid_merge"
        wm.merged_hits = self.memory_agent.hybrid_merge(
            keyword_hits, semantic_hits, rag_hits, kg_hits=kg_hits)
        log.debug(f"[ORCHESTRATOR] Stage 8: Hybrid Merge → {len(wm.merged_hits)} items")
        _eli_pipe_orch("stage_8", merged=len(wm.merged_hits))

        wm.trace["stage_9"] = "cross_encoder_rerank"
        wm.reranked_hits = self.memory_agent.rerank(
            user_input, wm.merged_hits)
        log.debug(f"[ORCHESTRATOR] Stage 9: Rerank → {len(wm.reranked_hits)} items")
        _eli_pipe_orch("stage_9", reranked=len(wm.reranked_hits))

        wm.trace["stage_10"] = "context_assembly"
        wm.assembled_context, wm.final_prompt = self.engine.assemble_precise_context(
            user_input=user_input,
            working_memory=wm,
            short_term_memory=stm,
            intent=intent,
            reasoning_mode=reasoning_mode,
        )
        log.debug(f"[ORCHESTRATOR] Stage 10: Context Assembly → {len(wm.assembled_context)} chars")
        _eli_pipe_orch("stage_10", assembled_chars=len(wm.assembled_context or ""))

        wm.trace["stage_10_5"] = "persona_handoff"
        try:
            if hasattr(self.engine, "_build_persona_handoff_once"):
                wm.persona_handoff = self.engine._build_persona_handoff_once(
                    user_input=user_input,
                    memory_context=wm.assembled_context,
                    bus_result=getattr(wm, "bus_result", None),
                    recent_turns=getattr(stm, "recent_turns", []),
                    working_memory=wm,
                )
            _ph = str(getattr(wm, "persona_handoff", "") or "")
            log.debug(f"[ORCHESTRATOR] Stage 10.5: Persona Handoff → {len(_ph)} chars")
        except Exception as _ph_err:
            log.debug(f"[ORCHESTRATOR] Stage 10.5: Persona Handoff unavailable: {_ph_err}")

        # ELI_PRIVATE_REASONING_DISPATCH_V1
        # For private reasoning modes (chain_of_thought, self_consistency,
        # tree_of_thoughts, constitutional_ai) the orchestrator MUST hand off
        # to _run_chat_reasoning_loop so the mode-specific algorithm runs.
        # Otherwise the call below collapses to a single GGUF call and the
        # generate->critique->revise (or propose->develop, or N-sample->select)
        # pipeline never executes. Quick mode is untouched.
        try:
            from eli.cognition.reasoning_modes import is_private_reasoning_mode as _rm_private_chat
            _chat_is_private = _rm_private_chat(reasoning_mode)
        except Exception:
            _chat_is_private = bool(
                reasoning_mode
                and str(reasoning_mode).strip().lower()
                not in {"", "quick", "fast", "balanced"}
            )

        if _chat_is_private and hasattr(self.engine, "_run_chat_reasoning_loop"):
            log.debug(f"[ORCHESTRATOR] Stage 11: private reasoning loop -> {reasoning_mode}")
            wm.trace["stage_11"] = "llm_generation_private_loop"
            _eli_pipe_orch("stage_11_private_loop", mode=str(reasoning_mode), action=action)
            try:
                _loop_intent = dict(intent) if isinstance(intent, dict) else {"action": "CHAT"}
                _loop_result = self.engine._run_chat_reasoning_loop(
                    user_input=user_input,
                    memory_context=str(getattr(wm, "assembled_context", "") or ""),
                    intent=_loop_intent,
                    reasoning_mode=reasoning_mode,
                    trace=wm.trace,
                    gen_overrides=None,
                    situation_brief="",
                )
                _loop_response = str((_loop_result or {}).get("response") or "").strip()
                if _loop_response:
                    wm.final_response = _loop_response
                    _eli_orch_complete_final_stage(
                        "completed",
                        note="chat_private_reasoning_loop",
                    )
                    self.engine._in_orchestrator = False
                    return {
                        "ok": True,
                        "action": "CHAT",
                        "content": _loop_response,
                        "response": _loop_response,
                        "trace": wm.trace,
                        "evidence_used": bool(((_loop_result or {}).get("evidence") or {}).get("used")),
                        "reasoning_mode": str(reasoning_mode or ""),
                    }
                log.debug("[ORCHESTRATOR] private reasoning loop returned empty -> falling back to single-shot")
            except Exception as _priv_err:
                log.debug(f"[ORCHESTRATOR] private reasoning loop failed -> falling back to single-shot: {_priv_err}")
        # ELI_PRIVATE_REASONING_DISPATCH_V1_END

        wm.trace["stage_11"] = "llm_generation"
        log.debug(f"[ORCHESTRATOR] Stage 11: LLM Generation → {'streaming' if stream else 'oneshot'}")
        _eli_pipe_orch("stage_11", mode=("streaming" if stream else "oneshot"), action=action)

        if stream:
            result_stream = self.engine.generate_stream_from_assembled_prompt(
                wm.final_prompt,
                wm,
                reasoning_mode=reasoning_mode,
            )
            _eli_orch_complete_final_stage(
                "streaming_handoff",
                note="chat_stream",
            )
            self.engine._in_orchestrator = False
            return result_stream

        response = self.engine.generate_from_assembled_prompt(
            wm.final_prompt,
            wm,
            reasoning_mode=reasoning_mode,
        )
        wm.final_response = response

        _eli_orch_complete_final_stage(
            "completed",
            note="chat_finalized",
        )
        self.engine._in_orchestrator = False
        return {
            "ok": True,
            "action": "CHAT",
            "content": response,
            "response": response,
            "trace": wm.trace,
        }


