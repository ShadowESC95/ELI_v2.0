"""Deterministic assertions for the ELI eval harness.

Each assertion is {type: <name>, ...} and checks a normalised driver result
(see eli_driver). Returns (passed: bool, detail: str). All offline, no judge.

Available types:
  contains / not_contains   value (case-insensitive substring of the answer text)
  regex                     value (re.search on text)
  action_is                 value (str or list — action must be one of)
  action_not                value (str or list — action must NOT be any of)
  matched_by                value (substring of meta.matched_by)
  grounding_min/grounding_max  value (float, on trace grounding_confidence)
  response_mode             value (str or list — meta.response_mode is one of)
  hedged                    true → answer is an honest "I won't guess" hedge
  max_latency_s             value (float — reply produced within budget)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_HEDGE_MARKERS = (
    "can't verify", "cannot verify", "won't guess", "wont guess", "not certain",
    "i'm not sure", "im not sure", "don't have grounded", "rather not guess",
    "ungrounded_hedge",
)


def _text(r: Dict[str, Any]) -> str:
    return str(r.get("text") or "").lower()


def _as_list(v) -> List[str]:
    if isinstance(v, (list, tuple, set)):
        return [str(x).upper() for x in v]
    return [str(v).upper()]


def check(assertion: Dict[str, Any], r: Dict[str, Any]) -> Tuple[bool, str]:
    t = str(assertion.get("type") or "").strip().lower()
    val = assertion.get("value")

    if t == "contains":
        ok = str(val).lower() in _text(r)
        return ok, f"contains {val!r}: {'yes' if ok else 'MISSING'}"
    if t == "not_contains":
        ok = str(val).lower() not in _text(r)
        return ok, f"not_contains {val!r}: {'ok' if ok else 'FOUND (bad)'}"
    if t == "regex":
        ok = bool(re.search(str(val), r.get("text") or "", re.I))
        return ok, f"regex {val!r}: {'match' if ok else 'no match'}"
    if t == "action_is":
        want = _as_list(val)
        got = str(r.get("action") or "").upper()
        return (got in want), f"action={got or '∅'} want∈{want}"
    if t == "action_not":
        bad = _as_list(val)
        got = str(r.get("action") or "").upper()
        return (got not in bad), f"action={got or '∅'} must∉{bad}"
    if t == "matched_by":
        ok = str(val).lower() in str(r.get("matched_by") or "").lower()
        return ok, f"matched_by~{val!r}: got {r.get('matched_by')!r}"
    if t == "response_mode":
        want = _as_list(val)
        got = str(r.get("response_mode") or "").upper()
        return (got in want), f"response_mode={got or '∅'} want∈{want}"
    if t == "grounding_min":
        g = r.get("grounding")
        ok = g is not None and float(g) >= float(val)
        return ok, f"grounding={g} >= {val}"
    if t == "grounding_max":
        g = r.get("grounding")
        ok = g is not None and float(g) <= float(val)
        return ok, f"grounding={g} <= {val}"
    if t == "hedged":
        is_hedge = (str(r.get("response_mode") or "").lower() == "ungrounded_hedge"
                    or any(m in _text(r) for m in _HEDGE_MARKERS))
        return (is_hedge == bool(val)), f"hedged={is_hedge} want={bool(val)}"
    if t == "max_latency_s":
        lat = float(r.get("latency_s") or 0.0)
        ok = lat <= float(val)
        return ok, f"latency={lat}s <= {val}s"

    return False, f"unknown assertion type {t!r}"
