"""What ELI reports about its own load must match what actually happened.

Three defects found while verifying the 27B on the Vulkan GPU pack. None
stopped the model running; all three make a later diagnostic lie, which is
the failure class this project spends most of its guards preventing.

  1. smart-fit reduced 28 GPU layers to 16 and llama.cpp confirmed
     "offloaded 16/66", but the very next line read
     "[GGUF][EFFECTIVE] ... -> effective gpu_layers=28". The precedence put
     `selected` (the loader's PLAN) ahead of the live model object (what was
     actually constructed), so the plan won and the log contradicted itself.
  2. `get_last_load_params()` returned {} after every successful load, so
     every caller read None for every field. `_last_params` was declared at
     module level and never assigned once.
  3. `generate("Say hello")` logged RAW_TEXT 'Hello! How can I help you
     today' and returned an object whose str() was ''. The legacy generator
     yields dicts -- {"response": ...} -- and the stream buffer appended only
     `isinstance(tok, str)`, so every chunk was dropped. Silently returning
     nothing for a call that succeeded is the same failure as the
     generator-repr leak _CleanTokenStream exists to prevent.
"""
import inspect

import pytest

from eli.cognition import gguf_inference as gi


# ── 1. "effective" means what the runtime really did ───────────────────────
def test_effective_prefers_the_live_object_over_the_plan():
    src = inspect.getsource(gi)
    start = src.index("effective[key] = _eli_eff_int(")
    window = src[start:start + 400]
    live_at = window.index("live_value")
    sel_at = window.index("selected_value")
    assert live_at < sel_at, (
        "the selected candidate outranks the live model again; a reduced load "
        "will report the number it intended, not the one it used"
    )


# ── 2. the load parameters must actually be recorded ───────────────────────
def test_last_params_is_populated_on_load():
    src = inspect.getsource(gi)
    assert 'globals()["_last_params"] = {' in src, \
        "_last_params is declared and never assigned again"


def test_get_last_load_params_falls_back_to_live():
    """Even if the write is missed, reporting nothing about a model that is
    demonstrably loaded is worse than reporting the live snapshot."""
    src = inspect.getsource(gi.get_last_load_params)
    assert "_live_runtime_params" in src


def test_get_last_load_params_returns_a_dict():
    out = gi.get_last_load_params()
    assert isinstance(out, dict)


# ── 3. a stream's str() must not drop the text ─────────────────────────────
@pytest.mark.parametrize("chunk,expected", [
    ("plain text", "plain text"),
    ({"response": "from response"}, "from response"),
    ({"text": "from text"}, "from text"),
    ({"content": "from content"}, "from content"),
    ({"choices": [{"text": "openai shaped"}]}, "openai shaped"),
    ({"choices": [{"delta": {"content": "delta shaped"}}]}, "delta shaped"),
])
def test_every_chunk_shape_yields_its_text(chunk, expected):
    assert gi._stream_chunk_text(chunk) == expected


@pytest.mark.parametrize("junk", [None, 42, [], {}, {"unrelated": "x"}])
def test_unrecognised_chunks_are_empty_not_crashes(junk):
    assert gi._stream_chunk_text(junk) == ""


def test_stream_str_returns_the_text_of_dict_chunks():
    """The exact defect: a generator of {"response": ...} stringified to ''."""
    stream = gi._CleanTokenStream(iter([
        {"response": "Hello! "}, {"response": "How can I help"},
    ]))
    assert str(stream) == "Hello! How can I help"


def test_stream_str_still_works_for_string_chunks():
    stream = gi._CleanTokenStream(iter(["Hello! ", "How can I help"]))
    assert str(stream) == "Hello! How can I help"


def test_stream_str_never_leaks_a_generator_repr():
    """The original reason this class exists -- still true after the change."""
    def gen():
        yield {"response": "text"}
    out = str(gi._CleanTokenStream(gen()))
    assert "generator object" not in out
    assert out == "text"


def test_partial_iteration_then_str_keeps_everything():
    stream = gi._CleanTokenStream(iter([
        {"response": "one "}, {"response": "two "}, {"response": "three"},
    ]))
    first = next(iter(stream))
    assert first == {"response": "one "} or first == "one "
    assert "two" in str(stream) and "three" in str(stream)
