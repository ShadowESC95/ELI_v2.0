"""User-visible response surface — coerce_user_visible / streaming coercer.

Guarantees the GUI/voice never receive a raw envelope dict, a JSON surface packet,
or a `<generator object …>` repr — everything collapses to clean display text.
Pure, model-free. Runs in the normal suite.
"""
from __future__ import annotations

import json

import pytest

from eli.runtime import user_visible_response_surface as rs


# --------------------------------------------------------------------------- #
# coerce_user_visible
# --------------------------------------------------------------------------- #
def test_plain_string_passes_through():
    assert rs.coerce_user_visible("hello world") == "hello world"


def test_dict_prefers_response_field():
    assert rs.coerce_user_visible({"ok": True, "response": "the answer"}) == "the answer"


def test_dict_uses_content_when_no_response():
    assert rs.coerce_user_visible({"ok": True, "content": "from content"}) == "from content"


def test_dict_without_text_never_leaks_envelope():
    out = rs.coerce_user_visible({"ok": False, "action": "OPEN_APP"})
    assert "OPEN_APP" in out and out.startswith("No user-visible response")
    assert "{" not in out  # never a raw dict repr


def test_none_becomes_empty_string():
    assert rs.coerce_user_visible(None) == ""


def test_non_str_non_dict_stringified():
    assert rs.coerce_user_visible(42) == "42"


def test_generator_is_consumed_not_repr():
    def gen():
        yield "alpha "
        yield "beta"
    out = rs.coerce_user_visible(gen())
    assert isinstance(out, str)
    assert "generator object" not in out
    assert "alpha" in out and "beta" in out


# --------------------------------------------------------------------------- #
# JSON surface packets must render as readable text, never raw JSON
# --------------------------------------------------------------------------- #
def test_identity_surface_packet_renders_readable():
    packet = json.dumps({"surface": "identity_evidence"})
    out = rs.coerce_user_visible(packet)
    assert not out.strip().startswith("{")
    assert "ELI" in out or "Identity" in out


def test_generic_surface_packet_extracts_response():
    packet = json.dumps({"surface": "runtime_evidence", "response": "grounded answer"})
    assert rs.coerce_user_visible(packet) == "grounded answer"


# --------------------------------------------------------------------------- #
# _coerce_streaming_result
# --------------------------------------------------------------------------- #
def test_streaming_dict_collapses_to_string():
    assert rs._coerce_streaming_result({"response": "done"}) == "done"


def test_streaming_generator_yields_clean_chunks():
    def gen():
        yield {"delta": "one "}
        yield "two"
        yield {"no_text": True}   # envelope chunk with no usable text → dropped
    out = "".join(list(rs._coerce_streaming_result(gen())))
    assert "one" in out and "two" in out
    assert "no_text" not in out and "{" not in out
