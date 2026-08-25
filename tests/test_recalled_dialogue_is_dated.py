"""Recalled dialogue must be dated, or yesterday reads as now.

Stored memories were rendered with a timestamp; conversation snippets beside
them were not. Undated, last night's sign-off came back the next afternoon as
current: at 14:39 ELI said "Night's still young" and "I'll be here when you
finally wake up", echoing a conversation that had ended around 00:25. The clock
context was correct throughout -- the model was not misreading the time, it was
reading yesterday's turns as part of this exchange.
"""
import re
from pathlib import Path

import eli.cognition.agent_bus as ab


def _source() -> str:
    return Path(ab.__file__).read_text(encoding="utf-8")


def test_conversation_snippets_are_timestamped_like_stored_memories():
    src = _source()
    assert re.search(r'conv_text\.append\(f"  \[\{_ts_str\}\] \{role\}: \{txt\}"', src), (
        "recalled conversation turns are rendered without a timestamp again, so "
        "an earlier session's dialogue is indistinguishable from the current one")


def test_the_section_says_the_turns_are_from_earlier_sessions():
    src = _source()
    assert "EARLIER sessions" in src, (
        "the snippet header no longer marks the turns as past")


def test_stored_memories_are_still_timestamped():
    """The fix is symmetry -- don't lose the side that was already right."""
    src = _source()
    assert re.search(r'hits_text\.append\(f"  - \[\{ts_str\}\] \{txt\}"\)', src)


def test_a_missing_timestamp_does_not_break_the_line():
    """Older rows may have no ts; they must still render, just undated."""
    src = _source()
    assert 'else f"  {role}: {txt}"' in src, (
        "the undated fallback is gone; a hit without a ts would render '[] role:'")
