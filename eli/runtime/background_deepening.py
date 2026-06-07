"""Stage 3b — background deepening.

When a QUICK answer is poorly grounded on a checkable factual turn, the fast reply
is returned immediately (quick never deepens synchronously — Stage 2), and a
background thread keeps gathering: it re-dispatches the agent bus broadly at a
deeper mode with a larger gather budget, and — only if it genuinely crosses a
grounding bar — surfaces a better answer asynchronously via the proactive panel.

Tightly gated: quick-mode only, clearly-low grounding only, checkable-factual
only, deduped by question signature, at most one in flight, with a re-run
cooldown. Kill switch: env ELI_BACKGROUND_DEEPEN=0 or the `cog.background_deepen`
tunable. Never surfaces a guess (re-checks grounding + degeneracy before posting).
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_LOCK = threading.RLock()
_INFLIGHT: set = set()        # question signatures currently deepening (dedupe)
_DONE: Dict[str, float] = {}  # signature -> last-completed ts (re-run cooldown)
_MAX_INFLIGHT = 1
_RERUN_COOLDOWN_S = 600.0
_LOW_GROUNDING = 0.40         # only deepen clearly-weak answers
_SURFACE_BAR = 0.55           # only surface if the deepened pass crosses this


def _enabled() -> bool:
    if os.environ.get("ELI_BACKGROUND_DEEPEN", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        from eli.core.cognition_tunables import get_tunable
        return int(get_tunable("cog.background_deepen")) != 0
    except Exception:
        return True


def _sig(user_input: str) -> str:
    return hashlib.sha1((user_input or "").strip().lower().encode("utf-8")).hexdigest()[:12]


def schedule(engine: Any, user_input: str, intent: Dict[str, Any],
             bus_result: Any, reasoning_mode: Optional[str]) -> bool:
    """Maybe schedule a background deepen. Non-blocking. Returns True if scheduled."""
    if not _enabled():
        return False
    try:
        from eli.cognition.reasoning_modes import canonical_mode
        if canonical_mode(reasoning_mode) != "quick":
            return False  # deeper modes already deepen synchronously (Stage 2)
    except Exception:
        return False
    try:
        grounding = float(getattr(bus_result, "grounding_confidence", 0.0) or 0.0)
    except Exception:
        grounding = 0.0
    if grounding >= _LOW_GROUNDING:
        return False
    try:
        from eli.runtime.grounding_escalation import classify_factual
        is_fact, _domain = classify_factual(user_input)
    except Exception:
        is_fact = False
    if not is_fact:
        return False  # banter/opinion/command/meta → never deepen

    sig = _sig(user_input)
    now = time.time()
    with _LOCK:
        if len(_INFLIGHT) >= _MAX_INFLIGHT or sig in _INFLIGHT:
            return False
        if now - _DONE.get(sig, 0.0) < _RERUN_COOLDOWN_S:
            return False
        _INFLIGHT.add(sig)

    try:
        from eli.runtime.background_tasks import get_background_tasks
        get_background_tasks().submit(
            f"deepen:{(user_input or '')[:40]}",
            _worker, engine, user_input, dict(intent or {}), sig,
        )
        log.debug(f"[DEEPEN] scheduled background deepen (grounding={grounding:.2f}) sig={sig}")
        return True
    except Exception as e:
        with _LOCK:
            _INFLIGHT.discard(sig)
        log.debug(f"[DEEPEN] schedule failed: {e}")
        return False


def _worker(engine: Any, user_input: str, intent: Dict[str, Any], sig: str) -> None:
    try:
        from eli.runtime.grounding_escalation import _redispatch_broad, _is_degenerate
        deep = _redispatch_broad(engine, user_input, intent,
                                 reasoning_mode="advanced", gather_mult=2.0)
        if deep is None:
            return
        dg = float(getattr(deep, "grounding_confidence", 0.0) or 0.0)
        if dg < _SURFACE_BAR:
            log.debug(f"[DEEPEN] still ungrounded ({dg:.2f}) — not surfacing a guess")
            return
        evidence = deep.to_context_block() if hasattr(deep, "to_context_block") else ""
        if not evidence.strip():
            return
        answer = engine._synthesize_answer(
            evidence, user_input, reasoning_mode="advanced", action="SELF_REPORT")
        if not answer or _is_degenerate(answer):
            return
        _surface(user_input, answer, dg)
    except Exception as e:
        log.debug(f"[DEEPEN] worker failed: {e}")
    finally:
        with _LOCK:
            _INFLIGHT.discard(sig)
            _DONE[sig] = time.time()


def _surface(user_input: str, answer: str, grounding: float) -> None:
    """Push the deepened answer to the proactive panel (non-intrusive)."""
    note = (f"I looked deeper into “{(user_input or '').strip()[:80]}” — "
            f"a more grounded answer:\n\n{(answer or '').strip()}")
    try:
        from eli.planning.proactive_daemon import get_daemon
        d = get_daemon()
        q = getattr(d, "suggestion_queue", None) if d is not None else None
        if q is not None:
            q.put(("deepened_answer", {"suggestion": note, "question": user_input,
                                       "grounding": grounding}))
            log.debug(f"[DEEPEN] surfaced deepened answer (grounding={grounding:.2f})")
            return
    except Exception as e:
        log.debug(f"[DEEPEN] surface failed: {e}")
    log.info("[DEEPEN] (no proactive surface) " + note[:200])


__all__ = ["schedule"]
