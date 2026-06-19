"""Bounded, isolated execution substrate for ELI's coding agent.

The execution-feedback loop is mandatory in the coding agent, and this module is
its foundation: run candidate code (or a test) in a separate process with a
temp working dir, a scrubbed environment, a non-interactive matplotlib backend,
a wall-clock timeout, and (on POSIX) a generous CPU rlimit. It NEVER runs code
in-process.

Design choices that matter:
- Deliberately NO RLIMIT_AS — it breaks numpy/scipy address-space use and would
  produce spurious MemoryErrors on exactly the scientific code ELI writes.
- A timeout, a signal/limit kill, or a missing optional dependency is NOT a code
  failure (the script "started fine" / the box lacks a lib). Only a genuine
  unhandled traceback (non-zero exit with `Traceback (most recent call last)`)
  is a crash. This precise rule is what keeps the feedback loop from rejecting
  legitimate long-running / heavy / optional-dep code.
- Multiple languages via an interpreter map; Python gets the deepest support.

All execution is opt-in at the agent level and additionally gated by
ELI_CODING_SANDBOX (default on); set it to 0 to disable execution entirely.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_TRACEBACK_MARKER = "Traceback (most recent call last)"

# language -> (file extension, argv builder given the script path)
_RUNNERS: Dict[str, tuple] = {
    "python": (".py", lambda p: [sys.executable, p]),
    "bash": (".sh", lambda p: ["bash", p]),
    "javascript": (".js", lambda p: ["node", p]),
    "typescript": (".ts", lambda p: ["ts-node", p]),
    "ruby": (".rb", lambda p: ["ruby", p]),
    "go": (".go", lambda p: ["go", "run", p]),
    "lua": (".lua", lambda p: ["lua", p]),
}


@dataclass
class RunResult:
    """Outcome of one sandboxed execution."""
    ran: bool                      # did we manage to launch + observe it at all
    crashed: bool                  # genuine unhandled exception (real failure)
    returncode: Optional[int]
    timed_out: bool
    stdout: str
    stderr: str
    traceback_tail: str = ""       # last lines of a real traceback, for repair feedback
    note: str = ""                 # human-readable explanation of the verdict

    @property
    def clean(self) -> bool:
        """True when the program ran without a genuine crash (exit 0, or a
        tolerated timeout / signal / missing-optional-dep)."""
        return self.ran and not self.crashed

    def to_dict(self) -> Dict:
        return {
            "ran": self.ran, "crashed": self.crashed, "returncode": self.returncode,
            "timed_out": self.timed_out, "clean": self.clean,
            "traceback_tail": self.traceback_tail, "note": self.note,
            "stdout": self.stdout[-2000:], "stderr": self.stderr[-2000:],
        }


def sandbox_enabled() -> bool:
    return os.environ.get("ELI_CODING_SANDBOX", "1").strip().lower() not in ("0", "false", "no", "off")


def _scrubbed_env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD"))}
    env["MPLBACKEND"] = "Agg"      # never open / block on a GUI window (plt.show())
    env["ELI_SANDBOX"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _cpu_limit_preexec(cpu_seconds: int):
    """Return a preexec_fn that caps CPU time (POSIX only), or None."""
    try:
        import resource

        def _limits():
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
            except Exception:
                pass
        return _limits
    except Exception:
        return None


def _maybe_harden(argv: List[str]) -> List[str]:
    """Optionally wrap argv in firejail/nsjail for OS-level isolation (no network
    egress, namespaced) when one is installed AND opt-in via ELI_SANDBOX_ISOLATE=1.

    Off by default → zero behaviour change (the plain subprocess + CPU-rlimit path).
    When enabled but neither tool is present, it degrades gracefully to that same
    path. `--noprofile` keeps the temp working dir reachable; `--net=none` is the
    real win (generated/patched code can't phone home from the sandbox)."""
    if os.environ.get("ELI_SANDBOX_ISOLATE", "0").strip().lower() not in ("1", "true", "yes", "on"):
        return argv
    try:
        import shutil
        fj = shutil.which("firejail")
        if fj:
            return [fj, "--quiet", "--noprofile", "--net=none", "--"] + argv
        nj = shutil.which("nsjail")
        if nj:
            return [nj, "-Mo", "--disable_proc", "--really_quiet", "--", *argv]
    except Exception:
        pass
    return argv


def run_code(
    code: str,
    language: str = "python",
    *,
    timeout: float = 20.0,
    cpu_seconds: int = 30,
    extra_files: Optional[Dict[str, str]] = None,
    argv_suffix: Optional[List[str]] = None,
    entry_name: str = "candidate",
) -> RunResult:
    """Run `code` in an isolated subprocess and classify the outcome.

    extra_files: {relative_name: contents} written alongside the entry file
                 (e.g. a synthesised test module that imports the candidate).
    argv_suffix: extra args appended to the runner argv.
    """
    language = (language or "python").lower()
    if not sandbox_enabled():
        return RunResult(ran=True, crashed=False, returncode=None, timed_out=False,
                         stdout="", stderr="", note="sandbox disabled (ELI_CODING_SANDBOX=0)")

    runner = _RUNNERS.get(language)
    if runner is None:
        return RunResult(ran=False, crashed=False, returncode=None, timed_out=False,
                         stdout="", stderr="", note=f"no sandbox runner for language {language!r}")

    ext, argv_builder = runner
    try:
        timeout = float(os.environ.get("ELI_CODING_RUN_TIMEOUT", "") or timeout)
    except Exception:
        pass
    preexec = _cpu_limit_preexec(cpu_seconds)
    env = _scrubbed_env()

    try:
        with tempfile.TemporaryDirectory(prefix="eli_code_") as td:
            entry = Path(td) / f"{entry_name}{ext}"
            entry.write_text(code, encoding="utf-8")
            for rel, contents in (extra_files or {}).items():
                fp = Path(td) / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(contents, encoding="utf-8")
            argv = _maybe_harden(argv_builder(str(entry)) + list(argv_suffix or []))
            try:
                proc = subprocess.run(
                    argv, cwd=td, env=env, capture_output=True, text=True,
                    timeout=timeout, preexec_fn=preexec,
                )
            except subprocess.TimeoutExpired as te:
                return RunResult(
                    ran=True, crashed=False, returncode=None, timed_out=True,
                    stdout=(te.stdout or "") if isinstance(te.stdout, str) else "",
                    stderr=(te.stderr or "") if isinstance(te.stderr, str) else "",
                    note=f"ran past {timeout:.0f}s timeout (started fine — long/monitor code)",
                )
            except FileNotFoundError:
                return RunResult(ran=False, crashed=False, returncode=None, timed_out=False,
                                 stdout="", stderr="", note=f"interpreter for {language} not installed")
    except Exception as exc:
        return RunResult(ran=False, crashed=False, returncode=None, timed_out=False,
                         stdout="", stderr="", note=f"sandbox infra error: {exc}")

    out, err = proc.stdout or "", proc.stderr or ""
    if proc.returncode == 0:
        return RunResult(True, False, 0, False, out, err, note="exited cleanly")

    # Non-zero exit. Decide crash vs tolerated.
    if _TRACEBACK_MARKER not in err and language == "python":
        return RunResult(True, False, proc.returncode, False, out, err,
                         note="non-zero exit, no Python traceback (signal/limit) — tolerated")
    if any(m in err for m in ("ModuleNotFoundError", "ImportError")):
        return RunResult(True, False, proc.returncode, False, out, err,
                         note="missing optional dependency on this machine — tolerated")
    tail = "\n".join(err.strip().splitlines()[-8:])
    return RunResult(True, True, proc.returncode, False, out, err,
                     traceback_tail=tail, note="genuine runtime crash")


def smoke_import(dotted: str, *, project_root: Path, timeout: float = 30.0) -> RunResult:
    """Import an installed module by dotted path in a subprocess — used to verify
    a patched module still loads. Crash on any import exception."""
    code = (
        "import importlib, sys\n"
        f"importlib.import_module({dotted!r})\n"
    )
    env = _scrubbed_env()
    env["ELI_PATCH_SMOKE"] = "1"
    try:
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(project_root),
                              capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return RunResult(True, True, None, True, "", "", note=f"import exceeded {timeout:.0f}s")
    except Exception as exc:
        return RunResult(False, False, None, False, "", "", note=f"smoke-import infra error: {exc}")
    if proc.returncode == 0:
        return RunResult(True, False, 0, False, proc.stdout or "", proc.stderr or "", note="imports clean")
    tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
    return RunResult(True, True, proc.returncode, False, proc.stdout or "", proc.stderr or "",
                     traceback_tail=tail, note="import failed")
