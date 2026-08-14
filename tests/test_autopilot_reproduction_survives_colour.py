"""The debugger must not disown a failure it just reproduced.

Surfaced by a full-suite run in a shell with ``FORCE_COLOR=3`` exported. pytest
colourises even through ``capture_output``, and every escape sequence ends in a
LETTER, which glues to the text after it:

    '\\x1b[31m\\x1b[1m1 failed\\x1b[0m'
     ..........^ 'm' and '1' are both word characters

so ``\\b\\d+\\s+failed\\b`` has no word boundary to anchor on and does not match,
and ``^FAILED\\s`` never matches because the line begins with the escape, not with
'F'. ``verify()`` ran a test, watched it fail, and reported ``reproduced: False``.

That is the one answer this function must never give: a false negative about a
real failure it has already observed. The exit status now decides — it survives
any formatting — with colour disabled in the child and stripped from the capture
so quoted output stays readable.
"""
import re

import pytest

from eli.runtime import autopilot_debugger as dbg


COLOURED_SUMMARY = (
    "\x1b[31mFAILED\x1b[0m tests/test_probe.py::\x1b[1mtest_probe\x1b[0m - assert False\n"
    "\x1b[31m===================== \x1b[31m\x1b[1m1 failed\x1b[0m\x1b[31m in 0.11s\x1b[0m ====\x1b[0m"
)


def test_the_escape_really_does_defeat_the_old_match():
    """Proves the mechanism, so this file cannot pass for the wrong reason."""
    assert not re.search(r"\b\d+\s+failed\b", COLOURED_SUMMARY)
    assert not re.search(r"^(?:FAILED|ERROR)\s", COLOURED_SUMMARY, re.M)
    # …and that stripping is what restores it.
    plain = dbg._strip_ansi(COLOURED_SUMMARY)
    assert re.search(r"\b\d+\s+failed\b", plain)
    assert re.search(r"^(?:FAILED|ERROR)\s", plain, re.M)


def test_strip_ansi_leaves_ordinary_text_alone():
    plain = "FAILED tests/test_probe.py::test_probe - assert False\n1 failed in 0.11s"
    assert dbg._strip_ansi(plain) == plain


@pytest.fixture
def probe(tmp_path):
    """A test file that genuinely fails, inside the repo pytest will run."""
    path = dbg._repo_root() / "tests" / "test_autopilot_colour_probe_tmp.py"
    path.write_text("def test_probe():\n    assert False\n", encoding="utf-8")
    yield "tests/test_autopilot_colour_probe_tmp.py::test_probe"
    path.unlink(missing_ok=True)


def test_a_failing_test_reproduces_even_with_colour_forced(probe, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "3")
    monkeypatch.setenv("PY_COLORS", "1")
    result = dbg._run_validation(dbg._repo_root(), [probe])
    assert result["ran"] is True
    assert result["failed"] is True, "a failure that was observed was reported as a pass"
    assert result["exit_status"] == 1


def test_captured_output_is_plain_text(probe, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "3")
    out = dbg._run_validation(dbg._repo_root(), [probe])["output"]
    assert "\x1b[" not in out, "escape sequences leaked into the quoted report output"


def test_a_passing_test_is_not_called_a_reproduction(monkeypatch):
    path = dbg._repo_root() / "tests" / "test_autopilot_pass_probe_tmp.py"
    path.write_text("def test_probe():\n    assert True\n", encoding="utf-8")
    monkeypatch.setenv("FORCE_COLOR", "3")
    try:
        result = dbg._run_validation(dbg._repo_root(), ["tests/test_autopilot_pass_probe_tmp.py"])
        assert result["failed"] is False
        assert result["exit_status"] == 0
    finally:
        path.unlink(missing_ok=True)


def test_no_targets_is_not_a_run():
    assert dbg._run_validation(dbg._repo_root(), []) == {
        "ran": False, "failed": False, "output": ""}
