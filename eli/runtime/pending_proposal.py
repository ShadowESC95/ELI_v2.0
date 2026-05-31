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

_OFFER_RE = _re.compile(
    r"\b(?:want me to|shall i|should i|would you like me to|do you want me to|"
    r"i can|i could|i'?ll|happy to)\s+(.+?)(?:\?|,| or |$)",
    _re.I,
)

# Phrases that are conversational, not real actions worth queuing.
_NON_ACTION = _re.compile(
    r"^(help|assist|explain|tell you|let you know|clarify|answer|continue|"
    r"keep going|elaborate|go on|see|check back|be here)\b",
    _re.I,
)


def extract_proposal(response_text: str) -> str:
    """Pull the first concrete actionable offer out of an ELI reply, if any."""
    text = (response_text or "").strip()
    if not text:
        return ""
    m = _OFFER_RE.search(text)
    if not m:
        return ""
    phrase = " ".join(m.group(1).split()).strip(" .,;:")
    if not phrase or len(phrase) < 3:
        return ""
    if _NON_ACTION.match(phrase):
        return ""
    return phrase
