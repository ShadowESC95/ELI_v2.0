"""Speech-damage layer for app names, on top of the cross-platform resolver.

Two problems were tangled together here.

**Duplication.** Three alias tables existed: ``APP_ALIASES`` in router_enhanced
(30 entries), a second ``app_aliases`` inline in the same file (10), and
``_APP_ALIASES`` in executor_enhanced (11). The router's and the executor's had
**no overlap at all**, so an alias resolved or not depending on which layer saw
the word first — "open thunderbird" worked in one, "open vs code" in the other.
They also disagreed: "chrome" mapped to ``chromium`` in the inline table, so on a
machine with both installed, "open chrome" launched the wrong browser.

**Platform.** All three tables were GNOME-only — ``nautilus``, ``gedit``,
``eog``, ``baobab``. On KDE, XFCE, macOS or Windows every one of those names is
wrong, and ELI ships to all of them.

The fix for the second is NOT another table: ``eli.utils.platform_compat``
already resolves an app *role* to whatever is installed on the host, across
Linux desktops (GNOME/KDE/XFCE/Cinnamon/MATE), macOS (bundle names, including
the System Settings/System Preferences split), Windows (executables and
``ms-settings:``-style URI handlers) and Android. So this module maps spoken
forms to ROLES and hands off; it does not know or care what a file manager is
called on the host.

What is genuinely local to this module is the speech-recognition damage —
"tundra bird", "calander", "virtual studio code". Those are artefacts of ELI's
STT, they are the same on every OS, and they belong nowhere near a platform
table.
"""
from __future__ import annotations

from typing import Dict

# Spoken/misheard form → the role or canonical name platform_compat understands.
# Keys must be lowercase and whitespace-normalised; normalize_app() normalises
# its input before lookup.
APP_ALIASES: Dict[str, str] = {
    # ── speech-recognition damage (the reason this layer exists) ──
    "thunderbirds": "mail",
    "thunder birds": "mail",
    "tundra bird": "mail",
    "tundrabird": "mail",
    "thunderbird": "mail",
    "calender": "calendar",
    "calander": "calendar",
    "calandar": "calendar",
    "virtual studio code": "vscode",   # STT hears "virtual" for "visual"
    "codes": "vscode",

    # ── spoken forms platform_compat's common table does not carry ──
    "vs code": "vscode",
    "visual studio code": "vscode",
    "code-oss": "vscode",
    "text editor": "editor",
    "image viewer": "photos",
    "music player": "music",
    "system monitor": "system monitor",
    "disk usage": "disk usage",
    "terminal app": "terminal",
    "mozilla": "firefox",
    "chrome browser": "chrome",
    "chromium browser": "chromium",
    "firefox browser": "firefox",
}


def normalize_app(spoken: str, *, platform_name: str | None = None) -> str:
    """Resolve a spoken/misheard app name to a launcher name for the host OS.

    Applies the speech-damage aliases above, then defers to platform_compat so
    the result is right for the actual desktop: a "calculator" is
    ``gnome-calculator`` on GNOME, ``kcalc`` on KDE, ``Calculator`` on macOS and
    ``calc.exe`` on Windows — resolved against what is installed, not guessed.

    Pass ``platform_name`` to resolve for another OS (returns that platform's
    canonical names unprobed, since probing only makes sense on the host).
    Unknown names pass through unchanged: this is a convenience for what people
    say, not an allow-list of what may be launched.
    """
    s = " ".join((spoken or "").strip().lower().split())
    if not s:
        return ""
    role = APP_ALIASES.get(s, s)
    try:
        from eli.utils.platform_compat import normalize_app_name
        return normalize_app_name(role, platform_name)
    except Exception:
        # platform_compat is the resolver, not a hard dependency of routing —
        # returning the role unresolved is better than failing the command.
        return role
