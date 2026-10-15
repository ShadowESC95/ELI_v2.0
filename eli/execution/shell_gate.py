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
    # Windows: the same harm in its own words (until 2.5.17 the gate knew only POSIX commands)
    r"\b(?:del|erase)\b.*\s/s\b",                # recursive delete
    r"\b(?:rd|rmdir)\b.*\s/s\b",                 # recursive directory removal
    r"\bformat(?:\.com)?\s+[a-z]:",              # format a drive
    r"\bremove-item\b.*-recurse\b",              # PowerShell recursive delete
    r"\breg(?:\.exe)?\s+delete\b",               # registry deletion
    r"\bvssadmin\b.*\bdelete\b",                # shadow copies (backups) deleted
    r"\bwbadmin\b.*\bdelete\b",                 # backups deleted
    r"\bbcdedit\b",                              # boot configuration
    r"\bcipher(?:\.exe)?\s+/w\b",                # wipe free space
    r"\b(?:invoke-expression|iex)\b",            # PowerShell arbitrary exec
    r"\b(?:cmd|powershell|pwsh)(?:\.exe)?\s+(?:/[ck]\b|-c(?:ommand)?\b|-enc)",  # shell -c arbitrary exec
    r">\s*[a-z]:\\windows\\",                     # redirect into the Windows folder
    # macOS
    r"\bdiskutil\s+(?:erase|zerodisk|secureerase|partitiondisk|reformat)",  # erase a disk
    r"\bcsrutil\s+disable\b",                    # system integrity protection off
    r"\bspctl\s+--master-disable\b",             # Gatekeeper off
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
    # Windows
    "cmd", "powershell", "pwsh",                 # shell interpreters
    "cscript", "wscript", "mshta",               # scripting engines
    "diskpart", "format",                        # disk tools
    "bcdedit", "vssadmin", "wbadmin",            # boot config, backups
    # macOS
    "osascript",                                 # scripting engine
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
            argv0 = (shlex.split(cmd_str, posix=os.name != "nt") or [""])[0].strip('"')
        # either separator and no Windows suffix: C:\\Windows\\System32\\cmd.exe is cmd
        argv0_base = re.split(r"[\\\\/]", argv0)[-1].lower()
        argv0_base = re.sub(r"\.(?:exe|com|bat|cmd)$", "", argv0_base)
    except Exception:
        argv0_base = ""
    if argv0_base in _DENIED_EXECUTABLES:
        return _blocked_result(
            f"Execution of '{argv0_base}' is not permitted via RUN_CMD for security reasons.")

    return None
