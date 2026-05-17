from __future__ import annotations
from typing import Any, Dict, List

class TaskPlanner:
    """
    Minimal shim to satisfy existing imports.
    Replace with a richer planner later; for now this stops stale imports from
    pointing at a non-existent file.
    """
    def plan(self, user_input: str, intent: Dict[str, Any] | None = None) -> Dict[str, Any]:
        intent = intent or {}
        action = str(intent.get("action") or "CHAT")
        steps: List[str] = [
            f"classify task as {action}",
            "gather required evidence",
            "execute tools if needed",
            "synthesise evidence",
            "return grounded response",
        ]
        return {
            "ok": True,
            "planner": "TaskPlanner",
            "action": action,
            "steps": steps,
            "source": "shim",
        }

    __call__ = plan
