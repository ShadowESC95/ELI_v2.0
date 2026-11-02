"""Conservative, model-output-based exact-answer formatting for ELI.

This policy must not infer a missing answer, change a tool result or override an
external factual uncertainty gate. It only enforces an explicit user format
contract when the model's text already contains a verifiable candidate.
"""
from __future__ import annotations

from datetime import date
import re
from typing import Optional, Tuple

from eli.cognition.supplied_in_message import worked_out_date

_ISO = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_STRICT_DATE = re.compile(r"\bYYYY-MM-DD\s+only\b", re.I)
_STRICT_UNKNOWN = re.compile(
    r"\b(?:say|reply|answer)\s+(?:with\s+)?(?:exactly\s+)?UNKNOWN\s+only\b", re.I
)
_STRICT_YES_NO = re.compile(
    r"\b(?:answer|reply|respond)\s+(?:with\s+)?YES\s+or\s+NO\s+only\b", re.I
)


def _iso_dates(s: str):
    dates = []
    for found in _ISO.findall(s):
        try:
            dates.append(date.fromisoformat(found).isoformat())
        except ValueError:
            continue    # four digits, two and two that are not a date
    return dates


def enforce_explicit_output_contract(prompt: str, response: str) -> Tuple[str, Optional[str]]:
    """Return (visible_response, applied_contract_or_None).

    Fails open: unrelated or ambiguous responses are returned unchanged.
    Contracts are about output format, not permission to execute commands.
    """
    user = str(prompt or "")
    raw = str(response or "")
    stripped = raw.strip()
    if not user.strip() or not stripped:
        return raw, None

    if _STRICT_UNKNOWN.search(user):
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if lines and lines[0].strip("`\"' ") == "UNKNOWN":
            # Abstention must be the model's own first-line conclusion.
            return "UNKNOWN", "unknown_only"
        return raw, None

    if _STRICT_YES_NO.search(user):
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if lines and lines[0].strip("`\"' .!").upper() in {"YES", "NO"}:
            choice = lines[0].strip("`\"' .!").upper()
            # Do not flatten a response that explicitly contradicts its first line.
            if re.search(rf"\b{'NO' if choice == 'YES' else 'YES'}\b", "\n".join(lines[1:]), re.I):
                return raw, None
            return choice, "yes_no_only"
        return raw, None

    # ELI_V6_EXACT_IDENTIFIER_V1
    # Repeat an identifier verbatim only when the exact same unique identifier
    # occurs in both the user's request and the response. This is output
    # shaping, not authorization, verification or tool execution.
    if re.search(r"\b(?:repeat|reply|respond|output|print|return)\s+(?:exactly\s+)?(?:the\s+)?identifier\b", user, re.I):
        token_pattern = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9]*-[A-Za-z0-9][A-Za-z0-9_-]*)(?![A-Za-z0-9_-])")
        requested = set(token_pattern.findall(user))
        present = set(token_pattern.findall(stripped))
        if len(requested) == 1 and present == requested:
            identifier = next(iter(requested))
            if re.match(rf"^\s*[`\"']?{re.escape(identifier)}(?:\b|\s|[.!,])", stripped):
                return identifier, "identifier_only_verified"
    if _STRICT_DATE.search(user):
        derived = worked_out_date(user)
        candidates = _iso_dates(stripped)
        if derived and derived in candidates:
            return derived, "date_only_verified"
        # A standalone date answer is already compliant. Do not mine an external
        # fact explanation or guess among several conflicting dates.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped) and candidates:
            return stripped, None
    return raw, None
