"""Shutdown aborts in-flight inference so teardown never blocks on a long native call.

Regression for the 20-30 min shutdown hang: a background self-improvement/codegen call
sat in a single multi-minute native llm() call holding the shared lock, so unload_model()
blocked. signal_shutdown() installs a cooperative abort on EVERY generation (foreground
and background) and the broker short-circuits new calls.
"""
import eli.cognition.gguf_inference as gi


def test_shutdown_signal_roundtrip():
    gi.clear_shutdown()
    assert gi.is_shutting_down() is False
    gi.signal_shutdown()
    assert gi.is_shutting_down() is True
    gi.clear_shutdown()
    assert gi.is_shutting_down() is False


def test_shutdown_aborts_every_call():
    gi.clear_shutdown()
    gi._FG_PRIORITY.clear()
    try:
        gi.signal_shutdown()
        assert gi._should_abort_generation(background=True) is True
        assert gi._should_abort_generation(background=False) is True
    finally:
        gi.clear_shutdown()


def test_fg_priority_preempts_background_only_not_foreground():
    # A waiting foreground turn preempts BACKGROUND work but never aborts foreground work.
    gi.clear_shutdown()
    gi._FG_PRIORITY.set()
    try:
        assert gi._should_abort_generation(background=False) is False  # foreground runs
        assert gi._should_abort_generation(background=True) is True    # background yields
    finally:
        gi._FG_PRIORITY.clear()


def test_no_abort_when_idle():
    gi.clear_shutdown()
    gi._FG_PRIORITY.clear()
    assert gi._should_abort_generation(background=True) is False
    assert gi._should_abort_generation(background=False) is False


def test_broker_short_circuits_new_calls_during_shutdown():
    from eli.cognition.inference_broker import get_broker
    broker = get_broker()
    if broker is None or not getattr(broker, "gguf_ready", False):
        import pytest
        pytest.skip("no broker/model loaded")
    gi.signal_shutdown()
    try:
        assert broker.infer("hello", system="x", max_tokens=8) == ""
    finally:
        gi.clear_shutdown()
