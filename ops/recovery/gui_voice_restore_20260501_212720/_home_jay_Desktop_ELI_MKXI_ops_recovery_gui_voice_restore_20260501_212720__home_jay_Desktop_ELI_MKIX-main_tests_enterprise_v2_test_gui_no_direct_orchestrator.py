from pathlib import Path


def test_gui_no_longer_directly_runs_orchestrator():
    txt = Path("eli/gui/eli_pro_audio_gui_MKI.py").read_text(encoding="utf-8")
    assert "AgentOrchestrator(adapter).run(" not in txt
    assert "PATH2 FALLBACK -> AgentOrchestrator(adapter)" not in txt
