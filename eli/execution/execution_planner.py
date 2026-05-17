from __future__ import annotations

from typing import Any, Dict, List

from eli.runtime.pipeline_models import RouteDecision, ExecutionPlan, PlanStep
from eli.runtime.response_contracts import contract_for_action


def build_route_decision(user_input: str, routed: Dict[str, Any] | Any) -> RouteDecision:
    if isinstance(routed, dict):
        action = str(routed.get("action") or "CHAT")
        args = routed.get("args") if isinstance(routed.get("args"), dict) else {}
        conf = float(routed.get("confidence") or 0.0)
        meta = routed.get("meta") if isinstance(routed.get("meta"), dict) else {}
    else:
        action = str(getattr(routed, "action", "CHAT"))
        args = getattr(routed, "args", {}) if isinstance(getattr(routed, "args", {}), dict) else {}
        conf = float(getattr(routed, "confidence", 0.0) or 0.0)
        meta = getattr(routed, "meta", {}) if isinstance(getattr(routed, "meta", {}), dict) else {}

    return RouteDecision(
        user_input=str(user_input or ""),
        action=action,
        args=args,
        confidence=conf,
        meta=meta,
    )


def _steps(*items: tuple[str, str, Dict[str, Any] | None]) -> List[PlanStep]:
    out: List[PlanStep] = []
    for name, kind, cfg in items:
        out.append(PlanStep(name=name, kind=kind, config=dict(cfg or {})))
    return out


def build_execution_plan(rd: RouteDecision) -> ExecutionPlan:
    c = contract_for_action(rd.action)
    action = str(rd.action or "CHAT").upper()

    if action == "RUNTIME_STATUS":
        profile = ["introspection"]
        steps = _steps(
            ("runtime_snapshot", "agent", {"profile": "introspection"}),
            ("final_response", "response", {"provider": c.provider}),
        )

    elif action == "MEMORY_STATUS":
        profile = ["memory"]
        steps = _steps(
            ("memory_snapshot", "agent", {"profile": "memory"}),
            ("final_response", "response", {"provider": c.provider}),
        )

    elif action == "COGNITION_STATUS":
        profile = ["introspection", "file_code"]
        steps = _steps(
            ("introspection", "agent", {"profile": "introspection"}),
            ("file_runtime_scan", "agent", {"profile": "file_code"}),
            ("final_response", "response", {"provider": c.provider}),
        )

    elif action == "MEMORY_RECALL":
        profile = ["memory"]
        steps = _steps(
            ("memory_recall", "agent", {"profile": "memory"}),
            ("context_assembly", "assembly", {"mode": "memory_report"}),
            ("final_response", "response", {"provider": c.provider}),
        )

    elif action == "CHAT":
        profile = ["planner", "memory", "retrieval", "synthesis"]
        steps = _steps(
            ("hyde_query", "planner", {"enabled": True}),
            ("retrieval_keyword", "retrieval", {"limit": 12}),
            ("retrieval_semantic", "retrieval", {"limit": 12}),
            ("retrieval_faiss", "retrieval", {"limit": 12}),
            ("hybrid_merge", "assembly", {"enabled": True}),
            ("rerank", "assembly", {"limit": 8}),
            ("context_assembly", "assembly", {"mode": "grounded_chat"}),
            ("final_response", "response", {"provider": c.provider}),
        )

    else:
        profile = ["executor", "synthesis"]
        steps = _steps(
            ("action_dispatch", "executor", {"action": action}),
            ("context_assembly", "assembly", {"mode": "action_result"}),
            ("final_response", "response", {"provider": c.provider}),
        )

    return ExecutionPlan(
        action=action,
        quick=bool(c.quick),
        agent_profile=profile,
        steps=steps,
        response_provider=c.provider,
    )

