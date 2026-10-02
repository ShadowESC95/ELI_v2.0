"""CLAIM: headline marketing copy in README / persona matches mechanisms in code.

Numbers are covered by ``test_readme_counts.py`` and ``test_capability_manifest.py``.
This file checks *mechanism* claims — the sort of drift where a feature is real but
the docs describe the wrong implementation (or a retired one).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from . import _helpers as H

REPO = H.REPO
README = (REPO / "README.md").read_text(encoding="utf-8")
PERSONA = (REPO / "eli" / "cognition" / "persona.txt").read_text(encoding="utf-8")


def _builtin_agent_count() -> int:
    """_ALL_AGENTS is a process-wide mutable global that several OTHER tests
    legitimately append custom/spec agents to (test_custom_agent_integration.
    py, test_agent_dispatch_persist.py) — tagged _custom=True, same as a real
    user-installed custom agent would be. The "15 specialist agents" claim is
    about the BUILT-IN roster this ships with, not whatever a given process
    has loaded — live bug (2026-10-02): this file failed under the full suite
    (16, not 15) purely from test run order/global-state leakage elsewhere,
    not a real marketing-claim drift. Filtering to non-custom agents tests
    the actual claim regardless of what else has run in this process."""
    from eli.cognition.agent_bus import _ALL_AGENTS
    return sum(1 for a in _ALL_AGENTS if not getattr(a, "_custom", False))


def test_fifteen_bus_agents_registered():
    n = _builtin_agent_count()
    assert n == 15, f"marketing says 15 agents; built-in _ALL_AGENTS has {n}"


def test_persona_agent_count_matches_bus():
    m = re.search(r"(\d+)\s+specialist agents", PERSONA)
    assert m, "persona.txt should state specialist agent count"
    assert int(m.group(1)) == _builtin_agent_count()


def test_twelve_stage_pipeline_stages_exist():
    from eli.kernel import pipeline_trace as pt
    stages = set(getattr(pt, "STAGE_NAMES", {}).values())
    assert len(stages) == 12
    assert "PERCEIVE_INGEST" in stages
    assert "LEARNING_STATE_UPDATE" in stages


def test_five_reasoning_modes_public_layer():
    from eli.cognition.reasoning_modes import mode_display
    for key, label in (
        ("quick", "Quick"),
        ("chain_of_thought", "Normal"),
        ("self_consistency", "Advanced"),
        ("tree_of_thoughts", "Research"),
        ("constitutional_ai", "Expert"),
    ):
        assert mode_display(key) == label


def test_shell_gate_is_denylist_not_allowlist():
    src = (REPO / "eli" / "execution" / "shell_gate.py").read_text(encoding="utf-8")
    assert "_DENIED_EXECUTABLES" in src
    assert "_BLOCKED_PATTERNS" in src
    assert "allowlist" not in src.lower() or "denylist" in src.lower()


def test_netguard_socket_guard_exists():
    from eli.core.netguard import should_block_network
    assert callable(should_block_network)


def test_server_default_port_is_8081_not_8502():
    src = (REPO / "api" / "server.py").read_text(encoding="utf-8")
    assert "8081" in src
    assert "8502" not in src


def test_no_pynvml_dependency():
    for req in ("requirements-full.txt", "requirements.lock.txt", "pyproject.toml"):
        p = REPO / req
        if p.exists():
            assert "pynvml" not in p.read_text(encoding="utf-8").lower()


def test_piper_voice_index_claim_has_code_anchor():
    src = (REPO / "eli" / "runtime" / "voice_assets.py").read_text(encoding="utf-8")
    assert "166" in src and "45" in src
    assert "voices.json" in src


def test_wake_word_training_hook_exists():
    src = (REPO / "eli" / "perception" / "audio_stt.py").read_text(encoding="utf-8")
    assert "wake" in src.lower()
    assert "retrain" in src.lower() or "enroll" in src.lower()


def test_gender_matched_tts_fallback_exists():
    src = (REPO / "eli" / "perception" / "tts_router.py").read_text(encoding="utf-8")
    assert "gender" in src.lower() and "fallback" in src.lower()


def test_custom_agent_loader_exists():
    src = (REPO / "eli" / "cognition" / "agent_bus.py").read_text(encoding="utf-8")
    assert "SpecAgent" in src
    assert "_load_custom_agents" in src or "custom agents" in src.lower()


def test_hyde_query_expansion_module_exists():
    from eli.cognition.hyde import expand_query_hyde
    assert callable(expand_query_hyde)


def test_lora_train_action_in_manifest():
    actions = {c["action"] for c in H.capabilities()}
    assert "LORA_TRAIN" in actions


def test_readme_does_not_claim_quick_skips_orchestrator():
    """Since v2.3.37 Quick still runs the gradient orchestrator — lighter, not absent."""
    features = README.split("## Features", 1)[-1].split("## Optional", 1)[0].lower()
    bad = (
        "quick-only bypass",
        "quick skips",
        "quick = bus only",
        "quick mode skips",
        "14-agent",
    )
    for phrase in bad:
        assert phrase not in features, f"README Features still claims '{phrase}'"


def test_readme_does_not_call_retrieval_twelve_stage_pipeline():
    """The 12-stage label belongs to cognition (S01–S12), not the retrieval substeps."""
    assert "12-stage retrieval pipeline" not in README.lower()


@pytest.mark.parametrize("fmt", ["pdf", "docx", "odt", "epub"])
def test_readme_document_formats_are_dispatched(fmt):
    if fmt not in README.lower():
        pytest.skip(f"{fmt} not mentioned in README")
    src = (REPO / "eli" / "plugins" / "document_reader" / "plugin.py").read_text(encoding="utf-8")
    assert f'".{fmt}"' in src, f"README mentions {fmt} but document_reader does not dispatch it"
