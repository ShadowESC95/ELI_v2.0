"""Continuous User Model — ELI's living, semantic, auto-updating model of the user.

ONE canonical door every consumer reads through (cognition, persona, proactive,
reflection, awareness). Three tiers:
  * EVIDENCE  — user_patterns / memories / session_summaries / KG (existing, unchanged).
  * SYNTHESIS — the `user_model` table (one row per user_id): structured JSON columns +
                a free-text `dossier` (LLM narrative) + a pre-rendered `brief` for a fast
                per-turn direct read.
  * READ      — get_user_brief() (fast SELECT, the per-turn block) and read_user_model()
                (full structured model).

Fully local: synthesis uses the already-resident GGUF broker with a "return '' on any
failure → heuristic" guard. User-scoped by user_id (never a flat file) so one user's
model never bleeds into another's. Model/user/hardware-agnostic.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Pattern-prefix → structured column. user_patterns is the evidence; this groups it.
_PREFIX_TO_COL = {
    "identity": "identity",
    "preference": "comms_style",
    "project": "current_focus",
    "research": "current_focus",
    "interest": "interests",
    "goal": "goals",
    "habit": "habits",
}
_COLS = ("identity", "comms_style", "current_focus", "interests", "habits", "goals", "relationship")

# Single source of the onboarding nudge (was inlined in context_synthesiser.py).
ONBOARDING_NUDGE = (
    "ONBOARDING: You do not know this user yet — no profile is stored. Naturally work a "
    "brief, conversational baseline into your reply (their name, then what they work on and "
    "how they like answers — terse vs detailed). Keep it light, one or two questions at a "
    "time, not a form. The user can say 'skip' anytime. Do this until a profile exists."
)


# --------------------------------------------------------------------------- #
# Paths / identity                                                            #
# --------------------------------------------------------------------------- #
def _db_path(db_path: Optional[Path | str] = None) -> Path:
    if db_path:
        return Path(db_path)
    try:
        from eli.core.paths import user_db_path
        return Path(user_db_path())
    except Exception:
        from eli.runtime.profile_extractor import _user_db
        return _user_db()


def _resolve_user_id(user_id: Optional[str] = None) -> str:
    if user_id:
        return str(user_id)
    try:
        from eli.core.paths import get_paths
        f = get_paths().config_dir / "user_id"
        if f.exists():
            return f.read_text(encoding="utf-8", errors="ignore").strip() or "default"
    except Exception:
        pass
    return "default"


def _get_name(user_id: Optional[str] = None) -> str:
    try:
        from eli.kernel.state import get_user_name
        return (get_user_name("", user_id=user_id) or "").strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Evidence: group user_patterns by structured column                          #
# --------------------------------------------------------------------------- #
def _read_patterns_grouped(db_path: Optional[Path | str] = None) -> Dict[str, List[str]]:
    """Return {column: [pattern_data, ...]} from user_patterns (most-recent first)."""
    out: Dict[str, List[str]] = {c: [] for c in _COLS}
    try:
        con = sqlite3.connect(str(_db_path(db_path)))
        try:
            rows = con.execute(
                "SELECT pattern_type, pattern_data FROM user_patterns "
                "ORDER BY COALESCE(timestamp, ts, 0) DESC"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return out
    seen = set()
    for ptype, pdata in rows:
        pfx = str(ptype or "").split(".", 1)[0].lower()
        col = _PREFIX_TO_COL.get(pfx)
        data = (pdata or "").strip()
        if not col or not data:
            continue
        key = (col, data.lower())
        if key in seen:
            continue
        seen.add(key)
        out[col].append(data)
    return out


# --------------------------------------------------------------------------- #
# Render the fast per-turn brief                                              #
# --------------------------------------------------------------------------- #
def _join(items: List[str], n: int = 4) -> str:
    return "; ".join(s.rstrip(". ") for s in items[:n] if s and s.strip())


def render_brief(name: str, grouped: Dict[str, List[str]], dossier: str = "") -> str:
    lines: List[str] = []
    head = f"USER MODEL: {name}" if name else "USER MODEL: (name not yet known)"
    ident = _join(grouped.get("identity", []))
    # comms_style aggregates EVERY preference.* signal (learned tone/humor/depth +
    # explicit style/persona/commands). The default n=4 silently dropped the
    # overflow — so learned tone could be evicted from the per-turn brief by newer
    # preferences. These are the voice directives; render them all (generous cap).
    style = _join(grouped.get("comms_style", []), n=12)
    bits = [b for b in (ident, style) if b]
    lines.append(head + (" — " + " ".join(bits) if bits else ""))
    focus = _join(grouped.get("current_focus", []))
    interests = _join(grouped.get("interests", []))
    if focus:
        lines.append(f"Currently focused on: {focus}.")
    if interests:
        lines.append(f"Interests: {interests}.")
    goals = _join(grouped.get("goals", []))
    if goals:
        lines.append(f"Goals: {goals}.")
    rel = _join(grouped.get("relationship", []), 2)
    if rel:
        lines.append(f"Rapport: {rel}.")
    if dossier:
        lines.append(dossier.strip().split("\n")[0][:300])
    return "\n".join(l for l in lines if l).strip()


# --------------------------------------------------------------------------- #
# Store helpers                                                               #
# --------------------------------------------------------------------------- #
def ensure_user_model_row(user_id: Optional[str] = None, db_path: Optional[Path | str] = None) -> None:
    uid = _resolve_user_id(user_id)
    try:
        from eli.runtime.profile_extractor import ensure_profile_tables
        ensure_profile_tables(_db_path(db_path))
        con = sqlite3.connect(str(_db_path(db_path)))
        try:
            con.execute("INSERT OR IGNORE INTO user_model(user_id, ts) VALUES(?,?)", (uid, time.time()))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def _read_row(uid: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    try:
        con = sqlite3.connect(str(_db_path(db_path)))
        con.row_factory = sqlite3.Row
        try:
            r = con.execute("SELECT * FROM user_model WHERE user_id=?", (uid,)).fetchone()
        finally:
            con.close()
        return dict(r) if r else None
    except Exception:
        return None


def _loads(v) -> Any:
    try:
        return json.loads(v) if v else None
    except Exception:
        return v


# --------------------------------------------------------------------------- #
# Public reads                                                                #
# --------------------------------------------------------------------------- #
def read_user_model(user_id: Optional[str] = None, db_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Full structured model. Falls back to assembling from user_patterns + name when no
    synthesized row exists yet (blank slate / pre-first-synthesis)."""
    uid = _resolve_user_id(user_id)
    name = _get_name(user_id)
    row = _read_row(uid, db_path)
    if row and (row.get("brief") or row.get("dossier")):
        model = {c: _loads(row.get(c)) for c in _COLS}
        model.update({
            "user_id": uid, "name": name,
            "dossier": row.get("dossier") or "", "brief": row.get("brief") or "",
            "confidence": row.get("confidence") or 0.0, "updated_at": row.get("updated_at") or 0.0,
            "is_seeded": True,
        })
        return model
    grouped = _read_patterns_grouped(db_path)
    return {
        "user_id": uid, "name": name,
        "identity": grouped["identity"], "comms_style": grouped["comms_style"],
        "current_focus": grouped["current_focus"], "interests": grouped["interests"],
        "habits": grouped["habits"], "goals": grouped["goals"], "relationship": grouped["relationship"],
        "dossier": "", "brief": "", "confidence": 0.0, "updated_at": 0.0,
        "is_seeded": bool(name or any(grouped[c] for c in _COLS)),
    }


def get_user_brief(user_id: Optional[str] = None, turn_count: int = 0,
                   db_path: Optional[Path | str] = None) -> str:
    """The fast per-turn block. One `SELECT brief` when synthesized; otherwise assembles a
    minimal brief from patterns + name; returns the onboarding nudge on a true blank slate
    (no name AND no patterns) within the first few turns."""
    uid = _resolve_user_id(user_id)
    row = _read_row(uid, db_path)
    if row and (row.get("brief") or "").strip():
        return row["brief"].strip()
    name = _get_name(user_id)
    grouped = _read_patterns_grouped(db_path)
    has_evidence = bool(name or any(grouped[c] for c in _COLS))
    if not has_evidence:
        return ONBOARDING_NUDGE if int(turn_count) <= 4 else ""
    return render_brief(name, grouped)


# --------------------------------------------------------------------------- #
# Updates                                                                     #
# --------------------------------------------------------------------------- #
def refresh_user_model_brief(memory: Any = None, user_id: Optional[str] = None,
                             db_path: Optional[Path | str] = None) -> str:
    """Cheap, non-LLM: re-render the structured columns + brief from current user_patterns
    + name. Keeps the per-turn read fresh between full LLM syntheses. Returns the brief."""
    uid = _resolve_user_id(user_id)
    name = _get_name(user_id)
    grouped = _read_patterns_grouped(db_path)
    if not (name or any(grouped[c] for c in _COLS)):
        return ""
    row = _read_row(uid, db_path)
    dossier = (row or {}).get("dossier") or ""
    brief = render_brief(name, grouped, dossier)
    _upsert(uid, grouped, dossier, brief, db_path, confidence=(row or {}).get("confidence") or 0.4)
    return brief


def synthesize_user_model(memory: Any = None, user_id: Optional[str] = None,
                          session_summary: str = "", db_path: Optional[Path | str] = None,
                          broker: Any = None) -> bool:
    """Consolidate user_patterns + the latest session summary into the dossier (LLM) and
    re-render the structured columns + brief. LLM writes ONLY the narrative dossier; the
    structured columns + brief are deterministic from patterns, so a failed/absent model
    degrades to the heuristic brief. Fully local; returns True if a row was written."""
    uid = _resolve_user_id(user_id)
    name = _get_name(user_id)
    grouped = _read_patterns_grouped(db_path)
    if not (name or any(grouped[c] for c in _COLS)):
        return False

    dossier = ""
    try:
        b = broker
        if b is None:
            from eli.cognition.inference_broker import get_inference_broker
            b = get_inference_broker()
        if b is not None and getattr(b, "gguf_ready", True):
            facts = []
            if name:
                facts.append(f"Name: {name}")
            for col in _COLS:
                if grouped.get(col):
                    facts.append(f"{col.replace('_', ' ')}: {_join(grouped[col], 6)}")
            if session_summary:
                facts.append(f"Latest session: {session_summary[:600]}")
            prompt = (
                "Write ONE tight paragraph (3-4 sentences, no preamble, no lists) describing this "
                "user as a working model — who they are, how they like to work and be spoken to, what "
                "they're focused on, and the rapport. Plain, specific, no flattery.\n\n"
                + "\n".join(facts)
            )
            out = b.infer(prompt, system="", max_tokens=220, temperature=0.4, background=True)
            dossier = (out or "").strip()
    except Exception:
        dossier = ""

    if not dossier:  # heuristic fallback — never block on the LLM
        parts = [p for p in (_join(grouped["identity"]), _join(grouped["comms_style"]),
                             _join(grouped["current_focus"])) if p]
        dossier = (f"{name + ': ' if name else ''}" + ". ".join(parts)).strip()

    brief = render_brief(name, grouped, dossier)
    _upsert(uid, grouped, dossier, brief, db_path, confidence=0.7)
    return True


def _upsert(uid: str, grouped: Dict[str, List[str]], dossier: str, brief: str,
            db_path: Optional[Path | str], confidence: float = 0.5) -> None:
    try:
        from eli.runtime.profile_extractor import ensure_profile_tables
        ensure_profile_tables(_db_path(db_path))
        now = time.time()
        con = sqlite3.connect(str(_db_path(db_path)))
        try:
            con.execute(
                """
                INSERT INTO user_model
                  (user_id, identity, comms_style, current_focus, interests, habits, goals,
                   relationship, dossier, brief, sources, confidence, updated_at, ts)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                  identity=excluded.identity, comms_style=excluded.comms_style,
                  current_focus=excluded.current_focus, interests=excluded.interests,
                  habits=excluded.habits, goals=excluded.goals, relationship=excluded.relationship,
                  dossier=excluded.dossier, brief=excluded.brief, sources=excluded.sources,
                  confidence=excluded.confidence, updated_at=excluded.updated_at, ts=excluded.ts
                """,
                (uid, json.dumps(grouped["identity"]), json.dumps(grouped["comms_style"]),
                 json.dumps(grouped["current_focus"]), json.dumps(grouped["interests"]),
                 json.dumps(grouped["habits"]), json.dumps(grouped["goals"]),
                 json.dumps(grouped["relationship"]), dossier, brief, "user_patterns",
                 float(confidence), now, now),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
