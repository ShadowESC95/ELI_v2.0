"""Canonical 12-stage pipeline trace — single numbering for blueprint, orchestrator, and engine.

Every runtime path logs via ``log_pipeline_stage()`` so "stage 12" always means
LEARNING + STATE UPDATE from ``pipeline.py`` STEPS, not an ad-hoc sub-label.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# Mirrors eli/kernel/pipeline.py STEPS indices 0..11 → stage numbers 1..12.
STAGE_NAMES: Dict[int, str] = {
    1: "PERCEIVE_INGEST",
    2: "INPUT_GUARDS",
    3: "ROUTER",
    4: "GROUNDING_GATE",
    5: "PLANNER",
    6: "AGENT_BUS",
    7: "CONTEXT_ASSEMBLY",
    8: "INFERENCE_BROKER",
    9: "REASONING_SYNTHESIS",
    10: "OUTPUT_GOVERNOR",
    11: "RESPONSE_DELIVERY",
    12: "LEARNING_STATE_UPDATE",
}

# Orchestrator internal trace keys → canonical stage numbers (for cross-path debug).
ORCH_KEY_TO_STAGE: Dict[str, int] = {
    "stage_1": 3,
    "stage_2": 2,
    "stage_3": 5,
    "stage_4": 5,
    "stage_5_6_7": 6,
    "stage_8": 7,
    "stage_9": 7,
    "stage_10": 7,
    "stage_10_5": 7,
    "stage_11": 9,
    "stage_12": 12,
    "agent_bus_nonchat": 6,
    "agent_bus_specialists": 6,
}


def stage_label(stage: int) -> str:
    return STAGE_NAMES.get(int(stage), f"STAGE_{stage}")


def log_pipeline_stage(
    stage: int,
    *,
    component: str,
    detail: str = "",
    req_id: str = "",
    **fields: Any,
) -> None:
    """Unified pipeline log line: ``[PIPELINE] S06 AGENT_BUS orchestrator …``."""
    try:
        num = int(stage)
    except Exception:
        num = 0
    name = stage_label(num)
    parts = [f"S{num:02d}", name, str(component or "unknown")]
    if detail:
        parts.append(str(detail))
    if req_id:
        parts.append(f"req={req_id}")
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    log.debug("[PIPELINE] " + " ".join(parts))


def map_orch_trace_key(key: str) -> int:
    return int(ORCH_KEY_TO_STAGE.get(str(key or ""), 0))


def orch_trace_note(key: str, value: str = "") -> str:
    """Human-readable note tying an orchestrator sub-step to the canonical stage."""
    st = map_orch_trace_key(key)
    if not st:
        return str(value or key)
    return f"canonical=S{st:02d} {stage_label(st)} | {key}={value}"
