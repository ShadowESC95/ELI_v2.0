"""
test_01_core.py
===============
Tests for eli.core — config, paths, hardware_profile, runtime_settings.
"""
import pytest
import importlib
import os


# ── Module attribute presence ──────────────────────────────────────────────────

def test_core_config_has_config_class():
    mod = importlib.import_module("eli.core.config")
    attrs = dir(mod)
    hits = [a for a in attrs if "config" in a.lower() or "Config" in a]
    assert hits, f"eli.core.config exposes no Config-like symbol. Got: {attrs}"


def test_core_paths_exports_paths():
    mod = importlib.import_module("eli.core.paths")
    attrs = dir(mod)
    path_attrs = [a for a in attrs if "path" in a.lower() or "dir" in a.lower() or "PATH" in a]
    assert path_attrs, f"eli.core.paths exposes no path symbols. Got: {attrs}"


def test_core_db_paths_exposes_paths():
    mod = importlib.import_module("eli.core.db_paths")
    attrs = dir(mod)
    assert any("db" in a.lower() or "path" in a.lower() or "sqlite" in a.lower() for a in attrs), \
        f"eli.core.db_paths looks empty: {attrs}"


# ── Cross-module wiring ────────────────────────────────────────────────────────

def test_core_imports_not_circular():
    """Importing config after paths should not raise circular import errors."""
    paths = importlib.import_module("eli.core.paths")
    config = importlib.import_module("eli.core.config")
    assert paths is not None and config is not None


