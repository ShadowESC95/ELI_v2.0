"""Unified self-maintenance orchestration tests."""
from __future__ import annotations

import pytest


def test_maintenance_config_defaults():
    from eli.runtime.self_maintenance_config import (
        ANALYSIS_MIN_CLUSTER,
        DEFAULT_ANALYSIS_DAYS,
        PATCH_MIN_CLUSTER,
    )

    assert DEFAULT_ANALYSIS_DAYS == 14
    assert ANALYSIS_MIN_CLUSTER == 1
    assert PATCH_MIN_CLUSTER == 2


def test_run_maintenance_cycle_analyze_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path))
    from eli.runtime.self_maintenance import run_maintenance_cycle

    out = run_maintenance_cycle(mode="analyze", days=14)
    assert out["mode"] == "analyze"
    assert "Improvement cycle complete" in out["content"]
    assert out["failure_count"] == out["failure_count"]  # numeric


def test_generate_patch_routes_to_self_improve_propose():
    from eli.execution.router_enhanced import route

    intent = route("generate patch for eli")
    assert intent.get("action") == "SELF_IMPROVE"
    assert (intent.get("args") or {}).get("mode") == "propose"


def test_self_maintenance_help_surface():
    from eli.runtime.self_maintenance import maintenance_surface_help

    text = maintenance_surface_help()
    assert "self analyse" in text
    assert "self fix" in text
    assert "14 days" in text
