"""Install profile detection — Android headless, WoA, desktop."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from eli.setup.platform_profile import (
    InstallProfile,
    get_platform_info,
    install_script_for_profile,
)


def test_android_profile_routes_to_install_android_sh(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "eli.setup.platform_profile.is_android_headless",
        lambda: True,
    )
    script = tmp_path / "scripts" / "install_android.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    path, cmd = install_script_for_profile(tmp_path)
    assert path == script
    assert cmd[0] == "bash"
    assert "install_android.sh" in cmd[1]


def test_desktop_profile_routes_to_install_sh(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "eli.setup.platform_profile.is_android_headless",
        lambda: False,
    )
    monkeypatch.setattr(
        "eli.setup.platform_profile.is_windows_on_arm",
        lambda: False,
    )
    monkeypatch.setattr(
        "eli.setup.platform_profile.sys",
        SimpleNamespace(platform="linux"),
    )
    sh = tmp_path / "install.sh"
    sh.write_text("#!/bin/bash\n", encoding="utf-8")
    path, cmd = install_script_for_profile(tmp_path)
    assert path == sh
    assert path.name == "install.sh"
    assert "--auto-model" in cmd


def test_android_platform_info():
    from eli.setup import platform_profile as pp

    orig = pp.is_android_headless
    try:
        pp.is_android_headless = lambda: True
        info = get_platform_info()
        assert info.profile == InstallProfile.ANDROID_HEADLESS
        assert info.supports_gui is False
        assert info.launch_command[-1] == "eli.cli.headless"
    finally:
        pp.is_android_headless = orig


def test_install_android_sh_emits_progress_markers():
    text = Path("scripts/install_android.sh").read_text(encoding="utf-8")
    assert "eli_progress()" in text
    assert "[ELI-PROGRESS]" in text
    assert "eli_progress finish 100" in text


def test_build_packages_runs_builders_that_exist_and_names_what_they_make():
    """The macos target called packaging/macos/build-macos-app.sh, which does not exist, so it only
    printed that there was no macOS builder; and its notes and checksums named the .deb
    eli-v2.0_<v>_amd64.deb, while build-deb.sh writes ELI_v2-<v>-amd64.deb."""
    import re
    text = Path("build_packages.sh").read_text(encoding="utf-8")
    called = re.findall(r'"\$PROJECT_ROOT/(packaging/[^"]+\.(?:sh|ps1))"', text)
    assert "packaging/macos/build-dmg.sh" in called
    assert not [p for p in called if not Path(p).is_file()], called
    deb_writer = Path("packaging/debian/build-deb.sh").read_text(encoding="utf-8")
    deb = re.search(r'DEB="\$OUT_DIR/(ELI_v2-\$\{VERSION\}-amd64\.deb)"', deb_writer).group(1)
    assert f"dist/{deb}" in text and "ELI_v2-*-amd64.deb" in text and "eli-v2.0_" not in text
    dmg_writer = Path("packaging/macos/build-dmg.sh").read_text(encoding="utf-8")
    assert 'DMG="$ROOT/dist/ELI_v2-${VERSION}-macos-${ARCH}.dmg"' in dmg_writer and "ELI_v2-*.dmg" in text


def test_build_packages_scopes_windows_arm64():
    text = Path("build_packages.sh").read_text(encoding="utf-8")
    assert "windows-arm64-lean" in text
    assert "windows-arm64" in text
    assert "wheelhouse-arm64" in text
    assert "win_arm64" in text
