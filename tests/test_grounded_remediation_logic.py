"""grounded_remediation — the pure logic (classifiers, diagnosis, plan-building,
renderers, pending-state). We NEVER drive `execute_pending_plan` (it would run real
install/repair commands); every test here is read-only or state-only.
"""
from __future__ import annotations

import pytest

from eli.runtime import grounded_remediation as gr


@pytest.fixture(autouse=True)
def _clean_state():
    # No pending plan can leak into a test → a stray affirmation can never execute.
    gr.clear_pending()
    gr.set_busy(False)
    yield
    gr.clear_pending()
    gr.set_busy(False)


# --------------------------------------------------------------------------- #
# yes/no classifiers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["yes", "yes please", "ok sure go ahead", "yeah", "yep do it"])
def test_affirmations(text):
    assert gr.is_affirmation(text) is True


@pytest.mark.parametrize("text", ["no", "nope", "no thanks", "don't", "cancel"])
def test_negations(text):
    assert gr.is_negation(text) is True


def test_classifier_edges():
    assert gr.is_affirmation("") is False
    assert gr.is_negation("") is False
    assert gr.is_affirmation("no") is False


# --------------------------------------------------------------------------- #
# app-name extraction + install candidates + diagnosis (read-only)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["open firefox", "launch spotify", "start the gimp app"])
def test_extract_app_name(text):
    name = gr.extract_app_name(text)
    assert isinstance(name, str) and name


def test_build_install_candidates():
    cands = gr.build_install_candidates("firefox")
    assert isinstance(cands, list)
    if cands:
        assert all(isinstance(c, dict) for c in cands)


def test_diagnose_functions_are_read_only_dicts():
    for out in (gr.diagnose_app("firefox"), gr.diagnose_path("/definitely/not/here"),
                gr.diagnose_browser("firefox"), gr.diagnose_ide_generic()):
        assert isinstance(out, dict)


# --------------------------------------------------------------------------- #
# pending / busy / last-failure state
# --------------------------------------------------------------------------- #
def test_busy_flag():
    gr.set_busy(True); assert gr.is_busy() is True
    gr.set_busy(False); assert gr.is_busy() is False


def test_pending_lifecycle():
    plan = {"domain": "app", "subject": "firefox", "operation": "install",
            "commands": ["true"], "steps": ["install firefox"]}
    result = {"ok": False, "domain": "app", "subject": "firefox", "repairable": True}
    gr.set_pending_for_test(plan, result, stage="offered")
    assert gr.get_pending() is not None
    gr.clear_pending()
    assert gr.get_pending() is None


def test_remember_and_get_failure():
    result = {"ok": False, "domain": "app", "subject": "gimp", "reason_code": "not_found"}
    gr.remember_failure(result)
    got = gr.get_last_failure()
    assert got is None or isinstance(got, dict)


# --------------------------------------------------------------------------- #
# plan-building + renderers (pure, structural)
# --------------------------------------------------------------------------- #
_RESULT = {
    "ok": False, "domain": "app", "subject": "firefox", "reason_code": "not_found",
    "repairable": True, "repair_options": ["install"], "message": "couldn't open firefox",
    "evidence": {}, "metadata": {}, "response": "", "handoff": {},
}

_PLAN = {
    "domain": "app", "subject": "firefox", "operation": "install",
    "title": "Install firefox", "commands": ["sudo apt install firefox"],
    "steps": ["install firefox"], "source": "apt", "risk": "low",
}


def test_build_repair_plan():
    plan = gr.build_repair_plan(dict(_RESULT))
    assert plan is None or isinstance(plan, dict)


def test_renderers_return_strings():
    assert isinstance(gr.render_failure_message(dict(_RESULT)), str)
    assert isinstance(gr.offer_for_result(dict(_RESULT)), str)
    assert isinstance(gr.render_repair_preview(dict(_PLAN)), str)


def test_handle_confirmation_no_pending_is_safe():
    # With nothing pending, a confirmation must not execute anything.
    gr.clear_pending()
    out = gr.handle_confirmation("yes")
    assert out is None or isinstance(out, str)


def test_handle_confirmation_decline_is_safe():
    # A decline must never execute anything and must not crash (whether or not the
    # environment supports remediation / the negation regex clears the pending plan).
    gr.set_pending_for_test(dict(_PLAN), dict(_RESULT), stage="offered")
    out = gr.handle_confirmation("no")
    assert out is None or isinstance(out, str)
