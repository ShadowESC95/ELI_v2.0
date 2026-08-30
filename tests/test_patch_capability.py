"""Patch target resolution — source_root and patch_capability."""
from __future__ import annotations

from pathlib import Path

import pytest

from eli.core import paths


def test_source_root_prefers_eli_source_root_env(monkeypatch, tmp_path):
    fake = tmp_path / "checkout"
    (fake / "eli" / "cognition").mkdir(parents=True)
    (fake / "eli" / "gui").mkdir(parents=True)
    (fake / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    monkeypatch.setenv("ELI_SOURCE_ROOT", str(fake))
    paths.source_root.cache_clear()
    try:
        assert paths.source_root() == fake.resolve()
    finally:
        paths.source_root.cache_clear()


def test_patch_capability_reports_git_source():
    cap = paths.patch_capability()
    assert "source_root" in cap
    assert "can_patch_live" in cap
    assert cap["install_kind"] in {"source", "packaged", "frozen"}
