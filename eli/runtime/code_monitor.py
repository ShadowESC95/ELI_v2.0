"""
brain.awareness.code_monitor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Detects changes in Eli's source tree via git diff, classifies them
by subsystem, generates natural-language summaries for memory storage
and cognitive context injection.

No background threads — called on boot and on demand.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from eli.runtime.proposal_adapters import safe_git_completed

log = logging.getLogger(__name__)

# Files/dirs we never report on
_IGNORE = {
    "__pycache__", ".pyc", ".egg-info", ".pytest_cache",
    "node_modules", ".git/", ".venv/", ".bak_", "_graveyard",
    "unsloth_compiled_cache", ".gguf", ".safetensors",
    ".onnx", ".sqlite3", ".cpython-",
}

# Map path prefixes to human-readable subsystem names.
_SUBSYSTEM = {
    "eli/cognition":     "cognitive engine",
    "eli/kernel":        "kernel / engine",
    "eli/memory":        "memory system",
    "eli/planning":      "planning / proactive daemon",
    "eli/runtime":       "runtime authority / remediation",
    "eli/perception":    "perception / audio / OS controller",
    "eli/execution":     "executor / action handlers / router",
    "tools/registry":    "capability registry",
    "tools/analysis":    "analysis tools",
    "tools/documents":   "document generator",
    "tools/io":          "I/O (TTS, STT, clipboard)",
    "tools/media":       "media tools",
    "plugins/":          "plugins",
    "gui/":              "GUI",
    "core/":             "core runtime / config",
    "tests/":            "test suite",
    "config/":           "configuration",
    "scripts/":          "scripts",
}


class FileChange:
    __slots__ = ("path", "change_type", "subsystem", "lines_added", "lines_removed")

    def __init__(self, path: str, change_type: str, subsystem: str = "",
                 lines_added: int = 0, lines_removed: int = 0):
        self.path = path
        self.change_type = change_type
        self.subsystem = subsystem
        self.lines_added = lines_added
        self.lines_removed = lines_removed


class ChangeReport:
    __slots__ = ("changes", "timestamp", "git_ref", "prev_ref", "method")

    def __init__(self):
        self.changes: List[FileChange] = []
        self.timestamp: float = 0.0
        self.git_ref: str = ""
        self.prev_ref: str = ""
        self.method: str = "git"

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    @property
    def file_count(self) -> int:
        return len(self.changes)

    def by_subsystem(self) -> Dict[str, List[FileChange]]:
        groups: Dict[str, List[FileChange]] = {}
        for ch in self.changes:
            groups.setdefault(ch.subsystem or "other", []).append(ch)
        return dict(sorted(groups.items()))

    def summary(self) -> str:
        """One-liner for memory storage."""
        if not self.changes:
            return "No code changes detected."
        groups = self.by_subsystem()
        total_add = sum(f.lines_added for f in self.changes)
        total_rem = sum(f.lines_removed for f in self.changes)
        net = total_add - total_rem
        parts = []
        for subsys, files in groups.items():
            a = sum(f.lines_added for f in files)
            r = sum(f.lines_removed for f in files)
            lbl = f"+{a}" if not r else f"+{a}/-{r}"
            parts.append(f"{subsys} ({lbl} in {len(files)} file{'s' if len(files) != 1 else ''})")
        return (
            f"{self.file_count} file{'s' if self.file_count != 1 else ''} changed: "
            f"{', '.join(parts)}. Net {'+' if net >= 0 else ''}{net} lines."
        )

    def cognitive_briefing(self) -> str:
        """Richer text for cognitive engine context injection."""
        if not self.changes:
            return "No code changes since last check."
        lines = [f"Code changes ({self.method}, ref {self.git_ref or 'n/a'}):"]
        for subsys, files in self.by_subsystem().items():
            lines.append(f"  [{subsys}]")
            for f in sorted(files, key=lambda x: abs(x.lines_added - x.lines_removed), reverse=True)[:6]:
                tag = {"added": "+", "deleted": "−", "modified": "Δ", "renamed": "→"}.get(f.change_type, "?")
                lines.append(f"    {tag} {f.path}  (+{f.lines_added}/-{f.lines_removed})")
            if len(files) > 6:
                lines.append(f"    … and {len(files) - 6} more")
        lines.append(self.summary())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify(path: str) -> str:
    for prefix, label in _SUBSYSTEM.items():
        if path.startswith(prefix):
            return label
    return "other"


def _ignore(path: str) -> bool:
    return any(pat in path for pat in _IGNORE)


def _git_ok(repo: Path) -> bool:
    try:
        r = safe_git_completed(["git", "rev-parse", "--is-inside-work-tree"],
                           cwd=repo, capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _git_head(repo: Path) -> str:
    try:
        r = safe_git_completed(["git", "rev-parse", "--short", "HEAD"],
                           cwd=repo, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""


def _git_diff(repo: Path, since: str) -> List[FileChange]:
    changes: List[FileChange] = []
    # numstat
    r1 = safe_git_completed(
        ["git", "diff", "--numstat", "--diff-filter=ACDMR", since, "HEAD"],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    stats: Dict[str, tuple] = {}
    for line in (r1.stdout or "").strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            a = int(parts[0]) if parts[0] != "-" else 0
            d = int(parts[1]) if parts[1] != "-" else 0
            stats[parts[2]] = (a, d)
    # name-status
    r2 = safe_git_completed(
        ["git", "diff", "--name-status", "--diff-filter=ACDMR", since, "HEAD"],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    type_map = {"A": "added", "C": "added", "D": "deleted", "M": "modified", "R": "renamed"}
    for line in (r2.stdout or "").strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        ct = type_map.get(parts[0][0], "modified")
        path = parts[-1]
        if _ignore(path):
            continue
        add, rem = stats.get(path, (0, 0))
        changes.append(FileChange(
            path=path, change_type=ct, subsystem=_classify(path),
            lines_added=add, lines_removed=rem,
        ))
    return changes


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CodeMonitor:
    """
    Detects what changed in Eli's source tree since last check.

    Usage:
        mon = CodeMonitor()
        report = mon.check()
        if report.has_changes:
            print(report.summary())
    """

    STATE_FILE = ".code_monitor_state.json"

    def __init__(self, repo_root: Optional[Path] = None):
        if repo_root is None:
            try:
                from eli.core.paths import get_paths
                repo_root = get_paths().project_root
            except Exception:
                repo_root = Path(__file__).resolve().parents[3]
        self.repo_root = Path(repo_root)
        self.state_path = self.repo_root / self.STATE_FILE
        self.use_git = _git_ok(self.repo_root)

    def check(self) -> ChangeReport:
        """Single check pass. Updates saved state."""
        state = self._load_state()
        report = ChangeReport()
        report.timestamp = time.time()

        if not self.use_git:
            report.method = "unavailable"
            return report

        report.method = "git"
        report.git_ref = _git_head(self.repo_root)
        report.prev_ref = state.get("git_ref", "")

        if report.prev_ref and report.prev_ref != report.git_ref:
            report.changes = _git_diff(self.repo_root, report.prev_ref)
        elif not report.prev_ref:
            # First run — show changes in last commit
            try:
                report.changes = _git_diff(self.repo_root, "HEAD~1")
            except Exception:
                pass

        self._save_state({"git_ref": report.git_ref, "timestamp": report.timestamp})
        return report

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, data: Dict[str, Any]) -> None:
        try:
            self.state_path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except Exception as exc:
            log.warning("code_monitor: state save failed: %s", exc)
