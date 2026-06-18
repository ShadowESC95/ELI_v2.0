"""Light, skippable first-run onboarding interview.

On a blank-slate user (no name, no User Model), ELI runs a short 3-question baseline —
name → role/work → answer style — driven through `engine.process` so it works in BOTH the
GUI and headless. Answers seed the existing stores (`set_user_name` + `user_patterns`),
which flow automatically into the continuous User Model, persona, KG, and cognition.

NON-BLOCKING + SKIPPABLE: a substantive first message (a real task/question) passes straight
through to normal processing (the persona-handoff nudge then learns the baseline organically);
the explicit interview only engages on a light opener, and "skip"/"later" ends it at any step.
State lives in `artifacts/onboarding_state.json` (mirrors `pending_habit.json`). Fully local.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

_STEPS = ("name", "role", "style")
_SKIP_WORDS = ("skip", "later", "skip onboarding", "no thanks", "not now", "maybe later")
_STATE_TTL = 7 * 24 * 3600  # a week — fine to resume; cleared on finish/skip


def _artifacts_dir() -> Path:
    try:
        from eli.core.paths import get_paths
        d = Path(get_paths().artifacts_dir)
    except Exception:
        d = Path("artifacts")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file() -> Path:
    return _artifacts_dir() / "onboarding_state.json"


# --------------------------------------------------------------------------- #
# State                                                                       #
# --------------------------------------------------------------------------- #
def get_onboarding_state() -> Optional[Dict[str, Any]]:
    p = _state_file()
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if time.time() - float(d.get("created_at", 0)) > _STATE_TTL:
        clear_onboarding_state()
        return None
    return d


def _set_onboarding_state(step: str, data: Optional[Dict[str, Any]] = None) -> None:
    cur = get_onboarding_state() or {"created_at": time.time(), "answers": {}}
    cur["step"] = step
    cur["status"] = "active"
    if data:
        cur.setdefault("answers", {}).update(data)
    _state_file().write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_onboarding_state() -> None:
    try:
        _state_file().unlink()
    except FileNotFoundError:
        pass


def is_onboarding_active() -> bool:
    st = get_onboarding_state()
    return bool(st and st.get("status") == "active")


# --------------------------------------------------------------------------- #
# Blank-slate detection + opener heuristic                                    #
# --------------------------------------------------------------------------- #
def _count(db_path, table: str) -> int:
    try:
        con = sqlite3.connect(str(db_path))
        try:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            con.close()
    except Exception:
        return 0  # table missing → 0


def _is_blank_slate(db_path=None) -> bool:
    """Truly brand-new install: no User Model AND no prior conversation AND no stored
    memories. Strict on purpose — a user who already has any history is NOT onboarded
    (and existing tests with seeded data never trip the interview)."""
    try:
        from eli.runtime import user_model as um
        if um.read_user_model(db_path=db_path).get("is_seeded"):
            return False
        p = um._db_path(db_path)
        if _count(p, "conversation_turns") > 0 or _count(p, "memories") > 0:
            return False
        return True
    except Exception:
        return False


def _looks_substantive(text: str) -> bool:
    """A real task/question — should pass through, not trigger the interview."""
    t = (text or "").strip().lower()
    if len(t) > 60:
        return True
    _verbs = ("fix", "open", "run", "write", "show", "list", "search", "play", "create",
              "explain", "summar", "code", "debug", "install", "download", "set ", "make",
              "build", "find", "read", "delete", "remove", "add ", "generate", "help me")
    return any(t.startswith(v) or f" {v}" in t for v in _verbs)


# --------------------------------------------------------------------------- #
# Question script                                                             #
# --------------------------------------------------------------------------- #
def _question(step: str, answers: Dict[str, Any]) -> str:
    name = answers.get("name", "")
    if step == "name":
        return ("First time here, so I don't know you yet — quick baseline and then I'm out of "
                "your way. What should I call you?  (or say 'skip' and just ask me anything)")
    if step == "role":
        return f"Good to meet you, {name}. What do you mostly work on?"
    if step == "style":
        return "Noted. Default answer style — terse and direct, or full detail?"
    return ""


def _apply_answer(step: str, text: str, db_path=None) -> None:
    text = (text or "").strip()
    if not text:
        return
    if step == "name":
        nm = text
        for lead in ("my name is ", "i'm ", "i am ", "call me ", "it's ", "name's "):
            if nm.lower().startswith(lead):
                nm = nm[len(lead):]
        nm = nm.strip().strip(".!,").split("\n")[0][:40]
        try:
            from eli.kernel.state import set_user_name
            set_user_name(nm)
        except Exception:
            pass
        return
    # role / style → user_patterns (reuse the canonical writer)
    try:
        import sqlite3
        from eli.runtime.profile_extractor import _insert_user_pattern, ensure_profile_tables, _user_db
        db = Path(db_path) if db_path else _user_db()
        ensure_profile_tables(db)
        con = sqlite3.connect(str(db))
        cur = con.cursor()
        if step == "role":
            _insert_user_pattern(cur, "identity.role", f"User's work/role: {text[:200]}")
        elif step == "style":
            _insert_user_pattern(cur, "preference.style", f"User prefers {text[:120]} answers by default.")
        con.commit()
        con.close()
    except Exception:
        pass


def _finish(db_path=None) -> str:
    clear_onboarding_state()
    try:
        from eli.runtime.user_model import refresh_user_model_brief
        refresh_user_model_brief(db_path=db_path)
    except Exception:
        pass
    return ("Set — I've got a baseline. I'll fill in the rest as we go; tell me anything to "
            "remember at any time. What can I do for you?")


# --------------------------------------------------------------------------- #
# The engine intercept                                                        #
# --------------------------------------------------------------------------- #
def onboarding_intercept(user_input: str, user_id: Optional[str] = None, db_path=None) -> Optional[str]:
    """Return ELI's onboarding message if this turn is part of onboarding, else None
    (normal processing continues). Safe to call every turn — cheap and self-gating."""
    text = (user_input or "").strip()

    if is_onboarding_active():
        st = get_onboarding_state() or {}
        step = st.get("step", "name")
        answers = st.get("answers", {})
        if text.lower() in _SKIP_WORDS:
            clear_onboarding_state()
            return "No problem — I'll pick it up as we go. Ask me anything."
        # store this answer, advance
        _apply_answer(step, text, db_path=db_path)
        answers[step] = text if step != "name" else text
        idx = _STEPS.index(step) if step in _STEPS else 0
        if idx + 1 < len(_STEPS):
            nxt = _STEPS[idx + 1]
            # remember the name for later question phrasing
            if step == "name":
                answers["name"] = answers.get("name", text).strip().strip(".!,")[:40]
            _set_onboarding_state(nxt, {step: text, "name": answers.get("name", "")})
            return _question(nxt, answers)
        return _finish(db_path=db_path)

    # Not active — only begin on a true blank slate AND a light opener (never hijack a task).
    if _is_blank_slate(db_path=db_path) and not _looks_substantive(text):
        _set_onboarding_state("name", {})
        return _question("name", {})
    return None
