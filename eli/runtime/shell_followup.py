"""Resolve deictic shell follow-ups ("run that command") from prior assistant output."""
from __future__ import annotations

import re
from typing import Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_RUN_PRIOR_SHELL_RE = re.compile(
    r"^\s*(?:please\s+)?(?:run|execute)\s+(?:that|this|the|it)(?:\s+command)?\s*\.?\s*$",
    re.I,
)

_CODE_FENCE_RE = re.compile(r"```(?:bash|sh|shell)?\n([\s\S]*?)```", re.I)

_READ_ONLY_CMDS = frozenset({
    "date", "echo", "stat", "cat", "timedatectl", "uptime", "whoami", "hostname",
    "uname", "ls", "pwd", "head", "tail", "grep", "wc", "df", "free",
})


def is_run_prior_shell_request(text: str) -> bool:
    return bool(_RUN_PRIOR_SHELL_RE.match(str(text or "").strip()))


def extract_shell_from_assistant(text: str) -> str:
    """Pull the first safe command line from a fenced shell block."""
    m = _CODE_FENCE_RE.search(str(text or ""))
    if not m:
        return ""
    lines = [
        ln.strip().rstrip(";")
        for ln in m.group(1).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for preferred in ("date", "timedatectl", "stat"):
        for line in lines:
            if line.split()[0].lower() == preferred:
                return line
    for line in lines:
        first = line.split()[0].lower()
        if first in _READ_ONLY_CMDS and first not in {"echo"}:
            return line
    return lines[0] if lines else ""


def _last_assistant_text() -> str:
    try:
        from eli.memory.memory import get_memory
        for turn in reversed(get_memory().get_recent_conversation(limit=8) or []):
            role = str((turn or {}).get("role") or "").lower()
            if role in ("assistant", "eli"):
                content = str((turn or {}).get("content") or "").strip()
                if content:
                    return content
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return ""


def resolve_run_prior_shell(user_text: str = "") -> Optional[str]:
    """Return a shell command to execute when the user says 'run that command'."""
    if not is_run_prior_shell_request(user_text):
        return None
    cmd = extract_shell_from_assistant(_last_assistant_text())
    return cmd or None
