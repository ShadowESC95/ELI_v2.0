"""CLAIM: capability_manifest.json is what the code holds now, and holds nothing about any one machine.

The manifest used to be checked one capability at a time (924 cases), and 231 of them asserted an
"active" flag that was never anything but true.
"""
from __future__ import annotations

from . import _helpers as H


def test_the_manifest_is_what_the_code_holds_now():
    from eli.runtime.capability_sync import CapabilitySync
    from eli.tools.registry.capability_updater import manifest_entry
    found = [manifest_entry(a, m) for a, m in sorted(CapabilitySync(repo_root=H.REPO).discover().items())]
    shipped = H.manifest()
    assert shipped.get("total") == len(shipped.get("capabilities", []))
    assert shipped.get("capabilities") == found, "regenerate it: python -m eli.tools.registry.capability_updater"


def test_the_supported_flag_matches_the_executor():
    flagged = {c["action"] for c in H.capabilities() if c.get("in_supported_list")}
    assert flagged == set(H.supported_actions())


def test_nothing_about_this_machine_is_shipped():
    """Verified, reachable, healthy: each install measures those for itself (capability_status)."""
    machine = {"active", "health", "last_verified_success", "reliability", "verification_count", "evidence_state",
               "reachable", "device_available", "dependency_ready", "permission_state", "discovered_at"}
    assert not [c["action"] for c in H.capabilities() if machine & set(c)]
