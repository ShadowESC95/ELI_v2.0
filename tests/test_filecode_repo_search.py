"""file_code agent: real repo-wide search (not just the ~14 curated files).
Deterministic — no model."""
from __future__ import annotations
import pytest
from eli.cognition.agent_bus import FileCodeAgent, _filecode_extract_terms

A = FileCodeAgent()


def _files_for(q):
    r = A.run(q, {"action": "CHAT"}, "s", "u")
    return {s.split(":")[0] for s in (r.data or {}).get("snippets", [])}


@pytest.mark.parametrize("q,needle", [
    ("how does netguard work", "core/netguard.py"),
    ("what's in persona_updater.py", "cognition/persona_updater.py"),
    ("where is the habit scheduler", "planning/habits_scheduler.py"),
    ("explain tts_router", "perception/tts_router.py"),
    ("crisis guard code", "core/crisis_guard.py"),
    ("what files handle the knowledge graph", "memory/knowledge_graph.py"),
    ("tell me about the gaze engine", "perception/gaze_engine.py"),
])
def test_finds_files_outside_the_curated_map(q, needle):
    files = _files_for(q)
    assert any(f.endswith(needle) for f in files), f"{needle} not in {files}"


def test_non_code_chat_is_skipped():
    r = A.run("hello how are you today", {"action": "CHAT"}, "s", "u")
    assert (r.data or {}).get("skipped") is True


def test_term_extraction_ignores_stopwords():
    assert _filecode_extract_terms("hello how are you") == set()
    assert "persona_updater" in _filecode_extract_terms("read persona_updater.py")
