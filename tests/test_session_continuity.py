"""Session continuity — live thread memory in prompts."""
from __future__ import annotations

from eli.cognition.correction_patterns import is_continuity_complaint, is_correction_query
from eli.runtime.session_continuity import (
    SESSION_THREAD_MAX_TURNS,
    build_inline_exchange_block,
    build_session_thread_block,
    prior_turns_excluding_current,
    session_has_prior_turns,
)


def test_session_thread_covers_twelve_turns():
    turns = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(14)
    ]
    block = build_session_thread_block(turns, user_input="turn 14")
    assert "CONVERSATION THREAD" in block
    assert "turn 2" in block
    assert "turn 13" in block
    assert "turn 0" not in block


def test_inline_exchange_excludes_current_user_message():
    turns = [
        {"role": "user", "content": "But does Tubi have it?"},
        {"role": "assistant", "content": "Maybe later"},
        {"role": "user", "content": "earlier point"},
    ]
    block = build_inline_exchange_block(turns, user_input="But does Tubi have it?")
    assert "earlier point" in block
    assert block.count("But does Tubi") == 0


def test_session_has_prior_turns():
    turns = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert session_has_prior_turns(turns, "c")
    assert not session_has_prior_turns(turns[:1], "c")


def test_continuity_complaint_routes_correction():
    q = "are you not paying attention to your previous answers?"
    assert is_continuity_complaint(q)
    assert is_correction_query(q)


def test_prior_turns_count():
    turns = [{"role": "user", "content": f"t{i}"} for i in range(5)]
    prior = prior_turns_excluding_current(turns, "t5")
    assert len(prior) == 5
    assert SESSION_THREAD_MAX_TURNS == 12


def test_a_reply_the_user_points_back_at_is_given_whole():
    """The date asked about in "what day is that from, in your long response above?" was past the
    cut every earlier turn gets."""
    long_reply = "Memory recall:\n" + "\n---\n".join(f"[Mon 28 Sep 21:{i:02d}] line {i}" for i in range(40))
    turns = [{"role": "user", "content": "how is the memory doing?"},
             {"role": "assistant", "content": long_reply},
             {"role": "user", "content": "ok"},
             {"role": "assistant", "content": "Grand."}]
    pointed = build_inline_exchange_block(turns, user_input="In your long response above, what day is that from?")
    assert "line 39" in pointed
    plain = build_inline_exchange_block(turns, user_input="what's the weather like")
    assert "line 39" not in plain


def test_the_latest_reply_is_whole_and_a_fetched_one_says_so(monkeypatch):
    """The sea wall story sat past the 280-character cut of a news briefing, so a follow-up about it
    reached a model that had never seen it."""
    import eli.runtime.orchestrator_audit_ledger as oal
    t0 = 1_800_000_000.0
    briefing = ("The county library reopened after repairs [Coast Gazette]. " + "Other story. " * 40
                + "The harbour council approved the new sea wall after a storm-damage review that ran "
                  "for two winters [Coast Gazette].")
    turns = [{"role": "user", "content": "what is the latest news?", "timestamp": t0},
             {"role": "assistant", "content": briefing, "timestamp": t0 + 60}]
    monkeypatch.setattr(oal, "recent_turns", lambda limit=50, db_path=None: [
        {"ts": t0 + 59, "action": "NEWS_FETCH", "parent_request_id": ""}])
    block = build_inline_exchange_block(turns, user_input="go deeper on the sea wall vote", budget_chars=6000)
    assert "approved the new sea wall after a storm-damage review" in block
    assert "result of NEWS_FETCH" in block


def test_the_exchange_fits_its_budget_keeping_the_newest():
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "y" * 250} for i in range(12)]
    block = build_inline_exchange_block(turns, user_input="next", budget_chars=1200)
    assert "turn 11" in block and "turn 0 " not in block
    assert len(block) <= 1200 + 200   # the budget plus the one header line


def test_a_prompt_over_budget_drops_old_lines_not_the_message():
    from eli.runtime.session_continuity import fit_exchange_prompt
    prompt = ("[Recent conversation — x]\n" + "\n".join(f"ELI: old {i} " + "z" * 100 for i in range(20))
              + "\n\nYou: go deeper on the sea wall vote")
    out = fit_exchange_prompt(prompt, 700)
    assert out.endswith("You: go deeper on the sea wall vote")
    assert out.startswith("[Recent conversation") and "old 19" in out and "old 0 " not in out
