"""MULTI_COMMAND must survive a crash mid-sequence and never re-run a step that already
succeeded when the same phrase is resubmitted."""
import pytest

from eli.execution import command_sequence_log as log
from eli.execution.executor_enhanced import execute


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_COMMAND_SEQUENCE_LOG", str(tmp_path / "seq.json"))


def test_resumes_after_a_simulated_crash():
    raw = "what time is it and what time is it"
    cmds = ["what time is it", "what time is it"]

    # simulate a crash: step 0 completed and was durably recorded, step 1 never ran
    seq = log.start_or_resume(raw, cmds)
    log.mark_step(seq["sequence_id"], 0, True, "• what time is it →\nSTEP-0-RESULT")

    r = execute("MULTI_COMMAND", {"commands": cmds, "raw": raw})
    assert r["ok"] is True
    assert r["meta"]["resumed"] is True
    assert "STEP-0-RESULT" in r["content"]
    assert "(already done)" in r["content"]
    # step 1 actually ran this call (it wasn't in done_ok)
    assert r["content"].count("•") == 2


def test_a_failed_step_is_retried_not_the_whole_chain():
    raw = "what time is it and this will definitely fail and what time is it"
    cmds = ["what time is it", "this will definitely fail", "what time is it"]

    seq = log.start_or_resume(raw, cmds)
    log.mark_step(seq["sequence_id"], 0, True, "• what time is it →\nOK-0")
    log.mark_step(seq["sequence_id"], 1, False, "• this will definitely fail →\nfailed: nope")
    log.mark_step(seq["sequence_id"], 2, True, "• what time is it →\nOK-2")
    log.finish(seq["sequence_id"], all_ok=False)   # a real failure stays resumable

    resumed = log.start_or_resume(raw, cmds)
    assert resumed["resumed"] is True
    assert set(resumed["done_ok"].keys()) == {0, 2}
    assert 1 not in resumed["done_ok"]


def test_a_fully_successful_run_does_not_resume():
    raw = "what time is it"
    cmds = ["what time is it"]
    seq = log.start_or_resume(raw, cmds)
    log.mark_step(seq["sequence_id"], 0, True, "• what time is it →\nOK")
    log.finish(seq["sequence_id"], all_ok=True)

    again = log.start_or_resume(raw, cmds)
    assert again["resumed"] is False
    assert again["done_ok"] == {}
    assert again["sequence_id"] != seq["sequence_id"]


def test_resume_window_expires():
    raw = "what time is it and what time is it"
    cmds = ["what time is it", "what time is it"]
    old = 1_000_000.0  # far enough in the past to be outside the resume window
    seq = log.start_or_resume(raw, cmds, now=old)
    log.mark_step(seq["sequence_id"], 0, True, "• what time is it →\nOK", now=old)

    later = log.start_or_resume(raw, cmds, now=old + 7200.0)  # +2h, past the 1h window
    assert later["resumed"] is False
    assert later["done_ok"] == {}


def test_execute_without_raw_key_does_not_crash():
    r = execute("MULTI_COMMAND", {"commands": ["what time is it", "what time is it"]})
    assert r["ok"] is True
    assert r["content"].count("•") == 2
