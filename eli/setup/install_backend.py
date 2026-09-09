"""Cross-platform install backend — streams install.sh / install.ps1 into GUI progress."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from eli.setup.status import project_root

_PROGRESS_RE = re.compile(
    r"\[ELI-PROGRESS\]\s+phase=(?P<phase>\S+)\s+pct=(?P<pct>\d+)\s+msg=(?P<msg>.*)",
    re.IGNORECASE,
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Fallback keyword → (phase, pct) when explicit markers are absent
_LINE_HINTS: Tuple[Tuple[str, str, int], ...] = (
    ("Your system", "system", 8),
    ("Virtual environment", "venv", 12),
    ("Creating virtual environment", "venv", 14),
    ("Installing PyTorch", "torch", 22),
    ("llama-cpp", "llama", 35),
    ("Installing ELI v2.0", "eli", 55),
    ("Installing dependencies", "eli", 62),
    ("Seeded clean config", "database", 72),
    ("database architecture", "database", 78),
    ("Fetching a model", "model", 85),
    ("embedder", "assets", 88),
    ("voice", "assets", 90),
    ("Import verify", "finish", 95),
    ("Summary", "finish", 98),
    ("Android / Termux setup", "welcome", 5),
    ("Android setup complete", "finish", 100),
    ("Termux build packages", "system", 10),
    ("llama-cpp-python (CPU", "llama", 40),
    ("Initialising full database", "database", 75),
)


@dataclass
class InstallProgress:
    phase: str = "welcome"
    percent: int = 0
    message: str = ""
    log_lines: List[str] = field(default_factory=list)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def parse_install_line(line: str) -> Optional[InstallProgress]:
    clean = _strip_ansi(line)
    if not clean:
        return None
    m = _PROGRESS_RE.search(clean)
    if m:
        return InstallProgress(
            phase=m.group("phase"),
            percent=int(m.group("pct")),
            message=m.group("msg").strip(),
        )
    pct = None
    phase = None
    for hint, ph, p in _LINE_HINTS:
        if hint.lower() in clean.lower():
            phase, pct = ph, p
            break
    if phase is None:
        if clean.startswith("[OK]"):
            return InstallProgress(message=clean[4:].strip())
        if clean.startswith("[..]"):
            return InstallProgress(message=clean[4:].strip())
        if clean.startswith("[WARN]") or clean.startswith("[!]"):
            return InstallProgress(message=clean)
        return None
    msg = clean
    if clean.startswith("[OK]"):
        msg = clean[4:].strip()
    elif clean.startswith("[..]"):
        msg = clean[4:].strip()
    return InstallProgress(phase=phase, percent=pct or 0, message=msg)


def install_script_path(root: Optional[Path] = None) -> Path:
    root = root or project_root()
    from eli.setup.platform_profile import install_script_for_profile
    script, _cmd = install_script_for_profile(root)
    return script


def build_install_command(root: Optional[Path] = None) -> List[str]:
    root = root or project_root()
    from eli.setup.platform_profile import install_script_for_profile
    _script, cmd = install_script_for_profile(root)
    return cmd


def shutil_which(name: str) -> Optional[str]:
    import shutil
    return shutil.which(name)


def run_install_streaming(
    *,
    on_line: Callable[[str], None],
    on_progress: Callable[[InstallProgress], None],
    root: Optional[Path] = None,
    env: Optional[dict] = None,
) -> Tuple[int, str]:
    """Run the platform installer; invoke callbacks per line. Returns (exit_code, log_path)."""
    root = root or project_root()
    cmd = build_install_command(root)
    log_dir = root / "artifacts"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "install_gui.log"

    run_env = os.environ.copy()
    run_env["ELI_PROJECT_ROOT"] = str(root)
    run_env["PYTHONUNBUFFERED"] = "1"
    if env:
        run_env.update(env)

    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=run_env,
    )
    assert proc.stdout is not None
    lines: List[str] = []
    start = time.monotonic()
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n\r")
            lines.append(line)
            on_line(line)
            parsed = parse_install_line(line)
            if parsed:
                if parsed.percent <= 0 and lines:
                    elapsed = time.monotonic() - start
                    parsed.percent = min(95, int(5 + elapsed / 6))
                on_progress(parsed)
        proc.wait()
    except Exception as exc:
        proc.kill()
        proc.wait()
        raise RuntimeError(f"Install subprocess failed: {exc}") from exc

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(proc.returncode or 0), str(log_path)


def python3_available() -> Tuple[bool, str]:
    import shutil
    py = shutil.which("python3") or shutil.which("python")
    if not py:
        return False, ""
    try:
        out = subprocess.check_output(
            [py, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            text=True,
            timeout=15,
        ).strip()
        major, minor = (int(x) for x in out.split(".")[:2])
        if (major, minor) < (3, 10):
            return False, out
        return True, out
    except Exception as exc:
        return False, str(exc)


def qt_available() -> bool:
    try:
        from eli.gui.qt_compat import QApplication  # noqa: F401
        return True
    except Exception:
        return False
