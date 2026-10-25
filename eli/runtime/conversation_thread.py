"""Conversation thread awareness — topic carryover, proactive grounding, web queries.

Keeps ELI from confabulating on underspecified follow-ups ("season 3 reviews")
and from answering entertainment/plot threads without retrieval when the user
expects grounded facts.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# Set by the engine immediately before routing so the web prepass can expand queries.
_route_ctx: Dict[str, str] = {"thread_topic": ""}

_ENTERTAINMENT_RE = re.compile(
    r"\b(?:the\s+)?(?:game\s+of\s+thrones|last\s+of\s+us|marvel|mcu|star\s+wars|"
    r"season\s+\d+|episode\s+\d+)\b",
    re.I,
)
_SHOW_TITLE_RE = re.compile(
    r"\b(?:watching|watch(?:ed|ing)?|show|series|spinoff|spin-off)\s+(.{4,80}?)"
    r"(?:\s+with\s+me|\s+haha|\s+please|\.|,|$)",
    re.I,
)
# "Blue Harbor season 3", "we're on Blue Harbor episode 6": a capitalised title before season/episode.
_TITLE_BEFORE_SEASON_RE = re.compile(
    r"\b((?:[A-Z][\w'’:-]*\s+){0,4}[A-Z][\w'’:-]*)\s+(?:season|episode)\s+\d+")
_LEADING_VERB_RE = re.compile(r"^(?:Watching|Watched|Watch|Started|Starting|Finished|Finishing)\s+")
_UNDERSPECIFIED_RE = re.compile(
    r"\b(?:season\s+\d+|episode\s+\d+|reviews?\s+for|the\s+latest\s+episodes?|"
    r"what\s+happened|plot|premiere|release\s+date)\b",
    re.I,
)
_GROUNDING_DEMAND_RE = re.compile(
    r"\b(?:search\s+(?:the\s+)?(?:web|online|internet)|look\s+it\s+up|google\s+it|"
    r"come\s+with\s+(?:some\s+)?(?:facts?|info|context)|"
    r"at\s+least\s+(?:come|bring)\s+with|"
    r"getting\s+ahead\s+of\s+yourself|you(?:'re|\s+are)\s+guessing|"
    r"did\s+not\s+fetch|didn't\s+fetch|not\s+what\s+happened|that's\s+wrong|"
    r"that\s+is\s+wrong)\b",
    re.I,
)
_SEARCH_VERB_RE = re.compile(
    r"\b(?:web\s+search|search\s+(?:the\s+)?(?:web|online|internet)|"
    r"search\s+for|look\s+(?:it|this|that)?\s*up|google\b|find\s+out)\b",
    re.I,
)
_STOP = frozenset({
    "the", "a", "an", "and", "or", "but", "so", "i", "you", "we", "me", "my",
    "your", "it", "that", "this", "what", "when", "where", "how", "why", "is",
    "are", "was", "were", "do", "did", "can", "could", "would", "please", "just",
    "about", "with", "for", "on", "in", "to", "of", "at", "be", "been", "have",
    "has", "had", "will", "wanna", "want", "go", "get", "some", "any", "all",
})


def set_route_context(*, thread_topic: str = "") -> None:
    _route_ctx["thread_topic"] = str(thread_topic or "").strip()


def get_route_thread_topic() -> str:
    return str(_route_ctx.get("thread_topic") or "").strip()


def recent_turns_from_context(context: Any) -> List[Dict[str, str]]:
    if not context:
        return []
    out: List[Dict[str, str]] = []
    for item in context:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower()
        content = str(item.get("content") or item.get("message") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def extract_thread_topic(turns: List[Dict[str, str]]) -> str:
    """Best-effort subject of the current conversation thread: the show or film the most recent
    turns are about. Read newest first: the whole window read in order gave the oldest title, so
    "watching Coco now" stayed the topic after the talk had moved to something else."""
    for turn in reversed(turns[-8:]):
        text = str(turn.get("content") or "")
        m = _SHOW_TITLE_RE.search(text)
        if m:
            topic = m.group(1).strip(" .?!,\"'")
            if len(topic.split()) <= 8:
                return topic
        m = _TITLE_BEFORE_SEASON_RE.search(text)
        if m:
            return _LEADING_VERB_RE.sub("", m.group(1)).strip()
        ents = _ENTERTAINMENT_RE.findall(text)
        if ents:
            return " ".join(dict.fromkeys(str(e).strip() for e in ents[:3]))
    return ""


def last_subject(turns: List[Dict[str, str]]) -> str:
    """What the user last asked about: the subject of their most recent earlier message that has
    one ("look up ORBIT", "no dude, ORBIT and Northwind" -> "ORBIT and Northwind"). What "look it up"
    refers to. "" when no earlier message names anything."""
    from eli.runtime.command_splitter import without_correction_lead
    for turn in reversed(turns or []):
        if str(turn.get("role") or "").lower() != "user":
            continue
        text = without_correction_lead(str(turn.get("content") or ""))
        subject = extract_search_subject(text)
        if subject and web_query_has_substance(subject) and not is_grounding_demand(subject):
            return subject
    return ""


def expand_web_query(user_input: str, thread_topic: str = "") -> str:
    """Merge thread topic into underspecified web queries."""
    raw = str(user_input or "").strip()
    topic = str(thread_topic or get_route_thread_topic() or "").strip()
    if not raw:
        return raw
    q = extract_search_subject(raw) or raw
    low = q.lower()
    if topic and _UNDERSPECIFIED_RE.search(low):
        if topic.lower() not in low:
            q = f"{topic} {q}"
    elif topic and _SEARCH_VERB_RE.search(raw) and not web_query_has_substance(q):
        # "google it": the topic is what "it" is. A search that names something is left as the
        # user said it ("look up ORBIT" became "Coco now ORBIT" while a film was the topic).
        q = topic
    return re.sub(r"\s+", " ", q).strip()


def extract_search_subject(raw: str) -> str:
    """Pull the searchable subject from a mid-sentence web request."""
    s = str(raw or "").strip()
    if not s:
        return ""
    patterns = (
        r"search\s+the\s+web(?:\s+and)?\s*(.+)$",
        r"(?:search\s+(?:the\s+)?(?:web|online|internet)\s+(?:for\s+)?(.+))$",
        r"(?:do\s+a\s+)?web\s+search\s+(?:and\s+)?(?:get\s+)?(.+)$",
        r"(?:search\s+for|look\s+up|google)\s+(.+)$",
        r"(?:get\s+(?:some\s+)?(?:reviews?|info|facts?)\s+(?:for|on|about)\s+(.+))$",
        r"(?:reviews?\s+for\s+(.+))$",
        r"(?:wanna\s+do\s+a\s+web\s+search\s+and\s+get\s+(.+))$",
        r"(?:come\s+with\s+(?:some\s+)?(?:facts?|info)\s+(?:about|on)\s+(.+))$",
    )
    _vague = {
        "some facts", "facts", "info", "some info",
        "and come with some facts", "come with some facts",
    }
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m and m.group(1).strip():
            subj = _clean_query_tail(m.group(1).strip())
            if subj and subj.lower() not in _vague:
                return subj
    if _SEARCH_VERB_RE.search(s):
        m2 = _SEARCH_VERB_RE.search(s)
        if m2:
            tail = s[m2.end():].strip(" ,:-")
            tail = re.sub(r"^(?:and\s+)?(?:get\s+)?(?:some\s+)?", "", tail, flags=re.I).strip()
            if tail and tail.lower() not in _vague:
                return _clean_query_tail(tail)
    cleaned = _clean_query_tail(s)
    if _SEARCH_VERB_RE.search(cleaned) or len(cleaned.split()) > 10:
        return ""
    return cleaned


def _clean_query_tail(q: str) -> str:
    q = re.sub(r"^(?:some|the|a|an)\s+", "", q.strip(" .?!,\"'"), flags=re.I)
    q = re.sub(r"\b(?:please|for me|now|online|on the internet)\b\.?$", "", q, flags=re.I).strip()
    return q[:160]


_META_STOP_RE = re.compile(
    r"\b(?:you|i|we|can|could|would|please|do|go|run|just|a|an|the|to|for|me|my|now|"
    r"have|has|access|use|using|web|internet|online|search|searching|searches|google|"
    r"googling|look|looking|looks|up|it|this|that|these|those|check|checking|confirm|"
    r"verify|find|finding|out|on|and|or|so|then|actual|actually|real|really)\b",
    re.I,
)


def web_query_has_substance(query: str, *, min_terms: int = 1) -> bool:
    """True when a web query names something after stripping meta-instructions: "look it up" names
    nothing, "look up ORBIT" names one thing (two were required, so it opened the browser)."""
    q = str(query or "").strip()
    if not q:
        return False
    subject = _META_STOP_RE.sub(" ", q)
    subject = re.sub(r"[^a-z0-9]+", " ", subject, flags=re.I).strip()
    return len([w for w in subject.split() if w]) >= min_terms


def build_thread_aware_query(user_input: str, turns: Optional[List[Dict[str, str]]] = None) -> str:
    topic = extract_thread_topic(turns or []) or get_route_thread_topic()
    raw = str(user_input or "").strip()
    subject = extract_search_subject(raw)
    vague = (not subject or not web_query_has_substance(subject) or is_grounding_demand(subject)
             or subject.lower() in {"some facts", "facts", "info", "some info",
                                    "and come with some facts", "come with some facts"})
    if is_grounding_demand(raw) and vague:
        # "look it up": what the user last asked about. Only when no earlier message names
        # anything does the show being talked about stand in (it gave "Coco now facts
        # reviews plot summary" two messages after the talk had moved on to ORBIT).
        earlier = last_subject(turns or [])
        if earlier:
            return expand_web_query(earlier, "")
        if topic:
            return f"{topic} facts reviews plot summary"
    if subject:
        return expand_web_query(subject, topic)
    return expand_web_query(raw, topic)


def is_grounding_demand(text: str) -> bool:
    return bool(_GROUNDING_DEMAND_RE.search(str(text or "")))


def should_proactive_web_search(
    user_input: str,
    turns: Optional[List[Dict[str, str]]] = None,
) -> Tuple[bool, str, str]:
    """Return (should_search, query, reason)."""
    raw = str(user_input or "").strip()
    if not raw:
        return False, "", ""
    turns = list(turns or [])
    topic = extract_thread_topic(turns)

    try:
        from eli.cognition.correction_patterns import explicit_web_search_request
        explicit = explicit_web_search_request(raw)
    except Exception:
        explicit = bool(_SEARCH_VERB_RE.search(raw))

    if explicit or is_grounding_demand(raw):
        q = build_thread_aware_query(raw, turns)
        if len(q.split()) >= 2:
            reason = "grounding_demand" if is_grounding_demand(raw) else "explicit_web"
            return True, q, reason

    # Underspecified factual follow-up in an entertainment thread (reviews, search).
    if topic and _UNDERSPECIFIED_RE.search(raw.lower()):
        if _SEARCH_VERB_RE.search(raw) or re.search(r"\breviews?\b|\bfacts?\b|\binfo\b", raw, re.I):
            q = expand_web_query(raw, topic)
            return True, q, "thread_underspecified"

    return False, "", ""


def proactive_web_intent(
    user_input: str,
    turns: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Build a WEB_SEARCH intent when conversation context requires retrieval."""
    ok, query, reason = should_proactive_web_search(user_input, turns)
    if not ok or not query:
        return None
    try:
        from eli.core.config import network_allowed
        if not network_allowed():
            return None
    except Exception:
        return None
    return {
        "action": "WEB_SEARCH",
        "args": {"query": query},
        "confidence": 0.94,
        "meta": {
            "matched_by": f"conversation_thread.{reason}",
            "thread_topic": extract_thread_topic(turns or []),
            "need_grounding": True,
            "allow_chat_without_evidence": False,
        },
    }


def ambient_vision_context_block() -> str:
    try:
        from eli.perception.ambient_vision import ambient_vision_status
        st = ambient_vision_status()
    except Exception:
        return ""
    if not st.get("enabled"):
        return ""
    text = str(st.get("last_glance_text") or "").strip()
    if not text:
        return ""
    return f"[Ambient screen glance — use for context; do not invent unseen details]\n{text[:700]}"


def conversation_grounding_rule(user_input: str, turns: Optional[List[Dict[str, str]]] = None) -> str:
    """Short system rule injected into CHAT when discussing external topics."""
    topic = extract_thread_topic(turns or [])
    if not topic and not _ENTERTAINMENT_RE.search(str(user_input or "")):
        return ""
    subj = topic or "the topic under discussion"
    return (
        f"CONVERSATION_GROUNDING: You are discussing {subj}. Do NOT invent plot points, "
        f"episode events, release dates, or reviews from memory. If you lack verified facts, "
        f"say so briefly and use WEB_SEARCH (or offer to) before discussing specifics. "
        f"Respect user corrections immediately — they outrank your prior reply."
    )
