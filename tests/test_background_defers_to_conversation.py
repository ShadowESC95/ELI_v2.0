"""Background generation does not start while a conversation is live: it would take the one model the next message needs."""
from eli.cognition import gguf_inference as gi
from eli.cognition import inference_broker as ib


class _Llm:
    calls = 0

    def __call__(self, prompt, **kw):
        _Llm.calls += 1
        return {"choices": [{"text": "generated"}]}

    def tokenize(self, b, add_bos=False):
        return list(range(len(b) // 4 + 1))


def _invoke(stream=False):
    return gi._safe_invoke_llm(_Llm(), "hello", temperature=0.1, max_tokens=16, top_p=0.9, top_k=40,
                               repeat_penalty=1.0, stop=None, stream=stream, grammar=None)


def test_background_work_waits_while_a_conversation_is_active(monkeypatch):
    _Llm.calls = 0
    monkeypatch.setattr(ib, "foreground_recently_active", lambda window=30.0: True)
    gi.set_background_inference(True)
    try:
        assert _invoke()["choices"][0]["text"] == ""
        assert list(_invoke(stream=True)) == []
    finally:
        gi.set_background_inference(False)
    assert _Llm.calls == 0


def test_background_work_runs_when_idle_and_the_conversation_is_never_deferred(monkeypatch):
    _Llm.calls = 0
    monkeypatch.setattr(ib, "foreground_recently_active", lambda window=30.0: False)
    gi.set_background_inference(True)
    try:
        assert _invoke()["choices"][0]["text"] == "generated"
    finally:
        gi.set_background_inference(False)
    monkeypatch.setattr(ib, "foreground_recently_active", lambda window=30.0: True)
    assert _invoke()["choices"][0]["text"] == "generated"


def test_the_window_can_be_turned_off(monkeypatch):
    _Llm.calls = 0
    monkeypatch.setenv("ELI_BG_DEFER_WINDOW", "0")
    monkeypatch.setattr(ib, "foreground_recently_active", lambda window=30.0: True)
    gi.set_background_inference(True)
    try:
        assert _invoke()["choices"][0]["text"] == "generated"
    finally:
        gi.set_background_inference(False)


def test_a_long_reply_in_progress_keeps_background_work_waiting(monkeypatch):
    """45 s into a 78 s streamed reply the daemon judged the model free and started an insight call."""
    from eli.cognition import inference_broker as ib
    started = ib.foreground_call_started()
    try:
        monkeypatch.setattr(ib, "_last_foreground_ts", ib._time.monotonic() - 3600)
        monkeypatch.setattr(ib, "_last_foreground_duration", 0.0)
        assert ib.foreground_recently_active(30.0)
    finally:
        ib.foreground_call_finished(started)
    assert not ib.foreground_in_progress()


def test_the_users_turn_waiting_to_embed_makes_a_background_generation_yield():
    """A typed "close settings" waited 92 s before routing: storing it embeds the text, the embedder
    shares llama.cpp's lock with the model, and a news synthesis held that lock for its whole 109 s
    call. Only generations raised foreground priority, so the synthesis was never asked to yield."""
    import contextvars
    import threading
    import time
    from types import SimpleNamespace
    from eli.kernel import request_context
    from eli.memory.vector_store import VectorStore
    from eli.runtime.native_locks import LLAMA_CPP_NATIVE_LOCK

    holding, yielded = threading.Event(), threading.Event()

    def background_generation():
        gi.set_background_inference(True)
        with LLAMA_CPP_NATIVE_LOCK:
            holding.set()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:  # one token at a time, as llama.cpp's callbacks see it
                if gi._should_abort_generation(gi.is_background_inference()):
                    yielded.set()
                    return
                time.sleep(0.01)

    store = object.__new__(VectorStore)
    store._embed_lock = threading.Lock()
    store._embedder = SimpleNamespace(embed=lambda text: [1.0, 0.0, 0.0])

    def users_turn():
        request_context.turn_facts_var.set({"request_id": "req-test", "autonomous": False})
        return store._embed("close settings")

    bg = threading.Thread(target=background_generation, daemon=True)
    bg.start()
    assert holding.wait(5)
    started = time.monotonic()
    vec = contextvars.copy_context().run(users_turn)
    assert vec is not None and yielded.is_set()
    assert time.monotonic() - started < 5, "the user's turn waited for the background generation"
    bg.join(5)


def test_background_work_waiting_on_the_lock_never_preempts_another_background_job():
    from eli.kernel import request_context
    from eli.runtime.native_locks import FOREGROUND_WAITING, hold_llama_lock
    assert not request_context.in_user_turn()  # a daemon thread has no user turn
    with hold_llama_lock(foreground=request_context.in_user_turn()):
        assert not FOREGROUND_WAITING.is_set()


def test_a_turn_that_never_uses_the_model_still_holds_background_work_back(monkeypatch):
    """A news synthesis started between two typed commands (open settings, close settings): only
    model calls counted as activity, and neither command used the model."""
    from eli.kernel.engine import CognitiveEngine
    monkeypatch.setattr(ib, "_last_foreground_ts", ib._time.monotonic() - 3600)
    monkeypatch.setattr(ib, "_last_foreground_duration", 0.0)
    assert not ib.foreground_recently_active(30.0)
    monkeypatch.setattr(CognitiveEngine, "_process_impl", lambda self, *a, **k: "Closed settings.")
    assert object.__new__(CognitiveEngine).process("close settings") == "Closed settings."
    assert ib.foreground_recently_active(30.0)
