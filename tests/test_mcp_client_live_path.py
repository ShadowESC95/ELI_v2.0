"""The live MCP client must honour the enabled flag and launch through the sandbox,
as the install-time probe does."""
from __future__ import annotations

import json
import sys
import textwrap

import pytest

FAKE_SERVER = textwrap.dedent('''
    import json, sys
    def send(o):
        sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            send({"jsonrpc":"2.0","id":i,"result":{
                "protocolVersion":"2025-06-18","capabilities":{"tools":{}},
                "serverInfo":{"name":"demo","version":"0.1.0"}}})
        elif m == "tools/list":
            send({"jsonrpc":"2.0","id":i,"result":{"tools":[
                {"name":"read_file","description":"Read a file"}]}})
        elif m == "tools/call":
            send({"jsonrpc":"2.0","id":i,"result":{
                "content":[{"type":"text","text":"ok"}]}})
''')


@pytest.fixture()
def server_script(tmp_path):
    p = tmp_path / "fake_mcp.py"
    p.write_text(FAKE_SERVER, encoding="utf-8")
    return p


@pytest.fixture()
def cfg(tmp_path, monkeypatch, server_script):
    """A config with one server, written directly (bypassing install_server)
    so each test controls `enabled` explicitly."""
    def _write(enabled: bool, **extra):
        path = tmp_path / "mcp_servers.json"
        monkeypatch.setenv("ELI_MCP_CONFIG", str(path))
        entry = {"command": sys.executable, "args": [str(server_script)],
                 "enabled": enabled, **extra}
        path.write_text(json.dumps({"mcpServers": {"demo": entry}}), encoding="utf-8")
        return path
    return _write


@pytest.fixture(autouse=True)
def _reset_live_sessions():
    """_SESSIONS is a module-level cache keyed by server name; a leaked live
    process from one test must not answer for the next one."""
    from eli.integrations.mcp import client
    yield
    with client._LOCK:
        for sess in client._SESSIONS.values():
            sess.stop()
        client._SESSIONS.clear()


# ── the enabled gate ─────────────────────────────────────────────────────────

def test_a_disabled_server_is_never_launched(cfg):
    from eli.integrations.mcp import client
    cfg(enabled=False)
    result = client.call_tool("demo.read_file", {})
    assert result["ok"] is False
    assert "disabled" in result["error"].lower()
    with client._LOCK:
        assert "demo" not in client._SESSIONS or not client._SESSIONS["demo"].alive(), \
            "a disabled server's process must never actually start"


def test_a_never_enabled_server_missing_the_key_entirely_is_treated_as_disabled(cfg):
    """A hand-pasted config (the module's own docstring example) has no
    `enabled` key at all -- absence must not be trusted as consent, matching
    install_server()'s own "disabled by default" philosophy."""
    from eli.integrations.mcp import client
    path = cfg(enabled=False)
    data = json.loads(path.read_text())
    del data["mcpServers"]["demo"]["enabled"]
    path.write_text(json.dumps(data), encoding="utf-8")
    result = client.call_tool("demo.read_file", {})
    assert result["ok"] is False
    assert "disabled" in result["error"].lower()


def test_a_disabled_server_offers_no_tools(cfg):
    from eli.integrations.mcp import client
    cfg(enabled=False)
    assert client.list_tools() == []


def test_an_enabled_server_still_works(cfg):
    """Positive control: the enabled gate must not block a genuinely enabled,
    genuinely working server."""
    from eli.integrations.mcp import client
    cfg(enabled=True)
    tools = client.list_tools()
    assert {t["name"] for t in tools} == {"read_file"}
    result = client.call_tool("demo.read_file", {})
    assert result["ok"] is True and result["text"] == "ok"


def test_enabling_after_a_refused_start_lets_it_run(cfg):
    """set_enabled(True) must actually change what the LIVE path does, not
    just what the lifecycle module reports."""
    from eli.integrations.mcp import client
    from eli.plugins import mcp as lifecycle
    path = cfg(enabled=False)
    assert client.call_tool("demo.read_file", {})["ok"] is False
    lifecycle.set_enabled("demo", True)
    with client._LOCK:
        client._SESSIONS.pop("demo", None)  # force a fresh session for the new state
    assert client.call_tool("demo.read_file", {})["ok"] is True


# ── containment ──────────────────────────────────────────────────────────────

def test_the_live_launch_goes_through_the_same_sandbox_as_the_install_probe(cfg, monkeypatch):
    """Direct wiring check: _Session.start() must call
    subprocess_sandbox.popen(), not a bare subprocess.Popen(), with the same
    permission derivation probe() uses (network only if declared, cwd/declared
    paths bound for read)."""
    from eli.integrations.mcp import client
    from eli.plugins import subprocess_sandbox

    cfg(enabled=True, permissions=["network"], read_paths=["/tmp"])

    calls = []
    real_popen = subprocess_sandbox.popen

    def _spy(argv, **kwargs):
        calls.append(kwargs)
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(subprocess_sandbox, "popen", _spy)
    result = client.call_tool("demo.read_file", {})

    assert result["ok"] is True, result
    assert len(calls) == 1, "the live launch must route through subprocess_sandbox.popen"
    assert calls[0]["allow_network"] is True, "declared network permission must reach the sandbox"
    assert "/tmp" in calls[0]["read_paths"]


def test_a_server_without_declared_network_is_isolated_on_the_live_path(cfg):
    """Same containment guarantee test_a_server_without_the_network_capability_is_contained
    proves for the install probe (test_plugin_mcp.py), proven here for the path
    that actually runs on every real tool call."""
    from eli.plugins import subprocess_sandbox
    if not subprocess_sandbox.capabilities()["network_isolation"]:
        pytest.skip("no unprivileged sandbox on this platform")
    from eli.integrations.mcp import client

    cfg(enabled=True)  # no "permissions" -> no network declared
    client.call_tool("demo.read_file", {})
    with client._LOCK:
        sess = client._SESSIONS.get("demo")
    assert sess is not None and sess.alive(), "server should have started contained, not failed to start"
