"""One CognitiveEngine per process.

From a live 2.2.5 log: after the startup dialog loaded the model, a SECOND full
engine init ran mid-session —

    [COGNITIVE] GGUF model loaded successfully          <- again
    [COGNITIVE] Habit scheduler started                 <- again
    [COGNITIVE] Self-improvement loop started           <- again
    [COGNITIVE] Proactive daemon already running - skipping duplicate start
    [COGNITIVE] Signal handler registration failed ... signal only works in main thread
    ...
    [COGNITIVE] Shutdown: complete.                     <- twice, the second saying
    [COGNITIVE] Shutdown: native teardown already done by another instance

The GUI built its engine directly and never published it, so the first
background caller of get_engine() (habits_scheduler, on its own thread) built
another one — with auto_init_gguf defaulting to True, hence the second model
load. Only the proactive daemon had its own duplicate guard; the habit
scheduler and self-improvement loop did not.
"""
import inspect
import threading

from eli.kernel import engine as eng


def test_set_engine_exists_and_publishes():
    e = object()
    prev = eng._engine
    try:
        eng.set_engine(e)
        assert eng.get_engine() is e, "a published engine must be the one handed out"
    finally:
        eng._engine = prev


def test_get_engine_is_locked():
    """Two background threads racing would each build an engine, and the loser's
    daemons would already be running when it was discarded."""
    src = inspect.getsource(eng.get_engine)
    assert "_engine_lock" in src
    assert isinstance(eng._engine_lock, type(threading.Lock()))


def test_the_gui_publishes_its_engine():
    import pathlib
    gui = pathlib.Path(eng.__file__).resolve().parents[1] / "gui" / "eli_pro_audio_gui_v2_0.py"
    src = gui.read_text(encoding="utf-8")
    i = src.index("self._cognitive_engine = CognitiveEngine(")
    j = src.index("CognitiveEngine singleton ready", i)
    assert "set_engine(self._cognitive_engine)" in src[i:j], (
        "the GUI builds an engine the rest of the process cannot see, so "
        "get_engine() will construct a second one"
    )


def test_the_gui_engine_does_not_autoload_the_model():
    """The startup dialog loads it later with the operator's parameters; a
    second engine defaulting to auto_init_gguf=True is what loaded it twice."""
    import pathlib
    gui = pathlib.Path(eng.__file__).resolve().parents[1] / "gui" / "eli_pro_audio_gui_v2_0.py"
    src = gui.read_text(encoding="utf-8")
    i = src.index("self._cognitive_engine = CognitiveEngine(")
    assert "auto_init_gguf=False" in src[i:i + 200]
