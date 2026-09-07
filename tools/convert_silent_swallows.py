#!/usr/bin/env python3
"""Convert silent `except: pass` to observable log.debug where `log` is in scope.

Safe rules:
- Module must already bind `log = get_logger(__name__)` before the handler line.
- Handler body must be exactly `pass` (single statement).
- Does not touch handlers at module-import time before `log` is bound.

Run from repo root: python tools/convert_silent_swallows.py [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELI = os.path.join(REPO, "eli")
LOG_LINE = 'log.debug("suppressed exception", exc_info=True)'


def _log_binding_line(tree: ast.AST, src_lines: list[str]) -> int | None:
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "log":
                    return node.lineno
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "log":
            return node.lineno
    for i, line in enumerate(src_lines, 1):
        if re.match(r"^log\s*=\s*get_logger\(__name__\)", line):
            return i
    return None


def convert_file(path: str, *, dry_run: bool) -> int:
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0

    log_ln = _log_binding_line(tree, [l.rstrip("\n") for l in lines])
    if log_ln is None:
        return 0

    changed = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ExceptHandler)
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)):
            continue
        if node.lineno <= log_ln:
            continue
        pass_ln = node.body[0].lineno - 1  # 0-based
        if pass_ln >= len(lines):
            continue
        stripped = lines[pass_ln].lstrip()
        if stripped.strip() != "pass":
            continue
        indent = lines[pass_ln][: len(lines[pass_ln]) - len(stripped)]
        replacement = indent + LOG_LINE + ("\n" if lines[pass_ln].endswith("\n") else "")
        if not dry_run:
            lines[pass_ln] = replacement
        changed += 1

    if changed and not dry_run:
        open(path, "w", encoding="utf-8").write("".join(lines))
    return changed


def add_logger_and_convert(path: str, *, dry_run: bool) -> int:
    """Add get_logger import + binding after imports, then convert."""
    src = open(path, encoding="utf-8").read()
    if "log = get_logger(__name__)" in src:
        return convert_file(path, dry_run=dry_run)

    lines = src.splitlines(keepends=True)
    insert_at = 0
    in_docstring = False
    doc_delim = None
    last_import_line = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if i == 0 and (s.startswith('"""') or s.startswith("'''")):
            doc_delim = '"""' if '"""' in s else "'''"
            if s.count(doc_delim) >= 2 and len(s) > 3:
                insert_at = i + 1
                continue
            in_docstring = True
            continue
        if in_docstring:
            if doc_delim and doc_delim in s:
                in_docstring = False
                insert_at = i + 1
            continue
        if s.startswith("import ") or s.startswith("from "):
            last_import_line = i + 1
        elif s and not s.startswith("#") and last_import_line > 0:
            break
    insert_at = last_import_line or insert_at

    block = (
        "\nfrom eli.utils.log import get_logger\n\n"
        "log = get_logger(__name__)\n"
    )
    if not dry_run:
        lines.insert(insert_at, block)
        open(path, "w", encoding="utf-8").write("".join(lines))
    return convert_file(path, dry_run=dry_run) if not dry_run else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--add-logger", action="append", default=[], metavar="REL_PATH",
                    help="Files under eli/ that need logger import first")
    args = ap.parse_args()

    total = 0
    for f in sorted(glob.glob(os.path.join(ELI, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(f, REPO).replace("\\", "/")
        if rel in args.add_logger or any(rel.endswith(x) for x in args.add_logger):
            n = add_logger_and_convert(f, dry_run=args.dry_run)
        else:
            n = convert_file(f, dry_run=args.dry_run)
        if n:
            print(f"{n:3d}  {rel}")
            total += n
    print(f"converted {total} handlers" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
