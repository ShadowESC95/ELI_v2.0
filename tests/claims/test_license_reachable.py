"""CLAIM: every download can put the PolyForm licence in front of its user.

ELI is source-available under PolyForm Internal Use 1.0.0, so the terms have to
be reachable from each shape it ships in — not just the Windows installer, which
is the only wrapper with a licence pane of its own. These pin the surfaces:

  * `LICENSE` / `NOTICE` / `THIRD_PARTY_NOTICES.md` exist and name the licence
  * the frozen bundles carry them (ELI.spec data manifest)
  * the dmg and AppImage stage them into the artifact
  * the Windows installer shows one at install time
  * `--license` resolves the text at runtime, on every platform
"""
from __future__ import annotations

import pytest

from . import _helpers as H

REPO = H.REPO

DOCS = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")


@pytest.mark.parametrize("name", DOCS)
def test_license_doc_present(name):
    path = REPO / name
    assert path.is_file(), f"{name} missing from the repo root"
    assert path.stat().st_size > 200, f"{name} is suspiciously short"


def test_license_names_polyform():
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "PolyForm Internal Use License 1.0.0" in text
    assert "you may not distribute the software" in text.lower().replace("\n", " ")


@pytest.mark.parametrize("name", DOCS + ("models/MODEL_LICENSES.md",))
def test_frozen_bundle_ships_license(name):
    """ELI.spec's data manifest must carry the terms into exe/zip/dmg/AppImage."""
    spec = (REPO / "ELI.spec").read_text(encoding="utf-8")
    assert f'"{name}"' in spec, f"{name} not in the ELI.spec data manifest"


@pytest.mark.parametrize("script,label", [
    ("packaging/macos/build-dmg.sh", "dmg"),
    ("packaging/linux/build-appimage-pyinstaller.sh", "AppImage"),
])
def test_artifact_stages_license(script, label):
    """The dmg/AppImage have no installer step, so they stage the docs directly."""
    text = (REPO / script).read_text(encoding="utf-8")
    assert "LICENSE" in text, f"the {label} build does not stage LICENSE"
    assert "THIRD_PARTY_NOTICES.md" in text, \
        f"the {label} build does not stage THIRD_PARTY_NOTICES.md"


def test_windows_installer_shows_license():
    iss = (REPO / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert "LicenseFile=" in iss, "Inno installer has no licence pane"
    assert "AppCopyright=" in iss, "Inno installer declares no copyright"


def test_license_flag_wired_into_both_entry_points():
    src = (REPO / "eli" / "__main__.py").read_text(encoding="utf-8")
    frozen = (REPO / "packaging" / "pyinstaller" / "eli_entry.py").read_text(encoding="utf-8")
    for name, text in (("eli/__main__.py", src), ("eli_entry.py", frozen)):
        assert "--license" in text, f"{name} does not handle --license"
        assert "license_info" in text, f"{name} does not call the licence printer"


def test_license_resolves_at_runtime():
    from eli.runtime.license_info import license_path, license_text

    assert license_path() is not None, "LICENSE not resolvable from a source checkout"
    text = license_text()
    assert "PolyForm Internal Use License 1.0.0" in text
    assert "Jason Fitzgibbon Bridgeman" in text
