"""Regression: a KV-slot decode failure must not return ZERO tokens.

Observed live (Qwen3.6-35B, ctx=45056): on a near-full-context turn llama.cpp threw
`llama_decode returned 2` (it couldn't seat the batch — the cache was full of accumulated
saved states). `_safe_invoke_llm` only recovered from a *predicted* context overflow, so this
different error shape hit a bare `raise`; the engine's non-stream retry then re-ran the same
prompt against the same full cache and also failed, yielding no reply at all.

Fix: treat a KV-slot decode failure as recoverable — drop the reusable states, clear the cache,
skip the saved-state resume on the retry, and decode fresh with headroom.
"""
import eli.cognition.gguf_inference as g


class _Ctx:
    def __init__(self):
        self.cleared = 0

    def kv_cache_clear(self):
        self.cleared += 1


class _Llm:
    def __init__(self, fail_times=1):
        self.calls = 0
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
            raise RuntimeError("llama_decode returned 2")
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
