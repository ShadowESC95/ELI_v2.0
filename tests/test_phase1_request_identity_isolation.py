"""Phase 1 of the identity/provenance plan (2026-10-02): CognitiveEngine is a
process-wide singleton (get_engine()). Before this phase, self.user_id /
self.session_id were plain instance attributes set once at __init__ — under
concurrent API requests (api/server.py's handlers run genuinely concurrently
on FastAPI's threadpool), one request's turn could read or overwrite
another's identity mid-flight. process() is now a thin wrapper: user_id/
session_id, when given, are set as ContextVars for the duration of that one
call, isolated per thread.

This is the real concurrency test the plan's own verification section asked
for — a ThreadPoolExecutor driving two simultaneous process() calls with
different identities and a mocked slow step widening the race window,
asserting each thread's reads carry its own identity throughout, never the
other's. Don't just trust that contextvars isolate across threads — verify
it directly, the same way the project verified the audit-chain request_id
fix with a real sqlite round-trip rather than a source-text assertion.

_process_impl is mocked here, not the real pipeline — this isolates the
identity mechanism itself (the thing this phase actually changed) from GGUF
inference, routing, and memory I/O, which are unrelated to what's being
verified and would make this slow and non-deterministic for no benefit.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from eli.kernel.engine import CognitiveEngine


def _slow_identity_probe(self, user_input, source="user", stream=False,
                          reasoning_mode=None, **kwargs):
    first = self.user_id
    time.sleep(0.15)
    second = self.user_id
    return {
        "user_id_before_sleep": first,
        "user_id_after_sleep": second,
        "session_id": self.session_id,
        "thread": threading.current_thread().name,
    }


def _new_bare_engine() -> CognitiveEngine:
    """Same __new__-without-__init__ pattern engine.py's own process() already
    guards for (see the 'Minimal attr guard for __new__-constructed instances'
    comment there) — skips the heavy real __init__ (GGUF, memory DB, daemons)
    since none of that is exercised by this test."""
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine._fallback_user_id = "desktop-default"
    engine._fallback_session_id = "desktop-session"
    return engine


def test_two_concurrent_requests_never_see_each_others_identity():
    engine = _new_bare_engine()

    with patch.object(CognitiveEngine, "_process_impl", _slow_identity_probe):
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(
                engine.process, "hello", user_id="user-A", session_id="sess-A")
            time.sleep(0.05)  # let A start sleeping before B begins
            fut_b = pool.submit(
                engine.process, "hello", user_id="user-B", session_id="sess-B")
            result_a = fut_a.result(timeout=5)
            result_b = fut_b.result(timeout=5)

    assert result_a["user_id_before_sleep"] == "user-A"
    assert result_a["user_id_after_sleep"] == "user-A", (
        "thread A's identity changed mid-turn — leaked from/to another thread"
    )
    assert result_a["session_id"] == "sess-A"
    assert result_b["user_id_before_sleep"] == "user-B"
    assert result_b["user_id_after_sleep"] == "user-B"
    assert result_b["session_id"] == "sess-B"
    assert result_a["thread"] != result_b["thread"]

    # After both requests finish, the fallback the GUI/background daemons see
    # with no override must be untouched by either request's identity.
    assert engine.user_id == "desktop-default"
    assert engine.session_id == "desktop-session"


def test_streaming_reply_keeps_its_identity_until_the_generator_is_drained():
    """The actual subtlety this phase had to get right: process() returns a
    generator whose body runs AFTER process() itself has already returned
    (the caller iterates it later, e.g. api/server.py's chat_stream SSE
    loop). A plain try/finally reset inside process() would tear the
    override down before the stream's own body ever reads it."""
    engine = _new_bare_engine()

    def _streaming_probe(self, user_input, source="user", stream=False,
                          reasoning_mode=None, **kwargs):
        def _gen():
            for _ in range(3):
                time.sleep(0.02)
                yield self.user_id
        return _gen()

    with patch.object(CognitiveEngine, "_process_impl", _streaming_probe):
        result = engine.process("hello", user_id="user-stream", stream=True)
        seen = list(result)

    assert seen == ["user-stream", "user-stream", "user-stream"]
    # Drained — the override must be gone, not leaked into the next call on
    # this (or a reused threadpool) thread.
    assert engine.user_id == "desktop-default"


def test_omitting_identity_falls_back_to_the_engine_default_unchanged():
    """The GUI and background daemons (habits_scheduler.py, scheduled_tasks.py)
    call process() with no user_id/session_id at all today — must see exactly
    the same single-instance behavior as before this wrapper existed."""
    engine = _new_bare_engine()

    with patch.object(CognitiveEngine, "_process_impl", _slow_identity_probe):
        result = engine.process("hello")

    assert result["user_id_before_sleep"] == "desktop-default"
    assert result["session_id"] == "desktop-session"


def test_orchestrator_recursion_guard_does_not_false_trip_across_threads():
    """orchestrator.py's own recursion guard ("Recursion detected in
    orchestrator.run()") read/wrote self.engine._in_orchestrator as a plain
    flag on the shared engine singleton — two unrelated concurrent requests
    could trip it: thread B would see True because thread A set it, and
    raise a false recursion error for a request that never recursed at all.
    Converting it to the same contextvar pattern as the rest of this phase
    fixes that while the real same-thread guard (set then read on the same
    call stack) still works identically to before."""
    engine = _new_bare_engine()

    def _hold_in_orchestrator(self, user_input, source="user", stream=False,
                               reasoning_mode=None, **kwargs):
        self._in_orchestrator = True
        time.sleep(0.1)
        seen = self._in_orchestrator
        self._in_orchestrator = False
        return seen

    with patch.object(CognitiveEngine, "_process_impl", _hold_in_orchestrator):
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(engine.process, "hello")
            fut_b = pool.submit(engine.process, "hello")
            assert fut_a.result(timeout=5) is True
            assert fut_b.result(timeout=5) is True

    # Neither thread's True leaked into the other's read, and nothing leaked
    # past both calls finishing.
    assert engine._in_orchestrator is False


def test_an_exception_mid_turn_still_releases_the_identity_override():
    engine = _new_bare_engine()

    def _raising_probe(self, user_input, source="user", stream=False,
                        reasoning_mode=None, **kwargs):
        raise RuntimeError("boom")

    with patch.object(CognitiveEngine, "_process_impl", _raising_probe):
        try:
            engine.process("hello", user_id="user-crash")
        except RuntimeError:
            pass

    assert engine.user_id == "desktop-default"
