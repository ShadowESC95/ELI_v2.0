"""Locks on two defects from a live session (v2.1.63, 18:47–18:50).

ELI claimed it had been "keeping tabs on your project's state" from "the Simulation
Lab", citing a "branch tree" and a "development console". None of that existed. A scan
of all four SQLite stores found those names ONLY in ELI's own replies, written after it
said them; `current_room` was None, and world objects are rendered in the GUI panel and
never in the prompt. It was confabulation, not a data leak.

Two things made it possible, and both are fixed here.

**1. "Where are you getting this information?" had no route.** The only provenance route
matched jargon — "which agents contributed", "last response trace". The plain human
phrasing fell to ``fallback.chat`` at 0.60 and the model invented a source. The agent
bus records exactly which agents contributed to the previous turn, so this is answerable
from real data and must never be narrated.

**2. The evidence was fetched and then thrown away.** On the turn where the user asked
whether ELI's awareness was genuine, the bus ran seven agents at grounding 0.98 —
including a 1,415-char introspection result — and the streaming context guard trimmed
6,352 chars of it down to 685 before the model saw it. `max_tokens` is a ceiling, not an
expectation, and reserving all of it for output starved the evidence budget.
"""
import pytest

from eli.execution.router_enhanced import route
from eli.kernel.engine import _OUTPUT_RESERVE_TOKENS


def _action(text):
    return str((route(text) or {}).get("action") or "").upper()


def _via(text):
    return str(((route(text) or {}).get("meta") or {}).get("matched_by") or "")


# ── 1. provenance questions reach the real trace ────────────────────────────
@pytest.mark.parametrize("text", [
    "where are you getting this information?",      # the live case, verbatim
    "where are you getting that from?",
    "how do you know that?",
    "how do you know this?",
    "what are you basing that on?",
    "what is that based on?",
    "where did that come from?",
    "says who?",
])
def test_provenance_questions_route_to_the_last_response_trace(text):
    assert _action(text) == "EXPLAIN_LAST_RESPONSE", text


def test_the_live_question_is_labelled_traceably():
    assert "provenance" in _via("where are you getting this information?")


def test_provenance_route_demands_grounding():
    """It must not be answerable from the model's imagination — that is the bug."""
    r = route("where are you getting this information?")
    assert r["meta"].get("need_grounding") is True
    assert r["meta"].get("allow_chat_without_evidence") is False


def test_provenance_route_is_confident_enough_to_beat_the_llm_resolver():
    assert route("how do you know that?")["confidence"] >= 0.9


# ── 2. legitimate questions are NOT hijacked ────────────────────────────────
def test_the_name_audit_route_still_wins():
    """"how do you know my name" has its own dedicated route and must keep it —
    which is why the provenance patterns require a demonstrative."""
    assert _action("how do you know my name?") == "NAME_SOURCE_AUDIT"


@pytest.mark.parametrize("text", [
    "where did you put the file?",
    "where is my cv file?",
    "how are you?",
    "how do you know when to run a backup at 8pm?",
])
def test_ordinary_questions_are_not_captured(text):
    assert _action(text) != "EXPLAIN_LAST_RESPONSE", text


def test_the_original_jargon_route_still_works():
    """The narrow route this generalises must not have been broken by it."""
    assert _action("which agents contributed to that?") == "EXPLAIN_LAST_RESPONSE"


# ── 3. the evidence budget ──────────────────────────────────────────────────
def _mem_budget(n_ctx, max_tok, persona, query, reserve_tokens):
    total = int(n_ctx * 3.5 * 0.80)
    return max(400, total - persona - query - (min(max_tok, reserve_tokens) * 4))


def test_the_live_turn_would_now_keep_its_evidence():
    """The exact numbers from the log: n_ctx 10384, max_tokens 3461, 6352 chars of
    bus evidence at grounding 0.98, trimmed to 685."""
    n_ctx, max_tok, persona, query, evidence = 10384, 3461, 14500, 93, 6352
    old = _mem_budget(n_ctx, max_tok, persona, query, max_tok)          # reserve = ceiling
    new = _mem_budget(n_ctx, max_tok, persona, query, _OUTPUT_RESERVE_TOKENS)
    assert old < evidence, "fixture no longer reproduces the bug"
    assert new >= evidence, "evidence still does not fit"


def test_reserve_is_a_cap_not_an_increase():
    """When max_tokens is already small the reservation must not grow — that would
    shrink the evidence budget on short-output modes."""
    small = 256
    assert min(small, _OUTPUT_RESERVE_TOKENS) == small


def test_reserve_is_sane():
    assert 256 <= _OUTPUT_RESERVE_TOKENS <= 4096


def test_budget_never_goes_negative_on_a_huge_persona():
    """The floor must hold even when persona + query exceed the whole budget."""
    assert _mem_budget(2048, 512, 999_999, 5_000, _OUTPUT_RESERVE_TOKENS) == 400


def test_a_bigger_context_yields_a_bigger_evidence_budget():
    small = _mem_budget(4096, 1024, 6000, 100, _OUTPUT_RESERVE_TOKENS)
    large = _mem_budget(16384, 1024, 6000, 100, _OUTPUT_RESERVE_TOKENS)
    assert large > small


def test_the_shipped_guard_uses_the_capped_reserve():
    """Assert the call site, not a re-derivation — the arithmetic above is only a
    model of it."""
    import inspect
    from eli.kernel import engine as eng

    src = inspect.getsource(eng.CognitiveEngine._stream_model_response)
    assert "_OUTPUT_RESERVE_TOKENS" in src, "the streaming guard still reserves the ceiling"
    assert "_out_reserve_tok_s * 4" in src
