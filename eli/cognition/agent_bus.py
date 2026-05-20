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
            from eli.core.paths import get_paths as _gp
            db_path = _gp().artifacts_dir / "agent.sqlite3"
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
        for key in ("snippets", "results", "hits", "items", "content", "entries", "rules", "insights", "memory_context"):
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
    aggregated_confidence: float = 0.0
    confidence_label: str = ""                        # human-readable tier
    agents_used: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    orchestrator_plan: Optional[Dict[str, Any]] = None  # multi-step plan from OrchestratorAgent

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
                snippets = d["snippets"][:8]
                parts.append("Source code evidence (file:line: content):\n" + "\n".join(snippets))
            elif r.agent == "reflection" and d.get("insights"):
                insights = d["insights"][:4]
                lines = [f"  - {i}" for i in insights]
                parts.append("Recent ELI reflections/observations:\n" + "\n".join(lines))
            elif r.agent == "system" and d.get("content"):
                parts.append(f"Runtime/system evidence:\n{str(d['content'])[:800]}")
            elif r.agent == "capability" and d.get("content"):
                parts.append(f"Capability evidence:\n{str(d['content'])[:400]}")
            elif r.agent == "habit" and d.get("rules"):
                rules = d["rules"][:3]
                lines = [f"  - {rule.get('name', '')} @ {rule.get('hour', 0):02d}:{rule.get('minute', 0):02d}"
                         for rule in rules]
                parts.append("Habit automation rules:\n" + "\n".join(lines))
            elif r.agent == "self_improvement" and d.get("failures"):
                fails = d["failures"][:3]
                lines = [f"  - {f.get('user_input', '')[:80]}" for f in fails]
                parts.append("Recent ELI failure log:\n" + "\n".join(lines))
            elif r.agent == "proactive" and d.get("insights"):
                insights = d["insights"][:3]
                lines = [f"  - {i}" for i in insights]
                parts.append("Proactive insights:\n" + "\n".join(lines))
            elif r.agent == "frontier" and d.get("content"):
                parts.append(f"Frontier system matrix:\n{str(d['content'])[:900]}")
            elif r.agent == "plugin" and d.get("content"):
                parts.append(f"Plugin result:\n{str(d['content'])[:400]}")
            elif r.agent == "introspection" and d.get("content"):
                parts.append(f"ELI architecture/pipeline (grounded):\n{str(d['content'])[:700]}")
            elif r.agent == "voice" and d.get("content"):
                parts.append(f"Voice/TTS status:\n{str(d['content'])[:200]}")
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
    low = (user_input or "").strip().lower()
    if action in {
        "RUNTIME_AUDIT", "IMPORT_AUDIT", "RESOLVE_RUNTIME_PATHS", "GUI_RUNTIME_AUDIT",
        "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME", "RUNTIME_STATUS",
        "MEMORY_STATUS", "COGNITION_STATUS", "LIST_CAPABILITIES", "AWARENESS_STATUS",
        "CODE_CHANGES", "FRONTIER_STATUS", "ELI_IDENTITY_AUDIT",
    }:
        return True
    triggers = (
        "who are you", "what are you running", "gpu layers", "context size",
        "batch", "temperature", "what do you know about me", "from memory",
        "memory internals", "how does your memory work", "how does memory work",
        "runtime audit", "import audit", "what changed", "wiring", "line ",
        ".py", "db table", "db tables", "which file", "which files",
        "broker", "orchestrator", "agent bus", "prompt to response", "response loop",
        "pipeline", "folders and paths involved", "full wiring",
        "how many agents", "agent roster", "what agents", "which agents",
        "how many stages", "pipeline stages", "prompt->response", "cognitive pipeline",
        "cognition pipeline", "how do you work", "how does your cognition",
        "frontier status", "full system audit", "full system wiring", "cross-system matrix",
        "eli identity audit", "classify eli", "classification audit",
        "world tab", "labs tab", "image engine", "proactive daemon",
    )
    return any(t in low for t in triggers)


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
    if len(words) < 10:
        return False

    return True


class MemoryAgent(_BaseAgent):
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
                print(f"[AGENT:memory] skipped action={action} short_or_irrelevant elapsed={elapsed:.0f}ms")
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

            limit = 8  # semantic hits
            raw_hits = mem.recall_memory(user_input, limit=limit)
            conv_hits = []
            try:
                conv_hits = mem.search_conversations(user_input, user_id=user_id, limit=5)
            except Exception:
                pass
            recent = mem.get_recent_conversation(limit=6, user_id=user_id)  # full history, char-budgeted below
            summaries = []
            try:
                summaries = mem.get_session_summaries(user_id=user_id, limit=3)
            except Exception:
                pass

            total_hits = len(raw_hits) + len(conv_hits)
            local_conf = min(0.9, 0.3 + total_hits * 0.04)

            context_parts: List[str] = []
            if recent:
                # recent is DESC-sorted (newest first). Take the 20 most recent
                # turns, then strip the trailing user+assistant pair so the model
                # doesn't regurgitate the live prompt or its own last reply.
                turns_to_show = list(recent[:20])  # newest-first slice of 20
                # Drop the most-recent assistant turn (prevent verbatim replay)
                # and the most-recent user turn (it's the current live prompt).
                while turns_to_show and turns_to_show[0].get("role") in ("user", "assistant"):
                    turns_to_show = turns_to_show[1:]
                    if len(turns_to_show) >= 2:
                        break  # strip at most the latest user+assistant pair
                # Reverse to chronological order for display (oldest → newest)
                display_turns = list(reversed(turns_to_show))
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
                    text = (t.get("content") or "")[:120]  # trim each turn
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
                for h in raw_hits[:6]:  # reduced from 12
                    txt = (h.get("text") or h.get("content") or "")[:160]
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
                for h in conv_hits[:4]:
                    try:
                        from eli.runtime.diagnostic_patterns import should_exclude_turn_from_prompt
                        if should_exclude_turn_from_prompt(h.get("role"), h.get("content")):
                            continue
                    except Exception:
                        pass
                    txt = (h.get("content") or "")[:120]
                    role = h.get("role", "?")
                    if txt:
                        conv_text.append(f"  {role}: {txt}")
                if conv_text:
                    context_parts.append(
                        "Related conversation snippets:\n" + "\n".join(conv_text))

            if summaries:
                sum_text = []
                for s in summaries[:2]:
                    txt = (s.get("summary") or s.get("content") or "")[:200]
                    if txt:
                        sum_text.append(f"  - {txt}")
                if sum_text:
                    context_parts.append("Session summaries:\n" + "\n".join(sum_text))

            memory_context = "\n\n".join(context_parts).strip()
            elapsed = (time.perf_counter() - t0) * 1000

            print(f"[AGENT:memory] hits={total_hits} ctx_chars={len(memory_context)} "
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
            print(f"[AGENT:memory] ERROR: {e}")
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
        "OPEN_APP", "OPEN_URL", "OPEN_FILE_SYSTEM", "OPEN_BROWSER",
        "OPEN_AUDIO_SETTINGS", "OPEN_SYSTEM_SETTINGS", "OPEN_POWER_SETTINGS",
        "OPEN_COMMUNICATION_HUB", "OPEN_MEDIA_HUB", "OPEN_NETWORK_BROWSER",
        "OPEN_IDE", "OPEN_IN_IDE",
        "STOP_MEDIA", "PAUSE_MEDIA", "PLAY_MEDIA", "NEXT_MEDIA", "PREVIOUS_MEDIA",
        "MEDIA_CONTROL",
        "VOLUME", "SCREENSHOT", "KEYBOARD",
        "SET_CLIPBOARD", "GET_CLIPBOARD",
        "RUN_CMD", "SHELL_EXEC", "LIST_DIR", "READ_FILE",
        "SET_ALARM", "SET_TIMER",
        "WRITE_NOTE", "CREATE_FOLDER", "CLOSE_APP",
        "TILE_WINDOWS", "MINIMISE_ALL", "RESTORE_WINDOWS",
        "MAXIMISE_WINDOW", "NEXT_WINDOW", "PREVIOUS_WINDOW",
        "SWITCH_WORKSPACE", "FOCUS_APP",
        "SCREEN_LOCATE",
        "TIME", "DATE",
        "ANALYZE_PDF", "ANALYZE_CSV",
        "RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS",
        "USER_IDENTITY_SUMMARY", "SELF_REPORT", "EXPLAIN_LAST_RESPONSE",
        "GPU_STATUS", "SELF_IMPROVEMENT_LOG",
        "MEMORY_STORE", "MEMORY_RECALL", "MEMORY_STATS",
        "PERSONAL_MEMORY_SUMMARY", "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "RUNTIME_AUDIT", "IMPORT_AUDIT", "RESOLVE_RUNTIME_PATHS", "GUI_RUNTIME_AUDIT",
        "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME",
        "NAME_SOURCE_AUDIT", "ROUTING_FAULT_EXPLAIN", "FRONTIER_STATUS", "ELI_IDENTITY_AUDIT",
        "LIST_CAPABILITIES", "AWARENESS_STATUS", "CODE_CHANGES", "SELF_TEST",
        "PERSONA_LOCK_SET", "PERSONA_LOCK_STATUS", "PERSONA_LOCK_CLEAR",
        "CHECK_CHRONAL_ALIGNMENT",
        "SEQUENCE",
    }

    # LLM-heavy actions: executed by CognitiveEngine after bus returns, never dispatched
    # inside the parallel phase (avoids timeout + double-execution).
    LLM_ACTIONS: Set[str] = {
        "GENERATE_SCRIPT", "GENERATE_PROJECT", "GENERATE_DOCUMENT",
        "DOC_GENERATE", "CREATE_DOCUMENT", "FIX_FILE", "DATA_FABRICATOR",
        "SHOW_DIFF", "CHAT",
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
            print(f"[AGENT:system] execute result: {result}")
            elapsed = (time.perf_counter() - t0) * 1000
            ok = bool(result.get("ok", False))
            local_conf = 0.92 if ok else 0.20
            content = result.get("content") or result.get("response") or ""
            print(f"[AGENT:system] action={action} ok={ok} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=ok, confidence=local_conf,
                data={**result, "action": action, "content": content},
                elapsed_ms=elapsed,
                error=result.get("error") if not ok else None,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:system] ERROR action={action}: {e}")
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
            print(f"[AGENT:habit] rules={len(rules)} events={len(events)} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=local_conf,
                data={"rules": rules, "event_count": len(events)},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:habit] ERROR: {e}")
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
            print(f"[AGENT:self_improvement] failures={len(failures)} "
                  f"proposals={len(proposals)} conf={local_conf:.2f} "
                  f"elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=local_conf,
                data={"failures": failures, "proposals": proposals},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:self_improvement] ERROR: {e}")
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
            print(f"[AGENT:proactive] insights={len(insights)} "
                  f"daemon_running={status.get('running', False)} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=local_conf,
                data={"insights": insights, "status": status},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:proactive] ERROR: {e}")
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
            print(
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
            print(f"[AGENT:frontier] ERROR: {e}")
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
            print(f"[AGENT:plugin] execute result: {result}")
            elapsed = (time.perf_counter() - t0) * 1000
            ok = bool(result.get("ok", False))
            local_conf = 0.88 if ok else 0.18
            print(f"[AGENT:plugin] action={action} ok={ok} "
                  f"conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=ok, confidence=local_conf,
                data={**result, "action": action},
                elapsed_ms=elapsed,
                error=result.get("error") if not ok else None,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:plugin] ERROR action={action}: {e}")
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
            x in low for x in ("capability", "capabilities", "what can you do", "actions", "awareness", "what changed")
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
            print(f"[AGENT:capability] action={exec_action} ok={ok} conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=ok, confidence=local_conf,
                data={**result, "action": exec_action, "content": result.get("content") or result.get("response") or ""},
                elapsed_ms=elapsed,
                error=result.get("error") if not ok else None,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:capability] ERROR: {e}")
            return AgentResult(agent=self.name, ok=False, confidence=0.0, data={}, elapsed_ms=elapsed, error=str(e))


class VoiceAgent(_BaseAgent):
    """
    Answers queries about TTS/STT status and voice preferences.
    Does not produce audio itself — that remains in the GUI/TTS router.
    """
    name = "voice"
    timeout_s = 2.0

    def run(self, user_input: str, intent: Dict[str, Any],
            session_id: str, user_id: str) -> AgentResult:
        low = (user_input or "").lower()
        if not any(x in low for x in ("voice", "speak", "tts", "speech", "mic",
                                       "listen", "stt", "hear", "whisper", "piper")):
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
            print(f"[AGENT:voice] engine={engine} stt={stt_avail} "
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
) -> float:
    """Aggregate evidence-confidence across the agent bus.

    Calibration rule: intent_conf alone never produces high agg_conf.
    intent_conf is *route* confidence (regex matched a phrase), not
    *answer* confidence. A 0.99 router match with zero agent evidence
    should not yield 0.98 final — it should yield ~0.55, signalling
    "we know what was asked, but no agents grounded an answer".

    Weights:
      base = 0.30 * intent_conf            (route certainty alone is weak)
      + agent contributions (capped per agent type)
      - empty-bus penalty if NO agent produced grounded data

    Empty-bus penalty: when 0 contributors return signal, the result is
    a near-pure regex match. The aggregated score should reflect that
    we did not actually verify anything.
    """
    base = 0.30 * float(intent_conf or 0.0)
    score = base

    grounded_signal = 0.0  # tracks whether ANY contributor returned grounded data
    contributors = 0

    for r in results:
        if r.data.get("skipped"):
            continue
        if not r.ok:
            continue
        contributors += 1

        if r.agent == "memory":
            mem_hits = int(r.data.get("hit_count", 0) or 0)
            grounded_signal += min(0.25, mem_hits * 0.05)
            score += min(0.25, mem_hits * 0.05)

        elif r.agent == "system":
            content = str(r.data.get("content") or "")
            score += 0.12
            if "/" in content or ".py" in content:
                grounded_signal += 0.10
                score += 0.10

        elif r.agent == "plugin":
            score += 0.12
            grounded_signal += 0.06

        elif r.agent == "habit":
            habit_hits = len(r.data.get("rules") or [])
            score += min(0.10, habit_hits * 0.05)
            if habit_hits:
                grounded_signal += 0.05

        elif r.agent == "self_improvement":
            failures = r.data.get("failures") or []
            if failures:
                score += 0.05
                grounded_signal += 0.03

        elif r.agent == "proactive":
            insights = r.data.get("insights") or []
            if insights:
                score += 0.05
                grounded_signal += 0.03

        elif r.agent == "voice":
            score += 0.03

        elif r.agent == "introspection":
            if r.data.get("content"):
                score += 0.15           # grounded self-knowledge is high value
                grounded_signal += 0.15

        elif r.agent == "reflection":
            insights = r.data.get("insights") or []
            score += min(0.08, len(insights) * 0.02)
            # Reflection insights are introspective, not grounded evidence —
            # they don't count toward grounded_signal.

        elif r.agent == "file_code":
            snippets = r.data.get("snippets") or []
            score += min(0.15, len(snippets) * 0.04)
            if snippets:
                grounded_signal += min(0.10, len(snippets) * 0.03)

    # Multi-contributor bonus: only when there's also grounded signal,
    # not just three agents that all returned 'I had nothing'.
    if contributors >= 3 and grounded_signal > 0.05:
        score += 0.05

    # Empty-bus penalty: if no agent produced any grounded evidence,
    # cap the aggregated score at "medium" (0.65). High-confidence
    # claims require grounding.
    if grounded_signal <= 0.0:
        score = min(score, 0.65)

    return max(0.02, min(0.98, score))


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
    timeout_s = 2.0

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

        print(f"[AGENT:orchestrator] action={action} plan_type={plan.get('type','none')} "
              f"elapsed={elapsed:.0f}ms")
        return AgentResult(
            agent=self.name, ok=True, confidence=0.70 if plan else 0.0,
            data={"plan": plan, "needs_planning": bool(plan)},
            elapsed_ms=elapsed,
        )


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

        selected_names = _select_agents_for_intent(user_input, action)
        active_agents = [
            a for a in _ALL_AGENTS
            if getattr(a, "_enabled", True)
            and (selected_names is None or a.name in selected_names)
        ]
        futures = {
            self._pool.submit(
                agent.run, user_input, intent, session_id, user_id
            ): agent
            for agent in active_agents
        }

        results: List[AgentResult] = []
        max_timeout = max((a.timeout_s for a in active_agents), default=5.0)

        for future in as_completed(futures, timeout=max_timeout + 1.0):
            agent = futures[future]
            try:
                result = future.result(timeout=agent.timeout_s)
                results.append(result)
            except FuturesTimeout:
                print(f"[AGENTBUS] {agent.name} timed out after {agent.timeout_s}s")
                results.append(AgentResult(
                    agent=agent.name, ok=False, confidence=0.0,
                    data={}, error="timeout",
                ))
            except Exception as e:
                print(f"[AGENTBUS] {agent.name} raised: {e}")
                results.append(AgentResult(
                    agent=agent.name, ok=False, confidence=0.0,
                    data={}, error=str(e),
                ))

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

        agg_conf = _aggregate_confidence(intent_conf, results, action)
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

        print(
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
            agents_used=agents_used,
            elapsed_ms=elapsed,
            orchestrator_plan=orchestrator_plan,
        )

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

class FileCodeAgent(_BaseAgent):
    name = "file_code"
    timeout_s = 4.0

    def run(self, user_input: str, intent: Dict[str, Any], session_id: str, user_id: str) -> AgentResult:
        t0 = time.perf_counter()
        try:
            action = str((intent or {}).get("action", "") or "").upper().strip()
            low = (user_input or "").strip().lower()

            relevant = (
                _query_is_grounded(user_input, action)
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

            root = Path(__file__).resolve().parents[2]

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

            local_conf = 0.78 if snippets else 0.20
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:file_code] snippets={len(snippets)} files_scanned={files_scanned} conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=local_conf,
                data={"snippets": snippets[:20], "files_scanned": files_scanned},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:file_code] ERROR: {e}")
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
                              "RUNTIME_STATUS", "COGNITION_STATUS"} or any(
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
            print(f"[AGENT:introspection] content_chars={len(content)} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name, ok=True, confidence=0.90,
                data={"content": content, "snippets": [content[:800]]},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:introspection] ERROR: {e}")
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
            print(f"[AGENT:reflection] insights={len(insights)} conf={local_conf:.2f} elapsed={elapsed:.0f}ms")
            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=local_conf,
                data={"insights": insights[:12]},
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[AGENT:reflection] ERROR: {e}")
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
    Queries the SQLite knowledge graph (eli_memory.sqlite3 kg_entities/kg_relations)
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

            ctx = kg.context_for_prompt(user_input, max_chars=700)
            elapsed = (time.perf_counter() - t0) * 1000

            if not ctx:
                return AgentResult(agent=self.name, ok=True, confidence=0.0,
                                   data={"skipped": True}, elapsed_ms=elapsed)

            confidence = min(0.85, 0.4 + stats["relations"] * 0.02)
            kg_block = f"Knowledge graph context:\n{ctx}"
            print(f"[AGENT:knowledge_graph] {stats['entities']} entities, "
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
    MemoryAgent(),
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

try:
    from eli.runtime.runtime_policy import timeout as _eli_agent_timeout
    for _eli_agent in _ALL_AGENTS:
        _eli_agent.timeout_s = _eli_agent_timeout(
            f"agent_{getattr(_eli_agent, 'name', 'unknown')}",
            float(getattr(_eli_agent, "timeout_s", 4.0) or 4.0),
        )
except Exception:
    pass

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
        print(f"[AGENTBUS] Trusted agent registered: {py_file.name} ({sha[:12]}…)")
    except Exception as _e:
        print(f"[AGENTBUS] Failed to register agent trust for {py_file.name}: {_e}")


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
                        print(
                            f"[AGENTBUS] SECURITY: Custom agent '{py_file.name}' is not trusted. "
                            f"Run `eli --trust-agent {py_file}` to approve it before loading."
                        )
                        continue
                    if file_hash != trusted_hash:
                        print(
                            f"[AGENTBUS] SECURITY: Custom agent '{py_file.name}' hash mismatch — "
                            f"file may have been modified. Re-run `eli --trust-agent {py_file}` "
                            f"to re-approve after reviewing the changes."
                        )
                        continue
                # ── Load ────────────────────────────────────────────────────
                try:
                    spec = _ilu.spec_from_file_location(py_file.stem, str(py_file))
                    mod = _ilu.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    print(f"[AGENTBUS] Loaded custom agent: {py_file.name} from {custom_dir}")
                except Exception as _e:
                    print(f"[AGENTBUS] Failed to load custom agent {py_file.name}: {_e}")
        except Exception as _e:
            print(f"[AGENTBUS] Custom agent dir scan failed for {custom_dir}: {_e}")


_load_custom_agents()
