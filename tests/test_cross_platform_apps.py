"""Behaviour lock: ELI resolves apps/terminals on EVERY OS, not just Ubuntu/GNOME.

Every role used to be a single hardcoded name per platform, which silently
assumed one distro and one OS release:

* Linux  — `x-terminal-emulator` is a Debian alternatives symlink and the
  gnome-*/gedit/eog names are GNOME-only; none exist on a stock Arch/KDE box.
* macOS  — "System Settings" is Ventura (13)+; Monterey and older have
  "System Preferences", and `open -a "System Settings"` fails there. Bundles are
  also not on PATH, so shutil.which() is the wrong existence test entirely.
* Windows— `wt.exe` ships with 11 but not with a stock 10.

`shutil.which(...) -> None -> return False` made those failures silent, so the
lock is: each role resolves to something actually installed on the host.
"""

import pytest

from eli.utils import platform_compat as pc


@pytest.fixture
def as_host(monkeypatch):
    """Pretend the host is `name` so app_aliases() probes that platform."""
    def _set(name):
        for attr, value in (("ANDROID", "android"), ("WINDOWS", "windows"),
                            ("MACOS", "macos"), ("LINUX", "linux"), ("BSD", "bsd")):
            monkeypatch.setattr(pc, attr, name == value, raising=False)
    return _set


def _only(*known):
    return lambda name: f"/usr/bin/{name}" if name in known else None


# --------------------------------------------------------------------------
# Linux: not every Linux is Ubuntu with GNOME
# --------------------------------------------------------------------------

def test_linux_terminals_cover_non_debian_desktops():
    names = pc.LINUX_APP_CANDIDATES["terminal"]
    for arch_common in ("alacritty", "kitty", "foot", "konsole", "xterm"):
        assert arch_common in names, f"{arch_common} missing — breaks Arch/minimal WM"
    assert len(names) > 1, "a single terminal name is a Debian assumption"


def test_linux_roles_are_not_gnome_only():
    for role, gnome_only in (("calculator", "gnome-calculator"),
                             ("settings", "gnome-control-center"),
                             ("photos", "eog"),
                             ("music", "rhythmbox")):
        names = pc.LINUX_APP_CANDIDATES[role]
        assert len(names) > 1 and names != (gnome_only,), f"{role} is GNOME-only"


def test_arch_package_names_are_known():
    """Arch names differ from Debian's for the same app."""
    assert "code-oss" in pc.LINUX_APP_CANDIDATES["vscode"]
    assert "chromium" in pc.LINUX_APP_CANDIDATES["chromium"]
    assert "google-chrome-stable" in pc.LINUX_APP_CANDIDATES["chrome"]


def test_linux_resolves_to_an_installed_terminal(as_host, monkeypatch):
    """A KDE/Arch box with only konsole must still resolve a terminal."""
    as_host("linux")
    monkeypatch.setattr(pc.shutil, "which", _only("konsole"))
    assert pc.app_aliases()["terminal"] == "konsole"


def test_linux_terminal_argv_uses_the_installed_terminal(as_host, monkeypatch):
    as_host("linux")
    monkeypatch.setattr(pc.shutil, "which", _only("foot"))
    assert pc.terminal_argv(["bash", "-lc", "echo hi"]) == ["foot", "bash", "-lc", "echo hi"]


def test_linux_terminal_argv_is_none_when_nothing_installed(as_host, monkeypatch):
    as_host("linux")
    monkeypatch.setattr(pc.shutil, "which", lambda n: None)
    assert pc.terminal_argv(["bash"]) is None


# --------------------------------------------------------------------------
# macOS: bundles, not PATH — and names move between releases
# --------------------------------------------------------------------------

def test_macos_settings_falls_back_on_older_releases(as_host, monkeypatch):
    """Monterey and older: `open -a "System Settings"` fails; use Preferences."""
    as_host("macos")
    monkeypatch.setattr(pc, "_macos_app_exists", lambda n: n == "System Preferences")
    assert pc.app_aliases()["settings"] == "System Preferences"


def test_macos_settings_prefers_modern_name_when_present(as_host, monkeypatch):
    as_host("macos")
    monkeypatch.setattr(pc, "_macos_app_exists", lambda n: n == "System Settings")
    assert pc.app_aliases()["settings"] == "System Settings"


def test_macos_music_falls_back_to_itunes(as_host, monkeypatch):
    as_host("macos")
    monkeypatch.setattr(pc, "_macos_app_exists", lambda n: n == "iTunes")
    assert pc.app_aliases()["music"] == "iTunes"


def test_macos_apps_are_not_probed_on_path(monkeypatch):
    """which("Safari") is always None — a PATH probe would call every app missing."""
    monkeypatch.setattr(pc.shutil, "which", lambda n: None)
    monkeypatch.setattr(pc, "_macos_app_exists", lambda n: n == "Safari")
    assert pc.app_exists("Safari", "macos") is True
    assert pc.app_exists("Nonexistent App", "macos") is False


def test_macos_terminal_covers_third_party():
    assert "iTerm" in pc.MACOS_APP_CANDIDATES["terminal"]


# --------------------------------------------------------------------------
# Windows: no Windows Terminal on a stock 10
# --------------------------------------------------------------------------

def test_windows_terminal_falls_back_without_windows_terminal(as_host, monkeypatch):
    as_host("windows")
    monkeypatch.setattr(pc.shutil, "which", _only("powershell.exe"))
    assert pc.app_aliases()["terminal"] == "powershell.exe"


def test_windows_terminal_prefers_wt_when_present(as_host, monkeypatch):
    as_host("windows")
    monkeypatch.setattr(pc.shutil, "which", _only("wt.exe", "powershell.exe"))
    assert pc.app_aliases()["terminal"] == "wt.exe"


def test_windows_uri_handlers_need_no_path_entry():
    """ms-settings: is a protocol handler — which() would call it missing."""
    assert pc.app_exists("ms-settings:", "windows") is True
    assert pc.app_exists("ms-photos:", "windows") is True


def test_windows_exe_resolves_with_or_without_suffix(monkeypatch):
    monkeypatch.setattr(pc.shutil, "which", _only("code"))
    assert pc.app_exists("code.exe", "windows") is True


def test_windows_terminal_argv_falls_back_to_cmd(as_host, monkeypatch):
    as_host("windows")
    monkeypatch.setattr(pc.shutil, "which", _only("cmd.exe"))
    argv = pc.terminal_argv(["echo", "hi"])
    assert argv and argv[0] == "cmd.exe"


# --------------------------------------------------------------------------
# Cross-cutting
# --------------------------------------------------------------------------

@pytest.mark.parametrize("platform", ["linux", "macos", "windows", "android", "bsd"])
def test_every_platform_has_candidates_and_a_canonical_table(platform):
    table = pc.APP_CANDIDATES_BY_PLATFORM[platform]
    assert table, f"{platform} has no app candidates"
    for role, names in table.items():
        assert isinstance(names, tuple) and names, f"{platform}.{role} empty"
        assert pc.APP_ALIASES_BY_PLATFORM[platform][role] == names[0]


def test_app_aliases_keeps_str_contract_for_other_platforms():
    """Back-compat: callers get dict[str, str], resolved or not."""
    for platform in ("linux", "macos", "windows", "android", "bsd"):
        for value in pc.app_aliases(platform).values():
            assert isinstance(value, str)


def test_known_aliases_still_resolve():
    assert pc.app_aliases("android")["terminal"] == "com.termux"
    assert pc.normalize_app_name("vs code", "windows") == "code.cmd"
    assert pc.normalize_platform("arch") == "linux"
    assert pc.normalize_platform("manjaro") == "manjaro"  # unknown → passthrough


def test_first_available_returns_none_when_nothing_exists(monkeypatch):
    monkeypatch.setattr(pc.shutil, "which", lambda n: None)
    assert pc.first_available("nope-a", "nope-b", platform_name="linux") is None
