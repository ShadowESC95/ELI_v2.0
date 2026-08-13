"""Lock on _live_runtime_snapshot reading llama_cpp's n_ctx.

Found by running the real engine, not by reading code: every turn logged

    File "engine.py", line 4299, in _live_runtime_snapshot
        snap[key] = int(value)
    TypeError: int() argument must be ... not 'method'

twice, swallowed by `except Exception: log.debug("suppressed exception")`. llama_cpp
exposes `n_ctx` as a METHOD (`llm.n_ctx()`), so `int(<bound method>)` always raised and
the preferred live-object path fell through to the parameter-container guesses below
it. The snapshot still produced a number, so nothing ever looked broken — the same
"suppressed exception hides a real defect" shape as the earlier guard failures.
"""
import inspect

from eli.kernel.engine import CognitiveEngine


class _LlamaLike:
    """Mimics llama_cpp.Llama: n_ctx is callable, the rest absent."""
    def n_ctx(self):
        return 6144


def test_llama_cpp_still_exposes_n_ctx_as_a_method():
    """If upstream ever makes it a plain attribute the guard is harmless, but this
    records WHY the callable check is there."""
    import llama_cpp
    assert callable(getattr(llama_cpp.Llama, "n_ctx", None))


def test_snapshot_calls_a_callable_before_coercing():
    src = inspect.getsource(CognitiveEngine._live_runtime_snapshot)
    head = src[:src.index("Common llama_cpp parameter containers")]
    assert "callable(value)" in head and "value = value()" in head, (
        "the live-object path will raise TypeError on llama_cpp's n_ctx() again"
    )


def test_a_callable_attribute_coerces_to_its_value():
    """The actual behaviour: int() must see 6144, not a bound method."""
    value = _LlamaLike().n_ctx
    if callable(value):
        value = value()
    assert int(value) == 6144
