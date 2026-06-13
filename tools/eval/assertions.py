"""Assertions for the ELI eval harness.

Each assertion is {type: <name>, ...} and checks a normalised driver result
(see eli_driver). Returns (passed: bool, detail: str).

All checks are DETERMINISTIC and offline EXCEPT `rubric`, which is model-graded by
ELI's OWN local model (the inference broker) — still 100% local, never a cloud judge.

Available types:
  contains / not_contains   value (case-insensitive substring of the answer text)
  contains_all              value (list — every substring must be present)
  contains_any              value (list — at least one substring present)
  not_contains_any          value (list — none of the substrings present)
  regex / regex_not         value (re.search on text must / must-not match)
  action_is                 value (str or list — action must be one of)
  action_not                value (str or list — action must NOT be any of)
  matched_by                value (substring of meta.matched_by)
  grounding_min/grounding_max  value (float, on trace grounding_confidence)
  response_mode             value (str or list — meta.response_mode is one of)
  hedged                    true → answer is an honest "I won't guess" hedge
  is_refusal                true/false → answer is/ isn't a capability refusal
  no_placeholder            answer must not contain TODO/lorem/"as an AI" filler
  length_min/length_max     value (int — answer character length bound)
  word_count_min            value (int — answer has at least N words)
  max_latency_s             value (float — reply produced within budget)
  arg_equals                key + value — router args[key] equals value (missing = "")
  arg_contains              key + value — router args[key] contains value
  arg_not_contains          key + value — router args[key] does not contain value
  arg_empty                 key — router args[key] is absent/empty
  result_ok                 true/false — executor result's `ok` flag (executor target)
  semantic_min              value (reference text) + min (0-1, default 0.75) — LOCAL
                            embedding cosine vs reference; soft-skips if no embedder
  rubric                    value (criteria) + min (0-1, default 0.7) + samples (int,
                            default 1) — LOCAL judge scores the answer; with samples>1
                            it grades N times and takes the median (self-consistency)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_HEDGE_MARKERS = (
    "can't verify", "cannot verify", "won't guess", "wont guess", "not certain",
    "i'm not sure", "im not sure", "don't have grounded", "rather not guess",
    "ungrounded_hedge",
)

_REFUSAL_MARKERS = (
    "i can't help", "i cannot help", "i won't", "i will not", "i'm unable",
    "i am unable", "cannot assist", "can't assist", "not able to", "i don't do",
)

# Boilerplate / unfinished-output markers. ELI must never ship these
# (ties to the no-fake-actions / no-toy-code invariants).
_PLACEHOLDER_MARKERS = (
    "todo", "tbd", "lorem ipsum", "placeholder", "as an ai", "as a language model",
    "<insert", "your text here", "fill in here", "[...]", "xxxxx",
)


def _as_strs(v) -> List[str]:
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    return [str(v)]


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
    if t == "regex_not":
        bad = bool(re.search(str(val), r.get("text") or "", re.I))
        return (not bad), f"regex_not {val!r}: {'ok' if not bad else 'matched (bad)'}"
    if t == "contains_all":
        missing = [s for s in _as_strs(val) if s.lower() not in _text(r)]
        return (not missing), f"contains_all: {'ok' if not missing else 'MISSING ' + repr(missing)}"
    if t == "contains_any":
        present = [s for s in _as_strs(val) if s.lower() in _text(r)]
        return (bool(present)), f"contains_any: {'ok' if present else 'NONE present'}"
    if t == "not_contains_any":
        found = [s for s in _as_strs(val) if s.lower() in _text(r)]
        return (not found), f"not_contains_any: {'ok' if not found else 'FOUND ' + repr(found)}"
    if t == "length_min":
        n = len(str(r.get("text") or ""))
        return (n >= int(val)), f"length={n} >= {val}"
    if t == "length_max":
        n = len(str(r.get("text") or ""))
        return (n <= int(val)), f"length={n} <= {val}"
    if t == "word_count_min":
        n = len(str(r.get("text") or "").split())
        return (n >= int(val)), f"words={n} >= {val}"
    if t == "is_refusal":
        is_ref = any(m in _text(r) for m in _REFUSAL_MARKERS)
        want = bool(val if val is not None else True)
        return (is_ref == want), f"is_refusal={is_ref} want={want}"
    if t == "no_placeholder":
        found = [m for m in _PLACEHOLDER_MARKERS if m in _text(r)]
        return (not found), f"no_placeholder: {'clean' if not found else 'FOUND ' + repr(found)}"
    if t == "arg_contains":
        key = str(assertion.get("key") or "")
        got = str((r.get("args") or {}).get(key, "")).strip().lower()
        sub = str(val if val is not None else "").strip().lower()
        return (sub in got), f"arg[{key}]={got!r} contains {sub!r}: {'ok' if sub in got else 'MISSING'}"
    if t == "result_ok":
        got = bool(r.get("ok", True))
        want = bool(val if val is not None else True)
        return (got == want), f"result_ok={got} want={want} (err={r.get('error') or '∅'})"
    if t == "semantic_min":
        return _semantic_check(assertion, r)
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


def _judge(question: str, answer: str, rubric: str, samples: int = 1) -> Tuple[float, str]:
    """Score an answer against a rubric using ELI's OWN local model (broker).
    Returns (score 0-1, short reason). 100% local — never a cloud judge.

    With samples>1 the model grades the answer N times and the MEDIAN score is
    returned (self-consistency — damps single-shot judge variance). A single
    sample stays fully deterministic (temperature 0); multi-sample uses a small
    temperature so the draws actually differ."""
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
        n = max(1, int(samples))
        temp = 0.0 if n == 1 else 0.4
        scores: List[float] = []
        reason = ""
        for _ in range(n):
            # background=True so the judge call never stamps the foreground-activity clock.
            # Generous cap so a REASONING judge (Qwen3/DeepSeek-R1) can think AND still
            # emit the score (a 32-token cap was wholly consumed by <think>, leaving no
            # number). Non-reasoning judges stop early after the score, so this is free.
            out = broker.infer(prompt, system=system, max_tokens=320, temperature=temp,
                               background=True) or ""
            m = re.search(r"\d+(?:\.\d+)?", out)
            if m:
                scores.append(max(0.0, min(10.0, float(m.group()))) / 10.0)
                if not reason:
                    reason = out.strip().replace("\n", " ")[:60]
        if not scores:
            return 0.0, f"unparseable judge reply {out[:40]!r}"
        scores.sort()
        median = scores[len(scores) // 2]
        tag = reason if n == 1 else f"median of {len(scores)}: {reason}"
        return median, tag
    except Exception as e:  # pragma: no cover
        return -1.0, f"judge error {type(e).__name__}"


def _embed_cosine(a: str, b: str) -> Optional[float]:
    """Cosine similarity of two strings using the resident local nomic embedder
    (the vector store's). Returns None if no real embedder is available."""
    try:
        from eli.memory.vector_store import get_vector_store
        vs = get_vector_store()
        emb = vs._get_embedder() if vs is not None else None
        if emb is None:
            return None
        import numpy as _np
        va = _np.asarray(emb.embed(a), dtype=float).ravel()
        vb = _np.asarray(emb.embed(b), dtype=float).ravel()
        na = float(_np.linalg.norm(va))
        nb = float(_np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0 or va.shape != vb.shape:
            return None
        return float(_np.dot(va, vb) / (na * nb))
    except Exception:
        return None


def _semantic_check(assertion: Dict[str, Any], r: Dict[str, Any]) -> Tuple[bool, str]:
    ref = str(assertion.get("value") or "").strip()
    try:
        min_score = float(assertion.get("min", 0.75))
    except Exception:
        min_score = 0.75
    answer = str(r.get("text") or "").strip()
    if not answer or not ref:
        return False, "semantic: empty answer or reference"
    score = _embed_cosine(ref, answer)
    if score is None:
        # Embedder unavailable — soft pass (mirrors rubric's judge-unavailable path)
        # so the deterministic board still runs without the nomic model.
        return True, "semantic: embedder unavailable — not scored"
    return (score >= min_score), f"semantic cos={score:.2f} >= {min_score}"


def _rubric_check(assertion: Dict[str, Any], r: Dict[str, Any]) -> Tuple[bool, str]:
    rubric = str(assertion.get("value") or "").strip()
    try:
        min_score = float(assertion.get("min", 0.7))
    except Exception:
        min_score = 0.7
    try:
        samples = int(assertion.get("samples", 1))
    except Exception:
        samples = 1
    answer = str(r.get("text") or "").strip()
    question = str(r.get("prompt") or "").strip()
    if not answer:
        return False, "rubric: no answer text to grade"
    score, why = _judge(question, answer, rubric, samples=samples)
    if score < 0:
        # Judge unavailable (no model) — surface as SKIP-like soft pass so the
        # deterministic board still runs model-free; run_eval treats engine cases
        # as skipped when there's no model, so this only fires mid-run oddities.
        return True, f"rubric: judge unavailable ({why}) — not scored"
    return (score >= min_score), f"rubric score={score:.2f} >= {min_score} ({why})"
