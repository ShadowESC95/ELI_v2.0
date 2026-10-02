"""Phase 3 of the identity/provenance plan (2026-10-02): capability_manifest.json
was fully wiped and rebuilt from a fresh AST scan on every regen (capability_
updater.py) — any field not re-derivable from that scan + evidence_ledger was
lost every time, which is why `active` had always been a hardcoded True with
no real detection: there was nowhere to persist a real answer between regens.

eli.runtime.capability_state is that place — one row per action, updated
incrementally, never wiped wholesale. Mirrors test_orchestrator_audit_ledger.
py's style: every call passes an explicit db_path to a throwaway file.
"""
import os
import tempfile

import pytest

from eli.runtime import capability_state as cs
from eli.runtime.evidence_arbitration import EvidenceState


@pytest.fixture()
def db():
    return os.path.join(tempfile.mkdtemp(prefix="eli_cap_state_"), "cap.sqlite3")


def test_unknown_action_returns_none_not_a_fabricated_default(db):
    assert cs.get_state("NEVER_SEEN", db_path=db) is None


def test_touch_discovered_persists_and_is_idempotent(db):
    cs.touch_discovered("OPEN_APP", now=100.0, db_path=db)
    first = cs.get_state("OPEN_APP", db_path=db)
    assert first["discovered_at"] == 100.0

    cs.touch_discovered("OPEN_APP", now=999.0, db_path=db)
    second = cs.get_state("OPEN_APP", db_path=db)
    assert second["discovered_at"] == 100.0, "a second discovery must not overwrite the first"


def test_upsert_merges_fields_without_wiping_others(db):
    """The actual bug being fixed: capability_manifest.json's full-wipe-and-
    rebuild destroyed exactly this kind of persistent signal every regen."""
    cs.upsert_state("OPEN_APP", db_path=db, reachable=True)
    cs.upsert_state("OPEN_APP", db_path=db, device_available=True)

    state = cs.get_state("OPEN_APP", db_path=db)
    assert state["reachable"] is True
    assert state["device_available"] is True  # not wiped by the second call


def test_upsert_rejects_an_unknown_field(db):
    with pytest.raises(ValueError):
        cs.upsert_state("OPEN_APP", db_path=db, made_up_field=1)


def test_record_probe_result_sets_evidence_state_and_last_probe_at(db):
    cs.record_probe_result("OPEN_APP", EvidenceState.FOUND, reachable=True, db_path=db)
    state = cs.get_state("OPEN_APP", db_path=db)
    assert state["evidence_state"] == EvidenceState.FOUND
    assert state["reachable"] is True
    assert state["last_probe_at"] is not None


def test_regenerating_state_does_not_reset_last_probe_at_or_evidence_state(db):
    """Direct regression test for the plan's own stated core bug: a later
    'regen' (here, calling touch_discovered/upsert_state again, exactly as
    capability_updater.py does on every run) must not null out what a probe
    already established."""
    cs.record_probe_result("OPEN_APP", EvidenceState.FOUND, reachable=True, db_path=db)
    before = cs.get_state("OPEN_APP", db_path=db)

    # Simulate a later capability_updater.py run touching this same action.
    cs.touch_discovered("OPEN_APP", db_path=db)
    cs.upsert_state("OPEN_APP", db_path=db, permission_state="not_applicable")

    after = cs.get_state("OPEN_APP", db_path=db)
    assert after["last_probe_at"] == before["last_probe_at"]
    assert after["evidence_state"] == before["evidence_state"]
    assert after["reachable"] == before["reachable"]


def test_record_probe_result_caches_evidence_ledger_reliability(db, monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.evidence_ledger.last_verified_success", lambda action, **k: 123.0)
    monkeypatch.setattr(
        "eli.runtime.evidence_ledger.predict_success", lambda action, **k: 0.75)

    cs.record_probe_result("OPEN_APP", EvidenceState.FOUND, db_path=db)
    state = cs.get_state("OPEN_APP", db_path=db)
    assert state["last_verified_success"] == 123.0
    assert state["reliability"] == 0.75


# ── freshness policy ──────────────────────────────────────────────────────

def test_a_never_probed_action_is_stale():
    assert cs.is_stale("NEVER_SEEN", "reachable", db_path=os.path.join(
        tempfile.mkdtemp(), "x.sqlite3")) is True


def test_a_recently_probed_dimension_is_not_stale(db):
    cs.record_probe_result("OPEN_APP", EvidenceState.FOUND, reachable=True,
                           now=1000.0, db_path=db)
    assert cs.is_stale("OPEN_APP", "reachable", now=1000.0 + 60, db_path=db) is False


def test_an_old_probe_is_stale_after_its_ttl(db):
    cs.record_probe_result("OPEN_APP", EvidenceState.FOUND, reachable=True,
                           now=1000.0, db_path=db)
    assert cs.is_stale("OPEN_APP", "reachable", now=1000.0 + 6 * 60, db_path=db) is True


def test_a_dimension_with_no_freshness_policy_is_never_forced_stale(db):
    cs.record_probe_result("OPEN_APP", EvidenceState.FOUND, db_path=db)
    assert cs.is_stale("OPEN_APP", "evidence_state", db_path=db) is False


# ── probe adapters: 4 genuinely incompatible native shapes, confirmed by
# direct read, normalized to one (evidence_state, cost_estimate, detail) ────

def test_adapt_load_probe_maps_all_four_real_verdicts():
    from eli.core.load_probe import PROVEN_OK, PROVEN_BAD, UNPROVEN_TIMEOUT, UNPROVEN_UNAVAILABLE
    assert cs._adapt_load_probe(PROVEN_OK, "fine")[0] == EvidenceState.FOUND
    assert cs._adapt_load_probe(PROVEN_BAD, "crashed")[0] == EvidenceState.NOT_FOUND
    assert cs._adapt_load_probe(UNPROVEN_TIMEOUT, "slow")[0] == EvidenceState.INSPECTION_FAILED
    assert cs._adapt_load_probe(UNPROVEN_UNAVAILABLE, "n/a")[0] == EvidenceState.NOT_AVAILABLE


def test_adapt_mic_probe_handles_none_and_a_real_rms():
    assert cs._adapt_mic_probe(None)[0] == EvidenceState.NOT_FOUND
    state, _, detail = cs._adapt_mic_probe(450)
    assert state == EvidenceState.FOUND
    assert "450" in detail


def test_adapt_ble_probe_handles_error_protocol_and_neither():
    assert cs._adapt_ble_probe({"error": "connect failed"})[0] == EvidenceState.INSPECTION_FAILED
    assert cs._adapt_ble_probe({"protocol": "tuya", "error": None})[0] == EvidenceState.FOUND
    assert cs._adapt_ble_probe({})[0] == EvidenceState.NOT_FOUND


def test_adapt_mqtt_probe_handles_ok_and_failure():
    assert cs._adapt_mqtt_probe({"ok": True})[0] == EvidenceState.FOUND
    assert cs._adapt_mqtt_probe({"ok": False, "error": "refused"})[0] == EvidenceState.NOT_FOUND


def test_all_four_adapters_are_registered():
    assert set(cs._ADAPTERS) == {"load_probe", "mic_probe", "ble_probe", "mqtt_probe"}


# ── probe selection ──────────────────────────────────────────────────────

def test_cheapest_adapter_for_reachable_is_mqtt_not_ble():
    """A plain TCP connect (mqtt) is mechanically cheaper than a BLE GATT
    negotiation (ble) — both resolve 'reachable', mqtt should win."""
    assert cs.select_cheapest_adapter("reachable") == "mqtt_probe"


def test_cheapest_adapter_for_device_available_is_mic():
    assert cs.select_cheapest_adapter("device_available") == "mic_probe"


def test_a_dimension_with_no_registered_adapter_returns_none():
    assert cs.select_cheapest_adapter("dependency_ready") is None
