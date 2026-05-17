from __future__ import annotations

from typing import Any, Dict

from eli.runtime.stage_packets import make_stage_packet


def _trim(text: str, n: int = 220) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def route_packet(obj: Any):
    d = obj.to_dict() if hasattr(obj, "to_dict") else (dict(obj) if isinstance(obj, dict) else {"value": repr(obj)})
    return make_stage_packet(
        stage="route",
        kind="route_decision",
        payload=d,
        summary=_trim(f"action={d.get('action', '?')} conf={d.get('confidence', '?')}"),
        confidence=(d.get("confidence") if isinstance(d.get("confidence"), (int, float)) else None),
    )


def plan_packet(obj: Any):
    d = obj.to_dict() if hasattr(obj, "to_dict") else (dict(obj) if isinstance(obj, dict) else {"value": repr(obj)})
    return make_stage_packet(
        stage="plan",
        kind="execution_plan",
        payload=d,
        summary=_trim(f"action={d.get('action', '?')} quick={d.get('quick', '?')}"),
    )


def evidence_packet(count: int, extra: Dict[str, Any] | None = None):
    payload = {"count": int(count or 0)}
    if extra:
        payload.update(extra)
    return make_stage_packet(
        stage="evidence",
        kind="evidence_snapshot",
        payload=payload,
        summary=f"evidence_count={int(count or 0)}",
    )


def final_request_packet(obj: Any):
    d = obj.to_dict() if hasattr(obj, "to_dict") else (dict(obj) if isinstance(obj, dict) else {"value": repr(obj)})
    return make_stage_packet(
        stage="final_request",
        kind="final_answer_request",
        payload=d,
        summary=_trim(f"request_id={d.get('request_id', '?')} action={d.get('action', '?')} quick={d.get('quick', '?')}"),
    )


def generation_packet(prompt: str):
    return make_stage_packet(
        stage="generation",
        kind="prompt_dispatch",
        payload={"prompt_preview": str(prompt or "")[:1200]},
        summary=_trim(prompt, 180),
    )


def output_packet(result: Any):
    text = result if isinstance(result, str) else repr(result)
    return make_stage_packet(
        stage="output",
        kind="model_output",
        payload={"preview": str(text)[:1200]},
        summary=_trim(text, 180),
    )
