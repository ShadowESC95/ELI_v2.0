"""Split one utterance that chains MULTIPLE imperative commands into its parts.

    "close steam and set an alarm for 7am"   → ["close steam", "set an alarm for 7am"]
    "open spotify then play vincent's tale"   → ["open spotify", "play vincent's tale"]

The engine runs each part through its normal pipeline (route → agents → execute) and
combines the results — so a single sentence can trigger several actions.

Guards against false splits (the hard part):
  • must START with an imperative verb (so questions / statements aren't split);
  • EVERY segment must also start with an imperative verb — so "play tom and jerry",
    "open the file and folder manager", "set the volume and brightness" stay whole;
  • no "?" (compound questions are handled by the engine's question splitter);
  • 2–5 segments.

Pure/deterministic — no model, no I/O. The engine additionally verifies ≥2 segments
route to real actions before executing, as a second safety net.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Conjunctions that separate chained commands. "and then" / "and also" before bare
# "and"/"then" so they're consumed as one separator.
_CONJ_RX = re.compile(
    r"\s+(?:and then|and also|;|,\s*then\s+|\bthen\b|\band\b)\s+", re.I)

# Imperative action verbs a real command starts with.
_IMP_START = re.compile(
    r"^\s*(open|launch|start|play|pause|stop|close|quit|kill|set|get|fetch|show"
    r"|check|run|remind|turn|mute|unmute|screenshot|take|send|search|find|read"
    r"|generate|create|write|build|schedule|update|download|enable|disable|email"
    r"|message|post|analyse|analyze|examine|review|make|give me|tell me to)\b", re.I)


def _trim_trailing_chatter(seg: str) -> str:
    """Drop a conversational sentence fused onto the end of a command segment, e.g.
    'play evil by eminem. haha no, you already told me of the tokamaks' →
    'play evil by eminem'. Without this the trailing banter became part of the media
    title and was searched verbatim.

    Conservative on purpose: only cut at a '. ' / '! ' / '? ' boundary when the tail is
    ≥3 words and is NOT itself imperative — so short titles with internal punctuation
    ('play mr. brightside') and any genuinely chained command survive untouched."""
    for mt in re.finditer(r"[.!?]\s+", seg):
        head = seg[:mt.start()].strip(" ,.")
        tail = seg[mt.end():].strip()
        if not head or _IMP_START.search(tail):
            continue
        if len(tail.split()) >= 3:
            return head
    return seg


def split_commands(text: str, *, max_parts: int = 5) -> Optional[List[str]]:
    """Return the imperative command segments if `text` chains ≥2 of them, else None."""
    t = (text or "").strip()
    if not t or "?" in t:
        return None
    if not _IMP_START.search(t):
        return None
    parts = [p.strip(" ,.") for p in _CONJ_RX.split(t) if p.strip(" ,.")]
    if not (2 <= len(parts) <= max_parts):
        return None
    if not all(_IMP_START.search(p) for p in parts):
        return None
    return [_trim_trailing_chatter(p) for p in parts]


__all__ = ["split_commands"]
