#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase10b_repair_future_import_order_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/execution/router_enhanced.py",
    ROOT / "eli/execution/portable_intent_contract.py",
    ROOT / "eli/execution/media_intents.py",
]

FUTURE = "from __future__ import annotations"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def find_insert_idx(lines: list[str]) -> int:
    """
    Legal future-import position:
    after shebang / encoding comments / initial comments / initial blank lines,
    and after a module docstring if one is still at the top.
    """
    i = 0

    if i < len(lines) and lines[i].startswith("#!"):
        i += 1

    # Encoding comments are only relevant in first two lines, but comments/blank
    # before future imports are legal, so keep them above the future import.
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1

    if i >= len(lines):
        return i

    # Optional module docstring.
    s = lines[i].lstrip()
    m = re.match(r'(?i)^[rubf]*("""|\'\'\')', s)
    if not m:
        return i

    quote = m.group(1)

    # Single-line docstring.
    rest = s[len(s) - len(s.lstrip()):]
    if s.count(quote) >= 2 and not s.rstrip().endswith("\\"):
        return i + 1

    # Multi-line docstring.
    j = i + 1
    while j < len(lines):
        if quote in lines[j]:
            return j + 1
        j += 1

    return i


changed = []
for path in TARGETS:
    if not path.exists():
        continue

    src = read(path)
    backup = OUT / (str(path.relative_to(ROOT)).replace("/", "__") + ".before")
    backup.write_text(src, encoding="utf-8")

    lines = src.splitlines()

    # Remove all future-annotation imports, wherever the broken patch left them.
    stripped = [ln for ln in lines if ln.strip() != FUTURE]

    insert_idx = find_insert_idx(stripped)
    stripped.insert(insert_idx, FUTURE)

    fixed = "\n".join(stripped) + "\n"

    if fixed != src:
        path.write_text(fixed, encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))

compile_cmd = [sys.executable, "-m", "compileall", "-q", "eli"]
cp = subprocess.run(compile_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

summary = OUT / "SUMMARY.md"
summary.write_text(
    "# Phase 10b Future Import Repair\n\n"
    f"Changed files:\n" +
    ("".join(f"- {x}\n" for x in changed) if changed else "- none\n") +
    "\nCompile output:\n\n```text\n" +
    cp.stdout +
    "\n```\n",
    encoding="utf-8",
)

print(f"REPORT: {OUT}")
print(summary.read_text())

if cp.returncode != 0:
    raise SystemExit(cp.returncode)
