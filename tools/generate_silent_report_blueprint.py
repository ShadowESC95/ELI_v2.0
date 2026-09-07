#!/usr/bin/env python3
"""Generate comprehensive silent-exception report for blueprints/ (gitignored).

Outputs:
  blueprints/SILENT_EXCEPTION_FULL_REPORT.md
  blueprints/SILENT_EXCEPTION_FULL_REPORT.pdf  (when pandoc/weasyprint available)

Run from repo root: python tools/generate_silent_report_blueprint.py
"""
from __future__ import annotations

import ast
import glob
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELI = os.path.join(REPO, "eli")
OUT_MD = os.path.join(REPO, "blueprints", "SILENT_EXCEPTION_FULL_REPORT.md")
OUT_PDF = os.path.join(REPO, "blueprints", "SILENT_EXCEPTION_FULL_REPORT.pdf")

CATEGORY_RULES: list[tuple[str, re.Pattern, str]] = [
    (
        "import_guard",
        re.compile(r"\b(import|__import__|from .+)\b", re.I),
        "Optional import or boot-time module load. Failure degrades a feature; should log once "
        "logger is bound. Risk: import-order bugs hide missing dependencies.",
    ),
    (
        "env_parse",
        re.compile(r"\b(getenv|environ|int\(|float\()\b"),
        "Environment override parse failure. Falls back to default; silent pass hides "
        "misconfiguration (wrong ELI_* value).",
    ),
    (
        "optional_cleanup",
        re.compile(r"\b(close|unlink|remove|quit|stop|cleanup|flush|shutdown)\b", re.I),
        "Best-effort teardown. Non-fatal but makes shutdown/mpv/socket bugs invisible.",
    ),
    (
        "fallback_probe",
        re.compile(r"\b(which|shutil|subprocess|Popen|run\(|open_url|playerctl|wmctrl)\b"),
        "Fallback chain probe. Silent failure → wrong 'feature unavailable' UX without logs.",
    ),
    (
        "settings_io",
        re.compile(r"\b(settings|config|json|save|load|write|read|sqlite)\b", re.I),
        "Settings or DB I/O. Silent pass can leave stale config or partial writes unnoticed.",
    ),
    (
        "gui_optional",
        re.compile(r"\b(QT|Qt|tkinter|widget|dock|panel|gui|QScintilla)\b", re.I),
        "GUI optional widget path. Often runs before module logger; convert after boot logger exists.",
    ),
    (
        "hardware_probe",
        re.compile(r"\b(gpu|cuda|vram|hardware|device|torch|/proc/|/sys/)\b", re.I),
        "Hardware/GPU probe. Silent failure yields wrong performance tier or missing GPU.",
    ),
    (
        "media_control",
        re.compile(r"\b(mpv|youtube|spotify|player|media|mpris|playerctl)\b", re.I),
        "Media playback/control. High user visibility — prefer warning-level logs.",
    ),
    (
        "memory_recall",
        re.compile(r"\b(recall|memory|sqlite|conn\.execute|enqueue)\b", re.I),
        "Memory/recall write path. Silent pass can drop recall metadata without trace.",
    ),
    (
        "network_optional",
        re.compile(r"\b(request|urlopen|http|mqtt|socket)\b", re.I),
        "Optional network call. May be intentional offline degradation — still should log at debug.",
    ),
]

PRIORITY = {
    "media_control": "P1 — user-visible",
    "fallback_probe": "P1 — user-visible",
    "settings_io": "P2 — data integrity",
    "memory_recall": "P2 — data integrity",
    "hardware_probe": "P2 — performance",
    "env_parse": "P3 — config",
    "optional_cleanup": "P3 — diagnostic",
    "gui_optional": "P3 — GUI boot",
    "import_guard": "P3 — boot",
    "network_optional": "P3 — optional",
    "unclassified": "P4 — review",
}


def _enclosing(tree: ast.AST, ln: int) -> str:
    best = "module-level"
    best_fn = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= ln <= end:
                best_fn = f"def {node.name}()"
        elif isinstance(node, ast.ClassDef):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= ln <= end:
                best = f"class {node.name}"
    if best_fn:
        return best_fn
    return best


def _try_block_src(src: str, tree: ast.AST, handler: ast.ExceptHandler) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                if h is handler:
                    return ast.get_source_segment(src, node) or ""
    return ""


def _classify(try_src: str) -> tuple[str, str]:
    for name, pat, expl in CATEGORY_RULES:
        if pat.search(try_src):
            return name, expl
    if "return" in try_src:
        return "fallback_return", "Try/return fallback — exception swallowed to return None/False/default."
    return "unclassified", "Unclassified best-effort block — manual review required."


def _log_in_scope(src: str, line: int) -> tuple[bool, int | None]:
    log_ln = None
    for i, ln in enumerate(src.splitlines(), 1):
        if re.match(r"^\s*log\s*=\s*get_logger\(__name__\)", ln):
            log_ln = i
    return (log_ln is not None and line > log_ln, log_ln)


def collect() -> list[dict]:
    items = []
    for f in sorted(glob.glob(os.path.join(ELI, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(f, REPO).replace("\\", "/")
        src = open(f, encoding="utf-8").read()
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            items.append({
                "file": rel, "line": 0, "error": str(e),
            })
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ExceptHandler)
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)):
                continue
            ln = node.lineno
            exc = ast.unparse(node.type) if node.type else "bare except"
            ctx = _enclosing(tree, ln)
            try_src = _try_block_src(src, tree, node)
            cat, expl = _classify(try_src)
            has_log, log_ln = _log_in_scope(src, ln)
            start = max(0, ln - 5)
            end = min(len(lines), ln + 3)
            snippet = "\n".join(f"{i+1:5d}| {lines[i]}" for i in range(start, end))
            fix = (
                "Replace `pass` with `log.debug(\"suppressed exception\", exc_info=True)` — logger already in scope."
                if has_log
                else "Add `from eli.utils.log import get_logger` + `log = get_logger(__name__)` after imports, "
                     "or use boot logger if at module-import time before log binds."
            )
            items.append({
                "file": rel,
                "line": ln,
                "context": ctx,
                "except": exc,
                "category": cat,
                "priority": PRIORITY.get(cat, PRIORITY["unclassified"]),
                "explanation": expl,
                "log_in_scope": has_log,
                "log_line": log_ln,
                "fix": fix,
                "snippet": snippet,
                "try_preview": (try_src[:400] + "…") if len(try_src) > 400 else try_src,
            })
    return items


def write_markdown(items: list[dict], version: str) -> None:
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    by_file: dict[str, list] = {}
    by_cat: dict[str, int] = {}
    for it in items:
        by_file.setdefault(it["file"], []).append(it)
        by_cat[it.get("category", "?")] = by_cat.get(it.get("category", "?"), 0) + 1

    convertible = sum(1 for it in items if it.get("log_in_scope"))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(f"# ELI Silent Exception Full Report — v{version}\n\n")
        fh.write(f"**Generated:** {ts}  \n")
        fh.write(f"**Total remaining `except: pass` handlers:** {len(items)}  \n")
        fh.write(f"**Convertible without import changes:** {convertible}  \n")
        fh.write(f"**Requires logger import or boot-time care:** {len(items) - convertible}  \n\n")
        fh.write("---\n\n")
        fh.write("## Executive summary\n\n")
        fh.write(
            "Silent `except: pass` handlers hide failures and cause brittle runtime behaviour. "
            "v2.3.84 converted 469 handlers to observable `log.debug(..., exc_info=True)`. "
            "This report documents **every remaining handler** with location, classification, "
            "risk explanation, and recommended fix.\n\n"
        )
        fh.write("### By category\n\n")
        fh.write("| Category | Count | Typical priority |\n|----------|------:|------------------|\n")
        for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
            fh.write(f"| {cat} | {n} | {PRIORITY.get(cat, 'P4')} |\n")
        fh.write("\n### By file (top 20)\n\n")
        fh.write("| File | Count | Convertible now |\n|------|------:|:---------------:|\n")
        for fp, ents in sorted(by_file.items(), key=lambda x: (-len(x[1]), x[0]))[:20]:
            conv = sum(1 for e in ents if e.get("log_in_scope"))
            fh.write(f"| `{fp}` | {len(ents)} | {conv} |\n")
        fh.write("\n---\n\n")
        fh.write("## Full inventory (every handler)\n\n")
        idx = 0
        for fp in sorted(by_file):
            fh.write(f"## `{fp}` ({len(by_file[fp])} handlers)\n\n")
            for it in by_file[fp]:
                idx += 1
                fh.write(f"### #{idx} — Line {it['line']} — `{it['context']}`\n\n")
                fh.write(f"| Field | Value |\n|-------|-------|\n")
                fh.write(f"| **File** | `{it['file']}` |\n")
                fh.write(f"| **Line** | {it['line']} |\n")
                fh.write(f"| **Scope** | `{it['context']}` |\n")
                fh.write(f"| **Except type** | `{it['except']}` |\n")
                fh.write(f"| **Category** | {it['category']} |\n")
                fh.write(f"| **Priority** | {it['priority']} |\n")
                fh.write(f"| **Log in scope** | {'Yes' if it['log_in_scope'] else 'No'} |\n")
                if it.get("log_line"):
                    fh.write(f"| **Logger bound at line** | {it['log_line']} |\n")
                fh.write(f"\n**Why it exists / risk:** {it['explanation']}\n\n")
                fh.write(f"**Recommended fix:** {it['fix']}\n\n")
                if it.get("try_preview"):
                    fh.write("**Try block (preview):**\n\n```python\n")
                    fh.write(it["try_preview"])
                    fh.write("\n```\n\n")
                fh.write("**Source context:**\n\n```python\n")
                fh.write(it["snippet"])
                fh.write("\n```\n\n")
                fh.write("---\n\n")
    print(f"Wrote {OUT_MD} ({len(items)} entries)")


def write_pdf(version: str) -> bool:
    if not os.path.isfile(OUT_MD):
        return False
    # Try pandoc first
    for cmd in (
        ["pandoc", OUT_MD, "-o", OUT_PDF, "--pdf-engine=xelatex",
         "-V", "geometry:margin=1in", "-V", "fontsize=10pt"],
        ["pandoc", OUT_MD, "-o", OUT_PDF, "--pdf-engine=pdflatex"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and os.path.isfile(OUT_PDF):
                print(f"Wrote {OUT_PDF} via pandoc")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("PDF: pandoc not available or failed — MD report is complete", file=sys.stderr)
    return False


def main() -> int:
    try:
        import tomllib
        version = tomllib.loads(open(os.path.join(REPO, "pyproject.toml"), "rb").read())["project"]["version"]
    except Exception:
        version = "unknown"
    items = collect()
    write_markdown(items, version)
    write_pdf(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
