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


# ── session-sticky state ─────────────────────────────────────────────────────
# prev_bus_result, last_command_action, and last_orchestrator_reasoning_mode
# are DELIBERATELY meant to survive from one turn into the next (unlike every
# ContextVar above, which is pure within-one-turn scratch) — e.g. "was the
# previous command a NEWS_FETCH" has to still be true on the turn where the
# user says "dive deeper". A ContextVar is the wrong primitive for that: it is
# scoped to the current thread, not to the session the data actually belongs
# to, so two different CognitiveEngine-like objects (or, in production, a
# threadpool thread reused for a later, unrelated request) silently share one
# slot. Live bug (2026-10-02): a test constructing its own engine subclass
# inherited a reasoning-mode value an unrelated earlier test had left on the
# same thread, found by a failing persona-budget test, not by inspection.
#
# Keyed by session_id instead — correct for both a concurrent request (a
# different session_id never reads another session's entry) and a reused
# thread (the same session_id still finds its own entry, wherever it runs).
# Bounded with simple oldest-first eviction so a long-running process with
# many distinct sessions doesn't grow this unboundedly.
import threading as _threading
from collections import OrderedDict as _OrderedDict

_SESSION_STICKY_MAX = 500
_session_sticky_lock = _threading.Lock()
_session_sticky: "_OrderedDict[str, dict]" = _OrderedDict()


def get_session_sticky(session_id: Optional[str], field: str, default: Any = None) -> Any:
    if not session_id:
        return default
    with _session_sticky_lock:
        bucket = _session_sticky.get(session_id)
        return bucket.get(field, default) if bucket else default


def set_session_sticky(session_id: Optional[str], field: str, value: Any) -> None:
    if not session_id:
        return
    with _session_sticky_lock:
        bucket = _session_sticky.get(session_id)
        if bucket is None:
            bucket = {}
            _session_sticky[session_id] = bucket
        else:
            _session_sticky.move_to_end(session_id)
        bucket[field] = value
        while len(_session_sticky) > _SESSION_STICKY_MAX:
            _session_sticky.popitem(last=False)
