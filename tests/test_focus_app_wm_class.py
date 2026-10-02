"""Regression: focus_app()/active_window_matches() on Linux matched windows by
TITLE only (wmctrl -a / xdotool search --name, getwindowname). Spotify (and
other media players) rewrite their window title to the loaded track ("Artist
- Song") the instant anything plays, so title-matching silently stops finding
the app the moment it's no longer freshly launched — which is exactly the
state Spotify is normally in. WM_CLASS stays constant ("Spotify") for the
life of the process and must be tried first.

User report: "play evil by eminem on spotify" refused to type (focus never
confirmed) and the fallback search-only path never played the right track —
root cause traced to this title-matching gap in a live session log.
"""
from __future__ import annotations

import subprocess

import pytest

from eli.system import portable_app_control as pac


class _CP:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_active_window_matches_checks_wm_class_before_title(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac.shutil, "which", lambda c: f"/usr/bin/{c}" if c == "xdotool" else None)

    calls = []

    def fake_run(args, timeout=8.0):
        calls.append(list(args))
        if args[-1] == "getwindowclassname":
            return _CP(0, "Spotify")
        if args[-1] == "getwindowname":
            return _CP(0, "Billy Talent - Rusted From the Rain")
        return _CP(1, "")

    monkeypatch.setattr(pac, "_run", fake_run)

    assert pac.active_window_matches("spotify") is True
    assert calls[0][-1] == "getwindowclassname"


def test_active_window_matches_falls_back_to_title_when_class_unavailable(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac.shutil, "which", lambda c: f"/usr/bin/{c}" if c == "xdotool" else None)

    def fake_run(args, timeout=8.0):
        if args[-1] == "getwindowclassname":
            return _CP(0, "firefox")
        if args[-1] == "getwindowname":
            return _CP(0, "Spotify Free")
        return _CP(1, "")

    monkeypatch.setattr(pac, "_run", fake_run)

    assert pac.active_window_matches("spotify") is True


def test_active_window_matches_false_when_neither_matches(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac.shutil, "which", lambda c: f"/usr/bin/{c}" if c == "xdotool" else None)
    monkeypatch.setattr(pac, "_run", lambda args, timeout=8.0: _CP(0, "Firefox"))

    assert pac.active_window_matches("spotify") is False


def test_focus_app_tries_wmctrl_class_match_before_title_match(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac, "resolve_app", lambda q: pac.AppCandidate(name="spotify"))
    monkeypatch.setattr(pac.shutil, "which", lambda c: f"/usr/bin/{c}" if c == "wmctrl" else None)

    calls = []

    def fake_run(args, timeout=8.0):
        calls.append(list(args))
        if args[:2] == ["/usr/bin/wmctrl", "-x"]:
            return _CP(0, "")
        return _CP(1, "")

    monkeypatch.setattr(pac, "_run", fake_run)

    result = pac.focus_app("spotify")
    assert result["ok"] is True
    assert calls[0][1] == "-x", "must try WM_CLASS match (-x) before plain title match"


def test_focus_app_falls_back_to_xdotool_class_search(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac, "resolve_app", lambda q: pac.AppCandidate(name="spotify"))
    monkeypatch.setattr(
        pac.shutil, "which",
        lambda c: f"/usr/bin/{c}" if c in {"wmctrl", "xdotool"} else None,
    )

    calls = []

    def fake_run(args, timeout=8.0):
        calls.append(list(args))
        if args[0] == "/usr/bin/wmctrl":
            return _CP(1, "")
        if args[1:3] == ["search", "--class"]:
            return _CP(0, "12345\n")
        if args[1] == "windowactivate":
            return _CP(0, "")
        return _CP(1, "")

    monkeypatch.setattr(pac, "_run", fake_run)

    result = pac.focus_app("spotify")
    assert result["ok"] is True
    assert ["/usr/bin/xdotool", "search", "--class", "spotify"] in calls


def test_window_exists_true_when_class_search_finds_a_window(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac.shutil, "which", lambda c: f"/usr/bin/{c}" if c == "xdotool" else None)
    monkeypatch.setattr(pac, "_run", lambda args, timeout=8.0: (
        _CP(0, "12345\n") if args[1:3] == ["search", "--class"] else _CP(1, "")))
    assert pac.window_exists("spotify") is True


def test_window_exists_false_when_nothing_found(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac.shutil, "which", lambda c: f"/usr/bin/{c}" if c == "xdotool" else None)
    monkeypatch.setattr(pac, "_run", lambda args, timeout=8.0: _CP(0, ""))
    assert pac.window_exists("spotify") is False
