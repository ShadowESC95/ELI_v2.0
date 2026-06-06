"""
eli/brain/agents/agent_bus.py

Multi-agent orchestration layer for ELI.

Architecture
------------
Every user request is dispatched through the AgentBus.  The bus determines
which specialist agents are relevant, runs them concurrently in a thread pool
(each with a hard timeout so a slow agent never blocks the response), then
aggregates their evidence into a single DispatchResult that the CognitiveEngine
uses to build a richer, more confident reply.

Agents are evidence-gatherers and action-executors, not LLM proxies.
The LLM synthesis step still lives in CognitiveEngine._get_chat_response().

Agent roster
-----------
  MemoryAgent          – semantic recall, conversation history, stored facts,
                         habit rules, session summaries
  SystemAgent          – OS actions: open apps/files/URLs, volume, screenshot,
                         clipboard, keyboard, shell, timers, alarms
  HabitAgent           – pattern detection, automation rule proposals,
                         event logging for app launches
  SelfImprovementAgent – failure logging, improvement proposals, correction loop
  ProactiveAgent       – background daemon status, morning report, insights
  FrontierAgent        – cross-system runtime matrix (memory/self/proactive/
                         image/world/labs/chatflow)
  PluginAgent          – weather, calendar, web automation, document reader,
                         PDF/CSV analysis, smart home
  VoiceAgent           – TTS/STT status, voice preference queries
  KnowledgeAgent       – pure-LLM synthesis fallback (used when no other agent
                         supplies grounded evidence)

Confidence model
----------------
Each AgentResult carries a raw confidence (0.0–1.0).  The bus aggregates
them using a weighted scheme:

  base          = router intent confidence  (0.0–1.0)
  memory hit    += 0.08 per relevant result (capped at +0.20)
  system ok     += 0.15 if action succeeded, -0.10 if failed
  plugin data   += 0.12 if plugin returned a real result
  habit match   += 0.06 per matched rule
  multi-agent   += 0.05 if ≥ 3 agents contributed evidence
  grounded      += 0.08 if executor evidence has file paths / line numbers

Final score is clamped to [0.02, 0.98].

Offline guarantee
-----------------
No agent makes any network call.  All I/O is local SQLite, local filesystem,
or subprocess calls to system binaries (playerctl, paplay, etc.).
"""

from __future__ import annotations
import os
import re

from pathlib import Path
import sqlite3 as _sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set



from eli.utils.log import get_logger
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Agent dispatch persistence
# ---------------------------------------------------------------------------

def _persist_dispatch_result(
    action: str,
    agents_used: List[str],
    confidence: float,
    elapsed_ms: float,
    ok: bool,
    summary: str,
) -> None:
    """Write a summary row to agent.sqlite3 in a daemon thread (non-blocking).

    Creates the agent_dispatches table on first use.  Failures are silently
    swallowed so the dispatch path is never blocked by a DB write error.
    """
    def _write() -> None:
        try:
            from eli.core.paths import agent_db_path as _agent_db_path
            db_path = _agent_db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with _sqlite3.connect(str(db_path), timeout=3.0) as _conn:
                _conn.execute(
                    """CREATE TABLE IF NOT EXISTS agent_dispatches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        action TEXT,
                        agents_used TEXT,
                        confidence REAL,
                        elapsed_ms REAL,
                        ok INTEGER,
                        summary TEXT
                    )"""
                )
                _conn.execute(
                    "INSERT INTO agent_dispatches "
                    "(ts, action, agents_used, confidence, elapsed_ms, ok, summary) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        time.time(),
                        action,
                        ",".join(agents_used),
                        round(confidence, 4),
                        round(elapsed_ms, 1),
                        1 if ok else 0,
                        summary[:500],
                    ),
                )
                _conn.commit()
        except Exception:
            pass  # Never block the dispatch path

    threading.Thread(target=_write, daemon=True, name="eli-agent-persist").start()


# ---------------------------------------------------------------------------
# Evidence-driven confidence scoring (no hardcoded per-agent weights)
# ---------------------------------------------------------------------------
#
# Design constants. These describe the *structure* of the scoring algorithm,
# not arbitrary per-agent weights. Per-agent contributions are derived from
# (agent.confidence × evidence_density × calibration), all dynamic.

_ROUTE_BASE_WEIGHT = 0.30          # route-certainty share of total score
_SINGLE_AGENT_CAP = 0.30           # max contribution from any one agent
_EMPTY_BUS_CEILING = 0.65          # score ceiling when no grounded evidence
_DENSITY_SCALE = 1500.0            # chars-equivalent where density ≈ 0.63
_LIST_ITEM_CHAR_EQUIV = 50         # treat each list item as N chars
_CALIBRATION_MIN_RUNS = 5          # need this many runs before calibration applies
_CALIBRATION_HALF_LIFE = 50.0      # EMA half-life in runs
_METRICS_CACHE_TTL_S = 30.0        # how long to cache calibration table reads

_EVIDENCE_KEYS = (
    "snippets", "results", "hits", "items", "content",
    "entries", "rules", "insights", "memory_context",
)

_metrics_cache_lock = threading.Lock()
_metrics_cache: Dict[str, Any] = {"loaded_at": 0.0, "rows": {}}


def _evidence_density(data: Dict[str, Any]) -> float:
    """Continuous payload measure in [0, 1].

    Sums list lengths (weighted by _LIST_ITEM_CHAR_EQUIV) plus string lengths
    across known evidence keys, then maps through 1 - exp(-x/scale) so the
    response is smooth: more evidence → higher density, asymptotic to 1.

    A 200-char one-liner ≈ 0.12; a 1500-char report ≈ 0.63; 5000 chars ≈ 0.96.
    """
    import math
    if not isinstance(data, dict):
        return 0.0
    total = 0.0
    for k in _EVIDENCE_KEYS:
        v = data.get(k)
        if isinstance(v, (list, tuple)):
            total += float(len(v)) * float(_LIST_ITEM_CHAR_EQUIV)
        elif isinstance(v, str):
            total += float(len(v))
    if total <= 0:
        return 0.0
    return float(1.0 - math.exp(-total / float(_DENSITY_SCALE)))


def _stage_score_for_result(r: "AgentResult") -> Optional[float]:
    """Bridge agent result to evidence_arbitration scoring helpers when applicable.

    Returns a confidence-style score in [0, 1] for results that look like tool
    invocations (have 'ok'/'status'/'action' shape), else None so the caller
    falls back to agent.confidence alone.
    """
    try:
        from eli.runtime.evidence_arbitration import _score_tool_result
    except Exception:
        return None
    d = r.data or {}
    if not isinstance(d, dict):
        return None
    if not any(k in d for k in ("ok", "status", "action")):
        return None
    try:
        return float(_score_tool_result(d).score)
    except Exception:
        return None


def _agent_metrics_db_path() -> Optional[Any]:
    try:
        from eli.core.paths import agent_db_path as _agent_db_path
        p = _agent_db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return None


def _ensure_agent_metrics_table(conn: "_sqlite3.Connection") -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_metrics (
            agent TEXT NOT NULL,
            action TEXT NOT NULL,
            runs INTEGER NOT NULL DEFAULT 0,
            contributions INTEGER NOT NULL DEFAULT 0,
            sum_self_conf REAL NOT NULL DEFAULT 0.0,
            sum_density REAL NOT NULL DEFAULT 0.0,
            rolling_score REAL NOT NULL DEFAULT 0.5,
            last_updated REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY (agent, action)
        )"""
    )


def _load_agent_metrics_cached() -> Dict[tuple, Dict[str, float]]:
    """Return {(agent, action): {runs, rolling_score, ...}} with TTL cache."""
    now = time.time()
    with _metrics_cache_lock:
        if now - float(_metrics_cache.get("loaded_at", 0.0)) < _METRICS_CACHE_TTL_S:
            return dict(_metrics_cache.get("rows", {}) or {})
    rows: Dict[tuple, Dict[str, float]] = {}
    db_path = _agent_metrics_db_path()
    if db_path is not None:
        try:
            with _sqlite3.connect(str(db_path), timeout=2.0) as conn:
                _ensure_agent_metrics_table(conn)
                cur = conn.execute(
                    "SELECT agent, action, runs, contributions, "
                    "sum_self_conf, sum_density, rolling_score FROM agent_metrics"
                )
                for agent, action, runs, contribs, sc, sd, rs in cur.fetchall():
                    rows[(str(agent), str(action))] = {
                        "runs": int(runs or 0),
                        "contributions": int(contribs or 0),
                        "sum_self_conf": float(sc or 0.0),
                        "sum_density": float(sd or 0.0),
                        "rolling_score": float(rs or 0.5),
                    }
        except Exception:
            pass
    with _metrics_cache_lock:
        _metrics_cache["loaded_at"] = now
        _metrics_cache["rows"] = dict(rows)
    return rows


def _calibration_factor(
    agent: str,
    action: str,
    metrics: Dict[tuple, Dict[str, float]],
) -> float:
    """Return a multiplier in [0.5, 1.5] derived from rolling success.

    Returns 1.0 (neutral) when fewer than _CALIBRATION_MIN_RUNS data points
    exist. Otherwise: factor = 0.5 + rolling_score, clamped.
    """
    row = metrics.get((agent, action))
    if not row or int(row.get("runs", 0)) < _CALIBRATION_MIN_RUNS:
        return 1.0
    rs = float(row.get("rolling_score", 0.5))
    return max(0.5, min(1.5, 0.5 + rs))


def _persist_agent_metrics_for_dispatch(
    action: str,
    results: List["AgentResult"],
) -> None:
    """Update agent_metrics rows in a daemon thread.

    For each agent that ran, increments runs; if it had evidence, updates
    contributions, sums, and rolling_score (EMA of self_conf × density).
    """
    snapshots = []
    for r in results:
        try:
            if not r.ok or (r.data or {}).get("skipped"):
                continue
            self_conf = max(0.0, min(1.0, float(r.confidence or 0.0)))
            density = _evidence_density(r.data or {}) if r.has_evidence else 0.0
            snapshots.append((str(r.agent), self_conf, density, bool(r.has_evidence)))
        except Exception:
            continue
    if not snapshots:
        return

    def _write() -> None:
        try:
            db_path = _agent_metrics_db_path()
            if db_path is None:
                return
            alpha = 1.0 - 0.5 ** (1.0 / float(_CALIBRATION_HALF_LIFE))
            now = time.time()
            with _sqlite3.connect(str(db_path), timeout=3.0) as conn:
                _ensure_agent_metrics_table(conn)
                # Atomic upsert: all arithmetic happens in SQL so concurrent
                # writers can't lose increments via read-modify-write races.
                for agent, self_conf, density, has_ev in snapshots:
                    sample = self_conf * density  # in [0, 1]
                    contrib_inc = 1 if has_ev else 0
                    sc_inc = self_conf if has_ev else 0.0
                    d_inc = density if has_ev else 0.0
                    conn.execute(
                        "INSERT INTO agent_metrics "
                        "(agent, action, runs, contributions, sum_self_conf, "
                        "sum_density, rolling_score, last_updated) "
                        "VALUES (?, ?, 1, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(agent, action) DO UPDATE SET "
                        "runs = runs + 1, "
                        "contributions = contributions + excluded.contributions, "
                        "sum_self_conf = sum_self_conf + excluded.sum_self_conf, "
                        "sum_density = sum_density + excluded.sum_density, "
                        "rolling_score = (1 - ?) * rolling_score + ? * ?, "
                        "last_updated = excluded.last_updated",
                        (
                            agent, action,
                            contrib_inc, sc_inc, d_inc,
                            # First-insert rolling: start at neutral 0.5 then
                            # EMA toward this sample.
                            (1.0 - alpha) * 0.5 + alpha * sample,
                            now,
                            alpha, alpha, sample,
                        ),
                    )
                conn.commit()
            with _metrics_cache_lock:
                _metrics_cache["loaded_at"] = 0.0  # invalidate cache
        except Exception:
            pass

    threading.Thread(target=_write, daemon=True, name="eli-agent-metrics").start()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    agent: str
    ok: bool
    confidence: float          # 0.0 – 1.0, agent-local assessment
    data: Dict[str, Any]       # raw payload (memory hits, action result, etc.)
    elapsed_ms: float = 0.0
    error: Optional[str] = None

    @property
    def has_evidence(self) -> bool:
        """True when the agent returned non-empty, non-error data."""
        if not self.ok:
            return False
        d = self.data or {}
        for key in ("snippets", "results", "hits", "items", "content", "entries", "rules", "insights", "memory_context", "failures", "proposals"):
            v = d.get(key)
            if isinstance(v, (list, tuple)) and len(v) > 0:
                return True
            if isinstance(v, str) and v.strip():
                return True
        return False


@dataclass
class DispatchResult:
    intent_action: str
    intent_confidence: float
    agent_results: List[AgentResult] = field(default_factory=list)
    memory_context: str = ""
    action_result: Optional[Dict[str, Any]] = None   # for non-CHAT intents
    aggregated_confidence: float = 0.0               # composite (route + grounding)
    confidence_label: str = ""                        # human-readable tier
    grounding_confidence: float = 0.0                # answer quality signal (agent evidence only)
    agents_used: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    orchestrator_plan: Optional[Dict[str, Any]] = None  # multi-step plan from OrchestratorAgent
    execution_plan: Optional[Dict[str, Any]] = None  # canonical typed ExecutionPlan (execution_planner) that drove selection

    def to_context_block(self) -> str:
        """Serialise agent evidence into a compact text block for LLM injection."""
        parts: List[str] = []
        if self.memory_context:
            parts.append(self.memory_context)
        for r in self.agent_results:
            if not r.has_evidence:
                continue
            d = r.data or {}
            if r.agent == "file_code" and d.get("snippets"):
                snippets = d["snippets"][:12]
                parts.append("Source code evidence (file:line: content):\n" + "\n".join(snippets))
            elif r.agent == "reflection" and d.get("insights"):
                insights = d["insights"][:6]
                lines = [f"  - {i}" for i in insights]
                parts.append("Recent ELI reflections/observations:\n" + "\n".join(lines))
            elif r.agent == "system" and d.get("content"):
                parts.append(f"Runtime/system evidence:\n{str(d['content'])[:1200]}")
            elif r.agent == "capability" and d.get("content"):
                parts.append(f"Capability evidence:\n{str(d['content'])[:600]}")
            elif r.agent == "habit" and d.get("rules"):
                rules = d["rules"][:5]
                lines = [f"  - {rule.get('name', '')} @ {rule.get('hour', 0):02d}:{rule.get('minute', 0):02d}"
                         for rule in rules]
                parts.append("Habit automation rules:\n" + "\n".join(lines))
            elif r.agent == "self_improvement" and d.get("failures"):
                fails = d["failures"][:5]
                lines = [f"  - {f.get('user_input', '')[:80]}" for f in fails]
                parts.append("Recent ELI failure log:\n" + "\n".join(lines))
            elif r.agent == "proactive" and d.get("insights"):
                insights = d["insights"][:3]
                lines = [f"  - {i}" for i in insights]
                parts.append("Proactive insights:\n" + "\n".join(lines))
            elif r.agent == "frontier" and d.get("content"):
                parts.append(f"Frontier system matrix:\n{str(d['content'])[:1200]}")
            elif r.agent == "plugin" and d.get("content"):
                parts.append(f"Plugin result:\n{str(d['content'])[:600]}")
            elif r.agent == "introspection" and d.get("content"):
                parts.append(f"ELI architecture/pipeline (grounded):\n{str(d['content'])[:1000]}")
            elif r.agent == "voice" and d.get("content"):
                parts.append(f"Voice/TTS status:\n{str(d['content'])[:300]}")
        return "\n\n".join(p for p in parts if p.strip())


def _confidence_label(score: float) -> str:
    if score >= 0.88:
        return "very high"
    if score >= 0.72:
        return "high"
    if score >= 0.56:
        return "moderate"
    if score >= 0.38:
        return "low"
    return "very low"


def _query_is_grounded(user_input: str, action: str) -> bool:
    """Delegate to the canonical single-source-of-truth in eli.core.grounding."""
    try:
        from eli.core.grounding import is_grounded_query
        return is_grounded_query(user_input, action)
    except Exception:
        # Fallback: at minimum honour the action set.
        return action in {
            "RUNTIME_AUDIT", "IMPORT_AUDIT", "RESOLVE_RUNTIME_PATHS",
            "GUI_RUNTIME_AUDIT", "EXPLAIN_MEMORY_RUNTIME",
            "EXPLAIN_COGNITION_RUNTIME", "RUNTIME_STATUS", "MEMORY_STATUS",
            "COGNITION_STATUS", "LIST_CAPABILITIES", "AWARENESS_STATUS",
            "CODE_CHANGES", "FRONTIER_STATUS", "ELI_IDENTITY_AUDIT",
        }


def _query_mentions_code_or_architecture(user_input: str) -> bool:
    low = (user_input or "").strip().lower()
    triggers = (
        "pipeline", "stages", "agent", "agents", "orchestrator", "file", "files",
        "path", "paths", "line ", ".py", "module", "import", "wiring", "code",
        "architecture", "how do you work", "how does your cognition",
        "prompt to response", "prompt->response",
    )
    return any(t in low for t in triggers)


def _select_agents_for_intent(user_input: str, action: str) -> Optional[Set[str]]:
    """
    Return a minimal specialist set for grounded non-chat actions.

    CHAT retains the default broad fanout.  Runtime/status queries should not
    pull in habit/reflection/KG/memory unless the user is actually asking for
    those dimensions.
    """
    low = (user_input or "").strip().lower()
    action = (action or "CHAT").upper().strip()
    identity_terms = (
        "who are you",
        "what are you",
        "tell me about yourself",
        "your identity",
        "your persona",
        "persona",
        "identity",
        "self aware",
        "self-aware",
    )

    if action == "RUNTIME_STATUS":
        selected = {"system", "introspection", "orchestrator"}
        if _query_mentions_code_or_architecture(user_input):
            selected.add("file_code")
        if any(t in low for t in ("capability", "capabilities", "what can you do", "can you do")):
            selected.add("capability")
        if any(t in low for t in ("memory", "remember", "stored")):
            selected.add("memory")
        if any(t in low for t in identity_terms):
            selected.update({"memory", "reflection"})
        return selected

    if action == "SELF_REPORT":
        selected = {"system", "memory", "reflection", "introspection", "orchestrator"}
        if _query_mentions_code_or_architecture(user_input):
            selected.add("file_code")
        if any(t in low for t in ("entity", "entities", "relation", "graph", "knowledge graph")):
            selected.add("knowledge_graph")
        if any(t in low for t in ("capability", "capabilities", "what can you do", "can you do")):
            selected.add("capability")
        return selected

    if action in {"USER_IDENTITY_SUMMARY", "PERSONAL_MEMORY_SUMMARY", "PERSONAL_MEMORY_DEEP_EXPLAIN"}:
        # Focused identity/profile set — no file_code (code snippets inflate
        # context without adding value to "who am i" answers).
        selected = {"system", "memory", "orchestrator"}
        if any(t in low for t in ("reflection", "patterns", "noticed", "insight")):
            selected.add("reflection")
        if any(t in low for t in ("entity", "entities", "relation", "graph", "knowledge graph")):
            selected.add("knowledge_graph")
        return selected

    if action in {
        "FRONTIER_STATUS",
        "ELI_IDENTITY_AUDIT",
        "COGNITION_STATUS",
        "RUNTIME_AUDIT",
        "IMPORT_AUDIT",
        "RESOLVE_RUNTIME_PATHS",
        "GUI_RUNTIME_AUDIT",
        "EXPLAIN_COGNITION_RUNTIME",
        "CODE_CHANGES",
        "AWARENESS_STATUS",
    }:
        selected = {"system", "introspection", "file_code", "orchestrator"}
        if action == "AWARENESS_STATUS" or any(
            t in low for t in ("capability", "capabilities", "manifest")
        ):
            selected.add("capability")
        if any(t in low for t in ("memory", "sqlite", "database", "db")):
            selected.add("memory")
        if action in {"FRONTIER_STATUS", "ELI_IDENTITY_AUDIT"}:
            selected.update({"proactive", "reflection", "frontier"})
        return selected

    if action in {
        "MEMORY_STATUS",
        "MEMORY_RECALL",
        "EXPLAIN_MEMORY_RUNTIME",
        "PERSONAL_MEMORY_SUMMARY",
        "PERSONAL_MEMORY_DEEP_EXPLAIN",
    }:
        selected = {"system", "memory", "orchestrator"}
        if _query_mentions_code_or_architecture(user_input):
            selected.add("introspection")
        if any(t in low for t in ("entity", "entities", "relation", "graph", "knowledge graph")):
            selected.add("knowledge_graph")
        if any(t in low for t in ("reflection", "patterns", "noticed", "insight")):
            selected.add("reflection")
        return selected

    return None


# ---------------------------------------------------------------------------
# Agent dependency DAG
# ---------------------------------------------------------------------------
# Edges among bus agents: {agent: {agents it depends on}}. The bus builds a DAG
# from the *selected* agents intersected with this map, runs them in topological
# layers, and passes each completed layer's results to downstream agents via
# intent["_upstream"]. Agents with no declared dependency stay in the first
# layer and run fully in parallel (identical to the legacy flat fan-out).
#
# knowledge_graph ← memory: the KG agent seeds its lookup with what the memory
# agent surfaced this turn (see KnowledgeGraphAgent.run). Add more edges here to
# express further dependencies; cycles are rejected at build time.
_AGENT_DEPENDENCIES: Dict[str, Set[str]] = {
    "knowledge_graph": {"memory"},
}


def _agent_execution_layers(active_names: List[str]) -> List[List[str]]:
    """Topological layers for the active agent set, honouring _AGENT_DEPENDENCIES
    (restricted to the active set). Returns a single layer on any error so the
    bus can never be broken by the DAG."""
    try:
        from eli.core.dag import build_dag
        deps = {n: set(_AGENT_DEPENDENCIES.get(n, set())) & set(active_names) for n in active_names}
        return build_dag(deps).topological_layers()
    except Exception as exc:
        log.debug(f"[AGENTBUS] layer build failed, using single layer: {exc}")
        return [list(active_names)]


# ---------------------------------------------------------------------------
# Individual agents
# ---------------------------------------------------------------------------

class _BaseAgent:
    name: str = "base"
    timeout_s: float = 4.0
    _enabled: bool = True  # can be toggled from Advanced Settings at runtime

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        raise NotImplementedError



# ELI_MEMORY_RELEVANCE_GUARD_20260502
def _eli_memory_should_run(user_input: str, action: str) -> bool:
    low = re.sub(r"\s+", " ", str(user_input or "").lower()).strip(" .,!?:;")
    action = str(action or "CHAT").upper().strip()
    words = re.findall(r"[a-z0-9']+", low)

    # Explicit memory/profile/introspection actions are allowed to use memory.
    if action in {
        "MEMORY_RECALL",
        "MEMORY_STATUS",
        "MEMORY_STORE",
        "SELF_REPORT",
        "USER_IDENTITY_SUMMARY",
        "EXPLAIN_MEMORY_RUNTIME",
        "PERSONAL_MEMORY_SUMMARY",
        "PERSONAL_MEMORY_DEEP_EXPLAIN",
    }:
        return True

    # Direct commands/news/search/open/media/system actions should not receive
    # old conversation snippets. That is how stale "Immutable Techniques" garbage
    # contaminated live commands.
    if action != "CHAT":
        return False

    memory_markers = (
        "memory", "remember", "recall", "previous", "earlier", "last time",
        "what do you know about me", "who am i", "what is my name",
        "do you remember me", "do you know me", "my preferences",
        "from memory", "stored", "profile",
    )
    if any(m in low for m in memory_markers):
        return True

    # Tiny fragments after wake, e.g. "here i will", should not drag in memory.
    if len(words) < 4:
        return False

    return True


_MEM_HOP_STOP = {
    "about", "would", "could", "should", "there", "their", "these", "those",
    "which", "where", "what", "your", "yours", "really", "thing", "things",
    "stuff", "something", "anything", "everything", "currently", "actually",
    "prefers", "prefer", "wants", "user", "uses", "using", "works", "working",
}


def _memory_seed_terms(text: str, k: int = 5) -> list:
    """Pull the salient content terms from a memory hit so a second recall hop
    can deepen toward the topic the first hit revealed (multi-hop: find X →
    fetch what X is connected to). Keeps distinct words ≥5 chars (plus Ξ/χ/φ),
    drops generic stopwords. Order-preserving, capped at k."""
    out: list = []
    seen: set = set()
    for w in re.findall(r"[A-Za-zΞχφ][\wΞχφ–-]{4,}", str(text or "")):
        lw = w.lower()
        if lw in _MEM_HOP_STOP or lw in seen:
            continue
        seen.add(lw)
        out.append(w)
        if len(out) >= k:
            break
    return out


class BusMemoryAgent(_BaseAgent):
    """
    Retrieves semantic memories, conversation history, session summaries,
    and stored user facts — all from local SQLite.
    """
    name = "memory"
    timeout_s = 5.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        try:
            from eli.memory import get_memory
            mem = get_memory()

            action = str((intent or {}).get("action") or "CHAT").upper().strip()
            if not _eli_memory_should_run(user_input, action):
                elapsed = (time.perf_counter() - t0) * 1000
                log.debug(f"[AGENT:memory] skipped action={action} short_or_irrelevant elapsed={elapsed:.0f}ms")
                return AgentResult(
                    agent=self.name,
                    ok=True,
                    confidence=0.0,
                    data={
                        "skipped": True,
                        "memory_context": "",
                        "results": [],
                        "conv_hits": [],
                        "hit_count": 0,
                    },
                    elapsed_ms=elapsed,
                )

            from eli.core.cognition_tunables import snapshot as _cog_snapshot
            _tn = _cog_snapshot()  # user-tunable gather limits (GUI: Settings → Cognition)
            limit = _tn["cog.mem_semantic_recall"]  # semantic hits
            raw_hits = mem.recall_memory(user_input, limit=limit)
            conv_hits = []
            try:
                conv_hits = mem.search_conversations(user_input, user_id=user_id, limit=_tn["cog.mem_conv_recall"])
            except Exception:
                pass
            recent = mem.get_recent_conversation(limit=_tn["cog.mem_recent_turns"], user_id=user_id)  # full history, char-budgeted below
            summaries = []
            try:
                summaries = mem.get_session_summaries(user_id=user_id, limit=_tn["cog.mem_summaries_recall"])
            except Exception:
                pass

            # Multi-hop deepen (#2): when hop-1 recall is THIN, take the strongest
            # hit's salient terms and re-query — surfaces facts connected to the
            # first result that the bare user query missed. Gated on a thin first
            # hop so rich queries don't pay the extra recall cost.
            if 0 < len(raw_hits) < 5:
                try:
                    _seed = (raw_hits[0].get("text") or raw_hits[0].get("content") or "")
                    _seed_terms = _memory_seed_terms(_seed, k=5)
                    if _seed_terms:
                        _seen_ids = {h.get("id") for h in raw_hits if h.get("id")}
                        _seen_txt = {(h.get("text") or h.get("content") or "")[:80] for h in raw_hits}
                        _hop2 = mem.recall_memory(" ".join(_seed_terms), limit=_tn["cog.mem_hop2_recall"]) or []
                        _added = 0
                        for _h in _hop2:
                            _hid = _h.get("id")
                            _ht = (_h.get("text") or _h.get("content") or "")[:80]
                            if (_hid and _hid in _seen_ids) or _ht in _seen_txt:
                                continue
                            raw_hits.append(_h)
                            _seen_ids.add(_hid)
                            _seen_txt.add(_ht)
                            _added += 1
                            if len(raw_hits) >= _tn["cog.mem_merge_cap"]:
                                break
                        if _added:
                            log.debug(f"[AGENT:memory] hop-2 deepen: +{_added} hits from {_seed_terms}")
                except Exception:
                    pass

            total_hits = len(raw_hits) + len(conv_hits)
            local_conf = min(0.9, 0.3 + total_hits * 0.04)

            context_parts: List[str] = []
            if recent:
                # get_recent_conversation returns CHRONOLOGICAL order (oldest first)
                # — confirmed at memory.py: fetches DESC then list(reversed(rows)).
                # Take the newest 20, then drop the trailing user+assistant pair
                # so the model doesn't regurgitate the live prompt or its own last reply.
                turns_to_show = list(recent[-_tn["cog.mem_recent_turns"]:])  # newest N, still chronological
                if turns_to_show and turns_to_show[-1].get("role") == "assistant":
                    turns_to_show = turns_to_show[:-1]  # drop model's last reply
                if turns_to_show and turns_to_show[-1].get("role") == "user":
                    turns_to_show = turns_to_show[:-1]  # drop current live prompt
                display_turns = turns_to_show  # already chronological — no reverse needed
                lines = []
                char_count = 0
                for t in display_turns:
                    try:
                        from eli.runtime.diagnostic_patterns import should_exclude_turn_from_prompt
                        if should_exclude_turn_from_prompt(t.get("role"), t.get("content")):
                            continue
                    except Exception:
                        pass
                    role = "User" if t.get("role") == "user" else "ELI"
                    text = (t.get("content") or "")[:_tn["cog.mem_recent_chars"]]  # trim each turn
                    line = f"{role}: {text}"
                    char_count += len(line)
                    if char_count > 3500:
                        break
                    lines.append(line)
                if lines:
                    context_parts.append(
                        f"Recent conversation ({len(lines)} turns — use this when asked about past topics):\n"
                        + "\n".join(lines)
                    )

            if raw_hits:
                hits_text = []
                for h in raw_hits[:_tn["cog.mem_semantic_shown"]]:
                    txt = (h.get("text") or h.get("content") or "")[:_tn["cog.mem_fact_chars"]]
                    raw_ts = h.get("ts") or h.get("timestamp") or 0
                    try:
                        ts_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(raw_ts))) if raw_ts else ""
                    except Exception:
                        ts_str = str(raw_ts)
                    if txt:
                        hits_text.append(f"  - [{ts_str}] {txt}")
                if hits_text:
                    context_parts.append(
                        f"Relevant stored memories ({len(raw_hits)} found):\n" + "\n".join(hits_text))

            if conv_hits:
                conv_text = []
                for h in conv_hits[:_tn["cog.mem_conv_shown"]]:
                    try:
                        from eli.runtime.diagnostic_patterns import should_exclude_turn_from_prompt
                        if should_exclude_turn_from_prompt(h.get("role"), h.get("content")):
                            continue
                    except Exception:
                        pass
                    txt = (h.get("content") or "")[:_tn["cog.mem_conv_chars"]]
                    role = h.get("role", "?")
                    if txt:
                        conv_text.append(f"  {role}: {txt}")
                if conv_text:
                    context_parts.append(
                        "Related conversation snippets:\n" + "\n".join(conv_text))

            if summaries:
                sum_text = []
                for s in summaries[:_tn["cog.mem_summaries_shown"]]:
                    txt = (s.get("summary") or s.get("content") or "")[:_tn["cog.mem_summary_chars"]]
                    if txt:
                        sum_text.append(f"  - {txt}")
                if sum_text:
                    context_parts.append("Session summaries:\n" + "\n".join(sum_text))

            memory_context = "\n\n".join(context_parts).strip()
            elapsed = (time.perf_counter() - t0) * 1000

            log.debug(f"[AGENT:memory] hits={total_hits} ctx_chars={len(memory_context)} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")

            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=local_conf,
                data={"memory_context": memory_context,
                      "results": raw_hits,
                      "conv_hits": conv_hits,
                      "hit_count": total_hits},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:memory] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class SystemAgent(_BaseAgent):
    """
    Handles all OS-level actions: open apps/files/URLs, volume, screenshot,
    clipboard, keyboard, timers, alarms, shell commands.
    Routes through the existing executor so all allowlist/sandbox rules apply.
    """
    name = "system"
    timeout_s = 8.0

    # Actions this agent handles directly in the parallel phase.
    # CRITICAL: exclude LLM-dependent actions (GENERATE_SCRIPT, DOC_GENERATE, FIX_FILE,
    # DATA_FABRICATOR) — these call GGUF which takes minutes. They must be executed by the
    # CognitiveEngine AFTER the bus returns, not inside the bus's parallel phase.
    # The bus runs with hard timeouts; LLM actions would always time out and double-execute.
    SYSTEM_ACTIONS: Set[str] = {
        # ── App / OS control ──────────────────────────────────────────────────
        "OPEN_APP", "OPEN_URL", "OPEN_FILE_SYSTEM", "OPEN_BROWSER",
        "OPEN_AUDIO_SETTINGS", "OPEN_SYSTEM_SETTINGS", "OPEN_POWER_SETTINGS",
        "OPEN_COMMUNICATION_HUB", "OPEN_MEDIA_HUB", "OPEN_NETWORK_BROWSER",
        "OPEN_IDE", "OPEN_IN_IDE", "CLOSE_APP", "FOCUS_APP",
        # ── Window / workspace management ────────────────────────────────────
        "TILE_WINDOWS", "MINIMISE_ALL", "RESTORE_WINDOWS",
        "MAXIMISE_WINDOW", "NEXT_WINDOW", "PREVIOUS_WINDOW",
        "SWITCH_WORKSPACE",
        # ── Media ─────────────────────────────────────────────────────────────
        "STOP_MEDIA", "PAUSE_MEDIA", "PLAY_MEDIA", "NEXT_MEDIA", "PREVIOUS_MEDIA",
        "MEDIA_CONTROL", "SHUFFLE_MEDIA", "REPEAT_MEDIA",
        # ── Input / output ────────────────────────────────────────────────────
        "VOLUME", "SCREENSHOT", "KEYBOARD", "MOUSE_CONTROL",
        "SET_CLIPBOARD", "GET_CLIPBOARD",
        "SPEAK", "DICTATE", "TRANSCRIBE",
        # ── File / shell ──────────────────────────────────────────────────────
        "RUN_CMD", "SHELL_EXEC", "LIST_DIR", "READ_FILE", "CREATE_FOLDER",
        # ── Scheduling / timers ───────────────────────────────────────────────
        "SET_ALARM", "SET_TIMER",
        "POMODORO_START", "POMODORO_STOP", "POMODORO_STATUS",
        # ── Time / date ───────────────────────────────────────────────────────
        "TIME", "DATE",
        # ── Screen intelligence ───────────────────────────────────────────────
        "SCREEN_LOCATE", "OCR_IMAGE", "SCREEN_READ_ANALYZE",
        # ── Analysis ─────────────────────────────────────────────────────────
        "ANALYZE_PDF", "ANALYZE_CSV",
        # ── Notes ────────────────────────────────────────────────────────────
        "WRITE_NOTE", "NEW_NOTE", "LIST_NOTES", "SEARCH_NOTES",
        # ── System stats ─────────────────────────────────────────────────────
        "GPU_STATUS", "CPU_USAGE", "RAM_USAGE", "SYSTEM_STATS", "HARDWARE_PROFILE",
        # ── Network / web ─────────────────────────────────────────────────────
        "WEB_SEARCH", "GET_WEATHER", "NEWS_FETCH", "MORNING_REPORT",
        # ── Smart home ───────────────────────────────────────────────────────
        "SMART_HOME",
        # ── Plugin management ─────────────────────────────────────────────────
        "PLUGIN_LIST", "PLUGIN_ENABLE", "PLUGIN_DISABLE",
        "PLUGIN_INSTALL", "PLUGIN_UNINSTALL", "PLUGIN_SEARCH", "PLUGIN_STATUS",
        # ── Proactive daemon ──────────────────────────────────────────────────
        "PROACTIVE_START", "PROACTIVE_STOP", "PROACTIVE_STATUS",
        # ── Runtime / cognition status (grounded, no LLM) ─────────────────────
        "RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS",
        "USER_IDENTITY_SUMMARY", "SELF_REPORT", "EXPLAIN_LAST_RESPONSE",
        "SELF_IMPROVEMENT_LOG",
        "MEMORY_STORE", "MEMORY_RECALL", "MEMORY_STATS",
        "PERSONAL_MEMORY_SUMMARY", "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "RUNTIME_AUDIT", "IMPORT_AUDIT", "RESOLVE_RUNTIME_PATHS", "GUI_RUNTIME_AUDIT",
        "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME", "EXPLAIN_ALL_REASONING_MODES",
        "NAME_SOURCE_AUDIT", "ROUTING_FAULT_EXPLAIN", "FRONTIER_STATUS", "ELI_IDENTITY_AUDIT",
        "LIST_CAPABILITIES", "AWARENESS_STATUS", "CODE_CHANGES", "SELF_TEST",
        "PERSONA_LOCK_SET", "PERSONA_LOCK_STATUS", "PERSONA_LOCK_CLEAR",
        "CHECK_CHRONAL_ALIGNMENT",
        # ── Self-awareness / self-improvement (read-only or DB-only, no GGUF) ─
        "SELF_ANALYZE", "SELF_IMPROVE", "SELF_PATCH",
        "HABIT_STATUS",
        # ── Sequencing ───────────────────────────────────────────────────────
        "SEQUENCE",
    }

    # LLM-heavy actions: executed by CognitiveEngine after bus returns, never dispatched
    # inside the parallel phase (avoids timeout + double-execution).
    # SUMMARIZE_FILE uses GGUF. CONVERT_DOCUMENT may use GGUF. All GENERATE_* / FIX_FILE
    # / DATA_FABRICATOR / SHOW_DIFF are multi-second GGUF calls.
    LLM_ACTIONS: Set[str] = {
        "GENERATE_SCRIPT", "GENERATE_PROJECT", "GENERATE_DOCUMENT",
        "DOC_GENERATE", "CREATE_DOCUMENT", "FIX_FILE", "DATA_FABRICATOR",
        "SHOW_DIFF", "SUMMARIZE_FILE", "CONVERT_DOCUMENT", "CHAT",
    }

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        action = (intent.get("action") or "CHAT").upper()
        if action in self.LLM_ACTIONS:
            # Never execute LLM-heavy actions inside the parallel bus phase
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True, "reason": "llm_action_deferred"})
        if action not in self.SYSTEM_ACTIONS:
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True})

        t0 = time.perf_counter()
        try:
            from eli.execution.executor_enhanced import execute
            result = execute(action, intent.get("args") or {})
            log.debug(f"[AGENT:system] execute result: {result}")
            elapsed = (time.perf_counter() - t0) * 1000
            ok = bool(result.get("ok", False))
            local_conf = 0.92 if ok else 0.20
            content = result.get("content") or result.get("response") or ""
            log.debug(f"[AGENT:system] action={action} ok={ok} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=ok, confidence=local_conf,
                data={**result, "action": action, "content": content},
                elapsed_ms=elapsed,
                error=result.get("error") if not ok else None,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:system] ERROR action={action}: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class HabitAgent(_BaseAgent):
    """
    Reads existing automation rules, detects new patterns from event history,
    and proposes new habits. Logs app-launch events for pattern building.
    """
    name = "habit"
    timeout_s = 3.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        low = (user_input or "").lower()
        # Only run when the query is habit-relevant or action is system
        if not any(x in low for x in (
            "habit", "automat", "routine", "schedule", "every", "always",
            "pattern", "open", "spotify", "morning", "daily", "suggest"
        )):
            action = (intent.get("action") or "").upper()
            if action not in ("OPEN_APP",):
                return AgentResult(agent=self.name, ok=True, confidence=0.0,
                                   data={"skipped": True})
        try:
            from eli.memory import get_memory
            mem = get_memory()
            rules = mem.get_habit_rules(enabled_only=False)
            events = mem.get_habit_events(event_type="app_launch", days=14)
            elapsed = (time.perf_counter() - t0) * 1000
            local_conf = 0.70 if rules else 0.30
            log.debug(f"[AGENT:habit] rules={len(rules)} events={len(events)} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=local_conf,
                data={"rules": rules, "event_count": len(events)},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:habit] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class SelfImprovementAgent(_BaseAgent):
    """
    Surfaces recent failures, improvement proposals, and corrections.
    Also logs low-confidence responses back into the failure log so ELI
    can learn from them over time.
    """
    name = "self_improvement"
    timeout_s = 3.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        low = (user_input or "").lower()
        action = (intent.get("action") or "").upper()
        relevant = action in ("SELF_ANALYZE", "SELF_IMPROVE", "SELF_PATCH", "MORNING_REPORT") or any(
            x in low for x in ("improve", "failure", "error", "fix", "suggest", "learn")
        )
        if not relevant:
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True})
        try:
            from eli.runtime.self_improvement import get_self_improvement
            engine = get_self_improvement()
            failures = engine.analyze_failures(limit=10, days=7, min_cluster_size=1)
            proposals = []
            try:
                from eli.memory import get_memory
                proposals = get_memory().get_pending_proposals(limit=5)
            except Exception:
                pass
            elapsed = (time.perf_counter() - t0) * 1000
            local_conf = 0.65 if failures or proposals else 0.25
            log.debug(f"[AGENT:self_improvement] failures={len(failures)} "
                  f"proposals={len(proposals)} conf={local_conf:.2f} "
                  f"elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=local_conf,
                data={"failures": failures, "proposals": proposals},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:self_improvement] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class ProactiveAgent(_BaseAgent):
    """
    Delivers proactive insights, daemon status, and morning report data.
    Reads the proactive artifact files so the LLM can reference them.
    """
    name = "proactive"
    timeout_s = 3.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        action = (intent.get("action") or "").upper()
        low = (user_input or "").lower()
        relevant = action in ("PROACTIVE_STATUS", "PROACTIVE_START", "PROACTIVE_STOP",
                              "MORNING_REPORT") or any(
            x in low for x in ("proactive", "morning report", "insight", "suggestion",
                                "what have you noticed", "background")
        )
        if not relevant:
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True})
        try:
            from eli.core.paths import get_paths
            from pathlib import Path
            import json as _json

            paths = get_paths()
            pro_dir = Path(paths.artifacts_dir) / "proactive"
            insights: List[str] = []
            for fname in ("latest_context.txt", "latest_summary.txt", "latest_action.txt"):
                fp = pro_dir / fname
                if fp.exists():
                    try:
                        txt = fp.read_text(encoding="utf-8", errors="ignore").strip()
                        if txt:
                            insights.append(txt[:300])
                    except Exception:
                        pass

            from eli.execution.executor_enhanced import execute
            status = execute("PROACTIVE_STATUS", {})
            elapsed = (time.perf_counter() - t0) * 1000
            local_conf = 0.70 if insights else 0.35
            log.debug(f"[AGENT:proactive] insights={len(insights)} "
                  f"daemon_running={status.get('running', False)} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=local_conf,
                data={"insights": insights, "status": status},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:proactive] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class FrontierAgent(_BaseAgent):
    """
    Returns one grounded cross-system matrix covering runtime, memory, self,
    proactive, image-engine, world, labs, and chatflow wiring.
    """

    name = "frontier"
    timeout_s = 5.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        action = (intent.get("action") or "").upper()
        low = (user_input or "").lower()

        relevant = action in {"FRONTIER_STATUS", "ELI_IDENTITY_AUDIT"} or any(
            x in low
            for x in (
                "frontier status",
                "full system status",
                "full system audit",
                "cross-system matrix",
                "full project wiring",
                "memory self aware proactive image world labs",
                "eli identity audit",
                "classify eli",
                "classification audit",
            )
        )
        if not relevant:
            return AgentResult(agent=self.name, ok=True, confidence=0.0, data={"skipped": True})

        try:
            if action == "ELI_IDENTITY_AUDIT":
                from eli.runtime.eli_identity_audit import (
                    build_eli_identity_audit,
                    format_eli_identity_audit,
                )

                report = build_eli_identity_audit(user_input)
                content = format_eli_identity_audit(report)
            else:
                from eli.runtime.frontier_status import (
                    build_frontier_status_report,
                    format_frontier_status_report,
                )

                report = build_frontier_status_report(user_input)
                content = format_frontier_status_report(report)
            elapsed = (time.perf_counter() - t0) * 1000
            conf = 0.90 if bool(report.get("ok", False)) else 0.45
            log.debug(
                f"[AGENT:frontier] ok={report.get('ok', False)} "
                f"imports={sum(1 for m in report.get('module_matrix', []) if m.get('import_ok'))}/"
                f"{len(report.get('module_matrix', []))} elapsed={elapsed:.0f}ms"
            )
            return AgentResult(
                agent=self.name,
                ok=bool(report.get("ok", True)),
                confidence=conf,
                data={"report": report, "content": content},
                elapsed_ms=elapsed,
                error=report.get("error"),
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:frontier] ERROR: {e}")
            return AgentResult(
                agent=self.name,
                ok=False,
                confidence=0.0,
                data={},
                elapsed_ms=elapsed,
                error=str(e),
            )


class PluginAgent(_BaseAgent):
    """
    Routes to installed plugins: weather, calendar, web automation,
    document reader, smart home, PDF/CSV analysis.
    Falls through silently if no plugin matches.
    """
    name = "plugin"
    timeout_s = 6.0

    PLUGIN_ACTIONS: Set[str] = {
        "GET_WEATHER", "LIST_EVENTS", "ADD_EVENT",
    }

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        action = (intent.get("action") or "CHAT").upper()
        if action not in self.PLUGIN_ACTIONS:
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True})
        t0 = time.perf_counter()
        try:
            from eli.execution.executor_enhanced import execute
            result = execute(action, intent.get("args") or {})
            log.debug(f"[AGENT:plugin] execute result: {result}")
            elapsed = (time.perf_counter() - t0) * 1000
            ok = bool(result.get("ok", False))
            local_conf = 0.88 if ok else 0.18
            log.debug(f"[AGENT:plugin] action={action} ok={ok} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=ok, confidence=local_conf,
                data={**result, "action": action},
                elapsed_ms=elapsed,
                error=result.get("error") if not ok else None,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:plugin] ERROR action={action}: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class CapabilityAgent(_BaseAgent):
    """
    Grounded capability/status worker. Reads the executor capability surface so
    long-form capability questions can still be answered from real runtime data.
    """
    name = "capability"
    timeout_s = 6.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        action = (intent.get("action") or "").upper()
        low = (user_input or "").lower()
        relevant = action in {"LIST_CAPABILITIES", "AWARENESS_STATUS", "CODE_CHANGES"} or any(
            x in low for x in (
                "capability", "capabilities", "what can you do", "what can you",
                "actions", "awareness", "what changed",
                # broadened (#3): capability QUESTIONS that were being missed.
                "are you able to", "what are you able", "what are you capable",
                "capable of", "do you support", "what do you do", "your features",
                "what features", "everything you can", "list of commands",
                "list your", "what commands",
            )
        )
        if not relevant:
            return AgentResult(agent=self.name, ok=True, confidence=0.0, data={"skipped": True})
        try:
            from eli.execution.executor_enhanced import execute
            exec_action = action if action in {"LIST_CAPABILITIES", "AWARENESS_STATUS", "CODE_CHANGES"} else "LIST_CAPABILITIES"
            result = execute(exec_action, intent.get("args") or {})
            elapsed = (time.perf_counter() - t0) * 1000
            ok = bool(result.get("ok", False))
            local_conf = 0.90 if ok else 0.20
            log.debug(f"[AGENT:capability] action={exec_action} ok={ok} conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=ok, confidence=local_conf,
                data={**result, "action": exec_action, "content": result.get("content") or result.get("response") or ""},
                elapsed_ms=elapsed,
                error=result.get("error") if not ok else None,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:capability] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0, data={}, elapsed_ms=elapsed, error=str(e))


class VoiceAgent(_BaseAgent):
    """
    Answers queries about TTS/STT status and voice preferences.
    Does not produce audio itself — that remains in the GUI/TTS router.
    """
    name = "voice"
    timeout_s = 5.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        low = (user_input or "").lower()
        if not any(x in low for x in ("voice", "speak", "tts", "speech", "mic",
                                       "listen", "stt", "hear", "whisper", "piper",
                                       # broadened (#3): voice/audio status Qs.
                                       "microphone", "wake word", "voice mode",
                                       "are you listening", "talk to you")):
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True})
        t0 = time.perf_counter()
        try:
            import os
            engine = os.environ.get("ELI_TTS_ENGINE", "espeak").strip().lower()
            model  = os.environ.get("ELI_PIPER_MODEL", "").strip()
            mute   = os.environ.get("ELI_MUTE", "0") == "1"
            stt_avail = False
            try:
                import faster_whisper  # noqa: F401
                stt_avail = True
            except ImportError:
                pass
            elapsed = (time.perf_counter() - t0) * 1000
            info = {
                "tts_engine": engine,
                "piper_model": model or "(not configured)",
                "muted": mute,
                "stt_available": stt_avail,
                "content": (
                    f"TTS: {engine}"
                    + (f" model={model}" if model else "")
                    + (" [muted]" if mute else "")
                    + (", STT: faster-whisper available" if stt_avail
                       else ", STT: faster-whisper not installed")
                )
            }
            log.debug(f"[AGENT:voice] engine={engine} stt={stt_avail} "
                  f"elapsed={elapsed:.0f}ms")
            return AgentResult(agent=self.name, ok=True, confidence=0.65,
                               data=info, elapsed_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


# ---------------------------------------------------------------------------
# Confidence aggregator
# ---------------------------------------------------------------------------

def _aggregate_confidence(
    intent_conf: float,
    results: List[AgentResult],
    intent_action: str,
) -> Tuple[float, float]:
    """Evidence-driven aggregation. No hardcoded per-agent weights.

    Returns (aggregated_confidence, grounding_confidence):
      - aggregated_confidence: route-certainty + agent evidence, blended
      - grounding_confidence:  pure agent-evidence score (route-independent)

    Per-agent contribution = evidence_quality × density × calibration
    where:
      - evidence_quality is the agent's self-reported confidence, optionally
        blended (geometric mean) with evidence_arbitration._score_tool_result
        for results that look tool-typed.
      - density is a continuous payload measure across known evidence keys
        (see _evidence_density), smooth and asymptotic to 1.
      - calibration is a rolling per-(agent, action) multiplier learned from
        the agent_metrics table (starts neutral at 1.0).

    Single-agent contributions are capped at _SINGLE_AGENT_CAP so no one
    agent can dominate. Empty-bus dispatches are capped at _EMPTY_BUS_CEILING.
    """
    base = _ROUTE_BASE_WEIGHT * float(intent_conf or 0.0)
    score = base
    grounding = 0.0
    grounded_signal = 0.0
    contributors = 0

    calibration_rows = _load_agent_metrics_cached()

    for r in results:
        if not r.ok or (r.data or {}).get("skipped"):
            continue
        if r.agent == "orchestrator":
            # Planner role: produces a plan, not evidence. Excluded from
            # contribution count and weight (was implicitly 0 before).
            continue
        if not r.has_evidence:
            continue

        self_conf = max(0.0, min(1.0, float(r.confidence or 0.0)))
        if self_conf <= 0.0:
            continue

        density = _evidence_density(r.data or {})
        if density <= 0.0:
            continue

        cal = _calibration_factor(r.agent, intent_action, calibration_rows)

        stage_score = _stage_score_for_result(r)
        if stage_score is not None and stage_score > 0.0:
            evidence_quality = (self_conf * stage_score) ** 0.5
        else:
            evidence_quality = self_conf

        contribution = evidence_quality * density * cal
        contribution = max(0.0, min(_SINGLE_AGENT_CAP, contribution))
        if contribution <= 0.0:
            continue

        score += contribution
        grounding += contribution
        grounded_signal += contribution * 0.5
        contributors += 1

    # Cross-agent corroboration bonus: scales with total signal so three
    # agents with weak evidence don't beat one with strong evidence.
    if contributors >= 3 and grounded_signal > 0.0:
        bonus = min(0.10, grounded_signal * 0.20)
        score += bonus
        grounding += bonus

    # Empty-bus ceiling: route signal alone cannot reach high confidence.
    if grounded_signal <= 0.0:
        score = min(score, _EMPTY_BUS_CEILING)

    _persist_agent_metrics_for_dispatch(intent_action, results)

    return max(0.02, min(0.98, score)), max(0.0, min(0.98, grounding))


# ---------------------------------------------------------------------------
# Orchestrator agent — decides which capabilities to invoke for a task
# ---------------------------------------------------------------------------

class OrchestratorAgent(_BaseAgent):
    """
    Plans which agents and capabilities are needed to complete a complex task.
    For multi-step tasks (e.g. "prepare a presentation, save it, and open it"),
    it produces a structured plan that the CognitiveEngine uses to chain actions.

    This agent never executes actions itself — it only produces a plan dict
    that describes what should happen, in what order, and with what args.
    The engine executes the plan after the bus returns.
    """
    name = "orchestrator"
    timeout_s = 3.0

    # Tasks that clearly need multiple capabilities
    MULTI_STEP_TRIGGERS = [
        ("presentation", "slides", "powerpoint"),
        ("document", "save", "open"),
        ("script", "save", "open"),
        ("search", "summarize", "note"),
        ("find", "open", "edit"),
    ]

    GROUNDED_SYNTHESIS_ACTIONS = {
        "SELF_REPORT",
        "RUNTIME_STATUS",
        "GPU_STATUS",
        "REASONING_MODE_STATUS",
        "USER_IDENTITY_SUMMARY",
        "EXPLAIN_LAST_RESPONSE",
        "EXPLAIN_MEMORY_RUNTIME",
        "EXPLAIN_COGNITION_RUNTIME",
        "RUNTIME_AUDIT",
        "IMPORT_AUDIT",
        "GUI_RUNTIME_AUDIT",
        "RESOLVE_RUNTIME_PATHS",
        "MEMORY_STATUS",
        "COGNITION_STATUS",
        "MEMORY_RECALL",
        "PERSONAL_MEMORY_SUMMARY",
        "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "ROUTING_FAULT_EXPLAIN",
        "NAME_SOURCE_AUDIT",
        "SELF_ANALYZE",
        "SELF_IMPROVE",
        "SELF_IMPROVEMENT_LOG",
        "SELF_UPDATE",
        "META_DIAGNOSTIC",
        "IMAGE_STATUS",
        "FRONTIER_STATUS",
        "ELI_IDENTITY_AUDIT",
    }

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        try:
            action = (intent.get("action") or "CHAT").upper()
            low = (user_input or "").lower()

            # Only plan for complex multi-step tasks
            needs_planning = action == "CHAT" and any(
                sum(1 for kw in group if kw in low) >= 2
                for group in self.MULTI_STEP_TRIGGERS
            )

            # Also plan for known multi-step action types
            if action in ("GENERATE_SCRIPT", "GENERATE_DOCUMENT", "DOC_GENERATE", "DATA_FABRICATOR"):
                needs_planning = True

            if action in self.GROUNDED_SYNTHESIS_ACTIONS:
                needs_planning = True

            expressive = any(x in low for x in (
                "how are you", "how is the head", "head today", "personality back",
                "original personality", "come back to life", "are you back", "you alive",
            ))
            introspection = any(x in low for x in (
                "memory", "runtime", "cognition", "what patterns have you detected",
                "how i use you", "config", "gpu layers", "temperature", "context",
                "threads", "max tokens", "daemons",
            ))
            if expressive and introspection:
                needs_planning = True

            if not needs_planning:
                return AgentResult(agent=self.name, ok=True, confidence=0.0,
                                   data={"skipped": True})

            elapsed = (time.perf_counter() - t0) * 1000
            plan: Dict[str, Any] = {}

            if action == "GENERATE_SCRIPT":
                plan = {
                    "type": "generate_and_open",
                    "primary_action": "GENERATE_SCRIPT",
                    "post_actions": [{"action": "OPEN_IN_IDE", "args": {"path": ""}}],
                    "description": "Generate Python script, save to artifacts/scripts/, open in IDE",
                }
            elif action in ("GENERATE_DOCUMENT", "DOC_GENERATE", "DATA_FABRICATOR"):
                plan = {
                    "type": "generate_and_open",
                    "primary_action": action,
                    "post_actions": [{"action": "OPEN_IN_IDE", "args": {"path": ""}}],
                    "description": "Generate document, save, open in editor",
                }
            elif action in self.GROUNDED_SYNTHESIS_ACTIONS:
                plan = {
                    "type": "grounded_evidence_synthesis",
                    "primary_action": action,
                    "requires_stage_1": True,
                    "requires_stage_11": True,
                    "requires_stage_12": True,
                    "may_skip_middle_stages": True,
                    "subtasks": [
                        "ingest user request and runtime mode",
                        "route and gather authoritative local evidence",
                        "assemble evidence into working context",
                        "synthesize one persona-bound final answer",
                        "store response, learning signal, and trace metadata",
                    ],
                    "description": "Use deterministic evidence as grounding, then complete persona synthesis and learning instead of returning raw evidence.",
                }
            elif "presentation" in low or "slides" in low:
                plan = {
                    "type": "content_then_document",
                    "primary_action": "CHAT",
                    "suggested_followup": "DOC_GENERATE",
                    "description": "Answer with content outline, offer to generate a document/slides",
                }
            elif "terminal" in low and any(x in low for x in ("run", "execute", "type")):
                plan = {
                    "type": "sequence",
                    "primary_action": "SEQUENCE",
                    "description": "Multi-step terminal command chain",
                }
            elif expressive and introspection:
                plan = {
                    "type": "grounded_chat_synthesis",
                    "primary_action": "CHAT",
                    "requires_single_broker": True,
                    "subtasks": [
                        "state/personality framing",
                        "memory/runtime grounding",
                        "usage-pattern analysis if relevant",
                        "single final synthesized answer",
                    ],
                    "description": "Ground mixed personality/state + memory/runtime prompts through one brokered synthesis step",
                }

            log.debug(f"[AGENT:orchestrator] action={action} plan_type={plan.get('type','none')} "
                  f"elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=0.70 if plan else 0.0,
                data={"plan": plan, "needs_planning": bool(plan)},
                elapsed_ms=elapsed,
            )
        except Exception as _orch_err:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:orchestrator] ERROR: {_orch_err}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(_orch_err))


# ---------------------------------------------------------------------------
# The bus
# ---------------------------------------------------------------------------

class AgentBus:
    """
    Dispatch a request to all relevant specialist agents concurrently, then
    return an aggregated DispatchResult for the CognitiveEngine to consume.

    Usage
    -----
        bus = AgentBus()
        result = bus.dispatch(user_input, intent, session_id, user_id)
        # result.memory_context  → inject into LLM prompt
        # result.action_result   → use directly for non-CHAT intents
        # result.aggregated_confidence → attach to final response
    """

    def __init__(self, max_workers: int = 0):
        # Default to one thread per agent so all agents truly run in parallel.
        # Caller can pass an explicit cap, e.g. AgentBus(max_workers=8) on
        # memory-constrained machines.
        if max_workers > 0:
            _n = max_workers
        else:
            try:
                from eli.runtime.runtime_policy import budget as _eli_budget
                _n = min(len(_ALL_AGENTS), _eli_budget("agent_workers", len(_ALL_AGENTS), floor=4, ceiling=32))
            except Exception:
                _n = len(_ALL_AGENTS)
        self._pool = ThreadPoolExecutor(max_workers=_n,
                                        thread_name_prefix="eli-agent")
        self._lock = threading.Lock()

    def dispatch(
        self,
        user_input: str,
        intent: Dict[str, Any],
        session_id: str = "",
        user_id: str = "",
    ) -> DispatchResult:
        t0 = time.perf_counter()
        action = (intent.get("action") or "CHAT").upper()
        intent_conf = float(intent.get("confidence") or 0.5)

        # ── Tiny-query gate ────────────────────────────────────────────────
        # Short filler inputs ("ok", "yes", "sure", "thanks") routed to CHAT
        # gain nothing from a 14-agent broad fanout: MemoryAgent already self-
        # gates on < 10 words, and the rest skip too. Avoid spawning 14 futures
        # whose only work is to return skipped=True.
        # Gate: CHAT + ≤ 3 tokens + matches filler pattern → minimal set.
        _low_input = (user_input or "").strip().lower()
        _word_count = len(_low_input.split())
        _is_tiny_chat = (
            action == "CHAT"
            and _word_count <= 3
            and bool(re.match(
                r"^(ok|okay|yes|no|yeah|nope|sure|thanks|thank you|got it"
                r"|understood|alright|cool|nice|great|fine|hmm+|hm|mhm"
                r"|yep|nah|right|exactly|agreed|perfect|done)\s*[.!?]*$",
                _low_input,
            ))
        )
        # Grounding-escalation local tier asks for a broad fan-out so agents the
        # quick path skipped (file_code, RAG, knowledge_graph, deep memory) get a
        # chance to ground a low-confidence factual turn.
        _force_broad = False
        try:
            _force_broad = bool((intent.get("meta") or {}).get("_force_broad_agents"))
        except Exception:
            _force_broad = False
        if _force_broad:
            selected_names = None  # None → broad fan-out over all enabled agents
        elif _is_tiny_chat:
            selected_names = {"memory", "orchestrator"}
        else:
            selected_names = _select_agents_for_intent(user_input, action)

        # Resolve the concrete agent set, then route it through the canonical
        # typed ExecutionPlan so selection flows through one plan artifact rather
        # than an ad-hoc set. selected_names is None → broad fan-out (all enabled).
        if selected_names is None:
            _profile_names = [a.name for a in _ALL_AGENTS if getattr(a, "_enabled", True)]
        else:
            # Always give enabled CUSTOM agents a dispatch slot — built-in intent
            # selection never names them, so without this a user-created agent
            # would never run. They self-gate on their own triggers (returning
            # confidence 0.0 on no match), so this can't pollute results.
            _custom_names = {
                a.name for a in _ALL_AGENTS
                if getattr(a, "_custom", False) and getattr(a, "_enabled", True)
            }
            _profile_names = sorted(set(selected_names) | _custom_names)

        execution_plan_dict: Optional[Dict[str, Any]] = None
        plan_names: Set[str] = set(_profile_names)
        try:
            from eli.runtime.pipeline_models import RouteDecision as _RD
            from eli.execution.execution_planner import build_execution_plan as _build_plan
            _plan = _build_plan(
                _RD(user_input=user_input, action=action, confidence=intent_conf),
                agent_profile=_profile_names,
            )
            plan_names = set(_plan.agent_profile)
            execution_plan_dict = _plan.to_dict()
        except Exception as _plan_err:
            log.debug(f"[AGENTBUS] execution_planner unavailable, using raw selection: {_plan_err}")

        # Defence-in-depth: ensure enabled custom agents survive the execution
        # planner (which builds its profile from known/built-in agents and could
        # otherwise drop them). They self-gate, so including them is safe.
        plan_names |= {
            a.name for a in _ALL_AGENTS
            if getattr(a, "_custom", False) and getattr(a, "_enabled", True)
        }
        active_agents = [
            a for a in _ALL_AGENTS
            if getattr(a, "_enabled", True)
            and a.name in plan_names
        ]
        # Execute on the dependency DAG (topological layers, upstream → downstream),
        # falling back to flat parallel dispatch. When no dependency edges apply to
        # the selected set, the DAG collapses to a single layer = identical to the
        # flat fan-out, so this is non-regressive.
        results: List[AgentResult] = self._run_agents(
            active_agents, user_input, intent, session_id, user_id)

        # Assemble memory context: MemoryAgent first, then KnowledgeGraphAgent appended
        memory_context = ""
        for r in results:
            if r.agent == "memory" and r.ok:
                raw_ctx = r.data.get("memory_context", "")
                if raw_ctx:
                    if r.confidence < 0.50:
                        memory_context = ""
                    else:
                        memory_context = raw_ctx
                break
        for r in results:
            if r.agent == "knowledge_graph" and r.ok and not r.data.get("skipped"):
                kg_ctx = r.data.get("memory_context", "")
                if kg_ctx:
                    memory_context = (
                        memory_context + "\n\n" + kg_ctx
                    ).strip() if memory_context else kg_ctx
                break

        # For non-CHAT direct actions, pull the system/plugin result.
        # Failed results are preserved (not just ok=True) so the engine can
        # surface the executor's error message instead of silently retrying.
        action_result: Optional[Dict[str, Any]] = None
        if action in _DIRECT_ACTIONS or action in {"ANALYZE_PDF", "ANALYZE_CSV"}:
            # Prefer ok=True if available, otherwise fall back to first failed.
            ok_result = None
            failed_result = None
            for r in results:
                if r.agent not in ("system", "plugin"):
                    continue
                if r.data.get("skipped"):
                    continue
                if r.ok and ok_result is None:
                    ok_result = dict(r.data)
                elif (not r.ok) and failed_result is None:
                    failed_result = dict(r.data)
            action_result = ok_result if ok_result is not None else failed_result

        agg_conf, grounding_conf = _aggregate_confidence(intent_conf, results, action)
        label = _confidence_label(agg_conf)
        agents_used = [r.agent for r in results
                       if r.ok and not r.data.get("skipped")]
        elapsed = (time.perf_counter() - t0) * 1000

        # Extract orchestrator plan
        orchestrator_plan = None
        for r in results:
            if r.agent == "orchestrator" and r.ok and r.data.get("plan"):
                orchestrator_plan = r.data["plan"]
                break

        log.debug(
            f"[AGENTBUS] action={action} "
            f"profile={sorted(selected_names) if selected_names is not None else 'default'} "
            f"agents_used={agents_used} "
            f"intent_conf={intent_conf:.2f} agg_conf={agg_conf:.2f} "
            f"({label}) plan={orchestrator_plan.get('type') if orchestrator_plan else 'none'} "
            f"elapsed={elapsed:.0f}ms"
        )

        # Persist dispatch summary to agent.sqlite3 (non-blocking daemon thread)
        _persist_dispatch_result(
            action=action,
            agents_used=agents_used,
            confidence=agg_conf,
            elapsed_ms=elapsed,
            ok=bool(agents_used),
            summary=f"intent={action} label={label} agents={','.join(agents_used[:6])}",
        )

        return DispatchResult(
            intent_action=action,
            intent_confidence=intent_conf,
            agent_results=results,
            memory_context=memory_context,
            action_result=action_result,
            aggregated_confidence=agg_conf,
            confidence_label=label,
            grounding_confidence=grounding_conf,
            agents_used=agents_used,
            elapsed_ms=elapsed,
            orchestrator_plan=orchestrator_plan,
            execution_plan=execution_plan_dict,
        )

    # ── Agent execution (DAG-layered, with flat fallback) ───────────────────
    def _run_agents(self, active_agents: List["_BaseAgent"], user_input: str,
                    intent: Dict[str, Any], session_id: str, user_id: str) -> List[AgentResult]:
        use_dag = os.environ.get("ELI_AGENT_DAG", "1").strip().lower() not in ("0", "false", "no", "off")
        if use_dag:
            try:
                return self._run_agents_layered(active_agents, user_input, intent, session_id, user_id)
            except Exception as exc:
                log.debug(f"[AGENTBUS] DAG dispatch failed ({exc}); falling back to flat")
        return self._run_agents_flat(active_agents, user_input, intent, session_id, user_id)

    def _collect_layer(self, layer_agents: List["_BaseAgent"], user_input: str,
                       intent: Dict[str, Any], session_id: str, user_id: str) -> List[AgentResult]:
        """Run one layer in parallel with per-agent hard timeouts; robust to the
        outer as_completed timeout (stragglers recorded as timeouts)."""
        # Some system-agent actions run a FULL local LLM synthesis in the
        # executor (their result IS the answer, e.g. the news briefing). On
        # CPU-offloaded loads that legitimately takes 30-60s+, far beyond the
        # short evidence-agent timeout — and they run essentially alone in their
        # layer (memory etc. skip), so a generous ceiling here can't stall fast
        # agents. Don't drop the answer on the evidence timeout.
        _SLOW_SYNTH_ACTIONS = {"NEWS_FETCH", "MORNING_REPORT", "DAILY_REPORT"}
        _intent_action = str((intent or {}).get("action") or "").upper()

        def _eff_to(a) -> float:
            base = float(getattr(a, "timeout_s", 4.0) or 4.0)
            if getattr(a, "name", "") == "system" and _intent_action in _SLOW_SYNTH_ACTIONS:
                return max(base, 180.0)
            return base

        futures = {
            self._pool.submit(a.run, user_input, intent, session_id, user_id): a
            for a in layer_agents
        }
        max_timeout = max((_eff_to(a) for a in layer_agents), default=5.0)
        results: List[AgentResult] = []
        done: set = set()
        try:
            for future in as_completed(futures, timeout=max_timeout + 1.0):
                agent = futures[future]
                done.add(agent.name)
                try:
                    results.append(future.result(timeout=_eff_to(agent)))
                except FuturesTimeout:
                    log.debug(f"[AGENTBUS] {agent.name} timed out after {agent.timeout_s}s")
                    results.append(AgentResult(agent=agent.name, ok=False, confidence=0.0, data={}, error="timeout"))
                except Exception as e:
                    log.debug(f"[AGENTBUS] {agent.name} raised: {e}")
                    results.append(AgentResult(agent=agent.name, ok=False, confidence=0.0, data={}, error=str(e)))
        except FuturesTimeout:
            pass  # outer wait elapsed; fill stragglers below
        for fut, agent in futures.items():
            if agent.name not in done:
                results.append(AgentResult(agent=agent.name, ok=False, confidence=0.0, data={}, error="timeout"))
        return results

    def _run_agents_layered(self, active_agents: List["_BaseAgent"], user_input: str,
                            intent: Dict[str, Any], session_id: str, user_id: str) -> List[AgentResult]:
        by_name = {a.name: a for a in active_agents}
        layers = _agent_execution_layers(list(by_name.keys()))
        results: List[AgentResult] = []
        upstream: Dict[str, Any] = {}     # completed agent name → its result data
        for layer in layers:
            layer_agents = [by_name[n] for n in layer if n in by_name]
            if not layer_agents:
                continue
            layer_intent = intent
            if upstream and isinstance(intent, dict):
                layer_intent = dict(intent)
                layer_intent["_upstream"] = dict(upstream)
            layer_results = self._collect_layer(layer_agents, user_input, layer_intent, session_id, user_id)
            for r in layer_results:
                results.append(r)
                if r.ok and not (r.data or {}).get("skipped"):
                    upstream[r.agent] = r.data or {}
        return results

    def _run_agents_flat(self, active_agents: List["_BaseAgent"], user_input: str,
                         intent: Dict[str, Any], session_id: str, user_id: str) -> List[AgentResult]:
        """Legacy single-round parallel fan-out (DAG-disabled / fallback path)."""
        return self._collect_layer(active_agents, user_input, intent, session_id, user_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)


# Module-level singleton — shared across the process
_bus: Optional[AgentBus] = None
_bus_lock = threading.Lock()


def get_bus() -> AgentBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = AgentBus()
    return _bus


# === ELI FILECODE PATH GLOBAL GUARD START ===
try:
    Path
except NameError:
    from pathlib import Path as Path
# === ELI FILECODE PATH GLOBAL GUARD END ===

_FILECODE_STOP = {
    "file", "files", "code", "which", "where", "what", "your", "about",
    "does", "the", "this", "that", "function", "functions", "memory",
    "agent", "agents", "have", "with", "from", "into", "show", "tell",
    "explain", "find", "look", "class", "method", "methods", "module",
}


def _filecode_extract_terms(text: str) -> set:
    """Pull file/symbol search terms from a question so the agent can find ANY
    file in the repo, not just the ~14 curated ones. Captures *.py filenames,
    dotted modules (eli.x.y), snake_case/CamelCase identifiers, and quoted
    phrases. Stopwords and <4-char tokens are dropped to limit noise."""
    terms: set = set()
    low = str(text or "")
    for m in re.findall(r"\b([a-zA-Z_][\w/]*\.py)\b", low):
        terms.add(m.lower())
    for m in re.findall(r"\b(eli(?:\.\w+)+)\b", low):
        terms.add(m.lower())
    for m in re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z][a-zA-Z0-9]{3,})\b", text):
        terms.add(m.lower())
    for m in re.findall(r"[\"'`]([^\"'`]{3,40})[\"'`]", low):
        terms.add(m.strip().lower())
    return {t for t in terms if len(t) >= 4 and t not in _FILECODE_STOP}


_ELI_PY_STEMS_CACHE: set | None = None


def _eli_py_stems(eli_root: Path) -> set:
    """Cached set of every eli/**/*.py module stem (lowercased). Lets a bare
    word like 'netguard' be recognised as a real module without grepping noise."""
    global _ELI_PY_STEMS_CACHE
    if _ELI_PY_STEMS_CACHE is None:
        s: set = set()
        try:
            for p in eli_root.rglob("*.py"):
                ps = str(p)
                if "__pycache__" in ps or "/build/" in ps or "/.venv/" in ps:
                    continue
                s.add(p.stem.lower())
        except Exception:
            pass
        _ELI_PY_STEMS_CACHE = s
    return _ELI_PY_STEMS_CACHE


def _filecode_repo_search(eli_root: Path, terms: set, want: int,
                          name_terms: set | None = None) -> tuple:
    """Repo-wide search across every eli/**/*.py. Resolves filenames first (so
    'persona_updater'/'netguard' find their files) then greps `terms`. Bounded:
    skips pycache/build, caps files scanned and snippets. Returns (snippets,
    files_hit). `name_terms` are filename-only matches (real module stems)."""
    if (not terms and not name_terms) or want <= 0:
        return [], 0
    file_terms = {t.split("/")[-1].replace(".py", "") for t in (terms or set())}
    file_terms |= set(name_terms or set())
    file_terms = {t for t in file_terms if len(t) >= 4}

    def _fname_match(p: Path) -> bool:
        st = p.stem.lower()
        return any(ft in st for ft in file_terms) if file_terms else False

    candidates = []
    for p in eli_root.rglob("*.py"):
        ps = str(p)
        if "__pycache__" in ps or "/build/" in ps or "/.venv/" in ps:
            continue
        candidates.append(p)
    # Filename matches first so a named file surfaces even on a huge repo.
    candidates.sort(key=lambda p: (not _fname_match(p), str(p)))

    grep_set = set(terms or set()) | set(name_terms or set())
    out: list = []
    files_hit = 0
    scanned = 0
    for p in candidates:
        if len(out) >= want or scanned >= 400:
            break
        scanned += 1
        try:
            if p.stat().st_size > 600_000:
                continue
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            rel = str(p.relative_to(eli_root.parent))  # 'eli/...'
        except Exception:
            rel = p.name
        fhit = _fname_match(p)
        matched_here = 0
        if fhit:
            out.append(f"{rel}:1: (filename matches the query)")
            matched_here += 1
        for i, line in enumerate(content.splitlines(), 1):
            ll = line.lower()
            if any(t in ll for t in grep_set):
                out.append(f"{rel}:{i}: {line.strip()[:220]}")
                matched_here += 1
                if matched_here >= 5 or len(out) >= want:
                    break
        if matched_here:
            files_hit += 1
    return out[:want], files_hit


class FileCodeAgent(_BaseAgent):
    name = "file_code"
    timeout_s = 4.0

    def run(self, user_input: str, intent: Dict[str, Any], session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        try:
            action = str((intent or {}).get("action", "") or "").upper().strip()
            low = (user_input or "").strip().lower()

            _eli_root_fc = Path(__file__).resolve().parents[1]  # eli/
            _code_terms = _filecode_extract_terms(user_input)
            # Plain words that match a REAL eli module stem (e.g. "netguard",
            # "executor") become filename search terms — without grepping noise.
            _name_words = {
                w for w in re.findall(r"[a-z][a-z0-9_]{4,}", low)
                if w not in _FILECODE_STOP
            }
            # Adjacent words joined with "_" catch multi-word module names like
            # "crisis guard" → crisis_guard.py, "knowledge graph" → knowledge_graph.py.
            _seq = re.findall(r"[a-z][a-z0-9]+", low)
            _bigrams = {f"{_seq[i]}_{_seq[i + 1]}" for i in range(len(_seq) - 1)}
            _named_files = (_name_words | _bigrams) & _eli_py_stems(_eli_root_fc)
            relevant = (
                _query_is_grounded(user_input, action)
                or bool(_code_terms)  # any file/symbol/identifier → search the repo
                or bool(_named_files)  # a bare word that is a real module name
                or any(x in low for x in (
                    "file", "code", "which file", "which files", "where is",
                    "memory", "prompt", "response", "loop", "pipeline",
                    "broker", "orchestrator", "agent", "agents",
                    "router", "executor", "gguf", "inference",
                    "proactive", "daemon", "path", "paths", "db", "database",
                    "table", "tables", "wiring", "runtime", "cognition",
                ))
            )

            if not relevant:
                elapsed = (time.perf_counter() - t0) * 1000
                return AgentResult(
                    agent=self.name,
                    ok=True,
                    confidence=0.0,
                    data={"snippets": [], "files_scanned": 0, "skipped": True},
                    elapsed_ms=elapsed,
                )

            root = Path(__file__).resolve().parents[1]  # eli/ — files_map paths are relative to eli/

            # phaseBW5 fix: canonicalised paths under the live `eli/`
            # layout. Previous values pointed at `brain/...` and
            # `tools/automation/...` paths that no longer exist,
            # so the file_code agent's grep returned 0 results
            # for every memory/cognition query.
            files_map = {
                "agent_bus":         "cognition/agent_bus.py",
                "cognitive_engine": "kernel/engine.py",
                "orchestrator":      "cognition/orchestrator.py",
                "inference_broker":  "cognition/inference_broker.py",
                "gguf_inference":    "cognition/gguf_inference.py",
                "memory":            "memory/memory.py",
                "vector_store":      "memory/vector_store.py",
                "memory_init":       "memory/__init__.py",
                "router":            "execution/router_enhanced.py",
                "executor":          "execution/executor_enhanced.py",
                "gui_mki":           "gui/eli_pro_audio_gui_MKI.py",
                "core_paths":        "core/paths.py",
                "proactive":         "planning/proactive_daemon.py",
                "output_governor":   "cognition/output_governor.py",
            }

            patterns = []

            if "memory" in low or "db" in low or "database" in low or "table" in low:
                patterns.extend([
                    r"resolve_db_paths",
                    r"get_memory_status",
                    r"get_recent_conversation",
                    r"get_recent_turns_since",
                    r"search_conversations",
                    r"recall_memory",
                    r"store_memory",
                    r"add_conversation_turn",
                    r"memory_db",
                    r"user_db",
                    r"agent_db",
                    r"conversation_turns",
                    r"memories",
                    r"recall_log",
                ])

            if any(x in low for x in ("prompt", "response", "loop", "pipeline", "cognition", "reason", "reasoning")):
                patterns.extend([
                    r"def process\(",
                    r"route_intent",
                    r"_parse_intent",
                    r"_retrieve_relevant_memories",
                    r"_build_grounded_evidence_context",
                    r"_stream_chat",
                    r"_stream_model_response",
                    r"_run_chat_reasoning_loop",
                    r"_finalize_chat_result",
                    r"reasoning_mode",
                ])

            if any(x in low for x in ("broker", "gguf", "inference", "model", "stream")):
                patterns.extend([
                    r"inference_broker",
                    r"load_model",
                    r"generate",
                    r"chat_completion",
                    r"stream",
                    r"max_tokens",
                    r"temperature",
                    r"n_ctx",
                    r"n_gpu_layers",
                ])

            if any(x in low for x in ("route", "router", "executor", "action", "capability")):
                patterns.extend([
                    r"def route\(",
                    r"matched_by",
                    r"task_family",
                    r"need_grounding",
                    r"required_capabilities",
                    r"def execute\(",
                    r"EXPLAIN_MEMORY_RUNTIME",
                    r"EXPLAIN_COGNITION_RUNTIME",
                    r"RUNTIME_STATUS",
                    r"MEMORY_STATUS",
                    r"COGNITION_STATUS",
                ])

            if any(x in low for x in ("agent", "agents", "orchestrator", "plan", "file_code")):
                patterns.extend([
                    r"class .*Agent",
                    r"orchestrator_plan",
                    r"agents_used",
                    r"aggregated_confidence",
                    r"DispatchResult",
                    r"AgentResult",
                    r"file_code",
                    r"reflection",
                    r"memory_context",
                ])

            if any(x in low for x in ("proactive", "daemon", "background")):
                patterns.extend([
                    r"start_daemon",
                    r"ELI_PROACTIVE",
                    r"ELI_PROACTIVE_STARTED",
                    r"proactive_daemon",
                    r"_start_proactive_listener",
                    r"_start_reflection_loop",
                    r"_start_habit_loop",
                ])

            if any(x in low for x in ("path", "paths", "folder", "folders", "dir", "directories")):
                patterns.extend([
                    r"get_paths",
                    r"project_root",
                    r"artifacts_dir",
                    r"conversations_dir",
                    r"config_dir",
                    r"models_dir",
                    r"user_db",
                    r"agent_db",
                    r"memory_db",
                ])

            if not patterns:
                patterns = [
                    r"def process\(",
                    r"route_intent",
                    r"get_memory",
                    r"recall_memory",
                    r"store_memory",
                    r"add_conversation_turn",
                    r"get_recent_conversation",
                    r"orchestrator_plan",
                    r"agents_used",
                    r"load_model",
                    r"generate",
                    r"start_daemon",
                ]

            rels = []
            if any(x in low for x in ("memory", "db", "database", "table", "conversation")):
                rels.extend([
                    files_map["memory"],
                    files_map["memory_init"],
                    files_map["cognitive_engine"],
                    files_map["agent_bus"],
                    files_map["proactive"],
                ])
            if any(x in low for x in ("prompt", "response", "loop", "pipeline", "cognition")):
                rels.extend([
                    files_map["cognitive_engine"],
                    files_map["router"],
                    files_map["executor"],
                    files_map["agent_bus"],
                    files_map["inference_broker"],
                    files_map["gguf_inference"],
                ])
            if any(x in low for x in ("broker", "gguf", "inference", "model", "stream")):
                rels.extend([
                    files_map["inference_broker"],
                    files_map["gguf_inference"],
                    files_map["cognitive_engine"],
                ])
            if any(x in low for x in ("route", "router", "executor", "action", "capability")):
                rels.extend([
                    files_map["router"],
                    files_map["executor"],
                    files_map["cognitive_engine"],
                ])
            if any(x in low for x in ("agent", "agents", "orchestrator", "plan", "file_code")):
                rels.extend([
                    files_map["agent_bus"],
                    files_map["cognitive_engine"],
                    files_map["orchestrator"],
                    files_map["gui_mki"],
                    files_map["vector_store"],
                ])
            if any(x in low for x in ("proactive", "daemon", "background")):
                rels.extend([
                    files_map["proactive"],
                    files_map["cognitive_engine"],
                    files_map["agent_bus"],
                ])
            if any(x in low for x in ("path", "paths", "folder", "folders", "dir", "directories")):
                rels.extend([
                    files_map["executor"],
                    files_map["memory_init"],
                    files_map["memory"],
                    files_map["cognitive_engine"],
                ])

            if not rels:
                rels = list(files_map.values())

            seen = set()
            ordered_rels = []
            for rel in rels:
                if rel not in seen:
                    seen.add(rel)
                    ordered_rels.append(rel)

            snippets = []
            files_scanned = 0

            # Repo-FIRST for specific file/symbol queries: a named file/symbol is
            # more relevant than the curated map's generic matches (which would
            # otherwise greedily fill the budget and bury the real target). Seed
            # up to 14 so the curated architecture context can still top up.
            if _code_terms or _named_files:
                try:
                    _seed, _seed_files = _filecode_repo_search(
                        root, _code_terms, 14, name_terms=_named_files
                    )
                    snippets.extend(_seed)
                    files_scanned += _seed_files
                except Exception as _rs_err:
                    log.debug(f"[AGENT:file_code] repo search failed: {_rs_err}")

            for rel in ordered_rels[:20]:
                path = root / rel
                if not path.exists():
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                lines = content.splitlines()
                matched_here = 0
                for i, line in enumerate(lines, 1):
                    for pat in patterns:
                        try:
                            if re.search(pat, line, flags=re.I):
                                snippets.append(f"{rel}:{i}: {line.strip()[:220]}")
                                matched_here += 1
                                break
                        except re.error:
                            continue
                    if matched_here >= 6 or len(snippets) >= 20:
                        break

                files_scanned += 1
                if len(snippets) >= 20:
                    break

            # De-dup (repo seed + curated map can overlap) while preserving order.
            if snippets:
                _seen_s: set = set()
                _dedup: list = []
                for _s in snippets:
                    if _s not in _seen_s:
                        _seen_s.add(_s)
                        _dedup.append(_s)
                snippets = _dedup[:20]

            local_conf = 0.78 if snippets else 0.20
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:file_code] snippets={len(snippets)} files_scanned={files_scanned} conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=local_conf,
                data={"snippets": snippets[:20], "files_scanned": files_scanned},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:file_code] ERROR: {e}")
            return AgentResult(
                agent=self.name,
                ok=False,
                confidence=0.0,
                data={},
                elapsed_ms=elapsed,
                error=str(e),
            )


class IntrospectionBusAgent(_BaseAgent):
    """
    Wraps IntrospectionAgent for the AgentBus protocol.
    Triggered by architecture / pipeline / runtime questions.
    Provides grounded pipeline description and memory stats.
    """
    name = "introspection"
    timeout_s = 4.0

    def run(self, user_input: str, intent: Dict[str, Any], session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        low = (user_input or "").lower()
        action = (intent.get("action") or "").upper()

        relevant = action in {"EXPLAIN_COGNITION_RUNTIME", "EXPLAIN_MEMORY_RUNTIME",
                              "RUNTIME_STATUS", "COGNITION_STATUS", "SELF_REPORT"} or any(
            x in low for x in (
                "how many agents", "agent bus", "agent roster", "what agents", "which agents",
                "how many stages", "pipeline stages", "prompt to response", "prompt->response",
                "cognitive pipeline", "cognition pipeline", "how do you work",
                "how does your cognition", "what is your pipeline", "introspect",
                "runtime audit", "pipeline description",
            )
        )
        if not relevant:
            elapsed = (time.perf_counter() - t0) * 1000
            return AgentResult(agent=self.name, ok=True, confidence=0.0,
                               data={"skipped": True}, elapsed_ms=elapsed)

        try:
            from eli.cognition.introspection_agent import IntrospectionAgent
            ia = IntrospectionAgent()
            pipeline = ia.get_pipeline()
            memory_stats = ia.get_memory_stats()
            runtime = ia.get_runtime()
            content = f"Pipeline:\n{pipeline}\n\nMemory stats:\n{memory_stats}\n\nRuntime:\n{runtime}"
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:introspection] content_chars={len(content)} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=0.90,
                data={"content": content, "snippets": [content[:800]]},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:introspection] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


class ReflectionAgent(_BaseAgent):
    name = "reflection"
    timeout_s = 4.0

    def run(self, user_input: str, intent: Dict[str, Any], session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        try:
            action = str((intent or {}).get("action", "") or "").upper().strip()
            low = (user_input or "").strip().lower()

            relevant = (
                _query_is_grounded(user_input, action)
                or any(x in low for x in (
                    "reflection", "reflect", "pattern", "patterns",
                    "noticed", "what have you noticed", "how i use you",
                    "usage", "insight", "insights",
                ))
            )

            if not relevant:
                elapsed = (time.perf_counter() - t0) * 1000
                return AgentResult(
                    agent=self.name,
                    ok=True,
                    confidence=0.0,
                    data={"insights": [], "skipped": True},
                    elapsed_ms=elapsed,
                )

            from eli.memory import get_memory
            mem = get_memory()

            insights = []

            try:
                obs = list(mem.get_recent_observations(limit=8) or [])
            except Exception:
                obs = []

            try:
                sums = list(mem.get_session_summaries(user_id=user_id, limit=3) or [])
            except Exception:
                sums = []

            for row in obs[:8]:
                text = str(
                    row.get("observation")
                    or row.get("content")
                    or row.get("details")
                    or ""
                ).strip()
                if text:
                    insights.append(text[:220])

            for row in sums[:3]:
                text = str(row.get("summary") or row.get("content") or "").strip()
                if text:
                    insights.append(text[:220])

            local_conf = 0.68 if insights else 0.20
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:reflection] insights={len(insights)} conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=local_conf,
                data={"insights": insights[:12]},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[AGENT:reflection] ERROR: {e}")
            return AgentResult(
                agent=self.name,
                ok=False,
                confidence=0.0,
                data={},
                elapsed_ms=elapsed,
                error=str(e),
            )


class KnowledgeGraphAgent(_BaseAgent):
    """
    Queries the SQLite knowledge graph (user.sqlite3 kg_entities/kg_relations)
    for structured entity-relation context relevant to the current user input.

    Triggered by any non-trivial query — always runs, skips fast if no KG hits.
    Returns a compact context block of entities, predicates, and multi-hop neighbours.
    """
    name = "knowledge_graph"
    timeout_s = 3.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        try:
            from eli.memory.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()

            stats = kg.stats()
            if stats["entities"] == 0:
                # Empty graph — nothing to contribute yet
                return AgentResult(agent=self.name, ok=True, confidence=0.0,
                                   data={"skipped": True})

            # DAG upstream: seed the KG lookup with what the memory agent surfaced
            # this turn (memory → knowledge_graph edge). Guarded: no upstream ⇒
            # identical to the legacy user_input-only query.
            _query = user_input
            try:
                _up = (intent or {}).get("_upstream") or {}
                _mem = _up.get("memory") or {}
                _hits = (_mem.get("results") or _mem.get("conv_hits") or [])
                _terms = []
                for _h in _hits[:3]:
                    if isinstance(_h, dict):
                        _t = (_h.get("text") or _h.get("content") or "").strip()
                        if _t:
                            _terms.append(_t[:80])
                if _terms:
                    _query = (user_input + " " + " ".join(_terms))[:600]
            except Exception:
                _query = user_input

            from eli.core.cognition_tunables import get_tunable as _cog_get
            ctx = kg.context_for_prompt(_query, max_chars=_cog_get("cog.kg_max_chars"))
            elapsed = (time.perf_counter() - t0) * 1000

            if not ctx:
                return AgentResult(agent=self.name, ok=True, confidence=0.0,
                                   data={"skipped": True}, elapsed_ms=elapsed)

            confidence = min(0.85, 0.4 + stats["relations"] * 0.02)
            kg_block = f"Knowledge graph context:\n{ctx}"
            log.debug(f"[AGENT:knowledge_graph] {stats['entities']} entities, "
                  f"{stats['relations']} relations, ctx_chars={len(ctx)} "
                  f"elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=confidence,
                data={"memory_context": kg_block, "kg_stats": stats},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AgentResult(agent=self.name, ok=False, confidence=0.0,
                               data={}, elapsed_ms=elapsed, error=str(e))


# All agent classes are defined above. _ALL_AGENTS is placed here so that
# FileCodeAgent and ReflectionAgent exist when the list is evaluated.
_ALL_AGENTS: List[_BaseAgent] = [
    BusMemoryAgent(),
    SystemAgent(),
    HabitAgent(),
    SelfImprovementAgent(),
    ProactiveAgent(),
    FrontierAgent(),
    PluginAgent(),
    CapabilityAgent(),
    VoiceAgent(),
    OrchestratorAgent(),
    FileCodeAgent(),
    ReflectionAgent(),
    IntrospectionBusAgent(),
    KnowledgeGraphAgent(),
]

def _apply_runtime_policy_timeouts() -> None:
    """Adapt every agent's timeout_s to the active hardware/runtime policy.

    Called once for the built-in agents and again after custom agents load, so
    user-supplied agents also get hardware-adapted timeouts (previously they
    kept whatever they hardcoded because this ran before _load_custom_agents()).
    """
    try:
        from eli.runtime.runtime_policy import timeout as _eli_agent_timeout
        for _eli_agent in _ALL_AGENTS:
            _eli_agent.timeout_s = _eli_agent_timeout(
                f"agent_{getattr(_eli_agent, 'name', 'unknown')}",
                float(getattr(_eli_agent, "timeout_s", 4.0) or 4.0),
            )
    except Exception:
        pass


_apply_runtime_policy_timeouts()

# Action families that skip the LLM entirely — the system agent handles them
_DIRECT_ACTIONS: Set[str] = SystemAgent.SYSTEM_ACTIONS | PluginAgent.PLUGIN_ACTIONS


# ── Auto-load custom agents ───────────────────────────────────────────────────
# The wizard (GUI) writes agent files to eli/brain/agents/custom/.
# Older or hand-rolled agents may sit at eli/cognition/custom/.
# Either location is loaded at import time so register_agent() inside the
# module attaches the new class to _ALL_AGENTS.
def _get_trusted_agents_registry() -> dict:
    """Load the trusted-agents hash registry from config/trusted_agents.json.

    Returns a dict mapping filename → sha256_hex for all pre-approved agents.
    The file is created on first trust grant; missing file means no trusted agents.
    """
    import json as _json_ta
    from eli.core.paths import get_paths as _get_paths_ta
    try:
        registry_path = _get_paths_ta().config_dir / "trusted_agents.json"
        if registry_path.exists():
            return _json_ta.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _trust_custom_agent(py_file: Path) -> None:
    """Register a custom agent file as trusted by recording its SHA-256 hash.

    Call this once per file to add it to the trust registry so it can be
    loaded in future sessions.  Use `eli --trust-agent <path>` from the CLI.
    """
    import hashlib as _hl_ta, json as _json_ta
    from eli.core.paths import get_paths as _get_paths_ta
    sha = _hl_ta.sha256(py_file.read_bytes()).hexdigest()
    registry_path = _get_paths_ta().config_dir / "trusted_agents.json"
    try:
        existing: dict = {}
        if registry_path.exists():
            existing = _json_ta.loads(registry_path.read_text(encoding="utf-8"))
        existing[py_file.name] = sha
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(_json_ta.dumps(existing, indent=2), encoding="utf-8")
        log.debug(f"[AGENTBUS] Trusted agent registered: {py_file.name} ({sha[:12]}…)")
    except Exception as _e:
        log.debug(f"[AGENTBUS] Failed to register agent trust for {py_file.name}: {_e}")


def _load_custom_agents() -> None:
    import importlib.util as _ilu, hashlib as _hl
    project_root = Path(__file__).resolve().parents[1]
    candidate_dirs = [
        Path(__file__).resolve().parent / "custom",
        project_root / "brain" / "agents" / "custom",
    ]
    extra = (
        os.environ.get("ELI_CUSTOM_AGENTS_DIR", "") or ""
    ).strip()
    if extra:
        candidate_dirs.append(Path(extra).expanduser().resolve())

    trusted = _get_trusted_agents_registry()
    # Bypass trust check in dev/test mode
    trust_bypass = os.environ.get("ELI_TRUST_ALL_AGENTS", "").strip().lower() in ("1", "true", "yes")

    seen = set()
    for custom_dir in candidate_dirs:
        try:
            if not custom_dir.is_dir():
                continue
            for py_file in sorted(custom_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                if py_file.name in seen:
                    continue
                seen.add(py_file.name)

                # ── Trust verification ──────────────────────────────────────
                if not trust_bypass:
                    file_hash = _hl.sha256(py_file.read_bytes()).hexdigest()
                    trusted_hash = trusted.get(py_file.name)
                    if trusted_hash is None:
                        log.debug(
                            f"[AGENTBUS] SECURITY: Custom agent '{py_file.name}' is not trusted. "
                            f"Run `eli --trust-agent {py_file}` to approve it before loading."
                        )
                        continue
                    if file_hash != trusted_hash:
                        log.debug(
                            f"[AGENTBUS] SECURITY: Custom agent '{py_file.name}' hash mismatch — "
                            f"file may have been modified. Re-run `eli --trust-agent {py_file}` "
                            f"to re-approve after reviewing the changes."
                        )
                        continue
                # ── Load ────────────────────────────────────────────────────
                try:
                    _before_ids = {id(a) for a in _ALL_AGENTS}
                    spec = _ilu.spec_from_file_location(py_file.stem, str(py_file))
                    mod = _ilu.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    # Tag newly-registered agents as custom so dispatch always
                    # includes them (they self-gate on triggers); built-in intent
                    # selection won't name them.
                    for _na in _ALL_AGENTS:
                        if id(_na) not in _before_ids:
                            try:
                                _na._custom = True
                            except Exception:
                                pass
                    log.debug(f"[AGENTBUS] Loaded custom agent: {py_file.name} from {custom_dir}")
                except Exception as _e:
                    log.debug(f"[AGENTBUS] Failed to load custom agent {py_file.name}: {_e}")
        except Exception as _e:
            log.debug(f"[AGENTBUS] Custom agent dir scan failed for {custom_dir}: {_e}")


_load_custom_agents()
# Re-apply so custom agents registered into _ALL_AGENTS also get hardware-adapted timeouts.
_apply_runtime_policy_timeouts()
