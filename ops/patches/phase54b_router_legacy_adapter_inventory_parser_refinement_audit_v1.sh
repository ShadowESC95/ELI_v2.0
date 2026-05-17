#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase54b_router_legacy_adapter_inventory_parser_refinement_audit_${STAMP}"

PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"

mkdir -p "$OUT"

if [[ ! -f "$PHASE45B" ]]; then
  echo "Required file missing: $PHASE45B" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase54b — Retired Legacy-Adapter Parser Branch Reconciliation

## Current purpose

This script no longer attempts candidate-span extraction or parser-branch follow-up.

That work became obsolete once Phase45b accounting was corrected and showed:

- actionable legacy-adapter deletion candidates: 0
- catalogue-only already-absent chains: 4
- retain / deeper-review chains: 0

Phase54b now verifies that corrected state and records that the older parser
branch is retired.
EOF

echo "=== PHASE45b REFRESH ===" | tee "$OUT/00_phase45b_refresh.txt"
bash "$PHASE45B" 2>&1 | tee -a "$OUT/00_phase45b_refresh.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/00_phase45b_refresh.txt" \
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

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/01_phase45b_out_path.txt"

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
   "$OUT/02_phase45b_console_digest.txt"

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/03_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/04_phase45b_legacy_inventory.txt"

cp "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt" \
   "$OUT/05_phase45b_source_presence_reconciliation.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

out = Path(sys.argv[1])

digest = (out / "02_phase45b_console_digest.txt").read_text(encoding="utf-8")
conclusion = (out / "03_phase45b_conclusion.txt").read_text(encoding="utf-8")
inventory = (out / "04_phase45b_legacy_inventory.txt").read_text(encoding="utf-8")
recon = (out / "05_phase45b_source_presence_reconciliation.txt").read_text(encoding="utf-8")

truth_lines = (
    "Legacy adapter actionable guarded-delete candidate chains: 0",
    "Legacy adapter catalogue-only already-absent chains: 4",
    "Legacy adapter retain/deeper-review chains: 0",
)

digest_ok = all(line in digest for line in truth_lines)
conclusion_ok = all(line in conclusion for line in truth_lines)
inventory_catalogue_only = inventory.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT")
recon_catalogue_only = recon.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT")

matrix = [
    "=== PHASE54b RETIRED-PARSER-BRANCH MATRIX ===",
    f"phase45b_digest_accounting_ok={digest_ok}",
    f"phase45b_conclusion_accounting_ok={conclusion_ok}",
    f"legacy_inventory_catalogue_only_count={inventory_catalogue_only}",
    f"source_presence_reconciliation_catalogue_only_count={recon_catalogue_only}",
    "candidate_parser_branch_status=RETIRED",
    "candidate_span_extraction_required=False",
    "follow_on_parser_work_required=False",
]
(out / "06_reconciliation_matrix.txt").write_text(
    "\n".join(matrix) + "\n",
    encoding="utf-8",
)

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Phase45b digest preserves corrected 0 / 4 / 0 accounting",
    digest_ok,
    "expected corrected accounting lines in digest",
)
check(
    "Phase45b conclusion preserves corrected 0 / 4 / 0 accounting",
    conclusion_ok,
    "expected corrected accounting lines in conclusion",
)
check(
    "Legacy inventory contains four catalogue-only already-absent rows",
    inventory_catalogue_only == 4,
    f"observed={inventory_catalogue_only}",
)
check(
    "Source-presence reconciliation contains four catalogue-only already-absent rows",
    recon_catalogue_only == 4,
    f"observed={recon_catalogue_only}",
)

failed = 0
lines = ["=== PHASE54b RETIRED-PARSER-BRANCH TARGETED ASSERTIONS ==="]
for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "07_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

recommended = [
    "=== PHASE54b RETIRED-PARSER-BRANCH RECOMMENDED NEXT MOVE ===",
    "",
    "No parser-branch follow-up branch remains.",
    "",
    "The earlier inventory-parser work was attached to a now-retired deletion",
    "readiness workflow. Corrected Phase45b accounting shows no actionable",
    "live source debt for that branch.",
    "",
    "Proceed to closure/housekeeping work only.",
]
(out / "08_recommended_next_move.txt").write_text(
    "\n".join(recommended) + "\n",
    encoding="utf-8",
)

console = [
    "=== PHASE54b RETIRED-PARSER-BRANCH DIGEST ===",
    "Phase45b refresh: PASS",
    "Current Phase45b accounting: 0 actionable / 4 catalogue-only already absent / 0 retain",
    f"Targeted assertion failures: {failed}",
    "",
    "Conclusion:",
    "The former candidate-parser branch is retired.",
    "No follow-on parser work remains for this path.",
    "No deletion-readiness phase is authorised or required.",
    "",
    "Review:",
    "- 02_phase45b_console_digest.txt",
    "- 03_phase45b_conclusion.txt",
    "- 06_reconciliation_matrix.txt",
    "- 07_targeted_assertions.txt",
    "- 08_recommended_next_move.txt",
]
(out / "09_console_digest.txt").write_text(
    "\n".join(console) + "\n",
    encoding="utf-8",
)

print("\n".join(console))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE54B_OUT=$OUT"
