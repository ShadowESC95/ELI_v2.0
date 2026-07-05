"""Packaging smoke — catches TOML/script regressions before CI install fails."""
from __future__ import annotations

import tomllib
from pathlib import Path


def test_project_scripts_are_strings():
    """Dotted script names (eli-v2.0) must be quoted or TOML nests them."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = (data.get("project") or {}).get("scripts") or {}
    assert scripts, "project.scripts must not be empty"
    for name, target in scripts.items():
        assert isinstance(target, str), (
            f"project.scripts.{name!r} must be a string entry point, got {type(target).__name__}: {target!r}"
        )
        assert ":" in target, f"project.scripts.{name!r} looks malformed: {target!r}"


def test_package_name_matches_distribution():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "eli-v2.0"
