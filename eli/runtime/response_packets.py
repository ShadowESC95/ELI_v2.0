from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict
import uuid


@dataclass
class FinalAnswerRequest:
    request_id: str
    action: str
    quick: bool
    provider: str
    style_hint: str
    user_prompt: str
    route: Dict[str, Any]
    plan: Dict[str, Any]
    evidence_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def make_final_answer_request(
    *,
    action: str,
    quick: bool,
    provider: str,
    style_hint: str,
    user_prompt: str,
    route: Dict[str, Any] | None = None,
    plan: Dict[str, Any] | None = None,
    evidence_count: int = 0,
    request_id: str | None = None,
) -> FinalAnswerRequest:
    return FinalAnswerRequest(
        request_id=str(request_id or f"req_{uuid.uuid4().hex[:12]}"),
        action=str(action or "CHAT"),
        quick=bool(quick),
        provider=str(provider or "eli_final_response_provider"),
        style_hint=str(style_hint or "eli_grounded_natural"),
        user_prompt=str(user_prompt or ""),
        route=dict(route or {}),
        plan=dict(plan or {}),
        evidence_count=int(evidence_count or 0),
    )
