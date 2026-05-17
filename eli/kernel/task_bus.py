"""
eli/kernel/task_bus.py
─────────────────
Thin dispatcher that converts a task dict into an AgentBus dispatch call
and returns the DispatchResult.  CognitiveEngine imports:

    from eli.kernel.task_bus import run as _task_bus_run

Usage:
    result = run({
        "user_input": "...",
        "intent":     {...},
        "session_id": "...",
        "user_id":    "...",
    })
    # returns DispatchResult
"""
from __future__ import annotations
from typing import Any, Dict

from eli.cognition.agent_bus import get_bus, DispatchResult


def run(task: Dict[str, Any]) -> DispatchResult:
    """
    Dispatch a task through the full agent bus pipeline.

    Parameters
    ----------
    task : dict with keys:
        user_input  – raw user message (str)
        intent      – router intent dict {action, args, confidence, meta}
        session_id  – current session ID (str, optional)
        user_id     – user identifier (str, optional)

    Returns
    -------
    DispatchResult – aggregated evidence, memory context, confidence, plan
    """
    user_input = str(task.get("user_input") or "")
    intent     = dict(task.get("intent") or {"action": "CHAT", "confidence": 0.5})
    session_id = str(task.get("session_id") or "")
    user_id    = str(task.get("user_id") or "")

    bus = get_bus()
    return bus.dispatch(user_input, intent, session_id, user_id)
