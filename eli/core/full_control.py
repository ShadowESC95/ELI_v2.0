#!/usr/bin/env python3
"""ELI Full Control — a single master override that lifts ELI's safety barriers.

DEFAULT IS OFF. When off, ELI behaves exactly as it always has: offline-by-default,
self-editing gated, autonomy approval-gated, command safety fail-closed.

When ON (the user's explicit, opt-in choice via the GUI toggle), every gate that
consults this flag steps aside:
  • network gating (netguard / socket failsafe)  → network allowed
  • self-code patching (auto_patch_enabled gate)  → ELI may apply verified patches
  • autonomy/proposal approval (approval_engine)  → proposals auto-approved
  • command/shell safety gate                      → commands run without the gate

This is a power-user / trust switch. The SINGLE source of truth is the `full_control`
setting, flipped by the GUI toggle — there is no environment variable, so nothing can
conflict with the toggle. It is read live from the same in-memory settings store the Net
toggle uses, so flipping it takes effect immediately without a restart, and it persists.
Each barrier checks is_full_control() at its own decision point — there is no hidden
global mutation, so turning the toggle back OFF restores every gate at once.
"""
from __future__ import annotations


def is_full_control() -> bool:
    """True when the master override is active. Sole source: the `full_control` setting
    (the GUI toggle). Default False. Never raises."""
    try:
        from eli.core.config import get
        return bool(get("full_control", False))
    except Exception:
        return False


def set_full_control(enabled: bool) -> bool:
    """Flip the override via the live settings store (the toggle's single source of
    truth) and persist it. Returns the new state. Never raises."""
    enabled = bool(enabled)
    try:
        from eli.core.config import set as _set
        _set("full_control", enabled)
    except Exception:
        pass
    return enabled


__all__ = ["is_full_control", "set_full_control"]
