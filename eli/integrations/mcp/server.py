"""MCP server — ELI's own capabilities exposed to any MCP client.

Run it as::

    python -m eli.integrations.mcp.server

and point an MCP client at that command. This is the half that makes ELI a platform:
its action surface becomes callable by anything speaking the protocol, without that
client needing to know anything about ELI's router, effectors or memory.

Two deliberate restrictions:

* **Actions are exposed, not the engine.** A caller gets the effector surface, which
  is already gated, rather than a free-text prompt into the assistant.
* **The dangerous surface is opt-in.** Actions that control the machine or run code
  are withheld unless ``ELI_MCP_ALLOW_CONTROL=1``. Handing an arbitrary external
  client the mouse, the shell and the self-upgrade path by default would be a poor
  trade for convenience.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

from eli.utils.log import get_logger

log = get_logger(__name__)

_PROTOCOL_VERSION = "2024-11-05"

# Withheld unless explicitly allowed: anything that drives the machine, executes
# code, changes ELI itself, or spends the user's money/attention irreversibly.
_CONTROL_PREFIXES = (
    "COMPUTER_USE", "KEYBOARD", "MOUSE", "SHELL", "RUN_", "EXECUTE",
    "SELF_", "CODE_", "GAZE", "SET_CLIPBOARD", "SCHEDULE_", "DELETE_",
    "INSTALL", "UNINSTALL", "UPGRADE", "SMART_HOME", "SEND_",
)


def _allow_control() -> bool:
    return os.environ.get("ELI_MCP_ALLOW_CONTROL", "0") == "1"


def _exposed_actions() -> List[str]:
    try:
        from eli.execution.executor_enhanced import SUPPORTED_ACTIONS
    except Exception:
        log.debug("mcp.server: action surface unavailable", exc_info=True)
        return []
    actions = sorted(set(SUPPORTED_ACTIONS))
    if _allow_control():
        return actions
    return [a for a in actions if not a.startswith(_CONTROL_PREFIXES)]


def _describe(action: str) -> Dict[str, Any]:
    description = f"ELI action {action}"
    try:
        from eli.tools.registry import capabilities_doc
        for entry in getattr(capabilities_doc, "ENTRIES", []) or []:
            if isinstance(entry, dict) and entry.get("action") == action:
                description = str(entry.get("description") or description)
                break
    except Exception:
        log.debug("mcp.server: capability doc lookup failed", exc_info=True)
    return {
        "name": action,
        "description": description,
        # Args differ per action and are validated downstream by the effector, so the
        # schema stays open rather than asserting a shape that is not enforced here.
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
    }


def _call(action: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if action not in _exposed_actions():
        hint = "" if _allow_control() else " (set ELI_MCP_ALLOW_CONTROL=1 to expose control actions)"
        return {"content": [{"type": "text", "text": f"'{action}' is not exposed{hint}"}],
                "isError": True}
    try:
        from eli.execution.executor_enhanced import execute
        result = execute(action, arguments or {}) or {}
    except Exception as e:
        log.debug("mcp.server: %s failed", action, exc_info=True)
        return {"content": [{"type": "text", "text": f"{action} failed: {e}"}], "isError": True}

    text = str(result.get("content") or result.get("response") or "").strip()
    if not text:
        text = json.dumps(result, ensure_ascii=False, default=str)[:4000]
    return {"content": [{"type": "text", "text": text}],
            "isError": not bool(result.get("ok", True))}


def handle(message: Dict[str, Any]) -> Dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = str(message.get("method") or "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ELI", "version": _version()},
        }
    elif method == "tools/list":
        result = {"tools": [_describe(a) for a in _exposed_actions()]}
    elif method == "tools/call":
        result = _call(str(params.get("name") or ""), params.get("arguments") or {})
    elif method.startswith("notifications/"):
        return None
    elif method == "ping":
        result = {}
    else:
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"unknown method '{method}'"}}

    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _version() -> str:
    try:
        from eli.kernel.self_upgrade import _DEFAULT_RELEASE_TAG
        return str(_DEFAULT_RELEASE_TAG).lstrip("v")
    except Exception:
        return "0"


def serve(stdin=None, stdout=None) -> int:
    """Read JSON-RPC messages from stdin, write replies to stdout, until EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception:
            continue  # not our traffic; the transport is line-delimited JSON
        try:
            reply = handle(message)
        except Exception as e:
            log.debug("mcp.server: handler failed", exc_info=True)
            reply = {"jsonrpc": "2.0", "id": message.get("id"),
                     "error": {"code": -32603, "message": str(e)}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False, default=str) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(serve())
