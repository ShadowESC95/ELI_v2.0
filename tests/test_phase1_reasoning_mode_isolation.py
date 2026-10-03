"""Phase 1 completion (2026-10-03): the reasoning mode was the one piece of
per-turn state the original Phase 1 didn't move off the engine singleton,
even though "current mode" was in the original ask. process() wrote both
self._reasoning_mode and os.environ["ELI_CURRENT_REASONING_MODE"] — the env
var is process-global, shared by every thread, and gguf_inference's
_no_think_prefill read it to decide whether a thinking model thinks at all.
Under two concurrent API requests, a quick-mode request could turn thinking
off mid-generation for another request's expert answer, or on for a "hey".

Now: a per-turn reasoning_mode_var set by the process() wrapper (reset after
the turn, or after a stream drains — the stream formats its prompt, and so
makes the think/no-think call, after process() has returned), _reasoning_mode
as a property over it with the session's last mode as the between-turns
fallback, _no_think_prefill reading the per-turn value first, and AgentBus
running each agent in a copy of the caller's context so agent threads see the
request's mode and identity too.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from eli.kernel import request_context as rc
from eli.kernel.engine import CognitiveEngine


def _bare_engine(session_id="desktop-session"):
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._fallback_session_id = session_id
    eng._fallback_user_id = "desktop-default"
    return eng


# ── process(): each concurrent request sees its own mode ────────────────────

def test_two_concurrent_requests_never_see_each_others_mode():
    eng = _bare_engine()

    def _probe(self, user_input, source="user", stream=False, reasoning_mode=None, **kw):
        first = rc.reasoning_mode_var.get()
        time.sleep(0.15)
        return (first, rc.reasoning_mode_var.get(), self._reasoning_mode)

    with patch.object(CognitiveEngine, "_process_impl", _probe):
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(eng.process, "a", reasoning_mode="constitutional_ai", session_id="s-a")
            time.sleep(0.05)
            fb = pool.submit(eng.process, "b", reasoning_mode="quick", session_id="s-b")
            a, b = fa.result(timeout=5), fb.result(timeout=5)

    assert a == ("constitutional_ai",) * 3
    assert b == ("quick",) * 3


def test_the_turn_mode_is_released_after_a_non_streaming_turn():
    eng = _bare_engine()
    with patch.object(CognitiveEngine, "_process_impl", lambda self, *a, **k: "ok"):
        eng.process("hi", reasoning_mode="tree_of_thoughts")
    assert rc.reasoning_mode_var.get() is None


def test_a_stream_body_sees_its_mode_and_the_caller_never_does():
    """The generator's body runs after process() has returned — exactly when
    a real stream formats its prompt and calls _no_think_prefill — so it must
    still see the turn's mode. The caller's own context is never touched."""
    eng = _bare_engine()

    def _streaming(self, user_input, source="user", stream=False, reasoning_mode=None, **kw):
        def _gen():
            for _ in range(2):
                yield rc.reasoning_mode_var.get()
        return _gen()

    with patch.object(CognitiveEngine, "_process_impl", _streaming):
        gen = eng.process("hi", reasoning_mode="chain_of_thought", stream=True)
        assert rc.reasoning_mode_var.get() is None
        assert list(gen) == ["chain_of_thought", "chain_of_thought"]
    assert rc.reasoning_mode_var.get() is None


def test_an_exception_mid_turn_still_releases_the_mode():
    eng = _bare_engine()

    def _boom(self, *a, **k):
        raise RuntimeError("boom")

    with patch.object(CognitiveEngine, "_process_impl", _boom):
        with pytest.raises(RuntimeError):
            eng.process("hi", reasoning_mode="self_consistency")
    assert rc.reasoning_mode_var.get() is None


def test_between_turns_the_property_reports_that_sessions_last_mode():
    """Status reads ("what mode am I in?") outside a turn get this session's
    last mode — not whatever another session's turn left on the thread."""
    mine = _bare_engine("session-mine")
    other = _bare_engine("session-other")
    mine._reasoning_mode = "tree_of_thoughts"
    other._reasoning_mode = "quick"
    assert rc.reasoning_mode_var.get() is None, "a set outside a turn must not strand a value on the thread"
    assert mine._reasoning_mode == "tree_of_thoughts"
    assert other._reasoning_mode == "quick"


def test_a_mode_change_inside_a_turn_applies_to_that_turn_then_releases():
    """e.g. the phatic fast-path downgrading a deep request to quick mid-turn."""
    eng = _bare_engine("session-downgrade")

    def _downgrade(self, *a, **k):
        self._reasoning_mode = "quick"
        return rc.reasoning_mode_var.get()

    with patch.object(CognitiveEngine, "_process_impl", _downgrade):
        assert eng.process("hi", reasoning_mode="tree_of_thoughts") == "quick"
    assert rc.reasoning_mode_var.get() is None
    assert eng._reasoning_mode == "quick"  # the session remembers its last mode


# ── gguf_inference: the think/no-think call reads the turn's mode ───────────

@pytest.fixture()
def thinking_model(monkeypatch):
    from eli.cognition import gguf_inference as gi
    monkeypatch.setattr(gi, "_is_glm_model", lambda: False)
    monkeypatch.setattr(gi, "_force_no_think_active", lambda: False)
    monkeypatch.setattr(gi, "_is_thinking_model", lambda *a, **k: True)
    monkeypatch.delenv("ELI_MODEL_THINK", raising=False)
    return gi


_CLOSED = "<think>\n\n</think>\n\n"


def test_the_turn_mode_beats_a_stale_global_env_var(thinking_model, monkeypatch):
    monkeypatch.setenv("ELI_CURRENT_REASONING_MODE", "constitutional_ai")  # another request's
    token = rc.reasoning_mode_var.set("quick")
    try:
        assert thinking_model._no_think_prefill(structured=False, max_tokens=4096) == _CLOSED
    finally:
        rc.reasoning_mode_var.reset(token)


def test_a_deep_turn_is_not_silenced_by_someone_elses_quick(thinking_model, monkeypatch):
    monkeypatch.setenv("ELI_CURRENT_REASONING_MODE", "quick")  # another request's
    token = rc.reasoning_mode_var.set("constitutional_ai")
    try:
        assert thinking_model._no_think_prefill(structured=False, max_tokens=4096) == ""
    finally:
        rc.reasoning_mode_var.reset(token)


def test_outside_a_turn_the_env_var_fallback_still_works(thinking_model, monkeypatch):
    monkeypatch.setenv("ELI_CURRENT_REASONING_MODE", "quick")
    assert rc.reasoning_mode_var.get() is None
    assert thinking_model._no_think_prefill(structured=False, max_tokens=4096) == _CLOSED


# ── AgentBus: agent threads see the request's context ───────────────────────

def test_agent_threads_see_the_requests_mode_and_identity():
    from eli.cognition.agent_bus import AgentBus, AgentResult, _BaseAgent

    class _Probe(_BaseAgent):
        name = "ctx_probe"
        timeout_s = 5.0

        def run(self, user_input, intent, session_id, user_id):
            return AgentResult(agent=self.name, ok=True, confidence=1.0, data={
                "mode": rc.reasoning_mode_var.get(),
                "user": rc.user_id_var.get(),
            })

    bus = AgentBus(max_workers=2)
    tm = rc.reasoning_mode_var.set("tree_of_thoughts")
    tu = rc.user_id_var.set("user-from-request")
    try:
        results = bus._collect_layer([_Probe()], "hi", {}, "s", "u")
    finally:
        rc.user_id_var.reset(tu)
        rc.reasoning_mode_var.reset(tm)

    assert results and results[0].ok
    assert results[0].data == {"mode": "tree_of_thoughts", "user": "user-from-request"}
