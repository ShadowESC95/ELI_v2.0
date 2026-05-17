"""
Central visible-output contract for ELI.

Anything that may be displayed, spoken, persisted as assistant-visible text,
or returned through a direct bypass path should pass through visible_text().
"""

from __future__ import annotations

import re
from typing import Any


_PRIVATE_MARKER_RE = re.compile(
    r"(?is)"
    r"(chain[-_ ]?of[-_ ]?thought|reasoning chain|scratchpad|hidden reasoning|"
    r"private reasoning|internal reasoning|tree[-_ ]?of[-_ ]?thoughts?|"
    r"self[-_ ]?consistency|constitutional critique|draft critique|"
    r"critique pass|revision pass|active reasoning mode|reasoning mode self-awareness)"
)

_FINAL_MARKER_RE = re.compile(
    r"(?is)"
    r"(?:^|[\n\r]|[\.\!\?]\s+|\b)"
    r"(?:final\s+answer|final|answer|response)\s*[:\-]\s*"
)


def _extract_explicit_final(text: str) -> str:
    """
    If a model emits private scaffolding but also provides an explicit final
    section, keep the final section instead of collapsing everything to "...".
    """
    s = "" if text is None else str(text)
    if not s.strip():
        return ""

    if not _PRIVATE_MARKER_RE.search(s):
        return s

    matches = list(_FINAL_MARKER_RE.finditer(s))
    if not matches:
        return s

    start = matches[-1].end()
    final = s[start:].strip()

    # Remove obvious trailing private blocks if the model put them after final.
    final = re.split(
        r"(?is)\n\s*(?:chain[-_ ]?of[-_ ]?thought|scratchpad|hidden reasoning|private reasoning|critique pass)\s*[:\-]",
        final,
        maxsplit=1,
    )[0].strip()

    return final or s


def visible_text(
    text: Any,
    *,
    user_input: str = "",
    is_grounded: bool = False,
    evidence: str | None = None,
) -> str:
    raw = _extract_explicit_final("" if text is None else str(text))

    try:
        from eli.cognition.response_sanitizer import sanitize_assistant_text
        raw = sanitize_assistant_text(raw)
    except Exception:
        pass

    try:
        from eli.cognition.output_governor import govern_output, normalize_assistant_text
        raw = normalize_assistant_text(user_input or "", raw)
        raw = govern_output(raw, is_grounded=is_grounded, evidence=evidence or "")
    except Exception:
        pass

    try:
        from eli.cognition.response_sanitizer import sanitize_assistant_text
        raw = sanitize_assistant_text(raw)
    except Exception:
        pass

    return str(raw or "").strip()


__all__ = ["visible_text"]
