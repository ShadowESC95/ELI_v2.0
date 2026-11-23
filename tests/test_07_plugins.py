"""
test_07_plugins.py
==================
Tests for eli.plugins — manager, base, all plugin packages.
"""
import importlib
import pytest


PLUGIN_NAMES = [
    "calendar", "document_reader", "media", "notes",
    "pomodoro", "system_stats", "tts",
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


@pytest.mark.parametrize("plugin,cls,act,args,action", [
    ("notes", "QuickNotesPlugin", "list_notes", {}, "LIST_NOTES"),
    ("pomodoro", "PomodoroTimerPlugin", "status", {}, "POMODORO_STATUS"),
    ("system_stats", "SystemStatsPlugin", "ram_usage", {}, "RAM_USAGE"),
    ("tts", "TTSPlugin", "speak", {"text": "plugin check"}, "SPEAK"),
])
def test_a_builtin_plugin_shadowed_by_elis_own_action_runs_that_action(monkeypatch, plugin, cls, act,
                                                                        args, action):
    """These plugins kept second copies of actions the executor answers first, so their own code
    never ran (the pomodoro plugin's end-of-session announcement among it). Each runs ELI's own
    action now: one implementation per action."""
    import eli.perception.tts_router as tts_router
    monkeypatch.setattr(tts_router, "maybe_speak", lambda text, enabled=True: None)
    monkeypatch.setattr(tts_router, "speak_text", lambda text, **kw: {"ok": True, "played_through": "a stand-in"})
    try:  # nothing in a test may speak aloud: the old tts plugin spoke through pyttsx3
        import pyttsx3
        monkeypatch.setattr(pyttsx3, "init", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no speech")))
    except ImportError:
        pass
    inst = getattr(importlib.import_module(f"eli.plugins.{plugin}.plugin"), cls)()
    result = inst.execute(act, args)
    assert result.get("action") == action, result


def test_plugins_registry_index_exists():
    import os
    idx = os.path.join(
        importlib.import_module("eli.plugins").__file__,
        "..", "registry", "index.json"
    )
    idx = os.path.normpath(idx)
    assert os.path.isfile(idx), f"Plugin registry index.json missing at {idx}"


def test_a_new_users_plugin_state_is_not_another_programs(tmp_path, monkeypatch):
    """The plugin state of every ~/.config/eli-* and ~/.eli_* folder (earlier ELI programs, ELI VR, the
    licence keys) was copied in when v2 had none, so a new user started with the plugins another
    program had enabled."""
    import json
    from pathlib import Path
    import eli.plugins.manager as manager
    home = tmp_path / "home"
    other = home / ".config" / "eli-other-program"
    other.mkdir(parents=True)
    (other / "plugins_state.json").write_text(json.dumps({"enabled": ["someone_elses"], "disabled": [],
                                                          "installed": {}}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("ELI_ARTIFACTS_DIR", str(tmp_path / "v2_state"))
    state = json.loads(manager._state_file().read_text(encoding="utf-8"))
    assert state["enabled"] == [] and state["installed"] == {}
