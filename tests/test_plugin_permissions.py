"""Consent must fail closed, and 'once' must actually mean once.

A plugin was previously ordinary Python inside ELI's process with no declaration
and no prompt. These tests pin the properties that make a community marketplace
survivable: nothing is granted without an answer, an answer given where nobody is
watching is a refusal, and a refusal can be made permanent so a plugin cannot nag.
"""
import pytest

from eli.plugins import permissions as P


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    from eli.core import paths
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    P._STORE = None
    P.set_prompt_handler(None)
    yield
    P._STORE = None
    P.set_prompt_handler(None)
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()


def test_no_consent_ui_means_denied():
    """The 3am scheduled task case: a plugin must not gain a permission by running
    where nobody can be asked."""
    v = P.check("some_plugin", "filesystem_write")
    assert v["allowed"] is False
    assert v["prompted"] is False


def test_allow_once_does_not_persist_but_holds_for_the_session():
    P.set_prompt_handler(lambda req: P.ALLOW_ONCE)
    assert P.check("p", "network")["allowed"] is True

    # asked again this session: still allowed, without re-prompting
    P.set_prompt_handler(None)
    v = P.check("p", "network")
    assert v["allowed"] is True and v["prompted"] is False

    # a new session forgets it, and with no UI it falls back to denied
    P._STORE = None
    assert P.check("p", "network")["allowed"] is False


def test_allow_always_persists_across_sessions():
    P.set_prompt_handler(lambda req: P.ALLOW_ALWAYS)
    assert P.check("p", "network")["allowed"] is True
    P._STORE = None
    P.set_prompt_handler(None)
    v = P.check("p", "network")
    assert v["allowed"] is True and v["prompted"] is False


def test_deny_always_is_never_re_asked():
    calls = []

    def handler(req):
        calls.append(req)
        return P.DENY_ALWAYS

    P.set_prompt_handler(handler)
    assert P.check("nagger", "camera")["allowed"] is False
    assert P.check("nagger", "camera")["allowed"] is False
    assert P.check("nagger", "camera")["allowed"] is False
    assert len(calls) == 1, "a permanently refused plugin must not be able to ask again"


def test_deny_once_is_asked_again():
    calls = []
    P.set_prompt_handler(lambda req: (calls.append(req), P.DENY_ONCE)[1])
    P.check("p", "microphone")
    P.check("p", "microphone")
    assert len(calls) == 2


def test_decisions_are_per_plugin_not_global():
    P.set_prompt_handler(lambda req: P.ALLOW_ALWAYS if req["plugin_id"] == "trusted"
                         else P.DENY_ALWAYS)
    assert P.check("trusted", "network")["allowed"] is True
    assert P.check("other", "network")["allowed"] is False


def test_a_broken_consent_ui_denies():
    def explode(req):
        raise RuntimeError("dialog crashed")

    P.set_prompt_handler(explode)
    assert P.check("p", "process_exec")["allowed"] is False


def test_unknown_answer_is_treated_as_refusal():
    P.set_prompt_handler(lambda req: "yes_please")
    assert P.check("p", "os_control")["allowed"] is False


def test_revoking_makes_it_ask_again():
    P.set_prompt_handler(lambda req: P.ALLOW_ALWAYS)
    assert P.check("p", "clipboard")["allowed"] is True
    P.store().revoke("p", "clipboard")
    P.set_prompt_handler(None)
    assert P.check("p", "clipboard")["allowed"] is False


def test_require_raises_when_refused():
    P.set_prompt_handler(lambda req: P.DENY_ALWAYS)
    with pytest.raises(PermissionError):
        P.require("p", "filesystem_write")


def test_unknown_capability_is_reported_critical_not_ignored():
    d = P.describe("mind_control")
    assert d["risk"] == P.RISK_CRITICAL
    assert "does not know" in d["detail"]


def test_every_decision_is_audited():
    P.set_prompt_handler(lambda req: P.ALLOW_ONCE)
    P.check("p", "network")
    entries = P.store().audit_tail(10)
    assert any(e["plugin"] == "p" and e["capability"] == "network" for e in entries)


def test_risk_of_reports_the_worst():
    assert P.risk_of(["notifications", "process_exec"]) == P.RISK_CRITICAL
    assert P.risk_of(["notifications"]) == P.RISK_LOW
