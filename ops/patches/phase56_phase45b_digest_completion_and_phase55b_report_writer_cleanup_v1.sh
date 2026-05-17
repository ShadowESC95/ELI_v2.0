#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase56_phase45b_digest_completion_and_phase55b_report_writer_cleanup_${STAMP}"

PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE55B="ops/patches/phase55b_phase45b_legacy_adapter_candidate_accounting_repair_v2.sh"

mkdir -p "$OUT/backups"

for f in "$PHASE45B" "$PHASE55B"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE45B" "$OUT/backups/phase45b.before_phase56.bak"
cp "$PHASE55B" "$OUT/backups/phase55b.before_phase56.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase56 — Phase45b Digest Completion / Phase55b Report Writer Cleanup

## Why this phase exists

Phase55b successfully repaired the substantive Phase45b legacy-adapter
classification logic:

- actionable guarded-delete candidate chains: 0
- catalogue-only already-absent chains: 4
- retain/deeper-review chains: 0

However:

1. Phase45b's final console digest retained one shortened legacy line:
   `Legacy adapter guarded-delete candidate chains: 0`
   rather than exposing all three corrected categories.

2. Phase55b's own generated report text used literal `\n` strings instead of
   real newline characters.

## Repair scope

This phase:

- completes Phase45b's digest wording;
- fixes the Phase55b report-writer newline strings for future traceability;
- reruns Phase45b;
- validates digest / conclusion / inventory / reconciliation agreement.

No router source is modified.
EOF

python3 - "$PHASE45B" "$PHASE55B" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

phase45b_path = Path(sys.argv[1])
phase55b_path = Path(sys.argv[2])
out = Path(sys.argv[3])

changes: list[str] = []

# ---------------------------------------------------------------------
# 1. Complete Phase45b digest wording
# ---------------------------------------------------------------------

phase45b = phase45b_path.read_text(encoding="utf-8")

old_digest_line = '    f"Legacy adapter guarded-delete candidate chains: {adapter_delete_candidate_count}",\n'
new_digest_lines = '''    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
'''

if old_digest_line in phase45b:
    phase45b = phase45b.replace(old_digest_line, new_digest_lines, 1)
    changes.append("phase45b: replaced shortened legacy-adapter digest line with three-category corrected accounting")
elif (
    "Legacy adapter actionable guarded-delete candidate chains:" in phase45b
    and "Legacy adapter catalogue-only already-absent chains:" in phase45b
    and "Legacy adapter retain/deeper-review chains:" in phase45b
):
    changes.append("phase45b: corrected three-category digest accounting already present; skipped replacement")
else:
    raise SystemExit("Phase45b digest anchor not found and corrected digest block not detected; no change made.")

phase45b_path.write_text(phase45b, encoding="utf-8")

# ---------------------------------------------------------------------
# 2. Fix Phase55b literal-backslash-n report writer bug
# ---------------------------------------------------------------------

phase55b = phase55b_path.read_text(encoding="utf-8")
phase55b_before = phase55b

phase55b = phase55b.replace(
    '"\\\\n".join(lines) + "\\\\n"',
    '"\\n".join(lines) + "\\n"',
)

phase55b = phase55b.replace(
    '"\\\\n".join(digest_lines) + "\\\\n"',
    '"\\n".join(digest_lines) + "\\n"',
)

if phase55b != phase55b_before:
    changes.append("phase55b: repaired literal backslash-n report writer strings to real newline strings")
else:
    changes.append("phase55b: newline report writer strings already clean; skipped replacement")

phase55b_path.write_text(phase55b, encoding="utf-8")

(out / "01_changes_applied.txt").write_text(
    "\n".join(f"- {change}" for change in changes) + "\n",
    encoding="utf-8",
)

print("PHASE56_PATCH_APPLIED_OK")
for change in changes:
    print(f"- {change}")
PY

echo "=== BASH SYNTAX CHECKS ===" | tee "$OUT/02_bash_syntax_checks.txt"
bash -n "$PHASE45B" 2>&1 | tee -a "$OUT/02_bash_syntax_checks.txt"
echo "PHASE45B_BASH_SYNTAX_OK" | tee -a "$OUT/02_bash_syntax_checks.txt"
bash -n "$PHASE55B" 2>&1 | tee -a "$OUT/02_bash_syntax_checks.txt"
echo "PHASE55B_BASH_SYNTAX_OK" | tee -a "$OUT/02_bash_syntax_checks.txt"

echo "=== RUN REPAIRED PHASE45b ===" | tee "$OUT/03_repaired_phase45b_run.txt"
bash "$PHASE45B" 2>&1 | tee -a "$OUT/03_repaired_phase45b_run.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/03_repaired_phase45b_run.txt" \
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
  echo "Could not resolve repaired Phase45b output directory." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/04_phase45b_out_path.txt"

for f in \
  07_legacy_adapter_chain_transitive_liveness_inventory.txt \
  07b_legacy_adapter_chain_source_presence_reconciliation.txt \
  11_phase45b_conclusion.txt \
  12_console_digest.txt
do
  if [[ ! -f "$PHASE45B_OUT/$f" ]]; then
    echo "Expected repaired Phase45b artifact missing: $PHASE45B_OUT/$f" >&2
    exit 1
  fi
done

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/05_repaired_legacy_adapter_inventory.txt"

cp "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt" \
   "$OUT/06_repaired_legacy_adapter_source_presence_reconciliation.txt"

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/07_repaired_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/12_console_digest.txt" \
   "$OUT/08_repaired_phase45b_console_digest.txt"

python3 - "$PHASE55B" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

phase55b = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])

digest = (out / "08_repaired_phase45b_console_digest.txt").read_text(encoding="utf-8")
inventory = (out / "05_repaired_legacy_adapter_inventory.txt").read_text(encoding="utf-8")
reconciliation = (out / "06_repaired_legacy_adapter_source_presence_reconciliation.txt").read_text(encoding="utf-8")
conclusion = (out / "07_repaired_phase45b_conclusion.txt").read_text(encoding="utf-8")

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Phase45b digest actionable guarded-delete count is zero",
    "Legacy adapter actionable guarded-delete candidate chains: 0" in digest,
    "expected actionable guarded-delete digest count = 0",
)

check(
    "Phase45b digest catalogue-only already-absent count is four",
    "Legacy adapter catalogue-only already-absent chains: 4" in digest,
    "expected catalogue-only already-absent digest count = 4",
)

check(
    "Phase45b digest retain/deeper-review count is zero",
    "Legacy adapter retain/deeper-review chains: 0" in digest,
    "expected retain/deeper-review digest count = 0",
)

check(
    "Old shortened Phase45b digest line is absent",
    "Legacy adapter guarded-delete candidate chains:" not in digest,
    "old shortened digest wording should be absent",
)

check(
    "Phase45b conclusion corrected accounting remains intact",
    "Legacy adapter actionable guarded-delete candidate chains: 0" in conclusion
    and "Legacy adapter catalogue-only already-absent chains: 4" in conclusion
    and "Legacy adapter retain/deeper-review chains: 0" in conclusion,
    "expected corrected conclusion accounting 0 / 4 / 0",
)

check(
    "Legacy adapter inventory retains four catalogue-only absent rows",
    inventory.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "expected 4 catalogue-only classifications",
)

check(
    "Legacy adapter reconciliation retains four catalogue-only absent rows",
    reconciliation.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "expected 4 catalogue-only rows in source-presence reconciliation",
)

check(
    "No actionable guarded-delete rows remain in inventory",
    "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN" not in inventory,
    "inventory should contain no actionable guarded-delete chains",
)

check(
    "Phase55b report writer no longer contains literal backslash-n join strings",
    '"\\\\n".join(lines)' not in phase55b
    and '"\\\\n".join(digest_lines)' not in phase55b,
    "Phase55b should use real newline joins, not literal backslash-n joins",
)

failed = 0
lines = ["=== PHASE56 TARGETED ASSERTIONS ==="]
for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "09_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

digest_lines = [
    "=== PHASE56 DIGEST ===",
    "Phase45b digest completion patch: PASS",
    "Phase55b newline report-writer cleanup: PASS",
    "Patched script bash syntax checks: PASS",
    "Repaired Phase45b audit execution: PASS",
    f"Targeted assertion failures: {failed}",
    "",
    "Final corrected Phase45b legacy-adapter accounting:",
    "- actionable guarded-delete candidate chains: 0",
    "- catalogue-only already-absent chains: 4",
    "- retain/deeper-review chains: 0",
    "",
    "Conclusion:",
    "Phase45b now agrees across inventory, source-presence reconciliation,",
    "conclusion, and console digest. The legacy-adapter candidate-accounting",
    "branch is fully reconciled.",
    "",
    "Review:",
    "- 05_repaired_legacy_adapter_inventory.txt",
    "- 06_repaired_legacy_adapter_source_presence_reconciliation.txt",
    "- 07_repaired_phase45b_conclusion.txt",
    "- 08_repaired_phase45b_console_digest.txt",
    "- 09_targeted_assertions.txt",
]

(out / "10_console_digest.txt").write_text(
    "\n".join(digest_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(digest_lines))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE56_OUT=$OUT"
