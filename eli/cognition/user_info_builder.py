from __future__ import annotations

import atexit
import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_LOCK = threading.RLock()
_BG_THREAD = None
_BG_STARTED = False

DEFAULT_INTERVAL_SECONDS = 1800
QUERY_MAX_AGE_SECONDS = 300

def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _root() -> Path:
    # parents[2] resolves to the project root for files at eli/<pkg>/<file>.py
    return Path(__file__).resolve().parents[2]

def _artifacts() -> Path:
    try:
        from eli.core.paths import data_dir as _data_dir
        p = _data_dir()
    except Exception:
        p = _root() / "artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _paths() -> Dict[str, Path]:
    a = _artifacts()
    try:
        from eli.core.paths import user_db_path
        db_path = Path(user_db_path())
    except Exception:
        db_path = a / "db" / "user.sqlite3"

    try:
        from eli.kernel.state import _profile_path as runtime_profile_path
        profile_path = Path(runtime_profile_path())
        user_runtime = profile_path.parent
    except Exception:
        user_runtime = a / "runtime" / "users" / "default-user"
        profile_path = user_runtime / "user_profile.json"

    user_runtime.mkdir(parents=True, exist_ok=True)
    return {
        "txt": user_runtime / "user_info.txt",
        "meta": user_runtime / "user_info.meta.json",
        "diff": user_runtime / "user_info_diff.jsonl",
        "db": db_path,
        "profile": profile_path,
    }

def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _load_meta() -> Dict[str, Any]:
    p = _paths()["meta"]
    meta = _load_json(p, {})
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("generated_at", "")
    meta.setdefault("last_significant_change_at", "")
    meta.setdefault("dirty", False)
    meta.setdefault("dirty_reasons", [])
    meta.setdefault("builder_version", 1)
    meta.setdefault("max_age_seconds", DEFAULT_INTERVAL_SECONDS)
    meta.setdefault("source_counts", {})
    meta.setdefault("section_hashes", {})
    meta.setdefault("summary_hash", "")
    meta.setdefault("last_refresh_reason", "")
    return meta

def _save_meta(meta: Dict[str, Any]) -> None:
    _atomic_write_json(_paths()["meta"], meta)

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, name: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f'PRAGMA table_info("{name}")').fetchall()}
    except Exception:
        return set()


def _active_user_id() -> str:
    try:
        from eli.kernel.state import get_active_user_id
        return str(get_active_user_id() or "")
    except Exception:
        return ""


def _sql_coalesce_expr(cols: set[str], names: list[str], fallback: str = "''") -> str:
    present = [n for n in names if n in cols]
    if not present:
        return fallback
    return "COALESCE(" + ", ".join(present + [fallback]) + ")"


def _sql_time_expr(cols: set[str]) -> str:
    return _sql_coalesce_expr(cols, ["created_at", "timestamp", "ts", "id"], "0")

def _query_all(conn: sqlite3.Connection, sql: str, params=()) -> List[tuple]:
    try:
        return list(conn.execute(sql, params).fetchall())
    except Exception:
        return []

def _read_profile_json() -> Dict[str, Any]:
    try:
        from eli.kernel.state import load_user_profile
        data = load_user_profile()
    except Exception:
        p = _paths()["profile"]
        data = _load_json(p, {})
    return data if isinstance(data, dict) else {}


def _merge_profile_sections(sections: Dict[str, List[str]], profile: Dict[str, Any]) -> None:
    if not profile:
        return
    try:
        from eli.runtime.identity_validation import normalize_identity_candidate
    except Exception:
        normalize_identity_candidate = lambda value, **_: str(value or "").strip()  # type: ignore

    name = normalize_identity_candidate(profile.get("name", ""))
    preferred = normalize_identity_candidate(profile.get("preferred_name", ""))
    nickname = normalize_identity_candidate(profile.get("nickname", ""))
    if name:
        sections["Identity"].append(f"Name: {name}")
    if preferred:
        sections["Identity"].append(f"Preferred name: {preferred}")
    if nickname:
        sections["Identity"].append(f"Nickname: {nickname}")

    for item in profile.get("preferences", []) if isinstance(profile.get("preferences"), list) else []:
        text = str(item or "").strip()
        if text:
            sections["Working Style"].append(text)
    for item in profile.get("active_projects", []) if isinstance(profile.get("active_projects"), list) else []:
        text = str(item or "").strip()
        if text:
            sections["Active Projects"].append(text)
    for item in profile.get("research", []) if isinstance(profile.get("research"), list) else []:
        text = str(item or "").strip()
        if text:
            sections["Active Projects"].append(text)


def _is_profile_noise(text: Any, tags: str = "", kind: str = "", source: str = "") -> bool:
    """
    Reject rows that describe runtime/session mechanics rather than durable user facts.
    This must stay generic: no hardcoded user names, no project-specific identity values.
    """
    low = " ".join(str(text or "").lower().split())
    tags_l = str(tags or "").lower()
    kind_l = str(kind or "").lower()
    source_l = str(source or "").lower()

    if not low:
        return True

    noisy_markers = (
        "session context:",
        "reflection (24h):",
        "stable_fact_candidates",
        "memory runtime surface:",
        "personal memory summary",
        "eli user info snapshot",
        "runtime status:",
        "runtime snapshot",
        "control evidence packet",
        "script generated:",
        "generated script",
        "proactive daemon",
        "capability manifest",
        "what time is it assistant:",
        "weather for ",
        "matrix test:",
        "e2e test:",
        "enterprise test",
        "test:",
    )
    if any(x in low for x in noisy_markers):
        return True

    if "user:" in low and "assistant:" in low:
        return True

    noisy_tags = (
        "assistant_insight",
        "reflection",
        "session_summary",
        "runtime",
        "diagnostic",
        "audit",
        "generated_script",
        "script_output",
    )
    if any(x in tags_l for x in noisy_tags):
        return True

    if kind_l in {"reflection", "session_summary", "runtime", "diagnostic", "audit"}:
        return True

    if source_l in {"assistant", "system", "runtime", "reflection", "daemon"}:
        return True

    return False

def _gather_semantic(conn: sqlite3.Connection, user_id: str | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not _table_exists(conn, "semantic"):
        return out

    cols = _columns(conn, "semantic")
    where = ""
    params: tuple[Any, ...] = ()
    if user_id and "user_id" in cols:
        where = "WHERE COALESCE(user_id,'') = ?"
        params = (user_id,)

    rows = _query_all(
        conn,
        f"""
        SELECT fact, COALESCE(tags,''), COALESCE(confidence,0), COALESCE(created_at,'')
        FROM semantic
        {where}
        ORDER BY confidence DESC, created_at DESC
        LIMIT 200
        """,
        params,
    )
    seen = set()
    for fact, tags, conf, created_at in rows:
        fact = str(fact or "").strip()
        if not fact:
            continue
        k = fact.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(
            {
                "fact": fact,
                "tags": str(tags or ""),
                "confidence": float(conf or 0),
                "created_at": str(created_at or ""),
            }
        )
    return out

def _gather_user_patterns(conn: sqlite3.Connection, user_id: str | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not _table_exists(conn, "user_patterns"):
        return out

    cols = _columns(conn, "user_patterns")

    text_expr = _sql_coalesce_expr(cols, ["pattern_data", "text", "content", "value"], "''")
    type_expr = _sql_coalesce_expr(cols, ["pattern_type", "kind", "tags"], "''")
    time_expr = _sql_time_expr(cols)

    # The canonical user_patterns table has NO user_id column (it is single-user;
    # see eli/core/db_schema). Requiring one made this return empty for EVERY
    # pattern — the durable user-info synthesis got zero pattern evidence (incl.
    # the learned preference.tone.* tone signals). Only scope by user_id when the
    # column actually exists; otherwise read the whole (single-user) table.
    if "user_id" in cols:
        where = "WHERE COALESCE(user_id,'') = ? AND COALESCE(%s, '') != ''" % text_expr
        params = (str(user_id or ""),)
    else:
        where = "WHERE COALESCE(%s, '') != ''" % text_expr
        params = ()

    rows = _query_all(
        conn,
        f"""
        SELECT id, {text_expr} AS text, {type_expr} AS tags, {time_expr} AS t
        FROM user_patterns
        {where}
        ORDER BY {time_expr} DESC
        LIMIT 300
        """,
        params,
    )

    seen = set()
    for _id, text, tags, t in rows:
        text = str(text or "").strip()
        tags = str(tags or "").strip()
        if not text:
            continue
        k = (tags.lower(), text.lower())
        if k in seen:
            continue
        seen.add(k)
        out.append({
            "id": _id,
            "text": text,
            "tags": tags,
            "importance": 0.95,
            "created_at": str(t or ""),
        })
    return out


def _gather_stable_memories(conn: sqlite3.Connection, user_id: str | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not _table_exists(conn, "memories"):
        return out

    cols = _columns(conn, "memories")

    # Multi-user rule: identity/profile extraction only uses scoped rows.
    if "user_id" not in cols:
        return out

    text_expr = _sql_coalesce_expr(cols, ["text", "value", "content"], "''")
    tags_expr = _sql_coalesce_expr(cols, ["tags", "kind", "source"], "''")
    importance_expr = "COALESCE(importance, confidence, weight, 0)" if any(x in cols for x in ["importance", "confidence", "weight"]) else "0"
    time_expr = _sql_time_expr(cols)

    rows = _query_all(
        conn,
        f"""
        SELECT
            id,
            {text_expr} AS text,
            {tags_expr} AS tags,
            {importance_expr} AS importance,
            {time_expr} AS created_at
        FROM memories
        WHERE
            COALESCE(user_id,'') = ?
            AND COALESCE({text_expr}, '') != ''
            AND (
                lower(COALESCE({tags_expr},'')) LIKE '%user_fact%'
                OR lower(COALESCE({tags_expr},'')) LIKE '%preference%'
                OR lower(COALESCE({tags_expr},'')) LIKE '%identity%'
                OR lower(COALESCE({tags_expr},'')) LIKE '%project%'
                OR lower(COALESCE({tags_expr},'')) LIKE '%constraint%'
                OR lower(COALESCE({tags_expr},'')) LIKE '%long_term%'
                OR {importance_expr} >= 0.55
            )
        ORDER BY {importance_expr} DESC, {time_expr} DESC
        LIMIT 300
        """,
        (str(user_id or ""),),
    )

    seen = set()
    for _id, text, tags, importance, created_at in rows:
        text = str(text or "").strip()
        if not text:
            continue
        k = text.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(
            {
                "id": _id,
                "text": text,
                "tags": str(tags or ""),
                "importance": float(importance or 0),
                "created_at": str(created_at or ""),
            }
        )
    return out

def _gather_recent_turns(conn: sqlite3.Connection, user_id: str | None = None) -> List[str]:
    if not _table_exists(conn, "conversation_turns"):
        return []

    cols = _columns(conn, "conversation_turns")
    if "content" not in cols:
        return []

    where = "WHERE COALESCE(content,'') != ''"
    params: list[Any] = []

    if "role" in cols:
        where += " AND LOWER(COALESCE(role,'')) = 'user'"

    if user_id and "user_id" in cols:
        where += " AND COALESCE(user_id,'') = ?"
        params.append(user_id)

    rows = _query_all(
        conn,
        f"""
        SELECT COALESCE(content,'')
        FROM conversation_turns
        {where}
        ORDER BY COALESCE(timestamp, ts, id, 0) DESC
        LIMIT 80
        """,
        tuple(params),
    )
    return [str(txt or "").strip() for (txt,) in rows if str(txt or "").strip()]

def _categorise_semantic(semantic: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    sections = {
        "Identity": [],
        "Communication Preferences": [],
        "Working Style": [],
        "Active Projects": [],
        "Technical Environment": [],
        "Constraints / Avoidances": [],
        "Recent Significant Changes": [],
        "Uncertain / Needs Confirmation": [],
    }
    for item in semantic:
        fact = item["fact"]
        raw_tags = str(item.get("tags") or "")
        if _is_profile_noise(fact, raw_tags):
            continue
        tags = raw_tags.lower()
        conf = item["confidence"]
        if conf < 0.55:
            sections["Uncertain / Needs Confirmation"].append(fact)
            continue
        if any(x in tags for x in ["identity", "name", "alias"]):
            sections["Identity"].append(fact)
        elif any(x in tags for x in ["communication", "tone", "style"]):
            sections["Communication Preferences"].append(fact)
        elif any(x in tags for x in ["workflow", "work_style", "preference"]):
            sections["Working Style"].append(fact)
        elif "project" in tags:
            sections["Active Projects"].append(fact)
        elif any(x in tags for x in ["environment", "system", "runtime", "hardware", "software", "os"]):
            sections["Technical Environment"].append(fact)
        elif any(x in tags for x in ["constraint", "avoid", "dislike"]):
            sections["Constraints / Avoidances"].append(fact)
        else:
            sections["Uncertain / Needs Confirmation"].append(fact)
    return sections

def _categorise_memories(memories: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    sections = {
        "Identity": [],
        "Communication Preferences": [],
        "Working Style": [],
        "Active Projects": [],
        "Technical Environment": [],
        "Constraints / Avoidances": [],
        "Recent Significant Changes": [],
        "Uncertain / Needs Confirmation": [],
    }
    for item in memories:
        text = item["text"]
        raw_tags = str(item.get("tags") or "")
        if _is_profile_noise(text, raw_tags):
            continue
        tags = raw_tags.lower()
        importance = item["importance"]
        if importance < 0.55:
            continue
        if any(x in tags for x in ["identity", "user_fact", "name", "alias"]):
            sections["Identity"].append(text)
        elif any(x in tags for x in ["communication", "tone"]):
            sections["Communication Preferences"].append(text)
        elif any(x in tags for x in ["preference", "workflow", "work_style"]):
            sections["Working Style"].append(text)
        elif "project" in tags:
            sections["Active Projects"].append(text)
        elif any(x in tags for x in ["environment", "runtime", "hardware", "software", "os"]):
            sections["Technical Environment"].append(text)
        elif any(x in tags for x in ["constraint", "avoid", "dislike"]):
            sections["Constraints / Avoidances"].append(text)
        else:
            continue
    return sections

def _merge_sections(a: Dict[str, List[str]], b: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out = {}
    for k in a.keys():
        seen = set()
        vals: List[str] = []
        for source in (a.get(k, []), b.get(k, [])):
            for item in source:
                norm = " ".join(str(item).strip().lower().split())
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                vals.append(str(item).strip())
        out[k] = vals[:40]
    return out

def _recent_deltas_from_turns(turns: List[str]) -> List[str]:
    out = []
    keywords = (
        "prefer", "don't call me", "do not call me", "remember", "going forward",
        "from now on", "project", "working on", "use ", "avoid "
    )
    seen = set()
    for t in turns:
        low = t.lower()
        if any(k in low for k in keywords):
            norm = " ".join(low.split())
            if norm in seen:
                continue
            seen.add(norm)
            out.append(t.strip())
    return out[:12]

def _render_section(title: str, items: List[str]) -> str:
    if not items:
        return f"[{title}]\n- None confirmed.\n"
    return f"[{title}]\n" + "\n".join(f"- {x}" for x in items) + "\n"

def _compute_section_hashes(sections: Dict[str, List[str]]) -> Dict[str, str]:
    return {
        k: hashlib.sha256("\n".join(v).encode("utf-8")).hexdigest()
        for k, v in sections.items()
    }

def _append_diff(changed_sections: List[str], summary: str, reason: str) -> None:
    if not changed_sections:
        return
    row = {
        "ts": _utc_now(),
        "reason": reason,
        "changed_sections": changed_sections,
        "summary": summary,
    }
    p = _paths()["diff"]
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

def _make_summary(changed_sections: List[str]) -> str:
    return "No significant changes." if not changed_sections else "Changed sections: " + ", ".join(changed_sections)

def _is_stale(meta: Dict[str, Any], max_age_seconds: int = DEFAULT_INTERVAL_SECONDS) -> bool:
    ts = str(meta.get("generated_at") or "").strip()
    if not ts:
        return True
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (time.time() - dt.timestamp()) >= max_age_seconds
    except Exception:
        return True

def mark_user_info_dirty(reason: str, details: Dict[str, Any] | None = None) -> None:
    with _LOCK:
        meta = _load_meta()
        meta["dirty"] = True
        reasons = list(meta.get("dirty_reasons") or [])
        reasons.append({"ts": _utc_now(), "reason": reason, "details": details or {}})
        meta["dirty_reasons"] = reasons[-50:]
        _save_meta(meta)

def refresh_user_info(force: bool = False, reason: str = "manual") -> Dict[str, Any]:
    with _LOCK:
        paths = _paths()
        meta = _load_meta()

        if not force and not meta.get("dirty") and not _is_stale(meta, int(meta.get("max_age_seconds", DEFAULT_INTERVAL_SECONDS))):
            txt = paths["txt"].read_text(encoding="utf-8") if paths["txt"].exists() else ""
            return {
                "ok": True,
                "refreshed": False,
                "summary": "User info already fresh.",
                "text_path": str(paths["txt"]),
                "meta_path": str(paths["meta"]),
                "diff_path": str(paths["diff"]),
                "text": txt,
            }

        user_id = _active_user_id()
        semantic = []
        memories = []
        patterns = []
        recent_turns = []
        db = paths["db"]
        if db.exists():
            try:
                conn = sqlite3.connect(str(db))
                semantic = _gather_semantic(conn, user_id=user_id)
                memories = _gather_stable_memories(conn, user_id=user_id)
                patterns = _gather_user_patterns(conn, user_id=user_id)
                recent_turns = _gather_recent_turns(conn, user_id=user_id)
                conn.close()
            except Exception:
                pass

        profile = _read_profile_json()
        sec_sem = _categorise_semantic(semantic)
        sec_mem = _categorise_memories(memories)
        sec_pat = _categorise_memories(patterns)
        sections = _merge_sections(_merge_sections(sec_sem, sec_mem), sec_pat)

        _merge_profile_sections(sections, profile)

        for item in _recent_deltas_from_turns(recent_turns):
            if item not in sections["Recent Significant Changes"]:
                sections["Recent Significant Changes"].append(item)

        for k, vals in list(sections.items()):
            seen = set()
            clean = []
            for v in vals:
                norm = " ".join(str(v).strip().lower().split())
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                clean.append(str(v).strip())
            sections[k] = clean[:40]

        new_hashes = _compute_section_hashes(sections)
        old_hashes = dict(meta.get("section_hashes") or {})
        changed_sections = [k for k, v in new_hashes.items() if old_hashes.get(k) != v]

        generated_at = _utc_now()
        last_sig = meta.get("last_significant_change_at") or generated_at
        if changed_sections:
            last_sig = generated_at

        ordered = [
            "Identity",
            "Communication Preferences",
            "Working Style",
            "Active Projects",
            "Technical Environment",
            "Constraints / Avoidances",
            "Recent Significant Changes",
            "Uncertain / Needs Confirmation",
        ]

        txt = [
            "ELI USER INFO SNAPSHOT",
            f"Active User ID: {user_id or 'unknown'}",
            f"Generated: {generated_at}",
            f"Refresh Reason: {reason}",
            f"Dirty Before Refresh: {'yes' if meta.get('dirty') else 'no'}",
            f"Last Significant Change: {last_sig}",
            "Confidence Mode: controlled synthesis",
            "",
        ]
        for name in ordered:
            txt.append(_render_section(name, sections.get(name, [])))
        final_text = "\n".join(txt).rstrip() + "\n"

        _atomic_write(paths["txt"], final_text)
        summary = _make_summary(changed_sections)
        _append_diff(changed_sections, summary, reason)

        meta.update(
            {
                "generated_at": generated_at,
                "last_significant_change_at": last_sig,
                "dirty": False,
                "dirty_reasons": [],
                "builder_version": 1,
                "max_age_seconds": DEFAULT_INTERVAL_SECONDS,
                "active_user_id": user_id,
                "source_counts": {
                    "semantic": len(semantic),
                    "stable_memories": len(memories),
                    "user_patterns": len(patterns),
                    "recent_turns": len(recent_turns),
                },
                "section_hashes": new_hashes,
                "summary_hash": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
                "last_refresh_reason": reason,
            }
        )
        _save_meta(meta)

        return {
            "ok": True,
            "refreshed": True,
            "summary": summary,
            "changed_sections": changed_sections,
            "text_path": str(paths["txt"]),
            "meta_path": str(paths["meta"]),
            "diff_path": str(paths["diff"]),
            "text": final_text,
        }

def maybe_refresh_user_info(reason: str = "scheduled") -> Dict[str, Any]:
    with _LOCK:
        meta = _load_meta()
        if meta.get("dirty") or _is_stale(meta, int(meta.get("max_age_seconds", DEFAULT_INTERVAL_SECONDS))):
            return refresh_user_info(force=False, reason=reason)
        txt = _paths()["txt"].read_text(encoding="utf-8") if _paths()["txt"].exists() else ""
        return {"ok": True, "refreshed": False, "summary": "No refresh needed.", "text": txt}

def read_user_info(auto_refresh: bool = True, reason: str = "query") -> Dict[str, Any]:
    with _LOCK:
        meta = _load_meta()
        paths = _paths()
        if auto_refresh:
            if (not paths["txt"].exists()) or _is_stale(meta, QUERY_MAX_AGE_SECONDS) or bool(meta.get("dirty")):
                refresh_user_info(force=False, reason=reason)
                meta = _load_meta()
        txt = paths["txt"].read_text(encoding="utf-8") if paths["txt"].exists() else ""
        return {"ok": True, "text": txt, "meta": meta, "path": str(paths["txt"])}

def _bg_loop(interval_seconds: int) -> None:
    while True:
        try:
            maybe_refresh_user_info(reason="scheduled")
        except Exception:
            pass
        time.sleep(max(60, int(interval_seconds)))

def ensure_user_info_background_updater(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    global _BG_THREAD, _BG_STARTED
    with _LOCK:
        if _BG_STARTED:
            return
        _BG_STARTED = True
        _BG_THREAD = threading.Thread(
            target=_bg_loop,
            args=(int(interval_seconds),),
            name="eli-user-info-updater",
            daemon=True,
        )
        _BG_THREAD.start()

def register_user_info_exit_flush() -> None:
    def _flush() -> None:
        try:
            refresh_user_info(force=True, reason="process_exit")
        except Exception:
            pass
    atexit.register(_flush)
