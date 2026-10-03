"""Two regressions the first per-request-identity design shipped with, both
because it bound a turn's state to "the current thread's context" and neither
real caller keeps one context for a turn's lifetime. Each test reproduces the
real caller's shape, not an idealised one.

1. The GUI (eli_pro_audio_gui_v2_0.send_message) runs every message on a
   fresh threading.Thread and refreshes the confidence badge on the main
   thread through a QueuedConnection signal. _last_request_meta lived in a
   ContextVar, so the main thread always read {} (blank badge), and the next
   message's thread read _last_bus_result as None, so _prev_bus_result was
   always None.

2. /v1/chat/stream returns a sync generator; Starlette pulls each chunk with
   iterate_in_threadpool, which runs every next() through anyio in a FRESH
   copy of the request's context. Only chunk 0 saw the request's identity;
   every later chunk ran as the engine-default user (so post-stream writes
   like the audit-chain record were misattributed), and the stream ended with
   "Token ... was created in a different Context" as an error frame.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from eli.kernel import request_context as rc
from eli.kernel.engine import CognitiveEngine


def _bare(session="gui-session", user="desktop"):
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._fallback_session_id = session
    eng._fallback_user_id = user
    return eng


def test_gui_badge_and_previous_turn_survive_the_per_message_thread():
    eng = _bare()

    def _turn(self, *a, **k):
        self._last_request_meta = {"confidence": 0.91, "confidence_label": "high"}
        self._last_bus_result = "this turn's bus result"
        return "reply"

    with patch.object(CognitiveEngine, "_process_impl", _turn):
        worker = threading.Thread(target=lambda: eng.process("hi"))  # generate_worker's shape
        worker.start()
        worker.join()

    # The badge slot runs on the main thread.
    assert eng._last_request_meta == {"confidence": 0.91, "confidence_label": "high"}

    # The next message runs on another new thread and rotates last -> prev.
    seen = {}
    nxt = threading.Thread(target=lambda: seen.setdefault("v", eng._last_bus_result))
    nxt.start()
    nxt.join()
    assert seen["v"] == "this turn's bus result"


def test_streamed_api_reply_keeps_identity_and_mode_on_every_chunk_and_ends_cleanly():
    anyio = pytest.importorskip("anyio")
    concurrency = pytest.importorskip("starlette.concurrency")

    eng = _bare(session="engine-default", user="engine-default-user")

    def _stream(self, *a, **k):
        def g():
            for i in range(3):
                yield (self.user_id, self.session_id, rc.reasoning_mode_var.get())
        return g()

    def chat_stream_gen():  # same shape as api/server.py chat_stream._gen()
        yield "session-frame"
        try:
            for chunk in eng.process("hi", stream=True, reasoning_mode="constitutional_ai",
                                     user_id="alice", session_id="s-alice"):
                yield chunk
            yield "done"
        except Exception as e:  # what the real endpoint turns into an error frame
            yield f"error: {type(e).__name__}: {e}"

    frames = []

    async def _drive():
        async for frame in concurrency.iterate_in_threadpool(chat_stream_gen()):
            frames.append(frame)

    with patch.object(CognitiveEngine, "_process_impl", _stream):
        anyio.run(_drive)

    assert frames[0] == "session-frame"
    assert frames[1:4] == [("alice", "s-alice", "constitutional_ai")] * 3
    assert frames[-1] == "done", frames[-1]


def test_closing_a_stream_early_runs_its_cleanup_as_that_turn():
    """Client disconnect: the inner stream's finally blocks (e.g. the
    followthrough's audit record) must still see the turn's identity."""
    eng = _bare()
    cleanup_saw = {}

    def _stream(self, *a, **k):
        def g():
            try:
                yield "first"
                yield "second"
            finally:
                cleanup_saw["user"] = self.user_id
        return g()

    with patch.object(CognitiveEngine, "_process_impl", _stream):
        gen = eng.process("hi", stream=True, user_id="bob")
        assert next(gen) == "first"
        gen.close()

    assert cleanup_saw["user"] == "bob"
    assert rc.user_id_var.get() is None
