from __future__ import annotations
from typing import Any, Dict

from eli.runtime.pipeline_models import RouteDecision
from eli.execution.execution_planner import build_execution_plan


class TaskPlanner:
    """
    Thin compatibility wrapper over the canonical ``execution_planner``.

    Previously a hardcoded shim returning fixed step strings. It now delegates
    to ``build_execution_plan`` so there is a single real plan representation
    (``ExecutionPlan``) across the codebase. Kept as a class for backward
    compatibility with any caller importing ``TaskPlanner``.
    """

    def plan(self, user_input: str, intent: Dict[str, Any] | None = None) -> Dict[str, Any]:
        intent = intent or {}
        action = str(intent.get("action") or "CHAT")
        rd = RouteDecision(
            user_input=str(user_input or ""),
            action=action,
            confidence=float(intent.get("confidence") or 0.0),
        )
        plan = build_execution_plan(rd)
        return {
            "ok": True,
            "planner": "execution_planner",
            "action": plan.action,
            "agent_profile": list(plan.agent_profile),
            "steps": [s.to_dict() for s in plan.steps],
            "source": "execution_planner.build_execution_plan",
        }

    __call__ = plan
