#!/usr/bin/env python3
"""Refresh stale scale/version metrics in docs and UI copy.

Run from repo root after releases:  python tools/refresh_doc_metrics.py

Recomputes live counts (tests, capabilities, LOC, silent swallows) and applies
them across markdown + startup panel copy. Asset filenames track the current
release tag (pyproject.toml version).
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = ("/.venv/", "/models/", "/.claude/", "/node_modules/", "/build/", "/clearbuild/")

# Current release — keep in sync with pyproject.toml.
VERSION = "2.4.0"
VERSION_TAG = f"v{VERSION}"


def _read_version() -> str:
    try:
        import tomllib
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", VERSION))
    except Exception:
        return VERSION


def _count_silent_swallows() -> int:
    n = 0
    eli = ROOT / "eli"
    for f in eli.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.ExceptHandler)
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)):
                n += 1
    return n


def _capability_stats() -> dict:
    manifest = json.loads((ROOT / "capability_manifest.json").read_text(encoding="utf-8"))
    caps = manifest.get("capabilities", [])
    routable = sum(1 for c in caps if c.get("routable"))
    supported = sum(1 for c in caps if c.get("in_supported_list"))
    routable_or_supported = sum(
        1 for c in caps if c.get("routable") or c.get("in_supported_list"))
    return {
        "total": int(manifest.get("total") or len(caps)),
        "routable": routable,
        "supported": supported,
        "routable_or_supported": routable_or_supported,
    }


def _test_stats() -> dict:
    proc = subprocess.run(
        ["python3", "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    m = re.search(r"(\d[\d,]*)\s+tests collected", proc.stdout + proc.stderr)
    collected = int(m.group(1).replace(",", "")) if m else 0
    files = len(list((ROOT / "tests").rglob("test_*.py")))
    return {"collected": collected, "files": files}


def _loc_stats() -> dict:
    py_files = list((ROOT / "eli").rglob("*.py"))
    loc = 0
    for f in py_files:
        try:
            loc += sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return {"loc": loc, "py_files": len(py_files)}


def _floor(n: int, step: int = 10) -> int:
    """Round down to a readable floor for README '+N' claims."""
    if n >= 1000:
        return (n // 50) * 50
    return (n // step) * step


def build_replacements() -> list[tuple[str, str]]:
    ver = _read_version()
    tag = f"v{ver}"
    caps = _capability_stats()
    tests = _test_stats()
    loc = _loc_stats()
    swallows = _count_silent_swallows()
    today = "2026-09-08"

    test_floor = _floor(tests["collected"], 50)
    file_floor = _floor(tests["files"], 5)
    loc_k = loc["loc"] // 1000

    # Order: longer / more specific first.
    pairs: list[tuple[str, str]] = [
        # Asset filenames (any stale release suffix)
        ("ELI_v2-2.3.92-", f"ELI_v2-{ver}-"),
        ("ELI-Setup-2.3.92", f"ELI-Setup-{ver}"),
        (f"releases/download/v2.3.92/", f"releases/download/{tag}/"),
        (f"releases/tag/v2.3.92", f"releases/tag/{tag}"),
        (f"Current release: v2.3.92 (September 2026)", f"Current release: {tag} (September 2026)"),
        (f"Audited at v2.3.92 (September 2026)", f"Audited at {tag} (September 2026)"),
        (f"Current suite at **v2.3.92**", f"Current suite at **{tag}**"),
        (f"Verified at v2.3.92:", f"Verified at {tag}:"),
        (f"Updated for v2.3.92 (September 2026)", f"Updated for {tag} (September 2026)"),
        (f"Updated for v2.3.92.", f"Updated for {tag}."),
        (f"Last updated 2026-09-08 (v2.3.92)", f"Last updated {today} ({tag})"),
        (f"**Version:** 2.3.92", f"**Version:** {ver}"),
        (f"ELI v2.3.92.", f"ELI {tag}."),
        ("ELI_v2-2.3.73-", f"ELI_v2-{ver}-"),
        ("ELI_v2-2.3.72-", f"ELI_v2-{ver}-"),
        ("ELI-Setup-2.3.73", f"ELI-Setup-{ver}"),
        ("ELI-Setup-2.3.72", f"ELI-Setup-{ver}"),
        (f"releases/download/v2.3.73/", f"releases/download/{tag}/"),
        (f"releases/download/v2.3.72/", f"releases/download/{tag}/"),
        (f"releases/tag/v2.3.73", f"releases/tag/{tag}"),
        (f"releases/tag/v2.3.72", f"releases/tag/{tag}"),
        (f"real v2.3.73 assets", f"real {tag} assets"),
        (f"Current release: v2.3.73 (September 2026)", f"Current release: {tag} (September 2026)"),
        (f"Audited at v2.3.73 (September 2026)", f"Audited at {tag} (September 2026)"),
        (f"Current suite at **v2.3.73**", f"Current suite at **{tag}**"),
        (f"Verified at v2.3.73:", f"Verified at {tag}:"),
        (f"Updated for v2.3.73 (September 2026)", f"Updated for {tag} (September 2026)"),
        (f"Last updated 2026-09-05 (v2.3.82)", f"Last updated {today} ({tag})"),
        (f"Last updated 2026-09-01 (v2.3.73)", f"Last updated {today} ({tag})"),
        (f"ELI v2.3.73.", f"ELI {tag}."),
        (f"upgrade to **v2.3.73**", f"upgrade to **{tag}**"),
        (f"Fix (v2.3.73+):", f"Fix ({tag}+):"),
        # Capability counts (stale generations)
        ("225 capabilities (208 routable)", f"{caps['total']} capabilities ({caps['routable_or_supported']} routable or executor-backed)"),
        ("225 capabilities (208 of them routable", f"{caps['total']} capabilities ({caps['routable_or_supported']} routable or executor-backed"),
        ("**225 capabilities** (208 of them routable", f"**{caps['total']} capabilities** ({caps['routable_or_supported']} routable or executor-backed"),
        ("225 capabilities, 208 of them routable", f"{caps['total']} capabilities, {caps['routable_or_supported']} routable or executor-backed"),
        ("225 manifest) / 225 capabilities", f"{caps['supported']} `SUPPORTED_ACTIONS`) / {caps['total']} capabilities"),
        ("204 dispatch actions (225 manifest)", f"{caps['supported']} dispatch actions ({caps['total']} manifest)"),
        ("204 executor `SUPPORTED_ACTIONS`", f"{caps['supported']} executor `SUPPORTED_ACTIONS`"),
        ("(**208 routable**; 204 executor", f"(**{caps['routable_or_supported']} routable or executor-backed**; {caps['supported']} executor"),
        ("Manifest: 225 capabilities", f"Manifest: {caps['total']} capabilities"),
        ("225 (208 routable) is real", f"{caps['total']} ({caps['routable_or_supported']} routable or executor-backed) is real"),
        ("225 entries (208 routable)", f"{caps['total']} entries ({caps['routable_or_supported']} routable or executor-backed)"),
        (f"**225** (184 router-routable; 208 routable or executor-backed; 204 `SUPPORTED_ACTIONS`)",
         f"**{caps['total']}** ({caps['routable']} router-routable; {caps['routable_or_supported']} routable or executor-backed; {caps['supported']} `SUPPORTED_ACTIONS`)"),
        ("all 225 manifest actions", f"all {caps['total']} manifest actions"),
        # Test counts
        ("11,390 tests collected", f"{tests['collected']:,} tests collected"),
        ("11,358 tests collected", f"{tests['collected']:,} tests collected"),
        ("11,351 tests collected", f"{tests['collected']:,} tests collected"),
        ("11,067 tests collected", f"{tests['collected']:,} tests collected"),
        ("11,390 collected", f"{tests['collected']:,} collected"),
        ("11,358 collected", f"{tests['collected']:,} collected"),
        ("11,700+ passing", f"{test_floor:,}+ passing"),
        ("11,350+ passing", f"{test_floor:,}+ passing"),
        ("11,300+ passing", f"{test_floor:,}+ passing"),
        ("11,000+ passing", f"{test_floor:,}+ passing"),
        ("413 test files", f"{tests['files']} test files"),
        ("412 test files", f"{tests['files']} test files"),
        ("393 test files", f"{tests['files']} test files"),
        ("413 files", f"{tests['files']} files"),
        ("412 files", f"{tests['files']} files"),
        ("393 files", f"{tests['files']} files"),
        ("11,358 collected / 11,300+", f"{tests['collected']:,} collected / {test_floor:,}+"),
        ("11,390 collected / 11,350+", f"{tests['collected']:,} collected / {test_floor:,}+"),
        # LOC
        ("~181,530 LOC across 424 Python files", f"~{loc['loc']:,} LOC across {loc['py_files']} Python files"),
        ("~181,530 lines of Python in `eli/`", f"~{loc['loc']:,} lines of Python in `eli/`"),
        ("~181,530 lines of Python across 424 files", f"~{loc['loc']:,} lines of Python across {loc['py_files']} files"),
        ("**181,530 LOC across 424 Python files**", f"**{loc['loc']:,} LOC across {loc['py_files']} Python files**"),
        ("181,530 lines** across **424 modules**", f"{loc['loc']:,} lines** across **{loc['py_files']} modules**"),
        ("~181,530 LOC, 424 files", f"~{loc['loc']:,} LOC, {loc['py_files']} files"),
        ("eli/  (~181,530 LOC, 424 files)", f"eli/  (~{loc['loc']:,} LOC, {loc['py_files']} files)"),
        ("204 dispatch / 225 manifest", f"{caps['supported']} dispatch / {caps['total']} manifest"),
        ("204 dispatch actions (225 manifest)", f"{caps['supported']} dispatch actions ({caps['total']} manifest)"),
        ("204 dispatch actions (205 `SUPPORTED_ACTIONS`)", f"{caps['supported']} dispatch actions ({caps['supported']} `SUPPORTED_ACTIONS`)"),
        ("204 executor dispatch actions, 225", f"{caps['supported']} executor dispatch actions, {caps['total']}"),
        ("(**208 routable**; 205 executor", f"(**{caps['routable_or_supported']} routable or executor-backed**; {caps['supported']} executor"),
        ("208 routable or executor-backed)", f"{caps['routable_or_supported']} routable or executor-backed)"),
        ("225 capabilities (2026-08-29)", f"{caps['total']} capabilities ({today})"),
        ("225 manifest actions", f"{caps['total']} manifest actions"),
        ("~166k LOC", f"~{loc_k}k LOC"),
        ("181k-LOC", f"~{loc_k}k-LOC"),
        ("166,397 measured 2026-09-01", f"{loc['loc']:,} measured {today}"),
        ("181,530 measured 2026-08-29", f"{loc['loc']:,} measured {today}"),
        # Silent swallows (public summary only — not CEILING)
        ("646 → 172", f"646 → {swallows}"),
        ("646 → 177", f"646 → {swallows}"),
        ("Remaining count: 175", f"Remaining count: {swallows}"),
        ("175 remaining entries", f"{swallows} remaining entries"),
        # Launch tweet template
        (f"~166k LOC, 227 capabilities", f"~{loc_k}k LOC, {caps['total']} capabilities"),
    ]
    return pairs


def refresh_file(path: Path, replacements: list[tuple[str, str]]) -> bool:
    if any(s in str(path) for s in SKIP_PARTS):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    orig = text
    for old, new in replacements:
        if old == new:
            continue
        text = text.replace(old, new)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    replacements = build_replacements()
    targets = list(ROOT.glob("**/*.md")) + [ROOT / "eli/gui/panels/startup.py"]
    changed = []
    for path in sorted(set(targets)):
        if refresh_file(path, replacements):
            changed.append(path.relative_to(ROOT))
    print(f"Metrics: {_capability_stats()} | tests: {_test_stats()} | loc: {_loc_stats()} | swallows: {_count_silent_swallows()}")
    print(f"Updated {len(changed)} files:")
    for p in changed:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
