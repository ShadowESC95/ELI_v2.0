from __future__ import annotations

from eli.runtime.experimental_inventory import build_experimental_inventory


def test_experimental_inventory_detects_avatar_kit():
    inv = build_experimental_inventory()
    assert inv.get("exists") is True
    counts = inv.get("counts") or {}
    assert counts.get("projects", 0) >= 1
    assert counts.get("scripts", 0) >= 1
    assert counts.get("assets", 0) >= 1

    projects = inv.get("projects") or []
    names = {p.get("name") for p in projects}
    assert "eli_ar_avatar_kit" in names


def test_experimental_inventory_is_non_execution_metadata_only():
    inv = build_experimental_inventory()
    project = next(p for p in inv.get("projects") or [] if p.get("name") == "eli_ar_avatar_kit")
    assert project.get("readme_exists") is True
    assert project.get("script_count", 0) >= 1
    assert isinstance(project.get("scripts"), list)
    assert all(isinstance(item, str) for item in project.get("scripts"))

