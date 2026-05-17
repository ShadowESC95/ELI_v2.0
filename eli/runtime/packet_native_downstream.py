from __future__ import annotations

from typing import Any, Dict, List

from eli.runtime.stage_packets import StagePacket, make_stage_packet
from eli.runtime.stage_packet_store import current_stage_packets


def _trim(text: str, n: int = 220) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _obj_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        try:
            return dict(obj.to_dict())
        except Exception:
            pass
    if isinstance(obj, dict):
        return dict(obj)
    return {"repr": repr(obj)}


def build_context_assembly_packet(
    *,
    user_input: str,
    route: Any = None,
    plan: Any = None,
    evidence: Any = None,
    final_request: Any = None,
    stage_packets: List[StagePacket] | None = None,
) -> StagePacket:
    rd = _obj_dict(route)
    pd = _obj_dict(plan)
    ed = _obj_dict(evidence)
    fd = _obj_dict(final_request)
    sps = [p.to_dict() if hasattr(p, "to_dict") else dict(p) for p in (stage_packets or current_stage_packets())]

    payload = {
        "user_input": str(user_input or ""),
        "route": rd,
        "plan": pd,
        "evidence": ed,
        "final_request": fd,
        "stage_packet_count": len(sps),
        "stage_packet_kinds": [str(x.get("kind") or "") for x in sps],
    }
    return make_stage_packet(
        stage="context_assembly",
        kind="canonical_context_packet",
        payload=payload,
        summary=_trim(
            f"action={rd.get('action', '?')} quick={pd.get('quick', '?')} evidence={len(ed.get('items', []) or []) if isinstance(ed.get('items'), list) else ed.get('count', 0)} packets={len(sps)}"
        ),
    )


def build_governed_output_packet(result: Any) -> StagePacket:
    text = result if isinstance(result, str) else repr(result)
    return make_stage_packet(
        stage="governed_output",
        kind="governed_output_packet",
        payload={"preview": str(text)[:1600]},
        summary=_trim(text, 180),
    )


def build_final_assembly_packet(
    *,
    context_packet: StagePacket,
    governed_output: Any = None,
    final_output: Any = None,
) -> StagePacket:
    governed_preview = governed_output if isinstance(governed_output, str) else repr(governed_output)
    final_preview = final_output if isinstance(final_output, str) else repr(final_output)
    payload = {
        "context_packet": context_packet.to_dict(),
        "governed_preview": str(governed_preview)[:1600],
        "final_preview": str(final_preview)[:1600],
    }
    return make_stage_packet(
        stage="final_assembly",
        kind="canonical_final_assembly_packet",
        payload=payload,
        summary=_trim(final_preview or governed_preview or context_packet.summary, 180),
    )
