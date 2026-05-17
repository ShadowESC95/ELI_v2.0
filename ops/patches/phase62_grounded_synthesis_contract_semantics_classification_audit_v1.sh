#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase62_grounded_synthesis_contract_semantics_classification_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase62 — Grounded Synthesis Contract Semantics Classification Audit

Generated: $(date -Is)  
Root: $ROOT  
Router: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase61 proved that four emitted router contract markers have no direct
non-router literal references:

1. grounded_required
2. forbid_chat_fallback
3. forbid_unverified_generation
4. canonical_grounded_memory_runtime_no_raw_gguf

Phase62 determines whether these are:

- genuinely missing downstream enforcement;
- redundant aliases of already-enforced contracts;
- action-specific policies enforced without literal key/value lookup;
- or misleading dead metadata that should later be normalised or removed.

This phase does not modify source.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])
root = Path.cwd()
router_path = root / "eli/execution/router_enhanced.py"

router_mod = importlib.import_module("eli.execution.router_enhanced")

FAILED_MARKERS = [
    "grounded_required",
    "forbid_chat_fallback",
    "forbid_unverified_generation",
    "canonical_grounded_memory_runtime_no_raw_gguf",
]

CASES: list[tuple[str, str]] = [
    (
        "memory_runtime_exact",
        "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    ),
    (
        "memory_count",
        "How many memories do you have?",
    ),
    (
        "recent_memory_processing",
        "What memories have you been processing lately?",
    ),
    (
        "self_report_recent_updates",
        "What have you been working on recently?",
    ),
    (
        "gui_actual_scan_proof",
        "Did you actually scan the GUI file in full?",
    ),
]

# ---------------------------------------------------------------------
# 1. Runtime emission matrix
# ---------------------------------------------------------------------

runtime_rows: list[dict[str, Any]] = []

for case_id, prompt in CASES:
    result = router_mod.route(prompt)
    if not isinstance(result, dict):
        result = {"__non_dict__": repr(result)}

    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    row = {
        "case_id": case_id,
        "prompt": prompt,
        "action": result.get("action"),
        "args": result.get("args") or {},
        "meta": meta,
        "failed_markers_present": {
            marker: (
                marker in meta
                if marker != "canonical_grounded_memory_runtime_no_raw_gguf"
                else meta.get("response_contract") == marker
            )
            for marker in FAILED_MARKERS
        },
    }
    runtime_rows.append(row)

(out / "01_runtime_failed_marker_emission_matrix.json").write_text(
    json.dumps(runtime_rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

lines = ["=== PHASE62 RUNTIME FAILED-MARKER EMISSION MATRIX ==="]
for row in runtime_rows:
    lines.extend([
        "",
        f"[{row['case_id']}]",
        f"action={row['action']}",
        f"prompt={row['prompt']}",
        f"args={json.dumps(row['args'], sort_keys=True, ensure_ascii=False)}",
        f"meta={json.dumps(row['meta'], sort_keys=True, ensure_ascii=False)}",
        f"failed_markers_present={json.dumps(row['failed_markers_present'], sort_keys=True)}",
    ])

(out / "02_runtime_failed_marker_emission_matrix.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 2. Router source emission locations
# ---------------------------------------------------------------------

router_text = router_path.read_text(encoding="utf-8")
router_lines = router_text.splitlines()

source_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)

for marker in FAILED_MARKERS:
    for idx, line in enumerate(router_lines, start=1):
        if marker in line:
            start = max(1, idx - 4)
            end = min(len(router_lines), idx + 4)
            window = "\n".join(
                f"{ln:>6}: {router_lines[ln - 1]}"
                for ln in range(start, end + 1)
            )
            source_hits[marker].append({
                "line": idx,
                "window": window,
            })

(out / "03_router_failed_marker_source_hits.json").write_text(
    json.dumps(source_hits, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

source_render = ["=== ROUTER FAILED-MARKER SOURCE HITS ==="]
for marker in FAILED_MARKERS:
    hits = source_hits.get(marker, [])
    source_render.append("")
    source_render.append(f"[{marker}] hit_count={len(hits)}")
    if not hits:
        source_render.append("NO_ROUTER_HITS")
        continue
    for hit in hits:
        source_render.append(f"--- line {hit['line']} ---")
        source_render.append(hit["window"])

(out / "04_router_failed_marker_source_hits.txt").write_text(
    "\n".join(source_render) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 3. Downstream equivalent-enforcement evidence search
# ---------------------------------------------------------------------

SEARCH_FILES = [
    root / "eli/kernel/engine.py",
    root / "eli/execution/executor_enhanced.py",
    root / "eli/runtime/deterministic_grounding_gate.py",
    root / "eli/runtime/control_contracts.py",
    root / "eli/runtime/response_contracts.py",
    root / "eli/runtime/response_policy.py",
    root / "eli/runtime/final_response_provider.py",
    root / "eli/contracts/grounded_control.py",
    root / "eli/cognition/agent_bus.py",
    root / "eli/cognition/orchestrator.py",
]

SEARCH_PATTERNS: dict[str, list[str]] = {
    "grounded_required": [
        "need_grounding",
        "requires_grounded_synthesis",
        "grounded_status",
        "memory_runtime",
        "self_report_runtime",
        "grounded_audit",
    ],
    "forbid_chat_fallback": [
        "allow_chat_without_evidence",
        "forbid_chat",
        "chat fallback",
        "blocked",
        "return None",
        "not chat",
    ],
    "forbid_unverified_generation": [
        "requires_grounded_synthesis",
        "requires_output_validation",
        "forbid_unverified",
        "unverified",
        "output_validation",
    ],
    "canonical_grounded_memory_runtime_no_raw_gguf": [
        "EXPLAIN_MEMORY_RUNTIME Quick",
        "EXPLAIN_MEMORY_RUNTIME non-Quick",
        "EXPLAIN_MEMORY_RUNTIME",
        "memory_runtime",
        "raw gguf",
        "no raw",
    ],
}

equivalent_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)

for marker, patterns in SEARCH_PATTERNS.items():
    for path in SEARCH_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            matched = [p for p in patterns if p.lower() in low]
            if matched:
                equivalent_hits[marker].append({
                    "path": str(path.relative_to(root)),
                    "line": idx,
                    "matched_patterns": matched,
                    "text": line.rstrip(),
                })

(out / "05_equivalent_enforcement_evidence_hits.json").write_text(
    json.dumps(equivalent_hits, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

equiv_lines = ["=== PHASE62 EQUIVALENT-ENFORCEMENT EVIDENCE HITS ==="]
for marker in FAILED_MARKERS:
    hits = equivalent_hits.get(marker, [])
    equiv_lines.append("")
    equiv_lines.append(f"[{marker}] hit_count={len(hits)}")
    if not hits:
        equiv_lines.append("NO_EQUIVALENT_ENFORCEMENT_HINTS")
        continue
    for hit in hits[:120]:
        equiv_lines.append(
            f"{hit['path']}:{hit['line']}: "
            f"patterns={hit['matched_patterns']} :: {hit['text']}"
        )
    if len(hits) > 120:
        equiv_lines.append(f"... truncated {len(hits) - 120} additional hit(s)")

(out / "06_equivalent_enforcement_evidence_hits.txt").write_text(
    "\n".join(equiv_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 4. Focused source windows for likely live enforcement points
# ---------------------------------------------------------------------

WINDOW_TARGETS = {
    "memory_runtime_engine": ("eli/kernel/engine.py", ["EXPLAIN_MEMORY_RUNTIME Quick", "EXPLAIN_MEMORY_RUNTIME non-Quick"]),
    "memory_count_executor": ("eli/execution/executor_enhanced.py", ["requires_grounded_synthesis", "requires_output_validation", "quick_direct_allowed"]),
    "recent_memory_route_consumers": ("eli/execution/executor_enhanced.py", ['memory_scope") == "recent_processing"', "recent_processing"]),
    "self_report_engine": ("eli/kernel/engine.py", ["SELF_REPORT_RECENT_UPDATES", "quick_direct_allowed"]),
    "grounding_gate_actions": ("eli/runtime/deterministic_grounding_gate.py", ["EXPLAIN_MEMORY_RUNTIME", "MEMORY_STATUS", "SELF_REPORT"]),
}

window_out: list[str] = ["=== PHASE62 FOCUSED ENFORCEMENT SOURCE WINDOWS ==="]

for name, (rel, needles) in WINDOW_TARGETS.items():
    path = root / rel
    window_out.append("")
    window_out.append("=" * 110)
    window_out.append(name)
    window_out.append(f"path={rel}")
    window_out.append("=" * 110)

    if not path.exists():
        window_out.append("MISSING_FILE")
        continue

    lines_src = path.read_text(encoding="utf-8", errors="replace").splitlines()
    used_spans: set[tuple[int, int]] = set()

    for idx, line in enumerate(lines_src, start=1):
        if any(needle in line for needle in needles):
            start = max(1, idx - 6)
            end = min(len(lines_src), idx + 10)
            span = (start, end)
            if span in used_spans:
                continue
            used_spans.add(span)
            window_out.append(f"--- hit line {idx} ---")
            for ln in range(start, end + 1):
                window_out.append(f"{ln:>6}: {lines_src[ln - 1]}")

(out / "07_focused_enforcement_source_windows.txt").write_text(
    "\n".join(window_out) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 5. Classification draft
# ---------------------------------------------------------------------

classification: list[str] = [
    "=== PHASE62 CONTRACT SEMANTICS CLASSIFICATION DRAFT ===",
    "",
]

# grounded_required
classification.extend([
    "[grounded_required]",
    "- Direct literal downstream consumer: not found in Phase61.",
    "- Equivalent downstream semantic surfaces visible: need_grounding, requires_grounded_synthesis, task_family action families.",
    "- Preliminary classification: likely redundant alias / stale metadata, not yet proven as a missing runtime behavior.",
    "",
])

# forbid_chat_fallback
classification.extend([
    "[forbid_chat_fallback]",
    "- Direct literal downstream consumer: not found in Phase61.",
    "- Equivalent downstream semantic surfaces may exist through allow_chat_without_evidence=False plus explicit action-specific middleware.",
    "- Preliminary classification: suspicious declarative-only guard. Needs exact runtime-path proof before normalisation or removal.",
    "",
])

# forbid_unverified_generation
classification.extend([
    "[forbid_unverified_generation]",
    "- Direct literal downstream consumer: not found in Phase61.",
    "- MEMORY_STATUS count_only already emits requires_grounded_synthesis and requires_output_validation, both referenced downstream.",
    "- Preliminary classification: probably superseded by stronger explicit synthesis/validation flags, but must verify no unique semantic promise is lost.",
    "",
])

# canonical response contract
classification.extend([
    "[canonical_grounded_memory_runtime_no_raw_gguf]",
    "- Direct literal downstream consumer: not found in Phase61.",
    "- EXPLAIN_MEMORY_RUNTIME has extensive action-specific downstream handling, including explicit Quick direct and non-Quick synthesis engine branches.",
    "- Preliminary classification: likely router-local descriptive response_contract label, not the active enforcement mechanism.",
    "- Risk: misleading unless formally mapped or retired.",
    "",
])

(out / "08_contract_semantics_classification_draft.txt").write_text(
    "\n".join(classification) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 6. Targeted assertions
# ---------------------------------------------------------------------

assertions: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    assertions.append((label, ok, detail))

# Ensure the four markers are genuinely observed in runtime/source evidence.
for marker in FAILED_MARKERS:
    marker_runtime_seen = any(
        row["failed_markers_present"].get(marker, False)
        for row in runtime_rows
    )
    check(
        f"{marker} is actually emitted by at least one live route probe",
        marker_runtime_seen,
        f"{marker} was not observed in the live route emission matrix",
    )

# Equivalent evidence should exist for each failure marker. This is not proof,
# but it determines whether the failure is obviously a missing-feature void.
for marker in FAILED_MARKERS:
    check(
        f"{marker} has at least one equivalent-enforcement evidence hint downstream",
        len(equivalent_hits.get(marker, [])) > 0,
        f"no equivalent-enforcement evidence hints found for {marker}",
    )

failed = 0
assertion_lines = ["=== PHASE62 TARGETED SEMANTICS-CLASSIFICATION ASSERTIONS ==="]

for label, ok, detail in assertions:
    if ok:
        assertion_lines.append(f"PASS: {label}")
    else:
        failed += 1
        assertion_lines.append(f"FAIL: {label} — {detail}")

assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "09_targeted_semantics_classification_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 7. Verdict
# ---------------------------------------------------------------------

verdict = [
    "=== PHASE62 GROUNDED SYNTHESIS CONTRACT SEMANTICS VERDICT ===",
    f"TARGETED_ASSERTION_FAILURES={failed}",
    "",
]

if failed == 0:
    verdict.extend([
        "Verdict:",
        "- All four Phase61 failures are confirmed as live emitted markers.",
        "- All four also have at least some downstream equivalent-enforcement evidence nearby.",
        "- This means Phase61 did not prove missing runtime behavior; it proved contract-vocabulary drift / ambiguity.",
        "",
        "Recommended next phase:",
        "- Run a behavioural non-Quick/Quick execution audit for the affected actions.",
        "- That next audit should prove whether the live runtime actually obeys the intended policies:",
        "  1. Quick may return compact direct evidence.",
        "  2. Non-Quick must synthesize using grounded evidence.",
        "  3. No generic chat fallback should fabricate unsupported answers.",
        "",
        "Do not patch source yet.",
    ])
else:
    verdict.extend([
        "Verdict:",
        "- At least one Phase61 failure lacks even nearby equivalent-enforcement evidence.",
        "- That shifts suspicion toward a genuine downstream enforcement hole.",
        "- Inspect the failed semantics-classification assertions before proposing source changes.",
    ])

verdict.extend([
    "",
    "Review:",
    "- 02_runtime_failed_marker_emission_matrix.txt",
    "- 04_router_failed_marker_source_hits.txt",
    "- 06_equivalent_enforcement_evidence_hits.txt",
    "- 07_focused_enforcement_source_windows.txt",
    "- 08_contract_semantics_classification_draft.txt",
    "- 09_targeted_semantics_classification_assertions.txt",
])

(out / "10_contract_semantics_verdict.txt").write_text(
    "\n".join(verdict) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict))
print()
print(f"PHASE62_OUT={out}")

if failed:
    raise SystemExit(1)
PY
