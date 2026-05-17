from __future__ import annotations

import json
import os
from typing import Any, Dict

from eli.cognition.chat_model import chat_response
from eli.execution.router_enhanced import route_intent
from eli.execution.executor_enhanced import execute
from eli.tools.registry.capabilities import as_text as capabilities_text

REASONER_MODEL = os.environ.get("ELI_CHAT_MODEL", "eli-persona:latest")
ROUTER_MODEL = os.environ.get("ELI_ROUTER_MODEL", "eli-router:latest")
SYSTEM_CONTEXT = "Capabilities:\n" + (capabilities_text() or "")


def _content(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("content") or obj.get("response") or "")
    return "" if obj is None else str(obj)


def agent_step(user_message: str) -> Dict[str, Any]:
    reasoning = chat_response(user_message, system=SYSTEM_CONTEXT, model=REASONER_MODEL)
    content = _content(reasoning).strip()
    route = route_intent(content) if callable(route_intent) else {"action": "CHAT", "args": {}}
    if not isinstance(route, dict):
        route = {"action": "CHAT", "args": {}}
    action = route.get("action")
    if not action or action == "CHAT":
        return {"ok": True, "type": "message", "content": content}
    result = execute(action, route.get("args", {}))
    followup = chat_response(
        "Tool result:\n" + json.dumps(result, indent=2, ensure_ascii=False),
        system=SYSTEM_CONTEXT,
        model=REASONER_MODEL,
    )
    return {
        "ok": True,
        "type": "tool_result",
        "tool": action,
        "result": result,
        "content": _content(followup),
    }


def repl() -> None:
    while True:
        try:
            msg = input("ELI> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg or msg.lower() in {"quit", "exit"}:
            break
        out = agent_step(msg)
        print(_content(out))
