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
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _safe_call(obj: Any, name: str, *args, **kwargs):
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None
    return None


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _top_lines(rows: Any, key: str, limit: int = 8) -> List[str]:
    """Extract text lines from memory rows, filtering out raw user chat messages."""
    import re as _re
    # Raw conversational messages should never go into the persona overlay
    _chat_noise = _re.compile(
        r"^(hey|hi|hello|do you|can you|what|how|who|you mean|that is|i am|"
        r"sure|ok|yes|no|please|thanks|haha|lol|hm|hmm|i think|i want|"
        r"let me|tell me|give me|show me|help me|could you|would you)",
        _re.I
    )
    out: List[str] = []
    if not rows:
        return out
    for row in rows[:limit * 3]:  # scan more to find non-noise entries
        text = _clean(row.get(key) if isinstance(row, dict) else "")
        if not text:
            continue
        # Skip raw conversational user messages
        if _chat_noise.match(text):
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
    """Pull recent session summaries from the session_summaries table."""
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
                SELECT COALESCE(summary, content, '') AS body
                FROM session_summaries
                WHERE length(COALESCE(summary, content, '')) > 20
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
                SELECT pattern_type, pattern_data
                FROM user_patterns
                WHERE length(COALESCE(pattern_data,'')) > 10
                ORDER BY COALESCE(timestamp, ts, id) DESC
                """
            ).fetchall()
        finally:
            con.close()
        groups: Dict[str, List[str]] = {}
        seen: set = set()
        for (ptype, pdata) in rows:
            pdata = (pdata or "").strip()
            key = pdata.lower()[:120]
            if not pdata or key in seen:
                continue
            seen.add(key)
            prefix = (ptype or "other").split(".")[0]
            groups.setdefault(prefix, []).append(pdata)
        return groups
    except Exception as e:
        log.debug("_read_user_patterns error: %s", e)
        return {}


def update_user_profile_overlay(memory: Any = None) -> Dict[str, Any]:
    """
    Update user_profile.json from identity signals discovered in memory.
    Pulls from user_patterns table (authoritative, data-driven) rather
    than relying on free-text memory search which is fragile.
    """
    try:
        from eli.kernel.state import load_user_profile, update_user_profile, get_user_name
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    updates: Dict[str, Any] = {}

    # Authoritative name from state.json always wins
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

        # Identity signals (nickname, etc.) — only non-name ones
        for item in patterns.get("identity", []):
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
