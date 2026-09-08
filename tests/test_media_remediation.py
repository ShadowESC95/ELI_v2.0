"""Grounded remediation offers pip yt-dlp and OS packages for mpv."""
from __future__ import annotations

from eli.runtime.grounded_remediation import build_install_candidates, diagnose_media_tool


def test_yt_dlp_install_candidate_includes_pip(monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.grounded_remediation._platform",
        lambda: "linux",
    )
    monkeypatch.setattr(
        "eli.runtime.grounded_remediation._apt_candidate",
        lambda name: "",
    )
    cands = build_install_candidates("yt-dlp")
    sources = [c["source"] for c in cands]
    assert "pip" in sources
    pip = next(c for c in cands if c["source"] == "pip")
    assert "pip install" in pip["command"]
    assert "yt-dlp" in pip["command"]


def test_mpv_install_candidates_cross_platform(monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.grounded_remediation._platform",
        lambda: "windows",
    )
    monkeypatch.setattr(
        "eli.runtime.grounded_remediation.shutil.which",
        lambda cmd: "winget" if cmd == "winget" else None,
    )
    cands = build_install_candidates("mpv")
    assert any(c["source"] == "winget" for c in cands)
    winget = next(c for c in cands if c["source"] == "winget")
    assert "mpv.MPV" in winget["command"]


def test_diagnose_missing_mpv_offers_install(monkeypatch):
    monkeypatch.setattr(
        "eli.integrations.media.media_deps.media_tool_installed",
        lambda name: False,
    )
    monkeypatch.setattr(
        "eli.runtime.grounded_remediation.build_install_candidates",
        lambda name: [{
            "source": "apt",
            "command": "sudo apt-get install -y mpv",
            "label": "Install mpv via apt",
        }],
    )
    diag = diagnose_media_tool("mpv")
    assert diag["ok"] is False
    assert diag["domain"] == "media_tool"
    assert diag["repairable"] is True
    assert diag["repair_options"]
