from __future__ import annotations

from eli.runtime.visible_text import to_user_visible_text


def test_visible_text_prefers_response_from_dict():
    result = {
        "ok": True,
        "action": "TEST_ACTION",
        "content": "content value",
        "response": "response value",
    }
    assert to_user_visible_text(result) == "response value"


def test_visible_text_falls_back_to_content_from_dict():
    result = {
        "ok": True,
        "action": "TEST_ACTION",
        "content": "content value",
        "response": "",
    }
    assert to_user_visible_text(result) == "content value"


def test_visible_text_handles_plain_string():
    assert to_user_visible_text(" already visible ") == "already visible"


def test_visible_text_handles_none():
    assert to_user_visible_text(None) == ""


def test_visible_text_does_not_dump_raw_dict_when_no_content():
    result = {
        "ok": True,
        "action": "TEST_ACTION",
        "report": {"internal": "evidence"},
    }
    text = to_user_visible_text(result)
    assert text == "No user-visible response was produced for action TEST_ACTION."
    assert "{'ok':" not in text
    assert '"ok":' not in text


def test_visible_text_consumes_generator_tokens():
    def gen():
        yield "hello"
        yield " "
        yield "world"

    assert to_user_visible_text(gen()) == "hello world"


def test_visible_text_consumes_generator_dict_chunks():
    def gen():
        yield {"delta": "hello"}
        yield {"content": " world"}

    assert to_user_visible_text(gen()) == "hello world"
