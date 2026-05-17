from __future__ import annotations

from typing import Any, Dict, Tuple

from eli.runtime.stage_packet_store import append_stage_packet, current_stage_packets
from eli.execution.execution_intent_packets import (
    build_execution_intent_packet,
    build_execution_result_packet,
)


def _payload_from_packet_like(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        if obj.get("kind") == "execution_intent_packet" and isinstance(obj.get("payload"), dict):
            return dict(obj["payload"])
        return dict(obj)
    if hasattr(obj, "kind") and hasattr(obj, "payload"):
        try:
            if getattr(obj, "kind", "") == "execution_intent_packet":
                return dict(getattr(obj, "payload", {}) or {})
        except Exception:
            return {}
    return {}


def latest_execution_intent_payload() -> Dict[str, Any]:
    for pkt in reversed(current_stage_packets()):
        try:
            if getattr(pkt, "kind", "") == "execution_intent_packet":
                return dict(getattr(pkt, "payload", {}) or {})
        except Exception:
            pass
    return {}


def canonicalize_execution_call(action: Any, args: Dict[str, Any] | None = None) -> Tuple[Any, str, Dict[str, Any]]:
    payload = _payload_from_packet_like(action)

    if payload:
        packet = action
        act = str(payload.get("action") or "")
        call_args = dict(payload.get("args") or {})
        return packet, act, call_args

    if isinstance(action, dict) and ("action" in action or "tool" in action or "name" in action):
        packet = build_execution_intent_packet(
            action=str(action.get("action") or action.get("tool") or action.get("name") or ""),
            args=dict(action.get("args") or action.get("kwargs") or args or {}),
            plan=action,
            source="dict_call",
        )
        append_stage_packet(packet)
        payload = dict(packet.payload or {})
        return packet, str(payload.get("action") or ""), dict(payload.get("args") or {})

    try:
        from eli.runtime.evidence_store import get_current_execution_plan
        plan = get_current_execution_plan()
    except Exception:
        plan = None

    packet = build_execution_intent_packet(
        action=str(action or ""),
        args=dict(args or {}),
        plan=plan,
        source="executor_call",
    )
    append_stage_packet(packet)
    payload = dict(packet.payload or {})
    return packet, str(payload.get("action") or ""), dict(payload.get("args") or {})


def record_execution_result(action: str, args: Dict[str, Any] | None, result: Any) -> None:
    append_stage_packet(build_execution_result_packet(action, args or {}, result))

