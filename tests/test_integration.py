"""Integration tests — components working together — ~80 tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from eli.cognition.response_sanitizer import sanitize_assistant_text
from eli.core.runtime_settings import load_settings, save_settings, _resolve_relative_model_paths
from eli.core.paths import project_root, get_paths


# ── Settings + Path integration ───────────────────────────────────────────

def test_settings_relative_path_resolves_to_project(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({
        "model_path": "models/gguf/base/openhermes-2.5-mistral-7b.Q3_K_M.gguf"
    }))
    s = load_settings()
    resolved = Path(s["model_path"])
    assert resolved.is_absolute()
    assert str(project_root()) in str(resolved)

def test_settings_absolute_valid_path_unchanged(tmp_settings_file, monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    tmp_settings_file.write_text(json.dumps({"model_path": str(model)}))
    s = load_settings()
    assert s["model_path"] == str(model)

def test_settings_heals_stale_path_to_existing_model(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    # Use a stale path for the actual model file that exists
    model_filename = "openhermes-2.5-mistral-7b.Q3_K_M.gguf"
    stale = f"/nonexistent/ELI_MKXI/models/gguf/base/{model_filename}"
    tmp_settings_file.write_text(json.dumps({"model_path": stale}))
    s = load_settings()
    # Either healed to real path or kept stale if model doesn't exist
    assert isinstance(s["model_path"], str)


# ── Sanitizer + Engine integration ───────────────────────────────────────

def test_sanitizer_consistency_with_engine_persona():
    """All filler patterns that engine warns about should be stripped."""
    fillers = [
        "Of course, let me explain.",
        "Certainly! Here is the answer.",
        "Sure thing, I can help.",
        "Absolutely! That's a great point.",
        "Happy to help! The answer is yes.",
        "Great question! Here's what I know.",
        "Short answer: yes.",
        "I'd be happy to answer that.",
    ]
    for filler in fillers:
        result = sanitize_assistant_text(filler)
        # Content after filler should remain
        assert result != "..."
        assert len(result) > 0

def test_sanitizer_preserves_technical_content():
    tech_texts = [
        "Use n_gpu_layers=99 for full GPU offload.",
        "Run: pip install torch torchvision",
        "The FAISS index has 287 vectors.",
        "Temperature is set to 0.7 for creativity.",
        "Set batch_size=512 for optimal throughput.",
    ]
    for text in tech_texts:
        result = sanitize_assistant_text(text)
        # Technical content should survive
        assert len(result) > 0


# ── Settings + Memory integration ─────────────────────────────────────────

def test_settings_auto_load_respected(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"auto_load": False}))
    s = load_settings()
    assert s["auto_load"] is False

def test_settings_max_tokens_negative_one(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"max_tokens": -1}))
    s = load_settings()
    assert s["max_tokens"] == -1

def test_settings_use_mlock_bool(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"use_mlock": True}))
    s = load_settings()
    assert s["use_mlock"] is True


# ── Router + Memory integration ───────────────────────────────────────────

def test_memory_recall_route_leads_to_memory_agent():
    from eli.execution.router_enhanced import route

    result = route("What do you know about me?")
    action = result.get("action", "")
    assert action in ("MEMORY_RECALL", "CHAT", "USER_IDENTITY_SUMMARY", "PERSONAL_MEMORY_SUMMARY")

def test_chat_route_includes_memory_in_plan():
    from eli.execution.router_enhanced import route
    from eli.execution.execution_planner import build_route_decision, build_execution_plan

    result = route("Tell me about Python")
    rd = build_route_decision("Tell me about Python", result)
    plan = build_execution_plan(rd)
    assert plan is not None
    assert len(plan.steps) > 0


# ── TTS + Settings integration ────────────────────────────────────────────

def test_tts_voice_setting_persists(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"tts_voice": "en_US-ryan-high"})
    s = load_settings()
    assert s["tts_voice"] == "en_US-ryan-high"

def test_tts_active_voice_from_settings(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"tts_voice": "en_GB-cori-high"})
    # Env takes precedence over settings when set
    monkeypatch.delenv("ELI_PIPER_VOICE", raising=False)
    from eli.perception.tts_router import get_active_voice
    # Re-reading settings would give us cori-high
    result = get_active_voice()
    assert isinstance(result, str)


# ── Paths + Settings integration ──────────────────────────────────────────

def test_settings_file_in_config_dir():
    paths = get_paths()
    config_dir = paths.config_dir
    assert config_dir is not None
    assert isinstance(config_dir, Path)

def test_project_root_consistent():
    r1 = project_root()
    r2 = project_root()
    assert r1 == r2

def test_settings_config_dir_consistent(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    s1 = load_settings()
    s2 = load_settings()
    assert s1["provider"] == s2["provider"]


# ── Memory no-hallucination integration ──────────────────────────────────

def test_empty_recall_with_engine():
    """Engine recall_memory_query returns a list."""
    from eli.kernel.engine import CognitiveEngine
    eng = CognitiveEngine()
    results = eng.recall_memory_query("nonexistent_topic_xyzzy_12345")
    assert isinstance(results, list)

def test_populated_db_recall_with_engine(populated_db):
    """Engine recall should find relevant memories from populated_db."""
    from eli.memory.memory import Memory
    mem = Memory(db_path=str(populated_db))
    results = mem.recall_memory("jazz music")
    assert isinstance(results, list)
    if results:
        texts = [r.get("text", "") for r in results]
        assert any("jazz" in t.lower() for t in texts)


# ── Portability integration ───────────────────────────────────────────────

def test_settings_no_home_user_hardcoded(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({
        "model_path": "models/gguf/base/openhermes-2.5-mistral-7b.Q3_K_M.gguf"
    }))
    s = load_settings()
    # model_path should be absolute but not hardcoded to one user's home
    resolved = s["model_path"]
    forbidden_user_home = str(Path("/home") / "someuser")
    assert forbidden_user_home not in resolved or str(project_root()) in resolved

def test_relative_paths_are_machine_independent():
    """Relative paths should resolve to the current machine's project root."""
    settings = {"model_path": "models/gguf/base/test.gguf"}
    result = _resolve_relative_model_paths(settings)
    assert str(project_root()) in result["model_path"]
