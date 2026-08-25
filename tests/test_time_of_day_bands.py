"""The stated time bands and the actual ones must never drift apart.

At 00:21 ELI opened with "Morning, Jason." It was not hallucinating: part_of_day()
had only three bands, so `hour < 12` returned "morning" for every hour after
midnight, and context_synthesiser handed that to the model as authoritative fact
under "Do not guess the time or the part of day". The prose said the same thing.
Both had to be wrong together for the bug to exist, so both are checked together.
"""
import inspect
import re
import time

import eli.cognition.context_synthesiser as cs
from eli.runtime.reflection import part_of_day, report_label


def _at(hour: int) -> float:
    return time.mktime(time.struct_time((2026, 8, 25, hour, 30, 0, 1, 237, -1)))


def test_after_midnight_is_night_not_morning():
    for h in (0, 1, 2, 3, 4):
        assert part_of_day(_at(h)) == "night", f"{h:02d}:30 reported as morning again"


def test_bands_cover_every_hour_and_wrap():
    seen = {h: part_of_day(_at(h)) for h in range(24)}
    assert seen[5] == "morning" and seen[11] == "morning"
    assert seen[12] == "afternoon" and seen[16] == "afternoon"
    assert seen[17] == "evening" and seen[20] == "evening"
    assert seen[21] == "night" and seen[23] == "night"
    assert set(seen.values()) == {"night", "morning", "afternoon", "evening"}


def test_prose_given_to_the_model_matches_the_real_bands():
    """The instruction the model is told to trust must state the true boundaries."""
    # Adjacent string literals are joined first: the sentence is built from
    # several concatenated pieces, so a naive search sees it broken up.
    src = re.sub(r'"\s*\n\s*"', "", inspect.getsource(cs))
    m = re.search(r"Night is (\d{2}):00-(\d{2}):00, morning (\d{2}):00-(\d{2}):00, "
                  r"afternoon (\d{2}):00-(\d{2}):00, evening (\d{2}):00-(\d{2}):00", src)
    assert m, "the time-band prose is gone or reworded; it must stay checkable"
    n_start, n_end, m_start, m_end, a_start, a_end, e_start, e_end = (int(g) for g in m.groups())
    for h in range(24):
        actual = part_of_day(_at(h))
        if n_start <= h or h < n_end:
            stated = "night"
        elif m_start <= h < m_end:
            stated = "morning"
        elif a_start <= h < a_end:
            stated = "afternoon"
        else:
            stated = "evening"
        assert actual == stated, (
            f"{h:02d}:00 — prose says {stated}, part_of_day says {actual}")


def test_the_greeting_never_becomes_a_farewell():
    """'Good night' is a farewell; the daemon template must not produce it."""
    import eli.planning.proactive_daemon as pd
    src = inspect.getsource(pd)
    assert 'f"Good {_part_of_day()}"' not in src, (
        "the greeting drops part_of_day straight into 'Good {...}', which now "
        "yields 'Good night' as a GREETING")


def test_report_label_follows_the_clock():
    assert report_label(_at(2)).lower().startswith("night")
    assert report_label(_at(9)).lower().startswith("morning")
