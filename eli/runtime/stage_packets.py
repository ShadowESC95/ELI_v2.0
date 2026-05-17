from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import time
import uuid


def _now_ts() -> float:
    return float(time.time())


@dataclass
class StagePacket:
    packet_id: str = field(default_factory=lambda: f"pkt_{uuid.uuid4().hex[:12]}")
    stage: str = ""
    kind: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    confidence: Optional[float] = None
    created_at: float = field(default_factory=_now_ts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_any(cls, obj: Any) -> "StagePacket":
        if isinstance(obj, cls):
            return obj
        if isinstance(obj, dict):
            return cls(
                packet_id=str(obj.get("packet_id") or f"pkt_{uuid.uuid4().hex[:12]}"),
                stage=str(obj.get("stage") or ""),
                kind=str(obj.get("kind") or ""),
                payload=dict(obj.get("payload") or {}),
                summary=str(obj.get("summary") or ""),
                confidence=(None if obj.get("confidence") is None else float(obj.get("confidence"))),
                created_at=float(obj.get("created_at") or _now_ts()),
            )
        return cls(kind="unknown", payload={"repr": repr(obj)}, summary=str(obj)[:200])


@dataclass
class PacketSnapshot:
    packets: List[StagePacket] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"packets": [p.to_dict() for p in self.packets]}


def make_stage_packet(
    *,
    stage: str,
    kind: str,
    payload: Dict[str, Any] | None = None,
    summary: str = "",
    confidence: float | None = None,
) -> StagePacket:
    return StagePacket(
        stage=str(stage or ""),
        kind=str(kind or ""),
        payload=dict(payload or {}),
        summary=str(summary or ""),
        confidence=(None if confidence is None else float(confidence)),
    )
