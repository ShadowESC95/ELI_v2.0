#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase54_router_legacy_adapter_guarded_delete_readiness_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"

mkdir -p "$OUT"

for f in "$ROUTER" "$PHASE45B"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase54 — Retired Legacy-Adapter Readiness Branch Reconciliation

## Current purpose

This script no longer prepares any deletion patch.

The earlier readiness branch was retired after Phase45b accounting was repaired.
The authoritative Phase45b state is expected to be:

- actionable legacy-adapter deletion candidates: 0
- catalogue-only already-absent chains: 4
- retain / deeper-review chains: 0

Phase54 now verifies that state and records that no follow-on deletion phase
is authorised or required.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

echo "=== PHASE45b REFRESH ===" | tee "$OUT/01_phase45b_refresh.txt"
bash "$PHASE45B" 2>&1 | tee -a "$OUT/01_phase45b_refresh.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/01_phase45b_refresh.txt" \
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

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/02_phase45b_out_path.txt"

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
   "$OUT/03_phase45b_console_digest.txt"

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/04_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/05_phase45b_legacy_inventory.txt"

cp "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt" \
   "$OUT/06_phase45b_source_presence_reconciliation.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

out = Path(sys.argv[1])

digest = (out / "03_phase45b_console_digest.txt").read_text(encoding="utf-8")
conclusion = (out / "04_phase45b_conclusion.txt").read_text(encoding="utf-8")
inventory = (out / "05_phase45b_legacy_inventory.txt").read_text(encoding="utf-8")
recon = (out / "06_phase45b_source_presence_reconciliation.txt").read_text(encoding="utf-8")

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
    "=== PHASE54 RETIRED-BRANCH RECONCILIATION MATRIX ===",
    f"phase45b_digest_accounting_ok={digest_ok}",
    f"phase45b_conclusion_accounting_ok={conclusion_ok}",
    f"legacy_inventory_catalogue_only_count={inventory_catalogue_only}",
    f"source_presence_reconciliation_catalogue_only_count={recon_catalogue_only}",
    "branch_status=RETIRED",
    "follow_on_deletion_phase_authorised=False",
]
(out / "07_reconciliation_matrix.txt").write_text(
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
lines = ["=== PHASE54 RETIRED-BRANCH TARGETED ASSERTIONS ==="]
for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "08_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

recommended = [
    "=== PHASE54 RETIRED-BRANCH RECOMMENDED NEXT MOVE ===",
    "",
    "No deletion-readiness phase remains here.",
    "",
    "The previously proposed follow-on deletion branch is retired because",
    "Phase45b now proves there are:",
    "- 0 actionable live deletion candidates;",
    "- 4 catalogue-only rows whose source was already absent;",
    "- 0 retain/deeper-review chains.",
    "",
    "Proceed to closure/housekeeping work only.",
]
(out / "09_recommended_next_move.txt").write_text(
    "\n".join(recommended) + "\n",
    encoding="utf-8",
)

console = [
    "=== PHASE54 RETIRED-BRANCH DIGEST ===",
    "Router compile: PASS",
    "Phase45b refresh: PASS",
    "Current Phase45b accounting: 0 actionable / 4 catalogue-only already absent / 0 retain",
    f"Targeted assertion failures: {failed}",
    "",
    "Conclusion:",
    "The old Phase54 deletion-readiness branch is retired.",
    "No actionable legacy-adapter source debt remains for this branch.",
    "No follow-on deletion patch is authorised or required.",
    "",
    "Review:",
    "- 03_phase45b_console_digest.txt",
    "- 04_phase45b_conclusion.txt",
    "- 07_reconciliation_matrix.txt",
    "- 08_targeted_assertions.txt",
    "- 09_recommended_next_move.txt",
]
(out / "10_console_digest.txt").write_text(
    "\n".join(console) + "\n",
    encoding="utf-8",
)

print("\n".join(console))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE54_OUT=$OUT"
