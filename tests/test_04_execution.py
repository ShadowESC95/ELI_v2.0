"""
test_04_execution.py
====================
Tests for eli.execution — router, executor, intent packets, authority.
"""
import importlib
import pytest


def test_execution_package_init():
    mod = importlib.import_module("eli.execution")
    assert mod is not None


def test_execution_router_has_class():
    mod = importlib.import_module("eli.execution.router_enhanced")
    syms = dir(mod)
    # Module is function-based: check for the public route callable
    matches = [s for s in syms if "route" in s.lower() or "Router" in s]
    assert matches, f"No route function in router_enhanced.py: {syms}"


def test_execution_executor_has_class():
    mod = importlib.import_module("eli.execution.executor_enhanced")
    syms = dir(mod)
    matches = [s for s in syms if "Executor" in s or "executor" in s.lower()]
    assert matches, f"No Executor class in executor_enhanced.py: {syms}"


def test_execution_intent_packets_loadable():
    mod = importlib.import_module("eli.execution.execution_intent_packets")
    assert mod is not None


def test_execution_planner_loadable():
    mod = importlib.import_module("eli.execution.execution_planner")
    assert mod is not None


def test_execution_plugin_handlers_loadable():
    mod = importlib.import_module("eli.execution.executor_plugin_handlers")
    assert mod is not None


def test_execution_operator_actions_loadable():
    mod = importlib.import_module("eli.execution.operator_actions")
    assert mod is not None


def test_execution_operator_policy_loadable():
    mod = importlib.import_module("eli.execution.operator_policy")
    assert mod is not None


def test_execution_route_authority_loadable():
    mod = importlib.import_module("eli.execution.route_authority")
    assert mod is not None


def test_execution_router_plugin_intents_loadable():
    mod = importlib.import_module("eli.execution.router_plugin_intents")
    assert mod is not None


def test_execution_tool_execution_authority_loadable():
    mod = importlib.import_module("eli.execution.tool_execution_authority")
    assert mod is not None


def test_execution_cross_import_router_executor():
    """Router and executor should share no circular deps."""
    router = importlib.import_module("eli.execution.router_enhanced")
    executor = importlib.import_module("eli.execution.executor_enhanced")
    assert router and executor
