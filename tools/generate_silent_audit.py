#!/usr/bin/env python3
"""Generate SILENT_EXCEPTION_AUDIT.md with LOC, scope, and explanation per handler."""
from __future__ import annotations

import ast
import glob
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELI = os.path.join(REPO, "eli")
OUT = os.path.join(REPO, "docs", "SILENT_EXCEPTION_AUDIT.md")

CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("import_guard", re.compile(r"\b(import|__import__|from .+)\b", re.I)),
    ("env_parse", re.compile(r"\b(getenv|environ|int\(|float\()\b")),
    ("optional_cleanup", re.compile(r"\b(close|unlink|remove|quit|stop|cleanup|flush)\b", re.I)),
    ("fallback_probe", re.compile(r"\b(which|shutil|subprocess|Popen|run\(|open_url|playerctl)\b")),
    ("settings_io", re.compile(r"\b(settings|config|json|save|load|write|read)\b", re.I)),
    ("gui_optional", re.compile(r"\b(QT|Qt|tkinter|widget|dock|panel|gui)\b", re.I)),
    ("hardware_probe", re.compile(r"\b(gpu|cuda|vram|hardware|device|torch)\b", re.I)),
    ("media_control", re.compile(r"\b(mpv|youtube|spotify|player|media|mpris)\b", re.I)),
]


def _enclosing(tree: ast.AST, ln: int) -> str:
    best = "module-level"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= ln <= end:
                best = f"def {node.name}()"
        elif isinstance(node, ast.ClassDef):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= ln <= end:
                best = f"class {node.name}"
    return best


def _explain(try_src: str, exc: str, ctx: str) -> str:
    for name, pat in CATEGORY_RULES:
        if pat.search(try_src):
            return {
                "import_guard": "Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).",
                "env_parse": "Invalid env override — falls back to default; silent pass hides misconfiguration.",
                "optional_cleanup": "Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.",
                "fallback_probe": "Fallback chain probe (tool/browser/player) — silent failure causes wrong 'nothing works' UX.",
                "settings_io": "Settings read/write — silent pass can leave stale config or failed deletes unnoticed.",
                "gui_optional": "GUI optional widget/audio path — often pre-log binding; convert carefully after boot logger exists.",
                "hardware_probe": "Hardware/GPU probe — silent failure yields wrong performance tier.",
                "media_control": "Media playback/control path — high user visibility; prefer warning-level logs.",
            }[name]
    if "return" in try_src:
        return "Try/return fallback — exception swallowed to return None/False/default."
    return "Unclassified best-effort block — review whether failure should surface to operator logs."


def collect() -> list[dict]:
    items = []
    for f in sorted(glob.glob(os.path.join(ELI, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(f, REPO).replace("\\", "/")
        src = open(f, encoding="utf-8").read()
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ExceptHandler)
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)):
                continue
            ln = node.lineno
            exc = ast.unparse(node.type) if node.type else "bare except"
            ctx = _enclosing(tree, ln)
            # try block text (walk parents manually)
            try_src = ""
            for parent in ast.walk(tree):
                if isinstance(parent, ast.Try):
                    for h in parent.handlers:
                        if h is node:
                            try_src = ast.get_source_segment(src, parent) or ""
                            break
            expl = _explain(try_src, exc, ctx)
            start = max(0, ln - 3)
            end = min(len(lines), ln + 1)
            snippet = "\n".join(f"{i+1:5d}| {lines[i]}" for i in range(start, end))
            items.append({
                "file": rel, "line": ln, "context": ctx, "except": exc,
                "explanation": expl, "snippet": snippet,
            })
    return items


def main() -> None:
    items = collect()
    converted_note = (
        "v2.3.84 converted **469** handlers (where `log = get_logger(__name__)` was "
        "already in scope or safely added). This document lists **remaining** handlers "
        "still using bare `pass`."
    )
    by_file: dict[str, list] = {}
    for it in items:
        by_file.setdefault(it["file"], []).append(it)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("# Silent `except: pass` audit\n\n")
        fh.write(f"**Remaining count: {len(items)}** (CEILING ratchet target for v2.3.84)\n\n")
        fh.write(f"{converted_note}\n\n")
        fh.write("## Index by file\n\n")
        fh.write("| File | Count |\n|------|------:|\n")
        for fp in sorted(by_file, key=lambda x: (-len(by_file[x]), x)):
            fh.write(f"| `{fp}` | {len(by_file[fp])} |\n")
        fh.write("\n---\n\n")
        for fp in sorted(by_file):
            fh.write(f"## `{fp}` ({len(by_file[fp])})\n\n")
            for it in by_file[fp]:
                fh.write(f"### Line {it['line']} — `{it['context']}`\n\n")
                fh.write(f"- **Except:** `{it['except']}`\n")
                fh.write(f"- **Why it exists / risk:** {it['explanation']}\n")
                fh.write(f"- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.\n\n")
                fh.write("```python\n")
                fh.write(it["snippet"])
                fh.write("\n```\n\n")
    print(f"Wrote {OUT} with {len(items)} remaining entries")


if __name__ == "__main__":
    main()
