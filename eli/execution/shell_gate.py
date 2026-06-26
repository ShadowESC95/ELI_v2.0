"""Centralised shell-command safety gate.

Extracted verbatim from the inline RUN_CMD handler in ``executor_enhanced.py`` so the
destructive-pattern + dangerous-executable denylist lives in ONE small, *protected*
module instead of buried in a 14k-line file — where a self-improvement patch could
quietly strip it. ``self_improvement.apply_code_patch`` lists this file in its
protected-path set, so the self-modifier can never auto-edit the shell denylist.

Behaviour is identical to the previous inline gate:
  - ELI Full Control (the GUI toggle, default off) lifts the hard safety floor — when
    on, the destructive-pattern block and the executable denylist both step aside.
  - Otherwise, a destructive command pattern OR a denylisted ``argv[0]`` is refused.

100% local, deterministic, never raises. ``check_command`` returns a block-result
dict (the caller adds ``action``) when the command must be refused, else ``None``.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Any, Dict, Optional, Sequence, Union

# ── Destructive / dangerous command patterns — block outright ──
_BLOCKED_PATTERNS = [
    r"\brm\s+(-[rf]+\s+)?/(?!tmp)",            # rm -rf / (except /tmp)
    r"\bmkfs\b",                                # format filesystem
    r"\bdd\s+.*of=/dev/",                       # dd to raw device
    r"\bchmod\s+777\s+/",                       # chmod 777 on root
    r"\b:\(\)\s*\{.*\}",                        # fork bomb
    r"\bshutdown\b|\breboot\b|\bpoweroff\b",    # system power control
    r"\bcurl\b.*\|\s*(?:ba)?sh\b",              # curl | bash (remote exec)
    r"\bwget\b.*\|\s*(?:ba)?sh\b",              # wget | bash
    r"\b/dev/sd[a-z]\b",                        # raw disk device access
    r"\biptables\s+-F\b",                       # flush firewall rules
    r"\bmv\s+/\S",                              # mv files from root
    r"\b(?:bash|sh|zsh|ksh|fish|dash)\s+-c\b",  # shell -c arbitrary exec
    r"\bpython\d*\s+-c\b",                      # python -c arbitrary exec
    r"\bperl\s+-e\b",                           # perl -e arbitrary exec
    r"\bruby\s+-e\b",                           # ruby -e arbitrary exec
    r"\bnc\b.*-e\b",                            # netcat reverse shell
    r"\b(?:ncat|netcat)\b.*-e\b",               # netcat variants
    r">\s*/etc/",                               # redirect to system config
    r">\s*/boot/",                              # redirect to boot partition
    r"\bchpasswd\b|\bpasswd\b\s+\w",           # password change
    r"\bvisudo\b|\bsudoers\b",                  # sudoers modification
    r"\bcrontab\s+-[re]\b",                     # crontab modification
]

# ── Denylisted executable names as argv[0] ──
_DENIED_EXECUTABLES = {
    "bash", "sh", "zsh", "ksh", "fish", "dash",  # shell interpreters
    "python", "python3", "python2",              # scripting engines
    "perl", "ruby", "node", "nodejs",            # more scripting engines
    "nc", "ncat", "netcat",                      # network tools
    "dd", "mkfs", "fdisk", "parted",             # disk tools
    "rm", "shred", "wipe",                       # destructive file ops
    "iptables", "ip6tables", "nftables",         # firewall manipulation
}


def _full_control() -> bool:
    try:
        from eli.core.full_control import is_full_control
        return bool(is_full_control())
    except Exception:
        return False


def _blocked_result(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": "security_blocked",
            "content": msg, "response": msg, "blocked": True}


def check_command(cmd: Union[str, Sequence[Any]],
                  full_control: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    """Evaluate a shell command against the safety denylist.

    Returns a block-result dict (caller should set ``["action"]``) when the command
    must be refused, otherwise ``None``. ``full_control=None`` queries the live toggle.
    """
    # When cmd is a list, join to a string for pattern matching so that
    # ["bash", "-c", "..."] cannot bypass regex checks via str(list) repr.
    if isinstance(cmd, (list, tuple)):
        cmd_str = " ".join(str(x) for x in cmd)
    else:
        cmd_str = str(cmd)
    cmd_low = cmd_str.lower().strip()

    fc = _full_control() if full_control is None else bool(full_control)
    if fc:
        return None  # Full Control lifts the hard safety floor

    for pat in _BLOCKED_PATTERNS:
        if re.search(pat, cmd_low):
            return _blocked_result(f"Blocked dangerous command: {cmd_str[:60]}")

    try:
        if isinstance(cmd, (list, tuple)):
            argv0 = str(cmd[0]) if cmd else ""
        else:
            argv0 = (shlex.split(cmd_str) or [""])[0]
        argv0_base = os.path.basename(argv0).lower()
    except Exception:
        argv0_base = ""
    if argv0_base in _DENIED_EXECUTABLES:
        return _blocked_result(
            f"Execution of '{argv0_base}' is not permitted via RUN_CMD for security reasons.")

    return None
