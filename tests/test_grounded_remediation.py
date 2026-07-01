"""Grounded remediation — yes/no intent, platform detection, and busy/pending/
failure state.

is_affirmation / is_negation drive the pending-proposal + habit-confirm flows
(they must agree across callers); the busy/pending/failure helpers track an
in-flight repair offer. Pure/model-free logic. Runs in the normal suite.
"""
from __future__ import annotations

import sys

import pytest

from eli.runtime import grounded_remediation as gr


@pytest.fixture(autouse=True)
def _clean_pending():
    gr.clear_pending()
    gr.set_busy(False)
    yield
    gr.clear_pending()
    gr.set_busy(False)


# --------------------------------------------------------------------------- #
# is_affirmation / is_negation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["yes", "yeah", "yep", "sure", "ok go ahead", "yes please"])
def test_affirmations(text):
    assert gr.is_affirmation(text) is True


@pytest.mark.parametrize("text", ["no", "nope", "don't", "no thanks"])
def test_negations(text):
    assert gr.is_negation(text) is True


def test_affirmation_negation_are_distinct():
    assert gr.is_affirmation("yes") and not gr.is_negation("yes")
    assert gr.is_negation("no") and not gr.is_affirmation("no")


def test_empty_is_neither():
    assert gr.is_affirmation("") is False
    assert gr.is_negation("") is False
    assert gr.is_affirmation("hello there") is False


# --------------------------------------------------------------------------- #
# _platform
# --------------------------------------------------------------------------- #
def test_platform_matches_host():
    p = gr._platform()
    assert p in {"linux", "macos", "windows", "other"}
    if sys.platform.startswith("linux"):
        assert p == "linux"


# --------------------------------------------------------------------------- #
# busy / pending / failure state
# --------------------------------------------------------------------------- #
def test_busy_toggle():
    gr.set_busy(True)
    assert gr.is_busy() is True
    gr.set_busy(False)
    assert gr.is_busy() is False


def test_pending_set_get_clear():
    assert not gr.get_pending()
    gr.set_pending_for_test({"steps": ["install"]}, {"ok": False, "error": "not found"})
    assert gr.get_pending()          # a pending offer now exists
    gr.clear_pending()
    assert not gr.get_pending()


def test_remember_last_failure():
    gr.remember_failure({"ok": False, "error": "boom", "action": "OPEN_APP"})
    last = gr.get_last_failure()
    assert isinstance(last, dict) and last.get("error") == "boom"
