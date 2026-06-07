"""Document generation: clean topic parsing + self-referential grounding.

User-reported (2026-06-07): "generate a document with proposals for upgrades for
yourself" produced (a) a filename/topic that kept the leading "with", and (b) a
GENERIC HUMAN self-help plan (buy a tablet, exercise, work-life balance) instead
of a document grounded in ELI's own architecture.

Deterministic — the GGUF model is mocked; only routing + prompt assembly is tested.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from eli.execution.router_enhanced import route


# ── topic parsing strips command framing + stacked leading connectives ───────
@pytest.mark.parametrize("text,expected", [
    ("generate a document with proposals for upgrades for yourself",
     "proposals for upgrades for yourself"),
    ("generate a document about quantum computing", "quantum computing"),
    ("generate a document on the history of rome", "history of rome"),
])
def test_doc_topic_extraction(text, expected):
    r = route(text)
    assert r.get("action") == "GENERATE_DOCUMENT"
    assert (r.get("args") or {}).get("topic") == expected
    # raw text preserved so the executor can detect self-reference
    assert (r.get("args") or {}).get("_raw_user_text") == text


def test_self_description_block_is_grounded():
    from eli.execution.executor_enhanced import _eli_self_description_block
    b = _eli_self_description_block()
    assert b and "ELI" in b
    assert "local" in b.lower()
    assert ("netguard" in b.lower() or "agent" in b.lower() or "memory" in b.lower())


def _capture_doc_prompt(topic, raw):
    """Run GENERATE_DOCUMENT with the model mocked; return the user prompt."""
    import eli.cognition.gguf_inference as g
    captured = {}
    _orig_load, _orig_chat = g.load_model, g.chat_completion
    g.load_model = lambda *a, **k: object()
    def fake_chat(user_prompt, system=None, **k):
        captured["user"] = user_prompt
        return "# Doc\n\n" + ("Substantive grounded body content here. " * 60)
    g.chat_completion = fake_chat
    os.environ["ELI_ARTIFACTS_DIR"] = tempfile.mkdtemp()
    _prev_tm = os.environ.get("ELI_TEST_MODE")
    os.environ["ELI_TEST_MODE"] = "0"  # exercise the real (mocked) generation path
    try:
        from eli.execution.executor_enhanced import execute
        execute("GENERATE_DOCUMENT", {"topic": topic, "_raw_user_text": raw, "format": "md"})
    finally:
        g.load_model, g.chat_completion = _orig_load, _orig_chat
        if _prev_tm is None:
            os.environ.pop("ELI_TEST_MODE", None)
        else:
            os.environ["ELI_TEST_MODE"] = _prev_tm
    return captured.get("user", "")


def test_self_referential_doc_is_grounded_and_reframed():
    u = _capture_doc_prompt("proposals for upgrades for yourself",
                            "generate a document with proposals for upgrades for yourself")
    assert u
    # grounding block injected, topic reframed from "yourself" to ELI
    assert "ACTUAL architecture" in u
    assert "ELI" in u
    assert "yourself" not in u.lower()
    # explicitly forbids the generic-human-advice failure mode
    assert "personal-productivity" in u.lower() or "work-life" in u.lower()


def test_normal_doc_has_no_self_grounding():
    u = _capture_doc_prompt("quantum computing", "generate a document about quantum computing")
    assert u
    assert "ACTUAL architecture" not in u
    assert "Write a complete document about: quantum computing" in u
