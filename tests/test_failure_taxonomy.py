"""Failures are classified by what actually went wrong, not labelled a constant.

Every improvement proposal was logged as `category="stability", area="runtime"`,
whatever had failed. A CUDA out-of-memory, a missing voice file, a refused socket
and a bad dict key all arrived identically labelled — so `improvements`, which
the self-upgrade path reports from and the daemon prioritises over, carried no
signal to prioritise or filter BY.

It also matters for what happens next: a resource exhaustion wants a settings
change, a TypeError wants a patch, and a network failure on a deliberately
offline machine wants nothing at all.
"""
from __future__ import annotations

import pytest

from eli.runtime import failure_taxonomy as T


@pytest.mark.parametrize("error,expected", [
    ("CUDA error: out of memory allocating 4096 MiB", T.RESOURCE),
    ("MemoryError", T.RESOURCE),
    ("No space left on device", T.RESOURCE),
    ("TimeoutError: model load exceeded 900s", T.TIMEOUT),
    ("subprocess.TimeoutExpired", T.TIMEOUT),
    ("ConnectionRefusedError: [Errno 111]", T.NETWORK),
    ("OfflineError: blocked by netguard policy", T.NETWORK),
    ("PermissionError: [Errno 13] Permission denied", T.PERMISSION),
    ("ModuleNotFoundError: No module named 'piper'", T.DEPENDENCY),
    ("FileNotFoundError: no such file: voices/en_GB.onnx", T.MISSING),
    ("KeyError: 'session_id'", T.DATA),
    ("json.JSONDecodeError: Expecting value", T.DATA),
    ("AssertionError: expected 3 got 4", T.CORRECTNESS),
    ("TypeError: run() takes 1 positional argument but 2 were given", T.INTERFACE),
    ("AttributeError: 'NoneType' object has no attribute 'infer'", T.INTERFACE),
    ("sqlite3.OperationalError: database is locked", T.CONCURRENCY),
])
def test_category_is_derived_from_the_failure(error, expected):
    assert T.classify_category(error) == expected


def test_an_unrecognised_failure_is_honestly_unclassified():
    """The old constant is now the answer when nothing matched — not the answer
    to everything."""
    c = T.classify("something odd happened")
    assert c["category"] == T.STABILITY
    assert c["severity"] == "unknown"


# ── area ─────────────────────────────────────────────────────────────────────

def test_area_prefers_the_traceback_path_over_the_action_name():
    """The traceback is evidence; the action name is inference."""
    err = ('FileNotFoundError: missing\n  File "eli/perception/audio_stt.py", line 12')
    assert T.classify_area(err, command="MEMORY_RECALL") == "audio"


def test_area_falls_back_to_the_action_when_there_is_no_traceback():
    assert T.classify_area("playerctl failed", command="NEXT") == "media"
    assert T.classify_area("boom", command="WEB_SEARCH") == "network"


def test_area_is_runtime_when_nothing_identifies_it():
    assert T.classify_area("boom", command="") == "runtime"


# ── severity drives what happens next ────────────────────────────────────────

def test_code_defects_are_actionable():
    for c in (T.INTERFACE, T.CORRECTNESS, T.DATA, T.CONCURRENCY):
        assert T.is_actionable(c), c


def test_environmental_failures_are_not_patchable():
    """Proposing a code change because the user is offline on purpose only fills
    the improvements table with noise."""
    for c in (T.NETWORK, T.RESOURCE, T.PERMISSION, T.DEPENDENCY, T.MISSING):
        assert not T.is_actionable(c), c


def test_the_exception_type_is_reported_when_present():
    assert T.classify("TypeError: bad call")["exception"] == "TypeError"
    assert T.classify("just a message")["exception"] == ""


def test_exception_type_beats_misleading_message_text():
    """A TypeError that happens to mention a timeout is still a TypeError."""
    assert T.classify_category("TypeError: timed out handler is not callable") == T.INTERFACE


def test_every_category_has_a_severity():
    for name in dir(T):
        if name.isupper() and isinstance(getattr(T, name), str) and "_" not in name:
            cat = getattr(T, name)
            assert T._SEVERITY.get(cat), f"{name} has no severity"
