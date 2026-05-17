from __future__ import annotations

import re
from pathlib import Path

from eli.kernel.engine import CognitiveEngine


def test_quick_personal_memory_still_returns_direct_visible_text():
    eng = CognitiveEngine()
    out = eng.process(
        "What do you know about me from memory? Give me everything, provide a full and in depth summary.",
        reasoning_mode="quick",
    )

    assert isinstance(out, str)
    assert out.strip()
    assert "{'ok'" not in out[:120]
    assert "memory" in out.lower() or "remember" in out.lower()


def test_quick_routing_fault_still_returns_direct_visible_text():
    eng = CognitiveEngine()
    out = eng.process(
        "Why did you go to the browser instead of answering from memory?",
        reasoning_mode="quick",
    )

    assert isinstance(out, str)
    assert out.strip()
    assert "{'ok'" not in out[:120]
    assert any(term in out.lower() for term in ("browser", "route", "routing", "memory"))


def test_no_live_engine_process_assignment_remains():
    src = Path("eli/kernel/engine.py").read_text(encoding="utf-8", errors="replace")
    live_assignments = [
        line for line in src.splitlines()
        if re.search(r"^\s*CognitiveEngine\.process\s*=", line)
    ]
    assert live_assignments == []
