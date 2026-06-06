"""Regression: 'play X by Y on spotify' must open ONLY Spotify — never YouTube.

User report: requesting a Spotify song opened the search in BOTH YouTube and
Spotify and never actually played. Root cause was play_specific()'s Spotify
branch only returning when the dbus search reported success; on any failure it
fell through into the YouTube sections and opened a second platform.

These tests assert that an explicit Spotify target stays on Spotify in both the
success and the unreachable-Spotify paths.
"""
from __future__ import annotations

import subprocess

from eli.execution import executor_enhanced as ex


def _install_capture(monkeypatch, *, run_rc=0, run_stdout="Playing"):
    calls = {"popen": [], "run": []}

    class _P:
        pid = 1

    class _R:
        returncode = run_rc
        stdout = run_stdout
        stderr = ""

    def fake_popen(argv, *a, **k):
        calls["popen"].append(list(argv) if isinstance(argv, (list, tuple)) else [str(argv)])
        return _P()

    def fake_run(argv, *a, **k):
        calls["run"].append(list(argv) if isinstance(argv, (list, tuple)) else [str(argv)])
        return _R()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(ex.time, "sleep", lambda *_a, **_k: None)
    return calls


def _has_youtube(calls):
    blob = " ".join(" ".join(c) for c in calls["popen"] + calls["run"]).lower()
    return ("youtube" in blob) or ("ytsearch" in blob) or ("ytdl" in blob)


def test_spotify_target_plays_and_never_opens_youtube(monkeypatch):
    # Spotify reachable; status reports Playing -> honest played=True.
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    calls = _install_capture(monkeypatch, run_rc=0, run_stdout="Playing")

    res = ex.play_specific("juicy by notorious big", "spotify")

    assert res["action"] == "PLAY_MEDIA"
    assert res.get("played") is True
    assert not _has_youtube(calls), "Spotify request must not open YouTube"


def test_spotify_unreachable_reports_search_only_not_youtube(monkeypatch):
    # Every dbus/playerctl call fails and Spotify is not running -> must NOT
    # fall through to YouTube; must return an honest search_only/failure result.
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    calls = _install_capture(monkeypatch, run_rc=1, run_stdout="")

    res = ex.play_specific("juicy by notorious big", "spotify")

    assert res["action"] == "PLAY_MEDIA"
    assert res.get("played") is not True
    assert res.get("search_only") is True
    assert res.get("target") == "spotify"
    assert not _has_youtube(calls), "Unreachable Spotify must not open YouTube"
