#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="ops/reports/runtime_status_wrapper_debt_audit_${STAMP}.log"

python3 - <<'PY' | tee "$REPORT"
from pathlib import Path
import ast
import re

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")
lines = src.splitlines()

print("=== ENGINE SIZE ===")
print("path:", p)
print("lines:", len(lines))
print("chars:", len(src))
print()

print("=== RUNTIME STATUS MARKERS ===")
marker_re = re.compile(r"ELI_[A-Z0-9_]*RUNTIME_STATUS[A-Z0-9_]*")
for m in sorted(set(marker_re.findall(src))):
    first = next((i for i, line in enumerate(lines, 1) if m in line), None)
    print(f"{first}: {m}")
print()

print("=== CognitiveEngine.process ASSIGNMENTS ===")
for i, line in enumerate(lines, 1):
    if "CognitiveEngine.process =" in line:
        print(f"{i}: {line.strip()}")
print()

print("=== RUNTIME STATUS FUNCTION DEFINITIONS ===")
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and "runtime_status" in node.name.lower():
        print(f"{node.lineno}-{getattr(node, 'end_lineno', '?')}: def {node.name}(...):")
print()

print("=== RUNTIME STATUS PATCH BLOCK SPANS ===")
interesting = [
    "ELI_RUNTIME_STATUS_REPAIR_V10",
    "ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11",
    "ELI_RUNTIME_STATUS_SEMANTIC_VALIDATOR_V12",
    "ELI_RUNTIME_STATUS_QUICK_STRUCTURED_V13",
    "ELI_RUNTIME_STATUS_QUICK_PATHS_V14",
    "ELI_RUNTIME_STATUS_ALL_MODES_FILL_BLANKS_V15",
]

for marker in interesting:
    hits = [i for i, line in enumerate(lines, 1) if marker in line]
    if not hits:
        print(f"{marker}: NOT FOUND")
        continue
    start = hits[0]
    print(f"{marker}: first_seen_line={start}")
print()

print("=== LAST 500 LINES RUNTIME-RELATED HEADINGS ===")
for i in range(max(1, len(lines)-500), len(lines)+1):
    line = lines[i-1]
    if (
        "ELI_RUNTIME_STATUS" in line
        or "runtime-status" in line
        or "runtime_status" in line
        or "CognitiveEngine.process =" in line
    ):
        print(f"{i}: {line[:220]}")
print()

print("=== IMPORT COMPILE CHECK ===")
compile(src, str(p), "exec")
print("compile_ok=True")
PY

echo
echo "Report: $REPORT"
