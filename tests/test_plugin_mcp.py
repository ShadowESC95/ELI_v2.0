"""An MCP entry must be proven working before it reaches the config.

The four ways MCP installs fail in the wild — wrong config location, missing
runtime, unresolved environment, and nobody checking whether the server answered —
are all silent. Each one leaves an entry that looks installed and does nothing.
These tests pin that ELI catches all four at install time, and that a failed
install leaves the config untouched.
"""
import json
import sys
import textwrap

import pytest

from eli.plugins import mcp


FAKE_SERVER = textwrap.dedent('''
    import json, sys
    def send(o):
        sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
    print("banner noise on stderr", file=sys.stderr)
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
                {"name":"read_file","description":"Read a file"},
                {"name":"list_dir","description":"List a directory"}]}})
''')


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "mcp_servers.json"
    monkeypatch.setenv("ELI_MCP_CONFIG", str(path))
    return path


@pytest.fixture()
def server_script(tmp_path):
    p = tmp_path / "fake_mcp.py"
    p.write_text(FAKE_SERVER, encoding="utf-8")
    return p


def _entry(script, sid="demo"):
    return {"id": sid, "transport": "stdio", "command": sys.executable,
            "args": [str(script)], "permissions": ["filesystem_read"]}


def test_there_is_exactly_one_config_location(cfg):
    assert mcp.config_path() == cfg


def test_install_verifies_by_real_handshake(cfg, server_script):
    res = mcp.install_server(_entry(server_script))
    assert res["ok"], res.get("problems")
    assert res["tool_count"] == 2
    assert {t["name"] for t in res["tools"]} == {"read_file", "list_dir"}


def test_installed_server_lands_in_the_config_disabled(cfg, server_script):
    mcp.install_server(_entry(server_script))
    data = json.loads(cfg.read_text())
    assert "demo" in data["mcpServers"]
    assert data["mcpServers"]["demo"]["enabled"] is False, \
        "being configured is not the same as being allowed to run"
    assert data["mcpServers"]["demo"]["verified"] is True


def test_missing_runtime_fails_before_writing_anything(cfg):
    res = mcp.install_server({"id": "nope", "transport": "stdio",
                              "command": "definitely-not-a-real-binary", "args": []})
    assert res["ok"] is False and res["stage"] == "runtime"
    assert not cfg.exists(), "a failed install must not create a config"


def test_a_process_that_is_not_an_mcp_server_is_rejected(cfg):
    res = mcp.install_server(
        {"id": "notmcp", "transport": "stdio", "command": sys.executable,
         "args": ["-c", "import time; time.sleep(30)"]}, timeout=3)
    assert res["ok"] is False and res["stage"] == "handshake"
    assert not cfg.exists()


def test_non_json_banner_output_does_not_break_the_handshake(cfg, server_script):
    """Real servers print to stderr and sometimes stdout before speaking JSON-RPC."""
    assert mcp.install_server(_entry(server_script))["ok"] is True


def test_config_is_validated(cfg):
    assert not mcp.validate_entry({"id": "x", "transport": "stdio"})["ok"]
    assert not mcp.validate_entry({"id": "x", "transport": "http", "url": "ftp://x"})["ok"]
    assert mcp.validate_entry({"id": "x", "transport": "http",
                               "url": "https://example.com/mcp"})["ok"]


def test_doctor_reports_each_server(cfg, server_script):
    mcp.install_server(_entry(server_script))
    d = mcp.doctor(timeout=15)
    assert d["total"] == 1 and d["healthy"] == 1
    assert d["servers"][0]["tools"] == 2


def test_enable_disable_and_remove(cfg, server_script):
    mcp.install_server(_entry(server_script))
    assert mcp.set_enabled("demo", True)["ok"]
    assert mcp.get_server("demo")["enabled"] is True
    assert mcp.remove_server("demo")["ok"]
    assert mcp.get_server("demo") is None


def test_previous_config_is_backed_up(cfg, server_script):
    mcp.install_server(_entry(server_script, "one"))
    mcp.install_server(_entry(server_script, "two"))
    assert cfg.with_suffix(".json.bak").is_file()
    assert set(json.loads(cfg.read_text())["mcpServers"]) == {"one", "two"}


def test_the_network_caveat_matches_what_is_actually_enforced():
    """The text used to assert flatly that ELI could not stop a server reaching the
    internet. That is true with no sandbox and false on Linux with bubblewrap, so it
    is derived from the machine rather than asserted — a consent screen must not
    claim containment it is not applying, nor deny containment it is."""
    from eli.plugins import subprocess_sandbox
    caps = subprocess_sandbox.capabilities()

    text = mcp.network_caveat(allow_network=False)
    assert "own program" in text
    if caps["network_isolation"]:
        assert "cannot reach anything" in text
    else:
        assert "cannot stop it" in text

    # A server that asked for network is always told it has it.
    assert "cannot see what it sends" in mcp.network_caveat(allow_network=True)


def test_a_server_without_the_network_capability_is_contained(cfg, server_script):
    """The gap netguard structurally cannot cover: a child process's own sockets."""
    from eli.plugins import subprocess_sandbox
    if not subprocess_sandbox.capabilities()["network_isolation"]:
        pytest.skip("no unprivileged sandbox on this platform")
    entry = _entry(server_script)
    entry["permissions"] = []          # no network declared
    plan = subprocess_sandbox.build_command(
        [sys.executable, str(server_script)], allow_network=False)
    assert plan["contained"] is True
    assert "network:isolated" in plan["applied"]


def test_a_server_that_declares_network_gets_it(server_script):
    from eli.plugins import subprocess_sandbox
    if not subprocess_sandbox.capabilities()["network_isolation"]:
        pytest.skip("no unprivileged sandbox on this platform")
    plan = subprocess_sandbox.build_command(
        [sys.executable, str(server_script)], allow_network=True)
    assert "network:isolated" not in plan["applied"]
    assert any("network" in n for n in plan["notes"])
