#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase31_router_duplicate_semantic_audit_${STAMP}"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

{
  echo "# Phase 31 — Router Duplicate Semantic Audit"
  echo
  echo "Generated: $(date -Is)"
  echo "Root: $ROOT"
  echo "Target: $ROUTER"
  echo "Mode: audit only — no source files modified"
  echo
} > "$OUT/SUMMARY.md"

echo "=== PY_COMPILE ===" | tee "$OUT/00_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_compile.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

router = Path(sys.argv[1])
out = Path(sys.argv[2])
src = router.read_text(encoding="utf-8")
tree = ast.parse(src)

class DefCollector(ast.NodeVisitor):
    def __init__(self):
        self.stack: list[str] = []
        self.rows: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record(node, "FunctionDef")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record(node, "AsyncFunctionDef")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _record(self, node, kind: str):
        segment = ast.get_source_segment(src, node) or ""
        body_hash = hashlib.sha256(segment.encode("utf-8")).hexdigest()[:16]
        args = []
        for arg in node.args.posonlyargs:
            args.append(arg.arg)
        for arg in node.args.args:
            args.append(arg.arg)
        if node.args.vararg:
            args.append("*" + node.args.vararg.arg)
        for arg in node.args.kwonlyargs:
            args.append(arg.arg)
        if node.args.kwarg:
            args.append("**" + node.args.kwarg.arg)

        self.rows.append({
            "name": node.name,
            "kind": kind,
            "lineno": getattr(node, "lineno", None),
            "end_lineno": getattr(node, "end_lineno", None),
            "scope": "module" if not self.stack else "nested:" + ".".join(self.stack),
            "args": args,
            "decorators": [
                ast.unparse(dec) if hasattr(ast, "unparse") else type(dec).__name__
                for dec in node.decorator_list
            ],
            "body_hash": body_hash,
        })

collector = DefCollector()
collector.visit(tree)
rows = collector.rows

all_counts = Counter(row["name"] for row in rows)
module_counts = Counter(row["name"] for row in rows if row["scope"] == "module")

all_dupes = sorted(name for name, count in all_counts.items() if count > 1)
module_dupes = sorted(name for name, count in module_counts.items() if count > 1)

target_rows = [
    row for row in rows
    if row["name"] in {"route", "route_intent"}
]

(out / "01_ast_definition_inventory.json").write_text(
    json.dumps(rows, indent=2),
    encoding="utf-8",
)

with (out / "02_duplicate_summary.txt").open("w", encoding="utf-8") as f:
    f.write("=== ALL-SCOPE DUPLICATES ===\n")
    f.write(", ".join(all_dupes) if all_dupes else "none")
    f.write("\n\n=== MODULE-LEVEL DUPLICATES ===\n")
    f.write(", ".join(module_dupes) if module_dupes else "none")
    f.write("\n\n=== ROUTE / ROUTE_INTENT DEFINITIONS ===\n")
    for row in target_rows:
        f.write(
            f"{row['name']} | "
            f"scope={row['scope']} | "
            f"lines={row['lineno']}-{row['end_lineno']} | "
            f"args={row['args']} | "
            f"decorators={row['decorators']} | "
            f"hash={row['body_hash']}\n"
        )

# Render exact source windows for route / route_intent definitions
lines = src.splitlines()
with (out / "03_route_definition_windows.txt").open("w", encoding="utf-8") as f:
    for row in target_rows:
        start = max(1, int(row["lineno"]) - 12)
        end = min(len(lines), int(row["end_lineno"] or row["lineno"]) + 18)
        f.write("=" * 118 + "\n")
        f.write(
            f"{row['name']} | scope={row['scope']} | "
            f"definition lines={row['lineno']}-{row['end_lineno']} | "
            f"body_hash={row['body_hash']}\n"
        )
        f.write("=" * 118 + "\n")
        for idx in range(start, end + 1):
            f.write(f"{idx:6d}: {lines[idx - 1]}\n")
        f.write("\n")

# Focused same-name grouping
groups = defaultdict(list)
for row in target_rows:
    groups[row["name"]].append(row)

with (out / "04_route_duplicate_comparison.txt").open("w", encoding="utf-8") as f:
    for name in ("route", "route_intent"):
        subset = groups.get(name, [])
        f.write("=" * 96 + "\n")
        f.write(f"{name}: {len(subset)} definition(s)\n")
        f.write("=" * 96 + "\n")
        if not subset:
            f.write("none\n\n")
            continue
        for i, row in enumerate(subset, 1):
            f.write(
                f"[{i}] scope={row['scope']} "
                f"lines={row['lineno']}-{row['end_lineno']} "
                f"hash={row['body_hash']} "
                f"args={row['args']}\n"
            )
        unique_hashes = sorted({row["body_hash"] for row in subset})
        f.write(f"unique_body_hashes={unique_hashes}\n")
        if len(unique_hashes) == 1 and len(subset) > 1:
            f.write("assessment=duplicate bodies appear textually identical\n")
        elif len(subset) > 1:
            f.write("assessment=duplicate names have materially different bodies or source text\n")
        f.write("\n")
PY

{
  echo "=== RAW DEF-LINE GREP ==="
  grep -nE '^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+(route|route_intent)\b' "$ROUTER" || true
} > "$OUT/05_raw_definition_line_hits.txt"

{
  echo "=== ROUTE / ROUTE_INTENT SYMBOL REBINDING SURFACES ==="
  grep -nE \
    '(^|[^A-Za-z0-9_])(route|route_intent)[[:space:]]*=|globals\(\).*(route|route_intent)|_ORIG_ROUTE|_ORIG_ROUTE_INTENT|PREV_ROUTE|PREV_ROUTE_INTENT|wrapped.*route|route.*wrapped' \
    "$ROUTER" || true
} > "$OUT/06_symbol_rebinding_hits.txt"

{
  echo "=== HIGH-RISK ROUTER PATCH / GUARD HITS ==="
  grep -nEi \
    'guard|wrapper|wrapped|orig_route|route guard|route_intent|self-improvement|runtime/cognition/failure|high-priority|install failed|monkey|shadow' \
    "$ROUTER" || true
} > "$OUT/07_router_guard_patch_surface_hits.txt"

{
  echo "=== PROJECT-WIDE ROUTE IMPORT / CALL SURFACES ==="
  grep -RInE \
    'from[[:space:]]+eli\.execution\.router_enhanced[[:space:]]+import|router_enhanced\.(route|route_intent)|\broute_intent\(|\broute\(' \
    eli 2>/dev/null || true
} > "$OUT/08_project_route_usage_hits.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import inspect
import json
import sys
import traceback
from pathlib import Path

out = Path(sys.argv[1])

lines = []
lines.append("=== RUNTIME EFFECTIVE EXPORT PROBE ===")

try:
    import eli.execution.router_enhanced as router

    for name in ("route", "route_intent"):
        obj = getattr(router, name, None)
        lines.append(f"{name}: present={callable(obj)} repr={obj!r}")
        if callable(obj):
            try:
                lines.append(f"  module={getattr(obj, '__module__', None)}")
                lines.append(f"  qualname={getattr(obj, '__qualname__', None)}")
                lines.append(f"  firstlineno={getattr(getattr(obj, '__code__', None), 'co_firstlineno', None)}")
                lines.append(f"  signature={inspect.signature(obj)}")
            except Exception as exc:
                lines.append(f"  introspection_error={type(exc).__name__}: {exc}")
except Exception as exc:
    lines.append(f"IMPORT_FAILED={type(exc).__name__}: {exc}")
    lines.append(traceback.format_exc())

(out / "09_runtime_effective_export_probe.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)
PY

{
  echo "=== SUMMARY VIEW ==="
  echo
  echo "--- duplicate summary ---"
  cat "$OUT/02_duplicate_summary.txt"
  echo
  echo "--- runtime effective export probe ---"
  cat "$OUT/09_runtime_effective_export_probe.txt"
  echo
  echo "--- raw definition lines ---"
  cat "$OUT/05_raw_definition_line_hits.txt"
} | tee "$OUT/10_console_summary.txt"

{
  echo
  echo "## Audit files produced"
  for f in "$OUT"/*; do
    printf -- "- `%s`\n" "$(basename "$f")"
  done
  echo
  echo "## Interpretation target"
  echo "Use this report to decide whether the duplicate router definitions are:"
  echo "1. harmless nested/name reuse;"
  echo "2. intentional late-stage wrapper/rebinding architecture;"
  echo "3. accidental module-level shadowing requiring consolidation."
  echo
  echo "PHASE31_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE31_OUT=$OUT"
