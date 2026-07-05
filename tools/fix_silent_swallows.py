#!/usr/bin/env python3
"""Convert silent `except: pass` to observable logging (release ratchet fix)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELI = ROOT / "eli"
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 25
LOG_LINE = 'logging.getLogger(__name__).debug("suppressed exception", exc_info=True)'


def _has_logging_import(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name == "logging" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "logging":
            return True
    return False


def fix_file(path: Path, quota: int) -> int:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    lines = source.splitlines(keepends=True)
    targets: list[tuple[int, int]] = []  # (except_lineno-1, pass_lineno-1)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
        ):
            targets.append((node.lineno - 1, node.body[0].lineno - 1))
    if not targets:
        return 0
    targets = targets[:quota]
    if not _has_logging_import(tree):
        insert = 0
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(
            getattr(tree.body[0].value, "value", None), str
        ):
            insert = 1
        lines.insert(insert, "import logging\n")
        targets = [(a + 1, b + 1) for a, b in targets]
    fixed = 0
    for except_ln, pass_ln in sorted(targets, key=lambda x: x[1], reverse=True):
        except_indent = len(lines[except_ln]) - len(lines[except_ln].lstrip())
        lines[pass_ln] = " " * (except_indent + 4) + LOG_LINE + "\n"
        fixed += 1
    path.write_text("".join(lines), encoding="utf-8")
    return fixed


def main() -> int:
    remaining = TARGET
    total = 0
    priority = [
        ELI / "kernel" / "engine.py",
        ELI / "gui" / "eli_pro_audio_gui_v2_0.py",
        ELI / "execution" / "executor_enhanced.py",
    ]
    ordered = [p for p in priority if p.is_file()]
    ordered += sorted(p for p in ELI.rglob("*.py") if p not in priority)
    for path in ordered:
        if remaining <= 0:
            break
        n = fix_file(path, remaining)
        if n:
            print(f"  {n:3d}  {path.relative_to(ROOT)}")
            total += n
            remaining -= n
    print(f"[OK] fixed {total} silent swallows (target was {TARGET})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
