"""User-initiated generation cancel (Stop button)."""
from eli.cognition import gguf_inference as gi
from eli.kernel.engine import CognitiveEngine


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


def test_get_chat_response_short_circuits_once_cancelled():
    """Stop was taking minutes: CoT/ToT/constitutional/self-consistency chain
    several _get_chat_response calls per turn with nothing checked between
    them, so Stop only took effect after every remaining stage had also run
    its own full generation. This is the single choke point all of them go
    through — one check here instead of patching each reasoning mode."""
    eng = CognitiveEngine()
    gi.clear_cancel_generation()
    try:
        gi.request_cancel_generation()
        assert eng._get_chat_response("anything", reasoning_mode="chain_of_thought") == ""
    finally:
        gi.clear_cancel_generation()
