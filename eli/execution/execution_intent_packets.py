from __future__ import annotations

from typing import Any, Dict

from eli.runtime.stage_packets import StagePacket, make_stage_packet


def _trim(text: str, n: int = 220) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _dictish(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "to_dict"):
        try:
            return dict(obj.to_dict())
        except Exception:
            return {"repr": repr(obj)}
    return {"repr": repr(obj)}


def build_execution_intent_packet(
    action: str | None,
    args: Dict[str, Any] | None = None,
    *,
    plan: Any = None,
    source: str = "execution_authority",
) -> StagePacket:
    plan_d = _dictish(plan)
    effective_action = str(
        action
        or plan_d.get("action")
        or plan_d.get("tool")
        or plan_d.get("name")
        or ""
    )
    effective_args = dict(args or plan_d.get("args") or plan_d.get("kwargs") or {})

    payload = {
        "action": effective_action,
        "args": effective_args,
        "plan": plan_d,
        "source": source,
    }
    return make_stage_packet(
        stage="execution_intent",
        kind="execution_intent_packet",
        payload=payload,
        summary=_trim(
            f"action={effective_action or '?'} args={len(effective_args)} source={source}"
        ),
    )


def build_execution_result_packet(
    action: str,
    args: Dict[str, Any] | None,
    result: Any,
    *,
    source: str = "executor",
) -> StagePacket:
    if isinstance(result, dict):
        result_preview = {k: result.get(k) for k in list(result.keys())[:12]}
    else:
        result_preview = {"repr": repr(result)}

    payload = {
        "action": str(action or ""),
        "args": dict(args or {}),
        "result_preview": result_preview,
        "source": source,
    }
    return make_stage_packet(
        stage="execution_result",
        kind="execution_result_packet",
        payload=payload,
        summary=_trim(f"action={action or '?'} result={repr(result)[:160]}"),
    )
