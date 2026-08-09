"""Locks on app-name resolution: one table, and correct on every OS.

Two defects, found together.

**Duplication.** Three alias tables existed — ``APP_ALIASES`` in router_enhanced
(30 entries), an inline ``app_aliases`` in the same file (10), and
``_APP_ALIASES`` in executor_enhanced (11). The router's and the executor's had
NO overlap, so an alias resolved or not depending on which layer saw the word
first: "open thunderbird" worked in one, "open vs code" in the other. They also
disagreed — "chrome" mapped to ``chromium`` in the inline table, so on a machine
with both installed "open chrome" launched the wrong browser.

**Platform.** All three were GNOME-only (``nautilus``, ``gedit``, ``eog``,
``baobab``). Every one of those names is wrong on KDE, XFCE, macOS and Windows,
and ELI ships to all of them.

The second is fixed by deferring to ``platform_compat``, which already resolves
an app *role* against what is installed on the host. This module keeps only the
speech-recognition damage ("tundra bird", "calander"), which is OS-independent
and belongs nowhere near a platform table.
"""
from pathlib import Path

import pytest

from eli.execution.app_aliases import APP_ALIASES, normalize_app

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── one table ───────────────────────────────────────────────────────────────
def test_router_and_executor_share_the_one_table():
    """Identity, not equality — a copy would drift again."""
    from eli.execution.router_enhanced import APP_ALIASES as router_tbl
    from eli.execution.executor_enhanced import _APP_ALIASES as exec_tbl

    assert router_tbl is APP_ALIASES
    assert exec_tbl is APP_ALIASES


def test_no_second_literal_table_remains():
    for rel in ("eli/execution/router_enhanced.py", "eli/execution/executor_enhanced.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for marker in ("APP_ALIASES = {", "app_aliases = {", "_APP_ALIASES = {"):
            assert marker not in src, f"{rel} reintroduced a literal alias table ({marker})"


def test_no_gnome_executables_hardcoded_in_the_alias_layer():
    """The whole point of the platform handoff. A `nautilus` here is a bug on
    every non-GNOME desktop."""
    gnome_only = ("nautilus", "gedit", "eog", "baobab", "gnome-calculator",
                  "gnome-control-center", "rhythmbox", "x-terminal-emulator")
    for spoken, target in APP_ALIASES.items():
        assert target not in gnome_only, f"{spoken!r} hardcodes the GNOME name {target!r}"


# ── speech-recognition damage still absorbed ────────────────────────────────
@pytest.mark.parametrize("spoken", [
    "tundra bird", "thunder birds", "tundrabird", "thunderbirds",
])
def test_mishearings_of_thunderbird_reach_mail(spoken):
    assert normalize_app(spoken, platform_name="linux") in {
        "thunderbird", "evolution", "kmail", "geary", "mail"}


@pytest.mark.parametrize("spoken", ["calander", "calender", "calandar"])
def test_mishearings_of_calendar_reach_calendar(spoken):
    assert "calendar" in normalize_app(spoken, platform_name="linux").lower()


def test_virtual_studio_code_is_vscode():
    """STT reliably hears "virtual" for "visual"."""
    assert normalize_app("virtual studio code", platform_name="linux") in {
        "code", "code-oss", "codium"}


# ── correct on every OS, which is the point ─────────────────────────────────
@pytest.mark.parametrize("spoken,plat,expected", [
    ("files", "macos", "Finder"),
    ("files", "windows", "explorer.exe"),
    ("calculator", "macos", "Calculator"),
    ("calculator", "windows", "calc.exe"),
    ("settings", "macos", "System Settings"),
    ("settings", "windows", "ms-settings:"),
    ("text editor", "macos", "TextEdit"),
    ("text editor", "windows", "notepad.exe"),
    ("terminal", "macos", "Terminal"),
    ("terminal", "windows", "wt.exe"),
    ("tundra bird", "macos", "Mail"),
    ("tundra bird", "windows", "outlook.exe"),
])
def test_resolves_per_platform(spoken, plat, expected):
    assert normalize_app(spoken, platform_name=plat) == expected


@pytest.mark.parametrize("spoken", [
    "system monitor", "screenshot", "disks", "disk usage",
])
@pytest.mark.parametrize("plat", ["linux", "macos", "windows"])
def test_roles_added_for_the_gnome_only_entries(spoken, plat):
    """These four had no cross-OS role, so folding the GNOME table in would have
    dropped them on macOS and Windows."""
    got = normalize_app(spoken, platform_name=plat)
    assert got and got != spoken, f"{spoken!r} unresolved on {plat}"


# ── chrome/chromium, the outright disagreement ──────────────────────────────
def test_chrome_is_not_chromium_on_macos_or_windows():
    assert normalize_app("chrome", platform_name="macos") == "Google Chrome"
    assert normalize_app("chrome", platform_name="windows") == "chrome.exe"


def test_chrome_resolves_against_what_is_installed_on_the_host():
    """A fixed mapping cannot be right for everyone: `chrome` fails where only
    Chromium exists, `chromium` is wrong where real Chrome does."""
    import shutil
    resolved = normalize_app("chrome")
    if shutil.which("google-chrome") or shutil.which("google-chrome-stable"):
        assert "chrome" in resolved and "chromium" not in resolved
    else:
        assert resolved


# ── general contract ────────────────────────────────────────────────────────
def test_unknown_names_pass_through():
    assert normalize_app("some-private-tool", platform_name="linux") == "some-private-tool"


def test_empty_input_is_safe():
    assert normalize_app("") == ""
    assert normalize_app(None) == ""


def test_lookup_is_case_and_whitespace_insensitive():
    assert normalize_app("  TUNDRA   Bird ", platform_name="macos") == "Mail"


def test_keys_are_normalised():
    for k in APP_ALIASES:
        assert k == " ".join(k.lower().split()), f"unreachable alias key: {k!r}"
