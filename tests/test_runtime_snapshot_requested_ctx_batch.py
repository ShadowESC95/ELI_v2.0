"""The runtime report records what the load was asked for separately from what loaded, so a load
that came out smaller is not reported as "loaded as requested", and what loaded is read from the
live model rather than from the plan that was handed to it."""
from __future__ import annotations

from types import SimpleNamespace

from eli.cognition.gguf_inference import _requested_and_effective


def _plan(**kw):
    base = dict(n_ctx=4096, n_gpu_layers=11, n_threads=10, n_batch=128,
                asked={"n_ctx": 12384, "n_gpu_layers": 41, "n_batch": 256})
    base.update(kw)
    return SimpleNamespace(**base)


def _llm(n_ctx=4096, n_gpu_layers=11, n_threads=10, n_batch=128):
    return SimpleNamespace(n_ctx=lambda: n_ctx, model_params=SimpleNamespace(n_gpu_layers=n_gpu_layers),
                           n_threads=n_threads, n_batch=n_batch)


def test_a_smaller_load_reports_the_original_request():
    """The live scenario: asked ctx=12384, the memory free gave 4096."""
    requested, effective = _requested_and_effective(_plan(), _llm())
    assert (requested["n_ctx"], requested["n_gpu_layers"], requested["n_batch"]) == (12384, 41, 256)
    assert (effective["n_ctx"], effective["n_gpu_layers"], effective["n_batch"]) == (4096, 11, 128)


def test_a_load_as_asked_reports_the_same_on_both_sides():
    plan = _plan(n_ctx=8192, n_gpu_layers=41, n_batch=512,
                 asked={"n_ctx": 8192, "n_gpu_layers": 41, "n_batch": 512})
    requested, effective = _requested_and_effective(plan, _llm(8192, 41, 10, 512))
    assert requested == effective


def test_what_loaded_is_read_from_the_live_model():
    """llama.cpp may change a value while building the model; the report says what it built."""
    _requested, effective = _requested_and_effective(_plan(n_ctx=8000), _llm(n_ctx=8192))
    assert effective["n_ctx"] == 8192


def test_a_model_that_cannot_say_falls_back_to_the_plan():
    _requested, effective = _requested_and_effective(_plan(asked={}), SimpleNamespace())
    assert effective == {"n_ctx": 4096, "n_gpu_layers": 11, "n_threads": 10, "n_batch": 128}
