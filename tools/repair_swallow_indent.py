#!/usr/bin/env python3
"""Repair except-handler indent after fix_silent_swallows.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in ROOT.glob("eli/**/*.py"):
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    for i in range(len(lines) - 1):
        stripped = lines[i].strip()
        if not stripped.startswith("except") or not stripped.endswith(":"):
            continue
        if "suppressed exception" not in lines[i + 1]:
            continue
        except_indent = len(lines[i]) - len(lines[i].lstrip())
        log_indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
        if log_indent <= except_indent:
            lines[i + 1] = " " * (except_indent + 4) + lines[i + 1].lstrip()
            changed = True
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
        print(f"repaired {path.relative_to(ROOT)}")
