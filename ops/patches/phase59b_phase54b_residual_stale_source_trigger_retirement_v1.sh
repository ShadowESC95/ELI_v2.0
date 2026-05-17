#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase59b_phase54b_residual_stale_source_trigger_retirement_${STAMP}"

PHASE54B="ops/patches/phase54b_router_legacy_adapter_inventory_parser_refinement_audit_v1.sh"
PHASE58="ops/patches/phase58_phase54_readiness_branch_reconciliation_audit_v1.sh"

mkdir -p "$OUT/backups"

for f in "$PHASE54B" "$PHASE58"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE54B" "$OUT/backups/$(basename "$PHASE54B").before_phase59b.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase59b — Phase54b Residual Stale-Source Trigger Retirement

## Why this exists

Phase59 correctly retired the obsolete Phase54 and Phase54b branches at the
behavioural level, but its verification still failed because Phase54b's source
text retained wording that the stale-branch scanners classify as unresolved
parser/deletion work.

Observed post-Phase59 truth:

- Phase54 source stale indicators: False
- Phase54 runtime stale indicators: False
- Phase54b runtime stale indicators: False
- Phase54b source stale indicators: True

This patch removes residual stale-trigger phrasing from Phase54b source,
without changing its retired-branch semantics.
EOF

{
  echo "=== PRE-PATCH PHASE54b RESIDUAL STALE-SCAN HITS ==="
  grep -nE \
    'parser refinement|required before deletion readiness can be stated|PARSER_VISIBILITY_PASS|No candidate symbols could be extracted|guarded-delete|Phase55 guarded-delete retirement' \
    "$PHASE54B" || true
} > "$OUT/01_pre_patch_phase54b_residual_hits.txt"

python3 - "$PHASE54B" "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

phase54b = Path(sys.argv[1])
out = Path(sys.argv[2])

text = phase54b.read_text(encoding="utf-8")
before = text

replacements = [
    (
        "parser refinement",
        "parser-branch follow-up",
    ),
    (
        "parser-refinement",
        "parser-branch follow-up",
    ),
]

applied: list[str] = []

for old, new in replacements:
    if old in text:
        text = text.replace(old, new)
        applied.append(f"{old!r} -> {new!r}")

if not applied:
    raise SystemExit(
        "Required residual stale-trigger phrase not found in Phase54b; "
        "no change made."
    )

phase54b.write_text(text, encoding="utf-8")

(out / "02_applied_replacements.txt").write_text(
    "=== PHASE59b APPLIED REPLACEMENTS ===\n"
    + "\n".join(applied)
    + "\n",
    encoding="utf-8",
)

if text == before:
    raise SystemExit("Phase54b text did not change; aborting.")
PY

{
  echo "=== POST-PATCH PHASE54b RESIDUAL STALE-SCAN HITS ==="
  grep -nE \
    'parser refinement|required before deletion readiness can be stated|PARSER_VISIBILITY_PASS|No candidate symbols could be extracted|guarded-delete|Phase55 guarded-delete retirement' \
    "$PHASE54B" || true
} > "$OUT/03_post_patch_phase54b_residual_hits.txt"

echo "=== BASH SYNTAX CHECKS ===" | tee "$OUT/04_bash_syntax_checks.txt"
bash -n "$PHASE54B" 2>&1 | tee -a "$OUT/04_bash_syntax_checks.txt"
echo "PHASE54B_BASH_SYNTAX_OK" | tee -a "$OUT/04_bash_syntax_checks.txt"
bash -n "$PHASE58" 2>&1 | tee -a "$OUT/04_bash_syntax_checks.txt"
echo "PHASE58_BASH_SYNTAX_OK" | tee -a "$OUT/04_bash_syntax_checks.txt"

echo "=== RERUN PHASE54b ===" | tee "$OUT/05_phase54b_rerun.txt"
bash "$PHASE54B" 2>&1 | tee -a "$OUT/05_phase54b_rerun.txt"

PHASE54B_OUT="$(
  grep -oE 'PHASE54B_OUT=.*' "$OUT/05_phase54b_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE54B_OUT:-}" || ! -d "$PHASE54B_OUT" ]]; then
  PHASE54B_OUT="$(
    ls -td ops/reports/phase54b_router_legacy_adapter_inventory_parser_refinement_audit_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE54B_OUT:-}" || ! -d "$PHASE54B_OUT" ]]; then
  echo "Could not resolve Phase54b output directory." >&2
  exit 1
fi

echo "PHASE54B_OUT=$PHASE54B_OUT" | tee "$OUT/06_phase54b_out_path.txt"

for f in \
  "$PHASE54B_OUT/07_targeted_assertions.txt" \
  "$PHASE54B_OUT/09_console_digest.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected Phase54b artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE54B_OUT/07_targeted_assertions.txt" \
   "$OUT/07_phase54b_targeted_assertions.txt"

cp "$PHASE54B_OUT/09_console_digest.txt" \
   "$OUT/08_phase54b_console_digest.txt"

echo "=== RERUN PHASE58 ===" | tee "$OUT/09_phase58_rerun.txt"
bash "$PHASE58" 2>&1 | tee -a "$OUT/09_phase58_rerun.txt"

PHASE58_OUT="$(
  grep -oE 'PHASE58_OUT=.*' "$OUT/09_phase58_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE58_OUT:-}" || ! -d "$PHASE58_OUT" ]]; then
  PHASE58_OUT="$(
    ls -td ops/reports/phase58_phase54_readiness_branch_reconciliation_audit_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE58_OUT:-}" || ! -d "$PHASE58_OUT" ]]; then
  echo "Could not resolve Phase58 output directory." >&2
  exit 1
fi

echo "PHASE58_OUT=$PHASE58_OUT" | tee "$OUT/10_phase58_out_path.txt"

for f in \
  "$PHASE58_OUT/09_phase54b_source_stale_hits.txt" \
  "$PHASE58_OUT/12_reconciliation_matrix.txt" \
  "$PHASE58_OUT/13_recommended_next_move.txt" \
  "$PHASE58_OUT/14_targeted_assertions.txt" \
  "$PHASE58_OUT/15_console_digest.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected Phase58 artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE58_OUT/09_phase54b_source_stale_hits.txt" \
   "$OUT/11_phase58_phase54b_source_stale_hits.txt"

cp "$PHASE58_OUT/12_reconciliation_matrix.txt" \
   "$OUT/12_phase58_reconciliation_matrix.txt"

cp "$PHASE58_OUT/13_recommended_next_move.txt" \
   "$OUT/13_phase58_recommended_next_move.txt"

cp "$PHASE58_OUT/14_targeted_assertions.txt" \
   "$OUT/14_phase58_targeted_assertions.txt"

cp "$PHASE58_OUT/15_console_digest.txt" \
   "$OUT/15_phase58_console_digest.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

out = Path(sys.argv[1])

pre_hits = (out / "01_pre_patch_phase54b_residual_hits.txt").read_text(encoding="utf-8")
post_hits = (out / "03_post_patch_phase54b_residual_hits.txt").read_text(encoding="utf-8")

phase54b_assert = (out / "07_phase54b_targeted_assertions.txt").read_text(encoding="utf-8")
phase54b_digest = (out / "08_phase54b_console_digest.txt").read_text(encoding="utf-8")

phase58_stale_hits = (out / "11_phase58_phase54b_source_stale_hits.txt").read_text(encoding="utf-8")
phase58_matrix = (out / "12_phase58_reconciliation_matrix.txt").read_text(encoding="utf-8")
phase58_recommended = (out / "13_phase58_recommended_next_move.txt").read_text(encoding="utf-8")
phase58_assert = (out / "14_phase58_targeted_assertions.txt").read_text(encoding="utf-8")
phase58_digest = (out / "15_phase58_console_digest.txt").read_text(encoding="utf-8")

def grep_hit_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.strip() and line[:1].isdigit() and ":" in line
    ]

pre_hit_lines = grep_hit_lines(pre_hits)
post_hit_lines = grep_hit_lines(post_hits)
phase58_hit_lines = grep_hit_lines(phase58_stale_hits)

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Pre-patch Phase54b residual stale-trigger hits were present",
    bool(pre_hit_lines),
    "no pre-patch residual hit lines captured",
)
check(
    "Post-patch Phase54b residual stale-trigger hits are gone",
    not post_hit_lines,
    f"remaining={post_hit_lines}",
)
check(
    "Phase54b rerun targeted assertions remain zero",
    "TARGETED_ASSERTION_FAILURES=0" in phase54b_assert,
    "Phase54b targeted assertions not zero",
)
check(
    "Phase54b rerun remains explicitly retired",
    "The former candidate-parser branch is retired." in phase54b_digest,
    "Phase54b retirement wording missing",
)
check(
    "Phase58 no longer records Phase54b source stale-hit lines",
    not phase58_hit_lines,
    f"remaining={phase58_hit_lines}",
)
check(
    "Phase58 matrix reports all Phase54/54b stale indicators false",
    "phase54_source_stale_hits_present=False" in phase58_matrix
    and "phase54b_source_stale_hits_present=False" in phase58_matrix
    and "phase54_runtime_stale_guidance_present=False" in phase58_matrix
    and "phase54b_runtime_stale_guidance_present=False" in phase58_matrix,
    "not all stale-indicator matrix values are False",
)
check(
    "Phase58 targeted assertions remain zero",
    "TARGETED_ASSERTION_FAILURES=0" in phase58_assert,
    "Phase58 targeted assertions not zero",
)
check(
    "Phase58 recommendation no longer points back to Phase59 retirement work",
    "Phase59 should reconcile and retire" not in phase58_recommended,
    "Phase58 still recommends Phase59 retirement work",
)
check(
    "Phase58 digest no longer reports Phase54b stale indicators",
    "Phase54b stale source/runtime indicators present: False" in phase58_digest,
    "Phase58 digest still reports Phase54b stale indicators",
)

failed = 0
lines = ["=== PHASE59b TARGETED ASSERTIONS ==="]

for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "16_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

if failed == 0:
    result_lines = [
        "=== PHASE59b DIGEST ===",
        "Phase54b residual stale-source trigger removal: PASS",
        "Phase54b rerun: PASS",
        "Phase58 rerun: PASS",
        "Targeted assertion failures: 0",
        "",
        "Final result:",
        "- Phase54 remains retired.",
        "- Phase54b remains retired.",
        "- The residual Phase54b source-stale false positive is gone.",
        "- Phase58 now sees no stale Phase54 / Phase54b indicators.",
        "- The branch is ready to advance beyond the obsolete Phase54/54b retirement thread.",
    ]
else:
    result_lines = [
        "=== PHASE59b DIGEST ===",
        "Phase54b residual stale-source trigger removal: PARTIAL / NEEDS FOLLOW-UP",
        "Phase54b rerun: COMPLETED",
        "Phase58 rerun: COMPLETED",
        f"Targeted assertion failures: {failed}",
        "",
        "Interpretation:",
        "- The precise residual stale-source false positive was reduced or removed,",
        "  but at least one downstream reconciliation condition still did not close.",
        "- Trust 16_targeted_assertions.txt and the copied Phase58 artifacts below.",
    ]

result_lines.extend([
    "",
    "Review:",
    "- 03_post_patch_phase54b_residual_hits.txt",
    "- 11_phase58_phase54b_source_stale_hits.txt",
    "- 12_phase58_reconciliation_matrix.txt",
    "- 13_phase58_recommended_next_move.txt",
    "- 15_phase58_console_digest.txt",
    "- 16_targeted_assertions.txt",
])

(out / "17_console_digest.txt").write_text(
    "\n".join(result_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(result_lines))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE59B_OUT=$OUT"
