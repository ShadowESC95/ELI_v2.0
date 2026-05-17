#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$(pwd)}"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/phase19_grounded_followup_failure_bundle_${STAMP}"

mkdir -p \
  "$OUT/files" \
  "$OUT/logs" \
  "$OUT/diagnostics" \
  "$OUT/tests" \
  "$OUT/patch_context"

copy_rel() {
  local rel="$1"
  if [[ -f "$rel" ]]; then
    mkdir -p "$OUT/files/$(dirname "$rel")"
    cp -a "$rel" "$OUT/files/$rel"
  else
    echo "MISSING: $rel" >> "$OUT/diagnostics/missing_files.txt"
  fi
}

copy_patch_rel() {
  local rel="$1"
  if [[ -f "$rel" ]]; then
    mkdir -p "$OUT/patch_context/$(dirname "$rel")"
    cp -a "$rel" "$OUT/patch_context/$rel"
  else
    echo "MISSING: $rel" >> "$OUT/diagnostics/missing_patch_context.txt"
  fi
}

{
  echo "Phase 19 Grounded Follow-up Failure Bundle"
  echo "Date: $(date -Is)"
  echo "Root: $ROOT"
  echo
  echo "=== uname ==="
  uname -a || true
  echo
  echo "=== python ==="
  python3 --version || true
  echo
  echo "=== git branch ==="
  git branch --show-current || true
  echo
  echo "=== git HEAD ==="
  git rev-parse HEAD || true
  echo
  echo "=== git status --short ==="
  git status --short || true
  echo
  echo "=== git log --oneline -25 ==="
  git log --oneline -25 || true
} > "$OUT/00_header_and_git_state.txt" 2>&1

git diff --stat > "$OUT/01_git_diff_stat.txt" 2>&1 || true
git diff > "$OUT/02_git_diff_full.patch" 2>&1 || true

# -------------------------------------------------------------------
# Core source files required to diagnose and patch the failure
# -------------------------------------------------------------------

CORE_FILES=(
  "eli/execution/router_enhanced.py"
  "eli/execution/route_contracts.py"
  "eli/execution/route_authority.py"

  "eli/kernel/engine.py"

  "eli/cognition/agent_bus.py"
  "eli/cognition/orchestrator.py"
  "eli/cognition/context_builder.py"
  "eli/cognition/context_synthesiser.py"
  "eli/cognition/hyde.py"
  "eli/cognition/output_governor.py"
  "eli/cognition/response_governance.py"
  "eli/cognition/response_sanitizer.py"
  "eli/cognition/working_memory.py"
  "eli/cognition/gguf_inference.py"

  "eli/memory/memory.py"
  "eli/memory/working_memory.py"
  "eli/memory/memory_truth.py"

  "eli/runtime/deterministic_grounding_gate.py"
  "eli/runtime/grounded_remediation.py"
  "eli/runtime/evidence_arbitration.py"
  "eli/runtime/evidence_ledger.py"
  "eli/runtime/evidence_store.py"
  "eli/runtime/stage_packet_store.py"
  "eli/runtime/tool_result_store.py"
  "eli/runtime/last_trace.py"
  "eli/runtime/final_response_assembly.py"
  "eli/runtime/final_response_provider.py"
  "eli/runtime/user_visible_response_surface.py"
  "eli/runtime/truth_report.py"
  "eli/runtime/response_policy.py"
  "eli/runtime/control_contracts.py"
  "eli/runtime/retrieval_packets.py"
  "eli/runtime/typed_stage_bridge.py"
)

for rel in "${CORE_FILES[@]}"; do
  copy_rel "$rel"
done

# -------------------------------------------------------------------
# Tests most likely to expose the failure boundary
# -------------------------------------------------------------------

TEST_FILES=(
  "tests/test_execution_router.py"
  "tests/test_router_patterns.py"
  "tests/test_route_contracts.py"
  "tests/test_output_governor_semantics.py"
  "tests/test_deterministic_grounding_gate_install_inert.py"
  "tests/test_reasoning_mode_contract.py"
  "tests/test_response_sanitizer.py"
  "tests/test_sanitizer_extended.py"
  "tests/test_process_consumer_visible_boundaries.py"
  "tests/test_runtime_policy.py"
  "tests/test_live_route_executor_second_fix.py"
)

for rel in "${TEST_FILES[@]}"; do
  if [[ -f "$rel" ]]; then
    mkdir -p "$OUT/tests/$(dirname "$rel")"
    cp -a "$rel" "$OUT/tests/$rel"
  else
    echo "MISSING: $rel" >> "$OUT/diagnostics/missing_tests.txt"
  fi
done

# -------------------------------------------------------------------
# Runtime evidence from the failed live session
# -------------------------------------------------------------------

RUNTIME_FILES=(
  "ops/reports/live_after_phase18_20260512_231835.log"
  "artifacts/runtime/last_trace.json"
  "artifacts/runtime_snapshot.json"
  "generated_documents/runtime_audit_report.txt"
)

for rel in "${RUNTIME_FILES[@]}"; do
  if [[ -f "$rel" ]]; then
    mkdir -p "$OUT/logs/$(dirname "$rel")"
    cp -a "$rel" "$OUT/logs/$rel"
  else
    echo "MISSING: $rel" >> "$OUT/diagnostics/missing_runtime_evidence.txt"
  fi
done

# Include recent conversation JSONs if present; these are small and may help turn linkage analysis.
if compgen -G "artifacts/conversations/conversation_20260512_*.json" > /dev/null; then
  mkdir -p "$OUT/logs/artifacts/conversations"
  cp -a artifacts/conversations/conversation_20260512_*.json "$OUT/logs/artifacts/conversations/" || true
fi

# -------------------------------------------------------------------
# Patch context, especially route/grounding-related recent phases
# -------------------------------------------------------------------

PATCH_CONTEXT_FILES=(
  "ops/patches/phase13b_corrected_recover_router_piper_package_v2.sh"
  "ops/patches/phase13c_reuse_bus_result_all_engine_lanes.py"
  "ops/patches/phase13_dedupe_pdf_csv_agent_execution.py"
  "ops/patches/phase13_surface_integrity_package_repair_v1.sh"
  "ops/patches/phase14_labs_qt_pythonpath_import_venv_audit_repair_v1.sh"
  "ops/patches/phase14b_labs_pyqt6_pythonpath_importaudit_repair_v2.sh"
  "ops/patches/phase15_remove_stopgaps_fix_root_contracts_portability_v1.sh"
  "ops/patches/phase16_identity_matcher_dataset_portability_repair_v1.sh"
  "ops/patches/phase16b_identity_matcher_dataset_portability_repair_v2.sh"
  "ops/patches/phase16c_identity_matcher_dataset_portability_repair_v3.sh"
  "ops/patches/phase17_packaging_runtime_readiness_audit_v1.sh"
  "ops/patches/phase18_restore_embedder_asset_license_manifest_v1.sh"
)

for rel in "${PATCH_CONTEXT_FILES[@]}"; do
  copy_patch_rel "$rel"
done

for d in \
  ops/reports/phase13_surface_integrity_package_repair_* \
  ops/reports/phase13b_corrected_recover_router_piper_package_* \
  ops/reports/phase14b_labs_pyqt6_pythonpath_importaudit_repair_* \
  ops/reports/phase15_remove_stopgaps_fix_root_contracts_portability_* \
  ops/reports/phase16c_identity_matcher_dataset_portability_repair_* \
  ops/reports/phase17_packaging_runtime_readiness_audit_* \
  ops/reports/phase18_restore_embedder_asset_license_manifest_*
do
  if [[ -d "$d" && -f "$d/SUMMARY.md" ]]; then
    mkdir -p "$OUT/patch_context/$d"
    cp -a "$d/SUMMARY.md" "$OUT/patch_context/$d/"
  fi
done

# -------------------------------------------------------------------
# Static diagnosis: exact router duplicate symbol evidence
# -------------------------------------------------------------------

python3 - <<'PY' > "$OUT/diagnostics/03_router_ast_symbol_scan.txt" 2>&1
from __future__ import annotations
import ast
import json
from collections import defaultdict
from pathlib import Path

path = Path("eli/execution/router_enhanced.py")
src = path.read_text(encoding="utf-8")
tree = ast.parse(src)

symbols = defaultdict(list)

for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        symbols[node.name].append({
            "type": type(node).__name__,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", None),
        })

dupes = {k: v for k, v in symbols.items() if len(v) > 1}

print("=== DUPLICATE TOP-LEVEL SYMBOLS ===")
for name, defs in sorted(dupes.items()):
    print(name)
    for d in defs:
        print(f"  - {d['type']} line={d['line']} end_line={d['end_line']}")

print()
print("=== SPECIFIC ROUTE SYMBOLS ===")
for name in ("route", "route_intent"):
    print(name, json.dumps(symbols.get(name, []), indent=2))
PY

python3 - <<'PY' > "$OUT/diagnostics/04_router_route_function_windows.txt" 2>&1
from pathlib import Path

path = Path("eli/execution/router_enhanced.py")
lines = path.read_text(encoding="utf-8").splitlines()

windows = [
    ("route_original_area", 600, 700),
    ("route_intent_original_area", 2730, 2825),
    ("route_duplicate_area", 4380, 4465),
    ("route_intent_duplicate_area", 4420, 4495),
]

for title, start, end in windows:
    print("=" * 100)
    print(title, f"lines {start}-{end}")
    print("=" * 100)
    for i in range(start, min(end, len(lines)) + 1):
        print(f"{i:>6}: {lines[i-1]}")
    print()
PY

# -------------------------------------------------------------------
# Focused grep across failure-related files
# -------------------------------------------------------------------

grep -RInE \
  'chat\.long_question_guard|fallback\.chat|RUNTIME_AUDIT|duplicate_top_level_symbol|follow.?up|previous.*ground|prior.*ground|last_ground|last_trace|grounded|exact lines|line numbers|are you (lying|lieing)|can you fix it|truth|evidence' \
  eli/execution/router_enhanced.py \
  eli/kernel/engine.py \
  eli/cognition \
  eli/runtime \
  eli/memory/memory.py \
  > "$OUT/diagnostics/05_failure_surface_grep.txt" 2>&1 || true

# -------------------------------------------------------------------
# Extract the decisive failure lines from the live log
# -------------------------------------------------------------------

if [[ -f "ops/reports/live_after_phase18_20260512_231835.log" ]]; then
  grep -nEi \
    'RUNTIME_AUDIT|duplicate_top_level_symbol|chat\.long_question_guard|fallback\.chat|lines 42 and 56|Lines 45 and 47|handle_command1|are you lieing|exact lines|thats funny because|FAIL .*router_enhanced|I.ll delete|I.ve found the duplicates' \
    "ops/reports/live_after_phase18_20260512_231835.log" \
    > "$OUT/diagnostics/06_live_failure_key_lines.txt" 2>&1 || true
fi

# -------------------------------------------------------------------
# Py-compile important files
# -------------------------------------------------------------------

{
  echo "=== py_compile targeted source ==="
  python3 -m py_compile \
    eli/execution/router_enhanced.py \
    eli/kernel/engine.py \
    eli/cognition/agent_bus.py \
    eli/cognition/orchestrator.py \
    eli/cognition/context_builder.py \
    eli/cognition/context_synthesiser.py \
    eli/cognition/hyde.py \
    eli/cognition/output_governor.py \
    eli/cognition/response_governance.py \
    eli/memory/memory.py \
    eli/runtime/deterministic_grounding_gate.py \
    eli/runtime/grounded_remediation.py \
    eli/runtime/evidence_arbitration.py \
    eli/runtime/evidence_ledger.py \
    eli/runtime/final_response_assembly.py \
    eli/runtime/final_response_provider.py \
    eli/runtime/user_visible_response_surface.py \
    eli/runtime/truth_report.py \
    eli/runtime/control_contracts.py
  echo "py_compile: PASS"
} > "$OUT/diagnostics/07_py_compile_targeted.txt" 2>&1 || {
  echo "py_compile: FAIL — see output above" >> "$OUT/diagnostics/07_py_compile_targeted.txt"
}

# -------------------------------------------------------------------
# Targeted tests. Non-fatal; results are diagnostic.
# -------------------------------------------------------------------

TEST_CMD=(
  python3 -m pytest -q
  tests/test_execution_router.py
  tests/test_router_patterns.py
  tests/test_route_contracts.py
  tests/test_output_governor_semantics.py
  tests/test_deterministic_grounding_gate_install_inert.py
  tests/test_reasoning_mode_contract.py
  tests/test_response_sanitizer.py
  tests/test_sanitizer_extended.py
  tests/test_process_consumer_visible_boundaries.py
  tests/test_runtime_policy.py
  tests/test_live_route_executor_second_fix.py
)

if command -v timeout >/dev/null 2>&1; then
  timeout 300s "${TEST_CMD[@]}" > "$OUT/tests/08_pytest_targeted_contracts.txt" 2>&1 || true
else
  "${TEST_CMD[@]}" > "$OUT/tests/08_pytest_targeted_contracts.txt" 2>&1 || true
fi

# -------------------------------------------------------------------
# Bundle manifest and archive
# -------------------------------------------------------------------

{
  echo "Bundle directory: $OUT"
  echo
  echo "=== File inventory ==="
  find "$OUT" -type f -printf '%s %p\n' | sort -n
} > "$OUT/99_bundle_manifest.txt"

ARCHIVE="${OUT}.tar.gz"
tar -czf "$ARCHIVE" "$OUT"

sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"

echo
echo "============================================================"
echo "PHASE 19 GROUNDING FAILURE BUNDLE READY"
echo "============================================================"
echo "Archive : $ARCHIVE"
echo "SHA256  : ${ARCHIVE}.sha256"
echo
echo "Upload this tar.gz here:"
echo "  $ARCHIVE"
echo
echo "Do NOT upload models, Piper voices, image assets, or full DB dumps."
echo "============================================================"
