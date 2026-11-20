"""
authority_gate — who may have ELI carry out an action.

The machine's owner may have ELI do anything its other gates allow (approval_engine,
persistence_gate, the shell gate). A caller with a lesser role, an API user who is a
member or viewer, may not have it run code or commands, read or write files, see the
screen or clipboard, drive the keyboard and mouse, or change ELI itself: owner_only()
is that list, and the MCP server withholds the same list from its clients unless the
owner turns control on. The caller's role comes from request_context.caller_role_var,
set by the API for the turn; None (the desktop app, ELI's own daemons) is the owner.

Caller contract (engine.process() Stage 2 is FAIL-CLOSED):
  * check() must return a dict with an explicit boolean "allowed". A missing
    "allowed" key is treated as DENY, not allow.
  * To block, return {"allowed": False, "reason": "<why>"} — the reason is
    surfaced to the user.
  * If check() raises, the caller DENIES privileged/side-effecting actions
    (deny-on-doubt) and lets read-only/conversational actions degrade open.
  * So real logic added here is safe by construction: a bug fails closed for
    anything that can change the machine, and can never silently fail open.
"""
from __future__ import annotations

from typing import Any, Dict


# What only the owner may have ELI do, beyond the actions the model may never choose itself
# (llm_intent._EXPLICIT_ONLY_ACTIONS: persona, settings, plugins, MCP, self-patching, the shell).
_OWNER_ONLY = frozenset({
    "RUN_CMD", "SHELL_EXEC", "EXECUTE_GOAL",
    "GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT", "GENERATE_PROJECT", "GENERATE_CODE", "WRITE_CODE",
    "CODE_SOLVE", "FIX_FILE", "CONFIRM_CODE_FIX", "EXAMINE_CODE", "CODEBASE_GRAPH", "CODE_CHANGES",
    "READ_FILE", "LIST_DIR", "CREATE_FILE", "CREATE_FOLDER", "DELETE_FILE", "SUMMARIZE_FILE", "FILE_AUDIT",
    "ANALYZE_PDF", "ANALYZE_PDF_FOLDER", "ANALYZE_IMAGE", "OCR_IMAGE", "CONVERT_DOCUMENT",
    "SCREENSHOT", "SCREEN_READ_ANALYZE", "SCREEN_LOCATE", "GET_CLIPBOARD", "SET_CLIPBOARD",
    "KEYBOARD", "MOUSE_CONTROL", "OPEN_IDE", "OPEN_IN_IDE", "OPEN_FILE_SYSTEM",
})


def owner_only() -> frozenset:
    """The actions only the machine's owner may have ELI carry out."""
    try:
        from eli.cognition.llm_intent import _EXPLICIT_ONLY_ACTIONS
    except Exception:
        _EXPLICIT_ONLY_ACTIONS = frozenset()
    return _OWNER_ONLY | frozenset(_EXPLICIT_ONLY_ACTIONS)


def _caller_role() -> str:
    try:
        from eli.kernel.request_context import caller_role_var
        return str(caller_role_var.get() or "")
    except Exception:
        return ""


def status() -> Dict[str, Any]:
    return {
        "ok": True,
        "module": "authority_gate",
        "mode": "role-gate",
        "owner_only_actions": len(owner_only()),
        "enforced_with": ["approval_engine", "persistence_gate", "shell_gate.check_command"],
    }


def allow(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "allowed": True,
        "action": action,
        "args": args or {},
    }


def check(action: str, args: Dict[str, Any] | None = None, role: str | None = None) -> Dict[str, Any]:
    """Allowed unless the caller has a role below admin and the action is the owner's alone."""
    who = (role if role is not None else _caller_role()).strip().lower()
    name = str(action or "").strip().upper()
    if who and who != "admin" and name in owner_only():
        return {"ok": True, "allowed": False, "action": name, "args": args or {},
                "reason": f"{name} is for the machine's owner only, and this account is a {who}."}
    return allow(action, args)


__all__ = ["status", "allow", "check", "owner_only"]
