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

This is a power-user / trust switch. It is read live (env first), so flipping the GUI
toggle takes effect immediately without a restart, and it is persisted so it survives
one. Each barrier checks is_full_control() at its own decision point — there is no
hidden global mutation, so turning the toggle back OFF restores every gate at once.
"""
from __future__ import annotations
import os

_TRUE = {"1", "true", "yes", "on", "enabled"}
_FALSE = {"0", "false", "no", "off", "disabled"}


def is_full_control() -> bool:
    """True when the master override is active. Live env wins; else the persisted
    setting; default False. Never raises."""
    v = os.environ.get("ELI_FULL_CONTROL")
    if v is not None:
        return v.strip().lower() in _TRUE
    try:
        from eli.core.config import get
        return bool(get("full_control", False))
    except Exception:
        return False


def set_full_control(enabled: bool) -> bool:
    """Flip the override live (env) and persist it (settings). Returns the new state.
    Never raises."""
    enabled = bool(enabled)
    os.environ["ELI_FULL_CONTROL"] = "1" if enabled else "0"
    try:
        from eli.core.runtime_settings import save_settings
        save_settings({"full_control": enabled})
    except Exception:
        pass
    return enabled


__all__ = ["is_full_control", "set_full_control"]
