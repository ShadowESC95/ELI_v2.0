"""The prior-session search pool is wider than the prompt budget spent on it.

ELI could not answer questions about conversations from more than about a week
back. The cause was not retrieval quality: `cog.mem_summaries_recall` capped the
*search pool* at 6 summaries, so a session older than the last six was never a
candidate no matter how well it matched. Widening the pool costs a ranking pass,
not context — `cog.mem_summaries_shown` is what reaches the model.

These two knobs are easy to "tidy" back into agreement by someone who reads them
as duplicates, which would silently restore the original defect.
"""
from __future__ import annotations

from eli.core.cognition_tunables import TUNABLES


def _tunable(key: str):
    for t in TUNABLES:
        if t.key == key:
            return t
    raise AssertionError(f"tunable {key} is gone")


def test_search_pool_covers_a_meaningful_history():
    pool = _tunable("cog.mem_summaries_recall")
    assert pool.default >= 25, (
        f"session search pool is {pool.default}; at 6 ELI could not reach a "
        "conversation from a fortnight ago")


def test_pool_is_wider_than_what_is_put_in_the_prompt():
    pool = _tunable("cog.mem_summaries_recall").default
    shown = _tunable("cog.mem_summaries_shown").default
    assert pool > shown, (
        f"pool ({pool}) must exceed shown ({shown}) — a pool equal to the prompt "
        "budget means no ranking happens, it just takes the most recent N")


def test_prompt_budget_stays_modest():
    """Widening the pool must not be mistaken for licence to widen the prompt."""
    shown = _tunable("cog.mem_summaries_shown").default
    chars = _tunable("cog.mem_summary_chars").default
    assert shown * chars <= 4000, (
        f"{shown} summaries x {chars} chars would spend "
        f"{shown * chars} chars of context on session history alone")
