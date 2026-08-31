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
    return bool(CORRECTION_QUERY_RE.search(str(text or "")))


def is_biographical_dispute(text: str) -> bool:
    return bool(BIOGRAPHICAL_DISPUTE_RE.search(str(text or "")))
