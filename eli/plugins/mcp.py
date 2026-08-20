"""MCP servers: one config ELI owns, and an install that proves it works.

An MCP server is not a Python plugin. It is a separate process — usually `npx` or
`uvx` — that ELI talks to over JSON-RPC. That difference is why MCP installs fail
in practice, and it is worth naming the four ways:

  1. the config was written somewhere the host does not read;
  2. the runtime the server needs (node, uv, python) is not installed;
  3. paths and environment variables were never resolved, so it starts and dies;
  4. nobody checked whether it actually answered — the entry looked installed and
     silently did nothing.

This module removes all four. There is exactly ONE config file and ELI owns it
(`config_path()`), so "the correct location" is never in question. Installing runs
a preflight for the runtime, writes the entry atomically, then LAUNCHES the server
and performs a real MCP `initialize` handshake followed by `tools/list`. An entry
is only marked working when a server has answered with its tool list. Nothing is
taken on faith.

One thing this cannot do, and says so plainly: an MCP server is a child process, so
`netguard`'s socket guard — a monkeypatch inside ELI's own interpreter — does not
apply to it. A server that wants the network will reach it whatever ELI's offline
toggle says. Consent text for MCP installs must state that rather than imply a
containment that does not exist.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_lock = threading.RLock()

STDIO, HTTP = "stdio", "http"
PROTOCOL_VERSION = "2025-06-18"

# Runtimes an entry can depend on, and how to prove each is present.
_RUNTIMES = {
    "node": (["npx", "node"], "Node.js", "https://nodejs.org"),
    "python": (["uvx", "uv", "python3", "python"], "Python", "https://python.org"),
    "binary": ([], "a native binary", ""),
}


def config_path() -> Path:
    """The one file ELI reads MCP servers from. Never anywhere else."""
    override = os.environ.get("ELI_MCP_CONFIG")
    if override:
        return Path(override).expanduser()
    from eli.core.paths import config_dir
    return Path(config_dir()) / "mcp_servers.json"


# ── config i/o ─────────────────────────────────────────────────────────────────

def _read() -> Dict[str, Dict[str, Any]]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        log.debug("[MCP] unreadable config", exc_info=True)
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    return {str(k): dict(v) for k, v in servers.items() if isinstance(v, dict)}


def _write(servers: Dict[str, Dict[str, Any]]) -> Path:
    """Atomic write. A half-written MCP config is a broken ELI start, so the
    replace happens in one step and the previous file is kept as .bak."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_file():
        try:
            shutil.copy2(p, p.with_suffix(".json.bak"))
        except Exception:
            log.debug("[MCP] could not back up the previous config", exc_info=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "mcpServers": servers}, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return p


def list_servers() -> List[Dict[str, Any]]:
    with _lock:
        return [{"id": k, **v} for k, v in sorted(_read().items())]


def get_server(server_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _read().get(str(server_id))
        return {"id": str(server_id), **entry} if entry else None


# ── validation + runtime preflight ─────────────────────────────────────────────

def validate_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    problems: List[str] = []
    e = dict(entry or {})

    sid = str(e.get("id") or "").strip()
    if not sid:
        problems.append("Server id is required.")

    transport = str(e.get("transport") or STDIO).lower()
    if transport not in (STDIO, HTTP):
        problems.append(f"transport must be '{STDIO}' or '{HTTP}'.")
    e["transport"] = transport

    if transport == STDIO:
        if not str(e.get("command") or "").strip():
            problems.append("A stdio server needs a 'command'.")
        args = e.get("args") or []
        if not isinstance(args, list):
            problems.append("'args' must be a list.")
            args = []
        e["args"] = [str(a) for a in args]
    else:
        url = str(e.get("url") or "")
        if not url.startswith(("https://", "http://")):
            problems.append("An http server needs an http(s) 'url'.")
        if url.startswith("http://"):
            e.setdefault("warnings", []).append(
                "This server is plain http — traffic can be read and altered in transit.")

    env = e.get("env") or {}
    if not isinstance(env, dict):
        problems.append("'env' must be an object.")
        env = {}
    e["env"] = {str(k): str(v) for k, v in env.items()}

    perms = e.get("permissions") or []
    if not isinstance(perms, list):
        problems.append("'permissions' must be a list.")
        perms = []
    e["permissions"] = [str(p) for p in perms]

    return {"ok": not problems, "problems": problems, "entry": e}


def check_runtime(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Is the thing this server needs actually installed on this machine?

    Checked BEFORE anything is written, so a missing Node is a clear message at the
    point of install rather than a server that silently never starts.
    """
    if str(entry.get("transport") or STDIO) == HTTP:
        return {"ok": True, "runtime": "http", "found": entry.get("url"),
                "reason": "Remote server; nothing to install locally."}

    command = str(entry.get("command") or "")
    found = shutil.which(command)
    if found:
        version = ""
        try:
            proc = subprocess.run([found, "--version"], capture_output=True,
                                  text=True, timeout=10)
            version = (proc.stdout or proc.stderr or "").strip().splitlines()[:1]
            version = version[0] if version else ""
        except Exception:
            log.debug("[MCP] could not read runtime version", exc_info=True)
        return {"ok": True, "runtime": command, "found": found, "version": version,
                "reason": f"{command} is installed at {found}."}

    hint = ""
    if command in ("npx", "node"):
        hint = ("Install Node.js from https://nodejs.org (npx ships with it). "
                + {"Windows": "Or: winget install OpenJS.NodeJS",
                   "Darwin": "Or: brew install node",
                   "Linux": "Or use your distribution's nodejs package."}
                .get(platform.system(), ""))
    elif command in ("uvx", "uv"):
        hint = "Install uv from https://docs.astral.sh/uv/ (uvx ships with it)."
    elif command in ("python", "python3"):
        hint = "Python is required but was not found on PATH."

    return {"ok": False, "runtime": command, "found": None,
            "reason": f"'{command}' is not installed or not on PATH. {hint}".strip()}


# ── the handshake: proof it actually works ─────────────────────────────────────

def _rpc(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def probe(entry: Dict[str, Any], *, timeout: float = 30) -> Dict[str, Any]:
    """Start the server and complete a real MCP handshake.

    initialize → notifications/initialized → tools/list. Returns the tools the
    server actually offers. This is what distinguishes "configured" from "working";
    without it an entry is only a hope.
    """
    check = validate_entry(entry)
    if not check["ok"]:
        return {"ok": False, "stage": "config", "problems": check["problems"]}
    e = check["entry"]

    if e["transport"] == HTTP:
        return {"ok": False, "stage": "transport",
                "problems": ["Probing http MCP servers is not implemented yet; "
                             "only stdio servers are verified at install time."]}

    rt = check_runtime(e)
    if not rt["ok"]:
        return {"ok": False, "stage": "runtime", "problems": [rt["reason"]], "runtime": rt}

    env = dict(os.environ)
    env.update(e.get("env") or {})
    argv = [rt["found"]] + list(e.get("args") or [])

    # Containment. An MCP server is a separate process, so netguard cannot touch it —
    # the kernel can. A server that did not declare `network` gets no network
    # namespace at all, and its filesystem view is read-only with $HOME masked
    # except for paths it declared. See eli/plugins/subprocess_sandbox.py.
    allow_network = "network" in (e.get("permissions") or [])
    read_paths = list(e.get("read_paths") or [])
    write_paths = list(e.get("write_paths") or [])
    if e.get("cwd"):
        read_paths.append(str(Path(e["cwd"]).expanduser()))

    proc = None
    try:
        from eli.plugins import subprocess_sandbox
        plan = subprocess_sandbox.build_command(
            argv, allow_network=allow_network, read_paths=read_paths,
            write_paths=write_paths,
            cwd=str(Path(e["cwd"]).expanduser()) if e.get("cwd") else None)
        proc = subprocess_sandbox.popen(
            argv, allow_network=allow_network, read_paths=read_paths,
            write_paths=write_paths,
            cwd=str(Path(e["cwd"]).expanduser()) if e.get("cwd") else None,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, bufsize=1)
    except Exception as exc:
        return {"ok": False, "stage": "launch",
                "problems": [f"Could not start the server: {exc}"]}

    result: Dict[str, Any] = {"ok": False, "stage": "handshake", "problems": []}
    try:
        proc.stdin.write(_rpc({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ELI", "version": "2"},
            },
        }))
        proc.stdin.flush()

        deadline = time.time() + timeout
        init = None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue          # servers sometimes print banners before speaking JSON-RPC
            if msg.get("id") == 1:
                init = msg
                break

        if init is None:
            err = (proc.stderr.read() or "")[:400] if proc.stderr else ""
            result["problems"].append(
                "The server did not answer the MCP handshake within "
                f"{timeout:.0f}s." + (f" It said: {err}" if err else ""))
            return result
        if "error" in init:
            result["problems"].append(f"The server rejected the handshake: {init['error']}")
            return result

        info = (init.get("result") or {})
        proc.stdin.write(_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        proc.stdin.write(_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
        proc.stdin.flush()

        tools: List[Dict[str, Any]] = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.strip())
            except Exception:
                continue
            if msg.get("id") == 2:
                tools = (msg.get("result") or {}).get("tools") or []
                break

        return {
            "ok": True, "stage": "ready",
            "sandbox": {"contained": plan["contained"], "applied": plan["applied"],
                        "notes": plan["notes"]},
            "server_info": info.get("serverInfo") or {},
            "protocol": info.get("protocolVersion"),
            "capabilities": info.get("capabilities") or {},
            "tools": [{"name": t.get("name"), "description": t.get("description", "")}
                      for t in tools],
            "tool_count": len(tools),
            "problems": [],
        }
    except Exception as exc:
        result["problems"].append(f"Handshake failed: {exc}")
        return result
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    log.debug("[MCP] could not kill probe process", exc_info=True)


# ── install / manage ───────────────────────────────────────────────────────────

def install_server(entry: Dict[str, Any], *, verify: bool = True,
                   enable: bool = False, timeout: float = 30) -> Dict[str, Any]:
    """Add an MCP server to the one config ELI reads, verifying it first.

    Order is deliberate: validate, check the runtime, run the handshake, and only
    then write. A server that cannot answer never reaches the config, so the config
    never contains entries that quietly do nothing.
    """
    check = validate_entry(entry)
    if not check["ok"]:
        return {"ok": False, "stage": "config", "problems": check["problems"]}
    e = check["entry"]
    sid = e.pop("id")

    rt = check_runtime(e)
    if not rt["ok"]:
        return {"ok": False, "stage": "runtime", "problems": [rt["reason"]], "runtime": rt}

    probe_result: Dict[str, Any] = {}
    if verify:
        probe_result = probe({**e, "id": sid}, timeout=timeout)
        if not probe_result.get("ok"):
            return {"ok": False, "stage": probe_result.get("stage", "handshake"),
                    "problems": probe_result.get("problems") or ["The server did not respond."],
                    "runtime": rt}

    with _lock:
        servers = _read()
        servers[sid] = {
            **e,
            # Installed disabled by default: reaching ELI's action surface is a
            # separate decision from being configured.
            "enabled": bool(enable),
            "installed": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verified": bool(probe_result.get("ok")),
            "tools": probe_result.get("tools") or [],
            "server_info": probe_result.get("server_info") or {},
            "sandbox": probe_result.get("sandbox") or {},
        }
        path = _write(servers)

    sandbox = probe_result.get("sandbox") or {}
    return {
        "ok": True, "id": sid, "config": str(path),
        "sandbox": sandbox,
        "runtime": rt, "tools": probe_result.get("tools") or [],
        "tool_count": probe_result.get("tool_count", 0),
        "enabled": bool(enable),
        "problems": [],
        "response": (
            f"'{sid}' added to {path.name} and verified — it answered the handshake and "
            f"offers {probe_result.get('tool_count', 0)} tool(s). It is switched OFF until "
            f"you enable it."),
    }


def remove_server(server_id: str) -> Dict[str, Any]:
    with _lock:
        servers = _read()
        if server_id not in servers:
            return {"ok": False, "problems": [f"No MCP server called {server_id!r}."]}
        servers.pop(server_id)
        _write(servers)
    return {"ok": True, "problems": []}


def set_enabled(server_id: str, enabled: bool) -> Dict[str, Any]:
    with _lock:
        servers = _read()
        if server_id not in servers:
            return {"ok": False, "problems": [f"No MCP server called {server_id!r}."]}
        servers[server_id]["enabled"] = bool(enabled)
        _write(servers)
    return {"ok": True, "problems": []}


def doctor(*, timeout: float = 20) -> Dict[str, Any]:
    """Check every configured server and say exactly what is wrong with each.

    The diagnostic that answers "why isn't my MCP working" without guesswork.
    """
    reports = []
    for entry in list_servers():
        sid = entry["id"]
        rt = check_runtime(entry)
        item = {"id": sid, "enabled": bool(entry.get("enabled")),
                "runtime_ok": rt["ok"], "runtime": rt["reason"], "tools": 0,
                "ok": False, "problem": ""}
        if not rt["ok"]:
            item["problem"] = rt["reason"]
            reports.append(item)
            continue
        res = probe(entry, timeout=timeout)
        item["ok"] = bool(res.get("ok"))
        item["tools"] = res.get("tool_count", 0)
        if not res.get("ok"):
            item["problem"] = "; ".join(res.get("problems") or ["did not respond"])
        reports.append(item)

    healthy = sum(1 for r in reports if r["ok"])
    return {"ok": all(r["ok"] for r in reports) if reports else True,
            "servers": reports, "healthy": healthy, "total": len(reports),
            "config": str(config_path()),
            "summary": (f"{healthy} of {len(reports)} MCP server(s) responding."
                        if reports else "No MCP servers configured.")}


def network_caveat(allow_network: bool = False) -> str:
    """The sentence any MCP consent screen must carry — accurate to this machine.

    It used to say flatly that ELI could not stop a server reaching the internet.
    That is still true where no sandbox is available, and no longer true on Linux
    with bubblewrap, so the text is derived from what will actually be applied
    rather than asserted.
    """
    base = "An MCP server runs as its own program, outside ELI's own process. "
    try:
        from eli.plugins import subprocess_sandbox
        caps = subprocess_sandbox.capabilities()
        if caps["network_isolation"]:
            if allow_network:
                return (base + "This one asked for network access, so it will have it, "
                                "and ELI cannot see what it sends.")
            return (base + subprocess_sandbox.describe(False)
                    + " It did not ask for network access, so it is launched into an "
                      "empty network namespace and genuinely cannot reach anything.")
        return (base + "ELI's offline switch cannot stop it reaching the internet and "
                       "cannot see what it sends — no sandbox is available on this "
                       "system. Only add MCP servers you trust with that.")
    except Exception:
        return (base + "ELI's offline switch cannot stop it reaching the internet, and "
                       "ELI cannot see what it sends.")


__all__ = [
    "config_path", "list_servers", "get_server", "validate_entry", "check_runtime",
    "probe", "install_server", "remove_server", "set_enabled", "doctor",
    "network_caveat", "STDIO", "HTTP",
]
