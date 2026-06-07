"""Document generation: clean topic parsing + evidence-grounded synthesis.

User-reported (2026-06-07): document/script generation ran with NO evidence-
gathering agents (the plan was just generate→open), so every topic came back
generic — e.g. "proposals for upgrades for yourself" produced human productivity
advice instead of analysing ELI's actual code. The fix routes the right evidence
per task (code/file analysis, web, memory) and grounds the generation in it.

Deterministic — the GGUF model and the heavy evidence sources are mocked; only
routing + prompt assembly is tested.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from eli.execution.router_enhanced import route
import eli.execution.executor_enhanced as E


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
    assert (r.get("args") or {}).get("_raw_user_text") == text


def test_self_description_block_is_grounded():
    b = E._eli_self_description_block()
    assert b and "ELI" in b
    assert "local" in b.lower()
    assert ("netguard" in b.lower() or "agent" in b.lower() or "memory" in b.lower())


# ── evidence ROUTING: the right agent/tool per topic type ────────────────────
def test_evidence_router_self_topic_uses_code_and_architecture():
    ev, src = E._gather_generation_evidence(
        "proposals for upgrades for ELI itself",
        "generate a document with proposals for upgrades for yourself")
    # the architecture blueprint is a deterministic, always-available source
    assert "blueprints/what_eli_is.md" in src
    assert ev and "ELI" in ev


def test_evidence_router_external_topic_uses_web(monkeypatch):
    import eli.core.config as C
    import eli.plugins.web.plugin as W
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    monkeypatch.setattr(W, "_web_search_results",
                        lambda q, max_results=5: [{"title": "Rome", "href": "http://x",
                                                   "body": "Ancient Rome founded 753 BC"}])
    ev, src = E._gather_generation_evidence("the history of rome",
                                            "generate a document on the history of rome")
    assert "web_search" in src
    assert "Ancient Rome" in ev


def test_evidence_router_personal_topic_uses_memory(monkeypatch):
    class _FM:
        def recall_memory(self, q, limit=10, keyword_only=False):
            return [{"text": "User's research framework is the field-coherence model."}]
    import eli.memory as _mem
    monkeypatch.setattr(_mem, "get_memory", lambda: _FM())
    ev, src = E._gather_generation_evidence("my research framework",
                                            "generate a document about my research framework")
    assert "memory.recall" in src
    assert "field-coherence" in ev


def test_external_topic_offline_gathers_nothing(monkeypatch):
    import eli.core.config as C
    monkeypatch.setattr(C, "network_allowed", lambda: False)
    ev, src = E._gather_generation_evidence("the history of rome",
                                            "generate a document on the history of rome")
    assert "web_search" not in src  # net off → no web evidence (honest fallback)


# ── the gathered evidence is injected into the generation prompt ─────────────
def _capture_doc_prompt(monkeypatch, evidence, sources):
    import eli.cognition.gguf_inference as g
    captured = {}
    monkeypatch.setattr(g, "load_model", lambda *a, **k: object())
    def fake_chat(user_prompt, system=None, **k):
        captured["user"] = user_prompt
        return "# Doc\n\n" + ("Substantive grounded body content here. " * 60)
    monkeypatch.setattr(g, "chat_completion", fake_chat)
    monkeypatch.setattr(E, "_gather_generation_evidence",
                        lambda *a, **k: (evidence, sources))
    monkeypatch.setenv("ELI_ARTIFACTS_DIR", tempfile.mkdtemp())
    monkeypatch.setenv("ELI_TEST_MODE", "0")  # exercise the real (mocked) generation path
    E.execute("GENERATE_DOCUMENT", {"topic": "proposals for upgrades for yourself",
                                    "_raw_user_text": "x", "format": "md"})
    return captured.get("user", "")


def test_gathered_evidence_injected_into_prompt(monkeypatch):
    u = _capture_doc_prompt(monkeypatch, "AGENT BUS has 14 agents; reasoning modes are 5.",
                            ["file_code.repo_scan", "blueprints/what_eli_is.md"])
    assert u
    assert "EVIDENCE — gathered by ELI's own agents" in u
    assert "AGENT BUS has 14 agents" in u
    assert "file_code.repo_scan" in u
    assert "Do NOT pad with generic advice" in u


def test_no_evidence_triggers_honest_fallback(monkeypatch):
    u = _capture_doc_prompt(monkeypatch, "", [])
    assert u
    assert "No external evidence could be gathered" in u
