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
    assert "dist/WHEELHOUSE*.txt" in publish        # WHEELHOUSE.txt and WHEELHOUSE-arm64.txt
    assert "dist/RELEASE_NOTES.md" in publish
    assert "windows-portable-full" in publish


def test_release_workflow_builds_full_windows_portable():
    source = RELEASE_YML.split("build-source-artifacts:", 1)[1].split("release:", 1)[0]
    assert "windows-lean windows" in source or "windows-lean" in source and "windows" in source
    assert "windows-portable-full.zip" in source


def test_gpu_packs_refresh_on_version_tags():
    gpu = (ROOT / ".github/workflows/gpu-packs.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in gpu or "tags: ['v*']" in gpu


def _upload_patterns():
    publish = RELEASE_YML.split("\n  release:", 1)[1]
    files = publish.split("files: |", 1)[1].split("fail_on_unmatched_files", 1)[0]
    return [line.strip()[len("dist/"):] for line in files.splitlines() if line.strip().startswith("dist/")]


def test_every_file_the_checksums_list_is_one_the_release_uploads():
    """SHA256SUMS.txt listed WHEELHOUSE-arm64.txt, which the release never uploaded, so
    `sha256sum -c SHA256SUMS.txt` failed for every download of the set."""
    import fnmatch
    import re
    uploaded = _upload_patterns()
    builds = RELEASE_YML.split("\n  release:", 1)[0]
    summed = []
    for patterns in re.findall(r'for f in ([^;\n]+); do\n(?:\s*\[ -e "\$f" \] \|\| continue\n)?\s*(?:sha256sum|shasum)', builds):
        summed += patterns.split()
    assert "WHEELHOUSE*.txt" in summed and "*.dmg" in summed, summed
    for pattern in summed:
        name = pattern.replace("*", "-arm64")          # a name this pattern picks up
        assert any(fnmatch.fnmatchcase(name, up) for up in uploaded), f"{name} is in the checksums, not the release"


def test_the_upload_retry_covers_what_the_release_uploads():
    """The retry step re-uploads what the first upload missed; its list is the same as the upload's."""
    publish = RELEASE_YML.split("\n  release:", 1)[1]
    retry = publish.split("shopt -s nullglob", 1)[1].split("for f in ", 1)[1].split("; do", 1)[0].split()
    assert sorted(retry) == sorted(_upload_patterns())
