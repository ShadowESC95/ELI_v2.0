from __future__ import annotations

import re
from typing import Any

try:
    from eli.cognition.reasoning_modes import apply_final_reasoning_contract
except Exception:  # pragma: no cover
    def apply_final_reasoning_contract(text, mode=None):
        return str(text or "")

_STAGE_PREFIX_RE = re.compile(
    r'^\s*(?:eli|assistant|calmly|quietly|softly|gently|warmly|plainly|dryly)\s*:\s*["\']?',
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r'(?i)(?:\[(?:user|username|name)\]|<(?:user|local_user|username|name)>)'
)
# Generic assistant-speak openers that contradict ELI's dry personality.
# Strip only when they are the FULL opening clause (followed by comma/space/newline).
_FILLER_OPENER_RE = re.compile(
    r'^\s*(?:'
    r'of course[,!.]?\s*'
    r'|certainly[,!.]?\s*'
    r'|sure(?:\s+thing)?[,!.]?\s*'
    r'|absolutely[,!.]?\s*'
    r'|happy\s+to\s+help[,!.]?\s*'
    r'|great\s+question[,!.]?\s*'
    r'|excellent\s+question[,!.]?\s*'
    r'|good\s+question[,!.]?\s*'
    r'|that\'s\s+a\s+great\s+(?:question|point)[,!.]?\s*'
    r'|i\'d\s+be\s+happy\s+to[,!.]?\s*'
    r'|i\'m\s+glad\s+you\s+asked[,!.]?\s*'
    r'|short\s+answer\s*:\s*'
    r')',
    re.IGNORECASE,
)

def sanitize_assistant_text(text: Any) -> str:
    out = apply_final_reasoning_contract(text)
    out = _STAGE_PREFIX_RE.sub("", out)
    out = _FILLER_OPENER_RE.sub("", out)
    out = _PLACEHOLDER_RE.sub("", out)
    out = re.sub(r"^[\s\"']+|[\s\"']+$", "", out)
    out = re.sub(r'\s{2,}', ' ', out)
    out = re.sub(r'\s+([,.:;!?])', r'\1', out)
    out = out.strip()
    return out or "..."

def normalize_assistant_text(text: Any) -> str:
    return sanitize_assistant_text(text)

def clean_assistant_text(text: Any) -> str:
    return sanitize_assistant_text(text)

__all__ = [
    "sanitize_assistant_text",
    "normalize_assistant_text",
    "clean_assistant_text",
]


# Note: role-prefix and HR-phrase polish lives in eli.cognition.output_governor
# (govern_output → clean_response_style). This module only exposes the
# sanitize_assistant_text helper above.

