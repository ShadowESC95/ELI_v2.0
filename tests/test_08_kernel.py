"""
test_08_kernel.py
=================
Tests for eli.kernel — engine, world_model, scheduler, self_upgrade, pipeline.
"""
import importlib
import pytest


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


