"""Two perception paths imported names that do not exist and failed silently."""
from eli.perception import audio_stt, wakeword


def test_stt_diagnostics_reports_the_wake_phrase(monkeypatch):
    monkeypatch.setattr(wakeword, "is_trained", lambda: True)
    monkeypatch.setattr(wakeword, "get_wake_phrases", lambda: ["hey eli"])
    out = audio_stt.stt_diagnostics()
    assert out["wake_model_trained"] is True and out["wake_phrase"] == "hey eli"
