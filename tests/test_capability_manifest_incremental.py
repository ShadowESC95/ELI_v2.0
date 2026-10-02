"""Phase 3 of the identity/provenance plan (2026-10-02): capability_updater.py
now merges capability_state.py's incremental, persistent dimensions into
each manifest entry instead of only emitting the 9 AST/evidence_ledger-
derived fields it always has. `active` is a real derived field now (not
proven broken along any tracked dimension), not a hardcoded True.

permission_state for a plugin-sourced action is a plugin-level rollup from
PermissionStore (not a per-action lookup — PermissionStore is keyed by one
of 14 generic capability CLASSES a plugin declares in its manifest, and
there is no existing mapping from a specific action to which of those
classes it needs; see capability_updater.py's _plugin_permission_rollup for
the full reasoning). Coarser than per-action, but every value is grounded
in a real stored PermissionStore decision.
"""
import os

import pytest

from eli.tools.registry.capability_updater import _build_capability_entry


@pytest.fixture(autouse=True)
def isolated_capability_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CAPABILITY_STATE_DB", str(tmp_path / "cap.sqlite3"))
    yield


@pytest.fixture()
def isolated_permission_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path))
    from eli.plugins import permissions
    permissions._STORE = None  # the module caches a singleton; force a fresh one per test
    yield permissions
    permissions._STORE = None


def test_non_plugin_action_gets_not_applicable():
    entry = _build_capability_entry("OPEN_APP", {"source": "executor"})
    assert entry["permission_state"] == "not_applicable"


def test_plugin_action_with_no_decisions_yet_is_undetermined(isolated_permission_store):
    entry = _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    assert entry["permission_state"] == "undetermined"


def test_plugin_action_matches_a_real_allow_always_decision(isolated_permission_store):
    isolated_permission_store.store().record(
        "system_stats", "model_access", isolated_permission_store.ALLOW_ALWAYS)

    entry = _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    assert entry["permission_state"] == "granted"


def test_plugin_action_matches_a_real_deny_always_decision(isolated_permission_store):
    isolated_permission_store.store().record(
        "system_stats", "network", isolated_permission_store.DENY_ALWAYS)

    entry = _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    assert entry["permission_state"] == "denied"


def test_a_deny_outweighs_an_allow_on_mixed_grants(isolated_permission_store):
    """The more cautious signal wins when a plugin's grants are mixed —
    this is a rollup across all of a plugin's capability classes, not a
    single per-action answer."""
    store = isolated_permission_store.store()
    store.record("system_stats", "model_access", isolated_permission_store.ALLOW_ALWAYS)
    store.record("system_stats", "network", isolated_permission_store.DENY_ALWAYS)

    entry = _build_capability_entry("CPU_USAGE", {"source": "plugin", "plugin": "system_stats"})
    assert entry["permission_state"] == "denied"


def test_discovered_at_is_set_on_first_build_and_kept_on_the_next():
    first = _build_capability_entry("OPEN_APP", {"source": "executor"})
    assert first["discovered_at"] is not None

    second = _build_capability_entry("OPEN_APP", {"source": "executor"})
    assert second["discovered_at"] == first["discovered_at"]


def test_regenerating_does_not_reset_a_real_probe_result():
    """Direct regression test for the plan's core bug: capability_manifest.
    json's full-wipe-and-rebuild destroyed exactly this kind of persistent
    signal every regen. _build_capability_entry is what update_capability_
    manifest() calls per action on every run — calling it again must not
    erase evidence a probe already recorded."""
    from eli.runtime import capability_state as cs
    from eli.runtime.evidence_arbitration import EvidenceState

    cs.record_probe_result("SOME_DEVICE_ACTION", EvidenceState.NOT_FOUND, reachable=False)

    entry = _build_capability_entry("SOME_DEVICE_ACTION", {"source": "executor"})
    assert entry["evidence_state"] == EvidenceState.NOT_FOUND
    assert entry["reachable"] is False
    assert entry["active"] is False  # proven unreachable, not just unverified


def test_active_is_true_when_nothing_proves_it_broken():
    """Missing evidence is not the same as failing evidence — an action
    nothing has ever probed must still read as active, the same visible
    behavior as the old hardcoded True, but now for a real reason."""
    entry = _build_capability_entry("NEVER_PROBED_ACTION", {"source": "executor"})
    assert entry["active"] is True
    assert entry["reachable"] is None
    assert entry["device_available"] is None
