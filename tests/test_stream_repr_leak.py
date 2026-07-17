"""Behaviour lock: a streaming reply can never render as a generator repr.

Live bug (v2.1.17 AppImage, embedder-missing keyword-fallback path): 'hey eli'
rendered the literal '<generator object _wrap_stream_or_text.<locals>.gen at 0x…>'
instead of the reply. Root cause: the engine's streaming chain
(_stream_model_response → generate_stream_from_assembled_prompt → _stream_chat)
defensively does `str(chunk or "")`; when the whole stream object slipped through
a hop it was stringified into its Python repr and shown as the answer.

Fix: the single wrap chokepoint returns a _CleanTokenStream whose __str__/__repr__
yield the real text, so iterate → tokens (as before) and accidental str() → the
reply, never a repr.
"""

from eli.cognition.gguf_inference import _wrap_stream_or_text, _CleanTokenStream
from eli.runtime.visible_text import to_user_visible_text


def _stream(tokens):
    return _wrap_stream_or_text(iter(list(tokens)))


def test_str_of_stream_is_text_not_generator_repr():
    s = str(_stream(["Hey", " there"]))
    assert "generator object" not in s
    assert s == "Hey there"


def test_repr_of_stream_is_text_not_generator_repr():
    r = repr(_stream(["one", " two"]))
    assert "generator object" not in r
    assert r == "one two"


def test_the_exact_multihop_str_chunk_bug():
    """Reproduces `piece = str(chunk or "")` where chunk is the whole stream."""
    piece = str(_stream(["real", " reply"]) or "")
    assert "generator object" not in piece
    assert piece == "real reply"


def test_iteration_still_yields_tokens():
    tokens = list(_stream(["Hey", " Jason"]))
    assert "".join(tokens) == "Hey Jason"
    assert not any("generator object" in t for t in tokens)


def test_stream_is_recognised_as_a_stream_by_consumers():
    s = _stream(["hi"])
    # The GUI branch (`hasattr(result, '__next__')`) and to_user_visible_text
    # (`hasattr(result, '__next__')`) must still see it as an iterator.
    assert hasattr(s, "__next__") and hasattr(s, "__iter__")


def test_to_user_visible_text_consumes_the_stream():
    assert to_user_visible_text(_stream(["Real", " answer"])) == "Real answer"


def test_str_after_partial_iteration_returns_full_text():
    s = _CleanTokenStream(iter(["a", "b", "c"]))
    first = next(s)
    assert first == "a"
    assert str(s) == "abc"  # buffered "a" + drained "bc"


def test_dict_response_field_that_is_a_stream_is_consumed():
    """The 2.1.16 case must also stay fixed with the new wrapper type."""
    out = to_user_visible_text({"response": _stream(["from", " dict"]), "action": "CHAT"})
    assert out == "from dict"
    assert "generator object" not in out
