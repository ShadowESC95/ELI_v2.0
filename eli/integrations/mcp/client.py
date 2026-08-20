"""MCP client — ELI as a host that gains tools from configured MCP servers.

An MCP server is launched as a local subprocess and spoken to over stdio using
JSON-RPC 2.0. Config lives at ``config/mcp_servers.json`` and uses the same shape the
rest of the ecosystem uses, so a server the user already runs elsewhere can be pasted
straight in:

    {"mcpServers": {"files": {"command": "mcp-server-filesystem", "args": ["/data"]}}}

Design constraints that shaped this:

* **No sockets.** stdio only. Tool use therefore does not touch netguard's network
  posture, and a remote transport is absent by choice rather than bolted on in a way
  that would quietly bypass offline-by-default.
* **Nothing auto-starts.** Servers launch on first use and are reused, so an unused
  entry in the config costs nothing and a broken one cannot stall boot.
* **Failure is reported, never smoothed over.** A server that will not start, a tool
  that errors, a call that times out — each returns its real reason. A tool call that
  silently returns "done" is the confabulation failure mode with someone else's
  process attached.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_PROTOCOL_VERSION = "2024-11-05"
_START_TIMEOUT_S = 20.0
_CALL_TIMEOUT_S = 60.0

_SESSIONS: Dict[str, "_Session"] = {}
_LOCK = threading.RLock()


def config_path() -> Path:
    """The one file both MCP halves read.

    Delegates to `eli.plugins.mcp.config_path` so the lifecycle side (which installs
    and verifies servers) and the runtime side (which calls their tools) can never
    disagree about where the config lives — including under the ELI_MCP_CONFIG
    override, which only one of them used to honour.
    """
    try:
        from eli.plugins.mcp import config_path as _lifecycle_path
        return Path(_lifecycle_path())
    except Exception:
        from eli.core.paths import config_dir
        return Path(config_dir()) / "mcp_servers.json"


def load_config() -> Dict[str, Dict[str, Any]]:
    """Configured servers, or {} when unconfigured. Never raises — a malformed config
    must not take the assistant down with it."""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        log.debug("mcp: config unreadable at %s", p, exc_info=True)
        return {}
    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in servers.items():
        if isinstance(spec, dict) and spec.get("command"):
            out[str(name)] = spec
    return out


class _Session:
    """One live MCP server subprocess and the JSON-RPC conversation with it."""

    def __init__(self, name: str, spec: Dict[str, Any]) -> None:
        self.name = name
        self.spec = spec
        self.proc: Optional[subprocess.Popen] = None
        self.tools: List[Dict[str, Any]] = []
        self.error: str = ""
        self._id = 0
        self._lock = threading.RLock()

    # -- transport ---------------------------------------------------------
    def _send(self, payload: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        body = json.dumps(payload, ensure_ascii=False)
        self.proc.stdin.write(body + "\n")
        self.proc.stdin.flush()

    def _read(self, timeout: float) -> Optional[Dict[str, Any]]:
        """Read one JSON-RPC message, ignoring any non-JSON chatter the server prints."""
        assert self.proc and self.proc.stdout
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except Exception:
                log.debug("mcp[%s]: non-JSON line ignored: %s", self.name, line[:200])
        return None

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None,
                 timeout: float = _CALL_TIMEOUT_S) -> Dict[str, Any]:
        with self._lock:
            self._id += 1
            req_id = self._id
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                        "params": params or {}})
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = self._read(max(0.1, deadline - time.time()))
                if msg is None:
                    return {"error": {"message": f"{self.name} stopped responding"}}
                # Skip notifications and replies to other ids.
                if msg.get("id") == req_id:
                    return msg
            return {"error": {"message": f"{method} timed out after {timeout:.0f}s"}}

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        command = str(self.spec.get("command") or "")
        if not command:
            self.error = "no command configured"
            return False
        if not shutil.which(command) and not Path(command).is_file():
            self.error = f"'{command}' is not installed or not on PATH"
            return False

        argv = [command] + [str(a) for a in (self.spec.get("args") or [])]
        env = dict(os.environ)
        extra = self.spec.get("env")
        if isinstance(extra, dict):
            env.update({str(k): str(v) for k, v in extra.items()})

        try:
            self.proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, env=env,
                cwd=str(self.spec.get("cwd") or "") or None, bufsize=1)
        except Exception as e:
            self.error = f"could not start: {e}"
            log.debug("mcp[%s]: launch failed", self.name, exc_info=True)
            return False

        init = self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ELI", "version": "1"},
        }, timeout=_START_TIMEOUT_S)
        if init.get("error"):
            self.error = str(init["error"].get("message") or "initialize failed")
            self.stop()
            return False

        try:
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            log.debug("mcp[%s]: initialized notification failed", self.name, exc_info=True)

        listed = self._request("tools/list", {}, timeout=_START_TIMEOUT_S)
        if listed.get("error"):
            self.error = str(listed["error"].get("message") or "tools/list failed")
            self.stop()
            return False
        self.tools = list((listed.get("result") or {}).get("tools") or [])
        self.error = ""
        log.debug("mcp[%s]: connected with %d tool(s)", self.name, len(self.tools))
        return True

    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                log.debug("mcp[%s]: kill failed", self.name, exc_info=True)
        finally:
            self.proc = None

    def call(self, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        reply = self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        if reply.get("error"):
            return {"ok": False, "error": str(reply["error"].get("message") or "tool call failed")}
        result = reply.get("result") or {}
        # MCP returns content as a list of typed parts; flatten the text ones.
        parts = []
        for part in (result.get("content") or []):
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        text = "\n".join(p for p in parts if p).strip()
        if result.get("isError"):
            return {"ok": False, "error": text or "the tool reported an error"}
        return {"ok": True, "text": text, "raw": result}


def _session(name: str, spec: Dict[str, Any]) -> _Session:
    with _LOCK:
        sess = _SESSIONS.get(name)
        if sess is not None and sess.alive():
            return sess
        sess = _Session(name, spec)
        sess.start()
        _SESSIONS[name] = sess
        return sess


def status() -> Dict[str, Any]:
    """What is configured, what is connected, and what it offers — including the real
    reason for anything that is not working."""
    servers = load_config()
    out: List[Dict[str, Any]] = []
    for name, spec in servers.items():
        with _LOCK:
            live = _SESSIONS.get(name)
        out.append({
            "name": name,
            "command": str(spec.get("command") or ""),
            "connected": bool(live and live.alive() and not live.error),
            "tools": [t.get("name") for t in (live.tools if live else [])],
            "error": (live.error if live else ""),
        })
    return {"configured": len(servers), "servers": out, "config_path": str(config_path())}


def list_tools(refresh: bool = False) -> List[Dict[str, Any]]:
    """Every tool across every configured server, as
    ``{"server", "name", "qualified", "description", "schema"}``."""
    tools: List[Dict[str, Any]] = []
    for name, spec in load_config().items():
        if refresh:
            with _LOCK:
                old = _SESSIONS.pop(name, None)
            if old:
                old.stop()
        sess = _session(name, spec)
        if not sess.alive():
            continue
        for t in sess.tools:
            tname = str(t.get("name") or "")
            if not tname:
                continue
            tools.append({
                "server": name,
                "name": tname,
                "qualified": f"{name}.{tname}",
                "description": str(t.get("description") or ""),
                "schema": t.get("inputSchema") or {},
            })
    return tools


def call_tool(qualified: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call ``server.tool`` (or a bare tool name when it is unambiguous)."""
    servers = load_config()
    if not servers:
        return {"ok": False, "error": "no MCP servers are configured",
                "hint": f"add them to {config_path()}"}

    server_name, _, tool_name = qualified.partition(".")
    if not tool_name:
        # Bare tool name — resolve it if exactly one server offers it.
        matches = [t for t in list_tools() if t["name"] == qualified]
        if not matches:
            return {"ok": False, "error": f"no configured MCP server offers a tool called '{qualified}'"}
        if len({m["server"] for m in matches}) > 1:
            names = ", ".join(sorted(m["qualified"] for m in matches))
            return {"ok": False, "error": f"'{qualified}' is ambiguous — use one of: {names}"}
        server_name, tool_name = matches[0]["server"], matches[0]["name"]

    spec = servers.get(server_name)
    if spec is None:
        return {"ok": False, "error": f"no MCP server named '{server_name}' is configured"}

    sess = _session(server_name, spec)
    if not sess.alive():
        return {"ok": False, "error": sess.error or f"{server_name} is not running"}
    return sess.call(tool_name, arguments or {})


def shutdown_all() -> None:
    with _LOCK:
        for sess in list(_SESSIONS.values()):
            sess.stop()
        _SESSIONS.clear()
