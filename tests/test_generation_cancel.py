"""User-initiated generation cancel (Stop button)."""
from eli.cognition import gguf_inference as gi


def test_user_cancel_aborts_generation():
    gi.clear_cancel_generation()
    gi.clear_shutdown()
    assert gi._should_abort_generation(background=False) is False
    gi.request_cancel_generation()
    assert gi._should_abort_generation(background=False) is True
    assert gi._should_abort_generation(background=True) is True
    gi.clear_cancel_generation()
    assert gi._should_abort_generation(background=False) is False


def test_shutdown_still_aborts_without_user_cancel():
    gi.clear_cancel_generation()
    gi.clear_shutdown()
    gi.signal_shutdown()
    assert gi._should_abort_generation(background=False) is True
    gi.clear_shutdown()
