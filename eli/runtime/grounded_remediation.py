from __future__ import annotations

import glob
import json
import os
import time
import re
import shlex
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from .incident_log import write_incident
except Exception:  # pragma: no cover
    def write_incident(payload: dict) -> str:
        return ""

_LOCK = threading.RLock()
_BUSY = False
_PENDING = None
_LAST_FAILURE = None

YES_RE = re.compile(r"^\s*(yes|y|yeah|yep|confirm|go ahead|do it|proceed|install it|download it)\s*$", re.I)
NO_RE = re.compile(r"^\s*(no|n|cancel|stop|abort|never mind|dont|don't)\s*$", re.I)


def _remediation_supported() -> bool:
    """Current repair planner executes Linux package-manager/desktop commands."""
    return sys.platform.startswith("linux")

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _root() -> Path:
    return Path(__file__).resolve().parents[3]

def _q(value: str) -> str:
    return shlex.quote(str(value))

def _pending_file() -> Path:
    path = _root() / "artifacts" / "pending_remediation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def _load_pending_state() -> dict | None:
    path = _pending_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _save_pending_state(payload: dict | None) -> None:
    path = _pending_file()
    if not payload:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def is_busy() -> bool:
    with _LOCK:
        return bool(_BUSY)

def set_busy(value: bool) -> None:
    global _BUSY
    with _LOCK:
        _BUSY = bool(value)

def get_pending():
    global _PENDING
    with _LOCK:
        if _PENDING is None:
            _PENDING = _load_pending_state()
        return _PENDING

def clear_pending() -> None:
    global _PENDING
    with _LOCK:
        _PENDING = None
        _save_pending_state(None)

def get_last_failure():
    with _LOCK:
        return _LAST_FAILURE

def remember_failure(result: dict) -> None:
    global _LAST_FAILURE
    with _LOCK:
        _LAST_FAILURE = result
    try:
        write_incident({"kind": "failure", "result": result})
    except Exception:
        pass

def set_pending_for_test(plan: dict, result: dict, stage: str = "offered") -> None:
    global _PENDING
    with _LOCK:
        _PENDING = {
            "kind": "repair",
            "stage": stage,
            "plan": plan,
            "result": result,
            "created_at": _now(),
        }
        _save_pending_state(_PENDING)

def _run(cmd: str, timeout: int = 30) -> dict:
    proc = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)
    return {
        "cmd": cmd,
        "rc": proc.returncode,
        "out": (proc.stdout or "").strip(),
        "err": (proc.stderr or "").strip(),
    }

def _needs_privileged_terminal(cmd: str) -> bool:
    return bool(re.search(r"(^|\s)sudo(\s|$)", str(cmd or "")))

def _sudo_cached() -> bool:
    check = _run("sudo -n true")
    return check["rc"] == 0

def _run_in_terminal(cmd: str) -> dict:
    run_dir = _root() / "artifacts" / "terminal_runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    log_path = run_dir / f"{run_id}.log"
    rc_path = run_dir / f"{run_id}.rc"
    meta_path = run_dir / f"{run_id}.json"
    sh_path = run_dir / f"{run_id}.sh"

    script = f"""#!/usr/bin/env bash
LOG={_q(str(log_path))}
RCF={_q(str(rc_path))}
rm -f "$LOG" "$RCF"

echo "[ELI] Running command..."
echo "[ELI] Log: $LOG"
echo

set -o pipefail
{{ {cmd}; }} 2>&1 | tee "$LOG"
rc=${{PIPESTATUS[0]}}
printf '%s\n' "$rc" > "$RCF"

echo
echo "[ELI] Command exit code: $rc"
echo "[ELI] Press Enter to close this terminal."
read -r _
"""

    try:
        sh_path.write_text(script, encoding="utf-8")
        os.chmod(sh_path, 0o700)
    except Exception as e:
        return {
            "cmd": cmd,
            "rc": 98,
            "out": "",
            "err": f"Failed to write terminal script: {e}",
            "transport": "script_terminal_spawn",
        }

    argv = None
    if shutil.which("gnome-terminal"):
        argv = ["gnome-terminal", "--", "bash", str(sh_path)]
    elif shutil.which("x-terminal-emulator"):
        argv = ["x-terminal-emulator", "-e", "bash", str(sh_path)]
    elif shutil.which("kgx"):
        argv = ["kgx", "bash", str(sh_path)]
    elif shutil.which("konsole"):
        argv = ["konsole", "-e", "bash", str(sh_path)]
    elif shutil.which("xfce4-terminal"):
        argv = ["xfce4-terminal", "--command", f"bash {sh_path}"]
    elif shutil.which("xterm"):
        argv = ["xterm", "-e", "bash", str(sh_path)]
    else:
        return {
            "cmd": cmd,
            "rc": 97,
            "out": "",
            "err": "No supported terminal emulator found for visible terminal execution.",
            "transport": "script_terminal_spawn",
        }

    try:
        meta_path.write_text(json.dumps({
            "transport": "script_terminal_spawn",
            "cmd": cmd,
            "argv": argv,
            "script_path": str(sh_path),
            "log_path": str(log_path),
            "rc_path": str(rc_path),
            "created_at": _now(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    try:
        subprocess.Popen(argv, start_new_session=True)
    except Exception as e:
        return {
            "cmd": cmd,
            "rc": 99,
            "out": "",
            "err": f"Failed to launch terminal: {e}",
            "transport": "script_terminal_spawn",
        }

    timeout_s = 900.0
    waited = 0.0
    while waited < timeout_s:
        if rc_path.exists():
            try:
                rc = int((rc_path.read_text(encoding="utf-8").strip() or "1").splitlines()[0].strip())
            except Exception:
                rc = 1
            try:
                out = log_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                out = ""
            return {
                "cmd": cmd,
                "rc": rc,
                "out": out,
                "err": "",
                "transport": "script_terminal_spawn",
                "script_path": str(sh_path),
                "log_path": str(log_path),
                "rc_path": str(rc_path),
            }
        time.sleep(1.0)
        waited += 1.0

    try:
        out = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        out = ""

    return {
        "cmd": cmd,
        "rc": 124,
        "out": out,
        "err": "Timed out waiting for terminal command completion.",
        "transport": "script_terminal_spawn",
        "script_path": str(sh_path),
        "log_path": str(log_path),
        "rc_path": str(rc_path),
    }

def _first_token(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line.split()[0]
    return ""

def _desktop_hits(name: str) -> list[str]:
    hits = []
    lowered = name.lower()
    for base in ("~/.local/share/applications", "/usr/share/applications"):
        root = Path(base).expanduser()
        if not root.exists():
            continue
        for pat in (f"*{name}*.desktop", f"*{lowered}*.desktop"):
            hits.extend(str(p) for p in root.glob(pat))
    return sorted(set(hits))

def _flatpak_installed(name: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    cmd = f"flatpak list --app --columns=application,name 2>/dev/null | grep -Eiq {_q(name)}"
    return _run(cmd)["rc"] == 0

def _snap_installed(name: str) -> bool:
    if not shutil.which("snap"):
        return False
    return _run(f"snap list {_q(name)} >/dev/null 2>&1")["rc"] == 0

def _apt_candidate(name: str) -> str:
    if not shutil.which("apt-cache"):
        return ""

    app = str(name).strip().lower()

    alias_map = {
        "chrome": "chromium",
        "google chrome": "chromium",
        "vscode": "code",
        "visual studio code": "code",
        "virtual studio code": "code",
        "vs code": "code",
    }

    blacklist = {
        "chrome-gnome-shell",
        "gnome-browser-connector",
        "libndpi-wireshark",
    }

    target = alias_map.get(app, app)

    r = _run("apt-cache search --names-only " + _q("^" + target + "$") + " | awk 'NR==1{print $1}'")
    tok = _first_token(r["out"])
    if tok and tok not in blacklist:
        return tok

    r = _run("apt-cache search --names-only " + _q("^" + target + "(-|$)") + " | awk 'NR==1{print $1}'")
    tok = _first_token(r["out"])
    if tok and tok not in blacklist:
        return tok

    return ""

def _snap_candidate(name: str) -> str:
    if not shutil.which("snap"):
        return ""
    r = _run(f"snap info {_q(name)}")
    if r["rc"] == 0 and ("name:" in r["out"].lower() or "name:" in r["err"].lower()):
        return name
    return ""

def _flatpak_candidate(name: str) -> str:
    if not shutil.which("flatpak"):
        return ""
    app = str(name).strip().lower()
    r = _run(f"flatpak search {_q(name)} 2>/dev/null | awk 'tolower($1)==tolower(app){{print $1; exit}} tolower($2)==tolower(app){{print $1; exit}}' app={_q(app)}")
    return _first_token(r["out"])

def _is_pkg_lock_error(run: dict) -> bool:
    text = "\n".join([
        str(run.get("out", "") or ""),
        str(run.get("err", "") or ""),
    ])
    return (
        "Could not get lock /var/lib/dpkg/lock-frontend" in text
        or "Unable to acquire the dpkg frontend lock" in text
    )

def _extract_pkg_lock_metadata(run: dict) -> dict:
    text = "\n".join([
        str(run.get("out", "") or ""),
        str(run.get("err", "") or ""),
    ])
    m = re.search(r"held by process\s+(\d+)\s+\(([^)]+)\)", text)
    return {
        "holder_pid": m.group(1) if m else "",
        "holder_name": m.group(2) if m else "",
        "raw": text,
    }

def _package_lock_evidence(run: dict) -> list[str]:
    text = "\n".join([
        str(run.get("out", "") or ""),
        str(run.get("err", "") or ""),
    ])
    ev = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if "lock" in s.lower() or "held by process" in s.lower():
            ev.append(s)

    meta = _extract_pkg_lock_metadata(run)
    if meta["holder_pid"]:
        ev.append(f"lock holder process -> {meta['holder_pid']} ({meta['holder_name']})")

    dedup = []
    seen = set()
    for item in ev:
        if item not in seen:
            dedup.append(item)
            seen.add(item)
    return dedup

def _find_interactive_pkg_prompt() -> dict:
    r = _run("ps -eo pid=,ppid=,tty=,comm=,args= | grep -E 'whiptail|dialog|debconf|dpkg-preconfig' | grep -v grep")
    out = str(r.get("out", "") or "").strip()
    if not out:
        return {
            "found": False,
            "pid": "",
            "ppid": "",
            "tty": "",
            "comm": "",
            "args": "",
        }

    for line in out.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) >= 5:
            return {
                "found": True,
                "pid": parts[0],
                "ppid": parts[1],
                "tty": parts[2],
                "comm": parts[3],
                "args": parts[4],
            }

    return {
        "found": False,
        "pid": "",
        "ppid": "",
        "tty": "",
        "comm": "",
        "args": "",
    }

def _mk_result(ok: bool, domain: str, subject: str, operation: str, reason_code: str,
               evidence: list[str] | None = None, repairable: bool = False,
               repair_options: list[dict] | None = None, metadata: dict | None = None) -> dict:
    return {
        "ok": bool(ok),
        "domain": domain,
        "subject": subject,
        "operation": operation,
        "reason_code": reason_code,
        "grounded": True,
        "confidence": 1.0,
        "evidence": evidence or [],
        "repairable": bool(repairable),
        "repair_options": repair_options or [],
        "metadata": metadata or {},
        "ts": _now(),
    }

def extract_app_name(text: str) -> str:
    raw = str(text or "").strip().lower()
    raw = re.sub(r"^\s*(open|run|launch|start)\s+", "", raw)
    raw = re.sub(r"\s+app$", "", raw).strip()

    alias_map = {
        "vscode": "code",
        "visual studio code": "code",
        "virtual studio code": "code",
        "vs code": "code",
        "chrome": "chromium",
        "google chrome": "chromium",
        "browser chrome": "chromium",
        "gedit": "gedit",
        "docker desktop": "docker-desktop",
    }

    return alias_map.get(raw, raw)

def build_install_candidates(name: str) -> list[dict]:
    candidates = []

    snap_name = _snap_candidate(name)
    if snap_name:
        candidates.append({
            "source": "snap",
            "command": f"sudo snap install {snap_name}",
            "label": f"Install {name} via snap",
        })

    apt_pkg = _apt_candidate(name)
    if apt_pkg:
        candidates.append({
            "source": "apt",
            "command": f"sudo apt-get update && sudo apt-get install -y {apt_pkg}",
            "label": f"Install {name} via apt package {apt_pkg}",
        })

    flatpak_app = _flatpak_candidate(name)
    if flatpak_app:
        candidates.append({
            "source": "flatpak",
            "command": f"flatpak install -y flathub {flatpak_app}",
            "label": f"Install {name} via flatpak {flatpak_app}",
        })

    order = {"snap": 0, "apt": 1, "flatpak": 2}
    candidates.sort(key=lambda x: order.get(x["source"], 99))
    return candidates

def diagnose_app(name: str) -> dict:
    app = extract_app_name(name)
    if not app:
        return _mk_result(False, "application", "", "status", "EMPTY_SUBJECT",
                          evidence=["No application name was provided."], repairable=False)

    which_path = shutil.which(app)
    desktop_hits = _desktop_hits(app)
    flatpak_ok = _flatpak_installed(app)
    snap_ok = _snap_installed(app)

    evidence = []
    evidence.append(f"command -v {app} -> {which_path if which_path else 'not found'}")
    evidence.append(f"desktop entry search -> {', '.join(desktop_hits) if desktop_hits else 'none found'}")
    evidence.append(f"flatpak lookup -> {'installed' if flatpak_ok else 'not installed'}")
    evidence.append(f"snap lookup -> {'installed' if snap_ok else 'not installed'}")

    if which_path or desktop_hits or flatpak_ok or snap_ok:
        result = _mk_result(True, "application", app, "status", "INSTALLED",
                            evidence=evidence, repairable=False)
        remember_failure(result)
        return result

    repair_options = build_install_candidates(app)
    result = _mk_result(False, "application", app, "open", "NOT_INSTALLED",
                        evidence=evidence, repairable=True,
                        repair_options=repair_options)
    remember_failure(result)
    return result


def diagnose_path(path: str) -> dict:
    import os as _os
    p = str(path or "").strip()
    if not p:
        return _mk_result(False, "filesystem", "", "open", "EMPTY_PATH",
                          evidence=["No path was provided."], repairable=False)
    expanded = _os.path.expanduser(p)
    exists = _os.path.exists(expanded)
    parent = str(_os.path.dirname(expanded))
    parent_exists = _os.path.exists(parent) if parent else False
    evidence = [
        f"path -> {expanded}",
        f"exists -> {exists}",
        f"parent -> {parent} ({'exists' if parent_exists else 'not found'})",
    ]
    if exists:
        return _mk_result(True, "filesystem", p, "open", "PATH_OK",
                          evidence=evidence, repairable=False)
    result = _mk_result(False, "filesystem", p, "open", "PATH_NOT_FOUND",
                        evidence=evidence, repairable=parent_exists,
                        metadata={"expanded": expanded, "parent": parent, "parent_exists": parent_exists})
    remember_failure(result)
    return result


def diagnose_browser(target: str = "") -> dict:
    browsers = ["firefox", "chromium-browser", "chromium", "google-chrome",
                "brave-browser", "epiphany", "falkon"]
    found = [b for b in browsers if shutil.which(b)]
    t = str(target or "").strip()
    evidence = [f"browser search -> {', '.join(found) if found else 'none found'}"]
    if t:
        evidence.insert(0, f"target -> {t}")
    if found:
        return _mk_result(True, "browser", t or "browser", "open", "BROWSER_OK",
                          evidence=evidence, repairable=False)
    candidates = [
        {"source": "apt", "label": "Install Firefox", "command": "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y firefox"},
        {"source": "snap", "label": "Install Firefox (snap)", "command": "sudo snap install firefox"},
        {"source": "flatpak", "label": "Install Firefox (flatpak)", "command": "flatpak install -y flathub org.mozilla.firefox"},
    ]
    result = _mk_result(False, "browser", t or "browser", "open", "NO_BROWSER_FOUND",
                        evidence=evidence, repairable=True, repair_options=candidates)
    remember_failure(result)
    return result


def diagnose_ide_generic() -> dict:
    editors = ["code", "codium", "subl", "gedit", "kate", "nano", "vim", "nvim"]
    found = [e for e in editors if shutil.which(e)]
    evidence = [f"editor search -> {', '.join(found) if found else 'none found'}"]
    if found:
        return _mk_result(True, "ide", "editor", "open", "IDE_OK",
                          evidence=evidence, repairable=False)
    candidates = [
        {"source": "snap", "label": "Install VS Code", "command": "sudo snap install code --classic"},
        {"source": "apt", "label": "Install gedit", "command": "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y gedit"},
        {"source": "flatpak", "label": "Install VS Codium (flatpak)", "command": "flatpak install -y flathub com.vscodium.codium"},
    ]
    result = _mk_result(False, "ide", "editor", "open", "NO_IDE_FOUND",
                        evidence=evidence, repairable=True, repair_options=candidates)
    remember_failure(result)
    return result


def build_repair_plan(result: dict) -> dict | None:
    if not result or not result.get("repairable"):
        return None

    if result.get("domain") == "application" and result.get("reason_code") == "NOT_INSTALLED":
        candidates = result.get("repair_options") or []
        if candidates:
            chosen = candidates[0]
            return {
                "id": f"install_{result['subject']}",
                "title": f"Install {result['subject']}",
                "domain": "application",
                "subject": result["subject"],
                "operation": "install",
                "risk": "low",
                "steps": [
                    f"Run the grounded install command for {result['subject']}",
                    "Verify that the application becomes locally discoverable after install",
                ],
                "commands": [chosen["command"]],
                "verification_steps": [f"check install state for {result['subject']}"],
                "source": chosen.get("source", "unknown"),
                "label": chosen.get("label", "Install " + str(result["subject"])),
            }

        app = str(result["subject"]).strip()
        search_install_cmd = (
            "bash -lc "
            + _q(
                f"""set -e
APP={_q(app)}

if command -v snap >/dev/null 2>&1 && snap info "$APP" >/dev/null 2>&1; then
  sudo snap install "$APP"
  exit 0
fi

if command -v apt-cache >/dev/null 2>&1; then
  PKG="$(apt-cache search --names-only "^$APP$" | awk 'NR==1{{print $1}}')"
  if [ -z "$PKG" ]; then
    PKG="$(apt-cache search --names-only "^$APP(-|$)" | awk 'NR==1{{print $1}}')"
  fi
  if [ -n "$PKG" ]; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG"
    exit 0
  fi
fi

if command -v flatpak >/dev/null 2>&1; then
  APPID="$(flatpak search "$APP" 2>/dev/null | awk 'tolower($1)==tolower(app){{print $1; exit}}' app="$APP")"
  if [ -n "$APPID" ]; then
    flatpak install -y flathub "$APPID"
    exit 0
  fi
fi

echo "No grounded install candidate found for $APP" >&2
exit 20"""
            )
        )

        return {
            "id": f"install_{result['subject']}",
            "title": f"Find and install {result['subject']}",
            "domain": "application",
            "subject": result["subject"],
            "operation": "install",
            "risk": "medium",
            "steps": [
                f"Search grounded package sources for an exact or prefix candidate matching {result['subject']}",
                "Install only an exact or prefix-matched candidate via snap, apt, or flatpak",
                "Use noninteractive apt defaults if apt is selected",
                "Verify that the application becomes locally discoverable after install",
            ],
            "commands": [search_install_cmd],
            "verification_steps": [f"check install state for {result['subject']}"],
            "source": "auto-search",
            "label": f"Find and install {result['subject']}",
        }

    if result.get("reason_code") == "PACKAGE_MANAGER_LOCKED":
        md = result.get("metadata") or {}
        retry_cmd = str(md.get("retry_command") or "").strip()
        holder_pid = str(md.get("holder_pid") or "").strip()
        holder_name = str(md.get("holder_name") or "").strip()

        if not retry_cmd:
            return None

        inspect_cmd = f"ps -fp {holder_pid}" if holder_pid else "ps -ef | grep -E 'apt|dpkg' | grep -v grep"

        if holder_pid:
            wait_and_retry_cmd = (
                "bash -lc "
                + _q(
                    f"""while ps -p {holder_pid} >/dev/null 2>&1; do
  sleep 2
done
{retry_cmd}"""
                )
            )
        else:
            wait_and_retry_cmd = retry_cmd

        return {
            "id": f"retry_pkg_lock_{result['subject']}",
            "title": f"Inspect package-manager lock and retry {result['subject']}",
            "domain": "package",
            "subject": result["subject"],
            "operation": "retry_install",
            "risk": "low",
            "steps": [
                "Inspect the process currently holding the apt/dpkg lock",
                "Wait for the lock holder to finish",
                "Retry the exact original install command",
                "Verify that the application becomes locally discoverable after install",
            ],
            "commands": [inspect_cmd, wait_and_retry_cmd],
            "verification_steps": [f"check install state for {result['subject']}"],
            "source": f"lock-holder:{holder_name or 'unknown'}",
            "label": f"Wait for package-manager lock and retry {result['subject']}",
        }

    if result.get("reason_code") == "PACKAGE_PROMPT_BLOCKED":
        md = result.get("metadata") or {}
        holder_pid = str(md.get("holder_pid") or "").strip()
        holder_name = str(md.get("holder_name") or "").strip()
        interactive_pid = str(md.get("interactive_pid") or "").strip()
        interactive_tty = str(md.get("interactive_tty") or "").strip()
        interactive_comm = str(md.get("interactive_comm") or "").strip()
        retry_cmd = str(md.get("retry_command") or "").strip()

        if not retry_cmd:
            return None

        retry_cmd = retry_cmd.replace("sudo apt-get", "sudo DEBIAN_FRONTEND=noninteractive apt-get")

        pids = [p for p in [interactive_pid, holder_pid] if p]
        inspect_cmd = "ps -fp " + " ".join(pids) if pids else "ps -ef | grep -E 'apt|dpkg|whiptail|dialog' | grep -v grep"
        kill_cmd = f"sudo kill -TERM {' '.join(pids)} 2>/dev/null || true" if pids else "true"

        wait_retry_cmd = (
            "bash -lc "
            + _q(
                f"""for i in $(seq 1 30); do
  alive=0
  {"ps -p " + holder_pid + " >/dev/null 2>&1 && alive=1" if holder_pid else "true"}
  {"ps -p " + interactive_pid + " >/dev/null 2>&1 && alive=1" if interactive_pid else "true"}
  if [ "$alive" -eq 0 ]; then
    break
  fi
  sleep 1
done
{retry_cmd}"""
            )
        )

        return {
            "id": f"resolve_pkg_prompt_{result['subject']}",
            "title": f"Terminate blocked package prompt and retry {result['subject']} noninteractively",
            "domain": "package",
            "subject": result["subject"],
            "operation": "retry_noninteractive_install",
            "risk": "medium",
            "steps": [
                f"Inspect the blocking interactive package prompt on {interactive_tty or 'unknown tty'}",
                "Terminate the blocked interactive prompt and lock holder",
                "Retry the original install command noninteractively with package defaults",
                "Verify that the application becomes locally discoverable after install",
            ],
            "commands": [inspect_cmd, kill_cmd, wait_retry_cmd],
            "verification_steps": [f"check install state for {result['subject']}"],
            "source": f"interactive-prompt:{interactive_comm or holder_name or 'unknown'}",
            "label": f"Terminate blocked package prompt and retry {result['subject']}",
        }

    if result.get("domain") == "filesystem" and result.get("reason_code") == "PATH_NOT_FOUND":
        md = result.get("metadata") or {}
        parent = str(md.get("parent") or "").strip()
        expanded = str(md.get("expanded") or result.get("subject") or "").strip()
        parent_exists = md.get("parent_exists", False)
        if parent_exists and expanded:
            return {
                "id": f"mkdir_{expanded.replace('/', '_')}",
                "title": f"Create directory: {expanded}",
                "domain": "filesystem",
                "subject": expanded,
                "operation": "create_dir",
                "risk": "low",
                "steps": [
                    f"Create the missing directory at {expanded}",
                    f"Open it in the file manager",
                ],
                "commands": [f"mkdir -p {_q(expanded)} && xdg-open {_q(expanded)}"],
                "verification_steps": [f"test -d {_q(expanded)}"],
                "source": "filesystem",
                "label": f"Create directory {expanded}",
            }
        return None

    if result.get("domain") in ("browser", "ide") and result.get("repairable"):
        candidates = result.get("repair_options") or []
        if not candidates:
            return None
        chosen = candidates[0]
        subj = str(result.get("subject") or result.get("domain") or "")
        return {
            "id": f"install_{subj.replace(' ', '_')}",
            "title": chosen.get("label", f"Install {subj}"),
            "domain": result["domain"],
            "subject": subj,
            "operation": "install",
            "risk": "low",
            "steps": [
                chosen.get("label", f"Install {subj}"),
                f"Verify that it becomes available after install",
            ],
            "commands": [chosen["command"]],
            "verification_steps": [f"command -v {subj}"],
            "source": chosen.get("source", "auto"),
            "label": chosen.get("label", f"Install {subj}"),
        }

    return None

def render_failure_message(result: dict) -> str:
    if not result:
        return "I cannot verify that because no grounded failure record exists."

    rc = result.get("reason_code")

    if rc == "NOT_INSTALLED":
        lead = f"Could not open {result['subject']}."
        reason = f"Verified reason: {result['subject']} is not installed on this machine."
    elif rc == "PACKAGE_MANAGER_LOCKED":
        lead = f"Repair blocked for {result['subject']}."
        reason = "Verified reason: another apt/dpkg process currently holds the package manager lock."
    elif rc == "PACKAGE_PROMPT_BLOCKED":
        lead = f"Repair is waiting for package configuration input for {result['subject']}."
        reason = "Verified reason: an interactive package-configuration prompt is currently blocking completion."
    elif rc == "LAUNCH_FAILED":
        lead = f"Could not open {result['subject']}."
        reason = "Verified reason: the open command failed, but I do not yet have a grounded launch stderr/exit-code trace for the cause."
    elif rc == "INSTALLED":
        lead = f"Status: {result['subject']} appears to be installed."
        reason = "Verified status: local application checks found an installed command, desktop entry, flatpak, or snap."
    elif rc == "PATH_NOT_FOUND":
        lead = f"Could not open folder: {result['subject']}."
        reason = "Verified reason: the path does not exist on this machine."
    elif rc == "NO_BROWSER_FOUND":
        lead = "No web browser was found on this machine."
        reason = "Verified reason: checked for Firefox, Chromium, Brave, and Epiphany — none installed."
    elif rc == "NO_IDE_FOUND":
        lead = "No code editor or IDE was found on this machine."
        reason = "Verified reason: checked for VS Code, Codium, Sublime Text, gedit, and Kate — none installed."
    else:
        lead = f"Could not complete: {result.get('operation', 'operation')} {result.get('subject', '')}."
        reason = f"Verified reason: {rc or 'UNKNOWN'}."

    lines = [lead, reason, "", "Evidence:"]
    for item in result.get("evidence") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)

def render_repair_preview(plan: dict) -> str:
    needs_priv = any(_needs_privileged_terminal(cmd) for cmd in plan.get("commands", []))
    lines = [
        f"Planned repair for {plan['subject']}:",
        "",
        f"Goal: {plan['title']}",
        "",
        "Steps:",
    ]
    for step in plan.get("steps", []):
        lines.append(f"- {step}")
    lines.extend(["", "Exact command(s):"])
    for cmd in plan.get("commands", []):
        lines.append(cmd)
    lines.extend([
        "",
        f"Source: {plan.get('source', 'unknown')}",
        f"Risk: {plan.get('risk', 'unknown')}",
        f"Requires privilege: {'yes' if needs_priv else 'no'}",
    ])
    if needs_priv:
        lines.extend([
            "",
            "On confirmation, ELI will open a visible terminal and run the exact privileged command there.",
        ])
    lines.extend([
        "",
        "Confirm repair?",
    ])
    return "\n".join(lines)

def offer_for_result(result: dict) -> str:
    msg = render_failure_message(result)
    plan = build_repair_plan(result)
    if plan:
        set_pending_for_test(plan, result, stage="offered")
        return msg + "\n\nWould you like me to download/install it?"
    return msg

def _render_exec_outcome(plan: dict, runs: list[dict], verify: dict) -> str:
    ok = all(r["rc"] == 0 for r in runs) and bool(verify.get("ok"))
    lines = ["Repair completed." if ok else "Repair failed.", ""]
    for r in runs:
        lines.append(f"Command: {r['cmd']}")
        lines.append(f"Exit code: {r['rc']}")
        if r["out"]:
            lines.append("stdout:")
            lines.append(r["out"])
        if r["err"]:
            lines.append("stderr:")
            lines.append(r["err"])
        lines.append("")
    lines.append("Verification:")
    for item in verify.get("evidence") or []:
        lines.append(f"- {item}")
    if not ok:
        lines.append("")
        lines.append("I did not invent a cause beyond the command output above.")
    return "\n".join(lines).strip()

def execute_pending_plan() -> str:
    pending = get_pending()
    if not pending:
        return "There is no pending repair to execute."

    plan = pending["plan"]
    prior_result = pending.get("result") or {}

    if plan.get("operation") == "retry_install":
        md = prior_result.get("metadata") or {}
        holder_pid = str(md.get("holder_pid") or "").strip()
        holder_name = str(md.get("holder_name") or "").strip()
        retry_command = str(md.get("retry_command") or "").strip()

        prompt = _find_interactive_pkg_prompt()
        if prompt.get("found"):
            prompt_result = _mk_result(
                False,
                "package",
                plan.get("subject", ""),
                "retry_install",
                "PACKAGE_PROMPT_BLOCKED",
                evidence=[
                    f"interactive prompt -> pid {prompt.get('pid')} tty {prompt.get('tty')} comm {prompt.get('comm')}",
                    f"interactive prompt args -> {prompt.get('args')}",
                    f"lock holder process -> {holder_pid} ({holder_name})" if holder_pid else "lock holder process -> unknown",
                ],
                repairable=True,
                metadata={
                    "holder_pid": holder_pid,
                    "holder_name": holder_name,
                    "interactive_pid": str(prompt.get("pid") or ""),
                    "interactive_tty": str(prompt.get("tty") or ""),
                    "interactive_comm": str(prompt.get("comm") or ""),
                    "interactive_args": str(prompt.get("args") or ""),
                    "retry_command": retry_command,
                },
            )
            remember_failure(prompt_result)
            prompt_plan = build_repair_plan(prompt_result)

            if prompt_plan:
                set_pending_for_test(prompt_plan, prompt_result, stage="offered")
                return (
                    render_failure_message(prompt_result)
                    + "\n\nWould you like me to terminate the blocked package configuration and retry noninteractively?"
                )

            clear_pending()
            return render_failure_message(prompt_result)

    runs = []

    set_busy(True)
    try:
        for cmd in plan.get("commands", []):
            if _needs_privileged_terminal(cmd):
                run_result = _run_in_terminal(cmd)
                run_result["handoff"] = "terminal"
                runs.append(run_result)
            else:
                run_result = _run(cmd)
                run_result["handoff"] = "direct"
                runs.append(run_result)
    finally:
        set_busy(False)

    for run in runs:
        if _is_pkg_lock_error(run):
            meta = _extract_pkg_lock_metadata(run)
            lock_result = _mk_result(
                False,
                "package",
                plan.get("subject", ""),
                plan.get("operation", "install"),
                "PACKAGE_MANAGER_LOCKED",
                evidence=_package_lock_evidence(run),
                repairable=True,
                metadata={
                    "retry_command": plan.get("commands", [])[-1] if plan.get("commands") else "",
                    "holder_pid": meta.get("holder_pid", ""),
                    "holder_name": meta.get("holder_name", ""),
                },
            )
            remember_failure(lock_result)
            lock_plan = build_repair_plan(lock_result)

            write_incident({
                "kind": "repair_execution",
                "plan": plan,
                "runs": runs,
                "verify": {"ok": False, "reason_code": "PACKAGE_MANAGER_LOCKED"},
            })

            if lock_plan:
                set_pending_for_test(lock_plan, lock_result, stage="offered")
                return (
                    render_failure_message(lock_result)
                    + "\n\nWould you like me to inspect the lock holder, wait for it to finish, and retry?"
                )

            clear_pending()
            return render_failure_message(lock_result)

    if plan.get("domain") in {"application", "package"} and plan.get("subject"):
        verify = diagnose_app(plan["subject"])
    else:
        verify = _mk_result(
            True,
            plan.get("domain", "unknown"),
            plan.get("subject", ""),
            "verify",
            "VERIFICATION_SKIPPED",
            evidence=["No verifier is defined for this plan."],
        )

    write_incident({
        "kind": "repair_execution",
        "plan": plan,
        "runs": runs,
        "verify": verify,
    })

    clear_pending()
    return _render_exec_outcome(plan, runs, verify)

def handle_confirmation(text: str) -> str | None:
    if not _remediation_supported():
        return None
    pending = get_pending()
    if not pending:
        return None

    if NO_RE.match(text or ""):
        clear_pending()
        return "Cancelled. I did not change anything."

    if YES_RE.match(text or ""):
        if pending["stage"] == "offered":
            with _LOCK:
                pending["stage"] = "previewed"
                _save_pending_state(pending)
            return render_repair_preview(pending["plan"])
        if pending["stage"] == "previewed":
            return execute_pending_plan()
        return "There is no executable pending stage right now."
    return None

def explain_last_failure(subject: str | None = None) -> str:
    last = get_last_failure()
    if not last:
        return "I cannot verify a previous failure because no grounded failure record exists."
    if subject and str(subject).strip():
        if str(last.get("subject", "")).lower() != extract_app_name(subject).lower():
            return "I have a grounded failure record, but it does not match that subject."
    msg = render_failure_message(last)
    plan = build_repair_plan(last)
    if plan:
        set_pending_for_test(plan, last, stage="offered")
        msg += "\n\nWould you like me to download/install it?"
    return msg

def status_message_for_app(app: str) -> str:
    result = diagnose_app(app)
    if result["ok"]:
        return render_failure_message(result)
    return offer_for_result(result)

def is_operational_query(query: str) -> bool:
    q = (query or "").strip().lower()
    patterns = [
        r"^(open|run|launch|start)\b",
        r"^(is|check|confirm)\b",
        r"^why\b.*\b(open|run|failed|error)\b",
        r"^(fix|repair|resolve)\b",
        r"\binstalled\b",
        r"\berror\b",
        r"\btraceback\b",
        r"\bmodule\b",
        r"\bimport\b",
        r"\bpackage\b",
    ]
    return any(re.search(p, q) for p in patterns)

def block_ungrounded_operational_output(query: str, text: str) -> str | None:
    q = query or ""
    t = text or ""
    if not is_operational_query(q):
        return None
    allowed_prefixes = (
        "Could not ",
        "Status:",
        "Cancelled.",
        "Planned repair",
        "Repair completed.",
        "Repair failed.",
        "I cannot verify",
    )
    if t.startswith(allowed_prefixes):
        return None
    return "I cannot verify that yet because no grounded system check has been completed."

def capture_executor_failure(action: str, args: dict | None, result) -> str | None:
    """Record a grounded failure and return an offer string when remediation is available."""
    if not _remediation_supported():
        return None
    if not isinstance(result, dict):
        return None
    if result.get("ok", True):
        return None

    args = args or {}
    message = str(result.get("message") or result.get("response") or "").strip()
    a = str(action)

    if a == "OPEN_APP":
        subject = extract_app_name(
            str(args.get("app") or args.get("name") or args.get("target") or args.get("message") or args.get("query") or "")
        )
        if subject:
            diag = diagnose_app(subject)
            if not diag.get("ok"):
                remember_failure(diag)
                return offer_for_result(diag)
            remember_failure(_mk_result(
                False, "application", subject, "open", "LAUNCH_FAILED",
                evidence=[message or f"OPEN_APP failed for {subject} without grounded stderr/exit-code details."],
                repairable=False,
            ))
        return None

    if a == "OPEN_IDE":
        subject = extract_app_name(
            str(args.get("app") or args.get("name") or args.get("target") or "")
        )
        if subject:
            diag = diagnose_app(subject)
        else:
            diag = diagnose_ide_generic()
        if not diag.get("ok"):
            remember_failure(diag)
            return offer_for_result(diag)
        return None

    if a == "OPEN_FILE_SYSTEM":
        path = str(args.get("path") or args.get("target") or args.get("name") or "")
        diag = diagnose_path(path)
        if not diag.get("ok"):
            remember_failure(diag)
            return offer_for_result(diag)
        return None

    if a in ("OPEN_BROWSER", "OPEN_URL"):
        target = str(args.get("url") or args.get("target") or args.get("name") or "")
        diag = diagnose_browser(target)
        if not diag.get("ok"):
            remember_failure(diag)
            return offer_for_result(diag)
        return None

    remember_failure(_mk_result(
        False, "executor", str(args.get('subject') or args.get('query') or action),
        str(action), "EXECUTOR_FAILURE",
        evidence=[message or f"Action {action} failed without grounded detail."],
        repairable=False,
    ))
    return None

def as_executor_result(message: str, ok: bool = False) -> dict:
    return {
        "ok": ok,
        "handled": True,
        "message": message,
        "response": message,
    }

def try_handle_query(text: str) -> str | None:
    if not _remediation_supported():
        return None
    raw = (text or "").strip()
    if not raw:
        return None

    # ---- Pending-repair confirmation intercept --------------------------
    # Consume YES/NO answers against any pending repair state before falling
    # through to open/check/install dispatch below.
    # Uses both exact match (YES_RE/NO_RE) and fuzzy word-in-input matching
    # to tolerate STT noise like "confirmed yes" or "namagem1 yes".
    _YES_WORD = re.compile(r'\b(yes|y|yeah|yep|confirm|confirmed|go ahead|do it|proceed|install it|download it)\b', re.I)
    _NO_WORD  = re.compile(r'\b(no|n|cancel|stop|abort|never mind|dont|don\'t)\b', re.I)
    pending = get_pending()
    if pending:
        stage = str(pending.get("stage") or "").strip().lower()
        _is_yes = bool(YES_RE.match(raw) or _YES_WORD.search(raw))
        _is_no  = bool(NO_RE.match(raw) or _NO_WORD.search(raw))
        # YES takes priority over NO when both appear (e.g. "yes no wait")
        if _is_yes and stage in {"offered", "pending", "proposed"}:
            with _LOCK:
                pending["stage"] = "previewed"
                globals()["_PENDING"] = pending
                _save_pending_state(pending)
            return render_repair_preview(pending.get("plan") or {})
        if _is_yes and stage == "previewed":
            return execute_pending_plan()
        if _is_no and stage in {"offered", "previewed", "pending", "proposed"}:
            clear_pending()
            return "Cancelled."

    # ---- "install X" / "download X" explicit commands ------------------
    # Handles both:
    #   (a) user confirming a pending offer by naming the app directly
    #       e.g. "install netflix" after ELI asked about installing netflix
    #   (b) fresh direct install request with no prior pending state
    _idm = re.match(r"^\s*(install|download|get|setup|set up)\s+(.+?)\s*$", raw, re.I)
    if _idm:
        subject = extract_app_name(_idm.group(2).strip())
        _pending = get_pending()
        if _pending:
            _plan = _pending.get("plan") or {}
            _stage = str(_pending.get("stage") or "").strip().lower()
            if str(_plan.get("subject", "")).lower() == subject.lower():
                # App matches the pending offer — advance the plan
                if _stage in {"offered", "pending", "proposed"}:
                    _pending["stage"] = "previewed"
                    globals()["_PENDING"] = _pending
                    _save_pending_state(_pending)
                    return render_repair_preview(_plan)
                if _stage == "previewed":
                    return execute_pending_plan()
        # No matching pending state — diagnose and offer
        diag = diagnose_app(subject)
        if not diag.get("ok"):
            return offer_for_result(diag)
        return f"{subject} appears to be already installed on this machine."

    m = re.match(r"^\s*(open|run|launch|start)\s+(.+?)\s*$", raw, re.I)
    if m:
        raw_subject = m.group(2).strip()
        subject = extract_app_name(raw_subject)

        if (
            raw_subject.startswith("/")
            or raw_subject.startswith("~/")
            or re.search(r"\b(folder|directory|path)\b", raw_subject, re.I)
            or raw_subject.lower() in {"trash", "home", "home directory"}
        ):
            return None

        diag = diagnose_app(subject)
        if not diag.get("ok"):
            return offer_for_result(diag)
        return None
        return explain_last_failure(m.group(1))

    m = re.match(r"^\s*(?:can you\s+)?(?:check|confirm)(?:\s+if)?\s+(.+?)\s+(?:is\s+)?(?:actually\s+)?(?:installed|on this machine|available|present)(?:\s+or\s+not)?\s*\??\s*$", raw, re.I)
    if m:
        return status_message_for_app(m.group(1))

    m = re.match(r"^\s*is\s+(.+?)\s+(?:installed|available|present)\s*\??\s*$", raw, re.I)
    if m:
        return status_message_for_app(m.group(1))

    m = re.match(r"^\s*(open|run|launch|start)\s+(.+?)\s*$", raw, re.I)
    if m:
        subject = extract_app_name(m.group(2))
        diag = diagnose_app(subject)
        if not diag.get("ok"):
            return offer_for_result(diag)
        return None

    if re.match(r"^\s*(fix|repair|resolve)(?:\s+this|\s+that|\s+it)?\s*$", raw, re.I):
        last = get_last_failure()
        if not last:
            return "I cannot verify what to repair because there is no grounded failure record yet."
        plan = build_repair_plan(last)
        if not plan:
            return render_failure_message(last)
        set_pending_for_test(plan, last, stage="offered")
        return render_failure_message(last) + "\n\nWould you like me to download/install it?"

    return None
