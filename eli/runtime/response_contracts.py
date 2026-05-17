from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict

_QUICK_ACTIONS = {
    "RUNTIME_STATUS",
    "REASONING_MODE_STATUS",
    "MEMORY_STATUS",
    "COGNITION_STATUS",
    "CODE_CHANGES",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "MEMORY_RECALL",
}

@dataclass
class ResponseContract:
    action: str
    quick: bool
    provider: str
    grounded: bool
    temperature: float
    max_tokens_cap: int
    require_persona: bool
    evidence_mode: str
    style_hint: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def is_quick_action(action: str | None) -> bool:
    return str(action or "").strip().upper() in _QUICK_ACTIONS


def contract_for_action(action: str | None) -> ResponseContract:
    a = str(action or "CHAT").strip().upper() or "CHAT"
    quick = is_quick_action(a)

    if quick:
        return ResponseContract(
            action=a,
            quick=True,
            provider="fastpath",
            grounded=True,
            temperature=0.20,
            max_tokens_cap=-1,
            require_persona=False,
            evidence_mode="strict",
            style_hint="brief_grounded",
        )

    if a in {"CHAT", "MEMORY_RECALL", "COGNITION_STATUS", "MEMORY_STATUS"}:
        temp = 0.35
        cap = -1  # unlimited
    else:
        temp = 0.30
        cap = -1  # unlimited

    return ResponseContract(
        action=a,
        quick=False,
        provider="eli_final_response_provider",
        grounded=True,
        temperature=temp,
        max_tokens_cap=cap,
        require_persona=True,
        evidence_mode="strict",
        style_hint="eli_grounded_natural",
    )
