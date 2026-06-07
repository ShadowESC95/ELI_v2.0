"""CLAIM: the headline structural facts hold — the 14-agent bus, 5 reasoning
modes, 12 main GUI tabs, 4 SQLite stores, and the load-bearing callables the
blueprints describe (netguard, evidence-planner, report-pipeline, autonomy ticks,
grounding gate, etc.) all actually exist and are wired.
"""
from __future__ import annotations

import importlib

import pytest

from . import _helpers as H

# ── 14 bus agents ────────────────────────────────────────────────────────────
_EXPECTED_AGENTS = [
    "memory", "knowledge_graph", "system", "habit", "self_improvement",
    "proactive", "frontier", "plugin", "capability", "voice", "orchestrator",
    "file_code", "introspection", "reflection",
]


@pytest.mark.parametrize("name", _EXPECTED_AGENTS, ids=_EXPECTED_AGENTS)
def test_bus_agent_registered(name):
    from eli.cognition.agent_bus import _ALL_AGENTS
    names = {getattr(a, "name", "") for a in _ALL_AGENTS}
    assert name in names, f"bus agent '{name}' not registered"


def test_bus_has_at_least_14_agents():
    from eli.cognition.agent_bus import _ALL_AGENTS
    assert len(_ALL_AGENTS) >= 14


# ── 5 reasoning modes ────────────────────────────────────────────────────────
_MODES = {
    "quick": "Quick", "chain_of_thought": "Normal", "self_consistency": "Advanced",
    "tree_of_thoughts": "Research", "constitutional_ai": "Expert",
}


@pytest.mark.parametrize("key,display", list(_MODES.items()), ids=list(_MODES))
def test_reasoning_mode_display(key, display):
    from eli.cognition.reasoning_modes import mode_display
    assert mode_display(key) == display


# ── 12 main GUI tabs (static source check — no Qt needed) ────────────────────
_TAB_CREATORS = [
    "create_chat_tab", "create_proactive_tab", "create_image_tab",
    "create_quick_actions_tab", "create_screen_control_tab", "create_files_tab",
    "create_labs_tab", "create_coding_tab", "create_tasks_tab",
    "create_report_builder_tab", "create_eli_world_tab", "create_settings_tab",
]
_GUI_SRC = (H.REPO / "eli" / "gui" / "eli_pro_audio_gui_MKI.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("creator", _TAB_CREATORS, ids=_TAB_CREATORS)
def test_main_tab_creator_defined_and_called(creator):
    assert f"def {creator}(" in _GUI_SRC, f"{creator} not defined"
    assert f"self.{creator}()" in _GUI_SRC, f"{creator} not called in init"


# ── 4 SQLite stores ──────────────────────────────────────────────────────────
_DBS = ["user.sqlite3", "agent.sqlite3", "system_index.sqlite3", "coding_memory.sqlite3"]


@pytest.mark.parametrize("db", _DBS, ids=_DBS)
def test_sqlite_store_present(db):
    assert (H.REPO / "artifacts" / "db" / db).exists(), f"{db} missing"


# ── load-bearing callables the blueprints describe ───────────────────────────
_CALLABLES = [
    ("eli.core.config", "network_allowed"),
    ("eli.runtime.evidence_planner", "plan_channels"),
    ("eli.runtime.evidence_planner", "gather"),
    ("eli.runtime.evidence_planner", "plan_and_gather"),
    ("eli.runtime.report_pipeline", "generate_document"),
    ("eli.runtime.report_pipeline", "enabled"),
    ("eli.runtime.grounding_escalation", "escalate"),
    ("eli.runtime.code_examiner", "examine"),
    ("eli.runtime.code_examiner", "resolve_targets"),
    ("eli.runtime.scheduled_tasks", "restore_scheduled_tasks"),
    ("eli.runtime.scheduled_tasks", "schedule_request"),
    ("eli.runtime.background_deepening", "schedule"),
    ("eli.runtime.state_providers", "capture_all"),
    ("eli.runtime.active_project", "get_active"),
    ("eli.planning.autonomy_controller", "safe_tick"),
    ("eli.planning.autonomy_controller", "safe_goal_tick"),
    ("eli.planning.autonomy_controller", "safe_scheduler_tick"),
    ("eli.planning.habits", "detect_habits"),
    ("eli.cognition.agent_bus", "get_bus"),
    ("eli.cognition.reasoning_modes", "canonical_mode"),
    ("eli.core.dag", "build_dag"),
    ("eli.core.model_tier", "detect_tier"),
    ("eli.tools.registry.capabilities_doc", "generate_capabilities_doc"),
    ("eli.tools.registry.capability_updater", "update_capability_manifest"),
    ("eli.memory.memory", "get_memory"),
]


@pytest.mark.parametrize("module,attr", _CALLABLES, ids=[f"{m}.{a}" for m, a in _CALLABLES])
def test_callable_exists(module, attr):
    mod = importlib.import_module(module)
    fn = getattr(mod, attr, None)
    assert callable(fn), f"{module}.{attr} is missing or not callable"


# ── a few behavioural claims ─────────────────────────────────────────────────
def test_netguard_offline_is_fail_closed():
    # The offline-by-default claim: when network is not allowed, WEB_SEARCH no-ops.
    import eli.core.config as C
    orig = C.network_allowed
    try:
        C.network_allowed = lambda: False
        from eli.execution.executor_enhanced import _execute_impl
        r = _execute_impl("WEB_SEARCH", {"query": "x"})
        assert r.get("offline") or not r.get("web_grounded"), "web search ran while offline"
    finally:
        C.network_allowed = orig


def test_evidence_planner_channels_are_known():
    from eli.runtime.evidence_planner import KNOWN_CHANNELS
    assert set(KNOWN_CHANNELS) == {"code", "web", "memory", "runtime"}


def test_report_pipeline_default_enabled():
    from eli.runtime.report_pipeline import enabled
    assert enabled() is True
