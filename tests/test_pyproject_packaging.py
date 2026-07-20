"""Packaging smoke — catches TOML/script regressions before CI install fails."""
from __future__ import annotations

from pathlib import Path

from eli.core.toml_util import load_toml


def test_project_scripts_are_strings():
    """Dotted script names (eli-v2.0) must be quoted or TOML nests them."""
    root = Path(__file__).resolve().parents[1]
    scripts = (load_toml(root / "pyproject.toml").get("project") or {}).get("scripts") or {}
    assert scripts, "project.scripts must not be empty"
    for name, target in scripts.items():
        assert isinstance(target, str), (
            f"project.scripts.{name!r} must be a string entry point, got {type(target).__name__}: {target!r}"
        )
        assert ":" in target, f"project.scripts.{name!r} looks malformed: {target!r}"


def test_package_name_matches_distribution():
    root = Path(__file__).resolve().parents[1]
    data = load_toml(root / "pyproject.toml")
    assert data["project"]["name"] == "eli-v2.0"
    assert data["project"]["version"] == "2.1.19"


def test_capability_manifest_shipped():
    root = Path(__file__).resolve().parents[1]
    manifest = root / "capability_manifest.json"
    assert manifest.is_file(), "capability_manifest.json must be tracked for fresh clones"
    data = __import__("json").loads(manifest.read_text(encoding="utf-8"))
    assert data.get("total", 0) >= 200
