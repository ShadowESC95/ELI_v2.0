"""A single value asked for by name, read from what the person said earlier.

"Reply with only the code" asks for a value, and MEMORY_RECALL's visible result is a transcript. The
value is served only when the records agree on one, said by the person about the same thing. Missing,
contradictory or ambiguous evidence leaves the ordinary result as it was. No memory is written and no
commands are executed.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_ASKS = re.compile(
    r"\b(?:recall|retrieve|remember|tell\s+me|what(?:['’]s|\s+is|\s+was))\b[^\n?]*?"
    r"\b(?:(?:the|my|exact)\s+)*(?P<attr>[a-z][\w-]*(?:\s[a-z][\w-]*)?)\s+(?:for|of)\s+(?:my|the)\s+"
    r"(?P<thing>[^\n?.,]+?)\s*(?:[?.,]|$)", re.I)
_VALUE = r"([A-Za-z0-9][A-Za-z0-9_.-]{0,127})"
_NOT_THE_PERSON = frozenset(("assistant", "tool", "web", "document", "file"))


def exact_value_from_hits(user_input: str, payload: Any) -> Optional[str]:
    """The one value MEMORY_RECALL's structured hits hold for what is asked, or None. Never mined from
    the readable transcript, which can echo the question, nor from the current request."""
    q = str(user_input or "")
    asked = _ASKS.search(q)
    if not asked or not isinstance(payload, dict) or not payload.get("ok", True):
        return None
    attr = asked.group("attr").strip()
    if not re.search(rf"\b(?:only|just)\s+the\s+{re.escape(attr)}\b", q, re.I):
        return None
    hits = payload.get("hits")
    if str(payload.get("action") or "MEMORY_RECALL").upper() != "MEMORY_RECALL" or not isinstance(hits, (list, tuple)):
        return None
    names = [re.compile(rf"(?<![\w-]){re.escape(w)}(?![\w-])", re.I) for w in asked.group("thing").split()]
    said_of = (re.compile(rf"\b{re.escape(attr)}\b[^.!?\n]*?(?:\b(?:is|was)\b|=|:)\s*{_VALUE}", re.I),
               re.compile(rf"\b(?:has|have|uses|holds)\s+(?:the\s+)?{re.escape(attr)}\s+{_VALUE}", re.I))
    values = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        # A prior assignment by the person: not ELI's words, a tool's output or an imported document.
        if str(hit.get("role") or "user").lower() not in ("user", "human"):
            continue
        if str(hit.get("origin") or "").lower() in _NOT_THE_PERSON:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(hit.get("text") or hit.get("content") or "")):
            if all(n.search(sentence) for n in names):
                values.update(m.group(1).rstrip(".") for pattern in said_of for m in pattern.finditer(sentence))
    return next(iter(values)) if len(values) == 1 else None


exact_project_code_from_hits = exact_value_from_hits      # the benchmark's own tests import this name
