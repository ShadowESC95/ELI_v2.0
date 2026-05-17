#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase32_router_surface_parity_contract_regression_audit_${STAMP}"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 32 — Router Surface Parity / Contract Regression Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Audit purpose

This audit determines whether the stacked router wrapper chain remains
semantically coherent across the public routing surfaces:

- route()
- route_intent()
- route_command()
- parse_command()
- classify()

It also snapshots high-value routing contracts before any consolidation patch.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/00_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import inspect
import json
import sys
import traceback
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
        "id": "open_spotify_typo",
        "text": "open potify",
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

META_KEYS = (
    "matched_by",
    "task_family",
    "need_grounding",
    "grounded_required",
    "allow_chat_without_evidence",
    "forbid_chat_fallback",
    "response_contract",
    "multipdf_count",
    "memory_scope",
    "profile_scope_contract",
    "identity_scope_contract",
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

def summarize_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "kind": type(result).__name__,
            "repr": repr(result),
        }

    args = result.get("args") if isinstance(result.get("args"), dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}

    return {
        "action": result.get("action"),
        "confidence": result.get("confidence"),
        "args": simplify(args),
        "meta_focus": {
            key: simplify(meta.get(key))
            for key in META_KEYS
            if key in meta
        },
        "top_level_keys": sorted(str(k) for k in result.keys()),
    }

def parity_key(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Compare semantically important routing outputs, not incidental confidence
    formatting or every metadata decoration.
    """
    args = summary.get("args") if isinstance(summary.get("args"), dict) else {}
    meta = summary.get("meta_focus") if isinstance(summary.get("meta_focus"), dict) else {}

    important_args = {}
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
            important_args[key] = args[key]

    important_meta = {}
    for key in (
        "task_family",
        "need_grounding",
        "grounded_required",
        "allow_chat_without_evidence",
        "forbid_chat_fallback",
        "response_contract",
        "multipdf_count",
    ):
        if key in meta:
            important_meta[key] = meta[key]

    return {
        "action": summary.get("action"),
        "args": important_args,
        "meta": important_meta,
    }

runtime_lines: list[str] = []
runtime_lines.append("=== IMPORT / PUBLIC ROUTING SURFACE PROBE ===")

try:
    import eli.execution.router_enhanced as router
except Exception as exc:
    runtime_lines.append(f"IMPORT_FAILED={type(exc).__name__}: {exc}")
    runtime_lines.append(traceback.format_exc())
    (out / "01_runtime_surface_probe.txt").write_text("\n".join(runtime_lines) + "\n", encoding="utf-8")
    raise SystemExit(1)

SURFACES = []
for name in ("route", "route_intent", "route_command", "parse_command", "classify"):
    obj = getattr(router, name, None)
    if callable(obj):
        SURFACES.append(name)
        runtime_lines.append(
            f"{name}: firstlineno={getattr(getattr(obj, '__code__', None), 'co_firstlineno', None)} "
            f"signature={inspect.signature(obj)} repr={obj!r}"
        )
    else:
        runtime_lines.append(f"{name}: MISSING_OR_NOT_CALLABLE repr={obj!r}")

(out / "01_runtime_surface_probe.txt").write_text("\n".join(runtime_lines) + "\n", encoding="utf-8")

records: list[dict[str, Any]] = []

for prompt in PROMPTS:
    rec: dict[str, Any] = {
        "id": prompt["id"],
        "text": prompt["text"],
        "surfaces": {},
    }

    for surface in SURFACES:
        fn = getattr(router, surface)
        try:
            result = fn(prompt["text"])
            summary = summarize_result(result)
            rec["surfaces"][surface] = {
                "ok": True,
                "summary": summary,
                "parity_key": parity_key(summary),
            }
        except Exception as exc:
            rec["surfaces"][surface] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }

    records.append(rec)

(out / "02_contract_probe_results.json").write_text(
    json.dumps(records, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

# ------------------------------------------------------------
# Compare route vs other public surfaces
# ------------------------------------------------------------

parity_lines: list[str] = []
parity_lines.append("=== ROUTER SURFACE PARITY REPORT ===")
parity_lines.append("Reference surface: route")
parity_lines.append("")

mismatch_count = 0
error_count = 0

for rec in records:
    pid = rec["id"]
    text = rec["text"]
    surfaces = rec["surfaces"]

    parity_lines.append("=" * 108)
    parity_lines.append(f"{pid}: {text}")
    parity_lines.append("=" * 108)

    route_rec = surfaces.get("route")
    if not route_rec or not route_rec.get("ok"):
        parity_lines.append("route: ERROR or missing; cannot compare this case.")
        error_count += 1
        parity_lines.append("")
        continue

    route_key = route_rec["parity_key"]
    parity_lines.append(f"route parity key: {json.dumps(route_key, ensure_ascii=False, sort_keys=True)}")

    for surface in SURFACES:
        if surface == "route":
            continue

        item = surfaces.get(surface)
        if not item:
            parity_lines.append(f"{surface}: MISSING")
            mismatch_count += 1
            continue

        if not item.get("ok"):
            parity_lines.append(f"{surface}: ERROR {item.get('error')}")
            error_count += 1
            mismatch_count += 1
            continue

        key = item["parity_key"]
        same = key == route_key
        parity_lines.append(
            f"{surface}: {'MATCH' if same else 'MISMATCH'} "
            f"{json.dumps(key, ensure_ascii=False, sort_keys=True)}"
        )
        if not same:
            mismatch_count += 1

    parity_lines.append("")

parity_lines.append("=" * 108)
parity_lines.append(f"TOTAL_SURFACE_MISMATCHES={mismatch_count}")
parity_lines.append(f"TOTAL_SURFACE_ERRORS={error_count}")
parity_lines.append("=" * 108)

(out / "03_surface_parity_report.txt").write_text(
    "\n".join(parity_lines) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------
# Compact contract matrix
# ------------------------------------------------------------

matrix_lines: list[str] = []
matrix_lines.append("=== COMPACT CONTRACT MATRIX ===")
matrix_lines.append("id | surface | action | matched_by | task_family | key_args")
matrix_lines.append("-" * 160)

for rec in records:
    for surface in SURFACES:
        item = rec["surfaces"].get(surface, {})
        if not item.get("ok"):
            matrix_lines.append(f"{rec['id']} | {surface} | ERROR | - | - | {item.get('error', '')}")
            continue

        summary = item["summary"]
        args = summary.get("args") or {}
        meta = summary.get("meta_focus") or {}
        key_args = {}
        for key in (
            "name", "query", "path", "paths", "memory_scope",
            "profile_scope", "identity_scope", "self_report_scope",
            "audit_depth", "proof_requested",
        ):
            if key in args:
                key_args[key] = args[key]

        matrix_lines.append(
            f"{rec['id']} | "
            f"{surface} | "
            f"{summary.get('action')} | "
            f"{meta.get('matched_by', '-')} | "
            f"{meta.get('task_family', '-')} | "
            f"{json.dumps(key_args, ensure_ascii=False, sort_keys=True)}"
        )

(out / "04_compact_contract_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------
# High-value PDF enrichment proof
# ------------------------------------------------------------

pdf_lines: list[str] = []
pdf_lines.append("=== MULTI-PDF ENRICHMENT CHECK ===")

for rec in records:
    if rec["id"] not in {"pdf_single", "pdf_multi"}:
        continue
    pdf_lines.append(f"--- {rec['id']} ---")
    for surface in SURFACES:
        item = rec["surfaces"].get(surface, {})
        if not item.get("ok"):
            pdf_lines.append(f"{surface}: ERROR {item.get('error')}")
            continue
        summary = item["summary"]
        pdf_lines.append(
            f"{surface}: action={summary.get('action')} "
            f"args={json.dumps(summary.get('args'), ensure_ascii=False, sort_keys=True)} "
            f"meta={json.dumps(summary.get('meta_focus'), ensure_ascii=False, sort_keys=True)}"
        )

(out / "05_multipdf_enrichment_check.txt").write_text(
    "\n".join(pdf_lines) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------
# Console digest
# ------------------------------------------------------------

digest = []
digest.append("=== PHASE 32 DIGEST ===")
digest.append("")
digest.append("Public surfaces:")
digest.extend(f"- {name}" for name in SURFACES)
digest.append("")
digest.append(f"Surface mismatches: {mismatch_count}")
digest.append(f"Surface errors: {error_count}")
digest.append("")
digest.append("See:")
digest.append("- 03_surface_parity_report.txt")
digest.append("- 04_compact_contract_matrix.txt")
digest.append("- 05_multipdf_enrichment_check.txt")

(out / "06_console_digest.txt").write_text("\n".join(digest) + "\n", encoding="utf-8")
print("\n".join(digest))
PY

{
  echo
  echo "## Files produced"
  for f in "$OUT"/*; do
    printf -- '- %s\n' "$(basename "$f")"
  done
  echo
  echo "PHASE32_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE32_OUT=$OUT"
