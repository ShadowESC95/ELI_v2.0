"""Release pipeline must publish the full artifact set (not AppImage-only).

Frozen bundles alone are insufficient for pip installs, Debian packages,
Windows source portables, and offline wheelhouses — all of which
self_upgrade and install.sh depend on.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_YML = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def test_release_workflow_builds_source_artifacts():
    assert "build-source-artifacts" in RELEASE_YML
    assert "wheelhouse" in RELEASE_YML
    assert "packaging/debian/build-deb.sh" in RELEASE_YML


def test_release_workflow_publishes_wheel_and_deb():
    publish = RELEASE_YML.split("release:", 1)[1]
    assert "dist/*.whl" in publish
    assert "dist/*.deb" in publish
    assert "dist/WHEELHOUSE.txt" in publish
    assert "dist/RELEASE_NOTES.md" in publish
    assert "windows-portable-full" in publish


def test_release_workflow_builds_full_windows_portable():
    source = RELEASE_YML.split("build-source-artifacts:", 1)[1].split("release:", 1)[0]
    assert "windows-lean windows" in source or "windows-lean" in source and "windows" in source
    assert "windows-portable-full.zip" in source


def test_gpu_packs_refresh_on_version_tags():
    gpu = (ROOT / ".github/workflows/gpu-packs.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in gpu or "tags: ['v*']" in gpu
