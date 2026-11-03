"""Regression: a decode that cannot seat its batch must not return ZERO tokens, and a decode ELI
aborted itself must not be taken for one.

llama_decode returns 1 when it could not find a KV slot for the batch, and 2 when the abort
callback stopped it. `_safe_invoke_llm` recovers from 1 by dropping the reusable states, clearing
the cache and decoding fresh with headroom. 2 is ELI's own callback (Stop, shutdown, or a turn
taking the model from a background call): read as a full cache, a background call cleared the
cache and the saved state the turn was about to reuse and retried into the same abort three times.
"""
import eli.cognition.gguf_inference as g


class _Ctx:
    def __init__(self):
        self.cleared = 0

    def kv_cache_clear(self):
        self.cleared += 1


class _Llm:
    def __init__(self, fail_times=1, code=1):
        self.calls = 0
        self.code = code
        self.resets = 0
        self.fail_times = fail_times
        self._ctx = _Ctx()
        self.n_batch = 256

    def reset(self):
        self.resets += 1

    def n_ctx(self):
        return 4096

    def __call__(self, prompt, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"llama_decode returned {self.code}")
        return {"choices": [{"text": "recovered"}], "usage": {"completion_tokens": 1}}


def _patch_helpers(monkeypatch, resume_calls):
    monkeypatch.setattr(g, "_fit_generation_budget", lambda llm, p, m: (p, m))
    monkeypatch.setattr(g, "is_background_inference", lambda: False)
    monkeypatch.setattr(g, "_make_stopping_criteria", lambda bg: None)
    monkeypatch.setattr(g, "_effective_ctx_limit", lambda llm: 4096)
    monkeypatch.setattr(g, "_estimate_prompt_tokens", lambda llm, p: 100)
    monkeypatch.setattr(g, "_resume_from_saved_state",
                        lambda llm, p, create: (resume_calls.append(create), "")[1])


def test_safe_invoke_recovers_from_kv_slot_decode_failure(monkeypatch):
    resume_calls = []
    _patch_helpers(monkeypatch, resume_calls)
    llm = _Llm(fail_times=1)

    out = g._safe_invoke_llm(
        llm, "a big prompt", temperature=0.7, max_tokens=512, top_p=0.9, top_k=40,
        repeat_penalty=1.1, stop=[], stream=False, grammar=None,
    )

    assert out["choices"][0]["text"] == "recovered"   # not zero tokens
    assert llm.calls == 2                              # failed once, then recovered
    assert llm.resets >= 1 and llm._ctx.cleared >= 1   # the cache was actually cleared
    assert resume_calls == [True]                      # resume ran once, then was SKIPPED on the retry


def test_non_kv_errors_still_propagate(monkeypatch):
    """A genuine, non-KV failure must not be swallowed by the recovery path — it still raises."""
    import pytest
    resume_calls = []
    _patch_helpers(monkeypatch, resume_calls)

    class _BadLlm(_Llm):
        def __call__(self, prompt, **kw):
            self.calls += 1
            raise RuntimeError("model file is corrupt")

    with pytest.raises(RuntimeError, match="corrupt"):
        g._safe_invoke_llm(
            _BadLlm(), "p", temperature=0.7, max_tokens=256, top_p=0.9, top_k=40,
            repeat_penalty=1.1, stop=[], stream=False, grammar=None,
        )


def test_a_decode_eli_aborted_is_neither_cleared_nor_retried(monkeypatch):
    import pytest
    resume_calls = []
    _patch_helpers(monkeypatch, resume_calls)
    llm = _Llm(fail_times=4, code=2)
    monkeypatch.setattr(g._bg_tls, "cut_short", True, raising=False)   # a turn took the model
    with pytest.raises(RuntimeError, match="returned 2"):
        g._safe_invoke_llm(llm, "p", temperature=0.7, max_tokens=200, top_p=0.9, top_k=40,
                           repeat_penalty=1.1, stop=[], stream=False, grammar=None)
    assert llm.calls == 1 and llm.resets == 0 and llm._ctx.cleared == 0


def test_an_abort_nothing_asked_for_is_tried_again_as_it_was(monkeypatch):
    resume_calls = []
    _patch_helpers(monkeypatch, resume_calls)
    monkeypatch.setattr(g._bg_tls, "cut_short", False, raising=False)
    llm = _Llm(fail_times=1, code=2)
    out = g._safe_invoke_llm(llm, "p", temperature=0.7, max_tokens=200, top_p=0.9, top_k=40,
                             repeat_penalty=1.1, stop=[], stream=False, grammar=None)
    assert out["choices"][0]["text"] == "recovered" and llm._ctx.cleared == 0 and resume_calls == [True, True]
