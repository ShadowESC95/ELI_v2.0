"""Two things ELI got wrong about itself, from one live 2.3.8 session.

**The clock.** At 10:47 ELI opened with "Morning's barely past noon" and the user
had to correct it. `part_of_day()` had existed in eli/runtime/reflection.py all
along and was correct, but only the proactive daemon's greeting and the daily-report
title called it — the chat prompt never carried the time, so the model guessed.
Three separate output blocklists already stripped "current time (authoritative" from
replies, filtering a string nothing produced: the consumers outlived the producer.

**The daemon.** In the same session the startup log said "Daemon started — continuous
learning active", the daemon visibly produced world suggestions, a news digest and a
pattern analysis, and the identity audit reported `daemon_running=False pid=0`.
`frontier_status` only looked for `proactive/daemon.pid`, and the GUI runs the daemon
as a thread inside its own process, so no pid file is ever written. Disowning a
capability you are actively using is the same class of fault as claiming one you lack.
"""
import json
import re
import time
from datetime import datetime

import pytest


# ── the clock ─────────────────────────────────────────────────────────────────

def _brief(text: str = "hello") -> str:
    from eli.cognition.context_synthesiser import build_persona_handoff
    return json.dumps(build_persona_handoff(text), default=str)


def test_the_prompt_carries_the_current_time():
    assert "CURRENT TIME" in _brief(), "the model has no idea what time it is"


def test_the_time_in_the_prompt_is_actually_now():
    blob = _brief()
    m = re.search(r"CURRENT TIME[^\"]*?(\d{2}):(\d{2})", blob)
    assert m, "no clock time found in the brief"
    now = datetime.now()
    prompt_minutes = int(m.group(1)) * 60 + int(m.group(2))
    real_minutes = now.hour * 60 + now.minute
    assert abs(prompt_minutes - real_minutes) <= 2, "the injected time is not the wall clock"


def test_the_part_of_day_matches_the_hour():
    from eli.runtime.reflection import part_of_day
    blob = _brief()
    expected = part_of_day()
    assert expected in blob, f"brief does not say it is {expected}"


@pytest.mark.parametrize("hour,expected", [
    (0, "morning"), (9, "morning"), (11, "morning"),
    (12, "afternoon"), (16, "afternoon"),
    (17, "evening"), (23, "evening"),
])
def test_part_of_day_boundaries(hour, expected):
    """10:47 is morning. The reply that started this said otherwise."""
    ts = time.mktime(datetime.now().replace(hour=hour, minute=30).timetuple())
    from eli.runtime.reflection import part_of_day
    assert part_of_day(ts) == expected


def test_the_brief_tells_the_model_not_to_guess():
    blob = _brief()
    assert "Do not guess the time" in blob


# ── the daemon ────────────────────────────────────────────────────────────────

def test_is_running_does_not_construct_a_daemon():
    """A status check that creates the thing it reports on is not a status check."""
    import eli.planning.proactive_daemon as pd
    before = pd._daemon
    pd.is_running()
    assert pd._daemon is before


def test_no_daemon_reports_not_running(monkeypatch):
    import eli.planning.proactive_daemon as pd
    monkeypatch.setattr(pd, "_daemon", None, raising=False)
    state = pd.is_running()
    assert state["running"] is False and state["mode"] == "none"


def test_a_live_in_process_daemon_is_reported_running(monkeypatch):
    import eli.planning.proactive_daemon as pd

    class _Live:
        running = True

    class _Thread:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(pd, "_daemon", _Live(), raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", _Thread(), raising=False)
    assert pd.is_running()["running"] is True


def test_a_dead_thread_is_not_reported_running(monkeypatch):
    """The flag stays True if the thread dies without calling stop(), so the flag
    alone would keep claiming the daemon is alive after it crashed."""
    import eli.planning.proactive_daemon as pd

    class _Live:
        running = True

    class _Dead:
        @staticmethod
        def is_alive():
            return False

    monkeypatch.setattr(pd, "_daemon", _Live(), raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", _Dead(), raising=False)
    state = pd.is_running()
    assert state["running"] is False
    assert state["thread_alive"] is False
    assert state["flag"] is True          # the discrepancy stays visible


def test_frontier_status_prefers_the_in_process_answer(monkeypatch):
    import eli.planning.proactive_daemon as pd

    class _Live:
        running = True

    class _Thread:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(pd, "_daemon", _Live(), raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", _Thread(), raising=False)

    from eli.runtime.frontier_status import build_frontier_status_report
    proactive = build_frontier_status_report("")["proactive"]
    assert proactive["running"] is True
    assert proactive["detected_via"] == "in_process"
    assert proactive["pid"] == 0, "in-process daemons have no pid, and that is fine"


# ── the probe budget ──────────────────────────────────────────────────────────

def test_the_load_probe_budget_is_thirty_seconds():
    """60s bought nothing on a config the smart-fit fallback had already measured —
    the operator just waited a minute longer for the same answer."""
    from eli.core.load_probe import _DEFAULT_TIMEOUT_S
    assert _DEFAULT_TIMEOUT_S == 30.0
