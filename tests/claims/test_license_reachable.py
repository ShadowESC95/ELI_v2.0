"""CLAIM: every download can put the licence in front of its user.

ELI is open source under the Apache License 2.0, and the terms (with the NOTICE
that names the copyright holder) have to be reachable from each shape it ships
in — not just the Windows installer, which is the only wrapper with a licence
pane of its own. These pin the surfaces:

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


def test_license_is_apache_2_0():
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text and "Version 2.0, January 2004" in text
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text
    notice = (REPO / "NOTICE").read_text(encoding="utf-8")
    assert "Apache License, Version 2.0" in notice and "Jason Fitzgibbon Bridgeman" in notice


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
    assert "Apache License" in text


def test_who_made_eli_is_read_from_the_licence_it_ships_with():
    """Asked who made it, the model invented a company; the NOTICE beside the licence names the maker."""
    from eli.runtime.license_info import made_by
    maker = made_by()
    assert maker and maker in (REPO / "NOTICE").read_text(encoding="utf-8") and "rights" not in maker.lower()


def test_every_command_that_starts_eli_reads_its_flags():
    """The `eli` scripts pointed at the window and ignored --license and --mcp-server; the frozen app
    opened its window for --mcp-server, the command `eli --mcp-config` gives other apps."""
    import re as _re
    scripts = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    block = scripts[scripts.index("[project.scripts]"):scripts.index("[project.gui-scripts]")]
    for name in ("eli", '"eli-v2.0"', "eli-cli"):
        assert _re.search(rf'^{_re.escape(name)} = "eli\.__main__:main"', block, _re.M), name
    frozen = (REPO / "packaging" / "pyinstaller" / "eli_entry.py").read_text(encoding="utf-8")
    assert '"--mcp-server" in argv' in frozen and 'mode == "mcp"' in frozen


def test_the_frozen_builds_carry_only_the_wake_word_files_eli_loads():
    """ELI.spec collected all of openwakeword's data, so its pre-trained wake-word models (CC BY-NC-SA
    4.0, non-commercial) went into every bundle, though ELI runs only the feature extractor."""
    import inspect
    import re
    from pathlib import Path
    from eli.perception import wakeword

    spec = (REPO / "ELI.spec").read_text(encoding="utf-8")
    named = [line for line in spec.splitlines() if '"openwakeword"' in line and not line.lstrip().startswith("#")]
    assert named and all("_wake_feature_files(" in line for line in named), named

    oww = pytest.importorskip("openwakeword")
    from openwakeword.utils import AudioFeatures
    loaded = set(re.findall(r'"(\w+)\.(?:onnx|tflite)"', inspect.getsource(AudioFeatures.__init__)))
    assert loaded and set(wakeword.FEATURE_MODELS) == loaded, "FEATURE_MODELS is not what ELI's extractor loads"
    hooks = pytest.importorskip("PyInstaller.utils.hooks")
    kept = {Path(src).stem for src, _dest in wakeword.feature_model_files(hooks.collect_data_files("openwakeword"))}
    pretrained = {Path(p).stem for p in oww.get_pretrained_model_paths()}
    assert kept == loaded and pretrained and not kept & pretrained
