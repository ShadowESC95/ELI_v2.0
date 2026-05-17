from __future__ import annotations

import json
from typing import Any, Dict, List

from eli.runtime.evidence_store import (
    get_current_evidence_packet,
    get_current_execution_plan,
    get_current_route_decision,
)
from eli.runtime.final_response_provider import current_contract


def _trim_text(text: str, limit: int = 400) -> str:
    s = " ".join(str(text or "").split()).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _summarize_evidence() -> List[Dict[str, Any]]:
    ep = get_current_evidence_packet()
    out: List[Dict[str, Any]] = []
    for item in ep.items[:10]:
        out.append({
            "source": item.source,
            "kind": item.kind,
            "summary": _trim_text(item.summary, 240),
        })
    return out


def assemble_final_prompt(prompt: str) -> str:
    contract = current_contract()
    if contract.quick:
        return str(prompt or "")

    rd = get_current_route_decision()
    plan = get_current_execution_plan()
    evidence = _summarize_evidence()

    payload = {
        "route": rd.to_dict() if rd else None,
        "plan": plan.to_dict() if plan else None,
        "evidence": evidence,
        "rules": {
            "grounded_only": True,
            "persona_required": bool(contract.require_persona),
            "provider": contract.provider,
            "style_hint": contract.style_hint,
            "quick": contract.quick,
        },
    }

    header = (
        "ASSEMBLED_RESPONSE_CONTEXT\n"
        "Use the route, plan, and evidence below as the authoritative basis for the final answer.\n"
        "Do not invent agent usage, runtime facts, memory facts, file facts, or tool results.\n"
        "If evidence is incomplete, say so plainly.\n"
        "Speak as ELI only after grounding on the supplied evidence.\n\n"
    )

    return header + json.dumps(payload, ensure_ascii=False, indent=2) + "\n\nUSER_FACING_PROMPT\n" + str(prompt or "")

