#!/usr/bin/env python3
"""Refresh stale scale/version metrics in docs and UI copy.

Run from repo root after releases:  python tools/refresh_doc_metrics.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = list(ROOT.glob("**/*.md")) + [ROOT / "eli/gui/panels/startup.py"]
SKIP_PARTS = ("/.venv/", "/models/", "/.claude/", "/node_modules/", "/build/")

# Order matters — longer / more specific patterns first.
REPLACEMENTS: list[tuple[str, str]] = [
    ("Updated for v2.3.72 (September 2026)", "Updated for v2.3.73 (September 2026)"),
    ("Updated for v2.3.55 (August 2026)", "Updated for v2.3.73 (September 2026)"),
    ("Updated for v2.3.44 (August 2026)", "Updated for v2.3.73 (September 2026)"),
    ("Updated for v2.3.72.", "Updated for v2.3.73."),
    ("Updated for v2.3.55.", "Updated for v2.3.73."),
    ("Updated for v2.3.44.", "Updated for v2.3.73."),
    ("Release **v2.3.44** on GitHub", "Release **v2.3.73** on GitHub"),
    ("Current release: v2.3.72 (September 2026)", "Current release: v2.3.73 (September 2026)"),
    ("Current release: v2.3.58 (August 2026)", "Current release: v2.3.73 (September 2026)"),
    ("Builds on v2.3.71.", "Builds on v2.3.73."),
    ("Builds on v2.3.56.", "Builds on v2.3.73."),
    ("Last updated 2026-09-01 (v2.3.72)", "Last updated 2026-09-01 (v2.3.73)"),
    ("Last updated 2026-08-30 (v2.3.53)", "Last updated 2026-09-01 (v2.3.73)"),
    ("Last updated 2026-08-28 (v2.3.32)", "Last updated 2026-09-01 (v2.3.73)"),
    ("Audited at v2.3.72 (September 2026)", "Audited at v2.3.73 (September 2026)"),
    ("Audited at v2.3.44 (August 2026)", "Audited at v2.3.73 (September 2026)"),
    ("Current suite at **v2.3.72**", "Current suite at **v2.3.73**"),
    ("Current suite at **v2.3.44**", "Current suite at **v2.3.73**"),
    ("Verified at v2.3.72:", "Verified at v2.3.73:"),
    ("Verified at v2.3.44:", "Verified at v2.3.73:"),
    ("Verified at v2.3.44: 11,067 collected", "Verified at v2.3.73: 11,358 collected"),
    ("Verified at v2.3.72: 11,351 collected", "Verified at v2.3.73: 11,358 collected"),
    ("11,351 tests collected across 412 files", "11,358 tests collected across 413 files"),
    ("11,067 tests collected across 393 files", "11,358 tests collected across 413 files"),
    ("11,351 tests collected", "11,358 tests collected"),
    ("11,067 tests collected", "11,358 tests collected"),
    ("11,351 collected / 11,300+", "11,358 collected / 11,300+"),
    ("11,067 collected / 11,000+", "11,358 collected / 11,300+"),
    ("11,351 collected", "11,358 collected"),
    ("11,067 collected", "11,358 collected"),
    ("11,000+ passing", "11,300+ passing"),
    ("11,000+ passed", "11,300+ passed"),
    ("412 files", "413 files"),
    ("412 test files", "413 test files"),
    ("393 files", "413 files"),
    ("~181k LOC", "~166k LOC"),
    ("181k-LOC", "~166k-LOC"),
    ("181,530 measured 2026-08-29", "166,397 measured 2026-09-01"),
    ("releases/tag/v2.3.72", "releases/tag/v2.3.73"),
    ("releases/tag/v2.3.55", "releases/tag/v2.3.73"),
    ("releases/tag/v2.3.58", "releases/tag/v2.3.73"),
    ("releases/download/v2.3.72/", "releases/download/v2.3.73/"),
    ("releases/download/v2.3.55/", "releases/download/v2.3.73/"),
    ("releases/download/v2.3.58/", "releases/download/v2.3.73/"),
    ("**Version:** 2.3.72", "**Version:** 2.3.73"),
    ("**Version:** 2.3.55", "**Version:** 2.3.73"),
    ("ELI-Setup-2.3.72", "ELI-Setup-2.3.73"),
    ("ELI-Setup-2.3.55", "ELI-Setup-2.3.73"),
    ("ELI_v2-2.3.72-", "ELI_v2-2.3.73-"),
    ("ELI_v2-2.3.55-", "ELI_v2-2.3.73-"),
    ("release v2.3.72", "release v2.3.73"),
    ("release v2.3.55", "release v2.3.73"),
    ("real v2.3.72 assets", "real v2.3.73 assets"),
    ("real v2.3.55 assets", "real v2.3.73 assets"),
    ("v2.3.72 AppImage", "v2.3.73 AppImage"),
    ("v2.3.55 AppImage", "v2.3.73 AppImage"),
    ("v2.3.72 release", "v2.3.73 release"),
    ("v2.3.55 release", "v2.3.73 release"),
    ("v2.3.72+", "v2.3.73+"),
    ("v2.3.55+", "v2.3.73+"),
    ("upgrade to **v2.3.72**", "upgrade to **v2.3.73**"),
    ("upgrade to **v2.3.55**", "upgrade to **v2.3.73**"),
    ("Fix (v2.3.72+):", "Fix (v2.3.73+):"),
    ("Fix (v2.3.55+):", "Fix (v2.3.73+):"),
    ("ELI v2.3.72.", "ELI v2.3.73."),
    ("ELI v2.3.58.", "ELI v2.3.73."),
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
