"""Stage 12 coordinator — single entry for post-response learning and persistence hooks."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from eli.kernel.pipeline_trace import log_pipeline_stage
from eli.utils.log import get_logger

log = get_logger(__name__)


def finalize_turn(
    engine: Any,
    *,
    user_input: str,
    response: str,
    intent: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    trace: Optional[Dict[str, Any]] = None,
    command: bool = False,
    confidence: Optional[float] = None,
    grounding_confidence: Optional[float] = None,
    agents_used: Optional[List[str]] = None,
    req_id: str = "",
) -> None:
    """Run all Stage-12 side effects in a fixed, observable order."""
    intent = dict(intent or {})
    result = dict(result or {})
    trace = dict(trace or {})

    log_pipeline_stage(
        12,
        component="learning_coordinator",
        detail="begin",
        req_id=req_id,
        action=str(intent.get("action") or "CHAT"),
    )

    # 1. Confidence / trace metadata for GUI and world panel
    try:
        if hasattr(engine, "_publish_last_response_meta"):
            engine._publish_last_response_meta(
                trace,
                action=str(intent.get("action") or "CHAT"),
                result_action=str(result.get("action") or intent.get("action") or "CHAT"),
                confidence=confidence,
                agents_used=list(agents_used or []),
                evidence_used=bool(result.get("evidence_used") or trace.get("evidence_used")),
                grounded=bool(grounding_confidence and grounding_confidence >= 0.5),
                response=str(response or ""),
                grounding_confidence=grounding_confidence,
                user_input=str(user_input or ""),
            )
    except Exception as exc:
        log.debug(f"[LEARNING] publish meta failed: {exc}")

    # 2. Persist assistant turn (governed, proposal capture)
    try:
        if response and hasattr(engine, "_store_assistant_turn"):
            engine._store_assistant_turn(str(response))
    except Exception as exc:
        log.debug(f"[LEARNING] store assistant turn failed: {exc}")

    # 3. Command/action learning (habits, ledger, app cmd memory)
    try:
        if hasattr(engine, "_learn_from_result"):
            _learn_intent = dict(intent)
            _learn_intent.setdefault("user_input", user_input)
            engine._learn_from_result(_learn_intent, result)
    except Exception as exc:
        log.debug(f"[LEARNING] learn_from_result failed: {exc}")

    # 4. Session digest is triggered inside _learn_from_result (every 20 turns)

    log_pipeline_stage(
        12,
        component="learning_coordinator",
        detail="completed",
        req_id=req_id,
        chars=len(str(response or "")),
        command=command,
    )
