"""Evidence reaches the model with a date, weekday and age."""
import time

from eli.cognition.evidence_format import age_label, row_time, when_label

NOW = time.mktime(time.strptime("2026-09-25 12:00", "%Y-%m-%d %H:%M"))


def _ts(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))


def test_age_labels():
    assert age_label(_ts("2026-09-25 01:00"), NOW) == "today"
    assert age_label(_ts("2026-09-24 23:59"), NOW) == "yesterday"
    assert age_label(_ts("2026-09-20 09:00"), NOW) == "5 days ago"
    assert age_label(_ts("2026-09-04 09:00"), NOW) == "3 weeks ago"
    assert age_label(_ts("2026-05-01 09:00"), NOW).endswith("months ago")


def test_weekday_comes_from_the_timestamp():
    # 2026-08-24 was a Monday
    assert when_label(_ts("2026-08-24 19:01"), NOW).startswith("2026-08-24 Mon")


def test_a_month_old_quote_is_not_labelled_recent():
    label = when_label(_ts("2026-08-24 19:01"), NOW)
    assert "days ago" in label or "weeks ago" in label
    assert "today" not in label and "yesterday" not in label


def test_missing_time_gives_no_label():
    assert when_label(None) == "" and when_label(0) == "" and when_label("x") == ""


def test_row_time_prefers_the_event_time():
    assert row_time({"event_ts": 5.0, "ts": 9.0}) == 5.0
    assert row_time({"ts": 9.0}) == 9.0
    assert row_time({"timestamp": 7.0}) == 7.0
    assert row_time("nope") is None


def test_the_engine_prints_dates_on_ranked_hits_and_turns():
    import inspect
    from eli.kernel import engine as eng
    src = inspect.getsource(eng.CognitiveEngine.assemble_precise_context)
    assert "when_label" in src
