"""Per-request state for CognitiveEngine, via contextvars instead of self.*.

The engine is a process-wide singleton (get_engine()). Before this, per-turn
state (session_id, user_id, request_id, bus results) lived as plain instance
attributes — under concurrent API requests (api/server.py's handlers run on
FastAPI's threadpool, genuinely concurrent) one request's turn could read or
overwrite another's mid-flight. ContextVars isolate this per request: anyio's
to_thread.run_sync (what Starlette uses for sync def handlers) copies the
caller's context into the worker thread, so a value set before dispatch stays
correct for that request's thread alone.

None here means "not explicitly set for this call" — callers with no
request-scoped identity (the GUI, background daemons) fall through to
CognitiveEngine's own per-instance default, computed once, unchanged from
before this file existed.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

session_id_var: ContextVar[Optional[str]] = ContextVar("eli_session_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("eli_user_id", default=None)
request_id_var: ContextVar[Optional[str]] = ContextVar("eli_request_id", default=None)
bus_result_var: ContextVar[Optional[Any]] = ContextVar("eli_bus_result", default=None)
request_meta_var: ContextVar[Optional[dict]] = ContextVar("eli_request_meta", default=None)
# None means "not explicitly set" for these two, same as the others above —
# NOT False. A ContextVar default of False would be indistinguishable from a
# legitimate "turn just ended" write, since nothing today ever sets these
# vars directly (only the property setters below, which write the engine's
# own fallback instead) — see CognitiveEngine's _in_followthrough /
# _orchestrator_active properties.
in_followthrough_var: ContextVar[Optional[bool]] = ContextVar("eli_in_followthrough", default=None)
orchestrator_active_var: ContextVar[Optional[bool]] = ContextVar("eli_orchestrator_active", default=None)
in_orchestrator_var: ContextVar[Optional[bool]] = ContextVar("eli_in_orchestrator", default=None)
prev_bus_result_var: ContextVar[Optional[Any]] = ContextVar("eli_prev_bus_result", default=None)
last_command_action_var: ContextVar[Optional[dict]] = ContextVar("eli_last_command_action", default=None)
last_orchestrator_reasoning_mode_var: ContextVar[Optional[str]] = ContextVar(
    "eli_last_orchestrator_reasoning_mode", default=None)
