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
    ("Updated for v2.1.51 (August 2026)", "Updated for v2.3.30 (August 2026)"),
    ("143,432 LOC across 392 Python files", "180,098 LOC across 421 Python files"),
    ("~156,000 lines of Python across 392 files", "~180,000 lines of Python across 421 files (`eli/`)"),
    ("~156,000 lines of Python", "~180,000 lines of Python in `eli/`"),
    ("It is ~156,000 lines of Python", "It is ~180,000 lines of Python in `eli/`"),
    ("126k-LOC project", "180k-LOC project"),
    ("~160,000 lines of Python", "~180,000 lines of Python in `eli/`"),
    ("~160k LOC across 397 Python files", "~180k LOC across 421 Python files (`eli/`)"),
    ("~160k LOC across 397", "~180k LOC across 421"),
    ("~156k LOC · 392 files", "~180k LOC · 421 files"),
    ("eli/  (~156k LOC, 392 files)", "eli/  (~180k LOC, 421 files)"),
    ("~156k LOC", "~180k LOC"),
    ("~160k LOC", "~180k LOC"),
    ("~155k", "~180k"),
    ("392 Python files", "421 Python files"),
    ("392 files", "421 files"),
    ("397 Python files", "421 Python files"),
    ("205 test files", "389 test files"),
    ("313 test files", "389 test files"),
    ("313+ files", "389+ files"),
    ("~3,884 lines", "~2,309 lines"),
    ("3,884 lines", "2,309 lines"),
    ("215 manifest capabilities", "225 manifest capabilities"),
    ("one of **215 manifest capabilities**", "one of **225 manifest capabilities**"),
    ("209 entries as of 2026-08-21; 206 routable", "225 entries as of 2026-08-28; 208 routable"),
    ("208 (206 routable) is real", "225 (208 routable) is real"),
    ("209 entries (206 routable)", "225 entries (208 routable)"),
    ("201 executor `SUPPORTED_ACTIONS`", "204 executor `SUPPORTED_ACTIONS`"),
    ("201 executor actions, 208", "204 executor dispatch actions, 225"),
    ("201 executor actions", "204 executor dispatch actions"),
    ("**206 routable**", "**208 routable**"),
    ("199 of them routable", "208 of them routable"),
    ("223 capabilities, 199 of them routable", "225 capabilities, 208 of them routable"),
    ("223 capabilities", "225 capabilities"),
    ("223 dispatch actions / 223 capabilities", "204 dispatch actions / 225 capabilities"),
    ("223 dispatch actions", "204 dispatch actions (225 manifest)"),
    ("all 223 actions", "all 225 manifest actions"),
    ("223 actions by name", "225 manifest actions by name"),
    ("9,400+ tests across 313+ files", "10,950+ tests across 389+ files"),
    ("9,400+ passing", "10,894+ passing"),
    ("9,400+ tests", "10,950+ tests"),
    ("9,400 passed", "10,894 passed"),
    ("9,400-test", "10,950+ test"),
    ("Verified at v2.2.9: 9,400 passing, 313 files", "Verified at v2.3.30: 10,894+ passing, 389 files"),
    ("Current suite at **v2.2.9**", "Current suite at **v2.3.30**"),
    ("223 capabilities | `capability_manifest.json`", "225 capabilities | `capability_manifest.json`"),
    ("Last updated 2026-08-18 (v2.2.9)", "Last updated 2026-08-28 (v2.3.30)"),
    ("*(measured 2026-06-28.)*", "*(measured 2026-08-28.)*"),
    ("Tests are GREEN (measured 2026-07-01)", "Tests are GREEN (measured 2026-08-28)"),
    ("releases/tag/v2.1.51", "releases/tag/v2.3.30"),
    ("releases/download/v2.1.51/", "releases/download/v2.3.30/"),
    ("releases/download/v2.1.51", "releases/download/v2.3.30"),
    ("**Version:** 2.1.51", "**Version:** 2.3.30"),
    ("ELI-Setup-2.1.51", "ELI-Setup-2.3.30"),
    ("209 entries as of 2026-08-21; 206 routable", "225 entries as of 2026-08-28; 208 routable or executor-backed"),
    ("7,348 passed / 0 failed / 45 skipped / 2 xfailed** (~8m16s", "10,894 passed / 54 skipped / 2 xfailed** (~13.5 min"),
    ("180,098 LOC", "180,100 LOC"),
    ("14951", "15923"),
    ("13841", "15240"),
    ("12100", "12605"),
    ("7111", "8161"),
    ("15102", "15923"),
    ("13992", "15240"),
    ("7627", "8161"),
    (
        "HAL, TARS, Rick, GLaDOS,\nJARVIS — built as a base voice",
        "calm, robotic, energetic, synthetic, and refined — built as a base voice",
    ),
    (
        "**character voices** (HAL/TARS/Rick/GLaDOS/JARVIS)",
        "**voice styles** (calm / robotic / energetic / synthetic / refined)",
    ),
    (
        "HAL, TARS, Rick, GLaDOS, JARVIS built in",
        "calm, robotic, energetic, synthetic, and refined styles built in",
    ),
    (
        "| Built-in | HAL, TARS, Rick, GLaDOS, JARVIS |",
        "| Built-in styles | calm, robotic, energetic, synthetic, refined |",
    ),
    ("ELI_v2-2.1.51-", "ELI_v2-2.3.30-"),
    ("release v2.1.51", "release v2.3.30"),
    ("real v2.1.51 assets", "real v2.3.30 assets"),
    (
        "accents and character voices (HAL, JARVIS, GLaDOS…) are downloadable later ",
        "accents and generic voice styles (calm, robotic, synthetic…) are downloadable later ",
    ),
    (
        "choose `char:hal`, `char:tars`, `char:rick`, `char:glados` or `char:jarvis`",
        "choose `char:calm`, `char:robotic`, `char:energetic`, `char:synthetic`, or `char:refined`",
    ),
    ("~160 executor actions", "~204 executor dispatch actions"),
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
