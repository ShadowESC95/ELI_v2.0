"""An installed, enabled plugin's own actions are actually callable.

The marketplace stopped one move short of useful. A plugin could be downloaded,
checksum-verified, scanned by eleven engines, consented to per capability, written
to disk, enabled and imported — and then nothing could invoke it:

  * `Plugin.register()` published actions into `capability_registry`, but that is a
    CATALOGUE. `list_capabilities` backs the docs and compatibility surfaces;
    nothing ever looked a `handler` back up and called it.
  * Registration was driven by `base.load_plugins()`, which enumerates the
    `eli.plugins` **source package** — so a plugin installed into the user's
    plugins directory was never among the ones registered in the first place.
  * And registration ran once at engine start, so nothing installed mid-session
    could work before a restart.

MCP servers were never affected: they have a real dispatch path through
`client.call_tool`. This is the Python-plugin half.
"""
from __future__ import annotations

import json

import pytest


PLUGIN_SRC = '''
from eli.plugins.base.base import Plugin


class GreeterPlugin(Plugin):
    name = "greeter"
    description = "Greets."

    def __init__(self):
        self.actions = {"hello": self.hello, "shout": self.shout}
        super().__init__()

    def hello(self, args):
        who = (args or {}).get("who") or "world"
        return {"ok": True, "content": f"hello {who}"}

    def shout(self, args):
        return "SHOUTING"
'''

SECOND_SRC = '''
from eli.plugins.base.base import Plugin


class RivalPlugin(Plugin):
    name = "rival"
    description = "Also greets."

    def __init__(self):
        self.actions = {"hello": self.hello}
        super().__init__()

    def hello(self, args):
        return {"ok": True, "content": "rival hello"}
'''


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    """A plugins directory holding one enabled plugin, as install() would leave it."""
    import eli.plugins.manager as M

    pdir = tmp_path / "plugins"
    (pdir / "greeter").mkdir(parents=True)
    (pdir / "greeter" / "plugin.py").write_text(PLUGIN_SRC, encoding="utf-8")
    (pdir / "greeter" / "eli_plugin.json").write_text(json.dumps({
        "id": "greeter", "name": "Greeter", "version": "1.0.0",
        "description": "Greets.", "author": "t", "license": "MIT",
        "permissions": []}), encoding="utf-8")

    state = {"enabled": ["greeter"], "disabled": []}
    monkeypatch.setattr(M, "_plugins_dir", lambda: pdir)
    monkeypatch.setattr(M, "_load_state", lambda: dict(state))
    monkeypatch.setattr(M, "_save_state", lambda s: state.update(s))

    mgr = M.PluginManager() if hasattr(M, "PluginManager") else M.get_manager()
    mgr._state = state
    mgr.enable("greeter")
    return mgr, pdir, state


def test_plugin_action_is_dispatchable(installed):
    mgr, _, _ = installed
    res = mgr.dispatch("GREETER_HELLO", {"who": "eli"})
    assert res is not None, "an enabled plugin's action must resolve"
    assert res["ok"] is True
    assert res["content"] == "hello eli"
    assert res["plugin"] == "greeter"


def test_bare_action_name_resolves_when_unambiguous(installed):
    mgr, _, _ = installed
    res = mgr.dispatch("HELLO", {})
    assert res is not None and res["content"] == "hello world"


def test_non_dict_return_is_normalised(installed):
    """A plugin author returning a plain string must not break the caller."""
    mgr, _, _ = installed
    res = mgr.dispatch("GREETER_SHOUT", {})
    assert res["ok"] is True
    assert res["content"] == "SHOUTING" and res["response"] == "SHOUTING"


def test_unknown_action_returns_none_not_an_error(installed):
    """None means 'no plugin claims this', which is what lets the executor fall
    through to its own 'unsupported action' answer instead of masking it."""
    mgr, _, _ = installed
    assert mgr.dispatch("NOT_A_PLUGIN_ACTION", {}) is None


def test_disabled_plugin_is_not_dispatchable(installed):
    mgr, _, state = installed
    state["enabled"] = []
    assert mgr.dispatch("GREETER_HELLO", {}) is None


def test_a_raising_plugin_is_reported_not_propagated(installed, monkeypatch):
    mgr, _, _ = installed
    inst = mgr._loaded["greeter"]

    # Plugin.execute binds handlers as methods (`__get__`), so a stub needs self.
    def boom(self, args):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(inst.actions, "hello", boom)

    res = mgr.dispatch("GREETER_HELLO", {})
    assert res["ok"] is False
    assert "kaboom" in res["content"]


def test_ambiguous_bare_name_is_reported_not_guessed(installed, monkeypatch):
    """Silently picking one of two plugins that both define HELLO is how one
    plugin ends up shadowing another."""
    import eli.plugins.manager as M
    mgr, pdir, state = installed

    (pdir / "rival").mkdir()
    (pdir / "rival" / "plugin.py").write_text(SECOND_SRC, encoding="utf-8")
    state["enabled"] = ["greeter", "rival"]
    mgr._state = state
    mgr.enable("rival")

    res = mgr.dispatch("HELLO", {})
    assert res is not None and res["ok"] is False
    assert "more than one" in res["content"]

    # …but the fully-qualified names still work.
    assert mgr.dispatch("GREETER_HELLO", {})["content"] == "hello world"
    assert mgr.dispatch("RIVAL_HELLO", {})["content"] == "rival hello"


def test_a_plugin_cannot_shadow_a_builtin_action():
    """Dispatch is the LAST stop in the executor. A listing declaring SHUTDOWN or
    SEND_EMAIL must not take that verb over for the whole assistant."""
    import inspect
    from eli.execution import executor_enhanced

    src = inspect.getsource(executor_enhanced._execute_impl)
    tail = src[-2000:]
    assert "get_manager().dispatch" in tail, (
        "plugin dispatch must sit at the end of _execute_impl, after every "
        "built-in handler has had its chance to claim the action")
