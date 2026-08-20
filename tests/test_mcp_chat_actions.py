"""Chat commands for add-ons.

Plugin actions already existed (install / uninstall / list / search / enable /
disable) but routed through `manager.install()`, which downloaded over raw urllib
and executed the result — none of the marketplace's verification applied. And MCP
servers had no chat surface at all.

Two rules these tests pin:

  * chat CAN trigger a verified install, because every check still runs;
  * chat can NEVER grant a capability or add an MCP server, because a chat message
    cannot carry informed consent for running a separate program or handing over
    the microphone. Those answer by pointing at the desktop screen.
"""
import pytest

from eli.execution.executor_enhanced import execute
from eli.execution.router_enhanced import route


def _action(reply):
    return reply.get("action") if isinstance(reply, dict) else getattr(reply, "action", None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_MCP_CONFIG", str(tmp_path / "mcp_servers.json"))
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    from eli.core import paths
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    yield


# ── routing ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase,expected", [
    # Runtime half — what live servers expose. Owned by the MCP client.
    ("mcp status", "MCP_STATUS"),
    ("what mcp servers do you have", "MCP_STATUS"),
    ("list my mcp tools", "MCP_TOOLS"),
    ("run the mcp tool read_file", "MCP_CALL"),
    # Lifecycle half — what is configured on this machine.
    ("list my mcp servers", "MCP_LIST"),
    ("show mcp servers", "MCP_LIST"),
    ("mcp doctor", "MCP_DOCTOR"),
    ("why is my mcp not working", "MCP_DOCTOR"),
    ("my mcp server is broken", "MCP_DOCTOR"),
    ("remove the mcp server filesystem", "MCP_REMOVE"),
    ("uninstall mcp filesystem", "MCP_REMOVE"),
    ("add an mcp server filesystem", "MCP_ADD"),
    ("set up mcp", "MCP_ADD"),
])
def test_mcp_phrases_route(phrase, expected):
    assert _action(route(phrase)) == expected


@pytest.mark.parametrize("phrase,expected", [
    ("install plugin pomodoro", "PLUGIN_INSTALL"),
    ("uninstall plugin notes", "PLUGIN_UNINSTALL"),
    ("list installed plugins", "PLUGIN_LIST"),
    ("enable plugin weather", "PLUGIN_ENABLE"),
    ("disable plugin notes", "PLUGIN_DISABLE"),
])
def test_plugin_phrases_still_route(phrase, expected):
    """The MCP block sits above the plugin block; it must not swallow these."""
    assert _action(route(phrase)) == expected


def test_uninstall_mcp_is_not_claimed_by_the_plugin_matcher():
    """`uninstall mcp filesystem` used to become PLUGIN_UNINSTALL of a plugin
    literally named 'mcp'."""
    reply = route("uninstall mcp filesystem")
    args = reply.get("args") if isinstance(reply, dict) else {}
    assert _action(reply) == "MCP_REMOVE"
    assert args.get("server") == "filesystem"


# ── execution ──────────────────────────────────────────────────────────────────

def test_mcp_list_on_a_fresh_machine_explains_itself():
    r = execute("MCP_LIST", {})
    assert r["ok"] is True
    assert "No MCP servers" in r["response"]


def test_mcp_doctor_reports_nothing_configured():
    r = execute("MCP_DOCTOR", {})
    assert "No MCP servers configured" in r["response"]


def test_mcp_remove_of_an_unknown_server_fails_clearly():
    r = execute("MCP_REMOVE", {"server": "nope"})
    assert r["ok"] is False
    assert "nope" in r["response"]


def test_mcp_add_from_chat_defers_to_the_consent_screen():
    """Adding an MCP server runs a separate program. That decision needs the screen
    that states what containment will actually apply on this machine."""
    r = execute("MCP_ADD", {"server": "filesystem"})
    assert "Marketplace" in r["response"]
    assert "separate program" in r["response"]


def test_mcp_remove_needs_an_argument():
    r = execute("MCP_REMOVE", {})
    assert r["ok"] is False


def test_the_two_mcp_halves_stay_distinct():
    """`eli.plugins.mcp` installs and verifies a server; `eli.integrations.mcp.client`
    connects and calls its tools. They share one config file and one shape, and they
    must not claim each other's actions — two effectors registering one action is a
    silent last-one-wins bug."""
    from eli.integrations.mcp import client
    from eli.plugins import mcp as lifecycle
    assert client.config_path() == lifecycle.config_path()


def test_mcp_status_reads_the_runtime_view():
    r = execute("MCP_STATUS", {})
    assert r["ok"] is True
    assert "MCP" in r["response"]


def test_mcp_tools_with_nothing_configured_explains_itself():
    r = execute("MCP_TOOLS", {})
    assert "MCP tools" in r["response"] or "can't see any" in r["response"]


def test_mcp_call_without_a_tool_name_fails_clearly():
    r = execute("MCP_CALL", {})
    assert r["ok"] is False
    assert "which MCP tool" in r["response"]
