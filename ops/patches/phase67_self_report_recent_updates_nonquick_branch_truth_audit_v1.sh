#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase67_self_report_recent_updates_nonquick_branch_truth_audit_${STAMP}"

ENGINE="eli/kernel/engine.py"
PHASE63="ops/patches/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh"

mkdir -p "$OUT"

for f in "$ENGINE" "$PHASE63"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase 67 — SELF_REPORT recent_updates Non-Quick Branch Truth Audit

## Purpose

Phase66 successfully repaired:
- the residual dict-literal synthesis_validated truth defect;
- the Phase63 heredoc shell-noise defect;
- engine syntax remained clean.

Phase63 still reports exactly one high-suspicion surface:

    SELF_REPORT.recent_updates

However, the current source also shows:
- a dedicated non-Quick synthesis helper:
      _mw_self_report_recent_updates_synthesize(...)
- a non-Quick middleware call into that helper;
- a GGUF synthesis trace line.

This audit determines whether Phase63 is:
1. correctly detecting a surviving non-Quick direct-return bypass, or
2. falsely matching the Quick direct-evidence branch / evidence packet preparation.

No source files are modified.
EOF

echo "=== PY_COMPILE ENGINE ===" | tee "$OUT/00_py_compile_engine.txt"
python3 -m py_compile "$ENGINE" 2>&1 | tee -a "$OUT/00_py_compile_engine.txt"
echo "PY_COMPILE_ENGINE_OK" | tee -a "$OUT/00_py_compile_engine.txt"

echo "=== PHASE63 BASH SYNTAX ===" | tee "$OUT/01_phase63_bash_syntax.txt"
bash -n "$PHASE63" 2>&1 | tee -a "$OUT/01_phase63_bash_syntax.txt"
echo "PHASE63_BASH_SYNTAX_OK" | tee -a "$OUT/01_phase63_bash_syntax.txt"

python3 - "$ENGINE" "$PHASE63" "$OUT" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

engine_path = Path(sys.argv[1])
phase63_path = Path(sys.argv[2])
out = Path(sys.argv[3])

engine = engine_path.read_text(encoding="utf-8")
phase63 = phase63_path.read_text(encoding="utf-8")

assertions: list[tuple[bool, str, str]] = []

def record(ok: bool, label: str, detail: str = "") -> None:
    assertions.append((ok, label, detail))

def line_no(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1

def source_window(lines: list[str], start: int, end: int, pad: int = 6) -> str:
    lo = max(1, start - pad)
    hi = min(len(lines), end + pad)
    out_lines: list[str] = []
    for n in range(lo, hi + 1):
        out_lines.append(f"{n:6d}: {lines[n-1]}")
    return "\n".join(out_lines) + "\n"

engine_lines = engine.splitlines()

# ---------------------------------------------------------------------
# 1. Locate the SELF_REPORT recent-updates middleware block
# ---------------------------------------------------------------------

start_marker = "# === ELI_ENGINE_MIDDLEWARE_SELF_REPORT_RECENT_UPDATES_V4 ==="
end_marker = "# === END ELI_ENGINE_MIDDLEWARE_SELF_REPORT_RECENT_UPDATES_V4 ==="

try:
    block_start_idx = next(i for i, line in enumerate(engine_lines, start=1) if start_marker in line)
    block_end_idx = next(i for i, line in enumerate(engine_lines, start=1) if end_marker in line)
except StopIteration:
    block_start_idx = block_end_idx = -1

record(
    block_start_idx > 0 and block_end_idx > block_start_idx,
    "SELF_REPORT recent-updates middleware block located",
    f"start={block_start_idx} end={block_end_idx}",
)

if not (block_start_idx > 0 and block_end_idx > block_start_idx):
    (out / "02_block_location_failure.txt").write_text(
        "Could not locate the expected SELF_REPORT recent-updates middleware block markers.\n",
        encoding="utf-8",
    )
    raise SystemExit("Phase67 could not locate SELF_REPORT recent-updates middleware block.")

block_lines = engine_lines[block_start_idx - 1:block_end_idx]
block_text = "\n".join(block_lines)

(out / "02_self_report_recent_updates_full_block.txt").write_text(
    source_window(engine_lines, block_start_idx, block_end_idx, pad=0),
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 2. Confirm the repaired non-Quick synthesis machinery exists in the block
# ---------------------------------------------------------------------

record(
    "_mw_self_report_recent_updates_synthesize(" in block_text,
    "middleware calls dedicated non-Quick self-report synthesis helper",
)

record(
    "SELF_REPORT recent_updates non-Quick: synthesized via GGUF" in block_text,
    "middleware emits non-Quick GGUF synthesis trace",
)

record(
    "_eli_self_mw_out" in block_text,
    "middleware stores synthesized non-Quick output separately",
)

record(
    "return _eli_self_mw_out" in block_text,
    "middleware returns synthesized non-Quick output",
)

# ---------------------------------------------------------------------
# 3. Collect lines that look like direct report returns / GGUF false flags
# ---------------------------------------------------------------------

direct_return_hits: list[dict[str, Any]] = []
gguf_false_hits: list[dict[str, Any]] = []
synth_call_hits: list[dict[str, Any]] = []

for absolute_lineno in range(block_start_idx, block_end_idx + 1):
    line = engine_lines[absolute_lineno - 1]
    stripped = line.strip()

    if "return _eli_self_mw_report" in stripped:
        direct_return_hits.append({
            "line": absolute_lineno,
            "text": stripped,
            "indent": len(line) - len(line.lstrip(" ")),
        })

    if '"gguf_used": False' in stripped or "['gguf_used'] = False" in stripped or '["gguf_used"] = False' in stripped:
        gguf_false_hits.append({
            "line": absolute_lineno,
            "text": stripped,
            "indent": len(line) - len(line.lstrip(" ")),
        })

    if "_mw_self_report_recent_updates_synthesize(" in stripped:
        synth_call_hits.append({
            "line": absolute_lineno,
            "text": stripped,
            "indent": len(line) - len(line.lstrip(" ")),
        })

(out / "03_self_report_direct_return_hits.json").write_text(
    json.dumps(direct_return_hits, indent=2) + "\n",
    encoding="utf-8",
)
(out / "04_self_report_gguf_false_hits.json").write_text(
    json.dumps(gguf_false_hits, indent=2) + "\n",
    encoding="utf-8",
)
(out / "05_self_report_synthesis_call_hits.json").write_text(
    json.dumps(synth_call_hits, indent=2) + "\n",
    encoding="utf-8",
)

record(
    len(synth_call_hits) >= 1,
    "self-report non-Quick synthesis call hit recorded",
    f"count={len(synth_call_hits)}",
)

# ---------------------------------------------------------------------
# 4. Heuristic branch classification of direct returns
# ---------------------------------------------------------------------
# We do not attempt full control-flow proof. We perform a line/indent aware scan
# over the block to classify whether direct report returns sit beneath a Quick-only
# branch, and whether any obvious non-Quick direct-return survives.

def nearest_branch_context(target_line: int) -> list[str]:
    target_idx = target_line - 1
    target_indent = len(engine_lines[target_idx]) - len(engine_lines[target_idx].lstrip(" "))
    contexts: list[str] = []

    for idx in range(target_idx - 1, block_start_idx - 2, -1):
        line = engine_lines[idx]
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < target_indent and stripped.startswith(("if ", "elif ", "else:", "try:", "except ")):
            contexts.append(f"{idx+1}:{stripped}")
            target_indent = indent
            if indent <= 12:
                break
    return contexts

classified_returns: list[dict[str, Any]] = []
quick_direct_return_count = 0
nonquick_direct_return_suspicion_count = 0

for hit in direct_return_hits:
    contexts = nearest_branch_context(hit["line"])
    ctx_blob = " | ".join(contexts).lower()

    quick_context = (
        "_eli_self_mw_quick" in ctx_blob
        or 'mode == "quick"' in ctx_blob
        or "mode == 'quick'" in ctx_blob
        or "quick" in ctx_blob and "if " in ctx_blob
    )

    nonquick_context = (
        "not _eli_self_mw_quick" in ctx_blob
        or 'mode != "quick"' in ctx_blob
        or "non-quick" in ctx_blob
    )

    classification = "QUICK_CONTEXT" if quick_context and not nonquick_context else "NONQUICK_OR_UNPROVEN_CONTEXT"

    if classification == "QUICK_CONTEXT":
        quick_direct_return_count += 1
    else:
        nonquick_direct_return_suspicion_count += 1

    classified_returns.append({
        **hit,
        "contexts": contexts,
        "classification": classification,
    })

(out / "06_self_report_direct_return_branch_classification.json").write_text(
    json.dumps(classified_returns, indent=2) + "\n",
    encoding="utf-8",
)

# It is acceptable to have report direct returns if they are Quick-only.
record(
    nonquick_direct_return_suspicion_count == 0,
    "no obvious SELF_REPORT recent_updates non-Quick direct report return remains",
    f"quick_context_direct_returns={quick_direct_return_count} nonquick_or_unproven={nonquick_direct_return_suspicion_count}",
)

# ---------------------------------------------------------------------
# 5. Probe whether Phase63's suspicion could be stale/narrow heuristic overlap
# ---------------------------------------------------------------------

phase63_hits: list[str] = []
for i, line in enumerate(phase63.splitlines(), start=1):
    low = line.lower()
    if (
        "self_report.recent_updates" in low
        or "self-report recent-updates" in low
        or "high_suspicion" in low
        or "gguf_used" in low
        or "direct" in low and "bypass" in low
    ):
        phase63_hits.append(f"{i:6d}: {line}")

(out / "07_phase63_self_report_heuristic_related_hits.txt").write_text(
    "\n".join(phase63_hits) + ("\n" if phase63_hits else ""),
    encoding="utf-8",
)

record(
    len(phase63_hits) > 0,
    "Phase63 self-report suspicion heuristic lines captured",
    f"hits={len(phase63_hits)}",
)

# ---------------------------------------------------------------------
# 6. Source windows around decisive block hits
# ---------------------------------------------------------------------

windows: list[str] = []

for hit in direct_return_hits:
    windows.append("=" * 110)
    windows.append(f"DIRECT REPORT RETURN WINDOW line={hit['line']}")
    windows.append(source_window(engine_lines, hit["line"], hit["line"], pad=10))

for hit in synth_call_hits:
    windows.append("=" * 110)
    windows.append(f"SYNTHESIS CALL WINDOW line={hit['line']}")
    windows.append(source_window(engine_lines, hit["line"], hit["line"], pad=10))

for hit in gguf_false_hits:
    windows.append("=" * 110)
    windows.append(f"GGUF_FALSE WINDOW line={hit['line']}")
    windows.append(source_window(engine_lines, hit["line"], hit["line"], pad=8))

(out / "08_decisive_engine_source_windows.txt").write_text(
    "\n".join(windows) + ("\n" if windows else ""),
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 7. Final verdict
# ---------------------------------------------------------------------

failures = [a for a in assertions if not a[0]]
truth_closed = not failures and nonquick_direct_return_suspicion_count == 0

verdict_lines = [
    "=== PHASE67 SELF_REPORT recent_updates NON-QUICK BRANCH TRUTH VERDICT ===",
    f"SELF_REPORT_RECENT_UPDATES_NONQUICK_BRANCH_TRUTH_CLOSED={str(truth_closed).upper()}",
    f"TARGETED_ASSERTION_FAILURES={len(failures)}",
    f"DIRECT_REPORT_RETURN_HITS={len(direct_return_hits)}",
    f"QUICK_CONTEXT_DIRECT_RETURN_HITS={quick_direct_return_count}",
    f"NONQUICK_OR_UNPROVEN_DIRECT_RETURN_HITS={nonquick_direct_return_suspicion_count}",
    f"SYNTHESIS_CALL_HITS={len(synth_call_hits)}",
    f"GGUF_FALSE_HITS_IN_BLOCK={len(gguf_false_hits)}",
    "",
]

if truth_closed:
    verdict_lines.extend([
        "Conclusion:",
        "- Current source shape does not show a surviving non-Quick direct-return bypass for SELF_REPORT.recent_updates.",
        "- The middleware contains the Phase65/65b non-Quick synthesis helper call and returns its output.",
        "- Phase63's remaining HIGH_SUSPICION result is therefore likely a stale or over-broad static heuristic, not a proven engine defect.",
        "- Next move should be a Phase63 audit-heuristic repair, not another engine synthesis patch.",
    ])
else:
    verdict_lines.extend([
        "Conclusion:",
        "- The source-shape audit could not close SELF_REPORT.recent_updates as clean.",
        "- Review 06_self_report_direct_return_branch_classification.json and 08_decisive_engine_source_windows.txt.",
        "- If a non-Quick direct report return is genuinely present, the next patch belongs in engine.py.",
    ])

(out / "09_branch_truth_verdict.txt").write_text(
    "\n".join(verdict_lines) + "\n",
    encoding="utf-8",
)

assertion_lines = ["=== PHASE67 TARGETED ASSERTIONS ==="]
for ok, label, detail in assertions:
    prefix = "PASS" if ok else "FAIL"
    if detail:
        assertion_lines.append(f"{prefix}: {label} — {detail}")
    else:
        assertion_lines.append(f"{prefix}: {label}")
assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={len(failures)}")

(out / "10_targeted_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict_lines))
print()
print("\n".join(assertion_lines))

PY

{
  echo "=== PHASE67 DIGEST ==="
  cat "$OUT/09_branch_truth_verdict.txt"
  echo
  echo "Review:"
  echo "- 02_self_report_recent_updates_full_block.txt"
  echo "- 03_self_report_direct_return_hits.json"
  echo "- 04_self_report_gguf_false_hits.json"
  echo "- 05_self_report_synthesis_call_hits.json"
  echo "- 06_self_report_direct_return_branch_classification.json"
  echo "- 07_phase63_self_report_heuristic_related_hits.txt"
  echo "- 08_decisive_engine_source_windows.txt"
  echo "- 10_targeted_assertions.txt"
  echo
  echo "PHASE67_OUT=$OUT"
} | tee "$OUT/11_console_digest.txt"

echo "PHASE67_OUT=$OUT"
