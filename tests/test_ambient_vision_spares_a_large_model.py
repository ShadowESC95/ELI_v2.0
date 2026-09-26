"""A glance that would unload and reload a large chat model waits for a quiet spell."""
from eli.perception import ambient_vision as av


def test_a_large_model_is_not_reloaded_just_after_a_conversation(monkeypatch):
    monkeypatch.setattr(av, "_swap_is_expensive", lambda: True)
    monkeypatch.setattr("eli.cognition.inference_broker.seconds_since_foreground", lambda: 120.0)
    assert av._too_soon_after_conversation() is True
    monkeypatch.setattr("eli.cognition.inference_broker.seconds_since_foreground", lambda: 2000.0)
    assert av._too_soon_after_conversation() is False


def test_a_cheap_swap_is_never_held_back(monkeypatch):
    monkeypatch.setattr(av, "_swap_is_expensive", lambda: False)
    monkeypatch.setattr("eli.cognition.inference_broker.seconds_since_foreground", lambda: 1.0)
    assert av._too_soon_after_conversation() is False


def test_the_wait_can_be_shortened(monkeypatch):
    monkeypatch.setenv("ELI_AMBIENT_LARGE_MODEL_IDLE_S", "60")
    monkeypatch.setattr(av, "_swap_is_expensive", lambda: True)
    monkeypatch.setattr("eli.cognition.inference_broker.seconds_since_foreground", lambda: 120.0)
    assert av._too_soon_after_conversation() is False


def test_the_size_check_reads_the_loaded_model(tmp_path, monkeypatch):
    import json
    big = tmp_path / "big.gguf"
    with open(big, "wb") as f:
        f.truncate(9 * 1024 ** 3)
    (tmp_path / "runtime_snapshot.json").write_text(json.dumps({"model_path": str(big)}))
    monkeypatch.setattr("eli.core.paths.get_paths", lambda: type("P", (), {"artifacts_dir": tmp_path})())
    monkeypatch.setattr(av, "_cfg", lambda k, d=None: False if k == "vision_fast_no_swap" else d)
    assert av._swap_is_expensive() is True
    monkeypatch.setattr(av, "_cfg", lambda k, d=None: True if k == "vision_fast_no_swap" else d)
    assert av._swap_is_expensive() is False
