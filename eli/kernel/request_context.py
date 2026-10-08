"""Per-request state for CognitiveEngine.

The engine is a process-wide singleton (get_engine()). Per-turn state used to
live as plain instance attributes, so concurrent API requests (FastAPI runs
sync handlers on a threadpool) could read or overwrite each other's mid-turn.

Two kinds of state live here:

* ContextVars, for values that belong to ONE turn: identity, request id,
  reasoning mode, and a few in-flight flags. CognitiveEngine.process() runs
  each turn inside its own contextvars.Context and resumes a streamed reply
  inside that same Context for every chunk. Binding a turn to "the current
  thread's context" does NOT work: the GUI starts a fresh thread per message
  and reads results on the main thread, and Starlette pulls each chunk of a
  sync stream through anyio in a fresh copy of the request context — both
  confirmed against the real code, and both broke the first version of this.

* A session-keyed store, for values that must outlive the turn and be seen
  from other threads: the last request meta (GUI badge, "what was your last
  message"), the last and previous bus results, the last command action, the
  last reasoning modes. Keyed by session so concurrent sessions never share.

None in a ContextVar means "not set for this turn" — callers with no request
identity (the GUI, background daemons) fall through to the engine's own
per-instance defaults.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

session_id_var: ContextVar[Optional[str]] = ContextVar("eli_session_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("eli_user_id", default=None)
request_id_var: ContextVar[Optional[str]] = ContextVar("eli_request_id", default=None)
# The current turn's reasoning mode. This used to be os.environ
# ["ELI_CURRENT_REASONING_MODE"] plus self._reasoning_mode on the singleton: the
# env var is process-global, so a concurrent quick request could switch a
# thinking model's <think> off for someone else's expert answer.
reasoning_mode_var: ContextVar[Optional[str]] = ContextVar("eli_reasoning_mode", default=None)
# None = not set this turn, not False: False is a legitimate in-turn value.
in_followthrough_var: ContextVar[Optional[bool]] = ContextVar("eli_in_followthrough", default=None)
# Set while a turn carries out what the user agreed to ("yes please" to an offer ELI does by
# writing): {"said", "offer", "message", "done"}. The turn it is set for runs with the offered
# task as its message.
agreed_task_var: ContextVar[Optional[dict]] = ContextVar("eli_agreed_task", default=None)
orchestrator_active_var: ContextVar[Optional[bool]] = ContextVar("eli_orchestrator_active", default=None)
in_orchestrator_var: ContextVar[Optional[bool]] = ContextVar("eli_in_orchestrator", default=None)
# What this turn actually did (its trace, bus result, published meta), collected
# as the turn runs so process() can write the audit row from the turn's own data
# whichever of its many exits it took. A fresh dict per process() call; a nested
# call gets its own and never writes into its parent's.
turn_facts_var: ContextVar[Optional[dict]] = ContextVar("eli_turn_facts", default=None)
# "typed" when the user typed this turn's message, "voice" when it was spoken, None when the
# caller did not say. Only speech can arrive as a fragment ("ply", "find your mo").
input_channel_var: ContextVar[Optional[str]] = ContextVar("eli_input_channel", default=None)


def note_turn_fact(name: str, value: Any) -> None:
    facts = turn_facts_var.get()
    if facts is not None:
        facts[name] = value


# ── session-sticky state ─────────────────────────────────────────────────────
# For values that must outlive the turn that set them or be read from another
# thread — "was the previous command a NEWS_FETCH" on the "dive deeper" turn,
# the GUI badge reading the last request meta on its main thread. The caller
# passes a key that already includes the engine instance and the session (see
# CognitiveEngine._sticky_key), so concurrent sessions never share an entry
# and the same session finds its own from any thread. Bounded oldest-first so
# a long-running process with many sessions doesn't grow this forever.
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
