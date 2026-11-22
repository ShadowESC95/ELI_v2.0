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
    assert "Apache License, Version 2.0" in notice and "ShadowESC95" in notice


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



def test_an_option_this_program_does_not_take_starts_nothing(tmp_path):
    """`eli --bundle legal` (another ELI's option) opened ELI v2's own window as if nothing had been
    asked. An unknown --option is refused before anything starts; the known ones still work."""
    import os
    import subprocess
    import sys
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", ELI_DATA_DIR=str(tmp_path))
    run = lambda *args: subprocess.run([sys.executable, "-m", "eli", *args], cwd=REPO, env=env,
                                       capture_output=True, text=True, timeout=120)
    refused = run("--bundle", "legal")
    assert refused.returncode == 2 and "does not take --bundle" in refused.stderr
    assert run("--help").returncode == 0 and "--headless" in run("--help").stdout
    assert run("--license").returncode == 0

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


def test_a_package_bundles_no_non_commercial_model_unless_asked(tmp_path, monkeypatch):
    """scripts/package_desktop_app.sh bundled Qwen2.5-3B, under the non-commercial Qwen Research
    License, whenever models/ had it, and the package goes to every user."""
    from eli.core import model_download as md
    monkeypatch.setattr(md, "_load_override_catalog", lambda: [])
    manifest = (REPO / "models" / "MODEL_LICENSES.md").read_text(encoding="utf-8")
    for entry in md.CATALOG:                       # the catalog says what the manifest says
        row = next(line for line in manifest.splitlines() if line.startswith(f"| `{entry['key']}` |"))
        assert entry["license"].split(" (")[0] in row, (entry["key"], row)

    for entry in md.CATALOG:
        (tmp_path / entry["filename"]).write_bytes(b"")
    picked = md.starter_model(tmp_path)
    open_sizes = [e["size_gb"] for e in md.CATALOG if e["license"] in md.OPEN_LICENSES]
    assert picked["license"] in md.OPEN_LICENSES and picked["size_gb"] == min(open_sizes)
    closed = tmp_path / "closed"
    closed.mkdir()
    for entry in md.CATALOG:
        if entry["license"] not in md.OPEN_LICENSES:
            (closed / entry["filename"]).write_bytes(b"")
    assert md.starter_model(closed) is None

    script = (REPO / "scripts" / "package_desktop_app.sh").read_text(encoding="utf-8")
    assert "eli.core.model_download --starter" in script
    assert not [e["filename"] for e in md.CATALOG if e["filename"] in script], "a model is named in the script"


def _gpl_sources():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gpl_sources", REPO / "packaging" / "gpl_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_release_attaches_the_source_of_the_gpl_packages_it_carries():
    """piper-tts and espeak-ng (GPL-3.0) are bundled, and no release said where their exact source was:
    GPL-3.0 lets a binary be passed on only with its source, or directions to it, beside it."""
    import importlib.util
    gs = _gpl_sources()
    assert gs.is_gpl(["GPL-3.0-or-later"]) and gs.is_gpl(["GPLv2"])
    assert gs.is_gpl(["Copyright (c) 2014, a maintainer",
                      "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)"])
    assert not gs.is_gpl(["LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"])       # used under the LGPL
    assert not gs.is_gpl(["License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)"])
    assert not gs.is_gpl(["Apache-2.0"]) and not gs.is_gpl(["MIT"]) and not gs.is_gpl(["EUPL-1.2"])
    cmake = (
        "include(ExternalProject)\n"
        "ExternalProject_Add(\n    speech_external\n"
        '    GIT_REPOSITORY "https://github.com/example-org/example-speech.git"\n'
        '    GIT_TAG "0123456789abcdef0123456789abcdef01234567"\n'
        "    CMAKE_ARGS -DCMAKE_INSTALL_PREFIX:PATH=${OUT}\n)\n"
        "FetchContent_Declare(data URL https://example.org/data-1.0.tar.gz)\n"
    )
    assert gs.cmake_fetches(cmake) == [
        ("git", "https://github.com/example-org/example-speech.git", "0123456789abcdef0123456789abcdef01234567"),
        ("url", "https://example.org/data-1.0.tar.gz", "")]
    assert gs.github_archive("https://github.com/example-org/example-speech.git", "v1.0") == \
        "https://github.com/example-org/example-speech/archive/v1.0.tar.gz"
    if importlib.util.find_spec("piper") is not None:
        assert "piper-tts" in {d["name"] for d in gs.gpl_distributions()}

    release = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    linux = release.split("\n  build-linux:", 1)[1].split("\n  build-source-artifacts:", 1)[0]
    assert "python packaging/gpl_sources.py dist/gpl-sources" in linux and "-gpl-sources.tar.gz" in linux
    assert "espeak-ng's source (compiled into piper-tts) is not in the GPL source archive" in linux
    notes = release.split("Write release notes stub", 1)[1].split("Verify:", 1)[0]
    assert "gpl-sources.tar.gz" in notes, "the release notes do not say where the GPL source is"
    assert "body_path: dist/RELEASE_NOTES.md" in release.split("\n  release:", 1)[1]
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "gpl-sources.tar.gz" in notices and "packaging/gpl_sources.py" in notices


def test_the_gpl_source_archive_holds_each_sdist_and_what_its_build_fetches(tmp_path, monkeypatch, capsys):
    """The fetch, with the network replaced: a GPL package's sdist from PyPI, checked against PyPI's
    digest, and the source its CMake build fetches, at the commit the build names."""
    import hashlib
    import io
    import json
    import tarfile
    gs = _gpl_sources()
    cmake = (b'ExternalProject_Add(engine\n    GIT_REPOSITORY "https://github.com/example-org/example-engine.git"\n'
             b'    GIT_TAG "89abcdef0123456789abcdef0123456789abcdef"\n)\n')
    sdist = io.BytesIO()
    with tarfile.open(fileobj=sdist, mode="w:gz") as tar:
        info = tarfile.TarInfo("example_speech-1.0/CMakeLists.txt")
        info.size = len(cmake)
        tar.addfile(info, io.BytesIO(cmake))
    sdist = sdist.getvalue()
    engine = b"engine source"
    digest = {"value": hashlib.sha256(sdist).hexdigest()}
    served = {
        "https://files.example.org/example_speech-1.0.tar.gz": sdist,
        "https://github.com/example-org/example-engine/archive/89abcdef0123456789abcdef0123456789abcdef.tar.gz": engine,
    }

    def fake_get(url):
        if url == gs.PYPI_JSON.format(name="example-speech", version="1.0"):
            return json.dumps({"urls": [
                {"packagetype": "bdist_wheel", "url": "https://files.example.org/x.whl", "filename": "x.whl",
                 "digests": {"sha256": "0"}},
                {"packagetype": "sdist", "url": "https://files.example.org/example_speech-1.0.tar.gz",
                 "filename": "example_speech-1.0.tar.gz", "digests": {"sha256": digest["value"]}}]}).encode()
        return served[url]

    monkeypatch.setattr(gs, "_get", fake_get)
    monkeypatch.setattr(gs, "gpl_distributions", lambda: [{"name": "example-speech", "version": "1.0",
                                                           "licence": "GPL-3.0-or-later", "home": ""}])
    monkeypatch.setattr(gs, "lgpl_distributions", lambda: [])     # the next test covers those
    out = tmp_path / "gpl-sources"
    assert gs.fetch_all(out) == 0
    assert (out / "example_speech-1.0.tar.gz").read_bytes() == sdist
    fetched = [p for p in out.iterdir() if "example-engine" in p.name]
    assert len(fetched) == 1 and fetched[0].read_bytes() == engine
    listing = (out / "SOURCES.md").read_text(encoding="utf-8")
    assert "example-speech 1.0 (GPL-3.0-or-later)" in listing and "fetched by its CMake build" in listing

    digest["value"] = "f" * 64                      # PyPI's digest no longer matches the file
    assert gs.fetch_all(tmp_path / "again") == 1
    assert "does not match" in capsys.readouterr().err


def test_a_compiled_package_whose_sdist_lacks_its_build_files_gets_the_tagged_repository(tmp_path, monkeypatch):
    """piper-tts 1.4.2's sdist on PyPI holds neither its CMakeLists.txt nor the C source of its espeak
    bridge, so the archive came out without espeak-ng and the v2.5.37 release stopped. A package that
    carries compiled code its sdist cannot build gets the repository at the version's tag as well, and
    what that tree's CMake build fetches."""
    import hashlib
    import io
    import json
    import tarfile
    gs = _gpl_sources()

    def archive(files):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, body in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        return buf.getvalue()

    sdist = archive({"example_voice-2.0/setup.py": b"from skbuild import setup\n",
                     "example_voice-2.0/src/example_voice/__init__.py": b""})
    repo = archive({"example-voice-2.0/CMakeLists.txt":
                    b'ExternalProject_Add(phonemes\n    GIT_REPOSITORY https://github.com/example-org/phonemes.git\n'
                    b'    GIT_TAG 0123456789abcdef0123456789abcdef01234567  # pinned\n)\n',
                    "example-voice-2.0/src/example_voice/bridge.c": b"int main(void) { return 0; }\n"})
    served = {
        "https://files.example.org/example_voice-2.0.tar.gz": sdist,
        "https://github.com/example-org/example-voice/archive/v2.0.tar.gz": repo,
        "https://github.com/example-org/phonemes/archive/0123456789abcdef0123456789abcdef01234567.tar.gz": b"phonemes",
    }

    def fake_get(url):
        if url == gs.PYPI_JSON.format(name="example-voice", version="2.0"):
            return json.dumps({"urls": [{"packagetype": "sdist", "url": "https://files.example.org/example_voice-2.0.tar.gz",
                                         "filename": "example_voice-2.0.tar.gz",
                                         "digests": {"sha256": hashlib.sha256(sdist).hexdigest()}}]}).encode()
        if url not in served:
            raise OSError(f"404 {url}")
        return served[url]

    monkeypatch.setattr(gs, "_get", fake_get)
    package = {"name": "example-voice", "version": "2.0", "licence": "GPL-3.0-or-later",
               "home": "http://github.com/example-org/example-voice", "compiled": "yes"}
    monkeypatch.setattr(gs, "gpl_distributions", lambda: [package])
    monkeypatch.setattr(gs, "lgpl_distributions", lambda: [])     # the LGPL listing has its own test
    out = tmp_path / "gpl-sources"
    assert gs.fetch_all(out) == 0
    names = sorted(p.name for p in out.iterdir())
    assert "example_voice-2.0.tar.gz" in names and "example-voice-2.0-repository.tar.gz" in names
    assert any("phonemes" in n for n in names), names
    assert "leaves out" in (out / "SOURCES.md").read_text(encoding="utf-8")

    # pure Python under the GPL: the sdist is the whole source, and nothing else is fetched
    package["compiled"] = ""
    again = tmp_path / "pure"
    assert gs.fetch_all(again) == 0
    assert sorted(p.name for p in again.iterdir()) == [gs.LGPL_LISTING, "SOURCES.md", "example_voice-2.0.tar.gz"]


def test_the_release_says_where_the_source_of_each_lgpl_package_it_carries_is(tmp_path, monkeypatch, capsys):
    """Qt for Python and the Qt inside it, zeroconf, chardet and python-xlib (LGPL) had only an upstream
    project link. GPL-3.0 section 6(d), which LGPL-3.0 section 4 applies, lets their source stay on
    another server when directions beside the binaries say exactly where: LGPL_SOURCES.md, beside
    SOURCES.md in the release's GPL source archive, names each package, its version and the address of
    that version's source, read from the installed packages when the release is built."""
    import importlib.util
    import re
    gs = _gpl_sources()
    assert gs.is_lgpl(["LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"]) and gs.is_lgpl(["LGPLv2+"])
    assert not gs.is_lgpl(["GPL-3.0-or-later"]) and not gs.is_lgpl(["MIT"])
    for name in ("PySide6/Qt/lib/libQt6Core.so.6", "PySide6/Qt6Gui.dll", "PySide6/Qt/lib/QtCore.framework/QtCore"):
        assert gs._QT_LIBRARY.search(name), name
    for name in ("PySide6/QtCore.abi3.so", "PySide6/QtCore.pyi", "PySide6/QtCore.pyd", "shiboken6/libshiboken6.abi3.so.6.0"):
        assert not gs._QT_LIBRARY.search(name) and not gs._QT_CORE.search(name), name
    assert gs._QT_CORE.search("PySide6/Qt/lib/libQt6Core.so.6") and not gs._QT_CORE.search("PySide6/Qt/lib/libQt6Gui.so.6")

    # the network and the Qt binding replaced: invented packages, one of each kind
    qt_core = "ExampleQt/Qt/lib/libQt6Core.so.6"
    packages = [
        {"name": "example-mdns", "version": "1.2.0", "licence": "LGPL-2.1-or-later", "home": "", "repos": [],
         "qt_libraries": [], "qt_core": ""},
        {"name": "ExampleQt_Essentials", "version": "6.0.1", "licence": "LGPL-3.0-only OR GPL-3.0-only", "home": "",
         "repos": ["https://code.qt.io/cgit/pyside/pyside-setup.git/"], "qt_libraries": [qt_core], "qt_core": qt_core},
        {"name": "example-x11", "version": "0.9", "licence": "LGPLv2+", "home": "https://github.com/example-org/example-x11",
         "repos": ["https://github.com/example-org/example-x11"], "qt_libraries": [], "qt_core": ""},
    ]
    sdist = {"url": "https://files.example.org/example_mdns-1.2.0.tar.gz", "filename": "example_mdns-1.2.0.tar.gz",
             "sha256": "ab" * 32}
    pyside = gs.SOURCE_ARCHIVES["code.qt.io/cgit/pyside/pyside-setup.git"][0].format(version="6.0.1")
    qt = gs.QT_SOURCE[0].format(minor="6.0", version="6.0.2")
    x11 = "https://github.com/example-org/example-x11/archive/v0.9.tar.gz"
    answering = {pyside, qt, x11}
    monkeypatch.setattr(gs, "pypi_sdist", lambda name, version: sdist if (name, version) == ("example-mdns", "1.2.0") else None)
    monkeypatch.setattr(gs, "_answers", lambda url: url in answering)
    monkeypatch.setattr(gs, "qt_version", lambda package: {"ExampleQt": "6.0.2"}[package])
    monkeypatch.setattr(gs, "gpl_distributions", lambda: [])
    monkeypatch.setattr(gs, "lgpl_distributions", lambda: packages)
    out = tmp_path / "gpl-sources"
    assert gs.fetch_all(out) == 0, capsys.readouterr().err
    listing = (out / gs.LGPL_LISTING).read_text(encoding="utf-8").splitlines()
    assert f"- example-mdns 1.2.0 (LGPL-2.1-or-later): {sdist['url']} (sha256 {'ab' * 32})" in listing
    assert f"- ExampleQt_Essentials 6.0.1 (LGPL-3.0-only OR GPL-3.0-only): {pyside}" in listing
    assert f"- example-x11 0.9 (LGPLv2+): {x11}" in listing
    assert f"- Qt 6.0.2, the libraries inside ExampleQt_Essentials (under their licence): {qt}" in listing
    assert (out / "SOURCES.md").is_file() and pyside.endswith("pyside-setup-everywhere-src-6.0.1.tar.xz")

    answering.discard(qt)                           # Qt's source answers nowhere: the release stops
    assert gs.fetch_all(tmp_path / "again") == 1
    assert "LGPL source not found: Qt, the libraries inside ExampleQt_Essentials" in capsys.readouterr().err

    if importlib.util.find_spec("PySide6") is not None:   # the wheels as installed: which Qt they carry
        carriers = [p for p in gs.lgpl_distributions() if p["qt_core"]]
        assert carriers and re.fullmatch(r"\d+\.\d+\.\d+", gs.qt_version(carriers[0]["qt_core"].split("/", 1)[0]))

    release = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    linux = release.split("\n  build-linux:", 1)[1].split("\n  build-source-artifacts:", 1)[0]
    assert "cat dist/gpl-sources/LGPL_SOURCES.md" in linux
    notes = release.split("Write release notes stub", 1)[1].split("Verify:", 1)[0]
    assert "LGPL_SOURCES.md" in notes and "gpl-sources.tar.gz" in notes
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    lgpl = notices[notices.index("## Source code of the LGPL components"):]
    assert "LGPL_SOURCES.md" in lgpl and "gpl-sources.tar.gz" in lgpl and "packaging/gpl_sources.py" in lgpl
