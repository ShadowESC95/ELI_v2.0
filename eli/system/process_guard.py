"""Verified process-kill safety for CLOSE_APP and friends.

`pkill -f <name>` matches the *full command line* of every process, as a
regex. A short or generic target is therefore a session-killer, not an app
closer: a GNOME session bus runs as

    dbus-daemon --session --address=systemd: --nofork --nopidfile --systemd-activation

so `pkill -f file` matches it on "nopidfile" and takes the whole desktop
session down. That is exactly what a "close file" request did on a live
2.3.15 desktop — the user was logged out, and the assistant then denied
having done it because the executor reported the kill as a success.

Nothing in this module trusts a name list on its own. Every pattern is
dry-run through `pgrep` first and the processes it *actually resolves to*
are inspected; the kill is only allowed when every one of them is an
ordinary user application. The name lists below are defence in depth for
the case where pgrep is unavailable, not the primary check.

Cross-platform: the pgrep/pkill path is POSIX-only. Windows closes windows
via Get-Process/CloseMainWindow and macOS via osascript `quit`, both of
which are window/app scoped and never reach this module.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# Signalling more processes than this is never "close an app" — a desktop
# app is a handful of processes, a runaway pattern is dozens.
MAX_KILL_FANOUT = 12

# Patterns too generic to ever full-cmdline match: they appear inside the
# command line of unrelated infrastructure (--nopidfile, --config-file,
# session managers, interpreter names) rather than identifying an app.
GENERIC_KILL_PATTERNS = frozenset({
    "a", "an", "the", "it", "this", "that", "all", "x", "up", "on", "in",
    "app", "apps", "application", "window", "windows", "tab", "tabs",
    "file", "files", "folder", "folders", "dir", "directory", "document",
    "documents", "home", "desktop", "download", "downloads", "picture",
    "pictures", "music", "video", "videos", "trash",
    "open", "close", "quit", "exit", "kill", "stop", "start", "run",
    "python", "python3", "py", "bash", "sh", "zsh", "fish", "node", "java",
    "perl", "ruby", "main", "core", "srv", "service", "services", "daemon",
    "session", "manager", "server", "system", "systemd", "shell", "term",
    "terminal", "console", "process", "task", "job", "user", "root",
    "eli", "assistant",
})

# Killing any of these ends the login session, the display server, the
# audio stack, or ELI itself.
PROTECTED_PROCESS_NAMES = frozenset({
    # init / service management
    "init", "systemd", "systemd-logind", "systemd-journald", "systemd-udevd",
    "systemd-oomd", "systemd-resolved", "systemd-timesyncd", "upstart",
    "launchd", "runit", "openrc", "s6-svscan",
    # session bus and portals
    "dbus-daemon", "dbus-broker", "dbus-broker-launch", "dbus-launch",
    "at-spi-bus-launcher", "at-spi2-registryd",
    "xdg-desktop-portal", "xdg-document-portal", "xdg-permission-store",
    "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-kde", "xdg-desktop-portal-wlr",
    # display servers and session managers
    "Xorg", "X", "Xwayland", "wayland", "weston", "mutter", "kwin",
    "kwin_x11", "kwin_wayland", "gnome-shell", "gnome-session",
    "gnome-session-binary", "gnome-keyring-daemon", "plasmashell",
    "ksmserver", "plasma_session", "xfce4-session", "xfwm4", "lxsession",
    "cinnamon", "cinnamon-session", "mate-session", "marco", "openbox",
    "i3", "sway", "hyprland", "labwc", "picom", "compton",
    # display / login managers
    "gdm", "gdm3", "gdm-session-worker", "sddm", "sddm-helper", "lightdm",
    "lxdm", "xdm", "greetd", "ly",
    # login / auth / policy
    "sshd", "polkitd", "polkit-gnome-authentication-agent-1", "accounts-daemon",
    "gnome-keyring", "seatd", "elogind",
    # audio stack — killing these silences the machine
    "pulseaudio", "pipewire", "pipewire-pulse", "wireplumber", "jackd",
    # filesystem / virtual filesystem daemons
    "gvfsd", "gvfsd-fuse", "gvfsd-metadata", "gvfs-udisks2-volume-monitor",
    "udisksd", "fusermount", "fusermount3", "automount",
    # kernel-adjacent
    "kthreadd", "kworker", "khugepaged", "ksoftirqd", "migration",
    # macOS — killing any of these ends the login session or the window server
    "WindowServer", "loginwindow", "SystemUIServer", "Dock", "Finder",
    "coreaudiod", "cfprefsd", "distnoted", "securityd", "opendirectoryd",
    "launchservicesd", "mds", "mds_stores", "mdworker", "notifyd",
    "diskarbitrationd", "configd", "powerd", "kernel_task", "logind",
    "UserEventAgent", "universalaccessd", "sharingd",
    # Windows — the session, the shell, and the security subsystem
    "winlogon.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "explorer.exe", "dwm.exe", "smss.exe", "svchost.exe", "system",
    "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe",
    "runtimebroker.exe", "shellexperiencehost.exe", "searchindexer.exe",
    "audiodg.exe", "spoolsv.exe", "lsaiso.exe", "wudfhost.exe",
})

# Whole families that must never be signalled, matched on the process name.
PROTECTED_NAME_PATTERNS = (
    re.compile(r"^gnome-(session|shell|keyring|settings)", re.I),
    re.compile(r"^gsd-", re.I),            # gnome-settings-daemon plugins
    re.compile(r"^xdg-", re.I),
    re.compile(r"^systemd", re.I),
    re.compile(r"^dbus", re.I),
    re.compile(r"^plasma", re.I),
    re.compile(r"^kde(init|_)", re.I),
    re.compile(r"^pipewire", re.I),
    re.compile(r"^wireplumber$", re.I),
    re.compile(r"^kworker", re.I),
    re.compile(r"^(ksoftirqd|migration|kthreadd|khugepaged|rcu_|irq/)", re.I),
)


@dataclass
class KillPlan:
    """The result of dry-running a kill pattern. `allowed` is the only gate."""
    allowed: bool
    reason: str
    pattern: str
    full_cmdline: bool
    pids: list[int] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "pattern": self.pattern,
            "full_cmdline": self.full_cmdline,
            "pids": list(self.pids),
            "blocked": list(self.blocked),
        }


def _own_pids() -> set[int]:
    """PIDs that are ELI itself — killing these is self-destruction."""
    pids: set[int] = set()
    for getter in (os.getpid, os.getppid):
        try:
            pids.add(int(getter()))
        except Exception:
            log.debug("process_guard: pid probe failed", exc_info=True)
    for getter in ("getpgrp", "getsid"):
        fn = getattr(os, getter, None)
        if fn is None:
            continue
        try:
            pids.add(int(fn(0) if getter == "getsid" else fn()))
        except Exception:
            log.debug("process_guard: pid probe failed", exc_info=True)
    pids.discard(0)
    return pids


def _process_name(pid: int) -> str:
    """Executable name for a pid, without trusting any external formatting."""
    try:
        with open(f"/proc/{int(pid)}/comm", "r", encoding="utf-8", errors="replace") as fh:
            name = fh.read().strip()
        if name:
            return name
    except Exception:
        log.debug("process_guard: name lookup failed", exc_info=True)
    ps = shutil.which("ps")
    if ps:
        try:
            cp = subprocess.run(
                [ps, "-p", str(int(pid)), "-o", "comm="],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=4, check=False,
            )
            return (cp.stdout or "").strip().splitlines()[0].strip() if cp.stdout else ""
        except Exception:
            return ""
    return ""


def is_protected_process(name: str) -> bool:
    """True when signalling this process would break the session or ELI."""
    n = str(name or "").strip()
    if not n:
        # An unidentifiable process is treated as protected: refusing to kill
        # something we could not name is the safe direction of failure.
        return True
    # Kernel threads are named "<name>/<cpu>" (kworker/0:1, ksoftirqd/0), so a
    # plain basename() would reduce them to "0:1" and let them through. Check
    # the raw name, its basename, and the segment before the first slash.
    candidates = {n, os.path.basename(n), n.split("/", 1)[0]}
    candidates.discard("")
    if candidates & PROTECTED_PROCESS_NAMES:
        return True
    return any(pat.search(c) for pat in PROTECTED_NAME_PATTERNS for c in candidates)


def _pgrep(pattern: str, full_cmdline: bool) -> Optional[list[int]]:
    """PIDs a pkill with these arguments would signal. None if pgrep is absent."""
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return None
    args = [pgrep, "-f", pattern] if full_cmdline else [pgrep, pattern]
    try:
        cp = subprocess.run(
            args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=6, check=False,
        )
    except Exception:
        return None
    pids: list[int] = []
    for line in (cp.stdout or "").split():
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def _windows_processes() -> Optional[list[tuple[int, str, str]]]:
    """(pid, image name, window title) for every process. None if unavailable.

    Windows has no pgrep, so tasklist is the enumeration source. The *checks*
    applied to the result are identical to the POSIX path — this is a
    different way to list processes, not a weaker set of rules.
    """
    tasklist = shutil.which("tasklist")
    if not tasklist:
        return None
    try:
        cp = subprocess.run(
            [tasklist, "/FO", "CSV", "/NH", "/V"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=15, check=False,
        )
    except Exception:
        return None
    import csv as _csv
    import io as _io
    out: list[tuple[int, str, str]] = []
    try:
        for row in _csv.reader(_io.StringIO(cp.stdout or "")):
            if len(row) < 2:
                continue
            try:
                pid = int(row[1])
            except ValueError:
                continue
            out.append((pid, (row[0] or "").strip(), (row[-1] or "").strip()))
    except Exception:
        return None
    return out


def _check_kill_pattern_windows(pattern: str, full_cmdline: bool) -> KillPlan:
    pat = pattern.strip()
    plan = KillPlan(allowed=False, reason="", pattern=pat, full_cmdline=full_cmdline)
    procs = _windows_processes()
    if procs is None:
        plan.reason = "tasklist unavailable — cannot verify what a kill would hit"
        return plan

    low = pat.lower()
    stem = low[:-4] if low.endswith(".exe") else low
    own = _own_pids()
    blocked: list[str] = []
    targets: list[int] = []
    for pid, image, title in procs:
        img_low = image.lower()
        img_stem = img_low[:-4] if img_low.endswith(".exe") else img_low
        hit = (img_stem == stem) or (full_cmdline and (low in img_low or low in title.lower()))
        if not hit:
            continue
        if pid in own:
            blocked.append(f"pid {pid} (ELI itself)")
            continue
        if is_protected_process(image):
            blocked.append(f"{image} (pid {pid})")
            continue
        targets.append(pid)

    plan.pids, plan.blocked = targets, blocked
    if blocked:
        plan.reason = ("refused — this would also signal protected processes: "
                       + ", ".join(blocked[:6]) + ("…" if len(blocked) > 6 else ""))
        return plan
    if not targets:
        plan.reason = f"no ordinary application matches {pat!r}"
        return plan
    if len(targets) > MAX_KILL_FANOUT:
        plan.reason = (f"refused — {pat!r} matches {len(targets)} processes, which is "
                       "far too broad to be a single application")
        return plan
    plan.allowed = True
    plan.reason = f"{len(targets)} matching process(es), none protected"
    return plan


def check_kill_pattern(pattern: str, *, full_cmdline: bool = False) -> KillPlan:
    """Dry-run a kill pattern and decide whether it may proceed.

    The decision is made from the processes the pattern *actually* resolves
    to on this machine right now, not from the pattern text alone.
    """
    pat = str(pattern or "").strip()
    plan = KillPlan(allowed=False, reason="", pattern=pat, full_cmdline=full_cmdline)

    if not pat:
        plan.reason = "no target given"
        return plan
    if os.name == "nt":
        if len(pat) < 3:
            plan.reason = f"target {pat!r} is too short to identify a process safely"
            return plan
        if full_cmdline and pat.lower() in GENERIC_KILL_PATTERNS:
            plan.reason = (f"{pat!r} is too generic to match process titles — it appears "
                           "inside unrelated system processes")
            return plan
        return _check_kill_pattern_windows(pat, full_cmdline)
    if len(pat) < 3:
        plan.reason = f"target {pat!r} is too short to identify a process safely"
        return plan
    if full_cmdline and pat.lower() in GENERIC_KILL_PATTERNS:
        plan.reason = (
            f"{pat!r} is too generic to match command lines — it appears inside "
            "unrelated system processes (this is what killed the session bus)"
        )
        return plan

    pids = _pgrep(pat, full_cmdline)
    if pids is None:
        # No pgrep: we cannot verify, so we only allow exact-name matching of
        # a non-generic target. An unverifiable full-cmdline kill is refused.
        if full_cmdline:
            plan.reason = "pgrep unavailable — refusing an unverifiable command-line kill"
            return plan
        if pat.lower() in GENERIC_KILL_PATTERNS or is_protected_process(pat):
            plan.reason = f"pgrep unavailable and {pat!r} is not a safe exact target"
            return plan
        plan.allowed = True
        plan.reason = "pgrep unavailable; exact-name kill of a non-protected target"
        return plan

    if not pids:
        plan.reason = f"no running process matches {pat!r}"
        return plan

    own = _own_pids()
    blocked: list[str] = []
    targets: list[int] = []
    for pid in pids:
        if pid in own:
            blocked.append(f"pid {pid} (ELI itself)")
            continue
        name = _process_name(pid)
        if is_protected_process(name):
            blocked.append(f"{name or 'unknown'} (pid {pid})")
            continue
        targets.append(pid)

    plan.pids = targets
    plan.blocked = blocked

    if blocked:
        plan.reason = (
            "refused — this would also signal protected processes: "
            + ", ".join(blocked[:6])
            + ("…" if len(blocked) > 6 else "")
        )
        return plan
    if not targets:
        plan.reason = f"every process matching {pat!r} is protected"
        return plan
    if len(targets) > MAX_KILL_FANOUT:
        plan.reason = (
            f"refused — {pat!r} matches {len(targets)} processes, which is far "
            "too broad to be a single application"
        )
        return plan

    plan.allowed = True
    plan.reason = f"{len(targets)} matching process(es), none protected"
    return plan


def safe_pkill(pattern: str, *, full_cmdline: bool = False, timeout: float = 8.0) -> dict:
    """Kill `pattern` only if `check_kill_pattern` clears it.

    Returns {"ok", "killed", "pids", "reason", "plan"}. `ok` is False and no
    signal is sent whenever the plan is refused.
    """
    plan = check_kill_pattern(pattern, full_cmdline=full_cmdline)
    if not plan.allowed:
        return {"ok": False, "killed": 0, "pids": [], "reason": plan.reason, "plan": plan.as_dict()}

    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if not taskkill:
            return {"ok": False, "killed": 0, "pids": [], "plan": plan.as_dict(),
                    "reason": "taskkill is not available on this system"}
        killed = 0
        for pid in plan.pids:
            try:
                # /T closes the process tree; no /F, so the app still gets the
                # chance to shut down cleanly, matching the POSIX SIGTERM.
                if subprocess.run([taskkill, "/PID", str(int(pid)), "/T"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=timeout, check=False).returncode == 0:
                    killed += 1
            except Exception:
                continue
        return {"ok": killed > 0, "killed": killed, "pids": list(plan.pids),
                "plan": plan.as_dict(),
                "reason": plan.reason if killed else "matched processes could not be closed"}

    kill = shutil.which("kill")
    killed = 0
    for pid in plan.pids:
        try:
            os.kill(int(pid), 15)  # SIGTERM — signal the verified pids only,
            killed += 1            # never re-run a pattern that could re-match.
        except ProcessLookupError:
            continue
        except PermissionError:
            if kill:
                try:
                    cp = subprocess.run([kill, "-15", str(int(pid))], timeout=timeout,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        check=False)
                    if cp.returncode == 0:
                        killed += 1
                except Exception:
                    continue
        except Exception:
            continue

    return {
        "ok": killed > 0,
        "killed": killed,
        "pids": list(plan.pids),
        "reason": plan.reason if killed else "matched processes could not be signalled",
        "plan": plan.as_dict(),
    }
