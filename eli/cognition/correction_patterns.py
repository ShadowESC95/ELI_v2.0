"""Shared patterns for user correction / dispute turns.

Used by the kernel query classifier and the deterministic router so both
agree on when a message is challenging ELI's prior answer.
"""
from __future__ import annotations

import re

CORRECTION_QUERY_RE = re.compile(
    r"\b("
    r"i did not ask|i didn't ask|not what i asked|that's not what i asked|"
    r"that is not what i asked|what are you talking about|answer properly|"
    r"data dump|stop giving me data|why did you send|did not ask for|"
    r"what do you mean|what wild night|what night|i never|didn't have|"
    r"did not have|that's not true|that is not true|i didn't say|"
    r"i did not say|where did you get|why do you say|never said|"
    r"never told you|didn't mention|did not mention"
    r")\b",
    re.IGNORECASE,
)

# User correcting ELI's recency ("that was today", "not last week").
TEMPORAL_CORRECTION_RE = re.compile(
    r"\b(?:was|is)\s+(?:today|yesterday|this morning|this evening|just now|earlier today)\b"
    r"|\bnot\s+last\s+week\b"
    r"|\bthat\s+was\s+(?:today|yesterday)\b",
    re.I,
)

# Complaints that ELI failed to read time/timestamps in the conversation.
META_CAPABILITY_COMPLAINT_RE = re.compile(
    r"\b(?:can(?:'t| not)|cannot|won't|will not)\s+(?:you\s+)?(?:read|parse|see|get)\b"
    r".{0,50}\b(?:timestamp|time|date|clock)\b"
    r"|\b(?:read|parse)\s+(?:a\s+)?(?:fucking\s+)?timestamp\b"
    r"|\bcan you not read\b",
    re.I,
)

BIOGRAPHICAL_DISPUTE_RE = re.compile(
    r"\b("
    r"what do you mean|what wild night|what night|i never|didn't have|"
    r"did not have|that's not true|that is not true|i didn't say|"
    r"i did not say|where did you get|why do you say|what are you talking about|"
    r"never said|never told you|didn't mention|did not mention|"
    r"been through|you said i|waking up late|wild night"
    r")\b",
    re.IGNORECASE,
)


def is_correction_query(text: str) -> bool:
    s = str(text or "")
    if CORRECTION_QUERY_RE.search(s):
        return True
    if META_CAPABILITY_COMPLAINT_RE.search(s):
        return True
    if TEMPORAL_CORRECTION_RE.search(s) and re.search(
        r"\b(?:you|eli|wrong|not|can(?:'t| not)|cannot)\b", s, re.I
    ):
        return True
    return False


def is_biographical_dispute(text: str) -> bool:
    return bool(BIOGRAPHICAL_DISPUTE_RE.search(str(text or "")))


WEB_SEARCH_REQUEST_RE = re.compile(
    r"\b("
    r"search the web|search online|look it up|google it|check online|"
    r"go search|web search|search for|look online|find online"
    r")\b",
    re.I,
)

# Routed executor actions must not be overridden by the CORRECTION repair shortcut.
_CORRECTION_BYPASS_ACTIONS = frozenset({
    "WEB_SEARCH", "WEB_FETCH", "WEB_LEARN", "SEARCH_WEB",
    "NEWS_FETCH", "GET_WEATHER",
})


def explicit_web_search_request(text: str) -> bool:
    return bool(WEB_SEARCH_REQUEST_RE.search(str(text or "")))


def correction_shortcut_allowed(text: str, action: str) -> bool:
    """True when the kernel may run _correction_repair before the main pipeline."""
    if str(action or "").upper() in _CORRECTION_BYPASS_ACTIONS:
        return False
    if explicit_web_search_request(text):
        return False
    return True
