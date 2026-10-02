"""Security hardening (2026-10-02): every macOS (osascript/AppleScript) branch in
portable_app_control.py interpolated resolve_app()'s output straight into a
double-quoted AppleScript string literal with zero escaping — close_app, minimize_app,
maximize_app, focus_app, and window_exists all did this. resolve_app() falls back to
the caller's RAW query verbatim when nothing installed matches it, and these
app-control functions are reached from LLM-routed voice/text commands (OPEN_APP,
CLOSE_APP, PLAY_MEDIA, etc.) — so the "app name" is not trusted, developer-controlled
text. A crafted name containing a `"` breaks out of the AppleScript string; AppleScript
can run `do shell script`, so an unescaped interpolation site here is command
injection with the user's own shell privileges, not just a syntax-error DoS.

Fixed with one shared `_osa_quote()` helper (backslash then double-quote escaped,
applied at every osascript interpolation site in the file) instead of patching each
call site differently. This is a "for sale to the public, any OS" product — this
class of bug must be closed everywhere it appears, not just in new code.
"""
from __future__ import annotations

from eli.system import portable_app_control as pac


class _CP:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_osa_quote_escapes_double_quotes_and_backslashes():
    # A name designed to break out of `tell application "<name>" to activate`
    # and append a second AppleScript command, e.g. one that shells out.
    hostile = 'Spotify" to activate' + chr(10) + 'tell app "Terminal'
    quoted = pac._osa_quote(hostile)
    assert '"' not in quoted.replace('\\"', "")  # every raw " is now escaped
    assert quoted == hostile.replace("\\", "\\\\").replace('"', '\\"')


def test_osa_quote_handles_embedded_backslash_before_quote():
    # Escaping order matters: backslashes must be doubled BEFORE quotes are escaped,
    # or a name ending in `\"` could still close the string early.
    hostile = 'evil\\" ; do shell script "rm -rf ~"'
    quoted = pac._osa_quote(hostile)
    # Reconstructing what AppleScript actually sees: every literal backslash and
    # quote in the source is individually escaped, so none of them can terminate
    # the surrounding string early.
    assert quoted.count('\\"') == hostile.count('"')
    assert "rm -rf" in quoted  # content preserved, just neutralised as a string


def test_focus_app_darwin_uses_osa_quote(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "darwin")
    monkeypatch.setattr(pac.shutil, "which", lambda c: "/usr/bin/osascript" if c == "osascript" else None)
    calls = []

    def fake_run(args, timeout=8.0):
        calls.append(list(args))
        return _CP(0, "")

    monkeypatch.setattr(pac, "_run", fake_run)
    pac.focus_app('Spotify" to activate end tell' + chr(10) + 'tell app "Finder')
    assert calls, "osascript should have been invoked"
    script = calls[0][2]
    # The injected `"` from the hostile name must be escaped, not raw, inside the script.
    assert 'to activate end tell\ntell app "Finder" to activate' not in script


def test_window_exists_darwin_uses_osa_quote(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "darwin")
    monkeypatch.setattr(pac.shutil, "which", lambda c: "/usr/bin/osascript" if c == "osascript" else None)
    calls = []

    def fake_run(args, timeout=8.0):
        calls.append(list(args))
        return _CP(0, "false")

    monkeypatch.setattr(pac, "_run", fake_run)
    pac.window_exists('x" to activate' + chr(10) + 'tell application "System Events" to keystroke "pwned')
    assert calls
    script = calls[0][2]
    assert script.count('"') % 2 == 0  # quotes balance — no literal break-out
