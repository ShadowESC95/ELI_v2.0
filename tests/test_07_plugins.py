"""
test_07_plugins.py
==================
Tests for eli.plugins — manager, base, all plugin packages.
"""
import importlib
import pytest


PLUGIN_NAMES = [
    "calendar", "document_reader", "media", "notes",
    "pomodoro", "smart_home", "system_stats", "tts",
    "weather", "web", "web_automation",
]


def test_plugins_package_init():
    assert importlib.import_module("eli.plugins") is not None


def test_plugins_manager_has_class():
    mod = importlib.import_module("eli.plugins.manager")
    syms = dir(mod)
    matches = [s for s in syms if "Manager" in s or "Plugin" in s]
    assert matches, f"No PluginManager class in manager.py: {syms}"


def test_plugins_base_has_base_class():
    mod = importlib.import_module("eli.plugins.base.base")
    syms = dir(mod)
    matches = [s for s in syms if "Base" in s or "Plugin" in s]
    assert matches, f"No base plugin class: {syms}"


@pytest.mark.parametrize("plugin", PLUGIN_NAMES, ids=PLUGIN_NAMES)
def test_plugin_package_importable(plugin):
    pkg = importlib.import_module(f"eli.plugins.{plugin}")
    assert pkg is not None


@pytest.mark.parametrize("plugin", PLUGIN_NAMES, ids=PLUGIN_NAMES)
def test_plugin_module_importable(plugin):
    mod = importlib.import_module(f"eli.plugins.{plugin}.plugin")
    assert mod is not None


@pytest.mark.parametrize("plugin", PLUGIN_NAMES, ids=PLUGIN_NAMES)
def test_plugin_has_plugin_class(plugin):
    mod = importlib.import_module(f"eli.plugins.{plugin}.plugin")
    syms = dir(mod)
    # Accept: a class with Plugin/plugin-name in its name, OR the standard
    # function-based plugin API (execute, PLUGIN_ID, ACTIONS)
    matches = [
        s for s in syms
        if "Plugin" in s
        or plugin.replace("_", "").capitalize() in s
        or s in ("execute", "PLUGIN_ID", "ACTIONS", "run", "handle")
    ]
    assert matches, f"No Plugin class or execute() in {plugin}/plugin.py: {syms}"


def test_plugins_registry_index_exists():
    import os
    idx = os.path.join(
        importlib.import_module("eli.plugins").__file__,
        "..", "registry", "index.json"
    )
    idx = os.path.normpath(idx)
    assert os.path.isfile(idx), f"Plugin registry index.json missing at {idx}"
