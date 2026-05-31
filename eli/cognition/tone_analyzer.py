"""
eli/cognition/tone_analyzer.py
================================
Lightweight tone/communication-style analyzer.

Derives user behavioral preferences from recent conversation turns using
heuristics — no LLM calls. Results are written to user_patterns as
preference.tone.* entries, which flow automatically through the persona
updater into the system prompt.

Signals detected
----------------
  style       — casual / mixed / technical
  depth       — brief / normal / detailed
  correction  — how often the user corrects ELI
  humor       — whether the user engages with banter/humor
  mode        — work / casual / mixed

Update cadence
--------------
Writes only when the analysis window has at least MIN_TURNS new user
turns since the last write, and at most once per WRITE_INTERVAL seconds.
"""

from __future__ import annotations

import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────

MIN_TURNS        = 20    # minimum user turns needed before writing signals
WRITE_INTERVAL   = 3600  # seconds between writes (1 hour)
ANALYSIS_WINDOW  = 100   # look at the last N user turns

# ── Pattern libraries ─────────────────────────────────────────────────────────

_CASUAL = frozenset({
    "yeah", "yep", "nope", "gonna", "wanna", "gotta", "dunno", "kinda",
    "sorta", "cheers", "pal", "mate", "buddy", "cool", "ok", "okay",
    "yup", "nah", "hmm", "tbh", "tbf", "imo", "btw", "fyi", "lol", "haha",
    "heh", "tho", "thx", "ty", "np", "gr8", "rly", "idk", "afaik",
})

_TECHNICAL = re.compile(
    r"\b(function|class|module|import|database|sqlite|api|json|http|async|"
    r"thread|memory|vector|inference|llm|neural|gpu|cpu|pipeline|algorithm|"
    r"recursive|binary|matrix|gradient|embedding|tensor|model|schema|query|"
    r"index|cache|buffer|kernel|daemon|process|signal|socket|runtime|debug|"
    r"stack|trace|exception|variable|parameter|argument|return|loop|array|"
    r"dict|list|tuple|integer|float|boolean|string|regex|parse|serialize)\b",
    re.I,
)

_CORRECTION = re.compile(
    r"\b(no[,.]?\s+that|wrong|incorrect|not (what|right)|that'?s not|"
    r"i meant|i said|i asked for|that wasn'?t|stop doing|don'?t do that|"
    r"no wait|actually[,\s]|that'?s wrong|not quite|missed the point|"
    r"you misunderstood|not what i|try again|that'?s incorrect|"
    r"you got it wrong|that'?s not it|no no)\b",
    re.I,
)

_DEPTH_MORE = re.compile(
    r"\b(more detail|elaborate|expand|go deeper|in depth|tell me more|"
    r"explain more|more about|can you explain|why does|how does|"
    r"step by step|walk me through|comprehensive|thorough|full (breakdown|explanation)|"
    r"break it down|in full|complete)\b",
    re.I,
)

_DEPTH_LESS = re.compile(
    r"\b(just (tell|give|show|say)|briefly|short (answer|version|reply)|"
    r"summarize|tldr|tl;dr|quick(ly)?|in a (word|sentence|line|nutshell)|"
    r"just the (answer|result|key)|keep it (short|brief|simple)|"
    r"don'?t need (the|all the) detail|spare me)\b",
    re.I,
)

_HUMOR_ENGAGE = re.compile(
    r"(haha|lol|heh|😂|🤣|😄|that'?s funny|good one|nice one|"
    r"\bha\b|\bha ha\b|you'?re funny|i laughed|made me (laugh|smile)|"
    r"got me there|touche|well played)",
    re.I,
)

_BANTER = re.compile(
    r"\b(pal|buddy|mate|cheeky|smartass|smart[- ]?ass|wise[- ]?guy|"
    r"you'?re killing me|you wish|dream on|yeah right|sure thing|"
    r"whatever you say|as if|oh really|oh come on|get out of here)\b",
    re.I,
)

_FRUSTRATION = re.compile(
    r"\b(come on|seriously|for (god'?s?|christ'?s?|heaven'?s?) sake|"
    r"are you (kidding|joking|serious)|what the (hell|heck|f[a-z]*)|"
    r"this is (wrong|broken|useless|not working)|still wrong|"
    r"again\?|you keep|you always|every time|not again)\b",
    re.I,
)


# ── Core analysis ─────────────────────────────────────────────────────────────

def _word_tokens(text: str) -> List[str]:
    return re.findall(r"[a-z']+", text.lower())


def analyze_turns(user_turns: List[str]) -> Dict[str, Any]:
    """
    Analyze a list of user message strings and return a signals dict.
    All values are raw counts/ratios — interpretation happens in build_preference_strings().
    """
    if not user_turns:
        return {}

    n = len(user_turns)
    total_words     = 0
    casual_hits     = 0
    tech_hits       = 0
    formal_hits     = 0
    correction_hits = 0
    depth_more_hits = 0
    depth_less_hits = 0
    humor_hits      = 0
    banter_hits     = 0
    frustration_hits = 0
    long_turns      = 0   # turns with ≥15 words
    short_turns     = 0   # turns with ≤4 words

    for text in user_turns:
        words = _word_tokens(text)
        wc = len(words)
        total_words += wc

        if wc >= 15:
            long_turns += 1
        elif wc <= 4:
            short_turns += 1

        casual_hits      += sum(1 for w in words if w in _CASUAL)
        tech_hits        += len(_TECHNICAL.findall(text))
        correction_hits  += 1 if _CORRECTION.search(text) else 0
        depth_more_hits  += 1 if _DEPTH_MORE.search(text) else 0
        depth_less_hits  += 1 if _DEPTH_LESS.search(text) else 0
        humor_hits       += 1 if _HUMOR_ENGAGE.search(text) else 0
        banter_hits      += 1 if _BANTER.search(text) else 0
        frustration_hits += 1 if _FRUSTRATION.search(text) else 0

    avg_wc = total_words / n

    return {
        "n":                 n,
        "avg_word_count":    avg_wc,
        "long_turn_ratio":   long_turns / n,
        "short_turn_ratio":  short_turns / n,
        "casual_rate":       casual_hits / n,
        "tech_rate":         tech_hits / n,
        "correction_rate":   correction_hits / n,
        "depth_more_rate":   depth_more_hits / n,
        "depth_less_rate":   depth_less_hits / n,
        "humor_rate":        humor_hits / n,
        "banter_rate":       banter_hits / n,
        "frustration_rate":  frustration_hits / n,
    }


def build_preference_strings(sig: Dict[str, Any]) -> Dict[str, str]:
    """
    Convert raw signal dict into human-readable preference strings keyed by
    tone dimension. These become the pattern_data values in user_patterns.
    """
    out: Dict[str, str] = {}

    # ── Communication style ───────────────────────────────────────────────────
    casual  = sig.get("casual_rate", 0)
    tech    = sig.get("tech_rate", 0)
    avg_wc  = sig.get("avg_word_count", 10)

    if tech > 1.5 and casual < 0.3:
        style = "User communicates in a primarily technical, precise style with low casual language."
    elif casual > 0.5 and tech < 0.8:
        style = "User communicates casually and informally — contractions, shorthand, conversational tone."
    elif tech > 0.8 and casual > 0.3:
        style = "User mixes technical precision with casual informal language depending on context."
    else:
        style = "User communicates in a neutral, direct style."
    out["style"] = style

    # ── Depth / response length preference ───────────────────────────────────
    more = sig.get("depth_more_rate", 0)
    less = sig.get("depth_less_rate", 0)
    long_r = sig.get("long_turn_ratio", 0)
    short_r = sig.get("short_turn_ratio", 0)

    if more > 0.05 or (long_r > 0.30 and avg_wc > 14):
        depth = "User prefers detailed, thorough responses — willing to engage with depth and complexity."
    elif less > 0.05 or (short_r > 0.55 and avg_wc < 7):
        depth = "User prefers brief, direct answers — cut to the point, minimal explanation unless asked."
    else:
        depth = "User accepts moderate response length — detailed when the topic warrants it."
    out["depth"] = depth

    # ── Correction sensitivity ────────────────────────────────────────────────
    corr = sig.get("correction_rate", 0)
    if corr > 0.10:
        correction = (
            f"User corrects ELI frequently (~{corr*100:.0f}% of turns) — "
            "prioritise accuracy and precision over speed; confirm understanding before proceeding."
        )
    elif corr > 0.04:
        correction = "User occasionally corrects ELI — stay precise, acknowledge mistakes directly."
    else:
        correction = "User rarely needs to correct ELI — current accuracy level is working."
    out["correction"] = correction

    # ── Humor / banter engagement ─────────────────────────────────────────────
    humor  = sig.get("humor_rate", 0)
    banter = sig.get("banter_rate", 0)
    if humor > 0.05 or banter > 0.05:
        out["humor"] = (
            "User actively engages with dry humor and banter — "
            "wit and sarcasm are welcome when timing is right."
        )
    elif humor > 0.02 or banter > 0.02:
        out["humor"] = "User occasionally responds to humor — light wit is acceptable."
    else:
        out["humor"] = "User has not engaged with humor — keep tone direct and neutral."

    # ── Frustration / stress signal ───────────────────────────────────────────
    frust = sig.get("frustration_rate", 0)
    if frust > 0.07:
        out["frustration"] = (
            "User shows frequent frustration signals — "
            "be more concise, acknowledge errors faster, reduce hedging."
        )

    # ── Session mode ──────────────────────────────────────────────────────────
    if tech > 1.2 and avg_wc > 10:
        out["mode"] = "User is typically in deep technical work mode — match that intensity."
    elif casual > 0.6 and avg_wc < 8:
        out["mode"] = "User often in casual check-in mode — brief responses keep the flow."
    else:
        out["mode"] = "User alternates between focused work and casual interaction — read the context."

    return out


# ── DB interface ──────────────────────────────────────────────────────────────

def _get_db_path(memory: Any) -> Optional[str]:
    p = getattr(memory, "db_path", None) or getattr(memory, "_db_path", None)
    if p:
        return str(p)
    try:
        from eli.core.paths import user_db_path
        return str(user_db_path())
    except Exception:
        return None


def _fetch_recent_user_turns(db_path: str, limit: int = ANALYSIS_WINDOW) -> List[str]:
    import sqlite3 as _sq
    try:
        con = _sq.connect(db_path)
        try:
            rows = con.execute(
                "SELECT content FROM conversation_turns "
                "WHERE lower(role) = 'user' AND length(COALESCE(content,'')) > 3 "
                "ORDER BY ROWID DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            con.close()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        log.debug("tone_analyzer: turn fetch failed: %s", e)
        return []


def _last_write_ts(db_path: str) -> float:
    """Return timestamp of the most recent preference.tone.* write."""
    import sqlite3 as _sq
    try:
        con = _sq.connect(db_path)
        try:
            row = con.execute(
                "SELECT MAX(COALESCE(timestamp, ts, 0)) FROM user_patterns "
                "WHERE pattern_type LIKE 'preference.tone.%'",
            ).fetchone()
        finally:
            con.close()
        return float(row[0] or 0) if row else 0.0
    except Exception:
        return 0.0


def _upsert_tone_preference(db_path: str, subtype: str, value: str) -> None:
    """
    Insert or replace a preference.tone.<subtype> row.
    Old rows with the same subtype are deleted first so stale signals don't accumulate.
    """
    import sqlite3 as _sq
    now = time.time()
    pattern_type = f"preference.tone.{subtype}"
    try:
        con = _sq.connect(db_path, timeout=5.0)
        try:
            con.execute(
                "DELETE FROM user_patterns WHERE pattern_type = ?",
                (pattern_type,),
            )
            con.execute(
                "INSERT INTO user_patterns (pattern_type, pattern_data, timestamp, ts) "
                "VALUES (?, ?, ?, ?)",
                (pattern_type, value, now, now),
            )
            con.commit()
        finally:
            con.close()
    except Exception as e:
        log.debug("tone_analyzer: upsert failed (%s): %s", pattern_type, e)


# ── Public entry point ────────────────────────────────────────────────────────

def run_tone_analysis(memory: Any) -> Dict[str, Any]:
    """
    Analyze recent user turns and write detected tone preferences to
    user_patterns. Safe to call frequently — skips if not enough new turns
    or not enough time has passed since last write.

    Returns a dict summarising what was written (or why it was skipped).
    """
    db_path = _get_db_path(memory)
    if not db_path:
        return {"ok": False, "reason": "no_db_path"}

    # Throttle: skip if last write was recent
    last_ts = _last_write_ts(db_path)
    if time.time() - last_ts < WRITE_INTERVAL:
        return {"ok": True, "reason": "throttled", "next_in_s": int(WRITE_INTERVAL - (time.time() - last_ts))}

    turns = _fetch_recent_user_turns(db_path)
    if len(turns) < MIN_TURNS:
        return {"ok": True, "reason": "insufficient_turns", "have": len(turns), "need": MIN_TURNS}

    signals  = analyze_turns(turns)
    prefs    = build_preference_strings(signals)

    written = []
    for subtype, value in prefs.items():
        _upsert_tone_preference(db_path, subtype, value)
        written.append(subtype)

    log.info("tone_analyzer: wrote %d tone preference signals: %s", len(written), written)
    return {"ok": True, "written": written, "signals": signals}
