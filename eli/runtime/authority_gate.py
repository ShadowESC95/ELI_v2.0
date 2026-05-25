"""
authority_gate — intentional stub.

All check() calls return allowed=True. ELI's action gating is handled
upstream by approval_engine + persistence_gate; this module exists as
a hook point for future role-based or capability-based access control.
Do not add blocking logic here without coordinating with approval_engine.
"""
from __future__ import annotations

from typing import Any, Dict


def status() -> Dict[str, Any]:
    return {"ok": True, "module": "authority_gate", "mode": "active"}


def allow(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "allowed": True,
        "action": action,
        "args": args or {},
    }


def check(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return allow(action, args)


__all__ = ["status", "allow", "check"]
