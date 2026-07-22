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
    # Shape, not a hardcoded literal: pinning the exact version here just made
    # this a FOURTH place to edit on every release (it failed the 2.1.24 bump
    # while asserting nothing real). The invariant worth guarding is below.
    import re
    assert re.fullmatch(r"\d+\.\d+\.\d+", data["project"]["version"]), \
        f"version must be MAJOR.MINOR.PATCH, got {data['project']['version']!r}"


def test_release_tag_default_tracks_pyproject_version():
    """The self-upgrade default release tag must match the packaged version.

    These are separate files, so a release bump can update one and miss the
    other — leaving a shipped build pointing its updater at the PREVIOUS tag.
    """
    root = Path(__file__).resolve().parents[1]
    version = load_toml(root / "pyproject.toml")["project"]["version"]
    src = (root / "eli" / "kernel" / "self_upgrade.py").read_text(encoding="utf-8")
    import re
    m = re.search(r'ELI_RELEASE_TAG"\s*,\s*"v([0-9.]+)"', src)
    assert m, "could not find the _DEFAULT_RELEASE_TAG fallback in self_upgrade.py"
    assert m.group(1) == version, (
        f"self_upgrade default tag v{m.group(1)} != pyproject version {version} — "
        "bump both when releasing")


def test_capability_manifest_shipped():
    root = Path(__file__).resolve().parents[1]
    manifest = root / "capability_manifest.json"
    assert manifest.is_file(), "capability_manifest.json must be tracked for fresh clones"
    data = __import__("json").loads(manifest.read_text(encoding="utf-8"))
    assert data.get("total", 0) >= 200
