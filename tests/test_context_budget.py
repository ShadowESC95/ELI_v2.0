"""Memory must not be the first thing sacrificed to fit the window."""
from eli.cognition.context_budget import (
    memory_char_budget, output_reserve_tokens, trim_memory_context, is_recall_question,
)

CTX = (
    "Verified stored memories (2 found):\n  - [2026-09-01] alpha fact\n  - [2026-09-02] beta fact\n\n"
    "Reranked evidence:\n"
    + "\n".join(f"{i:02d}. [conversation] hit number {i} " + "x" * 120 for i in range(1, 9))
    + "\n\nRecent turns:\n"
    + "\n".join(f"User: turn {i} " + "y" * 60 for i in range(1, 7))
)


def test_the_logged_case_no_longer_hits_the_floor():
    # 12,280-token window, 4,912 max_tokens, ~21k chars of fixed material: this was the 400-char case.
    old = max(400, int(12280 * 3.5 * 0.8) - 11000 - 13000 - 4912 * 4)
    new = memory_char_budget(12280, 24000, 4912)
    assert old == 400
    assert new > 2500


def test_reserve_scales_with_the_window_and_never_exceeds_the_request():
    assert output_reserve_tokens(4912, 12280) == 12280 // 8
    assert output_reserve_tokens(300, 12280) == 300
    assert output_reserve_tokens(4912, 2048) == 256
    assert output_reserve_tokens(-1, 12280) == 12280 // 8


def test_recall_questions_keep_a_third_of_the_window():
    b = memory_char_budget(12280, 40000, 4912, wanted_chars=5199, protect_memory=True)
    assert b == min(5199, int(12280 * 3.5 * 0.8) // 3)


def test_trim_keeps_the_best_ranked_lines_not_the_tail():
    out = trim_memory_context(CTX, 900)
    assert "hit number 1 " in out and "hit number 2 " in out
    assert "hit number 8" not in out
    assert len(out) <= 900 + 40


def test_trim_keeps_the_newest_turns():
    out = trim_memory_context(CTX, 1300)
    assert "turn 6" in out
    assert "turn 1 " not in out


def test_verified_block_survives_first():
    out = trim_memory_context(CTX, 420)
    assert "alpha fact" in out


def test_short_context_is_untouched():
    assert trim_memory_context("Recent turns:\nUser: hi", 4000) == "Recent turns:\nUser: hi"


def test_a_header_is_never_left_alone():
    out = trim_memory_context(CTX, 500)
    for header in ("Reranked evidence:", "Recent turns:"):
        if header in out:
            after = out.split(header, 1)[1].lstrip("\n")
            assert after and not after.startswith(("Verified", "Reranked", "Recent"))


def test_recall_question_detection():
    assert is_recall_question("What movies/series was i watching the past week or two?")
    assert is_recall_question("remember our recent conversations?")
    assert not is_recall_question("open spotify")
