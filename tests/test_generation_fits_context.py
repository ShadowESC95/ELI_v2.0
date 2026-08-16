"""Locks on a generation request never exceeding the model's real context window.

Live failure at 2.1.98. A smart-fit load asked for ctx=10384, llama.cpp answered
"Failed to create llama_context", and the loader's very next candidate was the
static hw-profile at ctx=4096 — a 60% cut on the first stumble. The session then
ran in a window smaller than its own prompt:

    turn 1  prompt 3,893 tok + max_tokens 2,048  in a 4,096 window
            -> reply cut to "Yes. Here's why."
    turn 2  prompt 5,188 tok
            -> "Requested tokens (5167) exceed context window of 4096"
            -> fell back to the non-streaming broker at max_tokens=128

Three separate defects stacked:

1. The budget clamp existed in the chat path and the JSON path, and NOT in the
   streaming path — which is the path every ordinary GUI turn takes. Streaming
   passed max_tokens through untouched. (The same "streaming misses the guard
   the other paths have" shape as the last-response trace and the prompt cap.)
2. `_safe_invoke_llm`'s protection was REACTIVE — it shrank only after llama.cpp
   raised. Mid-stream that is too late: the user has already seen the truncation.
3. The loader's graded step-downs (75%, 50%…) sat BELOW hw-profile in the
   candidate list, so a smart-fit failure never reached them.

Nothing here caps how much context ELI can use. The budget is read from whatever
the model actually loaded with, so a 100B model on a 128k window gets a 128k
budget — that case is asserted below, because a fix that quietly limited large
models would be worse than the bug.
"""
import pytest

import eli.cognition.gguf_inference as G

CHARS_PER_TOK = 4


class FakeLLM:
    def __init__(self, n_ctx):
        self._n = n_ctx

    def n_ctx(self):
        return self._n


@pytest.fixture(autouse=True)
def deterministic_tokeniser(monkeypatch):
    """A fixed chars->tokens ratio, so these assert the budgeting arithmetic
    rather than a particular tokeniser."""
    monkeypatch.setattr(G, "_estimate_prompt_tokens", lambda llm, p: len(p) // CHARS_PER_TOK)
    monkeypatch.setattr(G, "_effective_ctx_limit", lambda llm: llm.n_ctx())
    monkeypatch.setattr(G, "_truncate_prompt_to_tokens",
                        lambda llm, p, budget: p[: budget * CHARS_PER_TOK])


def _prompt(tokens):
    return "x" * (tokens * CHARS_PER_TOK)


def _fit(n_ctx, prompt_tokens, max_tokens):
    p, mt = G._fit_generation_budget(FakeLLM(n_ctx), _prompt(prompt_tokens), max_tokens)
    return len(p) // CHARS_PER_TOK, mt


# ── the exact live failure ──────────────────────────────────────────────────
def test_turn_one_is_not_truncated_mid_sentence():
    """3,893-token prompt, 2,048 requested, 4,096 window."""
    ptok, mt = _fit(4096, 3893, 2048)
    assert ptok + mt <= 4096
    assert mt >= 256, "a usable answer budget, not a cut-off sentence"


def test_an_oversized_prompt_does_not_raise_and_does_not_collapse_to_128():
    """5,188-token prompt in a 4,096 window — this is what threw."""
    ptok, mt = _fit(4096, 5188, 2048)
    assert ptok + mt <= 4096
    assert mt > 128, "still degrading to the broker's emergency budget"


# ── the invariant, across every shape ───────────────────────────────────────
@pytest.mark.parametrize("n_ctx,ptok,req", [
    (4096, 3893, 2048), (4096, 5188, 2048), (4096, 100, 8192),
    (8192, 7000, 4096), (2048, 2048, 512), (32768, 30000, 8192),
])
def test_request_always_fits_the_window(n_ctx, ptok, req):
    got_p, got_m = _fit(n_ctx, ptok, req)
    assert got_p + got_m <= n_ctx, f"{got_p}+{got_m} > {n_ctx}"
    assert got_m >= 1


@pytest.mark.parametrize("n_ctx", [2048, 4096, 8192, 32768, 131072])
def test_there_is_always_room_to_say_something(n_ctx):
    """A prompt that fills the window is not a short answer, it is no answer."""
    _, mt = _fit(n_ctx, n_ctx * 2, 4096)
    assert mt >= 96


# ── large models must not be capped ─────────────────────────────────────────
def test_a_128k_window_is_not_clamped_to_something_small():
    ptok, mt = _fit(131072, 8000, 32000)
    assert mt == 32000, "a large request that fits was reduced anyway"
    assert ptok == 8000, "prompt truncated when it comfortably fit"


def test_use_all_available_context_scales_with_the_window():
    _, small = _fit(4096, 500, 0)
    _, large = _fit(131072, 500, 0)
    assert large > small * 20, "max_tokens=0 must mean the REAL window, not a constant"
    assert large > 100_000


def test_budget_is_read_from_the_model_not_a_constant():
    """The window comes from the loaded model, so a bigger model gets a bigger
    budget with no code change."""
    budgets = [_fit(n, 1000, 0)[1] for n in (4096, 16384, 65536)]
    assert budgets == sorted(budgets) and len(set(budgets)) == 3


# ── failure modes must not make things worse ────────────────────────────────
def test_an_unusable_context_limit_is_passed_through_untouched(monkeypatch):
    monkeypatch.setattr(G, "_effective_ctx_limit", lambda llm: 0)
    p, mt = G._fit_generation_budget(FakeLLM(0), _prompt(100), 512)
    assert mt == 512


def test_a_raising_tokeniser_does_not_break_generation(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tokeniser unavailable")
    monkeypatch.setattr(G, "_estimate_prompt_tokens", boom)
    p, mt = G._fit_generation_budget(FakeLLM(4096), _prompt(100), 512)
    assert mt == 512, "a broken estimate must not silently shrink the answer"


def test_a_failing_truncator_still_returns_a_fitting_budget(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cannot truncate")
    monkeypatch.setattr(G, "_truncate_prompt_to_tokens", boom)
    _, mt = _fit(4096, 5000, 2048)
    assert mt >= 1


# ── the clamp must sit where it cannot be bypassed ──────────────────────────
def test_every_generation_path_goes_through_the_fit():
    """The chat path clamped, the JSON path clamped, streaming did neither.
    _safe_invoke_llm is the one function all three funnel into."""
    import inspect
    src = inspect.getsource(G._safe_invoke_llm)
    assert "_fit_generation_budget" in src


# NOTE: the loader's candidate ORDER is asserted in
# tests/test_vram_reserve_single_default.py, alongside the reserve default that
# is the actual reason the first attempt failed. An earlier version of this file
# asserted a ctx-percentage step-down inserted straight after the user's
# settings — that was the wrong fix and was reverted: it cut context FIRST,
# inverting hardware_profile.allocate()'s documented "layers -> batch -> ctx
# LAST" order, which exists so the user's context survives.
