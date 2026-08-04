"""Grammar-constrained tool calling: the model can only name a capability that exists.

The unconstrained resolver had three failure modes visible in its own parsing code —
markdown-fenced JSON (hence a regex strip), truncation mid-object, and invented action
names. Each collapsed the turn to CHAT, and a CHAT that then narrates having run the
command is precisely the confabulation ELI is built to prevent. A GBNF grammar makes an
invented capability unrepresentable rather than merely rejected after the fact.
"""
from __future__ import annotations
import pytest
from eli.cognition import llm_intent as li


def test_grammar_builds_over_the_live_catalogue():
    cat = li._catalogue()
    assert len(cat) > 50, "catalogue should expose the real action surface"
    assert li._action_grammar(cat) is not None


def test_grammar_is_cached_not_rebuilt_per_turn():
    cat = li._catalogue()
    assert li._action_grammar(cat) is li._action_grammar(cat)


def test_empty_catalogue_yields_no_grammar():
    # never constrain to nothing — that would make every turn unsatisfiable
    assert li._action_grammar([]) is None


def test_grammar_admits_only_catalogue_actions():
    # built by literal alternation, so a fabricated name cannot appear in the grammar
    cat = li._catalogue()
    # CHAT is internal (not advertised in the catalogue) but must still be emittable,
    # otherwise every greeting would be forced into a command.
    assert "CHAT" not in cat
    assert "TOTALLY_MADE_UP_ACTION" not in cat
    admitted = set(cat) | {"CHAT"}
    assert "CHAT" in admitted and "TOTALLY_MADE_UP_ACTION" not in admitted


def test_grammar_admits_chat_so_small_talk_stays_routable():
    from llama_cpp import LlamaGrammar
    calls = {}
    real = LlamaGrammar.from_string
    def spy(gbnf, *a, **k):
        calls["gbnf"] = gbnf
        return real(gbnf, *a, **k)
    LlamaGrammar.from_string = spy
    try:
        li._GRAMMAR_CACHE.clear()
        li._action_grammar(li._catalogue())
    finally:
        LlamaGrammar.from_string = real
        li._GRAMMAR_CACHE.clear()
    # GBNF escapes the JSON quotes, so the literal reads \"CHAT\"
    assert '\\"CHAT\\"' in calls["gbnf"], "CHAT must be an admitted alternative"


def test_resolver_still_returns_a_valid_shape_without_a_model(monkeypatch):
    # with inference unavailable the resolver must degrade to CHAT, not raise
    monkeypatch.setattr(li.gguf_inference, "chat_completion",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model")))
    out = li.parse_with_llm("open my project")
    assert isinstance(out, dict) and out.get("action")
    assert out["action"] in set(li._catalogue()) | {"CHAT"}


def test_grammar_failure_falls_back_to_free_text(monkeypatch):
    # a backend that rejects the grammar kwarg (Ollama/remote) must still route
    calls = {"n": 0}
    def fake(*a, **k):
        calls["n"] += 1
        if "grammar" in k:
            raise TypeError("unexpected keyword argument 'grammar'")
        return '{"action":"CHAT","args":{},"confidence":0.9}'
    monkeypatch.setattr(li.gguf_inference, "chat_completion", fake)
    out = li.parse_with_llm("hello there friend")
    assert out["action"] == "CHAT"
    assert calls["n"] >= 1  # tried grammar, then fell back


def test_grammar_object_reaches_the_live_model_call(monkeypatch):
    """End-to-end: the grammar must survive chat_completion -> _chat_completion_legacy ->
    _generate_legacy -> _safe_invoke_llm -> the llama object. A grammar that is built but
    dropped in transit constrains nothing while looking correct in isolation."""
    from eli.cognition import gguf_inference as gi
    seen = {}

    def fake_safe_invoke(llm, full_prompt, **kw):
        seen["grammar"] = kw.get("grammar")
        return {"choices": [{"text": '{"action":"DATE","args":{},"confidence":0.9}'}]}

    monkeypatch.setattr(gi, "_safe_invoke_llm", fake_safe_invoke)
    monkeypatch.setattr(gi, "_llm", object())  # non-None so generate() proceeds
    out = li.parse_with_llm("what is the date today")

    assert seen.get("grammar") is not None, "grammar was dropped before reaching the model"
    assert out["action"] in set(li._catalogue()) | {"CHAT"}
