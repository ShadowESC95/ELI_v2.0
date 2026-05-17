#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase35_router_top_level_duplicate_symbol_elimination_${STAMP}"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT/backups"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase35.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 35 — Router Top-Level Duplicate Symbol Elimination

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase 33 canonicalised the live public routing surfaces.

Phase 34 confirmed that the remaining concrete AST-level duplicate-symbol defect is
limited to:

- duplicate top-level \`route()\`
- duplicate top-level \`route_intent()\`

This phase removes those duplicate public function definitions without changing
the live wrapper chain:

1. Rename the late EOF personal-memory precedence \`route()\` wrapper into a private helper.
2. Explicitly bind \`route = <private helper>\`.
3. Rename the late EOF personal-memory precedence \`route_intent()\` wrapper into a private helper.
4. Explicitly bind \`route_intent = <private helper>\`.
5. Preserve Phase 11 multi-PDF enrichment.
6. Preserve Phase 33 canonical public-surface rebinding.
7. Verify duplicate-symbol elimination and targeted routing contracts.
EOF

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

text = router_path.read_text(encoding="utf-8")
changes: list[str] = []
warnings: list[str] = []

old_route_block = '''def route(text, *args, **kwargs):  # type: ignore[override]
    try:
        from eli.execution.route_contracts import classify_precedence_route
        _contract = classify_precedence_route(text)
        if _contract is not None:
            return _contract
    except Exception:
        pass

    if _eli_final_pm_previous_route_20260511 is None:
        return {
            "action": "CHAT",
            "args": {"message": str(text or "")},
            "confidence": 0.25,
            "meta": {"matched_by": "eli.final_personal_memory_precedence_fallback"},
        }
    return _eli_final_pm_previous_route_20260511(text, *args, **kwargs)
'''

new_route_block = '''def _eli_final_personal_memory_precedence_route(text, *args, **kwargs):
    try:
        from eli.execution.route_contracts import classify_precedence_route
        _contract = classify_precedence_route(text)
        if _contract is not None:
            return _contract
    except Exception:
        pass

    if _eli_final_pm_previous_route_20260511 is None:
        return {
            "action": "CHAT",
            "args": {"message": str(text or "")},
            "confidence": 0.25,
            "meta": {"matched_by": "eli.final_personal_memory_precedence_fallback"},
        }
    return _eli_final_pm_previous_route_20260511(text, *args, **kwargs)


route = _eli_final_personal_memory_precedence_route
'''

old_route_intent_block = '''def route_intent(text, *args, **kwargs):  # type: ignore[override]
    try:
        from eli.execution.route_contracts import classify_precedence_route
        _contract = classify_precedence_route(text)
        if _contract is not None:
            return _contract
    except Exception:
        pass

    if _eli_final_pm_previous_route_intent_20260511 is None:
        return route(text, *args, **kwargs)
    return _eli_final_pm_previous_route_intent_20260511(text, *args, **kwargs)
'''

new_route_intent_block = '''def _eli_final_personal_memory_precedence_route_intent(text, *args, **kwargs):
    try:
        from eli.execution.route_contracts import classify_precedence_route
        _contract = classify_precedence_route(text)
        if _contract is not None:
            return _contract
    except Exception:
        pass

    if _eli_final_pm_previous_route_intent_20260511 is None:
        return route(text, *args, **kwargs)
    return _eli_final_pm_previous_route_intent_20260511(text, *args, **kwargs)


route_intent = _eli_final_personal_memory_precedence_route_intent
'''

if "_eli_final_personal_memory_precedence_route(" in text:
    warnings.append("private late route precedence helper already present; route block replacement skipped")
else:
    if old_route_block not in text:
        raise RuntimeError("Required late route() duplicate block anchor not found")
    text = text.replace(old_route_block, new_route_block, 1)
    changes.append("renamed late duplicate top-level route() wrapper and rebound route explicitly")

if "_eli_final_personal_memory_precedence_route_intent(" in text:
    warnings.append("private late route_intent precedence helper already present; route_intent block replacement skipped")
else:
    if old_route_intent_block not in text:
        raise RuntimeError("Required late route_intent() duplicate block anchor not found")
    text = text.replace(old_route_intent_block, new_route_intent_block, 1)
    changes.append("renamed late duplicate top-level route_intent() wrapper and rebound route_intent explicitly")

router_path.write_text(text, encoding="utf-8")

(out / "01_changes_applied.txt").write_text(
    "=== CHANGES APPLIED ===\n"
    + ("\n".join(f"- {c}" for c in changes) if changes else "- none")
    + "\n\n=== WARNINGS ===\n"
    + ("\n".join(f"- {w}" for w in warnings) if warnings else "- none")
    + "\n",
    encoding="utf-8",
)

# Structural AST verification immediately after source mutation.
tree = ast.parse(text)
module_functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
]

counts: dict[str, int] = {}
locations: dict[str, list[str]] = {}

for node in module_functions:
    counts[node.name] = counts.get(node.name, 0) + 1
    locations.setdefault(node.name, []).append(
        f"{node.lineno}-{getattr(node, 'end_lineno', node.lineno)}"
    )

duplicate_names = sorted(name for name, count in counts.items() if count > 1)

structural_lines = [
    "=== PHASE 35 STRUCTURAL DUPLICATE CHECK ===",
    f"duplicate_module_level_functions={duplicate_names or []}",
    "",
    "route definitions:",
    *[f"- {loc}" for loc in locations.get("route", [])],
    "",
    "route_intent definitions:",
    *[f"- {loc}" for loc in locations.get("route_intent", [])],
    "",
    "private replacement helpers:",
    f"- _eli_final_personal_memory_precedence_route: {locations.get('_eli_final_personal_memory_precedence_route', [])}",
    f"- _eli_final_personal_memory_precedence_route_intent: {locations.get('_eli_final_personal_memory_precedence_route_intent', [])}",
]

(out / "02_structural_duplicate_check.txt").write_text(
    "\n".join(structural_lines) + "\n",
    encoding="utf-8",
)

if "route" in duplicate_names or "route_intent" in duplicate_names:
    raise RuntimeError(
        f"Top-level route duplicate elimination failed; duplicates remain: {duplicate_names}"
    )
PY

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/03_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

surfaces = ("route", "route_intent", "route_command", "parse_command", "classify")
canonical = getattr(router, "route", None)

identity_lines = [
    "=== PHASE 35 PUBLIC SURFACE IDENTITY ===",
]

all_same = True
for name in surfaces:
    fn = getattr(router, name, None)
    same = fn is canonical
    all_same = all_same and same
    identity_lines.append(
        f"{name}: "
        f"callable={callable(fn)} "
        f"same_as_route={same} "
        f"id={id(fn)} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else '-'}"
    )

identity_lines.append("")
identity_lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "04_public_surface_identity.txt").write_text(
    "\n".join(identity_lines) + "\n",
    encoding="utf-8",
)

if not all_same:
    raise RuntimeError("Public router surface identity drifted after Phase 35")

def route_summary(prompt: str) -> dict[str, Any]:
    result = router.route(prompt)
    if not isinstance(result, dict):
        return {"kind": type(result).__name__, "repr": repr(result)}

    args = result.get("args") if isinstance(result.get("args"), dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}

    return {
        "action": result.get("action"),
        "args": args,
        "meta": meta,
        "confidence": result.get("confidence"),
    }

cases = {
    "memory_count": "How many memories do you have?",
    "recent_memory_processing": "What memories have you been processing lately?",
    "gui_actual_scan_proof": "Did you actually scan the GUI file in full?",
    "memory_runtime_exact": "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    "name_source_audit": "How do you know my name?",
    "pdf_multi": "analyze /tmp/a.pdf and /tmp/b.pdf",
}

results = {name: route_summary(prompt) for name, prompt in cases.items()}

assertions: list[str] = []
failures: list[str] = []

def check(label: str, condition: bool, detail: str) -> None:
    if condition:
        assertions.append(f"PASS: {label} — {detail}")
    else:
        failures.append(f"FAIL: {label} — {detail}")

memory_count = results["memory_count"]
check(
    "memory count route scope",
    memory_count.get("action") == "MEMORY_STATUS"
    and memory_count.get("args", {}).get("memory_scope") == "count_only",
    json.dumps(memory_count, ensure_ascii=False, sort_keys=True),
)

recent_memory = results["recent_memory_processing"]
check(
    "recent memory processing grounded route",
    recent_memory.get("action") == "MEMORY_STATUS"
    and recent_memory.get("args", {}).get("memory_scope") == "recent_processing",
    json.dumps(recent_memory, ensure_ascii=False, sort_keys=True),
)

gui_proof = results["gui_actual_scan_proof"]
check(
    "GUI actual-scan proof route",
    gui_proof.get("action") == "GUI_RUNTIME_AUDIT"
    and gui_proof.get("args", {}).get("proof_requested") is True
    and gui_proof.get("args", {}).get("require_full_file_read_evidence") is True,
    json.dumps(gui_proof, ensure_ascii=False, sort_keys=True),
)

memory_runtime = results["memory_runtime_exact"]
check(
    "memory runtime strict route lock retained",
    memory_runtime.get("action") == "EXPLAIN_MEMORY_RUNTIME"
    and memory_runtime.get("meta", {}).get("matched_by") == "eli.memory_runtime_route_lock_v1"
    and memory_runtime.get("meta", {}).get("response_contract") == "canonical_grounded_memory_runtime_no_raw_gguf",
    json.dumps(memory_runtime, ensure_ascii=False, sort_keys=True),
)

name_source = results["name_source_audit"]
check(
    "name-source audit retained",
    name_source.get("action") == "NAME_SOURCE_AUDIT",
    json.dumps(name_source, ensure_ascii=False, sort_keys=True),
)

pdf_multi = results["pdf_multi"]
matched_by = str(pdf_multi.get("meta", {}).get("matched_by") or "")
check(
    "multi-PDF paths retained",
    pdf_multi.get("action") == "ANALYZE_PDF"
    and pdf_multi.get("args", {}).get("paths") == ["/tmp/a.pdf", "/tmp/b.pdf"]
    and pdf_multi.get("meta", {}).get("multipdf_count") == 2,
    json.dumps(pdf_multi, ensure_ascii=False, sort_keys=True),
)
check(
    "multi-PDF matched_by remains idempotent",
    matched_by.count("+phase11_multipdf") == 1,
    f"matched_by={matched_by!r}",
)

assertion_lines = [
    "=== PHASE 35 TARGETED CONTRACT ASSERTIONS ===",
    *assertions,
    *failures,
    "",
    f"TOTAL_ASSERTION_FAILURES={len(failures)}",
]

(out / "05_targeted_contract_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

(out / "06_targeted_contract_results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True),
    encoding="utf-8",
)

if failures:
    raise RuntimeError("Targeted Phase 35 contract assertions failed:\n" + "\n".join(failures))
PY

diff -u \
  "$OUT/backups/router_enhanced.py.before_phase35.bak" \
  "$ROUTER" \
  > "$OUT/07_phase35_source_diff.patch" || true

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path
from collections import Counter

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

text = router_path.read_text(encoding="utf-8")
tree = ast.parse(text)

module_functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
]

counts = Counter(node.name for node in module_functions)
duplicates = sorted(name for name, count in counts.items() if count > 1)

digest = [
    "=== PHASE 35 DIGEST ===",
    f"Top-level duplicate module functions: {duplicates or 'none'}",
    "Expected duplicate route symbols removed: "
    + str("route" not in duplicates and "route_intent" not in duplicates),
    "",
    "Verification artifacts:",
    "- 02_structural_duplicate_check.txt",
    "- 04_public_surface_identity.txt",
    "- 05_targeted_contract_assertions.txt",
    "- 07_phase35_source_diff.patch",
]

(out / "08_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
PY

{
  echo
  echo "## Changes"
  cat "$OUT/01_changes_applied.txt"
  echo
  echo "## Verification artifacts"
  echo "- \`02_structural_duplicate_check.txt\`"
  echo "- \`03_py_compile.txt\`"
  echo "- \`04_public_surface_identity.txt\`"
  echo "- \`05_targeted_contract_assertions.txt\`"
  echo "- \`06_targeted_contract_results.json\`"
  echo "- \`07_phase35_source_diff.patch\`"
  echo "- \`08_console_digest.txt\`"
  echo
  echo "PHASE35_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE35_OUT=$OUT"
