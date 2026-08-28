#!/usr/bin/env python3
"""Refresh stale scale/version metrics in docs and UI copy.

Run from repo root after releases:  python tools/refresh_doc_metrics.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = list(ROOT.glob("**/*.md")) + [ROOT / "eli/gui/panels/startup.py"]
SKIP_PARTS = ("/.venv/", "/models/", "/.claude/", "/node_modules/")

# Order matters — longer / more specific patterns first.
REPLACEMENTS: list[tuple[str, str]] = [
    ("Updated for v2.3.30 (August 2026)", "Updated for v2.3.32 (August 2026)"),
    ("Updated for v2.3.31 (August 2026)", "Updated for v2.3.32 (August 2026)"),
    ("Last updated 2026-08-28 (v2.3.30)", "Last updated 2026-08-28 (v2.3.32)"),
    ("Audited at `34e7a22` (v2.3.30 release)", "Audited at `55acf3e` (v2.3.32 release)"),
    ("Current suite at **v2.3.30**", "Current suite at **v2.3.32**"),
    ("Verified at v2.3.30:", "Verified at v2.3.32:"),
    ("releases/tag/v2.3.30", "releases/tag/v2.3.32"),
    ("releases/download/v2.3.30/", "releases/download/v2.3.32/"),
    ("releases/download/v2.3.30", "releases/download/v2.3.32"),
    ("**Version:** 2.3.30", "**Version:** 2.3.32"),
    ("ELI-Setup-2.3.30", "ELI-Setup-2.3.32"),
    ("ELI_v2-2.3.30-", "ELI_v2-2.3.32-"),
    ("release v2.3.30", "release v2.3.32"),
    ("real v2.3.30 assets", "real v2.3.32 assets"),
    ("180,100 LOC", "180,364 LOC"),
    ("180,098 LOC", "180,364 LOC"),
    ("~180,000 lines of Python across 421 files (`eli/`)", "~180,364 lines of Python across 421 files (`eli/`)"),
    ("~180,000 lines of Python in `eli/`", "~180,364 lines of Python in `eli/`"),
    ("It is ~180,000 lines of Python in `eli/`", "It is ~180,364 lines of Python in `eli/`"),
    ("180k-LOC project", "~180k-LOC project"),
    ("10,950+ tests across 389+ files", "10,970 tests collected across 389 files"),
    ("10,894+ passing", "10,900+ passing"),
    ("10,894 passed", "10,900+ passed"),
    ("10,894+ tests", "10,970 tests"),
    ("Verified at v2.3.32: 10,900+ passing, 389 files", "Verified at v2.3.32: 10,970 collected / 10,900+ passing, 389 files"),
    ("10,950+ test", "10,970 test"),
    ("executor_enhanced.py` (15.9k LOC)", "executor_enhanced.py` (~15.9k LOC)"),
    ("`engine.py` (15.2k)", "`engine.py` (~15.2k)"),
    ("`gui/eli_pro_audio_gui_v2_0.py` (12.6k)", "`gui/eli_pro_audio_gui_v2_0.py` (~12.6k)"),
    ("`router_enhanced.py` (8.2k)", "`router_enhanced.py` (~8.2k)"),
    ("v2.3.30 AppImage", "v2.3.32 AppImage"),
    ("v2.3.30 release", "v2.3.32 release"),
    ("_DEFAULT_RELEASE_TAG", "_DEFAULT_RELEASE_TAG"),  # no-op anchor
]


def refresh_file(path: Path) -> bool:
    if any(s in str(path) for s in SKIP_PARTS):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    orig = text
    for old, new in REPLACEMENTS:
        if old == new:
            continue
        text = text.replace(old, new)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    changed = []
    for path in sorted(set(TARGETS)):
        if refresh_file(path):
            changed.append(path.relative_to(ROOT))
    print(f"Updated {len(changed)} files:")
    for p in changed:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
