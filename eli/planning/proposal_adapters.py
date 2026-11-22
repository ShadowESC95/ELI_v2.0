from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import time
from typing import Any, Optional, Sequence


@dataclass
class CompletedLike:
    args: Any
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _discover_git_dir(start: Path) -> Optional[Path]:
    start = start.resolve()
    for p in [start, *start.parents]:
        gd = p / ".git"
        if gd.is_dir():
            return gd
        if gd.is_file():
            try:
                txt = gd.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                txt = ""
            if txt.startswith("gitdir:"):
                rel = txt.split(":", 1)[1].strip()
                cand = (p / rel).resolve()
                if cand.exists():
                    return cand
    return None


# The git commands this adapter runs: ones that only read. git status and git diff refresh the index
# when they can take its lock; --no-optional-locks stops that, so nothing in the checkout changes. A
# command that writes (commit, checkout, a -c setting, --output=FILE) is not run. git diff and git
# status used to come back empty without running, as a stand-in that kept this path from shelling
# out, so the code monitor never saw a change.
_READ_ONLY_GIT = frozenset({"diff", "status", "log", "show", "rev-parse", "ls-files"})
_WRITING_OPTIONS = ("--output", "--ext-diff")
# How long a read-only git command may take when the caller gives no timeout.
_GIT_TIMEOUT_S = 30


def safe_git_completed(args: Sequence[str] | None = None, cwd: str | None = None, **kwargs) -> CompletedLike:
    """A read-only git command run in `cwd` (diff, status, log, show, rev-parse, ls-files), as a
    CompletedProcess-like result. Anything else is not run, and says so in stderr."""
    argv = list(args or [])
    wd = Path(cwd).resolve() if cwd else Path.cwd().resolve()

    if not argv:
        return CompletedLike(args=argv, returncode=1, stderr="empty args")

    if (argv[0] != "git" or len(argv) < 2 or argv[1] not in _READ_ONLY_GIT
            or any(str(a).startswith(_WRITING_OPTIONS) for a in argv[2:])):
        return CompletedLike(args=argv, returncode=1,
                             stderr="not run: only read-only git commands are run here\n")

    if not _discover_git_dir(wd):
        return CompletedLike(args=argv, returncode=128, stderr="not a git repo\n")

    try:
        proc = subprocess.run(["git", "--no-optional-locks", *argv[1:]], cwd=str(wd), capture_output=True,
                              text=True, timeout=kwargs.get("timeout") or _GIT_TIMEOUT_S, check=False)
    except FileNotFoundError:
        return CompletedLike(args=argv, returncode=127, stderr="git is not installed\n")
    except subprocess.TimeoutExpired:
        return CompletedLike(args=argv, returncode=124, stderr="git took too long\n")
    except OSError as exc:
        return CompletedLike(args=argv, returncode=126, stderr=f"git could not run: {exc}\n")
    return CompletedLike(args=argv, returncode=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "")


def proposal_only_enqueue(args: Sequence[str] | None = None, cwd: str | None = None, env: dict | None = None, **kwargs) -> CompletedLike:
    argv = list(args or [])
    from eli.core.paths import proactive_dir
    out_dir = proactive_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    queue = out_dir / "proposal_queue.jsonl"

    payload = {
        "ts": int(time.time()),
        "kind": "proposal_only_enqueue",
        "args": argv,
        "cwd": cwd,
        "env_keys": sorted(list((env or {}).keys()))[:64],
    }

    with queue.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return CompletedLike(args=argv, returncode=0, stdout="enqueued proposal\n")

def governed_proposal_enqueue(
    kind,
    payload=None,
    source="unknown",
    priority=50,
    cwd=None,
    action_class="observe-only",
    emitter="unknown",
    requested_by="system",
    user_confirmed=False,
    approver="user",
):
    from eli.planning.proposal_queue import append_governed_proposal
    rec = append_governed_proposal(
        kind=kind,
        payload=payload or {},
        source=source,
        priority=priority,
        cwd=cwd,
        action_class=action_class,
        emitter=emitter,
        requested_by=requested_by,
        user_confirmed=user_confirmed,
        approver=approver,
    )
    return rec.to_dict() if hasattr(rec, "to_dict") else rec

def proactive_governed_enqueue(
    kind,
    payload=None,
    source="proactive",
    priority=50,
    cwd=None,
    action_class="observe-only",
    requested_by="system",
    user_confirmed=False,
    approver="user",
):
    from eli.planning.proposal_queue import append_governed_proposal
    rec = append_governed_proposal(
        kind=kind,
        payload=payload or {},
        source=source,
        priority=priority,
        cwd=cwd,
        action_class=action_class,
        emitter="proactive",
        requested_by=requested_by,
        user_confirmed=user_confirmed,
        approver=approver,
    )
    return rec.to_dict() if hasattr(rec, "to_dict") else rec

