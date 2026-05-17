from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class RouteDecision:
    user_input: str
    action: str
    args: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlanStep:
    name: str
    kind: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionPlan:
    action: str
    quick: bool
    agent_profile: List[str] = field(default_factory=list)
    steps: List[PlanStep] = field(default_factory=list)
    response_provider: str = "eli_final_response_provider"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "quick": self.quick,
            "agent_profile": list(self.agent_profile),
            "steps": [s.to_dict() for s in self.steps],
            "response_provider": self.response_provider,
        }


@dataclass
class EvidenceItem:
    source: str
    kind: str
    summary: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidencePacket:
    action: str
    items: List[EvidenceItem] = field(default_factory=list)

    def add(self, item: EvidenceItem) -> None:
        self.items.append(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "count": len(self.items),
            "items": [i.to_dict() for i in self.items],
        }
