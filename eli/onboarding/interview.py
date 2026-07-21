"""Light, skippable first-run onboarding interview.

On a blank-slate user (no name, no User Model), ELI runs a short baseline —
name → role → answer style → primary focus — driven through `engine.process` so it
works in BOTH the GUI and headless. Pick A–D / 1–4 or type your own answer; results
seed `set_user_name` + `user_patterns` and a one-paragraph baseline report, which
flow into the continuous User Model, persona, KG, and cognition.

NON-BLOCKING + SKIPPABLE: a substantive first message (a real task/question) passes
straight through to normal processing; the explicit interview only engages on a light
opener or when the user asks for profile setup. "skip"/"later" ends it at any step.
State lives in `artifacts/onboarding_state.json`. Fully local.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

_STEPS = ("name", "role", "style", "focus")
_SKIP_WORDS = ("skip", "later", "skip onboarding", "no thanks", "not now", "maybe later")
_STATE_TTL = 7 * 24 * 3600  # a week — fine to resume; cleared on finish/skip

_ROLE_OPTIONS = {
    "a": "Software / tech",
    "b": "Research / science",
    "c": "Creative / writing",
    "d": "Business / ops / admin",
    "e": "Other (user described)",
}

_STYLE_OPTIONS = {
    "1": "Just the answer — quick and to the point",
    "2": "Balanced — the answer with a little context",
    "3": "Thorough — walk me through the reasoning",
    "4": "Collaborative — think it through with me and ask me things back",
}

_FOCUS_OPTIONS = {
    "a": "Coding and debugging",
    "b": "Research and learning",
    "c": "Everyday assistant (notes, files, media)",
    "d": "Mix of everything",
}


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
def _profile_missing(db_path=None) -> bool:
    """True when no structured user profile exists yet (name + patterns)."""
    try:
        from eli.runtime import user_model as um
        model = um.read_user_model(db_path=db_path)
        if model.get("is_seeded"):
            return False
        grouped = um._read_patterns_grouped(db_path)
        name = um._get_name()
        return not (name or any(grouped[c] for c in um._COLS))
    except Exception:
        return False


def _is_blank_slate(db_path=None) -> bool:
    """Brand-new user profile — ignore stray session memories from a first greeting."""
    return _profile_missing(db_path=db_path)


def _looks_substantive(text: str) -> bool:
    """A real task/question — should pass through, not trigger the interview."""
    t = (text or "").strip().lower()
    if len(t) > 60:
        return True
    _verbs = ("fix", "open", "run", "write", "show", "list", "search", "play", "create",
              "explain", "summar", "code", "debug", "install", "download", "set ", "make",
              "build", "find", "read", "delete", "remove", "add ", "generate", "help me")
    return any(t.startswith(v) or f" {v}" in t for v in _verbs)


def _is_onboarding_meta_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    phrases = (
        "initial question",
        "question set",
        "onboarding",
        "baseline profile",
        "build a report",
        "get to know me",
        "know about me",
        "user report",
        "profile setup",
        "setup questions",
        "baseline eli",
    )
    return any(p in t for p in phrases)


def _is_not_an_answer(text: str) -> bool:
    """True when the user typed a question or command instead of answering the interview."""
    if _is_onboarding_meta_question(text):
        return False
    t = (text or "").strip().lower()
    if not t:
        return True
    if t.endswith("?"):
        return True
    first = t.split()[0]
    _q = ("what", "why", "how", "when", "where", "who", "which", "do", "does", "can",
          "are", "will", "could", "would", "is", "tell", "give", "show", "list")
    _cmd = ("fix", "open", "run", "write", "search", "play", "create", "explain",
            "summarise", "summarize", "code", "debug", "install", "download", "make",
            "build", "find", "read", "delete", "remove", "generate")
    return first in _q or first in _cmd


def _resolve_mc_choice(text: str, options: Dict[str, str]) -> str:
    """Map A/B/1/2 or free text to a canonical option label."""
    raw = (text or "").strip()
    if not raw:
        return raw
    t = raw.lower()
    if t in options:
        return options[t]
    m = re.match(r"^([a-e1-4])[\).\]:]?\s*(.*)$", t)
    if m and m.group(1) in options:
        tail = (m.group(2) or "").strip()
        if tail and m.group(1) == "e":
            return tail[:200]
        return options[m.group(1)]
    for key, label in options.items():
        if label.lower() in t or t == label.lower():
            return label
    # fuzzy: map how-they-describe-it to the closest interaction style
    if options is _STYLE_OPTIONS:
        if any(w in t for w in ("terse", "direct", "short", "just the answer", "quick", "brief", "concise")):
            return options["1"]
        if any(w in t for w in ("collaborat", "think it through", "ask me", "ask back", "back and forth", "together", "conversation")):
            return options["4"]
        if any(w in t for w in ("detail", "thorough", "walk", "reasoning", "explain", "tutorial", "step by step")):
            return options["3"]
        if "balanc" in t:
            return options["2"]
    return raw[:200]


def _format_options(options: Dict[str, str]) -> str:
    lines = []
    for key, label in options.items():
        lines.append(f"  {key.upper()}) {label}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Question script                                                             #
# --------------------------------------------------------------------------- #
def _short(val: str) -> str:
    """A tidy, lowercase fragment of a stored answer, safe to drop inline into the
    next question so the interview references what the user just said."""
    s = (val or "").strip().rstrip(".")
    s = re.sub(r"\s*\(user described\)\s*$", "", s, flags=re.I)
    return s[:48]


# What each step is really asking about + the answer scaffold (options + how to answer).
_STEP_TOPIC = {
    "name": "what they'd like you to call them",
    "role": "what they mostly work on or spend their days doing",
    "style": "how they like to be worked with — the answer style and back-and-forth they prefer",
    "focus": "what they most want you (ELI) around for",
}
_STEP_SCAFFOLD = {
    "role": (_ROLE_OPTIONS, "Pick a letter, or just tell me in your own words."),
    "style": (_STYLE_OPTIONS, "Pick a number, or describe the kind of back-and-forth you enjoy."),
    "focus": (_FOCUS_OPTIONS, "A–D, or tell me what you're hoping I'll take off your plate."),
}


def _known_facts(answers: Dict[str, Any]) -> str:
    bits = []
    if answers.get("name"):  bits.append(f"they're called {answers['name']}")
    if answers.get("role"):  bits.append(f"they work on {_short(answers['role'])}")
    if answers.get("style"): bits.append(f"they like answers that are {_short(answers['style'])}")
    return "; ".join(bits) if bits else "nothing yet — this is the very first thing"


def _unwrap_generate(out: Any) -> str:
    """generate() returns a dict ({'response': ...}); older paths may return a string or a
    llama.cpp choices dict. Pull the text out of whatever shape we get."""
    if isinstance(out, dict):
        return str(
            out.get("response") or out.get("text") or out.get("content")
            or (out.get("choices", [{}])[0].get("text", "") if out.get("choices") else "")
            or ""
        )
    return str(out or "")


def _gpu_offload_active() -> bool:
    """True when the local model is actually offloading layers to a GPU — the only
    case where generating a question per step is fast. On CPU-only, each generation
    took 1-4 min on a first-run (observed on Arch), a brutal onboarding, so the
    interview falls back to instant scripted questions there."""
    try:
        from eli.cognition import gguf_inference as _llm
        ovr = _llm.get_live_runtime_override() or {}
        return int(ovr.get("n_gpu_layers") or ovr.get("gpu_layers") or 0) > 0
    except Exception:
        return False


def _llm_question(step: str, answers: Dict[str, Any]) -> Optional[str]:
    """Generate the next onboarding question with the LOCAL model, so the interview is a
    real, adaptive conversation — ELI examines what it already knows and asks the single
    most useful, *specific* next question rather than reading a fixed script with fixed
    options. Returns None on any problem so the caller falls back to the scripted question."""
    topic = _STEP_TOPIC.get(step)
    if not topic:
        return None
    # Skip the (slow) per-step LLM generation on CPU-only hardware so the first-run
    # interview stays snappy; the scripted questions below are the instant fallback.
    # Force adaptive questions regardless with ELI_ONBOARDING_LLM=1.
    if os.environ.get("ELI_ONBOARDING_LLM", "").strip().lower() not in ("1", "true", "yes", "on") \
            and not _gpu_offload_active():
        return None
    try:
        from eli.cognition import gguf_inference as _llm
        sys_p = (
            "You are ELI, a local AI assistant meeting a new user and genuinely getting to "
            "know them. Examine what you already know, then ask the SINGLE most useful, "
            "SPECIFIC next question about the given topic — tailored to them and building on "
            "their prior answers (e.g. if they said 'research', ask what field or what they're "
            "working on lately). One short, warm question (1-2 sentences). Do NOT list "
            "letter/number options, do NOT answer for them, do NOT add anything after the "
            "question. Output only the question."
        )
        extra = ("This is the opener — warmly say you'd like to get to know them so you can be "
                 "their ELI, and gently mention they can say 'skip' anytime."
                 if step == "name" else "")
        usr_p = f"What you know so far: {_known_facts(answers)}. Now ask about: {topic}. {extra}".strip()
        out = _unwrap_generate(_llm.generate(sys_p, usr_p, max_tokens=90, temperature=0.8))
        q = out.strip().strip('"').split("\n\n")[0].strip()
        # Reject junk: empty/too short/long, leaked options, or template markers.
        if not q or len(q) < 12 or len(q) > 400:
            return None
        if any(m in q for m in ("A)", "B)", "1)", "2)", "<|", "•", "```")):
            return None
        return q
    except Exception:
        return None


def _question(step: str, answers: Dict[str, Any]) -> str:
    """The next question — LLM-generated (dynamic, plays off prior answers), with the
    scripted version below as a reliable fallback when the model isn't available."""
    dynamic = _llm_question(step, answers)
    if dynamic:
        return dynamic
    return _scripted_question(step, answers)


def _scripted_question(step: str, answers: Dict[str, Any]) -> str:
    """Deterministic fallback questions (used when the local model can't generate one)."""
    name = (answers.get("name") or "").strip()
    if step == "name":
        return (
            "Before we get into anything — I'd genuinely like to know who I'm working with. "
            "The more I understand you, the more I can be *your* ELI instead of a generic "
            "assistant, and I'll keep learning as we go. Just a couple of quick things, and "
            "skip anything you'd rather not answer (say 'skip' anytime).\n\n"
            "So, to start with — what should I call you?"
        )
    if step == "role":
        hi = f"{name} — good to meet you properly." if name else "Good to meet you."
        return (
            f"{hi} I'm curious what your days actually look like, so I can shape myself "
            "around them — what do you mostly work on?\n"
            f"{_format_options(_ROLE_OPTIONS)}\n"
            "Pick a letter, or just tell me in your own words — I'd rather hear it how you'd say it."
        )
    if step == "style":
        role = _short(answers.get("role", ""))
        lead = (
            f"{role.capitalize()} — that tells me a lot about how to be useful to you."
            if role and len(role) <= 32 else
            "Good — that helps me picture how to be useful to you."
        )
        return (
            f"{lead} Now the part I really care about: how do you actually like to be "
            "worked with? When I answer you, what feels right?\n"
            f"{_format_options(_STYLE_OPTIONS)}\n"
            "Pick a number, or just describe the kind of back-and-forth you enjoy — some people "
            "want me to get straight to it, others like me to think out loud and ask questions back."
        )
    if step == "focus":
        whom = f", {name}" if name else ""
        role = _short(answers.get("role", ""))
        ask = (
            f"Given you're into {role}, what do you most want me around for?"
            if role and len(role) <= 32 else
            "What do you most want me around for?"
        )
        return (
            f"Last one{whom}, then I'll get out of your way and we can actually start.\n"
            f"{ask}\n"
            f"{_format_options(_FOCUS_OPTIONS)}\n"
            "A–D, or tell me what you're hoping I'll take off your plate."
        )
    return ""


_GREETING_WORDS = (
    "good morning", "good afternoon", "good evening", "good day",
    "hello there", "hey there", "hi there", "howdy", "greetings",
    "hello", "hiya", "heya", "hey", "hi", "yo", "morning", "afternoon", "evening",
)


def _extract_name(text: str) -> str:
    """Pull a usable name out of a name-step reply, tolerant of greetings and
    self-introductions: 'Hi, I'm Keith' -> 'Keith', 'call me Sam' -> 'Sam'. A bare
    greeting with no actual name ('Hello and Good Morning') -> '' so the caller
    re-asks rather than storing the greeting AS the name — the reported skip where
    a longer greeting got captured as the user's name."""
    s = (text or "").strip()
    if not s:
        return ""
    # Peel any number of leading greeting tokens + joiners ("hello and good morning").
    changed = True
    while changed and s:
        changed = False
        low = s.lower()
        for g in sorted(_GREETING_WORDS, key=len, reverse=True):
            if low.startswith(g) and (len(low) == len(g) or not low[len(g)].isalpha()):
                s = s[len(g):].lstrip(" ,.!-–—&").lstrip()
                for j in ("and ", "& "):
                    if s.lower().startswith(j):
                        s = s[len(j):].lstrip()
                changed = True
                break
    # Strip an explicit self-introduction lead.
    low = s.lower()
    for lead in ("my name is ", "i'm ", "i am ", "call me ", "it's ", "name's ",
                 "the name's ", "this is "):
        if low.startswith(lead):
            s = s[len(lead):]
            break
    s = s.strip().strip(".!,").split("\n")[0].strip()
    if not s or len(s.split()) > 4:   # empty (pure greeting) or a full sentence, not a name
        return ""
    return s[:40]


def _apply_answer(step: str, text: str, db_path=None) -> str:
    """Persist one answer; return the canonical value stored."""
    text = (text or "").strip()
    if not text:
        return ""
    if step == "name":
        nm = _extract_name(text)
        if not nm:
            return ""   # greeting / no real name — caller re-asks instead of storing it
        try:
            from eli.kernel.state import set_user_name
            set_user_name(nm)
        except Exception:
            pass
        return nm
    if _is_not_an_answer(text):
        return ""
    if step == "role":
        canonical = _resolve_mc_choice(text, _ROLE_OPTIONS)
    elif step == "style":
        canonical = _resolve_mc_choice(text, _STYLE_OPTIONS)
    elif step == "focus":
        canonical = _resolve_mc_choice(text, _FOCUS_OPTIONS)
    else:
        canonical = text[:200]
    try:
        from eli.runtime.profile_extractor import _insert_user_pattern, ensure_profile_tables, _user_db
        db = Path(db_path) if db_path else _user_db()
        ensure_profile_tables(db)
        con = sqlite3.connect(str(db))
        cur = con.cursor()
        if step == "role":
            _insert_user_pattern(cur, "identity.role", f"User's work/role: {canonical[:200]}")
        elif step == "style":
            _insert_user_pattern(cur, "preference.style", f"User prefers {canonical[:120]} answers by default.")
        elif step == "focus":
            _insert_user_pattern(cur, "goal.primary", f"User wants ELI mainly for: {canonical[:200]}.")
        con.commit()
        con.close()
    except Exception:
        pass
    return canonical


def _baseline_report(answers: Dict[str, Any]) -> str:
    name = (answers.get("name") or "").strip() or "(not set)"
    role = (answers.get("role") or "").strip() or "(not set)"
    style = (answers.get("style") or "").strip() or "(not set)"
    focus = (answers.get("focus") or "").strip() or "(not set)"
    opener = f"Thanks, {name} — here's what I've picked up so far:" if name and name != "(not set)" \
        else "Thanks — here's what I've picked up so far:"
    return (
        f"{opener}\n\n"
        f"• I'll call you: {name}\n"
        f"• You work on: {role}\n"
        f"• You like me to be: {style}\n"
        f"• You mostly want me for: {focus}\n\n"
        "That's just my starting read on you and it'll keep evolving the more we talk — "
        "so correct me any time and I'll adjust. Now, what's on your mind?"
    )


def _store_baseline_memory(answers: Dict[str, Any], db_path=None) -> None:
    try:
        from eli.memory.memory import get_memory
        mem = get_memory()
        parts = []
        if answers.get("name"):
            parts.append(f"User's preferred name is {answers['name']}.")
        if answers.get("role"):
            parts.append(f"User's work/role: {answers['role']}.")
        if answers.get("style"):
            parts.append(f"User prefers {answers['style']} answers by default.")
        if answers.get("focus"):
            parts.append(f"User wants ELI mainly for: {answers['focus']}.")
        if not parts:
            return
        text = " ".join(parts)
        mem.store_memory(
            text,
            tags=["user", "baseline", "onboarding"],
            source="onboarding_interview",
            kind="identity",
            importance=0.9,
        )
    except Exception:
        pass


def _finish(db_path=None) -> str:
    st = get_onboarding_state() or {}
    answers = dict(st.get("answers") or {})
    clear_onboarding_state()
    try:
        from eli.runtime.user_model import refresh_user_model_brief
        refresh_user_model_brief(db_path=db_path)
    except Exception:
        pass
    _store_baseline_memory(answers, db_path=db_path)
    return _baseline_report(answers)


def _begin_or_resume(db_path=None) -> str:
    st = get_onboarding_state()
    if st and st.get("status") == "active":
        step = st.get("step", "name")
        return _question(step, st.get("answers") or {})
    _set_onboarding_state("name", {})
    return _question("name", {})


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
        answers = dict(st.get("answers") or {})
        if text.lower() in _SKIP_WORDS:
            clear_onboarding_state()
            return "No problem — I'll pick it up as we go. Ask me anything."
        if _is_onboarding_meta_question(text):
            return (
                "Yes — we're doing that now. "
                + _question(step, answers)
            )
        if _is_not_an_answer(text):
            clear_onboarding_state()
            return None
        canonical = _apply_answer(step, text, db_path=db_path)
        if step == "name":
            if not canonical:
                # No usable name (e.g. a bare greeting like "Hello and Good Morning").
                # Re-ask ONCE rather than store the greeting as their name; after that,
                # move on without a name so we never trap them in a loop (they can set
                # it later, and ELI works fine without one).
                attempts = int(answers.get("_name_attempts", 0)) + 1
                answers["_name_attempts"] = attempts
                if attempts < 2:
                    _set_onboarding_state("name", answers)
                    return ("I don't think I caught your name in there — what would you "
                            "like me to call you? (Or just say 'skip' and I'll move on.)")
                answers.pop("name", None)   # give up gracefully; continue the interview
            else:
                answers["name"] = canonical
        else:
            answers[step] = canonical or text[:200]
        idx = _STEPS.index(step) if step in _STEPS else 0
        if idx + 1 < len(_STEPS):
            nxt = _STEPS[idx + 1]
            _set_onboarding_state(nxt, answers)
            return _question(nxt, answers)
        _set_onboarding_state(step, answers)
        return _finish(db_path=db_path)

    if _profile_missing(db_path=db_path) and _is_onboarding_meta_question(text):
        return _begin_or_resume(db_path=db_path)

    if _is_blank_slate(db_path=db_path) and not _looks_substantive(text):
        _set_onboarding_state("name", {})
        return _question("name", {})
    return None
