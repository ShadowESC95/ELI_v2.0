#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase33_router_public_surface_canonicalisation_${STAMP}"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT/backups"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase33.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 33 — Router Public Surface Canonicalisation

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase 32 proved that ELI's exported router surfaces had drifted:

- route() and route_intent() were on the final live route chain
- route_command() was partially stale
- parse_command() and classify() were more stale

This caused real routing disagreements for:
- memory count grounding
- recent memory processing
- GUI audit proof requests
- multi-PDF path enrichment
- memory-runtime contract metadata

This repair:
1. makes Phase 11 multi-PDF enrichment idempotent;
2. binds all public routing surfaces to the final canonical route() object;
3. verifies zero public-surface parity mismatches for the Phase 32 contract matrix.

This does **not** yet flatten the historical in-file wrapper stack.  
That structural refactor should only happen after this public-surface authority is proven stable.
EOF

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

text = router_path.read_text(encoding="utf-8")
changes: list[str] = []

# ------------------------------------------------------------------
# 1. Make Phase 11 multi-PDF matched_by enrichment idempotent
# ------------------------------------------------------------------

old = '                    meta["matched_by"] = str(meta.get("matched_by") or "analyze.pdf") + "+phase11_multipdf"\n'

new = '''                    # ELI_PHASE33_MULTIPDF_IDEMPOTENT
                    _phase11_matched_by = str(meta.get("matched_by") or "analyze.pdf")
                    if "+phase11_multipdf" not in _phase11_matched_by:
                        meta["matched_by"] = _phase11_matched_by + "+phase11_multipdf"
                    else:
                        meta["matched_by"] = _phase11_matched_by
'''

if old in text:
    text = text.replace(old, new, 1)
    changes.append("multi-PDF matched_by enrichment made idempotent")
elif "ELI_PHASE33_MULTIPDF_IDEMPOTENT" in text:
    changes.append("multi-PDF idempotence already present; left unchanged")
else:
    raise RuntimeError("Could not locate Phase 11 matched_by enrichment anchor")

# ------------------------------------------------------------------
# 2. Append canonical public-surface export contract
# ------------------------------------------------------------------

marker = "ELI_PHASE33_CANONICAL_PUBLIC_ROUTER_SURFACE_EXPORT"

canonical_block = r'''

# =============================================================================
# ELI_PHASE33_CANONICAL_PUBLIC_ROUTER_SURFACE_EXPORT
#
# Phase 32 proved that the exported router surfaces had drifted:
#   - route / route_intent were on the latest final route chain
#   - route_command was partially stale
#   - parse_command / classify were more stale
#
# Do not let these historical aliases capture old intermediate route wrappers.
# Until router_enhanced.py is structurally flattened, all exported public routing
# surfaces must resolve to the single final route() authority below.
# =============================================================================
try:
    _ELI_PHASE33_FINAL_CANONICAL_ROUTE = route

    if callable(_ELI_PHASE33_FINAL_CANONICAL_ROUTE):
        route_intent = _ELI_PHASE33_FINAL_CANONICAL_ROUTE
        route_command = _ELI_PHASE33_FINAL_CANONICAL_ROUTE
        parse_command = _ELI_PHASE33_FINAL_CANONICAL_ROUTE
        classify = _ELI_PHASE33_FINAL_CANONICAL_ROUTE

        print(
            "[ROUTER] canonical public routing surfaces rebound to final route",
            flush=True,
        )
    else:
        print(
            "[ROUTER] canonical public routing surface export skipped: final route is not callable",
            flush=True,
        )

except Exception as _eli_phase33_router_surface_err:
    print(
        f"[ROUTER] canonical public routing surface export failed: "
        f"{_eli_phase33_router_surface_err}",
        flush=True,
    )
# =============================================================================
'''

if marker not in text:
    if not text.endswith("\n"):
        text += "\n"
    text += canonical_block
    changes.append("all public router surfaces rebound to final canonical route()")
else:
    changes.append("canonical public router surface export already present; left unchanged")

router_path.write_text(text, encoding="utf-8")

(out / "01_changes_applied.txt").write_text(
    "\n".join(f"- {item}" for item in changes) + "\n",
    encoding="utf-8",
)
PY

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/02_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])

PROMPTS = [
    {
        "id": "runtime_status_full",
        "text": "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
    },
    {
        "id": "memory_runtime_exact",
        "text": "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    },
    {
        "id": "personal_memory_summary",
        "text": "What do you know about me from memory?",
    },
    {
        "id": "name_source_audit",
        "text": "How do you know my name?",
    },
    {
        "id": "memory_count",
        "text": "How many memories do you have?",
    },
    {
        "id": "recent_memory_processing",
        "text": "What memories have you been processing lately?",
    },
    {
        "id": "self_report_recent_updates",
        "text": "What have you been working on recently?",
    },
    {
        "id": "gui_actual_scan_proof",
        "text": "Did you actually scan the GUI file in full?",
    },
    {
        "id": "play_media_query",
        "text": "play guilty conscience by eminem on spotify",
    },
    {
        "id": "tiny_fragment",
        "text": "resil",
    },
    {
        "id": "short_followup",
        "text": "continue",
    },
    {
        "id": "story_status_followup",
        "text": "what's the story",
    },
    {
        "id": "volume_up",
        "text": "volume up",
    },
    {
        "id": "pause_netflix",
        "text": "pause netflix",
    },
    {
        "id": "pdf_single",
        "text": "analyze /tmp/a.pdf",
    },
    {
        "id": "pdf_multi",
        "text": "analyze /tmp/a.pdf and /tmp/b.pdf",
    },
]

SURFACE_NAMES = (
    "route",
    "route_intent",
    "route_command",
    "parse_command",
    "classify",
)

META_KEYS = (
    "matched_by",
    "task_family",
    "need_grounding",
    "grounded_required",
    "allow_chat_without_evidence",
    "forbid_chat_fallback",
    "response_contract",
    "multipdf_count",
    "requires_grounded_synthesis",
    "requires_output_validation",
    "quick_direct_allowed",
    "forbid_unverified_generation",
)

def simplify(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): simplify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [simplify(v) for v in value]
    if isinstance(value, tuple):
        return [simplify(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)

def summarize(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"kind": type(result).__name__, "repr": repr(result)}

    args = result.get("args") if isinstance(result.get("args"), dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}

    return {
        "action": result.get("action"),
        "confidence": result.get("confidence"),
        "args": simplify(args),
        "meta": {
            key: simplify(meta.get(key))
            for key in META_KEYS
            if key in meta
        },
    }

def parity_key(summary: dict[str, Any]) -> dict[str, Any]:
    args = summary.get("args") if isinstance(summary.get("args"), dict) else {}
    meta = summary.get("meta") if isinstance(summary.get("meta"), dict) else {}

    key_args = {}
    for key in (
        "question",
        "message",
        "name",
        "query",
        "path",
        "paths",
        "memory_scope",
        "profile_scope",
        "identity_scope",
        "self_report_scope",
        "audit_depth",
        "proof_requested",
        "require_timestamps",
        "require_full_file_read_evidence",
    ):
        if key in args:
            key_args[key] = args[key]

    key_meta = {}
    for key in (
        "task_family",
        "need_grounding",
        "grounded_required",
        "allow_chat_without_evidence",
        "forbid_chat_fallback",
        "response_contract",
        "multipdf_count",
        "requires_grounded_synthesis",
        "requires_output_validation",
        "quick_direct_allowed",
        "forbid_unverified_generation",
    ):
        if key in meta:
            key_meta[key] = meta[key]

    return {
        "action": summary.get("action"),
        "args": key_args,
        "meta": key_meta,
    }

import eli.execution.router_enhanced as router

surface_probe = []
surface_probe.append("=== PUBLIC ROUTER SURFACE IDENTITY PROBE ===")

surface_functions = {}
for name in SURFACE_NAMES:
    fn = getattr(router, name, None)
    surface_functions[name] = fn
    surface_probe.append(
        f"{name}: "
        f"callable={callable(fn)} "
        f"id={id(fn)} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else '-'} "
        f"repr={fn!r}"
    )

canonical = surface_functions["route"]
identity_ok = all(surface_functions[name] is canonical for name in SURFACE_NAMES)

surface_probe.append("")
surface_probe.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={identity_ok}")

(out / "03_public_surface_identity_probe.txt").write_text(
    "\n".join(surface_probe) + "\n",
    encoding="utf-8",
)

records = []
mismatches = 0

for prompt in PROMPTS:
    row = {
        "id": prompt["id"],
        "text": prompt["text"],
        "surfaces": {},
    }

    reference_key = None

    for name in SURFACE_NAMES:
        fn = surface_functions[name]
        result = fn(prompt["text"])
        summary = summarize(result)
        key = parity_key(summary)
        row["surfaces"][name] = {
            "summary": summary,
            "parity_key": key,
        }

        if name == "route":
            reference_key = key
        elif key != reference_key:
            mismatches += 1

    records.append(row)

(out / "04_public_surface_contract_results.json").write_text(
    json.dumps(records, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

parity_lines = []
parity_lines.append("=== PHASE 33 ROUTER SURFACE PARITY REPORT ===")
parity_lines.append("Reference surface: route")
parity_lines.append("")

for row in records:
    parity_lines.append("=" * 108)
    parity_lines.append(f"{row['id']}: {row['text']}")
    parity_lines.append("=" * 108)

    ref = row["surfaces"]["route"]["parity_key"]
    parity_lines.append(f"route: {json.dumps(ref, ensure_ascii=False, sort_keys=True)}")

    for name in SURFACE_NAMES[1:]:
        key = row["surfaces"][name]["parity_key"]
        status = "MATCH" if key == ref else "MISMATCH"
        parity_lines.append(
            f"{name}: {status} {json.dumps(key, ensure_ascii=False, sort_keys=True)}"
        )

    parity_lines.append("")

parity_lines.append("=" * 108)
parity_lines.append(f"TOTAL_SURFACE_MISMATCHES={mismatches}")
parity_lines.append("=" * 108)

(out / "05_public_surface_parity_report.txt").write_text(
    "\n".join(parity_lines) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------
# Hard assertions for the Phase 32 defects
# ------------------------------------------------------------

checks = []
failures = []

def check(label: str, condition: bool, detail: str) -> None:
    status = "PASS" if condition else "FAIL"
    checks.append(f"{status}: {label} — {detail}")
    if not condition:
        failures.append(label)

# 1. All surface identities collapsed
check(
    "canonical surface identity",
    identity_ok,
    f"all public surfaces same object = {identity_ok}",
)

# 2. No parity mismatches
check(
    "public surface parity",
    mismatches == 0,
    f"mismatch count = {mismatches}",
)

def route_for(prompt_id: str) -> dict[str, Any]:
    for row in records:
        if row["id"] == prompt_id:
            return row["surfaces"]["route"]["summary"]
    raise KeyError(prompt_id)

memory_count = route_for("memory_count")
check(
    "memory count route scope",
    memory_count.get("action") == "MEMORY_STATUS"
    and memory_count.get("args", {}).get("memory_scope") == "count_only",
    json.dumps(memory_count, ensure_ascii=False, sort_keys=True),
)

recent_processing = route_for("recent_memory_processing")
check(
    "recent memory processing grounded route",
    recent_processing.get("action") == "MEMORY_STATUS"
    and recent_processing.get("args", {}).get("memory_scope") == "recent_processing",
    json.dumps(recent_processing, ensure_ascii=False, sort_keys=True),
)

gui_proof = route_for("gui_actual_scan_proof")
check(
    "GUI actual-scan proof route",
    gui_proof.get("action") == "GUI_RUNTIME_AUDIT"
    and gui_proof.get("args", {}).get("proof_requested") is True,
    json.dumps(gui_proof, ensure_ascii=False, sort_keys=True),
)

memory_runtime = route_for("memory_runtime_exact")
check(
    "memory runtime strict route lock retained",
    memory_runtime.get("action") == "EXPLAIN_MEMORY_RUNTIME"
    and memory_runtime.get("meta", {}).get("response_contract") == "canonical_grounded_memory_runtime_no_raw_gguf",
    json.dumps(memory_runtime, ensure_ascii=False, sort_keys=True),
)

pdf_multi = route_for("pdf_multi")
pdf_paths = pdf_multi.get("args", {}).get("paths")
pdf_matched_by = str(pdf_multi.get("meta", {}).get("matched_by") or "")
check(
    "multi-PDF paths retained",
    pdf_multi.get("action") == "ANALYZE_PDF"
    and pdf_paths == ["/tmp/a.pdf", "/tmp/b.pdf"],
    json.dumps(pdf_multi, ensure_ascii=False, sort_keys=True),
)
check(
    "multi-PDF matched_by idempotent",
    pdf_matched_by.count("+phase11_multipdf") == 1,
    f"matched_by={pdf_matched_by!r}",
)

(out / "06_targeted_phase32_defect_assertions.txt").write_text(
    "\n".join(checks) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------
# Structural duplicates snapshot — expected to remain for later flattening
# ------------------------------------------------------------

router_source = Path("eli/execution/router_enhanced.py").read_text(encoding="utf-8")
tree = ast.parse(router_source)
module_defs = [
    node.name
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
]
duplicates = sorted({
    name
    for name in module_defs
    if module_defs.count(name) > 1
})

dupe_lines = []
dupe_lines.append("=== STRUCTURAL MODULE-LEVEL DUPLICATE FUNCTION NAMES ===")
dupe_lines.append(", ".join(duplicates) if duplicates else "none")
dupe_lines.append("")
dupe_lines.append(
    "Note: Phase 33 fixes runtime public-surface drift. "
    "The historical in-file route()/route_intent() wrapper definitions are still "
    "structural debt to be flattened in the dedicated router consolidation pass."
)

(out / "07_structural_duplicate_snapshot.txt").write_text(
    "\n".join(dupe_lines) + "\n",
    encoding="utf-8",
)

digest = []
digest.append("=== PHASE 33 DIGEST ===")
digest.append(f"Canonical public surface identity: {identity_ok}")
digest.append(f"Public surface mismatch count: {mismatches}")
digest.append(f"Targeted assertion failures: {len(failures)}")
if failures:
    digest.append("Failures:")
    digest.extend(f"- {item}" for item in failures)
else:
    digest.append("All targeted Phase 32 defects verified repaired.")
digest.append("")
digest.append("See:")
digest.append("- 03_public_surface_identity_probe.txt")
digest.append("- 05_public_surface_parity_report.txt")
digest.append("- 06_targeted_phase32_defect_assertions.txt")
digest.append("- 07_structural_duplicate_snapshot.txt")

(out / "08_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))

if failures:
    raise SystemExit(1)
PY

diff -u \
  "$OUT/backups/router_enhanced.py.before_phase33.bak" \
  "$ROUTER" \
  > "$OUT/09_router_enhanced_phase33.diff" || true

{
  echo
  echo "## Files produced"
  for f in "$OUT"/*; do
    printf -- '- `%s`\n' "$(basename "$f")"
  done
  echo
  echo "PHASE33_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE33_OUT=$OUT"
