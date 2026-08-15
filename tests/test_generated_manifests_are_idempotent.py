"""Regenerating a manifest with no capability change must not rewrite the file.

`capability_manifest.json` and `capability_inventory.generated.json` are tracked,
and both writers stamped a fresh `generated_at` on every run — every app start,
every test run. The files were therefore permanently modified in git: they had to
be manually excluded from each of seven release commits in a row, and a genuine
capability change would have been indistinguishable from that noise sitting in the
same diff.

Both writers now compare against what is already on disk and skip the write when
the only difference would be the timestamp.
"""
import json
import time

import pytest


def _payload(**over):
    base = {
        "generated_at": "2026-08-15T10:00:00",
        "total": 2,
        "capabilities": [{"action": "A", "routable": True},
                         {"action": "B", "routable": False}],
    }
    base.update(over)
    return base


# ── capability_manifest.json ────────────────────────────────────────────────
def test_manifest_match_ignores_only_the_timestamp(tmp_path):
    from eli.tools.registry.capability_updater import _manifest_matches

    path = tmp_path / "capability_manifest.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    # Same capabilities, later clock → considered a match, so no write.
    assert _manifest_matches(path, _payload(generated_at="2026-08-15T23:59:59")) is True


def test_manifest_match_is_false_when_capabilities_change(tmp_path):
    from eli.tools.registry.capability_updater import _manifest_matches

    path = tmp_path / "capability_manifest.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    changed = _payload(total=3,
                       capabilities=[{"action": "A", "routable": True},
                                     {"action": "B", "routable": False},
                                     {"action": "C", "routable": True}])
    assert _manifest_matches(path, changed) is False


def test_a_missing_or_corrupt_manifest_is_not_a_match(tmp_path):
    from eli.tools.registry.capability_updater import _manifest_matches

    missing = tmp_path / "nope.json"
    assert _manifest_matches(missing, _payload()) is False

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert _manifest_matches(corrupt, _payload()) is False


# ── capability_inventory.generated.json ─────────────────────────────────────
@pytest.fixture
def sync(tmp_path):
    from eli.runtime.capability_sync import CapabilitySync
    return CapabilitySync(repo_root=tmp_path)


def test_inventory_is_not_rewritten_when_nothing_changed(sync):
    caps = {"A": {"source": "executor", "routable": True},
            "B": {"source": "plugin", "routable": False}}

    sync._write_inventory(caps)
    assert sync.inventory_path.exists()
    first = sync.inventory_path.read_text(encoding="utf-8")
    mtime = sync.inventory_path.stat().st_mtime_ns

    time.sleep(0.01)
    sync._write_inventory(caps)          # same capabilities, later clock
    assert sync.inventory_path.read_text(encoding="utf-8") == first
    assert sync.inventory_path.stat().st_mtime_ns == mtime, "file was rewritten"


def test_inventory_is_rewritten_when_a_capability_appears(sync):
    caps = {"A": {"source": "executor", "routable": True}}
    sync._write_inventory(caps)
    before = sync.inventory_path.read_text(encoding="utf-8")

    caps["NEW_ACTION"] = {"source": "executor", "routable": True}
    sync._write_inventory(caps)
    after = sync.inventory_path.read_text(encoding="utf-8")

    assert after != before
    assert "NEW_ACTION" in after


def test_inventory_is_rewritten_when_a_capability_disappears(sync):
    caps = {"A": {"source": "executor", "routable": True},
            "GONE": {"source": "executor", "routable": True}}
    sync._write_inventory(caps)
    assert "GONE" in sync.inventory_path.read_text(encoding="utf-8")

    del caps["GONE"]
    sync._write_inventory(caps)
    assert "GONE" not in sync.inventory_path.read_text(encoding="utf-8")


def test_first_write_always_happens(sync):
    assert not sync.inventory_path.exists()
    sync._write_inventory({"A": {"source": "executor", "routable": True}})
    assert sync.inventory_path.exists()
