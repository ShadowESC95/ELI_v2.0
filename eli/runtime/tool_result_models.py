from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ToolResultRecord:
    action: str
    ok: bool = True
    status: str = "ok"
    summary: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = "executor"
    result_type: str = "dict"
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "ok": bool(self.ok),
            "status": self.status,
            "summary": self.summary,
            "args": dict(self.args or {}),
            "payload": dict(self.payload or {}),
            "source": self.source,
            "result_type": self.result_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_any(cls, obj: Any) -> "ToolResultRecord":
        if isinstance(obj, cls):
            return obj
        if isinstance(obj, dict):
            return cls(
                action=str(obj.get("action") or ""),
                ok=bool(obj.get("ok", True)),
                status=str(obj.get("status") or ("ok" if obj.get("ok", True) else "error")),
                summary=str(obj.get("summary") or ""),
                args=dict(obj.get("args") or {}),
                payload=dict(obj.get("payload") or {}),
                source=str(obj.get("source") or "executor"),
                result_type=str(obj.get("result_type") or "dict"),
                created_at=str(obj.get("created_at") or _utc_now()),
            )
        return cls(action="", ok=False, status="error", summary=repr(obj), payload={"repr": repr(obj)}, result_type=type(obj).__name__)
