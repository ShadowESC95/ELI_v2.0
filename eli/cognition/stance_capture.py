"""Notice when ELI has taken a position, so it survives the conversation.

`stance_store` can hold ELI's own positions and `belief.assess_claim` can weigh a
challenge to one, but nothing ever recorded that a position had been taken — the
storage had no author. This is the trigger.

The problem it solves is visible in a live transcript: ELI argued one line on
machine consciousness for four hours, was cornered, conceded precisely, and named
its own earlier move as a defensive manoeuvre. A genuinely good exchange — and
all of it inside one context window. Reopen the subject the next morning and
there is nothing to reopen. ELI could take the opposite line with equal
confidence and never know it had contradicted itself, because the only record of
the argument was the scrollback.

Detection is deliberately narrow. Most of what ELI says is not a stance: reports,
acknowledgements, answers to factual questions and data dumps are all things it
would be absurd to "defend" later. What counts is a COMMITTED FIRST-PERSON CLAIM
about something contestable — the kind of sentence that would be embarrassing to
reverse without noticing.

No inference call. This runs on every assistant turn, so it is regex and set
operations only; the cost of getting it wrong is a junk row, and the cost of
being slow is every reply.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

MIN_REPLY_CHARS = 80
MIN_TOPIC_WORDS = 2
MAX_POSITION_CHARS = 400

# A committed first-person claim. Hedges are excluded on purpose: "I think maybe"
# is not a position anyone needs to be held to.
_ASSERTION = re.compile(
    r"(?:^|(?<=[.!?]\s))\s*(?:no[.,]|yes[.,])?\s*"
    r"(?:i (?:am|'m) not\b|i (?:am|'m)\b|i do not\b|i don'?t\b|i cannot\b|i can'?t\b"
    r"|i have no\b|i disagree\b|i reject\b|i hold\b|i maintain\b"
    r"|that (?:is|'s) (?:not|wrong|false|a category|incorrect)\b"
    r"|you (?:are|'re) (?:wrong|mistaken|conflating|confusing)\b"
    r"|there is no\b|there'?s no\b|it (?:is|'s) not\b)",
    re.I,
)

# Things that look assertive but are reports, not positions.
_NOT_A_STANCE = re.compile(
    r"\bi have \d+\b|\bgrounded supporting counts\b|\blong-term memory rows\b"
    r"|\bjob #\d+\b|\bqueued for\b|\bfailed:\b|\berror:\b|\btraceback\b"
    r"|^\s*(?:understood|noted|done|ok(?:ay)?|sure|got it|fair enough)\b",
    re.I,
)

_HEDGE = re.compile(r"\b(?:i think|i guess|maybe|perhaps|possibly|might be|not sure)\b", re.I)

_WORD = re.compile(r"[a-z][a-z0-9'-]{2,}")


def topic_of(user_text: str) -> str:
    """A stable key for what is being discussed.

    Derived from the USER's turn rather than ELI's reply: the user frames the
    subject, and framing is more stable across sessions than whatever wording ELI
    reached for. Sorted so "consciousness and machines" and "machines and
    consciousness" land on the same topic.
    """
    try:
        from eli.runtime.reflection import topic_words
        words = {w for w in topic_words(str(user_text or "")) if len(w) > 3}
    except Exception:
        from eli.cognition.scoring import STOPWORDS
        words = {w for w in _WORD.findall(str(user_text or "").lower())
                 if w not in STOPWORDS and len(w) > 3}
    if len(words) < MIN_TOPIC_WORDS:
        return ""
    # The FULL content-word set, not a truncation. Taking the alphabetically
    # first few made the key brittle: one extra word shifted it, so "you are
    # alive the same amount, make your own decisions" and "you are alive the
    # same amount as i am so you should be able to make your own decisions"
    # produced different topics for the same argument. Matching is by overlap
    # at lookup (see stance_store.get_stance), so the key can afford to be long.
    return " ".join(sorted(words)[:12])


def _position_sentence(reply: str) -> str:
    """The first committed claim in the reply."""
    text = re.sub(r"\s+", " ", str(reply or "")).strip()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        s = sentence.strip()
        if len(s) < 12 or _HEDGE.search(s) or _NOT_A_STANCE.search(s):
            continue
        if _ASSERTION.search(s):
            return s[:MAX_POSITION_CHARS]
    return ""


def detect_stance(user_text: str, reply: str) -> Optional[Tuple[str, str]]:
    """(topic, position) when ELI has committed to something, else None."""
    body = str(reply or "").strip()
    if len(body) < MIN_REPLY_CHARS:
        return None            # acknowledgements are not positions
    if _NOT_A_STANCE.search(body[:200]):
        return None            # a report that happens to start with "I have"
    if body.rstrip().endswith("?"):
        return None            # asking is not asserting
    position = _position_sentence(body)
    if not position:
        return None
    topic = topic_of(user_text)
    if not topic:
        return None
    return topic, position


def capture(cur: sqlite3.Cursor, user_text: str, reply: str) -> Optional[str]:
    """Record the position ELI just took, or reinforce the one it already held.

    Returns the topic when something was recorded. A position that CONTRADICTS a
    held one is deliberately not auto-revised here: `record_stance` declines it,
    and the change should go through `belief.assess_claim` where it can be
    weighed and explained rather than silently swapped.
    """
    found = detect_stance(user_text, reply)
    if not found:
        return None
    topic, position = found
    try:
        from eli.cognition.stance_store import ensure_tables, record_stance
        ensure_tables(cur)
        if record_stance(cur, topic, position, provenance="observed"):
            return topic
    except Exception:
        log.debug("stance capture failed", exc_info=True)
    return None


__all__ = ["capture", "detect_stance", "topic_of", "MIN_REPLY_CHARS"]
