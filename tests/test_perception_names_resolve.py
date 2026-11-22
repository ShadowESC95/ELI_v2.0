"""Two perception paths imported names that do not exist and failed silently."""
from eli.perception import audio_stt, wakeword


def test_stt_diagnostics_reports_the_wake_phrase(monkeypatch):
    monkeypatch.setattr(wakeword, "is_trained", lambda: True)
    monkeypatch.setattr(wakeword, "get_wake_phrases", lambda: ["hey eli"])
    out = audio_stt.stt_diagnostics()
    assert out["wake_model_trained"] is True and out["wake_phrase"] == "hey eli"


def test_reading_the_wake_phrases_writes_nothing(tmp_path, monkeypatch):
    """Reading them seeded a default file, so a fresh checkout's test run made models/wakeword/ in it."""
    import eli.core.paths as paths
    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "models")
    assert wakeword.get_wake_phrases() == list(wakeword._DEFAULT_PHRASES)
    assert not wakeword.is_trained()
    assert not (tmp_path / "models").exists()
    assert wakeword.set_wake_phrases(["Hey Nova"]) == ["hey nova"]
    assert wakeword.get_wake_phrases() == ["hey nova"]
