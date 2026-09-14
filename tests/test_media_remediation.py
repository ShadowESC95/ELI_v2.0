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


def test_media_tool_yes_executes_on_first_affirmation(monkeypatch):
    """Jess Iris Xe regression: 'yes' to mpv install must not stop at a preview
    the LLM can narrate instead of running apt."""
    from eli.runtime import grounded_remediation as gr

    gr.clear_pending()
    calls: list[str] = []

    def _fake_exec():
        calls.append("exec")
        return "Repair completed."

    monkeypatch.setattr(gr, "execute_pending_plan", _fake_exec)
    gr.set_pending_for_test(
        {
            "domain": "media_tool",
            "subject": "mpv",
            "title": "Install mpv",
            "commands": ["sudo apt-get install -y mpv"],
            "steps": [],
            "verification_steps": [],
        },
        {"ok": False, "domain": "media_tool", "subject": "mpv"},
        stage="offered",
    )
    out = gr.try_handle_query("yes")
    assert out == "Repair completed."
    assert calls == ["exec"]
    gr.clear_pending()


def test_remediation_confirm_is_phase45_direct():
    src = open(
        __file__.replace("tests/test_media_remediation.py", "eli/kernel/engine.py"),
        encoding="utf-8",
    ).read()
    block = src.split("_PHASE45_DIRECT_FAST_ACTIONS")[1].split("_PHASE45_SILENT")[0]
    assert "CONFIRM_PENDING_REMEDIATION" in block
    assert "CANCEL_PENDING_REMEDIATION" in block


def test_download_install_offer_not_armed_as_proposal():
    from eli.runtime.pending_proposal import extract_proposal
    assert extract_proposal(
        "I can't play that on YouTube yet — mpv is not available on this machine.\n\n"
        "Would you like me to download/install it?"
    ) == ""
