#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase57_phase55b_report_writer_literal_newline_residue_cleanup_${STAMP}"

PHASE55B="ops/patches/phase55b_phase45b_legacy_adapter_candidate_accounting_repair_v2.sh"
PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"

mkdir -p "$OUT/backups"

for f in "$PHASE55B" "$PHASE45B"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE55B" "$OUT/backups/phase55b.before_phase57.bak"
cp "$PHASE45B" "$OUT/backups/phase45b.before_phase57.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase57 — Phase55b Report Writer Literal-Newline Residue Cleanup

## Current state

Phase56 proved the substantive Phase45b legacy-adapter accounting is now correct:

- actionable guarded-delete candidate chains: 0
- catalogue-only already-absent chains: 4
- retain/deeper-review chains: 0

The only remaining failure was a Phase56 self-check that found residual
literal-backslash newline join syntax still present inside the Phase55b patch
script source.

## Repair scope

This phase:

1. inventories residual bad Phase55b report-writer join forms;
2. rewrites all remaining literal `"\\n".join(...)` / `'\\n'.join(...)`
   report-writer residues into real newline separators;
3. verifies the residues are absent;
4. reruns Phase55b;
5. confirms Phase55b now reports zero targeted assertion failures.

No router source is modified.
EOF

python3 - "$PHASE55B" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

phase55b_path = Path(sys.argv[1])
out = Path(sys.argv[2])

text = phase55b_path.read_text(encoding="utf-8")

bad_patterns = [
    ('"\\\\n".join(lines)', '"\\n".join(lines)'),
    ('"\\\\n".join(digest_lines)', '"\\n".join(digest_lines)'),
    ("'\\\\n'.join(lines)", "'\\n'.join(lines)"),
    ("'\\\\n'.join(digest_lines)", "'\\n'.join(digest_lines)"),
]

pre_lines = ["=== PHASE57 PRE-PATCH BAD-PATTERN INVENTORY ==="]
total_before = 0
for bad, good in bad_patterns:
    count = text.count(bad)
    total_before += count
    pre_lines.append(f"{bad!r}: {count}")

(out / "01_pre_patch_bad_pattern_inventory.txt").write_text(
    "\n".join(pre_lines) + "\n",
    encoding="utf-8",
)

changes: list[str] = []
patched = text

for bad, good in bad_patterns:
    count = patched.count(bad)
    if count:
        patched = patched.replace(bad, good)
        changes.append(f"replaced {count} occurrence(s) of {bad!r}")

if patched == text:
    changes.append("no bad literal-newline join forms required rewriting")

phase55b_path.write_text(patched, encoding="utf-8")

post = phase55b_path.read_text(encoding="utf-8")

post_lines = ["=== PHASE57 POST-PATCH BAD-PATTERN INVENTORY ==="]
total_after = 0
for bad, good in bad_patterns:
    count = post.count(bad)
    total_after += count
    post_lines.append(f"{bad!r}: {count}")

(out / "02_post_patch_bad_pattern_inventory.txt").write_text(
    "\n".join(post_lines) + "\n",
    encoding="utf-8",
)

(out / "03_changes_applied.txt").write_text(
    "\n".join(f"- {line}" for line in changes) + "\n",
    encoding="utf-8",
)

print("PHASE57_LITERAL_NEWLINE_RESIDUE_PATCH_OK")
print(f"BAD_PATTERN_OCCURRENCES_BEFORE={total_before}")
print(f"BAD_PATTERN_OCCURRENCES_AFTER={total_after}")
for line in changes:
    print(f"- {line}")

if total_after != 0:
    raise SystemExit("Residual literal-newline join forms remain after Phase57 patch.")
PY

echo "=== BASH SYNTAX CHECKS ===" | tee "$OUT/04_bash_syntax_checks.txt"
bash -n "$PHASE55B" 2>&1 | tee -a "$OUT/04_bash_syntax_checks.txt"
echo "PHASE55B_BASH_SYNTAX_OK" | tee -a "$OUT/04_bash_syntax_checks.txt"
bash -n "$PHASE45B" 2>&1 | tee -a "$OUT/04_bash_syntax_checks.txt"
echo "PHASE45B_BASH_SYNTAX_OK" | tee -a "$OUT/04_bash_syntax_checks.txt"

echo "=== RERUN REPAIRED PHASE55b ===" | tee "$OUT/05_phase55b_rerun.txt"
bash "$PHASE55B" 2>&1 | tee -a "$OUT/05_phase55b_rerun.txt"

PHASE55B_OUT="$(
  grep -oE 'PHASE55B_OUT=.*' "$OUT/05_phase55b_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE55B_OUT:-}" || ! -d "$PHASE55B_OUT" ]]; then
  PHASE55B_OUT="$(
    ls -td ops/reports/phase55b_phase45b_legacy_adapter_candidate_accounting_repair_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE55B_OUT:-}" || ! -d "$PHASE55B_OUT" ]]; then
  echo "Could not resolve latest repaired Phase55b output directory." >&2
  exit 1
fi

echo "PHASE55B_OUT=$PHASE55B_OUT" | tee "$OUT/06_phase55b_out_path.txt"

for f in \
  05_repaired_legacy_adapter_inventory.txt \
  06_repaired_legacy_adapter_source_presence_reconciliation.txt \
  07_repaired_phase45b_conclusion.txt \
  08_repaired_phase45b_console_digest.txt \
  09_targeted_assertions.txt \
  10_console_digest.txt
do
  if [[ ! -f "$PHASE55B_OUT/$f" ]]; then
    echo "Expected repaired Phase55b artifact missing: $PHASE55B_OUT/$f" >&2
    exit 1
  fi
done

cp "$PHASE55B_OUT/05_repaired_legacy_adapter_inventory.txt" \
   "$OUT/07_phase55b_repaired_legacy_adapter_inventory.txt"

cp "$PHASE55B_OUT/06_repaired_legacy_adapter_source_presence_reconciliation.txt" \
   "$OUT/08_phase55b_source_presence_reconciliation.txt"

cp "$PHASE55B_OUT/07_repaired_phase45b_conclusion.txt" \
   "$OUT/09_phase55b_repaired_phase45b_conclusion.txt"

cp "$PHASE55B_OUT/08_repaired_phase45b_console_digest.txt" \
   "$OUT/10_phase55b_repaired_phase45b_console_digest.txt"

cp "$PHASE55B_OUT/09_targeted_assertions.txt" \
   "$OUT/11_phase55b_targeted_assertions.txt"

cp "$PHASE55B_OUT/10_console_digest.txt" \
   "$OUT/12_phase55b_console_digest.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

out = Path(sys.argv[1])

assertions = (out / "11_phase55b_targeted_assertions.txt").read_text(encoding="utf-8")
digest = (out / "12_phase55b_console_digest.txt").read_text(encoding="utf-8")
phase45b_digest = (out / "10_phase55b_repaired_phase45b_console_digest.txt").read_text(encoding="utf-8")
phase45b_conclusion = (out / "09_phase55b_repaired_phase45b_conclusion.txt").read_text(encoding="utf-8")
inventory = (out / "07_phase55b_repaired_legacy_adapter_inventory.txt").read_text(encoding="utf-8")
reconciliation = (out / "08_phase55b_source_presence_reconciliation.txt").read_text(encoding="utf-8")

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Phase55b targeted assertion failures are zero",
    "TARGETED_ASSERTION_FAILURES=0" in assertions,
    "expected Phase55b targeted assertion failures = 0",
)

check(
    "Phase55b console digest states zero targeted assertion failures",
    "Targeted assertion failures: 0" in digest,
    "expected Phase55b digest failure count = 0",
)

check(
    "Phase45b digest still exposes actionable zero count",
    "Legacy adapter actionable guarded-delete candidate chains: 0" in phase45b_digest,
    "expected actionable zero digest line",
)

check(
    "Phase45b digest still exposes catalogue-only four count",
    "Legacy adapter catalogue-only already-absent chains: 4" in phase45b_digest,
    "expected catalogue-only four digest line",
)

check(
    "Phase45b digest still exposes retain zero count",
    "Legacy adapter retain/deeper-review chains: 0" in phase45b_digest,
    "expected retain zero digest line",
)

check(
    "Phase45b conclusion remains 0 / 4 / 0",
    "Legacy adapter actionable guarded-delete candidate chains: 0" in phase45b_conclusion
    and "Legacy adapter catalogue-only already-absent chains: 4" in phase45b_conclusion
    and "Legacy adapter retain/deeper-review chains: 0" in phase45b_conclusion,
    "expected corrected Phase45b conclusion accounting",
)

check(
    "Inventory remains four catalogue-only absent rows",
    inventory.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "expected 4 catalogue-only rows in inventory",
)

check(
    "Source-presence reconciliation remains four catalogue-only absent rows",
    reconciliation.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "expected 4 catalogue-only rows in reconciliation",
)

check(
    "No literal backslash-n line separators appear in Phase55b digest",
    "\\n" not in digest,
    "Phase55b digest should not contain visible literal backslash-n separators",
)

failed = 0
lines = ["=== PHASE57 TARGETED ASSERTIONS ==="]

for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "13_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

digest_lines = [
    "=== PHASE57 DIGEST ===",
    "Phase55b literal-newline residue cleanup: PASS",
    "Patched script syntax checks: PASS",
    "Phase55b rerun: PASS",
    f"Targeted assertion failures: {failed}",
    "",
    "Final result:",
    "- Phase45b legacy-adapter accounting remains correct at 0 / 4 / 0.",
    "- Phase55b now re-runs against that corrected state.",
    "- Phase55b report formatting residue is removed.",
    "- Phase55b targeted assertions should now be fully green.",
    "",
    "Review:",
    "- 01_pre_patch_bad_pattern_inventory.txt",
    "- 02_post_patch_bad_pattern_inventory.txt",
    "- 11_phase55b_targeted_assertions.txt",
    "- 12_phase55b_console_digest.txt",
    "- 13_targeted_assertions.txt",
]

(out / "14_console_digest.txt").write_text(
    "\n".join(digest_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(digest_lines))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE57_OUT=$OUT"
