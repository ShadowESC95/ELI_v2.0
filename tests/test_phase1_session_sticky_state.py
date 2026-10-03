"""Phase 1 follow-up (2026-10-02): _prev_bus_result, _last_command_action, and
_last_orchestrator_reasoning_mode are deliberately sticky ACROSS turns (e.g.
"was the previous command a NEWS_FETCH" has to still be true on the turn
where the user says "dive deeper") — unlike every other ContextVar-backed
property from Phase 1, which is pure within-one-turn scratch.

A ContextVar was the wrong primitive for that: it is scoped to the current
THREAD, not to the SESSION the data actually belongs to. Live bug, found by
a failing test rather than by inspection: test_live_session_2_3_0_
regressions.py::test_persona_budget_scales_with_the_context_window started
failing once an earlier, unrelated test left a non-"quick" reasoning mode
value on the same thread — a fresh engine-like object with no relation to
that earlier test inherited it anyway, because the ContextVar had no idea
they were different sessions.

Fixed with session-keyed shared storage (request_context.get/set_session_
sticky) instead. This file verifies the fix directly: two different
sessions never share a value (even reused on the same thread), the same
session shares its value correctly across different engine instances/
threads (the actual point of "sticky"), and the store is bounded so a
long-running process with many distinct sessions doesn't grow it forever.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from eli.kernel import request_context as rc
from eli.kernel.engine import CognitiveEngine


def _engine_for_session(session_id):
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._fallback_session_id = session_id
    return eng


def test_two_different_sessions_never_share_a_sticky_value():
    a = _engine_for_session("session-A")
    b = _engine_for_session("session-B")

    a._last_orchestrator_reasoning_mode = "chain_of_thought"
    assert b._last_orchestrator_reasoning_mode == "quick"
    assert a._last_orchestrator_reasoning_mode == "chain_of_thought"


def _on_new_thread(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("v", fn()))
    t.start()
    t.join()
    return out["v"]


def test_the_same_session_shares_its_sticky_value_across_threads():
    """The actual point of 'sticky': the same engine and session must still
    see what the last turn set, whichever thread runs the next turn — the GUI
    starts a fresh thread for every message."""
    eng = _engine_for_session("session-X")
    _on_new_thread(lambda: setattr(eng, "_last_command_action", {"action": "NEWS_FETCH"}))
    assert _on_new_thread(lambda: eng._last_command_action) == {"action": "NEWS_FETCH"}


def test_prev_bus_result_is_also_session_keyed():
    eng = _engine_for_session("session-Y")
    eng._prev_bus_result = "turn one's bus result"
    assert _on_new_thread(lambda: eng._prev_bus_result) == "turn one's bus result"

    other_session = _engine_for_session("session-Z")
    assert other_session._prev_bus_result is None


def test_two_engine_instances_never_share_even_with_the_same_session_id():
    """Engines built in the same second share an int(time()) session id. As
    plain attributes these were per instance; they must stay that way."""
    a = _engine_for_session("1790990000")
    b = _engine_for_session("1790990000")
    a._last_request_meta = {"confidence": 0.9}
    assert b._last_request_meta == {}
    assert a._last_request_meta == {"confidence": 0.9}


def test_an_engine_with_no_session_id_never_reads_or_writes_any_sessions_sticky_state():
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._fallback_session_id = None
    eng._last_orchestrator_reasoning_mode = "tree_of_thoughts"  # must be a safe no-op
    assert eng._last_orchestrator_reasoning_mode == "quick"

    # Confirm it truly never touched the shared store under any key.
    assert rc.get_session_sticky(None, "last_orchestrator_reasoning_mode") is None


def test_real_concurrent_sessions_on_a_threadpool_never_cross_contaminate():
    """The actual production shape this fixes: a threadpool reused across
    unrelated requests for different sessions must never let one session's
    sticky state leak into another's, regardless of which thread serves
    which request."""
    results = {}

    def _run(session_id, mode):
        eng = _engine_for_session(session_id)
        eng._last_orchestrator_reasoning_mode = mode
        results[session_id] = eng._last_orchestrator_reasoning_mode

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_run, "sess-1", "chain_of_thought"),
            pool.submit(_run, "sess-2", "tree_of_thoughts"),
        ]
        for f in futures:
            f.result(timeout=5)

    assert results["sess-1"] == "chain_of_thought"
    assert results["sess-2"] == "tree_of_thoughts"


def test_the_session_sticky_store_is_bounded():
    """A long-running process serving many distinct sessions must not grow
    this store forever."""
    for i in range(rc._SESSION_STICKY_MAX + 50):
        rc.set_session_sticky(f"bound-test-session-{i}", "x", i)
    assert len(rc._session_sticky) <= rc._SESSION_STICKY_MAX
