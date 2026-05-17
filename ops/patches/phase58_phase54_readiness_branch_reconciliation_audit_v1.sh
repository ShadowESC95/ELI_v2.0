#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase58_phase54_readiness_branch_reconciliation_audit_${STAMP}"

PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE54="ops/patches/phase54_router_legacy_adapter_guarded_delete_readiness_audit_v1.sh"
PHASE54B="ops/patches/phase54b_router_legacy_adapter_inventory_parser_refinement_audit_v1.sh"

mkdir -p "$OUT"

for f in "$PHASE45B" "$PHASE54" "$PHASE54B"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase58 — Phase54 Readiness Branch Reconciliation Audit

## Purpose

Phase57 closed the Phase45b / Phase55b accounting-repair side branch.

Current corrected Phase45b truth is expected to be:

- actionable guarded-delete candidate chains: 0
- catalogue-only already-absent chains: 4
- retain/deeper-review chains: 0

Phase54 and Phase54b were authored before that correction and must now be
re-evaluated against the current truth.

This phase is audit-only:
- no router source mutation;
- no patch-script mutation;
- no deletion pass.

It determines whether Phase54 / Phase54b now require a dedicated
reconciliation-retirement patch.
EOF

echo "=== BASH SYNTAX CHECKS ===" | tee "$OUT/01_bash_syntax_checks.txt"
bash -n "$PHASE45B" 2>&1 | tee -a "$OUT/01_bash_syntax_checks.txt"
echo "PHASE45B_BASH_SYNTAX_OK" | tee -a "$OUT/01_bash_syntax_checks.txt"
bash -n "$PHASE54" 2>&1 | tee -a "$OUT/01_bash_syntax_checks.txt"
echo "PHASE54_BASH_SYNTAX_OK" | tee -a "$OUT/01_bash_syntax_checks.txt"
bash -n "$PHASE54B" 2>&1 | tee -a "$OUT/01_bash_syntax_checks.txt"
echo "PHASE54B_BASH_SYNTAX_OK" | tee -a "$OUT/01_bash_syntax_checks.txt"

echo "=== RUN FRESH CORRECTED PHASE45b ===" | tee "$OUT/02_phase45b_refresh.txt"
bash "$PHASE45B" 2>&1 | tee -a "$OUT/02_phase45b_refresh.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/02_phase45b_refresh.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  PHASE45B_OUT="$(
    ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve fresh Phase45b output directory." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/03_phase45b_out_path.txt"

for f in \
  12_console_digest.txt \
  11_phase45b_conclusion.txt \
  07_legacy_adapter_chain_transitive_liveness_inventory.txt \
  07b_legacy_adapter_chain_source_presence_reconciliation.txt
do
  if [[ ! -f "$PHASE45B_OUT/$f" ]]; then
    echo "Expected Phase45b artifact missing: $PHASE45B_OUT/$f" >&2
    exit 1
  fi
done

cp "$PHASE45B_OUT/12_console_digest.txt" \
   "$OUT/04_phase45b_console_digest.txt"

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/05_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/06_phase45b_legacy_inventory.txt"

cp "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt" \
   "$OUT/07_phase45b_source_presence_reconciliation.txt"

{
  echo "=== PHASE54 SOURCE STALE-READINESS HIT SCAN ==="
  grep -nE \
    'readiness-positive|dedicated guarded-delete retirement patch|Phase55 router legacy adapter guarded-delete retirement patch|Legacy adapter guarded-delete candidate chains reported by Phase45b|guarded-delete candidate chains reported by Phase45b' \
    "$PHASE54" || true
} > "$OUT/08_phase54_source_stale_hits.txt"

{
  echo "=== PHASE54b SOURCE STALE-READINESS / PARSER HIT SCAN ==="

  # Phase59c:
  # Only emit genuinely obsolete parser/deletion-readiness guidance.
  # Do NOT classify the current retired-accounting truth line
  #   "Legacy adapter actionable guarded-delete candidate chains: 0"
  # as stale debt.
  python3 - "$PHASE54B" <<'PY_PHASE59C_SCAN'
from __future__ import annotations

from pathlib import Path
import re
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()

stale_patterns = [
    re.compile(r"parser refinement", re.I),
    re.compile(r"parser-refinement", re.I),
    re.compile(r"required before deletion readiness can be stated", re.I),
    re.compile(r"PARSER_VISIBILITY_PASS"),
    re.compile(r"No candidate symbols could be extracted", re.I),
    re.compile(r"adapter guarded-delete readiness parser failed to extract any candidate symbols", re.I),
    re.compile(r"later guarded-delete retirement patch", re.I),
    re.compile(r"Phase55 guarded-delete retirement", re.I),
    re.compile(r"authorises preparation of Phase55 guarded-delete retirement", re.I),
    re.compile(r"the liveness level\. Phase55 guarded-delete retirement can be prepared next", re.I),
    re.compile(r"Phase45b reports legacy adapter guarded-delete candidate chains", re.I),
    re.compile(r"Legacy adapter guarded-delete candidate chains:\s*[1-9]\d*", re.I),
    re.compile(r"Legacy adapter candidate chains are readiness-positive", re.I),
]

benign_accounting = "Legacy adapter actionable guarded-delete candidate chains: 0"

for lineno, line in enumerate(src, start=1):
    if benign_accounting in line:
        continue
    if any(rx.search(line) for rx in stale_patterns):
        print(f"{lineno}:{line}")
PY_PHASE59C_SCAN
} > "$OUT/09_phase54b_source_stale_hits.txt"

echo "=== RERUN PHASE54 ===" | tee "$OUT/10_phase54_rerun.txt"
set +e
bash "$PHASE54" 2>&1 | tee -a "$OUT/10_phase54_rerun.txt"
PHASE54_STATUS="${PIPESTATUS[0]}"
set -e
echo "PHASE54_EXIT_STATUS=$PHASE54_STATUS" | tee -a "$OUT/10_phase54_rerun.txt"

echo "=== RERUN PHASE54b ===" | tee "$OUT/11_phase54b_rerun.txt"
set +e
bash "$PHASE54B" 2>&1 | tee -a "$OUT/11_phase54b_rerun.txt"
PHASE54B_STATUS="${PIPESTATUS[0]}"
set -e
echo "PHASE54B_EXIT_STATUS=$PHASE54B_STATUS" | tee -a "$OUT/11_phase54b_rerun.txt"

python3 - "$OUT" "$PHASE54_STATUS" "$PHASE54B_STATUS" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

out = Path(sys.argv[1])
phase54_status = int(sys.argv[2])
phase54b_status = int(sys.argv[3])

phase45b_digest = (out / "04_phase45b_console_digest.txt").read_text(encoding="utf-8")
phase45b_conclusion = (out / "05_phase45b_conclusion.txt").read_text(encoding="utf-8")
phase45b_inventory = (out / "06_phase45b_legacy_inventory.txt").read_text(encoding="utf-8")
phase45b_recon = (out / "07_phase45b_source_presence_reconciliation.txt").read_text(encoding="utf-8")

phase54_source_hits = (out / "08_phase54_source_stale_hits.txt").read_text(encoding="utf-8")
phase54b_source_hits = (out / "09_phase54b_source_stale_hits.txt").read_text(encoding="utf-8")
phase54_run = (out / "10_phase54_rerun.txt").read_text(encoding="utf-8")
phase54b_run = (out / "11_phase54b_rerun.txt").read_text(encoding="utf-8")

def has_nonheader_hits(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) > 1

phase45b_truth_ok = all(
    needle in phase45b_digest
    for needle in (
        "Legacy adapter actionable guarded-delete candidate chains: 0",
        "Legacy adapter catalogue-only already-absent chains: 4",
        "Legacy adapter retain/deeper-review chains: 0",
    )
)

phase45b_conclusion_ok = all(
    needle in phase45b_conclusion
    for needle in (
        "Legacy adapter actionable guarded-delete candidate chains: 0",
        "Legacy adapter catalogue-only already-absent chains: 4",
        "Legacy adapter retain/deeper-review chains: 0",
    )
)

inventory_catalogue_only_count = phase45b_inventory.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT")
recon_catalogue_only_count = phase45b_recon.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT")

phase54_source_stale = has_nonheader_hits(phase54_source_hits)
phase54b_source_stale = has_nonheader_hits(phase54b_source_hits)

phase54_runtime_stale = any(
    needle in phase54_run
    for needle in (
        "readiness-positive for a dedicated",
        "Phase55 router legacy adapter guarded-delete retirement patch",
        "Legacy adapter guarded-delete candidate chains reported by Phase45b: 4",
    )
)

phase54b_runtime_stale = any(
    needle in phase54b_run
    for needle in (
        "PARSER_VISIBILITY_PASS=False",
        "No candidate symbols could be extracted",
        "parser refinement is required",
    )
)

lines = [
    "=== PHASE58 RECONCILIATION MATRIX ===",
    f"phase45b_truth_ok={phase45b_truth_ok}",
    f"phase45b_conclusion_ok={phase45b_conclusion_ok}",
    f"phase45b_inventory_catalogue_only_count={inventory_catalogue_only_count}",
    f"phase45b_reconciliation_catalogue_only_count={recon_catalogue_only_count}",
    f"phase54_exit_status={phase54_status}",
    f"phase54b_exit_status={phase54b_status}",
    f"phase54_source_stale_hits_present={phase54_source_stale}",
    f"phase54b_source_stale_hits_present={phase54b_source_stale}",
    f"phase54_runtime_stale_guidance_present={phase54_runtime_stale}",
    f"phase54b_runtime_stale_guidance_present={phase54b_runtime_stale}",
]

(out / "12_reconciliation_matrix.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Fresh Phase45b digest preserves corrected 0 / 4 / 0 accounting",
    phase45b_truth_ok,
    "expected corrected accounting lines in Phase45b digest",
)
check(
    "Fresh Phase45b conclusion preserves corrected 0 / 4 / 0 accounting",
    phase45b_conclusion_ok,
    "expected corrected accounting lines in Phase45b conclusion",
)
check(
    "Fresh Phase45b legacy inventory contains four catalogue-only already-absent rows",
    inventory_catalogue_only_count == 4,
    f"observed={inventory_catalogue_only_count}",
)
check(
    "Fresh Phase45b source-presence reconciliation contains four catalogue-only already-absent rows",
    recon_catalogue_only_count == 4,
    f"observed={recon_catalogue_only_count}",
)
check(
    "Phase54 rerun was captured",
    bool(phase54_run.strip()),
    "Phase54 rerun log is empty",
)
check(
    "Phase54b rerun was captured",
    bool(phase54b_run.strip()),
    "Phase54b rerun log is empty",
)

failed = 0
assertion_lines = ["=== PHASE58 TARGETED ASSERTIONS ==="]

for label, ok, detail in checks:
    if ok:
        assertion_lines.append(f"PASS: {label}")
    else:
        failed += 1
        assertion_lines.append(f"FAIL: {label} — {detail}")

assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "14_targeted_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

needs_phase59 = any(
    (
        phase54_source_stale,
        phase54b_source_stale,
        phase54_runtime_stale,
        phase54b_runtime_stale,
    )
)

if needs_phase59:
    recommendation = [
        "=== PHASE58 RECOMMENDED NEXT MOVE ===",
        "",
        "Phase54 / Phase54b are now stale relative to the repaired Phase45b accounting.",
        "",
        "Current truth:",
        "- actionable guarded-delete adapter chains: 0",
        "- catalogue-only already-absent adapter chains: 4",
        "- retain/deeper-review chains: 0",
        "",
        "Recommended next phase:",
        "- Phase59 should reconcile and retire the obsolete Phase54 / Phase54b",
        "  guarded-delete readiness branch so it no longer suggests a deletion pass",
        "  or parser-refinement work that Phase55b/56/57 made obsolete.",
    ]
else:
    recommendation = [
        "=== PHASE58 RECOMMENDED NEXT MOVE ===",
        "",
        "Phase54 / Phase54b no longer emit stale readiness guidance.",
        "No reconciliation patch is required for that branch.",
        "",
        "Recommended next phase:",
        "- proceed to a final router consolidation closure checkpoint.",
    ]

(out / "13_recommended_next_move.txt").write_text(
    "\n".join(recommendation) + "\n",
    encoding="utf-8",
)

digest = [
    "=== PHASE58 DIGEST ===",
    "Fresh corrected Phase45b refresh: PASS" if phase45b_truth_ok else "Fresh corrected Phase45b refresh: FAIL",
    f"Phase54 rerun exit status: {phase54_status}",
    f"Phase54b rerun exit status: {phase54b_status}",
    f"Phase54 stale source/runtime indicators present: {phase54_source_stale or phase54_runtime_stale}",
    f"Phase54b stale source/runtime indicators present: {phase54b_source_stale or phase54b_runtime_stale}",
    f"Targeted assertion failures: {failed}",
    "",
    "Interpretation:",
    "- Phase57 closed the Phase45b / Phase55b accounting-repair side branch.",
    "- Phase58 checks whether Phase54 / Phase54b still describe the old, now-obsolete guarded-delete branch.",
    "- No source files were modified.",
    "",
    "Review:",
    "- 04_phase45b_console_digest.txt",
    "- 05_phase45b_conclusion.txt",
    "- 08_phase54_source_stale_hits.txt",
    "- 09_phase54b_source_stale_hits.txt",
    "- 10_phase54_rerun.txt",
    "- 11_phase54b_rerun.txt",
    "- 12_reconciliation_matrix.txt",
    "- 13_recommended_next_move.txt",
    "- 14_targeted_assertions.txt",
]

(out / "15_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE58_OUT=$OUT"
