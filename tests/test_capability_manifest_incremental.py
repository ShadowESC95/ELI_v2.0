"""The shipped manifest says what the code can do; each install keeps whether it works there.

capability_manifest.json used to carry per-machine fields: every action read "active" (meaning only
"not proven broken"), and the claims bootstrap regenerated it from a test run's ledger, so a release
shipped 56 "verified" capabilities whose every timestamp came from tests against mocked libraries.
Now an entry holds code facts (where the action lives, how it is reached, the third-party modules its
branch imports) and capability_status() gives this machine's view: verified, unavailable or untested.

permission_state for a plugin-sourced action is a plugin-level rollup from PermissionStore (it is keyed
by capability class, not by action; see capability_updater._plugin_permission_rollup).
"""
import pytest

from eli.tools.registry.capability_updater import _build_capability_entry, capability_status


@pytest.fixture(autouse=True)
def isolated_capability_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CAPABILITY_STATE_DB", str(tmp_path / "cap.sqlite3"))
    worked = {}
    monkeypatch.setattr("eli.runtime.evidence_ledger.verified_actions", lambda **k: dict(worked))
    yield worked


@pytest.fixture()
def isolated_permission_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path))
    from eli.plugins import permissions
    permissions._STORE = None  # the module caches a singleton; force a fresh one per test
    yield permissions
    permissions._STORE = None


def _status(action):
    return capability_status([action])["actions"][action]


def test_an_entry_holds_only_what_the_code_says():
    entry = _build_capability_entry("OPEN_APP", {"source": "executor", "routable": True, "in_dispatch": True,
                                                 "needs": ["psutil"]})
    assert set(entry) == {"action", "source", "plugin", "routable", "in_dispatch", "in_supported_list", "needs"}
    assert entry["needs"] == ["psutil"]


def test_non_plugin_action_gets_not_applicable():
    _build_capability_entry("OPEN_APP", {"source": "executor"})
    assert _status("OPEN_APP")["permission_state"] == "not_applicable"


def test_plugin_action_with_no_decisions_yet_is_undetermined(isolated_permission_store):
    _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    assert _status("CPU_USAGE")["permission_state"] == "undetermined"


def test_plugin_action_matches_a_real_allow_always_decision(isolated_permission_store):
    isolated_permission_store.store().record("system_stats", "model_access", isolated_permission_store.ALLOW_ALWAYS)
    _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    assert _status("CPU_USAGE")["permission_state"] == "granted"


def test_a_deny_outweighs_an_allow_and_makes_it_unavailable(isolated_permission_store):
    store = isolated_permission_store.store()
    store.record("system_stats", "model_access", isolated_permission_store.ALLOW_ALWAYS)
    store.record("system_stats", "network", isolated_permission_store.DENY_ALWAYS)
    _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    st = _status("CPU_USAGE")
    assert st["permission_state"] == "denied" and st["status"] == "unavailable"


def test_discovered_at_is_set_on_first_build_and_kept_on_the_next():
    _build_capability_entry("OPEN_APP", {"source": "executor"})
    first = _status("OPEN_APP")["discovered_at"]
    _build_capability_entry("OPEN_APP", {"source": "executor"})
    assert first is not None and _status("OPEN_APP")["discovered_at"] == first


def test_regenerating_does_not_reset_a_real_probe_result():
    from eli.runtime import capability_state as cs
    from eli.runtime.evidence_arbitration import EvidenceState
    cs.record_probe_result("SOME_DEVICE_ACTION", EvidenceState.NOT_FOUND, reachable=False)
    _build_capability_entry("SOME_DEVICE_ACTION", {"source": "executor"})
    st = _status("SOME_DEVICE_ACTION")
    assert st["evidence_state"] == EvidenceState.NOT_FOUND and st["reachable"] is False
    assert st["status"] == "unavailable"


def test_nothing_recorded_is_untested_not_working():
    _build_capability_entry("NEVER_RUN_ACTION", {"source": "executor"})
    st = _status("NEVER_RUN_ACTION")
    assert st["status"] == "untested" and st["verified_at"] is None


def test_a_module_the_branch_imports_is_checked_on_this_machine():
    _build_capability_entry("NEEDS_MISSING", {"source": "executor", "needs": ["no_such_module_for_eli_tests"]})
    _build_capability_entry("NEEDS_PRESENT", {"source": "executor", "needs": ["sqlite3"]})
    assert _status("NEEDS_MISSING")["status"] == "unavailable"
    assert _status("NEEDS_PRESENT")["dependency_ready"] is True


def test_real_runs_decide_verified_and_unavailable(isolated_capability_state):
    from eli.runtime.capability_state import observe_run
    _build_capability_entry("RAN_OK", {"source": "executor"})
    isolated_capability_state["RAN_OK"] = 1.0
    assert _status("RAN_OK")["status"] == "verified"
    observe_run("NEEDS_PROGRAM", "failed", "wmctrl: command not found")
    observe_run("BAD_INPUT", "failed", "No such file or directory: 'notes.txt'")
    assert _status("NEEDS_PROGRAM")["status"] == "unavailable"
    assert _status("BAD_INPUT")["status"] == "untested"           # the user's missing file is not a missing part
    observe_run("NEEDS_PROGRAM", "ok")
    assert _status("NEEDS_PROGRAM")["dependency_ready"] is True


def test_the_listing_says_what_has_worked_here(isolated_capability_state):
    """It said "Loaded 231 public capabilities" with nothing to tell the 37 that had run from the rest."""
    from eli.execution.executor_enhanced import execute
    from eli.runtime.capability_state import observe_run
    isolated_capability_state["TIME"] = 1.0
    observe_run("OCR_IMAGE", "failed", "No module named 'pytesseract'")
    r = execute("LIST_CAPABILITIES", {})
    head = r["content"].splitlines()[0]
    assert r["ok"] and f"{r['count']} actions in my code; 1 has worked on this machine, 1 cannot run here" in head
    assert "- TIME (has worked here)" in r["content"]
    assert "- OCR_IMAGE (cannot run here: something it needs is not installed)" in r["content"]
    assert "- WEB_SEARCH\n" in r["content"]
