from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional
import time
import uuid


@dataclass
class ProposalRecord:
    kind: str
    payload: Dict[str, Any]
    source: str = "unknown"
    priority: int = 50
    created_at: float = field(default_factory=time.time)
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cwd: Optional[str] = None

    action_class: str = "observe-only"
    emitter: str = "unknown"
    requested_by: str = "system"

    approval_state: str = "pending"
    requires_confirmation: bool = False
    approved_by: Optional[str] = None
    policy_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, obj: Dict[str, Any]) -> "ProposalRecord":
        return cls(
            kind=str(obj.get("kind") or "unknown"),
            payload=dict(obj.get("payload") or {}),
            source=str(obj.get("source") or "unknown"),
            priority=int(obj.get("priority") or 50),
            created_at=float(obj.get("created_at") or time.time()),
            proposal_id=str(obj.get("proposal_id") or uuid.uuid4().hex),
            cwd=obj.get("cwd"),
            action_class=str(obj.get("action_class") or "observe-only"),
            emitter=str(obj.get("emitter") or "unknown"),
            requested_by=str(obj.get("requested_by") or "system"),
            approval_state=str(obj.get("approval_state") or "pending"),
            requires_confirmation=bool(obj.get("requires_confirmation", False)),
            approved_by=obj.get("approved_by"),
            policy_reason=str(obj.get("policy_reason") or ""),
        )
