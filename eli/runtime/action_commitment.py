"""Detect when ELI's reply COMMITS to performing an action.

The rule (Jason, 2026-06): no fake actions. If ELI says it will do something
("let me check the news", "fetching now", "I'll re-run that"), the caller must
actually re-run the pipeline and DO it — never let the promise stand as theatre,
and never emit fill-in placeholders ("[Story 1]", "checking…").

This module is pure/deterministic (no engine deps) so it can be unit-tested and
reused by any consumer. It returns the clause to re-dispatch; the caller routes
it through the real router→executor so the actual task runs.
"""
from __future__ import annotations

import re
from typing import Optional, Dict

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


# User directives/challenges that mean "actually (re-)do the task" — the caller
# re-runs the last real action instead of letting ELI chat about it / defend
# itself. Deliberately requires "again / it / that" or a doubt ("are you
# actually …ing") so a fresh request ("check the news") is NOT treated as a redo.
_REDO_RE = re.compile(
    r"\b(?:"
    r"(?:do|run|check|fetch|search|look)\s+(?:it|that)\s+again|"
    r"(?:check|fetch|search|run|look)\s+(?:it|that|again)|"
    r"re-?(?:run|check|fetch|do|try)\b|"
    r"try\s+(?:that\s+|it\s+)?again|"
    r"(?:are|were)\s+you\s+(?:actually|even|really)\s+\w+ing|"
    r"did\s+you\s+(?:actually|even|really)\s+\w+|"
    r"go\s+(?:on|ahead)\s+(?:then|and\s+\w+)|"
    r"actually\s+(?:do|run|check|fetch|search)\s+it"
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
    start = max(s.rfind(". ", 0, m.start()), s.rfind("\n", 0, m.start())) + 1
    end_dot = s.find(". ", m.end())
    end_nl = s.find("\n", m.end())
    ends = [e for e in (end_dot, end_nl) if e != -1]
    end = min(ends) if ends else len(s)
    clause = s[start:end].strip(" .\n") or s
    return {"clause": clause, "matched": m.group(0).strip()}
