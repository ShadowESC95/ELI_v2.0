"""Autopilot debugger — grounded diagnosis from real error text + real git history."""
from __future__ import annotations

from eli.runtime import autopilot_debugger as dbg

_TB = '''Traceback (most recent call last):
  File "eli/perception/tts_router.py", line 132, in _piper_prosody_args
    args += [flag, str(float(vals[key]))]
KeyError: 'length_scale'
'''


def test_traceback_gives_exception_and_affected_file():
    d = dbg.diagnose(_TB)
    assert d["ok"]
    assert "KeyError" in d["exception"]
    assert "eli/perception/tts_router.py" in d["affected_files"]
    assert "KeyError" in d["root_cause"] and "tts_router.py:132" in d["root_cause"]


def test_rollback_plan_is_grounded_in_git_history():
    d = dbg.diagnose(_TB)
    # the affected file is tracked, so a real suspect commit + a checkout line must appear
    assert d["suspect_commits"], "expected git history for a tracked file"
    assert any("git checkout" in line or "git revert" in line for line in d["rollback_plan"])


def test_validation_commands_include_the_ratchet():
    d = dbg.diagnose(_TB)
    assert any("test_no_silent_swallow" in c for c in d["validation_commands"])


def test_incidental_lint_is_not_the_root_cause():
    # tts_router.py is large; any pre-existing lint far from line 132 must NOT be blamed.
    d = dbg.diagnose(_TB)
    assert d["root_cause"].startswith("KeyError")
    # a note may summarise unrelated lint, but it is not the headline
    assert "unused" not in d["root_cause"].lower()


def test_pytest_failure_line_becomes_a_validation_command():
    out = "FAILED tests/test_voice_actions.py::test_set_voice - AssertionError: x != y"
    d = dbg.diagnose(out)
    assert "tests/test_voice_actions.py" in d["affected_files"]
    assert any("tests/test_voice_actions.py" in c for c in d["validation_commands"])


def test_empty_input_is_honest_not_fabricated():
    d = dbg.diagnose("")
    assert d["ok"]
    assert "nothing to diagnose" in d["root_cause"].lower()
    assert d["affected_files"] == []


def test_report_renders_all_sections():
    rep = dbg.format_report(dbg.diagnose(_TB))
    for section in ("Root cause", "Rollback plan", "Patch plan", "Validation commands"):
        assert section in rep


def test_stdlib_frames_are_excluded_only_repo_files_kept():
    tb = ('Traceback (most recent call last):\n'
          '  File "/usr/lib/python3.12/json/__init__.py", line 293, in load\n'
          '  File "eli/memory/vector_store.py", line 10, in search\n'
          'ValueError: bad index\n')
    d = dbg.diagnose(tb)
    assert "eli/memory/vector_store.py" in d["affected_files"]
    assert not any("site-packages" in f or f.startswith("/usr") for f in d["affected_files"])
