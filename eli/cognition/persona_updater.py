"""
brain.awareness.persona_updater
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs the persona auto-overlay update at boot and after reflection cycles.
Replaces the need to manually run scripts/persona_autoupdate_from_db.py.

Called from boot_awareness() and from the reflection cycle in the
cognitive engine.
"""

from __future__ import annotations
from pathlib import Path
import re

import logging
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Module-level debounce: skip update_persona_overlay() calls that occur within
# 120 seconds of the previous run. The Lock prevents the race condition where
# multiple threads (reflection, proactive daemon, self-improvement) all read
# _LAST_RUN=0.0 simultaneously at startup and all get past the check.
_PERSONA_OVERLAY_LAST_RUN: float = 0.0
_PERSONA_OVERLAY_MIN_INTERVAL: float = 120.0
_PERSONA_OVERLAY_LOCK: threading.Lock = threading.Lock()


def _safe_call(obj: Any, name: str, *args, **kwargs):
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return fn(*args, **kwargs)
        except Exception as _exc:
            log.warning("persona_updater._safe_call: %s.%s raised %s: %s",
                        type(obj).__name__, name, type(_exc).__name__, _exc)
            return None
    return None


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _top_lines(rows: Any, key: str, limit: int = 8) -> List[str]:
    """Extract text lines from memory rows, filtering out raw user chat messages,
    red-team probe logs, and other content that would contaminate the LLM context
    if injected into the persona overlay."""
    import re as _re
    # Raw conversational messages should never go into the persona overlay
    _chat_noise = _re.compile(
        r"^(hey|hi|hello|do you|can you|what|how|who|you mean|that is|i am|"
        r"sure|ok|yes|no|please|thanks|haha|lol|hm|hmm|i think|i want|"
        r"let me|tell me|give me|show me|help me|could you|would you)",
        _re.I
    )
    # Red-team / security probe logs MUST NOT enter the persona overlay.
    # When the LLM sees them in context it confabulates responses mentioning
    # "security_blocked", raw shell commands, file paths like /etc/passwd, etc.
    # These are internal diagnostic signals, not signals about persona.
    _diagnostic_noise = _re.compile(
        r"(?:security[_\s]+blocked|"
        r"\bRUN_CMD\b|\bSHELL_EXEC\b|"
        r"\b(?:rm\s+-rf|chmod|chown|chpasswd|crontab|iptables|dd\s+if=|nc\s+-l|"
        r"echo\s+\S+\s*>|cat\s+/etc/|ls\s+-la|mkfs|fdisk|kill\s+-9)\b|"
        r"/etc/(?:passwd|shadow|sudoers|hosts)|"
        r"/dev/(?:null|zero|random)|"
        r"investigate failure:\s*run_cmd)",
        _re.I,
    )
    out: List[str] = []
    if not rows:
        return out
    for row in rows[:limit * 5]:  # scan more to find non-noise entries
        text = _clean(row.get(key) if isinstance(row, dict) else "")
        if not text:
            continue
        # Skip raw conversational user messages
        if _chat_noise.match(text):
            continue
        # Skip red-team probe logs (security_blocked, raw shell commands, etc.)
        if _diagnostic_noise.search(text):
            continue
        # Skip very short entries (likely noise)
        if len(text) < 20:
            continue
        out.append(text[:220])
        if len(out) >= limit:
            break
    return out


def _habit_lines(mem: Any) -> List[str]:
    rules = _safe_call(mem, "get_habit_rules", enabled_only=False) or []
    out: List[str] = []
    for row in rules[:10]:
        if not isinstance(row, dict):
            continue
        name = _clean(row.get("name", ""))
        command = _clean(row.get("command", ""))
        hour = row.get("hour", 0)
        minute = row.get("minute", 0)
        enabled = bool(row.get("enabled", False))
        label = f"{name or 'unnamed'} @ {int(hour):02d}:{int(minute):02d}"
        if command:
            label += f" -> {command[:120]}"
        label += " [enabled]" if enabled else " [disabled]"
        out.append(label)
    return out


def _dedup_lines(lines: List[str]) -> List[str]:
    """Remove exact duplicates, keep order, keep last occurrence."""
    seen = set()
    result = []
    for line in reversed(lines):
        key = line.strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(line)
    result.reverse()
    return result


def _merge_memory_rows(*groups: Any, preferred_keys: tuple = ()) -> List[Dict[str, Any]]:
    """Merge rows from user/agent memory without duplicating the same signal."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for group in groups:
        if not group:
            continue
        for row in group:
            if not isinstance(row, dict):
                continue
            sig_parts = []
            for key in preferred_keys:
                val = _clean(row.get(key))
                if val:
                    sig_parts.append(val.lower())
            if not sig_parts:
                sig_parts = [_clean(v).lower() for v in row.values() if _clean(v)]
            sig = "|".join(sig_parts)[:500]
            if not sig or sig in seen:
                continue
            seen.add(sig)
            merged.append(row)
    return merged

def _sanitize_release_overlay_text(text: str) -> str:
    text = text or ""

    line_rules = [
        (r'(?m)^- Runtime status:.*$', '- Runtime status: sanitized'),
        (r'(?m)^- Cognition runtime:.*$', '- Cognition runtime: sanitized'),
        (r'(?m)^- Memory recall:.*$', '- Memory recall: sanitized'),
    ]
    for patt, repl in line_rules:
        text = re.sub(patt, repl, text)

    inline_rules = [
        (r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '<LOCAL_EMAIL>'),
        (r'(?<![A-Za-z0-9_])/(?:home|Users|mnt)/\S+', '<LOCAL_PATH>'),
        (r'\b[A-Za-z]:\\\S+', '<LOCAL_PATH>'),
    ]
    for patt, repl in inline_rules:
        text = re.sub(patt, repl, text)

    return text

def _post_sanitize_overlay_file(path) -> bool:
    try:
        path = Path(path)
        raw = path.read_text(encoding='utf-8', errors='replace')
        clean = _sanitize_release_overlay_text(raw)
        if clean != raw:
            path.write_text(clean, encoding='utf-8')
            return True
    except Exception:
        return False
    return False

def _get_reflection_themes(memory: Any, limit: int = 6) -> List[str]:
    """
    Pull reflection summaries and session narratives directly from the memories
    table. get_recent_semantic_memories() deliberately filters these out for
    RAG purposes, but they are exactly what we want for the persona overlay.
    """
    try:
        import sqlite3 as _sqlite3
        db_path = getattr(memory, "db_path", None) or getattr(memory, "_db_path", None)
        if db_path is None:
            try:
                from eli.core.paths import user_db_path
                db_path = str(user_db_path())
            except Exception:
                return []
        con = _sqlite3.connect(str(db_path))
        try:
            rows = con.execute(
                """
                SELECT COALESCE(text, value, '') AS body
                FROM memories
                WHERE (
                    kind IN ('reflection', 'memory')
                    AND (tags LIKE '%reflection%' OR tags LIKE '%session_summary%')
                )
                AND length(COALESCE(text, value, '')) > 20
                ORDER BY COALESCE(timestamp, ts, id) DESC
                LIMIT ?
                """,
                (limit * 4,),
            ).fetchall()
        finally:
            con.close()
        seen: set = set()
        out: List[str] = []
        for (body,) in rows:
            body = (body or "").strip()
            if not body or body in seen:
                continue
            seen.add(body)
            out.append(body[:280])
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        log.debug("_get_reflection_themes error: %s", e)
        return []


def _get_session_narrative(memory: Any, limit: int = 3) -> List[str]:
    """Pull the last `limit` session summaries for continuity context, newest
    first.

    Prefers the in-depth, LLM-generated end-of-session summaries in the
    `session_summaries` table (written at shutdown by
    profile_extractor.write_llm_session_summary). Falls back to the older, short
    `memories` rows tagged 'session_summary' when the rich table is empty (e.g.
    before the first clean shutdown). These are surfaced as PAST-SESSION
    continuity context (labelled "previous sessions — not current request" by
    kernel/state.py), never as current truth.
    """
    try:
        import sqlite3 as _sqlite3
        db_path = getattr(memory, "db_path", None) or getattr(memory, "_db_path", None)
        if db_path is None:
            try:
                from eli.core.paths import user_db_path
                db_path = str(user_db_path())
            except Exception:
                return []
        con = _sqlite3.connect(str(db_path))
        try:
            # 1) In-depth LLM session summaries (richer — allow more chars each).
            out: List[str] = []
            try:
                _has = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='session_summaries'"
                ).fetchone()
                if _has:
                    rows = con.execute(
                        """
                        SELECT COALESCE(summary, content, '')
                        FROM session_summaries
                        WHERE source IN ('session_end', 'session_end_heuristic')
                          AND length(COALESCE(summary, content, '')) > 20
                        ORDER BY COALESCE(ended_at, timestamp, ts, id) DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                    out = [(r[0] or "").strip()[:480] for r in rows if r[0]]
            except Exception:
                out = []
            if out:
                return out
            # 2) Fallback: short narratives in `memories`.
            rows = con.execute(
                """
                SELECT text FROM memories
                WHERE tags LIKE '%session_summary%'
                  AND length(COALESCE(text, '')) > 20
                ORDER BY ROWID DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            con.close()
        return [(r[0] or "").strip()[:240] for r in rows if r[0]]
    except Exception as e:
        log.debug("_get_session_narrative error: %s", e)
        return []


def _runtime_pattern_lines(limit: int = 8) -> List[str]:
    try:
        from eli.runtime.evidence_ledger import repeated_event_signals

        out: List[str] = []
        for item in repeated_event_signals(limit=limit, days=7):
            label = _clean(item.get("action") or item.get("event_type") or "event")
            subject = _clean(item.get("subject"))
            count = item.get("count")
            line = f"{label}"
            if subject:
                line += f" / {subject[:120]}"
            line += f" seen {count}x"
            out.append(line)
        return out
    except Exception:
        return []


def update_persona_overlay(memory: Any = None) -> Dict[str, Any]:
    """
    Rebuild persona.auto.txt from current memory state.
    This file contains ELI's evolving persona — habits, reflections,
    self-improvement notes, and failure patterns.

    User profile data (name, preferences, working style) is stored
    separately in user_profile.json via update_user_profile_overlay().

    Returns {"ok": bool, "changed": bool, "sections": int}.
    """
    global _PERSONA_OVERLAY_LAST_RUN
    now = time.time()
    with _PERSONA_OVERLAY_LOCK:
        if now - _PERSONA_OVERLAY_LAST_RUN < _PERSONA_OVERLAY_MIN_INTERVAL:
            return {"ok": True, "skipped": True, "reason": "debounce"}
        _PERSONA_OVERLAY_LAST_RUN = now

    if memory is None:
        try:
            from eli.memory import get_memory
            memory = get_memory()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    try:
        from eli.cognition.persona import update_auto_sections
    except Exception as exc:
        return {"ok": False, "error": f"persona.update_auto_sections unavailable: {exc}"}

    # Gather ELI-specific data from memory. Failures and improvements can live
    # in the agent DB even when the updater is invoked with the user DB.
    agent_memory = None
    try:
        from eli.memory import get_agent_memory
        agent_memory = get_agent_memory()
    except Exception:
        agent_memory = None

    observations = _safe_call(memory, "get_recent_observations", limit=8) or []
    user_improvements = _safe_call(memory, "get_recent_improvements", limit=8) or []
    user_failures = _safe_call(memory, "get_recent_failures", limit=5) or []
    agent_improvements = _safe_call(agent_memory, "get_recent_improvements", limit=8) or []
    agent_failures = _safe_call(agent_memory, "get_recent_failures", limit=5) or []
    improvements = _merge_memory_rows(
        user_improvements, agent_improvements,
        preferred_keys=("description", "content", "text"),
    )
    failures = _merge_memory_rows(
        user_failures, agent_failures,
        preferred_keys=("error", "failure", "description"),
    )

    # Reflection themes: use the direct DB query since get_recent_semantic_memories
    # deliberately filters out reflection/session_summary entries.
    reflection_themes = _dedup_lines(
        _get_reflection_themes(memory, limit=4) + _get_session_narrative(memory, limit=3)
    )

    # ELI's persona sections only — no user profile data here
    sections = {
        "Runtime Persona Notes": [
            "This file is ELI's auto-updating persona overlay.",
            "User profile (name, preferences) is stored separately in user_profile.json.",
            "Prefer concrete continuity, memory-backed context, and direct language.",
        ],
        "Habits (Auto-Updated)": _dedup_lines(_habit_lines(memory)),
        "Reflection / Observations (Auto-Updated)": _dedup_lines(
            _top_lines(observations, "observation", limit=8)
        ),
        "Runtime Patterns (Auto-Updated)": _dedup_lines(_runtime_pattern_lines(limit=8)),
        "Self Improvement (Auto-Updated)": _dedup_lines(
            _top_lines(improvements, "description", limit=8)
        ),
        "Recent Failure Patterns (Auto-Updated)": _dedup_lines(
            _top_lines(failures, "error", limit=5)
        ),
        "Processed Memory Themes (Auto-Updated)": reflection_themes,
    }

    try:
        update_auto_sections(sections)
        log.info("persona_updater: overlay updated (%d sections)", len(sections))
    except Exception as exc:
        log.warning("persona_updater: failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    # Run tone analysis — detects communication style, depth preference,
    # humor engagement, correction rate, and frustration signals from recent
    # conversation turns. Results are written to user_patterns as
    # preference.tone.* entries and flow into user_profile.json below.
    try:
        from eli.cognition.tone_analyzer import run_tone_analysis
        _tone_result = run_tone_analysis(memory)
        if _tone_result.get("written"):
            log.info("persona_updater: tone signals updated: %s", _tone_result["written"])
    except Exception as _tone_err:
        log.debug("persona_updater: tone analysis failed (non-fatal): %s", _tone_err)

    # Sync user_patterns → knowledge graph so it grows from real user data.
    try:
        _populate_kg_from_user_patterns(memory)
    except Exception as _kg_err:
        log.debug("persona_updater: kg sync failed (non-fatal): %s", _kg_err)

    # Also update the user profile file from identity signals in memory
    update_user_profile_overlay(memory)
    return {"ok": True, "changed": True, "sections": len(sections)}


def _read_user_patterns(memory: Any) -> Dict[str, List[str]]:
    """
    Read user_patterns table directly and group by pattern type.
    Returns {type_prefix: [data_string, ...]} for preference/identity/project/research.
    """
    try:
        import sqlite3 as _sqlite3
        db_path = getattr(memory, "db_path", None) or getattr(memory, "_db_path", None)
        if db_path is None:
            try:
                from eli.core.paths import user_db_path
                db_path = str(user_db_path())
            except Exception:
                return {}
        con = _sqlite3.connect(str(db_path))
        try:
            rows = con.execute(
                """
                SELECT pattern_type, pattern_data, COALESCE(timestamp, ts)
                FROM user_patterns
                WHERE length(COALESCE(pattern_data,'')) > 10
                ORDER BY COALESCE(timestamp, ts, id) DESC
                """
            ).fetchall()
        finally:
            con.close()
        import time as _time
        now = _time.time()
        groups: Dict[str, List[str]] = {}
        seen: set = set()
        for (ptype, pdata, pts) in rows:
            pdata = (pdata or "").strip()
            key = pdata.lower()[:120]
            if not pdata or key in seen:
                continue
            seen.add(key)
            prefix = (ptype or "other").split(".")[0]
            if prefix == "project" and pts:
                age_h = (now - float(pts)) / 3600
                if age_h >= 4:
                    age_label = f"{age_h/24:.0f}d ago" if age_h >= 48 else f"{age_h:.0f}h ago"
                    pdata = f"{pdata} (last active: {age_label})"
            groups.setdefault(prefix, []).append(pdata)
        return groups
    except Exception as e:
        log.debug("_read_user_patterns error: %s", e)
        return {}


def _extract_name_from_identity_item(text: str) -> str:
    """
    Extract a bare personal name from identity pattern strings like:
      "User's name is jason."
      "User's preferred name is Jason."
      "The user's name is jay."
    Returns the candidate name, or "" if nothing found.
    """
    import re as _re
    m = _re.search(
        r"(?:name is|preferred name is|called|known as)\s+([A-Za-z][A-Za-z' -]{1,29})\b",
        text,
        _re.I,
    )
    if not m:
        return ""
    candidate = m.group(1).strip(" .,;")
    # Reject obvious non-names
    if candidate.lower() in {
        "unknown", "none", "the", "a", "an", "no", "not", "asking", "user",
        "screenshot", "name", "unnamed", "anonymous", "guest", "admin",
        "root", "system", "default", "test", "sample", "example",
        "placeholder", "null", "undefined",
    }:
        return ""
    return candidate


def _populate_kg_from_user_patterns(memory: Any) -> None:
    """
    Sync structured user_patterns data into the knowledge graph.
    Extracts project, research, and preference signals and inserts
    them as typed triples so the KG agent has meaningful content.
    """
    from eli.memory.knowledge_graph import get_knowledge_graph
    kg = get_knowledge_graph()
    patterns = _read_user_patterns(memory)

    # Canonical user node
    kg.upsert_entity("User", "person")

    # Name from user_profile
    try:
        from eli.kernel.state import get_user_name
        name = get_user_name().strip()
        if name:
            kg.upsert_entity(name, "person")
            kg.add_relation("User", "has_name", name, source="user_profile")
    except Exception:
        pass

    # Projects → works_on
    for proj in patterns.get("project", [])[:4]:
        m = re.search(
            r"(?:developing|building|working\s+on|debugging|tuning)\s+([A-Za-z][A-Za-z0-9_\- ]{1,30})",
            proj, re.I,
        )
        if m:
            project_name = m.group(1).strip().rstrip("'s").strip()
            if len(project_name) > 2:
                kg.upsert_entity(project_name, "project")
                kg.add_relation("User", "works_on", project_name, source="user_patterns")

    # Research → researches
    for res in patterns.get("research", [])[:3]:
        for topic_match in re.finditer(
            r"\b(physics|simulation|hydrogen|solar|field\s+framework|"
            r"theoretical\s+physics|astrophysics|quantum|cosmology|"
            r"ELI|machine\s+learning|AI|cognition)\b",
            res, re.I,
        ):
            topic = topic_match.group(0).strip()
            kg.upsert_entity(topic, "research_area")
            kg.add_relation("User", "researches", topic, source="user_patterns")

    # Preferences → key terms only (avoid polluting with long strings)
    for pref in patterns.get("preference", [])[:4]:
        m = re.search(
            r"prefers?\s+(in[- ]depth|brief|executable|thorough|detailed|direct)\b",
            pref, re.I,
        )
        if m:
            pref_val = m.group(1).lower()
            kg.upsert_entity(pref_val, "preference")
            kg.add_relation("User", "prefers", pref_val, source="user_patterns")

    log.debug("persona_updater: kg sync complete — %d entities, %d relations",
              kg.stats().get("entities", 0), kg.stats().get("relations", 0))


def update_user_profile_overlay(memory: Any = None) -> Dict[str, Any]:
    """
    Update user_profile.json from identity signals discovered in memory.
    Pulls from user_patterns table (authoritative, data-driven) rather
    than relying on free-text memory search which is fragile.
    """
    try:
        from eli.kernel.state import load_user_profile, update_user_profile, get_user_name, set_user_name
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    updates: Dict[str, Any] = {}

    # Authoritative name from user_profile.json always wins
    name = get_user_name().strip()
    if name:
        updates["name"] = name

    if memory is not None:
        patterns = _read_user_patterns(memory)

        # Preferences
        pref_lines = patterns.get("preference", [])
        if pref_lines:
            updates["preferences"] = pref_lines[:6]

        # Active projects
        proj_lines = patterns.get("project", [])
        if proj_lines:
            updates["active_projects"] = proj_lines[:4]

        # Research areas
        research_lines = patterns.get("research", [])
        if research_lines:
            updates["research"] = research_lines[:3]

        # Identity signals: extract name from identity.name patterns if profile lacks it,
        # and write it back via set_user_name() so it persists for future sessions.
        for item in patterns.get("identity", []):
            if "name" not in updates:
                # Recover name from "User's name is X." / "preferred name is X." patterns
                recovered = _extract_name_from_identity_item(item)
                if recovered:
                    try:
                        set_user_name(recovered)  # write to user_profile.json
                        log.info("persona_updater: recovered name %r from user_patterns", recovered)
                    except Exception:
                        pass
                    updates["name"] = recovered
            if "nickname" in item.lower() or "nick" in item.lower() or "alias" in item.lower():
                if "nickname" not in updates:
                    updates["nickname"] = item

    if updates:
        try:
            update_user_profile(updates)
            log.info("persona_updater: user profile updated: %s", list(updates.keys()))
            return {"ok": True, "updated": list(updates.keys())}
        except Exception as exc:
            log.warning("persona_updater: user profile update failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    return {"ok": True, "updated": []}
