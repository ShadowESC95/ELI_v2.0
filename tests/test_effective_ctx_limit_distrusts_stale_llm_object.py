"""Reported: a live session's streaming preflight sized a prompt against
ctx=12200 (the user's raw requested setting) while the model had actually
loaded at ctx=6144 (smart-fit reduced it to fit free VRAM) -- every
[GGUF][EFFECTIVE] log line for the same session correctly said 6144, but
llm.n_ctx() returned the stale, larger figure for this one streaming call.
generate() then correctly rejected the oversized prompt: "Requested tokens
(7160) exceed context window of 6144". The turn recovered via the existing
non-streaming retry path, but the whole point of computing a budget up front
is to not need that retry.

_effective_ctx_limit() is the single choke point nearly every caller in this
module and eli/kernel/engine.py goes through (current_context_limit() ->
_runtime_n_ctx() -> the streaming/non-streaming preflight clamps). This
covers its fix: cross-check llm.n_ctx() against load_model()'s own recorded
"effective" ctx (the authoritative record of what that llm was actually
constructed with) and never let a larger live read override a smaller,
more-conservative recorded figure.
"""
import eli.cognition.gguf_inference as G


class _FakeLLM:
    def __init__(self, n_ctx):
        self._n_ctx = n_ctx

    def n_ctx(self):
        return self._n_ctx


def test_stale_larger_live_read_is_capped_by_the_recorded_effective_ctx(monkeypatch):
    """The exact field case: llm.n_ctx() says 12200, load_model()'s own
    record says the true effective ctx was 6144 -- 6144 must win."""
    monkeypatch.setattr(G, "_model_train_ctx", lambda: 32768)
    monkeypatch.setattr(
        G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {"effective": {"n_ctx": 6144}}, raising=False,
    )
    assert G._effective_ctx_limit(_FakeLLM(12200)) == 6144


def test_agreeing_values_are_unaffected(monkeypatch):
    monkeypatch.setattr(G, "_model_train_ctx", lambda: 32768)
    monkeypatch.setattr(
        G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {"effective": {"n_ctx": 6144}}, raising=False,
    )
    assert G._effective_ctx_limit(_FakeLLM(6144)) == 6144


def test_no_recorded_report_yet_falls_back_to_live_read(monkeypatch):
    """Must not regress the normal case (no report published yet, e.g. very
    first load) -- min(loaded, train) still applies with nothing to cross-check."""
    monkeypatch.setattr(G, "_model_train_ctx", lambda: 32768)
    monkeypatch.setattr(G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {}, raising=False)
    assert G._effective_ctx_limit(_FakeLLM(6144)) == 6144


def test_trained_window_smaller_than_both_still_wins(monkeypatch):
    monkeypatch.setattr(G, "_model_train_ctx", lambda: 4096)
    monkeypatch.setattr(
        G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {"effective": {"n_ctx": 6144}}, raising=False,
    )
    assert G._effective_ctx_limit(_FakeLLM(12200)) == 4096
