"""
test_08_kernel.py
=================
Tests for eli.kernel — engine, world_model, scheduler, self_upgrade, pipeline.
"""
import importlib
import pytest


def test_kernel_package_init():
    assert importlib.import_module("eli.kernel") is not None


def test_kernel_engine_has_class():
    mod = importlib.import_module("eli.kernel.engine")
    syms = dir(mod)
    matches = [s for s in syms if "Engine" in s]
    assert matches, f"No Engine class in kernel/engine.py: {syms}"


def test_kernel_world_model_has_class():
    mod = importlib.import_module("eli.kernel.world_model")
    syms = dir(mod)
    matches = [s for s in syms if "World" in s or "Model" in s]
    assert matches, f"No WorldModel class: {syms}"


def test_kernel_pipeline_loadable():
    assert importlib.import_module("eli.kernel.pipeline") is not None


def test_kernel_scheduler_loadable():
    assert importlib.import_module("eli.kernel.scheduler") is not None


def test_kernel_self_upgrade_loadable():
    assert importlib.import_module("eli.kernel.self_upgrade") is not None


def test_kernel_state_loadable():
    assert importlib.import_module("eli.kernel.state") is not None


def test_kernel_task_bus_loadable():
    assert importlib.import_module("eli.kernel.task_bus") is not None


def test_kernel_verify_dual_models_loadable():
    assert importlib.import_module("eli.kernel.verify_dual_models") is not None
