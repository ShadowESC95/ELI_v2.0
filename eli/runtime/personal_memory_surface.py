from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


def is_personal_memory_query(user_text: Any) -> bool:
    low = str(user_text or "").lower().strip()
    low = re.sub(r"\s+", " ", low)

    if not low:
        return False

    technical_markers = (
        "memory system works internally",
        "which files",
        "which db tables",
        "which functions",
        "runtime surface",
        "memory runtime",
        "schema",
        "table counts",
        "full runtime audit and tell me what's actually broken",
        "imports are failing",
        "what imports",
        "diagnostic report",
        "audit report",
    )
    if any(m in low for m in technical_markers):
        return False

    personal_markers = (
        "what do you know about me",
        "what do you remember about me",
        "do you know me",
        "who am i",
        "who i am",
        "my preferences",
        "my persona",
        "my ethos",
        "summarise me",
        "summarize me",
        "from memory",
        "search your memories",
        "search your memory",
        "search memories for",
        "search memory for",
        "my name",
    )

    return any(m in low for m in personal_markers)


def _clean(value: Any, limit: int = 520) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if s.lower() == "none":
        return ""
    if len(s) > limit:
        return s[: limit - 1].rstrip() + "…"
    return s


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return bool(
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
            (table,),
        ).fetchone()
    )


def _count(cur: sqlite3.Cursor, table: str) -> int:
    try:
        if not _table_exists(cur, table):
            return 0
        return int(cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        return -1


def _bad_raw_row(text: str, tags: str = "", kind: str = "", source: str = "", role: str = "") -> bool:
    low = _clean(text, 2400).lower()
    tags_l = str(tags or "").lower()
    kind_l = str(kind or "").lower()
    source_l = str(source or "").lower()
    role_l = str(role or "").lower()

    if not low:
        return True

    noise = (
        "reflection (24h):",
        "session context:",
        "proactive daemon started",
        "stored_name:",
        "stable_fact_candidates",
        "memory runtime surface:",
        "live memory audit complete",
        "root db exists:",
        "src db exists:",
        "weather for wexford",
        "what time is it assistant:",
        "capability manifest updated",
        "personal memory summary from active local db",
        "runtime snapshot hints:",
        "matrix test:",
        "e2e test:",
        "enterprise test",
        "eli response:",
        "test:",
    )
    if any(x in low for x in noise):
        return True

    if "user:" in low and "assistant:" in low:
        return True

    if "assistant_insight" in tags_l:
        return True
    if "reflection,auto" in tags_l:
        return True
    if "session_summary" in tags_l:
        return True
    if kind_l == "reflection":
        return True
    if source_l == "system":
        return True
    if source_l == "assistant":
        return True
    if role_l == "assistant":
        return True

    complaint_noise = (
        "insulting",
        "what's wrong with your brain",
        "whats wrong with your brain",
        "wat's wrong with your brain",
        "why did your response take so long",
        "why was it also incorrect",
        "you do not remember who i am",
    )
    if any(x in low for x in complaint_noise):
        return True

    probe_noise = (
        "what do you know about me from memory",
        "do you know me, my preferences",
        "explain exactly how your memory system works internally",
    )
    if any(x in low for x in probe_noise):
        return True

    return False


def _uniq(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for item in sorted(items, key=lambda x: (x["score"], x["source_rank"], x["ts"] or 0), reverse=True):
        key = re.sub(r"[^a-z0-9]+", " ", item["text"].lower()).strip()[:180]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= n:
            break

    return out


def _item(table: str, row_id: Any, text: Any, score: int, source_rank: int, ts_value: Any = 0) -> dict[str, Any]:
    return {
        "table": table,
        "id": row_id,
        "text": _clean(text, 560),
        "score": score,
        "source_rank": source_rank,
        "ts": ts_value or 0,
    }


def personal_memory_surface(question: Any = None) -> str:
    root = Path(__file__).resolve().parents[2]
    db = root / "artifacts" / "db" / "user.sqlite3"
    runtime_snapshot = root / "artifacts" / "runtime_snapshot.json"

    if not db.exists():
        return f"Personal memory summary unavailable: active user DB does not exist at {db}"

    identity: list[dict[str, Any]] = []
    prefs: list[dict[str, Any]] = []
    eli_project: list[dict[str, Any]] = []
    research: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    # ── HIGHEST PRIORITY: user_profile.json (written by set_user_name/update_user_profile) ──
    # This is the authoritative store — SQLite identity patterns are backup evidence only.
    try:
        from eli.kernel.state import get_user_name as _gun, load_user_profile as _lup
        _profile_name = _gun()
        if _profile_name:
            identity.insert(0, _item(
                "user_profile", "name",
                f"User's confirmed name: {_profile_name}",
                1000, 10, time.time(),
            ))
        _prof = _lup()
        _now_ts = time.time()
        for _pref in (_prof.get("preferences") or []):
            _pref = (_pref or "").strip()
            if _pref:
                prefs.append(_item("user_profile", "pref", _pref, 500, 8, _now_ts))
        for _proj in (_prof.get("active_projects") or []):
            _proj = (_proj or "").strip()
            if _proj:
                eli_project.append(_item("user_profile", "project", _proj, 500, 8, _now_ts))
        for _res in (_prof.get("research") or []):
            _res = (_res or "").strip()
            if _res:
                research.append(_item("user_profile", "research", _res, 500, 8, _now_ts))
    except Exception:
        pass

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    for table in [
        "memories",
        "memories_fts",
        "conversation_turns",
        "observations",
        "user_patterns",
        "session_summaries",
        "recall_log",
    ]:
        counts[table] = _count(cur, table)

    # 1. Highest priority: structured user_patterns.
    if _table_exists(cur, "user_patterns"):
        rows = cur.execute(
            """
            SELECT id, pattern_type, pattern_data, ts, timestamp
            FROM user_patterns
            ORDER BY COALESCE(ts, timestamp, 0) DESC
            LIMIT 1000
            """
        ).fetchall()

        for r in rows:
            ptype = str(r["pattern_type"] or "")
            pdata = _clean(r["pattern_data"], 600)
            ts_value = r["ts"] or r["timestamp"] or 0

            if ptype.startswith("identity."):
                identity.append(_item("user_patterns", r["id"], pdata, 300, 4, ts_value))
            elif ptype.startswith("preference."):
                prefs.append(_item("user_patterns", r["id"], pdata, 300, 4, ts_value))
            elif ptype.startswith("project.eli"):
                eli_project.append(_item("user_patterns", r["id"], pdata, 300, 4, ts_value))
            elif ptype.startswith("research."):
                research.append(_item("user_patterns", r["id"], pdata, 300, 4, ts_value))

    # 2. Stable memories: backup evidence.
    if _table_exists(cur, "memories"):
        rows = cur.execute(
            """
            SELECT id, text, value, content, tags, kind, source, ts, timestamp
            FROM memories
            ORDER BY COALESCE(ts, timestamp, 0) DESC
            LIMIT 1200
            """
        ).fetchall()

        for r in rows:
            text = _clean(r["text"] or r["value"] or r["content"] or "", 700)
            tags = str(r["tags"] or "")
            kind = str(r["kind"] or "")
            source = str(r["source"] or "")
            ts_value = r["ts"] or r["timestamp"] or 0

            if _bad_raw_row(text, tags=tags, kind=kind, source=source):
                continue

            low = text.lower()
            tags_l = tags.lower()
            kind_l = kind.lower()
            source_l = source.lower()

            if kind_l == "identity" or "identity" in tags_l or "name" in tags_l:
                identity.append(_item("memories", r["id"], text, 220, 3, ts_value))
            elif source_l == "user" and re.search(r"\bprefer|preference|no vague|diagnostic|audit|bash|step-by-step|in-depth\b", low):
                prefs.append(_item("memories", r["id"], text, 170, 3, ts_value))
            elif source_l == "user" and re.search(r"\beli|mkxi|mkix|gguf|cognition|orchestrator|sqlite|memory|runtime\b", low):
                eli_project.append(_item("memories", r["id"], text, 160, 3, ts_value))
            elif source_l == "user" and re.search(r"\bphysics\b|\bchemistry\b|\bbiology\b|\bengineering\b|\bsimulation\b|\bresearch\b|\bexperiment\b|\btheory\b", text, re.IGNORECASE):
                research.append(_item("memories", r["id"], text, 160, 3, ts_value))

    # 3. User conversation turns: last-resort evidence, mostly project/preference examples.
    if _table_exists(cur, "conversation_turns"):
        rows = cur.execute(
            """
            SELECT id, role, content, ts, timestamp
            FROM conversation_turns
            WHERE lower(COALESCE(role, '')) = 'user'
            ORDER BY COALESCE(ts, timestamp, 0) DESC
            LIMIT 1200
            """
        ).fetchall()

        for r in rows:
            text = _clean(r["content"], 700)
            ts_value = r["ts"] or r["timestamp"] or 0

            if _bad_raw_row(text, role="user", source="conversation_turns", kind="turn"):
                continue

            low = text.lower()

            # Generic identity-signal extraction. No user-specific names here.
            if (
                re.fullmatch(r".{0,60}\bmy name is\s+[a-z][a-z' -]{1,30}\b.{0,40}", low)
                or re.fullmatch(r".{0,80}\bit is\s+[a-z][a-z' -]{1,30},?\s+or\s+[a-z][a-z' -]{1,30}\b.{0,80}", low)
            ):
                identity.append(_item("conversation_turns", r["id"], text, 90, 1, ts_value))

            if re.search(r"\bno vague descriptions\b|\bfull runtime audit\b|\bdiagnostic\b|\bdirect bash commands\b|\bin depth\b|\bevery step\b", low):
                prefs.append(_item("conversation_turns", r["id"], text, 95, 1, ts_value))

            if re.search(r"\beli\b|\bmkxi\b|\bcognition pipeline\b|\borchestrator\b|\bmemory\b|\bruntime\b|\bpersona\.auto\b", low):
                eli_project.append(_item("conversation_turns", r["id"], text, 90, 1, ts_value))

            if re.search(r"\bphysics\b|\bchemistry\b|\bbiology\b|\bengineering\b|\btheory\b|\bsimulation\b|\bresearch\b|\bexperiment\b", text, re.IGNORECASE):
                research.append(_item("conversation_turns", r["id"], text, 90, 1, ts_value))

    identity = _uniq(identity, 4)
    prefs = _uniq(prefs, 5)
    eli_project = _uniq(eli_project, 3)
    research = _uniq(research, 3)

    try:
        if _table_exists(cur, "recall_log"):
            now = time.time()
            total = len(identity) + len(prefs) + len(eli_project) + len(research)
            cur.execute(
                """
                INSERT INTO recall_log(ts, timestamp, query, results_count, result_count, memory_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, now, str(question or "personal memory summary")[:500], total, total, None),
            )
            con.commit()
    except Exception:
        pass

    con.close()

    runtime_bits: list[str] = []
    if runtime_snapshot.exists():
        try:
            snap = json.loads(runtime_snapshot.read_text())
            for key in ["model", "model_path", "provider", "n_ctx", "context_size", "gpu_layers", "n_gpu_layers", "batch", "threads"]:
                if key in snap and snap[key] not in (None, ""):
                    runtime_bits.append(f"{key}={snap[key]}")
        except Exception:
            pass

    lines: list[str] = []
    lines.append("Personal memory summary from active local DB:")
    lines.append(f"- db: {db}")

    lines.append("")
    lines.append("Identity/name signals:")
    if identity:
        for item in identity:
            lines.append(f"- {item['text']} [{item['table']}#{item['id']}]")
    else:
        lines.append("- none strong enough")

    lines.append("")
    lines.append("Working-style / preference signals:")
    if prefs:
        for item in prefs:
            lines.append(f"- {item['text']} [{item['table']}#{item['id']}]")
    else:
        lines.append("- no structured preference rows found")

    lines.append("")
    lines.append("ELI / local-assistant project signals:")
    if eli_project:
        for item in eli_project:
            lines.append(f"- {item['text']} [{item['table']}#{item['id']}]")
    else:
        lines.append("- none found")

    lines.append("")
    lines.append("Research / physics signals:")
    if research:
        for item in research:
            lines.append(f"- {item['text']} [{item['table']}#{item['id']}]")
    else:
        lines.append("- none found")

    lines.append("")
    lines.append("Memory health:")
    lines.append("- counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    weaknesses: list[str] = []
    if counts.get("user_patterns", 0) == 0:
        weaknesses.append("user_patterns is empty")
    if counts.get("session_summaries", 0) == 0:
        weaknesses.append("session_summaries is empty")
    if counts.get("observations", 0) > 10:
        weaknesses.append("observations still contains repeated/non-profile system events")
    if counts.get("memories", 0) > 0 and len(identity + prefs + eli_project + research) < 5:
        weaknesses.append("stored memories exist, but high-value profile extraction is weak")
    lines.append("- weaknesses: " + ("; ".join(weaknesses) if weaknesses else "none obvious from this surface"))

    if runtime_bits:
        lines.append("")
        lines.append("Runtime snapshot hints:")
        lines.append("- " + "; ".join(runtime_bits[:10]))

    return "\n".join(lines)
