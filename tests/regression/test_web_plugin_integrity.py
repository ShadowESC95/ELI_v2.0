import importlib


def test_web_plugin_declares_canonical_action():
    mod = importlib.import_module("eli.plugins.web.plugin")

    assert "WEB_SEARCH" in getattr(mod, "ACTIONS", [])

    plugin = mod.WebSearchPlugin()
    keys = {str(k).upper() for k in plugin.actions.keys()}

    assert "WEB_SEARCH" in keys


def test_web_plugin_rejects_empty_query_without_network():
    mod = importlib.import_module("eli.plugins.web.plugin")

    plugin = mod.WebSearchPlugin()
    result = plugin.web_search({})

    assert result["ok"] is False
    assert result["action"] == "WEB_SEARCH"
    assert "query" in result["error"].lower()


def test_web_plugin_execute_aliases():
    mod = importlib.import_module("eli.plugins.web.plugin")

    result = mod.execute("WEB_SEARCH", {})
    assert result["ok"] is False
    assert result["action"] == "WEB_SEARCH"

    result = mod.execute("web_search", {})
    assert result["ok"] is False
    assert result["action"] == "WEB_SEARCH"
