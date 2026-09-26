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
