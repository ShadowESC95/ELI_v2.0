"""Shared patterns for user correction / dispute turns.

Used by the kernel query classifier and the deterministic router so both
agree on when a message is challenging ELI's prior answer.
"""
from __future__ import annotations

import re

CORRECTION_QUERY_RE = re.compile(
    r"\b("
    r"i did not ask|i didn't ask|not what i asked|that's not what i asked|"
    r"that is not what i asked|what are you talking about|what are you talking bout|"
    r"answer properly|"
    r"data dump|stop giving me data|why did you send|did not ask for|"
    r"what do you mean|what wild night|what night|i never|didn't have|"
    r"did not have|that's not true|that is not true|i didn't say|"
    r"i did not say|where did you get|why do you say|never said|"
    r"never told you|didn't mention|did not mention|"
    r"why did you lie|you lied|that was a lie|why did you say|"
    r"that was a question|that is a question|that's a question|"
    r"what is your problem|what's your problem"
    r")\b",
    re.IGNORECASE,
)

# Meta-conversation: user is challenging ELI's prior reply or asking ELI to
# elaborate on something ELI just said (not a new factual lookup).
META_CONVERSATION_RE = re.compile(
    r"(?:^|\b)("
    r"like what\??|"
    r"you asked me\b|"
    r"i responded with|"
    r"no you (?:were not|wasn't|didn't|did not|fucking were not)"
    r")(?:\b|$)",
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

# User correcting ELI's claimed model identity ("you are GLM", "no you are not Ornith").
MODEL_IDENTITY_DISPUTE_RE = re.compile(
    r"\b(?:no you are not|you are not|you're not|not what i said)\b"
    r"|\byou(?:'re| are)\s+(?:glm|qwen|ornith|llama|mistral|claude)\b"
    r"|\b(?:wrong model|not ornith|not glm|not qwen)\b"
    r"|\bcheck(?:\s+the|\s+your)?\s+model\s+again\b"
    r"|\blook at (?:the|your) model\b",
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


NEWS_FETCH_COMPLAINT_RE = re.compile(
    r"\b(?:"
    r"guessing|guess(?:ing)?|made\s+up|hallucin(?:at(?:e|ing|ed))?|"
    r"didn't\s+fetch|did\s+not\s+fetch|not\s+fetch(?:ing)?\s+(?:the\s+)?(?:actual|real)|"
    r"fake\s+story|invented|you\s+made\s+that\s+up|getting\s+ahead\s+of\s+yourself|"
    r"come\s+with\s+(?:some\s+)?(?:facts?|info)|at\s+least\s+come\s+with"
    r")\b",
    re.I,
)


def is_news_fetch_complaint(text: str) -> bool:
    s = str(text or "")
    if not NEWS_FETCH_COMPLAINT_RE.search(s):
        return False
    return bool(re.search(
        r"\b(?:news|story|stories|article|headline|fetch|deeper|briefing)\b", s, re.I))


def is_correction_query(text: str) -> bool:
    s = str(text or "")
    if is_news_fetch_complaint(s):
        return True
    if CORRECTION_QUERY_RE.search(s):
        return True
    if META_CONVERSATION_RE.search(s):
        return True
    if META_CAPABILITY_COMPLAINT_RE.search(s):
        return True
    if MODEL_IDENTITY_DISPUTE_RE.search(s):
        return True
    if TEMPORAL_CORRECTION_RE.search(s) and re.search(
        r"\b(?:you|eli|wrong|not|can(?:'t| not)|cannot)\b", s, re.I
    ):
        return True
    return False


RUNTIME_RECHECK_CORRECTION_RE = re.compile(
    r"\b(?:that(?:'s| is| was)?\s+not\s+true|not\s+true|that(?:'s| is)\s+wrong|you'?re\s+wrong)\b",
    re.I,
)

CODEBASE_HEALTH_RE = re.compile(
    r"\bhow(?:'?s|\s+is|\s+are)\s+(?:the\s+)?(?:codebase|code\s*base|repo|repository|project|code)\b",
    re.I,
)


def is_runtime_recheck_correction(text: str) -> bool:
    """User disputing ELI's prior factual/runtime claim and asking for a re-check."""
    s = str(text or "")
    if not RUNTIME_RECHECK_CORRECTION_RE.search(s):
        return False
    return bool(re.search(
        r"\b(check again|try again|look again|verify|recheck|re-check|check(?:\s+it)?\s+again)\b",
        s,
        re.I,
    ))


def is_codebase_health_query(text: str) -> bool:
    s = str(text or "")
    if CODEBASE_HEALTH_RE.search(s):
        return True
    return bool(re.search(
        r"\b(?:codebase|code\s*base|repo|repository)\b", s, re.I
    ) and re.search(r"\b(?:health|status|state|holding up|doing)\b", s, re.I))


def is_model_identity_dispute(text: str) -> bool:
    return bool(MODEL_IDENTITY_DISPUTE_RE.search(str(text or "")))


def is_biographical_dispute(text: str) -> bool:
    if is_runtime_recheck_correction(text):
        return False
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


def is_meta_conversation(text: str) -> bool:
    """True when the user is asking about ELI's own prior reply, not a new topic."""
    s = str(text or "")
    if META_CONVERSATION_RE.search(s):
        return True
    return bool(re.search(
        r"\b(that(?:'s| is| was) a question|like what\??)\b", s, re.I
    ))


def correction_shortcut_allowed(text: str, action: str) -> bool:
    """True when the kernel may run _correction_repair before the main pipeline."""
    if str(action or "").upper() in _CORRECTION_BYPASS_ACTIONS:
        return False
    if explicit_web_search_request(text):
        return False
    return True
