"""Generation grounding: clean topic parsing + the evidence-planner (hybrid DAG).

User-reported (2026-06-07): document/script generation ran with NO evidence-
gathering, so every topic came back generic. The fix is a hybrid evidence
planner+gatherer (eli/runtime/evidence_planner.py): the planner intuits which
evidence channels a task needs (model proposal + deterministic floor), the real
agents/tools gather them, and the generator synthesises from that. Wired centrally
in _execute_impl for every generative action, mode-aware.

Deterministic — the model and heavy sources are mocked; routing + injection tested.
"""
from __future__ import annotations

import tempfile

import pytest

from eli.execution.router_enhanced import route
import eli.execution.executor_enhanced as E
import eli.runtime.evidence_planner as EP


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
    assert b and "ELI" in b and "local" in b.lower()


# ── planner: deterministic floor picks the right channel per topic ───────────
@pytest.mark.parametrize("query,expected", [
    ("proposals for upgrades for ELI itself", "code"),
    ("my research framework", "memory"),
    ("the history of rome", "web"),
])
def test_planner_floor_routes_channel(query, expected):
    chans = EP.plan_channels("GENERATE_DOCUMENT", query, mode="quick")
    assert expected in chans


def test_planner_quick_mode_skips_model(monkeypatch):
    # quick mode must NOT make a model call (keeps the hot path fast)
    called = {"n": 0}
    monkeypatch.setattr(EP, "_model_channels", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or [])
    EP.plan_channels("GENERATE_DOCUMENT", "the history of rome", mode="quick")
    assert called["n"] == 0


def test_planner_deep_mode_uses_model(monkeypatch):
    monkeypatch.setattr(EP, "_model_channels", lambda *a, **k: ["runtime"])
    chans = EP.plan_channels("GENERATE_DOCUMENT", "the history of rome", mode="tree_of_thoughts")
    assert "runtime" in chans  # model proposal merged in


# ── gather: each channel runs the real agent/tool ────────────────────────────
def test_gather_external_uses_web(monkeypatch):
    import eli.core.config as C
    import eli.plugins.web.plugin as W
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    monkeypatch.setattr(W, "_web_search_results",
                        lambda q, max_results=5: [{"title": "Rome", "href": "http://x",
                                                   "body": "Ancient Rome founded 753 BC"}])
    ev, src = EP.gather(["web"], "the history of rome")
    assert "web_search" in src and "Ancient Rome" in ev


def test_gather_personal_uses_memory(monkeypatch):
    class _FM:
        def recall_memory(self, q, limit=10, keyword_only=False):
            return [{"text": "User's research framework is the field-coherence model."}]
    import eli.memory as _mem
    monkeypatch.setattr(_mem, "get_memory", lambda: _FM())
    ev, src = EP.gather(["memory"], "my research framework")
    assert "memory.recall" in src and "field-coherence" in ev


def test_gather_code_includes_real_analysis():
    # code channel must include the real architecture grounding at minimum
    ev, src = EP.gather(["code"], "proposals for upgrades for ELI itself", mode="quick")
    assert ev and ("blueprints" in src or "code_examiner" in src or "file_code" in src)


def test_evidence_planner_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ELI_EVIDENCE_PLANNER", "0")
    ev, src = EP.plan_and_gather("GENERATE_DOCUMENT", "anything", "quick")
    assert ev == "" and src == []


# ── the gathered evidence is injected + consumed by the generator ────────────
def _capture_doc_prompt(monkeypatch, evidence, sources):
    import eli.cognition.gguf_inference as g
    captured = {}
    monkeypatch.setattr(g, "load_model", lambda *a, **k: object())
    def fake_chat(user_prompt, system=None, **k):
        captured["user"] = user_prompt
        return "# Doc\n\n" + ("Substantive grounded body content here. " * 60)
    monkeypatch.setattr(g, "chat_completion", fake_chat)
    # central hook calls plan_and_gather → stub it deterministically
    monkeypatch.setattr(EP, "plan_and_gather", lambda *a, **k: (evidence, sources))
    monkeypatch.setenv("ELI_ARTIFACTS_DIR", tempfile.mkdtemp())
    monkeypatch.setenv("ELI_TEST_MODE", "0")
    # These tests assert the single-pass evidence-injection (the fallback prompt);
    # disable the multi-stage pipeline so chat_completion gets that exact prompt.
    monkeypatch.setenv("ELI_DOC_PIPELINE", "0")
    E.execute("GENERATE_DOCUMENT", {"topic": "proposals for upgrades for yourself",
                                    "_raw_user_text": "x", "format": "md"})
    return captured.get("user", "")


def test_gathered_evidence_injected_into_prompt(monkeypatch):
    u = _capture_doc_prompt(monkeypatch, "AGENT BUS has 14 agents; reasoning modes are 5.",
                            ["code_examiner", "blueprints"])
    assert u and "EVIDENCE — gathered by ELI's own agents" in u
    assert "AGENT BUS has 14 agents" in u and "code_examiner" in u
    assert "Do NOT pad with generic advice" in u


def test_no_evidence_triggers_honest_fallback(monkeypatch):
    u = _capture_doc_prompt(monkeypatch, "", [])
    assert u and "No external evidence could be gathered" in u
