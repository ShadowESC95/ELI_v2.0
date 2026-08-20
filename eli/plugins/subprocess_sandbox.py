"""Containment for child processes — the gap netguard structurally cannot cover.

`netguard` patches `socket.socket.connect` inside ELI's interpreter. An MCP server
is a separate program, usually Node or Go, whose network stack never touches
Python's socket module, so ELI's offline switch has no effect on it. That was
documented as an open hole; this closes it on Linux, and says so honestly where it
cannot.

The mechanism is **bubblewrap** — the same unprivileged sandbox Flatpak uses. No
root, no daemon, no kernel module to install:

  * **Network**: `--unshare-net` gives the child no network namespace at all. A
    server that did not declare the `network` capability cannot reach anything,
    regardless of what its code tries. This is real enforcement, not a Python-level
    monkeypatch it could bypass.
  * **Filesystem**: the root is bound read-only, then a tmpfs is laid over `$HOME`,
    so ssh keys, cloud credentials, browser stores and wallets are simply not there.
    Paths the server declared are bound back explicitly, read-only unless it asked
    for write.
  * **Process**: `--unshare-pid` hides other processes, `--die-with-parent` means it
    cannot outlive ELI, `--new-session` detaches it from the terminal so it cannot
    inject keystrokes via TIOCSTI.
  * **Privilege**: `PR_SET_NO_NEW_PRIVS` on every POSIX launch, so setuid binaries
    cannot be used to regain privilege, plus resource limits.

What this does NOT do, stated because a sandbox that oversells itself is worse than
none: on macOS and Windows only the no-new-privs / rlimit layer applies, and
`capabilities()` reports exactly that so callers can tell the operator the truth
rather than implying containment they are not getting.
"""
from __future__ import annotations

import os
import platform
import resource
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from eli.utils.log import get_logger

log = get_logger(__name__)

# Directories a child almost always needs to run at all.
_SYSTEM_ROOTS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt", "/etc")

# Deliberately conservative. RLIMIT_NPROC is per-USER, not per-process, so capping
# it makes every clone fail with EAGAIN the moment the account is already above the
# cap — which is how bubblewrap's namespace creation broke. RLIMIT_AS is likewise
# omitted: V8 and other JITs reserve enormous virtual address space up front and die
# under a limit that looks generous. Containment comes from the namespaces; these are
# only a runaway-resource backstop.
DEFAULT_RLIMITS = {
    "cpu_seconds": 3600,
    "open_files": 4096,
}


def capabilities() -> Dict[str, Any]:
    """What this machine can actually enforce. Never optimistic."""
    system = platform.system()
    bwrap = shutil.which("bwrap")
    unshare = shutil.which("unshare")
    caps = {
        "platform": system,
        "bubblewrap": bool(bwrap),
        "unshare": bool(unshare),
        "network_isolation": False,
        "filesystem_isolation": False,
        "no_new_privs": os.name == "posix",
        "rlimits": os.name == "posix",
        "notes": [],
    }
    if system == "Linux":
        if bwrap:
            caps["network_isolation"] = True
            caps["filesystem_isolation"] = True
        elif unshare:
            caps["network_isolation"] = True
            caps["notes"].append(
                "bubblewrap is not installed, so only network isolation is available. "
                "Install bubblewrap (bwrap) for filesystem isolation too.")
        else:
            caps["notes"].append(
                "Neither bubblewrap nor unshare is installed, so a child process "
                "cannot be contained. Install bubblewrap (bwrap).")
    else:
        caps["notes"].append(
            f"{system} has no unprivileged sandbox ELI can use. A child process runs "
            f"with your full account privileges and reaches the network freely.")
    return caps


def _make_preexec(new_session: bool):
    """Applied in the child between fork and exec. POSIX only.

    `new_session` is False when bubblewrap is doing it via --new-session; calling
    setsid twice is harmless but calling it when bwrap has not yet run detaches the
    wrong process.
    """
    def _warn(message: str) -> None:
        # This runs between fork and exec. The logging module can deadlock there —
        # a lock held by another thread at fork time is never released in the child
        # — so failures are reported with a direct write syscall instead of being
        # swallowed. Observable without being unsafe.
        try:
            os.write(2, ("[SANDBOX:child] " + message + "\n").encode("utf-8", "replace"))
        except Exception:
            return

    def _preexec() -> None:
        try:
            import ctypes
            # PR_SET_NO_NEW_PRIVS = 38 — a setuid binary can no longer raise privilege.
            ctypes.CDLL("libc.so.6", use_errno=True).prctl(38, 1, 0, 0, 0)
        except Exception as exc:
            _warn(f"could not set no-new-privs: {exc!r}")
        for name, limit in (("RLIMIT_CPU", DEFAULT_RLIMITS["cpu_seconds"]),
                            ("RLIMIT_NOFILE", DEFAULT_RLIMITS["open_files"])):
            try:
                which = getattr(resource, name)
                _soft, hard = resource.getrlimit(which)
                resource.setrlimit(which, (min(limit, hard) if hard > 0 else limit, hard))
            except Exception as exc:
                _warn(f"could not set {name}: {exc!r}")
        if new_session:
            try:
                os.setsid()
            except Exception as exc:
                _warn(f"could not start a new session: {exc!r}")
    return _preexec


def _executable_paths(argv: Sequence[str]) -> List[str]:
    """Directories the child needs bound back after $HOME is masked.

    Covers the two cases that actually bite: a virtualenv interpreter under the
    user's home, and a user-local runtime (nvm's node, uv's tool dir) that a
    home-wide tmpfs would otherwise erase.
    """
    out: List[str] = []
    home = os.path.expanduser("~")

    def add(path: Optional[str]) -> None:
        if not path:
            return
        try:
            real = os.path.realpath(path)
        except Exception:
            return
        if real.startswith(home + os.sep) and real not in out:
            out.append(real)

    # Any argument that IS an existing path is something the child was told to use:
    # a server script, a data directory, a config file. Masking $HOME and /tmp would
    # otherwise hide exactly the thing it was asked to run.
    for arg in list(argv)[1:]:
        text = str(arg)
        if text.startswith("-") or os.sep not in text:
            continue
        candidate = os.path.expanduser(text)
        if os.path.exists(candidate):
            real = os.path.realpath(candidate)
            target = real if os.path.isdir(real) else os.path.dirname(real)
            if target and target not in out and target not in ("/", os.sep):
                out.append(target)

    exe = shutil.which(argv[0]) if argv else None
    if exe:
        add(os.path.dirname(os.path.realpath(exe)))
        # A venv: .../venv/bin/python -> bind the whole venv, not just bin.
        parent = os.path.dirname(os.path.dirname(os.path.realpath(exe)))
        if parent and os.path.isdir(os.path.join(parent, "lib")):
            add(parent)
    # The running interpreter's prefix, for `sys.executable`-style launches.
    add(getattr(sys, "prefix", None))
    add(getattr(sys, "base_prefix", None))
    # Common user-local runtime roots, bound only if they exist (--ro-bind-try).
    for candidate in (".nvm", ".local/share/uv", ".local/bin", ".npm", ".cache/uv",
                      ".bun", ".deno"):
        add(os.path.join(home, candidate))
    return out


def build_command(argv: Sequence[str], *, allow_network: bool = False,
                  read_paths: Optional[Sequence[str]] = None,
                  write_paths: Optional[Sequence[str]] = None,
                  cwd: Optional[str] = None) -> Dict[str, Any]:
    """Wrap `argv` in the strongest sandbox this machine supports.

    Returns {argv, applied, notes, contained}. `contained` is False when nothing
    could be applied — the caller must surface that rather than proceeding quietly.
    """
    argv = [str(a) for a in argv]
    applied: List[str] = []
    notes: List[str] = []
    caps = capabilities()

    if platform.system() != "Linux":
        notes.extend(caps["notes"])
        return {"argv": argv, "applied": applied, "notes": notes, "contained": False}

    bwrap = shutil.which("bwrap")
    if bwrap:
        cmd = [bwrap, "--die-with-parent", "--new-session", "--unshare-pid",
               "--unshare-uts", "--unshare-ipc", "--unshare-cgroup-try"]
        # Read-only system. Binding the whole root read-only keeps arbitrary runtimes
        # (node, uv, python) working; the sensitive parts are masked below.
        cmd += ["--ro-bind", "/", "/"]
        cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]

        # Mask the home directory. Credentials live here, and a plugin has no default
        # business reading them; declared paths are bound back explicitly.
        home = os.path.expanduser("~")
        if home and home != "/":
            cmd += ["--tmpfs", home]

        # Masking $HOME also hides anything installed there — a venv interpreter, a
        # user-local node, an npm cache. Bind the program's own tree back read-only,
        # or the sandbox cannot start the very thing it is meant to contain.
        for needed in _executable_paths(argv):
            cmd += ["--ro-bind-try", needed, needed]
            applied.append(f"runtime:{needed}")

        for path in (read_paths or []):
            p = str(Path(path).expanduser())
            if os.path.exists(p):
                cmd += ["--ro-bind", p, p]
                applied.append(f"read:{p}")
        for path in (write_paths or []):
            p = str(Path(path).expanduser())
            os.makedirs(p, exist_ok=True)
            cmd += ["--bind", p, p]
            applied.append(f"write:{p}")

        if allow_network:
            cmd += ["--share-net"]
            notes.append("This program declared the network capability, so it has "
                         "network access. ELI cannot see what it sends.")
        else:
            cmd += ["--unshare-net"]
            applied.append("network:isolated")

        if cwd:
            cmd += ["--chdir", str(cwd)]
        applied += ["fs:home-masked", "fs:root-readonly", "proc:pid-namespace",
                    "proc:die-with-parent", "proc:new-session"]
        return {"argv": cmd + ["--"] + argv, "applied": applied, "notes": notes,
                "contained": True}

    unshare = shutil.which("unshare")
    if unshare and not allow_network:
        notes.append("bubblewrap is not installed; the network is isolated but the "
                     "filesystem is not. Install bubblewrap for full containment.")
        applied.append("network:isolated")
        return {"argv": [unshare, "-n", "--"] + argv, "applied": applied,
                "notes": notes, "contained": True}

    notes.extend(caps["notes"])
    return {"argv": argv, "applied": applied, "notes": notes, "contained": False}


def popen(argv: Sequence[str], *, allow_network: bool = False,
          read_paths: Optional[Sequence[str]] = None,
          write_paths: Optional[Sequence[str]] = None,
          env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None,
          **kwargs) -> subprocess.Popen:
    """`subprocess.Popen` with the sandbox applied and the environment scrubbed."""
    plan = build_command(argv, allow_network=allow_network, read_paths=read_paths,
                         write_paths=write_paths, cwd=cwd)
    child_env = dict(env or os.environ)
    # Secrets ELI holds are not the child's business.
    for key in list(child_env):
        upper = key.upper()
        if any(t in upper for t in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "APIKEY")):
            child_env.pop(key, None)
    if not plan["contained"]:
        log.warning("[SANDBOX] launching %s WITHOUT containment: %s",
                    argv[0], "; ".join(plan["notes"]) or "no sandbox available")
    kwargs.setdefault("env", child_env)
    if os.name == "posix":
        kwargs.setdefault("preexec_fn", _make_preexec(not plan["contained"]))
    # bwrap sets its own cwd via --chdir; passing cwd too would fail if masked.
    if cwd and not plan["contained"]:
        kwargs.setdefault("cwd", cwd)
    return subprocess.Popen(plan["argv"], **kwargs)


def describe(allow_network: bool = False) -> str:
    """One paragraph for a consent screen, matching what will actually be applied."""
    caps = capabilities()
    if not caps["bubblewrap"] and not caps["unshare"]:
        return ("This program will run with your full account privileges and "
                "unrestricted network access — ELI has no sandbox available on this "
                "system.")
    parts = []
    if caps["network_isolation"]:
        parts.append("no network access at all" if not allow_network
                     else "network access (it asked for it)")
    if caps["filesystem_isolation"]:
        parts.append("a read-only filesystem with your home directory hidden")
    parts.append("no ability to gain privileges, and it cannot outlive ELI")
    return "It will run with " + ", ".join(parts) + "."


__all__ = ["capabilities", "build_command", "popen", "describe", "DEFAULT_RLIMITS"]
