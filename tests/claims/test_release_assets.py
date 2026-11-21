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


def test_no_build_script_calls_a_tracked_file_gitignored():
    """build_packages.sh and package_desktop_app.sh said capability_manifest.json is gitignored, and
    the PDF scripts that the blueprint markdown is; git tracks all of them."""
    import subprocess
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "capability_manifest.json", "blueprints/*.md"],
                            capture_output=True, text=True, timeout=30)
    if listed.returncode != 0:
        import pytest
        pytest.skip("not a git checkout")
    tracked = listed.stdout.split()
    assert "capability_manifest.json" in tracked and any(t.endswith(".md") for t in tracked)
    for script in ("build_packages.sh", "scripts/package_desktop_app.sh",
                   "scripts/generate_blueprint_pdfs.sh", "scripts/generate_new_user_guide_pdf.sh"):
        for line in (ROOT / script).read_text(encoding="utf-8").splitlines():
            if "gitignored" in line.lower():
                assert not any(w in line.lower() for w in ("manifest", "markdown")), f"{script}: {line.strip()}"


def test_packaging_comments_say_what_the_code_does():
    import re
    # the version guard names the files that hold the version, and the test only as the check
    guard = RELEASE_YML.split("does not match pyproject.toml version", 1)[1].split("\n", 1)[0]
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    for path in ("pyproject.toml", "eli/kernel/self_upgrade.py"):
        assert path in guard and version in (ROOT / path).read_text(encoding="utf-8"), path
    assert "test_pyproject_packaging.py checks" in guard
    # no job adds the XTTS extra, so no note may say one does
    note = RELEASE_YML.split("REQUIRED_EXTRAS:", 1)[1].split("OPTIONAL_EXTRAS:", 1)[0]
    assert "job-level override" not in note and not re.search(r"EXTRAS:[^\n]*natural", RELEASE_YML)
    # the spec bundles the voices; its notes must not say it never does
    spec = (ROOT / "ELI.spec").read_text(encoding="utf-8")
    notes = spec.split('"""', 2)[1]
    assert '"tts_piper/piper"' in spec and not re.search(r"Piper voices[^*]*never bundled", notes)
    # the installed app keeps its data in the per-user ELI_v2 folder, which is where the header says
    iss = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    header = iss.split("#ifndef MyAppVersion", 1)[0]
    assert "{localappdata}\\ELI_v2" in header and "beside the app -" not in header
    # the .deb's size is printed by the build, not claimed
    deb = (ROOT / "packaging" / "debian" / "build-deb.sh").read_text(encoding="utf-8")
    assert not re.search(r"~\s*\d+\s*MB", deb) and 'du -h "$DEB"' in deb
