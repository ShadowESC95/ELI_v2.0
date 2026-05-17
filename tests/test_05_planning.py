"""
test_05_planning.py
===================
Tests for eli.planning — goals, habits, proposals, autonomy, proactive daemon.
"""
import importlib
import pytest


def test_planning_package_init():
    mod = importlib.import_module("eli.planning")
    assert mod is not None


def test_planning_goal_models_has_dataclass():
    mod = importlib.import_module("eli.planning.goal_models")
    syms = dir(mod)
    matches = [s for s in syms if "Goal" in s]
    assert matches, f"No Goal model in goal_models.py: {syms}"


def test_planning_goal_store_loadable():
    mod = importlib.import_module("eli.planning.goal_store")
    assert mod is not None


def test_planning_goal_tick_loadable():
    mod = importlib.import_module("eli.planning.goal_tick")
    assert mod is not None


def test_planning_habits_loadable():
    mod = importlib.import_module("eli.planning.habits")
    assert mod is not None


def test_planning_habits_scheduler_loadable():
    mod = importlib.import_module("eli.planning.habits_scheduler")
    assert mod is not None


def test_planning_habits_state_loadable():
    mod = importlib.import_module("eli.planning.habits_state")
    assert mod is not None


def test_planning_attention_queue_loadable():
    mod = importlib.import_module("eli.planning.attention_queue")
    assert mod is not None


def test_planning_autonomy_controller_loadable():
    mod = importlib.import_module("eli.planning.autonomy_controller")
    assert mod is not None


def test_planning_autonomy_scheduler_loadable():
    mod = importlib.import_module("eli.planning.autonomy_scheduler")
    assert mod is not None


def test_planning_jobqueue_loadable():
    mod = importlib.import_module("eli.planning.jobqueue")
    assert mod is not None


def test_planning_jobq_loadable():
    mod = importlib.import_module("eli.planning.jobq")
    assert mod is not None


def test_planning_jobqueue_cli_loadable():
    mod = importlib.import_module("eli.planning.jobqueue_cli")
    assert mod is not None


def test_planning_proactive_daemon_has_class():
    mod = importlib.import_module("eli.planning.proactive_daemon")
    syms = dir(mod)
    matches = [s for s in syms if "Daemon" in s or "Proactive" in s]
    assert matches, f"No daemon class in proactive_daemon.py: {syms}"


def test_planning_proposal_models_loadable():
    mod = importlib.import_module("eli.planning.proposal_models")
    assert mod is not None


def test_planning_proposal_queue_loadable():
    mod = importlib.import_module("eli.planning.proposal_queue")
    assert mod is not None


def test_planning_proposal_adapters_loadable():
    mod = importlib.import_module("eli.planning.proposal_adapters")
    assert mod is not None


def test_planning_proposal_memory_bridge_loadable():
    mod = importlib.import_module("eli.planning.proposal_memory_bridge")
    assert mod is not None


def test_planning_operator_goal_actions_loadable():
    mod = importlib.import_module("eli.planning.operator_goal_actions")
    assert mod is not None


def test_planning_agent_loop_loadable():
    mod = importlib.import_module("eli.planning.agent_loop")
    assert mod is not None


def test_planning_task_planner_loadable():
    mod = importlib.import_module("eli.planning.task_planner")
    assert mod is not None


def test_planning_db_paths_loadable():
    mod = importlib.import_module("eli.planning.db_paths")
    assert mod is not None
