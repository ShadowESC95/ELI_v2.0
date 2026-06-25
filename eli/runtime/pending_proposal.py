"""
eli/runtime/pending_proposal.py
================================
Tracks a single pending *proposal* ELI has offered the user in conversation —
e.g. it answered a question and ended with "Want me to set a reminder for the
premiere?". If the user then affirms ("yes", "go ahead"), the stored proposal
phrase is re-routed through the normal pipeline so it actually executes (or
asks for specifics), instead of the affirmation being swallowed as chat.

Distinct from runtime.grounded_remediation (which handles "install X?" repair
offers). This is the general "ELI offered to do something next" channel.

State is a single JSON file with a short TTL so a stale "yes" minutes later
cannot trigger an old offer.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# A proposal is only actionable for a short window after it was offered.
_TTL_SECONDS = 300.0


def _path() -> Path:
    try:
        from eli.core.paths import get_paths
        base = Path(get_paths().artifacts_dir) / "runtime"
    except Exception:
        base = Path(__file__).resolve().parents[2] / "artifacts" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base / "pending_proposal.json"


def set_pending_proposal(command: str, summary: str = "") -> None:
    """Record a proposal ELI just offered. `command` is the phrase to re-route
    if the user affirms (e.g. "set a reminder for the rick and morty premiere")."""
    command = (command or "").strip()
    if not command:
        return
    try:
        _path().write_text(
            json.dumps({"command": command, "summary": summary or command, "ts": time.time()}),
            encoding="utf-8",
        )
        log.debug("[PENDING_PROPOSAL] stored: %r", command[:120])
    except Exception as e:
        log.debug("[PENDING_PROPOSAL] store failed: %s", e)


def get_pending_proposal() -> Optional[Dict[str, Any]]:
    """Return the live pending proposal dict, or None if absent/expired."""
    p = _path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("command"):
        return None
    if time.time() - float(data.get("ts", 0) or 0) > _TTL_SECONDS:
        clear_pending_proposal()
        return None
    return data


def clear_pending_proposal() -> None:
    try:
        p = _path()
        if p.exists():
            p.unlink()
    except Exception:
        pass


# Offer / proposal extraction from an ELI response. Returns the proposed
# command phrase (first concrete option) or "" if the text contains no offer.
import re as _re

# STRONG offers are inherently a question the user can affirm ("want me to …",
# "shall I …"). The captured action phrase STOPS at the first clause/sentence
# boundary so a declarative tail can never run into it (the old regex stopped
# only at ? , or-end, so "I'll backup my state. You have to deal with …" was
# swallowed whole and stored as a fake action).
_STRONG_OFFER_RE = _re.compile(
    r"\b(?:want me to|shall i|should i|would you like me to|do you want me to)\s+"
    r"(.+?)(?:[.?!]|,| or |$)",
    _re.I,
)

# WEAK declarative stems ("I can …", "I'll …") are only a real OFFER when the
# clause is phrased as a question (ends with ?). Otherwise "I can appreciate the
# absurdity of existence" / "I'll be waiting here" are narrative, not actions —
# capturing them let a later "yes" trigger a bogus command (no-fake-actions
# violation). Requiring the trailing ? keeps genuine "I can run that for you?"
# offers while dropping declaratives.
_WEAK_OFFER_RE = _re.compile(
    r"\b(?:i can|i could|i'?ll|i'd be happy to|happy to)\s+(.+?)\?",
    _re.I,
)

# A real queued action phrase is short and imperative — a runaway multi-clause
# capture is prose, not an offer.
_MAX_PROPOSAL_WORDS = 12

# Phrases that are conversational, not real actions worth queuing.
_NON_ACTION = _re.compile(
    r"^(help|assist|explain|tell you|let you know|clarify|answer|continue|"
    r"keep going|elaborate|go on|see|check back|be here|appreciate|understand|"
    r"remember|think|know|be honest|admit|note)\b",
    _re.I,
)


def extract_proposal(response_text: str) -> str:
    """Pull the first concrete actionable offer out of an ELI reply, if any.

    Only genuine offers the user can affirm are returned: question-form "want me
    to …" / "shall I …", or a declarative "I can/I'll …" clause that is itself a
    question. Declarative narrative is never treated as a queued action."""
    text = (response_text or "").strip()
    if not text:
        return ""
    m = _STRONG_OFFER_RE.search(text) or _WEAK_OFFER_RE.search(text)
    if not m:
        return ""
    phrase = " ".join(m.group(1).split()).strip(" .,;:")
    if not phrase or len(phrase) < 3:
        return ""
    if len(phrase.split()) > _MAX_PROPOSAL_WORDS:
        return ""
    if _NON_ACTION.match(phrase):
        return ""
    return phrase
