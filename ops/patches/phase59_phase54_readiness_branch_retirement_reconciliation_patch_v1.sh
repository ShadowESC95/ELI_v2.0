#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase59_phase54_readiness_branch_retirement_reconciliation_patch_${STAMP}"

PHASE54="ops/patches/phase54_router_legacy_adapter_guarded_delete_readiness_audit_v1.sh"
PHASE54B="ops/patches/phase54b_router_legacy_adapter_inventory_parser_refinement_audit_v1.sh"
PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE58="ops/patches/phase58_phase54_readiness_branch_reconciliation_audit_v1.sh"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT/backups"

for f in "$PHASE54" "$PHASE54B" "$PHASE45B" "$PHASE58" "$ROUTER"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE54"  "$OUT/backups/$(basename "$PHASE54").before_phase59.bak"
cp "$PHASE54B" "$OUT/backups/$(basename "$PHASE54B").before_phase59.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase59 — Phase54 / Phase54b Readiness Branch Retirement Reconciliation Patch

## Why this patch exists

Phase58 proved that the Phase54 / Phase54b workflow branch is stale relative
to the repaired Phase45b accounting.

Current authoritative accounting is:

- actionable legacy-adapter deletion candidates: 0
- catalogue-only already-absent chains: 4
- retain / deeper-review chains: 0

Therefore:

- Phase54 must no longer recommend a deletion patch.
- Phase54b must no longer recommend parser-refinement work for a candidate
  branch that is already accounting-null.
- Both scripts should remain runnable, but only as retired-branch reconciliation
  auditors that verify the corrected Phase45b truth.

This patch modifies ops/audit scripts only.
It does not modify router source.
EOF

{
  echo "=== PRE-PATCH STALE STRING INVENTORY: PHASE54 ==="
  grep -nE \
    'readiness-positive|dedicated guarded-delete retirement patch|Phase55 router legacy adapter guarded-delete retirement patch|Legacy adapter guarded-delete candidate chains reported by Phase45b|guarded-delete candidate chains reported by Phase45b' \
    "$PHASE54" || true

  echo
  echo "=== PRE-PATCH STALE STRING INVENTORY: PHASE54b ==="
  grep -nE \
    'parser refinement|required before deletion readiness can be stated|PARSER_VISIBILITY_PASS|No candidate symbols could be extracted|guarded-delete|Phase55 guarded-delete retirement' \
    "$PHASE54B" || true
} > "$OUT/01_pre_patch_stale_string_inventory.txt"

# -------------------------------------------------------------------
# Rewrite Phase54 into a retired-branch reconciliation auditor
# -------------------------------------------------------------------

cat > "$PHASE54" <<'PH54'
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
PH54

chmod +x "$PHASE54"

# -------------------------------------------------------------------
# Rewrite Phase54b into a retired parser-branch reconciliation auditor
# -------------------------------------------------------------------

cat > "$PHASE54B" <<'PH54B'
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

This script no longer attempts candidate-span extraction or parser refinement.

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
    "No parser-refinement branch remains.",
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
PH54B

chmod +x "$PHASE54B"

{
  echo "=== POST-PATCH STALE STRING INVENTORY: PHASE54 ==="
  grep -nE \
    'readiness-positive|dedicated guarded-delete retirement patch|Phase55 router legacy adapter guarded-delete retirement patch|Legacy adapter guarded-delete candidate chains reported by Phase45b|guarded-delete candidate chains reported by Phase45b' \
    "$PHASE54" || true

  echo
  echo "=== POST-PATCH STALE STRING INVENTORY: PHASE54b ==="
  grep -nE \
    'parser refinement|required before deletion readiness can be stated|PARSER_VISIBILITY_PASS|No candidate symbols could be extracted|guarded-delete|Phase55 guarded-delete retirement' \
    "$PHASE54B" || true
} > "$OUT/02_post_patch_stale_string_inventory.txt"

echo "=== BASH SYNTAX CHECKS ===" | tee "$OUT/03_bash_syntax_checks.txt"
bash -n "$PHASE54" 2>&1 | tee -a "$OUT/03_bash_syntax_checks.txt"
echo "PHASE54_BASH_SYNTAX_OK" | tee -a "$OUT/03_bash_syntax_checks.txt"
bash -n "$PHASE54B" 2>&1 | tee -a "$OUT/03_bash_syntax_checks.txt"
echo "PHASE54B_BASH_SYNTAX_OK" | tee -a "$OUT/03_bash_syntax_checks.txt"

echo "=== RERUN REWRITTEN PHASE54 ===" | tee "$OUT/04_phase54_rerun.txt"
bash "$PHASE54" 2>&1 | tee -a "$OUT/04_phase54_rerun.txt"

PHASE54_OUT="$(
  grep -oE 'PHASE54_OUT=.*' "$OUT/04_phase54_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE54_OUT:-}" || ! -d "$PHASE54_OUT" ]]; then
  PHASE54_OUT="$(
    ls -td ops/reports/phase54_router_legacy_adapter_guarded_delete_readiness_audit_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE54_OUT:-}" || ! -d "$PHASE54_OUT" ]]; then
  echo "Could not resolve rewritten Phase54 output directory." >&2
  exit 1
fi

echo "PHASE54_OUT=$PHASE54_OUT" | tee "$OUT/05_phase54_out_path.txt"

echo "=== RERUN REWRITTEN PHASE54b ===" | tee "$OUT/06_phase54b_rerun.txt"
bash "$PHASE54B" 2>&1 | tee -a "$OUT/06_phase54b_rerun.txt"

PHASE54B_OUT="$(
  grep -oE 'PHASE54B_OUT=.*' "$OUT/06_phase54b_rerun.txt" \
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
  echo "Could not resolve rewritten Phase54b output directory." >&2
  exit 1
fi

echo "PHASE54B_OUT=$PHASE54B_OUT" | tee "$OUT/07_phase54b_out_path.txt"

for f in \
  "$PHASE54_OUT/10_console_digest.txt" \
  "$PHASE54_OUT/08_targeted_assertions.txt" \
  "$PHASE54B_OUT/09_console_digest.txt" \
  "$PHASE54B_OUT/07_targeted_assertions.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected verification artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE54_OUT/10_console_digest.txt" \
   "$OUT/08_phase54_console_digest.txt"

cp "$PHASE54_OUT/08_targeted_assertions.txt" \
   "$OUT/09_phase54_targeted_assertions.txt"

cp "$PHASE54B_OUT/09_console_digest.txt" \
   "$OUT/10_phase54b_console_digest.txt"

cp "$PHASE54B_OUT/07_targeted_assertions.txt" \
   "$OUT/11_phase54b_targeted_assertions.txt"

echo "=== RERUN PHASE58 RECONCILIATION AUDIT ===" | tee "$OUT/12_phase58_rerun.txt"
bash "$PHASE58" 2>&1 | tee -a "$OUT/12_phase58_rerun.txt"

PHASE58_OUT="$(
  grep -oE 'PHASE58_OUT=.*' "$OUT/12_phase58_rerun.txt" \
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
  echo "Could not resolve Phase58 rerun output directory." >&2
  exit 1
fi

echo "PHASE58_OUT=$PHASE58_OUT" | tee "$OUT/13_phase58_out_path.txt"

for f in \
  "$PHASE58_OUT/12_reconciliation_matrix.txt" \
  "$PHASE58_OUT/13_recommended_next_move.txt" \
  "$PHASE58_OUT/14_targeted_assertions.txt" \
  "$PHASE58_OUT/15_console_digest.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected Phase58 rerun artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE58_OUT/12_reconciliation_matrix.txt" \
   "$OUT/14_phase58_reconciliation_matrix.txt"

cp "$PHASE58_OUT/13_recommended_next_move.txt" \
   "$OUT/15_phase58_recommended_next_move.txt"

cp "$PHASE58_OUT/14_targeted_assertions.txt" \
   "$OUT/16_phase58_targeted_assertions.txt"

cp "$PHASE58_OUT/15_console_digest.txt" \
   "$OUT/17_phase58_console_digest.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

out = Path(sys.argv[1])

pre_hits = (out / "01_pre_patch_stale_string_inventory.txt").read_text(encoding="utf-8")
post_hits = (out / "02_post_patch_stale_string_inventory.txt").read_text(encoding="utf-8")

phase54_digest = (out / "08_phase54_console_digest.txt").read_text(encoding="utf-8")
phase54_assert = (out / "09_phase54_targeted_assertions.txt").read_text(encoding="utf-8")
phase54b_digest = (out / "10_phase54b_console_digest.txt").read_text(encoding="utf-8")
phase54b_assert = (out / "11_phase54b_targeted_assertions.txt").read_text(encoding="utf-8")

phase58_matrix = (out / "14_phase58_reconciliation_matrix.txt").read_text(encoding="utf-8")
phase58_recommended = (out / "15_phase58_recommended_next_move.txt").read_text(encoding="utf-8")
phase58_assert = (out / "16_phase58_targeted_assertions.txt").read_text(encoding="utf-8")
phase58_digest = (out / "17_phase58_console_digest.txt").read_text(encoding="utf-8")

def has_nonheader_hits(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) > 2

post_phase54_section, post_phase54b_section = post_hits.split(
    "=== POST-PATCH STALE STRING INVENTORY: PHASE54b ===",
    1,
)

phase54_post_stale = has_nonheader_hits(post_phase54_section)
phase54b_post_stale = bool(
    [line for line in post_phase54b_section.splitlines() if line.strip()]
)

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Pre-patch stale-hit inventory captured evidence",
    bool(pre_hits.strip()),
    "pre-patch inventory artifact empty",
)
check(
    "Phase54 stale retirement-guidance phrases removed",
    not phase54_post_stale,
    "post-patch Phase54 stale string scan still has hits",
)
check(
    "Phase54b stale parser/deletion-guidance phrases removed",
    not phase54b_post_stale,
    "post-patch Phase54b stale string scan still has hits",
)
check(
    "Rewritten Phase54 targeted assertions are zero",
    "TARGETED_ASSERTION_FAILURES=0" in phase54_assert,
    "Phase54 targeted assertions not zero",
)
check(
    "Rewritten Phase54b targeted assertions are zero",
    "TARGETED_ASSERTION_FAILURES=0" in phase54b_assert,
    "Phase54b targeted assertions not zero",
)
check(
    "Rewritten Phase54 digest states retired branch",
    "The old Phase54 deletion-readiness branch is retired." in phase54_digest,
    "Phase54 retired-branch digest wording missing",
)
check(
    "Rewritten Phase54b digest states retired parser branch",
    "The former candidate-parser branch is retired." in phase54b_digest,
    "Phase54b retired-parser digest wording missing",
)
check(
    "Phase58 rerun no longer sees stale Phase54 source/runtime indicators",
    "phase54_source_stale_hits_present=False" in phase58_matrix
    and "phase54_runtime_stale_guidance_present=False" in phase58_matrix,
    "Phase58 still sees stale Phase54 indicators",
)
check(
    "Phase58 rerun no longer sees stale Phase54b source/runtime indicators",
    "phase54b_source_stale_hits_present=False" in phase58_matrix
    and "phase54b_runtime_stale_guidance_present=False" in phase58_matrix,
    "Phase58 still sees stale Phase54b indicators",
)
check(
    "Phase58 rerun targeted assertions remain zero",
    "TARGETED_ASSERTION_FAILURES=0" in phase58_assert,
    "Phase58 targeted assertions not zero",
)
check(
    "Phase58 recommendation now permits closure work only",
    "proceed to a final router consolidation closure checkpoint" in phase58_recommended.lower(),
    "Phase58 did not transition to closure recommendation",
)
check(
    "Phase58 digest reports no stale Phase54 indicators",
    "Phase54 stale source/runtime indicators present: False" in phase58_digest
    and "Phase54b stale source/runtime indicators present: False" in phase58_digest,
    "Phase58 console digest still reports stale indicators",
)

failed = 0
lines = ["=== PHASE59 TARGETED ASSERTIONS ==="]

for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "18_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

console = [
    "=== PHASE59 DIGEST ===",
    "Phase54 retired-branch rewrite: PASS",
    "Phase54b retired-parser rewrite: PASS",
    "Patched script syntax checks: PASS",
    "Rewritten Phase54 rerun: PASS",
    "Rewritten Phase54b rerun: PASS",
    "Phase58 reconciliation rerun: PASS",
    f"Targeted assertion failures: {failed}",
    "",
    "Final result:",
    "- The obsolete Phase54 deletion-readiness branch is retired.",
    "- The obsolete Phase54b parser-refinement branch is retired.",
    "- Phase58 now reports no stale Phase54 / Phase54b source or runtime indicators.",
    "- The corrected Phase45b truth remains 0 / 4 / 0.",
    "- This path is now ready for a final router consolidation closure checkpoint.",
    "",
    "Review:",
    "- 08_phase54_console_digest.txt",
    "- 10_phase54b_console_digest.txt",
    "- 14_phase58_reconciliation_matrix.txt",
    "- 15_phase58_recommended_next_move.txt",
    "- 17_phase58_console_digest.txt",
    "- 18_targeted_assertions.txt",
]

(out / "19_console_digest.txt").write_text(
    "\n".join(console) + "\n",
    encoding="utf-8",
)

print("\n".join(console))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE59_OUT=$OUT"
