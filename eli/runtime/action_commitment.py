"""Detect when ELI's reply COMMITS to performing an action.

The rule (user-requested, 2026-06): no fake actions. If ELI says it will do something
("let me check the news", "fetching now", "I'll re-run that"), the caller must
actually re-run the pipeline and DO it — never let the promise stand as theatre,
and never emit fill-in placeholders ("[Story 1]", "checking…").

This module is pure/deterministic (no engine deps) so it can be unit-tested and
reused by any consumer. It returns the clause to re-dispatch; the caller routes
it through the real router→executor so the actual task runs.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

# Verbs ELI uses when promising to actually perform/redo a task. Deliberately
# excludes vague ones ("get back to you", "think", "know") to avoid false hits.
_ACTION_VERB = (
    r"(?:check|re-?check|fetch|re-?fetch|search|look(?:ing)?\s+(?:up|into)|"
    r"pull\s+(?:up|it\s+up)|run|re-?run|verify|confirm|find\s+out|update|refresh|"
    r"look\s+that\s+up)"
)

# "let me … <verb>", "I'll … <verb>", "give me a moment … <verb>", etc.
_COMMIT_RE = re.compile(
    r"\b(?:let\s+me|let'?s|i'?ll|i\s+will|i\s+am\s+going\s+to|i'?m\s+going\s+to|"
    r"allow\s+me\s+to|give\s+me\s+(?:a\s+)?(?:moment|sec(?:ond)?)|one\s+moment|"
    r"hang\s+on|on\s+it,?)\b[^.!?\n]{0,60}?\b" + _ACTION_VERB + r"\b",
    re.I,
)

# Present-tense "doing it now" theatre.
_DOING_RE = re.compile(
    r"\b(?:checking|re-?checking|fetching|re-?fetching|searching|"
    r"looking\s+that\s+up|running\s+that|pulling\s+(?:that|it)\s+up|verifying)\b"
    r"(?:\s*\.\.\.|\s+now|\s+for\s+you)?",
    re.I,
)

# Obvious fabricated fill-ins / fake-fetch markers — always a fake action.
_FAKE_THEATRE_RE = re.compile(
    r"\bchecking\s*\.\.\.|\(\s*fetching|\[\s*story\s*\d|\[\s*insert\b|\[\s*headline\s*\d",
    re.I,
)


# User directives/challenges that mean "actually (re-)do the task": the caller re-runs the last real
# action instead of letting ELI chat or defend itself. Requires "again / it / that" or a doubt ("are
# you actually ...ing") so a fresh request ("check the news") isn't treated as a redo.
_REDO_RE = re.compile(
    r"\b(?:"
    r"(?:do|run|check|fetch|search|look)\s+(?:it|that)\s+again|"
    r"(?:check|fetch|search|run|look)\s+(?:it|that|again)|"
    r"re-?(?:run|check|fetch|do|try)\b|"
    r"try\s+(?:that\s+|it\s+)?again|"
    r"(?:are|were)\s+you\s+(?:actually|even|really)\s+\w+ing|"
    r"did\s+you\s+(?:actually|even|really)\s+\w+|"
    r"go\s+(?:on|ahead)\s+(?:then|and\s+\w+)|"
    r"actually\s+(?:do|run|check|fetch|search)\s+it|"
    # It didn't happen: "you did not open spotify", "spotify didn't open", "nothing happened".
    # Live: "You did not open spotify again!!!" got a made-up account of checking the logs.
    r"you\s+(?:did\s*n[o']?t|didn'?t|never|have\s*n[o']?t|haven'?t)\s+(?:actually\s+|even\s+|really\s+)?\w+|"
    r"\b(?!(?:i|we)\b)\w+\s+(?:did\s*n[o']?t|didn'?t|never|has\s*n[o']?t|hasn'?t|won'?t)\s+"
    r"(?:open|opened|play|played|start|started|launch|launched|load|loaded|work|worked|happen|happened)|"
    r"nothing\s+(?:happened|opened|played|started|is\s+playing)"
    r")\b",
    re.I,
)


def is_redo_directive(text: str) -> bool:
    """True when the user is telling ELI to actually (re-)perform the task —
    so the caller can re-run the LAST real action rather than route to chat."""
    s = str(text or "")
    m = _REDO_RE.search(s)
    if not m:
        return False
    # Exclude "I'll check it myself" — the USER doing it, not a directive to ELI.
    pre = s[max(0, m.start() - 25):m.start()].lower()
    if "myself" in s.lower() or re.search(r"\b(?:i|i'?ll|i'?m|we|we'?ll)\b", pre):
        return False
    return True


# Re-running the last action on "did you actually X?" is only right when X is
# that action and it just happened. Live (2026-10-02): "did you actually read the
# files" re-ran a Spotify pause from seven minutes earlier and paused the music.
REDO_MAX_AGE_S = 300.0

# Verbs that point back at whatever ELI last did, not at one kind of action.
_GENERIC_REDO_VERBS = {
    "do", "doing", "did", "done", "run", "running", "check", "checking", "try",
    "trying", "go", "look", "looking", "fetch", "fetching", "search", "searching",
    "it", "that", "again", "work", "working", "worked", "happen", "happening", "happened",
}
# Words that say nothing about WHAT should have happened.
_NOT_AN_OBJECT = {
    "the", "a", "an", "it", "that", "this", "again", "me", "my", "for", "properly", "even",
    "actually", "really", "when", "i", "asked", "you", "to", "at", "all", "fucking", "fuckin",
    "bloody", "just", "yet", "now", "please", "song", "track", "music", "app", "still",
    "not", "didn't", "didnt", "never", "has", "hasn't", "hasnt", "have", "haven't", "havent",
    "won't", "wont", "nothing", "is",
}


def _redo_verb(text: str) -> Optional[str]:
    m = _REDO_RE.search(str(text or ""))
    if not m:
        return None
    words = re.findall(r"[a-z]+", m.group(0).lower())
    return words[-1] if words else None


def redo_applies(text: str, last_cmd: Optional[Dict[str, Any]],
                 now: Optional[float] = None) -> bool:
    """is_redo_directive, and the last action is recent and is what it's about."""
    if not last_cmd or not is_redo_directive(text):
        return False
    age = (time.time() if now is None else float(now)) - float(last_cmd.get("ts") or 0.0)
    if age > REDO_MAX_AGE_S:
        return False
    # A complaint that names what didn't happen ("you did not open spotify") is about the last
    # command only if that command was about the same thing.
    verb = _redo_verb(text)
    s = str(text or "")
    m = _REDO_RE.search(s)
    said = re.findall(r"[a-z0-9']+", m.group(0).lower()) + re.findall(r"[a-z0-9']+", s[m.end():].lower())[:4]
    named = [w for w in said if w != verb and w not in _NOT_AN_OBJECT and w not in _GENERIC_REDO_VERBS]
    if named:
        last_words = " ".join([str(last_cmd.get("input") or ""), str(last_cmd.get("action") or "").replace("_", " ")]
                              + [str(v) for v in (last_cmd.get("args") or {}).values()]).lower()
        if not any(w in last_words for w in named):
            return False
    if not verb or verb in _GENERIC_REDO_VERBS:
        return True
    stem = re.sub(r"(?:ing|ed)$", "", verb)  # pausing -> paus, played -> play
    tokens = [t for t in str(last_cmd.get("action") or "").lower().split("_") if len(t) >= 3]
    return any(t.startswith(stem[:4]) or stem.startswith(t[:4]) for t in tokens)


# "Go deeper on <topic>" phrasings. When the previous turn was a news briefing,
# the captured topic is what the user wants re-fetched specifically — not the
# whole briefing again. Pure/deterministic so the engine can gate on it.
_DEEPEN_RE = re.compile(
    r"\b(?:"
    r"look(?:ing)?\s+(?:closer|deeper)?\s*(?:in)?to|"
    r"dig\s+(?:in)?to|delve\s+(?:in)?to|"
    r"go\s+deeper\s+(?:on|into)|"
    r"more\s+(?:on|about)|"
    r"tell\s+me\s+more\s+(?:on|about)|"
    r"expand\s+(?:on|about)|elaborate\s+on|"
    r"(?:read|look)\s+(?:closer|more)\s+(?:on|about|into)"
    r")\s+(.+)$",
    re.I,
)

# Trailing nouns that are framing, not part of the topic ("the Hubble story").
_DEEPEN_TAIL = re.compile(
    r"\s+(?:story|stories|article|articles|news|headline|headlines|situation|"
    r"thing|topic|piece|report|please|for\s+(?:me|us))\s*$",
    re.I,
)
_DEEPEN_STOP = {"the", "a", "an", "that", "this", "it", "them", "those", "these"}


def extract_deepen_topic(text: str) -> str:
    """Return the topic the user wants to go deeper on, or "".

    "look closer into Hubble" -> "Hubble"; "tell me more about the JWST story"
    -> "JWST". The caller gates use of this on context (e.g. the previous turn
    was a news briefing) so it never hijacks an unrelated "look into the bug".
    """
    s = str(text or "").strip()
    if not s:
        return ""
    m = _DEEPEN_RE.search(s)
    if not m:
        return ""
    topic = m.group(1).strip().strip("?.!,;:\"' ")
    # Strip a trailing framing noun, possibly more than one ("the Hubble news
    # story" -> "Hubble").
    prev = None
    while prev != topic:
        prev = topic
        topic = _DEEPEN_TAIL.sub("", topic).strip()
    toks = [w for w in re.split(r"\s+", topic) if w]
    while toks and toks[0].lower() in _DEEPEN_STOP:
        toks.pop(0)
    while toks and toks[-1].lower() in _DEEPEN_STOP:
        toks.pop()
    topic = " ".join(toks).strip()
    # Reject runaway captures (a whole frustrated sentence). A deepen topic can be a descriptive
    # phrase ("magnetic fields that help binary star systems form" is 8 words), so allow up to 12.
    # The old 6-word cap dropped real article topics and stopped topic-deepen for anything past a
    # one- or two-word subject.
    if not topic or len(toks) > 12:
        return ""
    return topic


def recover_recent_deepen_topic(memory) -> str:
    """Best-effort topic from a recent 'go deeper into …' user turn."""
    try:
        turns = memory.get_recent_conversation(limit=12) or []
    except Exception:
        return ""
    for _t in reversed(turns):
        if str((_t or {}).get("role") or "").lower() != "user":
            continue
        topic = extract_deepen_topic(str((_t or {}).get("content") or ""))
        if topic:
            return topic
    return ""


def detect_action_commitment(text: str) -> Optional[Dict[str, str]]:
    """Return {clause, matched} if `text` promises/fakes an action, else None.

    `clause` is the sentence holding the commitment — re-route it through the
    real pipeline so the router resolves the concrete task (e.g. "let me check
    the latest news" → NEWS_FETCH).
    """
    s = str(text or "").strip()
    if not s:
        return None
    m = _COMMIT_RE.search(s) or _DOING_RE.search(s) or _FAKE_THEATRE_RE.search(s)
    if not m:
        return None
    # Past or perfect-continuous narration ("I've been checking", "I was searching", "I checked
    # earlier") isn't a commitment to act now, and re-running it buries the user in an action they
    # never asked for. Only a forward commitment ("let me check", "I'll fetch", "checking now")
    # triggers followthrough.
    _pre = s[max(0, m.start() - 30):m.start()].lower()
    if re.search(r"\b(?:been|was|were|have\s+been|had\s+been|i'?ve\s+been|"
                 r"earlier|already|recently|just\s+(?:checked|finished))\b", _pre):
        return None
    start = max(s.rfind(". ", 0, m.start()), s.rfind("\n", 0, m.start())) + 1
    end_dot = s.find(". ", m.end())
    end_nl = s.find("\n", m.end())
    ends = [e for e in (end_dot, end_nl) if e != -1]
    end = min(ends) if ends else len(s)
    clause = s[start:end].strip(" .\n") or s
    return {"clause": clause, "matched": m.group(0).strip()}
