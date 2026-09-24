"""ELI as an MCP server: protocol behaviour, control gating, launch config, clean stdout."""
import json
import subprocess
import sys

import pytest

from eli.integrations.mcp import server as srv


@pytest.fixture(autouse=True)
def _no_control(monkeypatch):
    monkeypatch.delenv("ELI_MCP_ALLOW_CONTROL", raising=False)


def _rpc(method, params=None, id_=1):
    return srv.handle({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def test_initialize_reports_the_server_and_version():
    r = _rpc("initialize")["result"]
    assert r["serverInfo"]["name"] == "ELI" and r["protocolVersion"]


def test_notifications_get_no_reply():
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_methods_are_a_protocol_error():
    assert _rpc("nope")["error"]["code"] == -32601


def test_control_actions_are_withheld_by_default(monkeypatch):
    monkeypatch.setattr("eli.execution.executor_enhanced.SUPPORTED_ACTIONS",
                        {"TIME", "SHELL_RUN", "SELF_UPGRADE", "MOUSE_CLICK"}, raising=False)
    names = {t["name"] for t in _rpc("tools/list")["result"]["tools"]}
    assert names == {"TIME"}


def test_control_actions_appear_only_when_allowed(monkeypatch):
    monkeypatch.setattr("eli.execution.executor_enhanced.SUPPORTED_ACTIONS",
                        {"TIME", "SHELL_RUN"}, raising=False)
    monkeypatch.setenv("ELI_MCP_ALLOW_CONTROL", "1")
    names = {t["name"] for t in _rpc("tools/list")["result"]["tools"]}
    assert names == {"TIME", "SHELL_RUN"}


def test_calling_a_withheld_action_is_refused_not_executed(monkeypatch):
    ran = []
    monkeypatch.setattr("eli.execution.executor_enhanced.SUPPORTED_ACTIONS", {"SHELL_RUN"}, raising=False)
    monkeypatch.setattr("eli.execution.executor_enhanced.execute", lambda *a, **k: ran.append(a) or {})
    r = _rpc("tools/call", {"name": "SHELL_RUN", "arguments": {}})["result"]
    assert r["isError"] is True and not ran


def test_an_exposed_action_runs_and_returns_text(monkeypatch):
    monkeypatch.setattr("eli.execution.executor_enhanced.SUPPORTED_ACTIONS", {"TIME"}, raising=False)
    monkeypatch.setattr("eli.execution.executor_enhanced.execute",
                        lambda action, args: {"ok": True, "content": "It is noon."})
    r = _rpc("tools/call", {"name": "TIME", "arguments": {}})["result"]
    assert r["isError"] is False and r["content"][0]["text"] == "It is noon."


def test_connection_config_for_a_source_install(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    entry = srv.connection_config()["mcpServers"]["eli"]
    assert entry["command"] == sys.executable
    assert entry["args"] == ["-m", "eli.integrations.mcp.server"] and "env" not in entry


def test_connection_config_for_the_appimage(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/opt/ELI.AppImage")
    entry = srv.connection_config()["mcpServers"]["eli"]
    assert entry["command"] == "/opt/ELI.AppImage" and entry["args"] == ["--mcp-server"]


def test_the_control_scope_is_carried_in_the_config():
    entry = srv.connection_config(allow_control=True)["mcpServers"]["eli"]
    assert entry["env"] == {"ELI_MCP_ALLOW_CONTROL": "1"}


def test_a_real_process_keeps_stdout_pure_protocol():
    """Importing the executor prints banners and native libs write to fd 1; none of it
    may reach the protocol stream."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    out = subprocess.run(
        [sys.executable, "-m", "eli", "--mcp-server"],
        input="\n".join(json.dumps(m) for m in msgs) + "\n",
        capture_output=True, text=True, timeout=120,
    )
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    assert len(lines) == 2
    replies = [json.loads(l) for l in lines]
    assert replies[0]["id"] == 1 and replies[1]["result"]["tools"]
