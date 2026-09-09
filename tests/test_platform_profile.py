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


def test_build_packages_scopes_windows_arm64():
    text = Path("build_packages.sh").read_text(encoding="utf-8")
    assert "windows-arm64-lean" in text
    assert "windows-arm64" in text
    assert "wheelhouse-arm64" in text
    assert "win_arm64" in text
