# AgentOrchestrator depends on CognitiveEngine's public contract (parse_intent,
# assemble_precise_context, generate_from_assembled_prompt, generate_stream_from_assembled_prompt).
# Keep those GUI methods until PATH2 moves onto engine-native equivalents.

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eli.execution.executor_enhanced import execute as execute_action
from eli.execution.executor_enhanced import SUPPORTED_ACTIONS as _SUPPORTED_ACTIONS

# Normalized set for O(1) validation of ReAct-proposed tool actions.
_VALID_ACTIONS = {str(a).strip().upper() for a in (_SUPPORTED_ACTIONS or [])}



from eli.cognition import memory_diag as _memory_diag
from eli.cognition import query_planner as _query_planner
from eli.cognition.evidence_format import this_conversation as _this_conversation
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


def _recent_turns_limit(reasoning_mode: object = None) -> int:
    """This user's recent turns for the orchestrator's short-term memory."""
    try:
        from eli.core.cognition_tunables import prompt_count
        return max(4, prompt_count("cog.mem_recent_turns", reasoning_mode))
    except Exception:
        return 8


# Only phrases that point back at the answer just given; "again" or "those" alone would hand
# the last period to an unrelated question.
_FOLLOWUP_RE = re.compile(
    r"\b(?:(?:check|look|search|try|go through (?:it|them)) again|check properly|in full|full list|"
    r"all of them|every (?:one|song|track) (?:of them|played)?|the rest|what else|anything else|"
    r"any (?:more|others)|what about the (?:rest|others)|you missed|is that all|that'?s not all|"
    r"should have (?:logs|a record|records))\b", re.I)
_FOLLOWUP_WINDOW_S = 900.0
# About the user's or ELI's own doings ("what did i play", "what did you do"), not a polite
# "can you tell me" wrapped around an outside question.
_PERSONAL_RE = re.compile(
    r"\b(?:i|i'm|i've|i'd|my|mine|we|us|our)\b"
    r"|\b(?:did|have|had|were)\s+you\b|\byou\s+(?:did|ran|played|opened|said|do|done|logged)\b"
    r"|(?<!tell )(?<!show )(?<!give )(?<!let )(?<!remind )(?<!help )\bme\b", re.I)


def _followup_window(engine: Any, user_input: str, window: Any) -> Any:
    """The period this turn is about. A follow-up with no period of its own ("check again in
    full", live after "name all the songs i played yesterday") keeps the previous turn's,
    for 15 minutes. A turn that names a period replaces it."""
    try:
        if window:
            engine._sticky_set("last_query_window", (window, time.time()))
            return window
        prev = engine._sticky_get("last_query_window")
        if (prev and _FOLLOWUP_RE.search(user_input or "")
                and time.time() - float(prev[1]) <= _FOLLOWUP_WINDOW_S):
            log.debug("[ORCHESTRATOR] follow-up keeps the previous period")
            return tuple(prev[0])
    except Exception:
        log.debug("follow-up window skipped", exc_info=True)
    return window


def _period_log_chars(reasoning_mode: object = None) -> int:
    """Room for the period log: a fifth of the loaded context, a little less in quick mode."""
    try:
        from eli.cognition import gguf_inference as _gi
        from eli.cognition.context_budget import chars_per_token
        n_ctx = int(_gi.current_context_limit() or 8192)
        share = 0.15 if str(reasoning_mode or "quick").lower() in ("", "quick", "fast") else 0.2
        return max(2500, min(12000, int(n_ctx * chars_per_token() * share)))
    except Exception:
        return 5000


def _verified_shown_limit(reasoning_mode: object = None) -> int:
    try:
        from eli.core.cognition_tunables import prompt_count
        return max(1, prompt_count("cog.mem_semantic_shown", reasoning_mode))
    except Exception:
        return 12


def _gap_rag_limit() -> int:
    """RAG width for the evidence-gap fallback, when the mode planned none."""
    try:
        from eli.core.cognition_tunables import snapshot as _cog_snapshot
        return max(2, int(_cog_snapshot().get("cog.orch_rag_limit", 24)))
    except Exception:
        return 24


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
        try:
            from eli.cognition.reasoning_modes import orchestrator_planner_mode as _opm
            mode = _opm(reasoning_mode or "balanced")
        except Exception:
            mode = (reasoning_mode or "balanced").lower()
            if mode in {"quick", "fast"}:
                mode = "fast"
            elif mode in {"research", "expert", "tree_of_thoughts", "constitutional_ai", "deep"}:
                mode = "deep"
            else:
                mode = "balanced"

        # Scale retrieval limits by mode budget (same knob as agent timeouts).
        try:
            from eli.cognition.reasoning_modes import mode_budget_multiplier as _mbm
            _budget = float(_mbm(reasoning_mode or "balanced"))
        except Exception:
            _budget = 1.0

        # A question that names a document or a kind of one, or one of the indexed titles.
        doc_query = False
        docs_indexed = False
        try:
            from eli.memory.document_index import asks_about_documents, attached_paths
            _index = getattr(self.engine, "document_rag", None)
            _attached = bool(_index and attached_paths(user_input))
            docs_indexed = _attached or bool(_index and _index.stats()["passages"])
            doc_query = _attached or (docs_indexed and (asks_about_documents(low) or _index.mentions(
                low, str(getattr(self.engine, "user_id", "") or ""))))
        except Exception:
            log.debug("document query check skipped", exc_info=True)
        identity  = any(k in low for k in ("who am i", "my name", "remember me"))
        runtime   = any(k in low for k in ("memory function", "memory work", "cognition", "how do you work"))

        # One tier-scaled read of the tunables. get_tunable() doesn't apply the
        # model-tier scaling, so this path used to gather at small-model limits on
        # any model, and deep modes used fixed 20/20/15, below the balanced default.
        try:
            from eli.core.cognition_tunables import snapshot as _cog_snapshot
            _tn = _cog_snapshot()
        except Exception:
            _tn = {}

        def _lim(key: str, fallback: int, floor: int, scale: float = 1.0,
                 by_mode: bool = True) -> int:
            mult = _budget if by_mode else 1.0
            return max(floor, int(round(float(_tn.get(key, fallback)) * mult * scale)))

        # Every limit sequential_retrieve and unified_retrieval read, so none of
        # them falls back to a hardcoded number.
        common = {
            "kg_limit":      _lim("cog.kg_entities", 8, 2),
            # History depth follows the model tier, not the mode: an expert turn
            # times 2.5 would put ~190 recent turns in front of a slow prefill.
            "recent_limit":  _lim("cog.mem_recent_turns", 30, 4, by_mode=False),
            "summary_limit": _lim("cog.mem_summaries_recall", 40, 2, by_mode=False),
            "hop2_limit":    _lim("cog.mem_hop2_recall", 20, 2),
            "merge_cap":     _lim("cog.mem_merge_cap", 40, 8),
        }

        if mode == "fast":
            return {
                **common,
                "need_keyword":   True,
                "need_semantic":  False,      # not kept unless evidence is thin (see sequential_retrieve)
                "need_rag":       doc_query,  # quick mode reads documents only when asked about one
                "rag_strict":     False,
                "need_kg":        identity,
                "keyword_limit":  _lim("cog.orch_keyword_limit", 32, 4, scale=0.25),
                "semantic_limit": 0,
                "rag_limit":      _lim("cog.orch_rag_limit", 24, 2, scale=0.25) if doc_query else 0,
                "prefer_identity": identity,
                "prefer_runtime":  runtime,
                "skip_hyde":       True,      # signals MemoryAgent to never run HyDE
                "max_react_iter":  1,
            }
        elif mode == "deep":
            # The mode budget (research 200%, expert 250% by default) already
            # widens these; deep never gathers less than balanced.
            return {
                **common,
                "need_keyword":   True,
                "need_semantic":  True,
                # Asked about a document: its best passages. Otherwise only passages that clearly
                # bear on the question, so an indexed library does not pad every prompt.
                "need_rag":       docs_indexed,
                "rag_strict":     not doc_query,
                "need_kg":        True,
                "keyword_limit":  _lim("cog.orch_keyword_limit", 32, 8),
                "semantic_limit": _lim("cog.orch_semantic_limit", 32, 8),
                "rag_limit":      _lim("cog.orch_rag_limit", 24, 4),
                "prefer_identity": identity,
                "prefer_runtime":  runtime,
                "skip_hyde":       False,
                "max_react_iter":  3,
            }
        else:  # balanced (default)
            return {
                **common,
                "need_keyword":   True,
                "need_semantic":  True,
                # Asked about a document: its best passages. Otherwise only passages that clearly
                # bear on the question, so an indexed library does not pad every prompt.
                "need_rag":       docs_indexed,
                "rag_strict":     not doc_query,
                "need_kg":        True,
                "keyword_limit":  _lim("cog.orch_keyword_limit", 32, 4),
                "semantic_limit": _lim("cog.orch_semantic_limit", 32, 4),
                "rag_limit":      _lim("cog.orch_rag_limit", 24, 2),
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

    def sequential_retrieve(self, user_input: str, hyde_query: str,
                          retrieval_plan: Dict[str, Any], ltm: LongTermMemoryRefs):
        """Run retrieval channels in series (embedder is not thread-safe across threads)."""
        keyword_hits: List[Dict[str, Any]] = []
        semantic_hits: List[Dict[str, Any]] = []
        rag_hits: List[Dict[str, Any]] = []
        kg_hits: List[Dict[str, Any]] = []
        # Populated whenever the unified call ran, regardless of whether the mode plan
        # wanted semantic hits kept — see the fetch-plan note below for why.
        _computed_semantic_hits: List[Dict[str, Any]] = []

        if retrieval_plan.get("need_keyword") or retrieval_plan.get("need_semantic"):
            try:
                from eli.memory.unified_retrieval import orchestrator_retrieve
                # mem.recall_memory() (reached via retrieve_for_turn, memory/retrieval.py)
                # runs the vector/FAISS search unconditionally — it has no need_semantic
                # parameter at all. orchestrator_retrieve's need_semantic only decides
                # whether to KEEP those hits or discard them afterward; fast mode's own
                # comment ("skip FAISS embedding, saves one LLM call") does not actually
                # happen on this path — the embedding call already runs regardless.
                # Request both unconditionally so the thin-evidence check below can use
                # hits that were already computed, instead of discarding real signal a
                # fast-mode turn already paid for and then making a genuinely new call.
                _fetch_plan = dict(retrieval_plan)
                _fetch_plan["need_keyword"] = True
                _fetch_plan["need_semantic"] = True
                keyword_hits, _computed_semantic_hits, _tr = orchestrator_retrieve(
                    self.engine,
                    user_input,
                    hyde_query,
                    _fetch_plan,
                    session_id=str(getattr(self.engine, "session_id", "") or ""),
                    user_id=str(getattr(self.engine, "user_id", "") or ""),
                )
                if retrieval_plan.get("need_semantic"):
                    semantic_hits = _computed_semantic_hits
                self._last_turn_retrieval = _tr
                try:
                    setattr(self.engine, "_last_turn_retrieval", _tr)
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
                log.debug(
                    "[ORCHESTRATOR] unified retrieval → keyword=%d semantic=%d elapsed=%.0fms",
                    len(keyword_hits), len(semantic_hits), float(getattr(_tr, "elapsed_ms", 0.0) or 0.0),
                )
            except Exception as _ur_err:
                log.debug(f"[ORCHESTRATOR] unified retrieval failed, falling back: {_ur_err}")
                if retrieval_plan.get("need_keyword"):
                    keyword_hits = self.keyword_search(
                        user_input, retrieval_plan.get("keyword_limit", 12))
                if retrieval_plan.get("need_semantic"):
                    semantic_hits = self.semantic_search(
                        hyde_query or user_input, retrieval_plan.get("semantic_limit", 12))

        if retrieval_plan.get("need_rag") and ltm.rag_ready:
            rag_hits = self.document_rag_search(
                user_input, retrieval_plan.get("rag_limit", 8), strict=bool(retrieval_plan.get("rag_strict")))

        if retrieval_plan.get("prefer_identity") or retrieval_plan.get("need_kg", True):
            kg_hits = self.kg_search(
                user_input, retrieval_plan.get("kg_limit", 8))

        # Evidence-gap fallback: a mode plan that intentionally skipped semantic/rag/kg
        # (fast mode, mainly) can still leave a turn with almost nothing to answer from.
        # Mirrors memory/retrieval.py's own _THIN_EVIDENCE precedent (same threshold,
        # same "ran dry, pull in more" idea) rather than inventing a second, divergent
        # gating constant. Only turns channels ON that the mode plan had OFF — a channel
        # that ran and came back thin is not re-run, since repeating it would just
        # reproduce the same thin result.
        try:
            from eli.memory.retrieval import _THIN_EVIDENCE as _thin_evidence
        except Exception:
            _thin_evidence = 3
        _total_hits = len(keyword_hits) + len(semantic_hits) + len(rag_hits) + len(kg_hits)
        if _total_hits < _thin_evidence:
            if not retrieval_plan.get("need_semantic") and _computed_semantic_hits:
                semantic_hits = _computed_semantic_hits
                log.debug("[ORCHESTRATOR] evidence gap (%d hits) — using already-computed semantic hits",
                         _total_hits)
            if not retrieval_plan.get("need_rag") and ltm.rag_ready:
                rag_hits = self.document_rag_search(
                    user_input, retrieval_plan.get("rag_limit") or _gap_rag_limit(), strict=True)
                if rag_hits:
                    log.debug("[ORCHESTRATOR] evidence gap (%d hits) — enabled rag, got %d",
                             _total_hits, len(rag_hits))
            if not (retrieval_plan.get("prefer_identity") or retrieval_plan.get("need_kg", True)):
                kg_hits = self.kg_search(user_input, retrieval_plan.get("kg_limit") or 8)
                if kg_hits:
                    log.debug("[ORCHESTRATOR] evidence gap (%d hits) — enabled kg, got %d",
                             _total_hits, len(kg_hits))

        return keyword_hits, semantic_hits, rag_hits, kg_hits

    def parallel_retrieve(self, user_input: str, hyde_query: str,
                          retrieval_plan: Dict[str, Any], ltm: LongTermMemoryRefs):
        """Backward-compatible alias — retrieval is sequential (see sequential_retrieve)."""
        return self.sequential_retrieve(user_input, hyde_query, retrieval_plan, ltm)

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
            # The KG character budget the user set (tier-scaled). This was
            # min(2000, limit * 120): ~960 chars at the default limit whatever
            # cog.kg_max_chars said.
            try:
                from eli.core.cognition_tunables import snapshot as _cog_snapshot
                _max_chars = int(_cog_snapshot().get("cog.kg_max_chars", 3200))
            except Exception:
                _max_chars = 3200
            if _max_chars <= 0:
                return []
            _ctx = _kg.context_for_prompt(query, max_chars=_max_chars,
                                          max_entities=max(1, int(limit)))
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
        self, query: str, limit: int, *, strict: bool = False) -> List[Dict[str, Any]]:
        try:
            index = getattr(self.engine, "document_rag", None)
            if index:
                uid = str(getattr(self.engine, "user_id", "") or "")
                # A file handed over with the message is stored now, so this turn can read it, and
                # the search stays inside it. Its vectors follow in the background.
                from eli.memory.document_index import attached_paths
                handed = []
                for path in attached_paths(query):
                    added = index.add(path, user_id=uid, source="attachment", embed=False)
                    if added.get("ok"):
                        handed.append(added["doc_id"])
                        index.note(path, user_id=uid, source="attachment")
                hits = index.search(query, limit=limit, strict=strict and not handed, user_id=uid,
                                    doc_ids=handed or None) or []
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
               hits: List[Dict[str, Any]], top_k: int = 20) -> List[Dict[str, Any]]:
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

    def _bus_result_for_escalation(self, wm) -> Any:
        br = getattr(wm, "bus_result", None)
        if br is not None:
            return br
        spec = (getattr(wm, "trace", None) or {}).get("agent_bus_specialists") or {}
        agg = float(spec.get("aggregated_confidence") or 0.0)
        class _Synth:
            grounding_confidence = agg
            aggregated_confidence = agg
        return _Synth()

    def _maybe_grounding_escalate(
        self,
        wm,
        user_input: str,
        intent: Dict[str, Any],
        *,
        stream: bool,
        reasoning_mode: Optional[str],
    ) -> Any:
        """Web/local escalation before LLM — orchestrator path must not skip this."""
        if getattr(self.engine, "_crisis_steering", None):
            return None
        # A question about the user's own period that the period log answers is not a web
        # question. Live: "what has been going on the past day or two?" was web-searched because
        # the agent bus, which ran no agents in quick mode, scored grounding 0.26.
        _ws = getattr(getattr(getattr(self, "memory_agent", None), "_last_turn_retrieval", None),
                      "window_stats", None) or {}
        if (_ws and (_ws.get("in_window") or _ws.get("turns") or _ws.get("actions"))
                and _PERSONAL_RE.search(user_input or "")):
            log.debug("[ORCHESTRATOR] personal period question answered from its own log — no escalation")
            return None
        try:
            from eli.runtime.grounding_escalation import escalate as _escalate
            _esc = _escalate(
                self.engine,
                user_input,
                intent,
                self._bus_result_for_escalation(wm),
                reasoning_mode=reasoning_mode,
                trace=getattr(wm, "trace", None),
                # Same scope as the episodic block below: this user, any session.
                # Unfiltered, an API turn could escalate on another user's turns.
                recent_turns=getattr(self.engine, "memory", None)
                and self.engine.memory.get_recent_conversation(
                    limit=_recent_turns_limit(reasoning_mode), user_id=self.engine.user_id) or None,
            )
            if _esc is None:
                return None
            _text = str(_esc.get("response") or _esc.get("content") or "").strip()
            if _text:
                try:
                    self.engine._store_assistant_turn(_text)
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            wm.trace["grounding_escalation"] = dict(_esc.get("meta") or {})
            log.debug(
                "[ORCHESTRATOR] grounding escalation short-circuit mode=%s",
                ( _esc.get("meta") or {}).get("response_mode"),
            )
            self.engine._in_orchestrator = False
            if stream and _text:
                def _esc_stream():
                    try:
                        for piece in self.engine._yield_text_chunks(_text, chunk_size=12):
                            yield piece
                    except Exception:
                        yield _text
                return _esc_stream()
            return _esc
        except Exception as _esc_err:
            log.debug(f"[ORCHESTRATOR] grounding escalation skipped: {_esc_err}")
            return None

    def run(self, user_input: Optional[str] = None, *, stream: bool = False,
            reasoning_mode: Optional[str] = None, **kwargs) -> Any:
        user_input = user_input or kwargs.pop("user_input", "")
        if not isinstance(user_input, str):
            user_input = str(user_input or "")

        # Grounded remediation pre-intercept: YES/NO confirmations consume pending repair state
        # before the router or LLM see them; try_handle_query() handles open/launch/check phrasing
        # without full pipeline planning.
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
                log.debug("suppressed exception", exc_info=True)

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
            # this conversation's turns; earlier days come in through retrieval and the period log
            recent_turns=_this_conversation(self.engine.memory.get_recent_conversation(
                limit=_recent_turns_limit(reasoning_mode), user_id=self.engine.user_id) or []),
        )
        ltm = LongTermMemoryRefs(
            sqlite_ready=True,
            vector_ready=hasattr(self.engine.memory, "vector_store"),
            rag_ready=bool(getattr(self.engine, "document_rag", None)),
        )

        wm.trace["stage_1"] = "intent_routing"
        _cached = getattr(self.engine, "_turn_resolved_intent", None)
        if (isinstance(_cached, dict) and _cached.get("text") == user_input
                and isinstance(_cached.get("intent"), dict)
                and _cached["intent"].get("action")):
            intent = dict(_cached["intent"])
            try:
                self.engine._turn_resolved_intent = None
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            log.debug(f"[ORCHESTRATOR] Stage 1: reusing engine-resolved intent → {intent.get('action')}")
        else:
            intent = self.engine.parse_intent(user_input, stm.recent_turns)
        # Honour the engine's META_DIAGNOSTIC->CHAT veto. The orchestrator re-resolves intent, so
        # without this it ran the original status action after the veto had downgraded it.
        if getattr(self.engine, "_eli_phase13_chat_override", False):
            try:
                self.engine._eli_phase13_chat_override = False
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            if str(intent.get("action", "")).upper() != "CHAT":
                log.debug(f"[ORCHESTRATOR] Phase-13 veto honoured → CHAT (was {intent.get('action')})")
                intent = {"action": "CHAT", "args": {"message": user_input},
                          "confidence": 0.9, "meta": {"matched_by": "phase13_chat_veto"}}
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
                    reasoning_mode=reasoning_mode,
                )
                wm.bus_result = bus_result
                # Mirror the CHAT path's rotation: non-CHAT turns (RUNTIME_STATUS, MEMORY_STATUS...)
                # also feed the next turn's persona handoff, or LAST_TURN_TRACE goes stale on a
                # follow-up.
                try:
                    self.engine._prev_bus_result = getattr(
                        self.engine, "_last_bus_result", None)
                    self.engine._last_bus_result = bus_result
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
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
                        log.debug("suppressed exception", exc_info=True)

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
                            reasoning_mode=reasoning_mode,
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

            _eli_orch_evidence_ok = True
            try:
                import os as _eli_orch_os
                from eli.contracts.grounded_control import (
                    GROUNDED_CONTROL_ACTIONS as _ELI_ORCH_GC, evidence_complete_for_action)
                if action in _ELI_ORCH_GC:
                    _eli_orch_evidence_ok = (
                        _eli_orch_os.environ.get("ELI_EVIDENCE_GATE_DISABLE", "").lower() in ("1", "true")
                        or evidence_complete_for_action(action, result)
                    )
            except Exception:
                _eli_orch_evidence_ok = True

            if _eli_orch_evidence_ok:
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
        retrieval_plan["window"] = _followup_window(self.engine, user_input,
                                                    _query_planner.plan_window(user_input))
        log.debug("[ORCHESTRATOR] Stage 4: Planner → mode=%s %s" % (
            reasoning_mode or "balanced", retrieval_plan))
        _eli_pipe_orch("stage_4", mode=(reasoning_mode or "balanced"))

        wm.trace["stage_3"] = "hyde_query_expansion"
        wm.hyde_query = self.memory_agent.build_hyde_query(
            user_input, skip_hyde=retrieval_plan.get("skip_hyde", False))
        hyde_preview = wm.hyde_query[:60] + "..." if len(wm.hyde_query) > 60 else wm.hyde_query
        log.debug(f"[ORCHESTRATOR] Stage 3: HyDE Query → {hyde_preview}")
        _eli_pipe_orch("stage_3", hyde_chars=len(wm.hyde_query or ""))

        wm.trace["stage_5_6_7"] = "sequential_retrieval"
        keyword_hits, semantic_hits, rag_hits, kg_hits = self.memory_agent.sequential_retrieve(
            user_input=user_input,
            hyde_query=wm.hyde_query,
            retrieval_plan=retrieval_plan,
            ltm=ltm,
        )
        wm.keyword_hits = keyword_hits
        wm.semantic_hits = semantic_hits
        wm.rag_hits = rag_hits
        wm.kg_hits = kg_hits
        # "rag: 0" on its own read as a search that found nothing; say what there was to search.
        _rag_note: Any = len(rag_hits)
        if not ltm.rag_ready:
            _rag_note = "off"
        elif not rag_hits:
            try:
                _dstats = self.engine.document_rag.stats()
                _rag_note = (f"0 of {_dstats['passages']} passages in {_dstats['documents']} documents"
                             if _dstats["passages"] else "0 (no documents indexed yet)")
            except Exception:
                log.debug("document stats unavailable", exc_info=True)
        log.debug(f"[ORCHESTRATOR] Stage 5/6/7: Sequential Retrieval → keyword: {len(keyword_hits)} semantic: {len(semantic_hits)} rag: {_rag_note} kg: {len(kg_hits)}")
        _eli_pipe_orch("stage_5_6_7", keyword=len(keyword_hits), semantic=len(semantic_hits), rag=len(rag_hits), kg=len(kg_hits))
        try:
            from eli.kernel.request_context import note_turn_fact as _note
            _wsn = getattr(getattr(self.memory_agent, "_last_turn_retrieval", None), "window_stats", None) or {}
            _note("retrieval", f"keyword {len(keyword_hits)}, semantic {len(semantic_hits)}, "
                               f"documents {len(rag_hits)}, graph {len(kg_hits)}"
                  + (f"; period {time.strftime('%d %b', time.localtime(_wsn['since']))}-"
                     f"{time.strftime('%d %b', time.localtime(_wsn['until']))}: {_wsn.get('turns', 0)} turns, "
                     f"{_wsn.get('actions', 0)} actions" if _wsn else ""))
        except Exception:
            log.debug("retrieval note skipped", exc_info=True)

        wm.trace["stage_8"] = "hybrid_merge"
        # The plan's merge_cap (40 by default, scaled by mode); this was a fixed 20 whatever the
        # mode gathered, so Advanced cut 110 hits to 20 before ranking.
        # Document passages are shown whole in their own block below, not cut to evidence-row length.
        wm.merged_hits = self.memory_agent.hybrid_merge(
            keyword_hits, semantic_hits, [], kg_hits=kg_hits,
            limit=max(8, int(retrieval_plan.get("merge_cap") or 20)))
        log.debug(f"[ORCHESTRATOR] Stage 8: Hybrid Merge → {len(wm.merged_hits)} items")
        _eli_pipe_orch("stage_8", merged=len(wm.merged_hits))

        wm.trace["stage_9"] = "heuristic_rerank"
        from eli.core.cognition_tunables import get_tunable as _cog_get
        from eli.cognition.reranker import rerank_candidates as _rerank
        _top_k = int(_cog_get("cog.rerank_top_k"))
        wm.reranked_hits = _rerank(user_input, wm.merged_hits, limit=_top_k)
        log.debug(f"[ORCHESTRATOR] Stage 9: Heuristic Rerank → {len(wm.reranked_hits)} items")
        _eli_pipe_orch("stage_9", reranked=len(wm.reranked_hits), method="heuristic_rerank")

        # Specialist AgentBus (memory prefetched above — no duplicate recall).
        try:
            from eli.cognition.agent_bus import (
                dispatch_specialists as _dispatch_spec,
                _ALL_AGENTS as _bus_agents,
                _query_mentions_code_or_architecture as _code_q,
            )
            from eli.cognition.reasoning_modes import mode_chat_agent_profile as _mcp
            _profile = _mcp(reasoning_mode, code_query=_code_q(user_input))
            if _profile is None:
                _spec_names = {
                    a.name for a in _bus_agents
                    if getattr(a, "_enabled", True) and a.name != "memory"
                }
            else:
                _spec_names = {n for n in _profile if n != "memory"}
                _spec_names.add("critic")
            wm.bus_result = _dispatch_spec(
                user_input, intent,
                session_id=self.engine.session_id,
                user_id=self.engine.user_id,
                reasoning_mode=reasoning_mode,
                skip_memory=True,
                agent_names=_spec_names,
            )
            try:
                self.engine._last_bus_result = wm.bus_result
                self.engine._last_orchestrator_trace = dict(getattr(wm, "trace", {}) or {})
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            wm.trace["agent_bus_specialists"] = {
                "agents_used": list(getattr(wm.bus_result, "agents_used", []) or []),
                "aggregated_confidence": float(
                    getattr(wm.bus_result, "aggregated_confidence", 0.0) or 0.0),
            }
            _eli_pipe_orch("agent_bus_specialists",
                           agents=len(wm.trace["agent_bus_specialists"]["agents_used"]))
        except Exception as _spec_err:
            wm.trace["agent_bus_specialists"] = {"error": str(_spec_err)}
            log.debug(f"[ORCHESTRATOR] specialist bus failed (non-fatal): {_spec_err}")

        try:
            self.engine._pending_recall_ids = [
                int(h["id"]) for h in wm.merged_hits
                if str(h.get("id", "")).isdigit() and int(h["id"]) > 0][:5]
        except Exception:
            log.debug("recalled ids not recorded", exc_info=True)
        try:
            _agg = getattr(wm.bus_result, "aggregated_confidence", None)
            # With no agent run (quick mode) the bus aggregate is a constant, not a measure of
            # this retrieval: "confidence 0.26 (very low)" sat above the period log that
            # answered the question.
            if not list(getattr(wm.bus_result, "agents_used", None) or []):
                _agg = None
            self.engine._memory_diag = _memory_diag.retrieval_record(
                len(keyword_hits), len(semantic_hits), len(kg_hits), len(wm.merged_hits),
                float(_agg) if _agg is not None else None,
                window=getattr(getattr(self.memory_agent, "_last_turn_retrieval", None), "window_stats", None),
                searched=getattr(getattr(self.memory_agent, "_last_turn_retrieval", None), "searched", None))
        except Exception:
            log.debug("memory diagnostics skipped", exc_info=True)
        wm.trace["stage_10"] = "context_assembly"
        wm.assembled_context, wm.final_prompt = self.engine.assemble_precise_context(
            user_input=user_input,
            working_memory=wm,
            short_term_memory=stm,
            intent=intent,
            reasoning_mode=reasoning_mode,
        )
        try:
            from eli.memory.unified_retrieval import format_verified_memory_block
            _tr = getattr(self.memory_agent, "_last_turn_retrieval", None)
            # Was the default shown=6 on every orchestrated turn.
            _verified = format_verified_memory_block(
                _tr, shown=_verified_shown_limit(reasoning_mode)) if _tr else ""
            if _verified and _verified not in (wm.assembled_context or ""):
                wm.assembled_context = (
                    _verified + "\n\n" + str(wm.assembled_context or "").strip()
                ).strip()
                wm.verified_memory_block = _verified
        except Exception as _vmb_err:
            log.debug(f"[ORCHESTRATOR] verified memory block inject skipped: {_vmb_err}")
        _period = ""
        try:
            from eli.memory.unified_retrieval import format_period_log
            _period = format_period_log(getattr(self.memory_agent, "_last_turn_retrieval", None),
                                        user_input, max_chars=_period_log_chars(reasoning_mode))
            if _period:
                wm.assembled_context = (_period + "\n\n" + str(wm.assembled_context or "").strip()).strip()
        except Exception as _pl_err:
            log.debug(f"[ORCHESTRATOR] period log skipped: {_pl_err}")
        try:
            if rag_hits:
                from eli.memory.document_index import format_passages
                _passages = format_passages(rag_hits, max_chars=_period_log_chars(reasoning_mode))
                if _passages:
                    wm.assembled_context = (_passages + "\n\n" + str(wm.assembled_context or "").strip()).strip()
        except Exception as _dp_err:
            log.debug(f"[ORCHESTRATOR] document passages skipped: {_dp_err}")
        # Asked about its own behaviour, ELI gets what the pipeline recorded doing; routing and
        # escalation never reach the model, so without this any account is invented.
        try:
            from eli.cognition import self_claims as _self_claims
            if _self_claims.asks_about_own_behaviour(user_input):
                _rows = _self_claims.turn_record_lines(
                    getattr(self.engine, "memory", None), user_id=str(getattr(self.engine, "user_id", "") or ""))
                if _rows:
                    wm.assembled_context = (_self_claims.record_block(_rows) + "\n\n"
                                            + str(wm.assembled_context or "").strip()).strip()
                    # What the reply is checked against: the pipeline's rows and the period log,
                    # never ELI's own earlier prose.
                    from eli.kernel.request_context import note_turn_fact as _note_record
                    _note_record("_record_lines", _rows)
                    _note_record("_record", "\n".join(_rows) + "\n" + str(_period or ""))
        except Exception as _tr_err:
            log.debug(f"[ORCHESTRATOR] turn record skipped: {_tr_err}")
        try:
            setattr(
                self.engine,
                "_last_orchestrator_memory_context",
                str(getattr(wm, "assembled_context", "") or ""),
            )
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        _diag_block = _memory_diag.block(getattr(self.engine, "_memory_diag", None))
        if _diag_block:
            wm.assembled_context = f"{_diag_block}\n\n{wm.assembled_context}".strip()
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
                    reasoning_mode=reasoning_mode,
                )
            _ph = str(getattr(wm, "persona_handoff", "") or "")
            log.debug(f"[ORCHESTRATOR] Stage 10.5: Persona Handoff → {len(_ph)} chars")
        except Exception as _ph_err:
            log.debug(f"[ORCHESTRATOR] Stage 10.5: Persona Handoff unavailable: {_ph_err}")

        # Private reasoning modes (chain_of_thought, self_consistency, tree_of_thoughts,
        # constitutional_ai) must hand off to _run_chat_reasoning_loop, or the call below collapses
        # to a single GGUF call and the mode's algorithm never runs. Quick mode is untouched.
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

        _esc_early = self._maybe_grounding_escalate(
            wm, user_input, intent, stream=stream, reasoning_mode=reasoning_mode,
        )
        if _esc_early is not None:
            return _esc_early

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


