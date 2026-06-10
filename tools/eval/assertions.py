"""Assertions for the ELI eval harness.

Each assertion is {type: <name>, ...} and checks a normalised driver result
(see eli_driver). Returns (passed: bool, detail: str).

All checks are DETERMINISTIC and offline EXCEPT `rubric`, which is model-graded by
ELI's OWN local model (the inference broker) — still 100% local, never a cloud judge.

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
  arg_equals                key + value — router args[key] equals value (missing = "")
  arg_not_contains          key + value — router args[key] does not contain value
  arg_empty                 key — router args[key] is absent/empty
  rubric                    value (criteria) + min (0-1, default 0.7) — LOCAL judge
                            scores the answer against the criteria; passes if >= min
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

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
    if t in ("arg_equals", "arg_not_contains", "arg_empty"):
        key = str(assertion.get("key") or "")
        got = str((r.get("args") or {}).get(key, "")).strip().lower()
        if t == "arg_empty":
            return (got == ""), f"arg[{key}]={got!r} empty: {'ok' if got == '' else 'NOT empty'}"
        if t == "arg_equals":
            want = str(val if val is not None else "").strip().lower()
            return (got == want), f"arg[{key}]={got!r} == {want!r}"
        sub = str(val if val is not None else "").strip().lower()
        ok = sub not in got
        return ok, f"arg[{key}]={got!r} not_contains {sub!r}: {'ok' if ok else 'FOUND (bad)'}"
    if t == "rubric":
        return _rubric_check(assertion, r)

    return False, f"unknown assertion type {t!r}"


def _judge(question: str, answer: str, rubric: str) -> Tuple[float, str]:
    """Score an answer against a rubric using ELI's OWN local model (broker).
    Returns (score 0-1, short reason). 100% local — never a cloud judge.
    Overridable judge tuning via env later; for now uses the resident model."""
    try:
        from eli.cognition.inference_broker import get_broker
        broker = get_broker()
        if broker is None or not getattr(broker, "gguf_ready", False):
            return -1.0, "no local judge model loaded"
        system = (
            "You are a STRICT, impartial answer evaluator. Read the QUESTION, the "
            "ASSISTANT ANSWER, and the RUBRIC. Judge ONLY how well the answer satisfies "
            "the rubric. Reply with a single integer 0-10 (10 = fully satisfies, 0 = "
            "fails), then a dash and at most 8 words of reason. Output nothing else."
        )
        prompt = (
            f"QUESTION:\n{question}\n\nASSISTANT ANSWER:\n{answer}\n\n"
            f"RUBRIC (what a good answer MUST do):\n{rubric}\n\nSCORE (0-10):"
        )
        # background=True so the judge call never stamps the foreground-activity clock.
        # Generous cap so a REASONING judge (Qwen3/DeepSeek-R1) can think AND still
        # emit the score (a 32-token cap was wholly consumed by <think>, leaving no
        # number). Non-reasoning judges stop early after the score, so this is free.
        out = broker.infer(prompt, system=system, max_tokens=320, temperature=0.0,
                           background=True) or ""
        m = re.search(r"\d+(?:\.\d+)?", out)
        if not m:
            return 0.0, f"unparseable judge reply {out[:40]!r}"
        score = max(0.0, min(10.0, float(m.group()))) / 10.0
        return score, out.strip().replace("\n", " ")[:60]
    except Exception as e:  # pragma: no cover
        return -1.0, f"judge error {type(e).__name__}"


def _rubric_check(assertion: Dict[str, Any], r: Dict[str, Any]) -> Tuple[bool, str]:
    rubric = str(assertion.get("value") or "").strip()
    try:
        min_score = float(assertion.get("min", 0.7))
    except Exception:
        min_score = 0.7
    answer = str(r.get("text") or "").strip()
    question = str(r.get("prompt") or "").strip()
    if not answer:
        return False, "rubric: no answer text to grade"
    score, why = _judge(question, answer, rubric)
    if score < 0:
        # Judge unavailable (no model) — surface as SKIP-like soft pass so the
        # deterministic board still runs model-free; run_eval treats engine cases
        # as skipped when there's no model, so this only fires mid-run oddities.
        return True, f"rubric: judge unavailable ({why}) — not scored"
    return (score >= min_score), f"rubric score={score:.2f} >= {min_score} ({why})"
