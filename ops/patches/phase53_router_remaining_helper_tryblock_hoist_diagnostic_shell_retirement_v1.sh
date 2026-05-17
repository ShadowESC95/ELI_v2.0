#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase53_router_remaining_helper_tryblock_hoist_diagnostic_shell_retirement_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"
PATCH_MARKER="ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1"

mkdir -p "$OUT/backups"

for f in "$ROUTER" "$PHASE36_SCRIPT" "$PHASE45B_SCRIPT"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase53.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase 53 — Router Remaining Helper Try-block Hoist / Diagnostic Shell Retirement

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase52 proved that the six remaining pre-Phase38 mixed Try blocks are no
longer route-wrapper shells. Their remaining live content is helper/import-only:

1. Profile-memory scope helper bundle
2. Memory-count helper
3. Recent-memory-processing helper + local regex import alias
4. Self-report recent-updates helper
5. GUI actual-scan audit helper
6. Memory-runtime route-lock helper pair

Each block's `except` branch is diagnostic-only print behaviour. Phase53 retires
those stale import-time diagnostic shells and hoists the helper/import bodies
directly to module scope.

## Required invariants

- Router compiles before and after patch.
- Phase36 semantic baseline JSON remains exact-match pre/post.
- Phase45b remaining mixed pre-Phase38 Try-block count falls from 6 to 0.
- Public router surfaces remain canonical and runtime probes remain correct.
- No post-Phase38 canonical dispatcher logic is altered.
EOF

echo "=== PRE-PATCH PY_COMPILE ===" | tee "$OUT/00_pre_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_pre_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_pre_py_compile.txt"

echo "=== PRE-PATCH PHASE36 BASELINE ===" | tee "$OUT/01_pre_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/01_pre_phase36_console.txt"

PRE36_OUT="$(
  grep -E '^PHASE36_V2_OUT=' "$OUT/01_pre_phase36_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PRE36_OUT:-}" || ! -d "$PRE36_OUT" ]]; then
  echo "Could not recover PRE36_OUT from Phase36 console output." >&2
  exit 1
fi

cp "$PRE36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/02_pre_phase36_semantic_baseline.json"

echo "=== PRE-PATCH PHASE45b REFRESH ===" | tee "$OUT/03_pre_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/03_pre_phase45b_console.txt"

python3 - "$ROUTER" "$OUT" "$PHASE38_MARKER" "$PATCH_MARKER" <<'PY'
from __future__ import annotations

import ast
import difflib
import json
import sys
import textwrap
from pathlib import Path
from typing import Iterable

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])
phase38_marker = sys.argv[3]
patch_marker = sys.argv[4]

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

if patch_marker in src:
    raise SystemExit(f"Phase53 marker already present: {patch_marker}")

marker_line = None
for idx, line in enumerate(lines, start=1):
    if phase38_marker in line:
        marker_line = idx
        break

if marker_line is None:
    raise SystemExit(f"Required Phase38 marker not found: {phase38_marker}")

tree = ast.parse(src)

EXPECTED_GROUPS = {
    "profile_scope_helpers": {
        "_eli_profile_scope_low",
        "_eli_profile_scope_result",
        "_eli_is_explicit_preference_request",
        "_eli_is_generic_profile_inventory",
        "_eli_is_full_profile_dump",
    },
    "memory_count_helper": {
        "_eli_is_memory_count_question",
    },
    "recent_memory_processing_helper": {
        "_eli_recent_memory_processing_question",
    },
    "self_report_recent_updates_helper": {
        "_eli_self_report_recent_updates_question",
    },
    "gui_actual_scan_helper": {
        "_eli_gui_audit_actual_scan_v2",
    },
    "memory_runtime_lock_helpers": {
        "_eli_memory_runtime_route_lock_should_trigger",
        "_eli_memory_runtime_route_lock_result",
    },
}

def imported_names(stmt: ast.stmt) -> list[str]:
    names: list[str] = []
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            names.append(alias.asname or alias.name.split(".")[0])
    elif isinstance(stmt, ast.ImportFrom):
        for alias in stmt.names:
            names.append(alias.asname or alias.name)
    return names

def is_print_expr(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    fn = call.func
    return isinstance(fn, ast.Name) and fn.id == "print"

def except_handler_is_diagnostic_only(handler: ast.ExceptHandler) -> bool:
    if not handler.body:
        return False
    return all(is_print_expr(stmt) or isinstance(stmt, ast.Pass) for stmt in handler.body)

def body_is_helper_import_only(body: Iterable[ast.stmt]) -> bool:
    allowed = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Import, ast.ImportFrom)
    return all(isinstance(stmt, allowed) for stmt in body)

selected: list[tuple[str, ast.Try, set[str], list[str]]] = []
seen_groups: set[str] = set()

for stmt in tree.body:
    if not isinstance(stmt, ast.Try):
        continue
    if stmt.lineno >= marker_line:
        continue
    if stmt.orelse or stmt.finalbody:
        continue
    if len(stmt.handlers) != 1:
        continue
    if not body_is_helper_import_only(stmt.body):
        continue
    if not except_handler_is_diagnostic_only(stmt.handlers[0]):
        continue

    helper_names = {
        body_stmt.name
        for body_stmt in stmt.body
        if isinstance(body_stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    imports: list[str] = []
    for body_stmt in stmt.body:
        imports.extend(imported_names(body_stmt))

    matched_tag = None
    for tag, expected in EXPECTED_GROUPS.items():
        if helper_names == expected:
            matched_tag = tag
            break

    if matched_tag is None:
        continue

    if matched_tag in seen_groups:
        raise SystemExit(f"Duplicate matching Phase53 Try block for group: {matched_tag}")

    seen_groups.add(matched_tag)
    selected.append((matched_tag, stmt, helper_names, imports))

missing = sorted(set(EXPECTED_GROUPS) - seen_groups)
if missing:
    raise SystemExit(f"Phase53 could not find expected helper Try block group(s): {missing}")

if len(selected) != 6:
    raise SystemExit(f"Phase53 expected 6 helper Try blocks; found {len(selected)}")

selected.sort(key=lambda item: item[1].lineno, reverse=True)

manifest_lines: list[str] = []
replacement_log: list[dict[str, object]] = []

for tag, node, helper_names, imports in selected:
    handler = node.handlers[0]
    start = node.lineno
    end = node.end_lineno
    body_start = node.lineno + 1
    body_end = handler.lineno - 1

    body_raw = "".join(lines[body_start - 1:body_end])
    body_hoisted = textwrap.dedent(body_raw).rstrip() + "\n"

    replacement = (
        f"# {patch_marker}: {tag}\n"
        "# Phase53: helper/import-only Try shell hoisted to module scope.\n"
        "# The former except branch only printed a diagnostic and swallowed import-time\n"
        "# helper-definition failure; that stale diagnostic shell is intentionally retired.\n"
        f"{body_hoisted}"
    )

    lines[start - 1:end] = [replacement]

    manifest_lines.extend([
        f"tag={tag}",
        f"lines={start}-{end}",
        f"helper_names={','.join(sorted(helper_names)) or '-'}",
        f"import_names={','.join(imports) or '-'}",
        f"replacement_chars={len(replacement)}",
        "",
    ])

    replacement_log.append({
        "tag": tag,
        "start_line": start,
        "end_line": end,
        "helper_names": sorted(helper_names),
        "import_names": imports,
        "replacement_chars": len(replacement),
    })

new_src = "".join(lines)

if new_src == src:
    raise SystemExit("Phase53 transformation produced no source change.")

router_path.write_text(new_src, encoding="utf-8")

(out / "04_selected_tryblock_manifest.txt").write_text(
    "=== PHASE 53 SELECTED TRYBLOCK MANIFEST ===\n"
    + "\n".join(manifest_lines),
    encoding="utf-8",
)

(out / "05_replacement_log.json").write_text(
    json.dumps(replacement_log, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

diff = difflib.unified_diff(
    src.splitlines(),
    new_src.splitlines(),
    fromfile="router_enhanced.py.before_phase53",
    tofile="router_enhanced.py.after_phase53",
    lineterm="",
)
(out / "06_phase53_source_diff.patch").write_text(
    "\n".join(diff) + "\n",
    encoding="utf-8",
)

print("PHASE53_TRANSFORM_OK")
print(f"PHASE38_MARKER_LINE_PREPATCH={marker_line}")
print(f"HOISTED_TRYBLOCK_COUNT={len(selected)}")
for tag, node, helpers, imports in sorted(selected, key=lambda item: item[1].lineno):
    print(
        f"HOISTED tag={tag} "
        f"lines={node.lineno}-{node.end_lineno} "
        f"helpers={','.join(sorted(helpers)) or '-'} "
        f"imports={','.join(imports) or '-'}"
    )
PY

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/07_post_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/07_post_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/07_post_py_compile.txt"

echo "=== POST-PATCH PHASE36 BASELINE ===" | tee "$OUT/08_post_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/08_post_phase36_console.txt"

POST36_OUT="$(
  grep -E '^PHASE36_V2_OUT=' "$OUT/08_post_phase36_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${POST36_OUT:-}" || ! -d "$POST36_OUT" ]]; then
  echo "Could not recover POST36_OUT from Phase36 console output." >&2
  exit 1
fi

cp "$POST36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/09_post_phase36_semantic_baseline.json"

python3 - "$OUT/02_pre_phase36_semantic_baseline.json" \
           "$OUT/09_post_phase36_semantic_baseline.json" \
           "$OUT/10_phase36_exact_semantic_compare.txt" \
           "$OUT/11_phase36_exact_semantic_diff.txt" <<'PY'
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

pre_path = Path(sys.argv[1])
post_path = Path(sys.argv[2])
compare_out = Path(sys.argv[3])
diff_out = Path(sys.argv[4])

pre_obj = json.loads(pre_path.read_text(encoding="utf-8"))
post_obj = json.loads(post_path.read_text(encoding="utf-8"))

pre_norm = json.dumps(pre_obj, indent=2, sort_keys=True, ensure_ascii=False)
post_norm = json.dumps(post_obj, indent=2, sort_keys=True, ensure_ascii=False)

equal = pre_obj == post_obj

compare_text = "\n".join([
    "=== PHASE 53 EXACT PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"EXACT_JSON_EQUAL={equal}",
    f"DIFF_WRITTEN={diff_out.name}",
    "",
])
compare_out.write_text(compare_text, encoding="utf-8")
print(compare_text, end="")

if equal:
    diff_out.write_text("NO_DIFF\n", encoding="utf-8")
else:
    diff = difflib.unified_diff(
        pre_norm.splitlines(),
        post_norm.splitlines(),
        fromfile="phase36_pre",
        tofile="phase36_post",
        lineterm="",
    )
    diff_out.write_text("\n".join(diff) + "\n", encoding="utf-8")
    raise SystemExit("Phase53 semantic baseline mismatch: exact JSON equality failed.")
PY

echo "=== POST-PATCH PHASE45b REFRESH ===" | tee "$OUT/12_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/12_post_phase45b_console.txt"

python3 - "$OUT/12_post_phase45b_console.txt" "$OUT/13_phase45b_postpatch_assertions.txt" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

console = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
out = Path(sys.argv[2])

def extract(label: str) -> int:
    m = re.search(rf"^{re.escape(label)}:\s*(\d+)\s*$", console, re.M)
    if not m:
        raise SystemExit(f"Could not parse Phase45b digest field: {label}")
    return int(m.group(1))

mixed = extract("Mixed pre-Phase38 Try blocks with post-marker live binds")
splittable = extract("Mechanically splittable mixed blocks")
manual = extract("Blocks requiring manual/deeper handling")

lines = [
    "=== PHASE 53 POST-PATCH PHASE45b ASSERTIONS ===",
    f"mixed_pre_phase38_tryblocks={mixed}",
    f"mechanically_splittable_mixed_blocks={splittable}",
    f"manual_or_deeper_mixed_blocks={manual}",
]

failures: list[str] = []

if mixed != 0:
    failures.append(f"expected mixed Try-block count 0 after Phase53; observed {mixed}")
else:
    lines.append("PASS: mixed Try-block count collapsed to 0")

if splittable != 0:
    failures.append(f"expected mechanically splittable count 0; observed {splittable}")
else:
    lines.append("PASS: mechanically splittable mixed-block count remains 0")

if manual != 0:
    failures.append(f"expected manual/deeper mixed-block count 0; observed {manual}")
else:
    lines.append("PASS: manual/deeper mixed-block count collapsed to 0")

if failures:
    lines.append("")
    lines.append("FAILURES:")
    lines.extend(f"- {item}" for item in failures)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    raise SystemExit("Phase53 Phase45b post-patch assertions failed.")

lines.append("PHASE53_PHASE45B_ASSERTIONS_PASS")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
PY

cat > "$OUT/14_direct_runtime_probe.py" <<'PY'
from __future__ import annotations

import json

from eli.execution import router_enhanced as r

surfaces = {
    "route": r.route,
    "route_intent": r.route_intent,
    "route_command": r.route_command,
    "parse_command": r.parse_command,
    "classify": r.classify,
}

surface_ids = {name: id(fn) for name, fn in surfaces.items()}
all_same = len(set(surface_ids.values())) == 1

identity = r.route("Who am I?")
memory_runtime = r.route(
    "Explain exactly how your memory system works internally — which files, which DB tables, which functions."
)
multipdf = r.route("analyze /tmp/a.pdf and /tmp/b.pdf")

print("=== PHASE 53 DIRECT RUNTIME SANITY PROBE ===")
print("surface_ids=" + json.dumps(surface_ids, sort_keys=True))
print(f"all_public_surfaces_same_object={all_same}")
print("identity_probe_result=" + json.dumps(identity, sort_keys=True))
print("memory_runtime_probe_result=" + json.dumps(memory_runtime, sort_keys=True))
print("multipdf_probe_result=" + json.dumps(multipdf, sort_keys=True))

failures: list[str] = []

if not all_same:
    failures.append("public router surfaces no longer share one canonical function object")

if identity.get("action") != "USER_IDENTITY_SUMMARY":
    failures.append(f"identity route action drifted: {identity.get('action')!r}")

if memory_runtime.get("action") != "EXPLAIN_MEMORY_RUNTIME":
    failures.append(f"memory-runtime route action drifted: {memory_runtime.get('action')!r}")

memory_meta = memory_runtime.get("meta") or {}
if memory_meta.get("response_contract") != "canonical_grounded_memory_runtime_no_raw_gguf":
    failures.append("memory-runtime response contract drifted")

if multipdf.get("action") != "ANALYZE_PDF":
    failures.append(f"multi-PDF action drifted: {multipdf.get('action')!r}")

multi_args = multipdf.get("args") or {}
if multi_args.get("paths") != ["/tmp/a.pdf", "/tmp/b.pdf"]:
    failures.append(f"multi-PDF paths drifted: {multi_args.get('paths')!r}")

multi_meta = multipdf.get("meta") or {}
matched_by = str(multi_meta.get("matched_by") or "")
if matched_by.count("phase11_multipdf") != 1:
    failures.append(f"multi-PDF matched_by idempotency drifted: {matched_by!r}")

if failures:
    print("DIRECT_RUNTIME_SANITY_PROBE_FAIL")
    for item in failures:
        print("FAIL:", item)
    raise SystemExit(1)

print("DIRECT_RUNTIME_SANITY_PROBE_PASS")
PY

echo "=== DIRECT RUNTIME SANITY PROBE ===" | tee "$OUT/15_direct_runtime_probe.txt"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
python3 "$OUT/14_direct_runtime_probe.py" 2>&1 | tee -a "$OUT/15_direct_runtime_probe.txt"

python3 - "$ROUTER" "$OUT/16_structural_postpatch_audit.txt" "$PATCH_MARKER" "$PHASE38_MARKER" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

router = Path(sys.argv[1])
out = Path(sys.argv[2])
patch_marker = sys.argv[3]
phase38_marker = sys.argv[4]

src = router.read_text(encoding="utf-8")
lines = src.splitlines()

marker_line = next((i for i, line in enumerate(lines, start=1) if phase38_marker in line), None)
if marker_line is None:
    raise SystemExit("Phase38 marker missing during structural post-patch audit.")

tree = ast.parse(src)

EXPECTED_GROUPS = [
    {
        "_eli_profile_scope_low",
        "_eli_profile_scope_result",
        "_eli_is_explicit_preference_request",
        "_eli_is_generic_profile_inventory",
        "_eli_is_full_profile_dump",
    },
    {"_eli_is_memory_count_question"},
    {"_eli_recent_memory_processing_question"},
    {"_eli_self_report_recent_updates_question"},
    {"_eli_gui_audit_actual_scan_v2"},
    {
        "_eli_memory_runtime_route_lock_should_trigger",
        "_eli_memory_runtime_route_lock_result",
    },
]

def helper_names_from_try(node: ast.Try) -> set[str]:
    return {
        stmt.name
        for stmt in node.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

remaining_matches = []
for stmt in tree.body:
    if not isinstance(stmt, ast.Try):
        continue
    if stmt.lineno >= marker_line:
        continue
    helpers = helper_names_from_try(stmt)
    if helpers in EXPECTED_GROUPS:
        remaining_matches.append((stmt.lineno, stmt.end_lineno, sorted(helpers)))

patch_marker_count = src.count(patch_marker)

lines_out = [
    "=== PHASE 53 STRUCTURAL POST-PATCH AUDIT ===",
    f"PHASE38_MARKER_LINE={marker_line}",
    f"PATCH_MARKER_COUNT={patch_marker_count}",
    f"REMAINING_TARGET_HELPER_TRYBLOCK_COUNT={len(remaining_matches)}",
]

for start, end, helpers in remaining_matches:
    lines_out.append(f"REMAINING lines={start}-{end} helpers={','.join(helpers)}")

failures: list[str] = []

if patch_marker_count != 6:
    failures.append(f"expected 6 Phase53 hoist markers; observed {patch_marker_count}")

if remaining_matches:
    failures.append("one or more targeted helper Try blocks remain after hoist")

if failures:
    lines_out.append("")
    lines_out.append("FAILURES:")
    lines_out.extend(f"- {item}" for item in failures)
    out.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print("\n".join(lines_out))
    raise SystemExit("Phase53 structural post-patch audit failed.")

lines_out.append("PHASE53_STRUCTURAL_POSTPATCH_AUDIT_PASS")
out.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
print("\n".join(lines_out))
PY

{
  echo "=== PHASE 53 DIGEST ==="
  echo "Router compile: PASS"
  echo "Helper Try-block hoist transform: PASS"
  echo "Exact Phase36 semantic baseline equality: PASS"
  echo "Phase45b remaining mixed pre-Phase38 Try-block count: 0"
  echo "Direct runtime sanity probe: PASS"
  echo "Structural post-patch audit: PASS"
  echo
  echo "Phase53 succeeded."
  echo
  echo "The six final helper/import-only pre-Phase38 Try/except shells have been"
  echo "removed. Their live helper bodies now sit directly at module scope."
  echo "The retired except branches were diagnostic-only print-and-swallow shells;"
  echo "no active routing semantics changed."
  echo
  echo "Review:"
  echo "- 04_selected_tryblock_manifest.txt"
  echo "- 06_phase53_source_diff.patch"
  echo "- 10_phase36_exact_semantic_compare.txt"
  echo "- 11_phase36_exact_semantic_diff.txt"
  echo "- 13_phase45b_postpatch_assertions.txt"
  echo "- 15_direct_runtime_probe.txt"
  echo "- 16_structural_postpatch_audit.txt"
  echo
  echo "PHASE53_OUT=$OUT"
} | tee "$OUT/17_console_digest.txt"

echo
cat "$OUT/17_console_digest.txt"
