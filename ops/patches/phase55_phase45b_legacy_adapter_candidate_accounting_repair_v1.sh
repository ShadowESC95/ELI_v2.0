#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase55_phase45b_legacy_adapter_candidate_accounting_repair_${STAMP}"

SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT/backups"

for f in "$SCRIPT" "$ROUTER"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$SCRIPT" "$OUT/backups/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh.before_phase55.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase55 — Phase45b Legacy Adapter Candidate Accounting Repair

## Problem

Phase54d proved that Phase45b's legacy-adapter inventory still printed four
"PROBABLE_PHASE46_GUARDED_DELETE_CHAIN" rows even though all four named
adapter chains are already absent from the current router source.

The old accounting logic tested only post-Phase38 liveness:

- no post-marker AST hits
- no post-marker text hits

That is insufficient. A chain with no liveness may be:

1. a real source-present guarded-delete candidate, or
2. a catalogue-only residue whose source has already been retired.

## Repair

Phase55 updates Phase45b so its legacy-adapter inventory distinguishes:

- `PROBABLE_PHASE46_GUARDED_DELETE_CHAIN`
- `CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT`
- `RETAIN_OR_DEEPER_REVIEW`

The Phase45b digest and conclusion are also repaired so that actionable
guarded-delete totals count only source-present groups.
EOF

python3 - "$SCRIPT" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

script_path = Path(sys.argv[1])
out = Path(sys.argv[2])

text = script_path.read_text(encoding="utf-8")
changes: list[str] = []

# ---------------------------------------------------------------------
# 1. Replace legacy adapter classification loop
# ---------------------------------------------------------------------

old_loop = '''for group_name, symbols in adapter_groups.items():
    ast_hits = sorted(symbols & post_marker_ast_loads)
    text_hits = sorted(sym for sym in symbols if re.search(rf"\\b{re.escape(sym)}\\b", post_marker_source))

    if not ast_hits and not text_hits:
        classification = "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN"
    else:
        classification = "RETAIN_OR_DEEPER_REVIEW"

    adapter_inventory.append(
        f"{group_name} | "
        f"{', '.join(ast_hits) or '-'} | "
        f"{', '.join(text_hits) or '-'} | "
        f"{classification}"
    )
'''

new_loop = '''adapter_actionable_delete_candidate_count = 0
adapter_catalogue_only_absent_count = 0
adapter_retain_or_review_count = 0

adapter_source_presence_reconciliation = [
    "=== PHASE 45b LEGACY ADAPTER CHAIN SOURCE-PRESENCE RECONCILIATION ===",
    "",
    "group | premarker_source_hits | postmarker_source_hits | classification",
    "-" * 220,
]

for group_name, symbols in adapter_groups.items():
    ast_hits = sorted(symbols & post_marker_ast_loads)
    text_hits = sorted(sym for sym in symbols if re.search(rf"\\b{re.escape(sym)}\\b", post_marker_source))

    premarker_source_hits = sorted(
        sym for sym in symbols
        if re.search(rf"\\b{re.escape(sym)}\\b", pre_marker_source)
    )
    postmarker_source_hits = sorted(
        sym for sym in symbols
        if re.search(rf"\\b{re.escape(sym)}\\b", post_marker_source)
    )

    has_current_source_presence = bool(premarker_source_hits or postmarker_source_hits)
    has_postmarker_liveness = bool(ast_hits or text_hits)

    if has_postmarker_liveness:
        classification = "RETAIN_OR_DEEPER_REVIEW"
        adapter_retain_or_review_count += 1
    elif has_current_source_presence:
        classification = "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN"
        adapter_actionable_delete_candidate_count += 1
    else:
        classification = "CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT"
        adapter_catalogue_only_absent_count += 1

    adapter_inventory.append(
        f"{group_name} | "
        f"{', '.join(ast_hits) or '-'} | "
        f"{', '.join(text_hits) or '-'} | "
        f"{classification}"
    )

    adapter_source_presence_reconciliation.append(
        f"{group_name} | "
        f"{', '.join(premarker_source_hits) or '-'} | "
        f"{', '.join(postmarker_source_hits) or '-'} | "
        f"{classification}"
    )
'''

if old_loop not in text:
    raise SystemExit("Required Phase45b adapter classification loop anchor not found; no change made.")

text = text.replace(old_loop, new_loop, 1)
changes.append("Replaced adapter classification loop with source-presence-aware accounting.")

# ---------------------------------------------------------------------
# 2. Write the new reconciliation artifact after the existing inventory artifact
# ---------------------------------------------------------------------

old_write = '''(out / "07_legacy_adapter_chain_transitive_liveness_inventory.txt").write_text(
    "\\n".join(adapter_inventory) + "\\n",
    encoding="utf-8",
)
'''

new_write = '''(out / "07_legacy_adapter_chain_transitive_liveness_inventory.txt").write_text(
    "\\n".join(adapter_inventory) + "\\n",
    encoding="utf-8",
)

(out / "07b_legacy_adapter_chain_source_presence_reconciliation.txt").write_text(
    "\\n".join(adapter_source_presence_reconciliation) + "\\n",
    encoding="utf-8",
)
'''

if old_write not in text:
    raise SystemExit("Required Phase45b adapter inventory write anchor not found; no change made.")

text = text.replace(old_write, new_write, 1)
changes.append("Added 07b source-presence reconciliation artifact.")

# ---------------------------------------------------------------------
# 3. Replace stale derived count
# ---------------------------------------------------------------------

old_count = '''adapter_delete_candidate_count = sum(
    1
    for row in adapter_inventory
    if row.endswith("PROBABLE_PHASE46_GUARDED_DELETE_CHAIN")
)
'''

new_count = '''adapter_delete_candidate_count = adapter_actionable_delete_candidate_count
'''

if old_count not in text:
    raise SystemExit("Required Phase45b adapter_delete_candidate_count anchor not found; no change made.")

text = text.replace(old_count, new_count, 1)
changes.append("Rebased adapter_delete_candidate_count on actionable source-present groups only.")

# ---------------------------------------------------------------------
# 4. Repair conclusion text
# ---------------------------------------------------------------------

old_conclusion_lines = '''    f"Legacy adapter chains classified as probable guarded-delete candidates: {adapter_delete_candidate_count}",
    "",
    "Interpretation:",
    "- This audit replaces Phase 45 v1's false-zero direct-load test.",
    "- Phase46 should be based on the transitive post-marker liveness matrix in this report.",
    "- Mechanically splittable mixed blocks are candidates for helper extraction + dead shell removal.",
    "- Adapter chains with no post-marker AST/text hits are candidates for a separate exact-semantic guarded deletion patch.",
    "- No source files were modified in Phase 45b.",
'''

new_conclusion_lines = '''    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
    "",
    "Interpretation:",
    "- This audit replaces Phase 45 v1's false-zero direct-load test.",
    "- Phase46 should be based on the transitive post-marker liveness matrix in this report.",
    "- Mechanically splittable mixed blocks are candidates for helper extraction + dead shell removal.",
    "- Legacy adapter groups are now reconciled against current router source presence.",
    "- Only source-present groups with no post-marker liveness count as actionable guarded-delete candidates.",
    "- Catalogue-only already-absent groups are accounting residue, not remaining router source debt.",
    "- No source files were modified in Phase 45b.",
'''

if old_conclusion_lines not in text:
    raise SystemExit("Required Phase45b conclusion accounting anchor not found; no change made.")

text = text.replace(old_conclusion_lines, new_conclusion_lines, 1)
changes.append("Updated Phase45b conclusion accounting text.")

# ---------------------------------------------------------------------
# 5. Repair digest text
# ---------------------------------------------------------------------

old_digest_lines = '''    f"Legacy adapter guarded-delete candidate chains: {adapter_delete_candidate_count}",
    "",
    "Review:",
    "- 02_mixed_tryblock_liveness_matrix.txt",
    "- 03_preserve_substatement_manifest.txt",
    "- 04_remove_candidate_substatement_manifest.txt",
    "- 05_preserve_source_windows.txt",
    "- 06_remove_candidate_source_windows.txt",
    "- 07_legacy_adapter_chain_transitive_liveness_inventory.txt",
    "- 08_residual_route_capture_symbol_hits.txt",
    "- 09_residual_public_alias_rebinding_hits.txt",
    "- 10_runtime_public_surface_identity_probe.txt",
    "- 11_phase45b_conclusion.txt",
'''

new_digest_lines = '''    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
    "",
    "Review:",
    "- 02_mixed_tryblock_liveness_matrix.txt",
    "- 03_preserve_substatement_manifest.txt",
    "- 04_remove_candidate_substatement_manifest.txt",
    "- 05_preserve_source_windows.txt",
    "- 06_remove_candidate_source_windows.txt",
    "- 07_legacy_adapter_chain_transitive_liveness_inventory.txt",
    "- 07b_legacy_adapter_chain_source_presence_reconciliation.txt",
    "- 08_residual_route_capture_symbol_hits.txt",
    "- 09_residual_public_alias_rebinding_hits.txt",
    "- 10_runtime_public_surface_identity_probe.txt",
    "- 11_phase45b_conclusion.txt",
'''

if old_digest_lines not in text:
    raise SystemExit("Required Phase45b digest accounting anchor not found; no change made.")

text = text.replace(old_digest_lines, new_digest_lines, 1)
changes.append("Updated Phase45b console digest accounting text.")

# ---------------------------------------------------------------------
# 6. Ensure pre_marker_source exists
# ---------------------------------------------------------------------

old_marker_split = '''post_marker_source = "\\n".join(lines[PHASE38_LINE - 1 :])
'''

new_marker_split = '''pre_marker_source = "\\n".join(lines[: PHASE38_LINE - 1])
post_marker_source = "\\n".join(lines[PHASE38_LINE - 1 :])
'''

if old_marker_split not in text:
    raise SystemExit("Required Phase45b post_marker_source anchor not found; no change made.")

text = text.replace(old_marker_split, new_marker_split, 1)
changes.append("Added pre_marker_source for current-source presence reconciliation.")

script_path.write_text(text, encoding="utf-8")

(out / "01_patch_changes.txt").write_text(
    "\\n".join(f"- {change}" for change in changes) + "\\n",
    encoding="utf-8",
)

print("PHASE55_PATCH_APPLIED_OK")
for change in changes:
    print(f"- {change}")
PY

echo "=== SCRIPT SYNTAX CHECK ===" | tee "$OUT/02_script_syntax_check.txt"
bash -n "$SCRIPT" 2>&1 | tee -a "$OUT/02_script_syntax_check.txt"
echo "BASH_SYNTAX_OK" | tee -a "$OUT/02_script_syntax_check.txt"

echo "=== RUN REPAIRED PHASE45b ===" | tee "$OUT/03_repaired_phase45b_run.txt"
bash "$SCRIPT" 2>&1 | tee -a "$OUT/03_repaired_phase45b_run.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/03_repaired_phase45b_run.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  PHASE45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* 2>/dev/null | head -1 || true)"
fi

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve repaired Phase45b output directory." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/04_phase45b_out_path.txt"

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/05_repaired_legacy_adapter_inventory.txt"

cp "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt" \
   "$OUT/06_repaired_legacy_adapter_source_presence_reconciliation.txt"

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/07_repaired_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/12_console_digest.txt" \
   "$OUT/08_repaired_phase45b_console_digest.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

out = Path(sys.argv[1])

digest = (out / "08_repaired_phase45b_console_digest.txt").read_text(encoding="utf-8")
inventory = (out / "05_repaired_legacy_adapter_inventory.txt").read_text(encoding="utf-8")
recon = (out / "06_repaired_legacy_adapter_source_presence_reconciliation.txt").read_text(encoding="utf-8")
conclusion = (out / "07_repaired_phase45b_conclusion.txt").read_text(encoding="utf-8")

checks = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "digest actionable count repaired to zero",
    "Legacy adapter actionable guarded-delete candidate chains: 0" in digest,
    "Expected actionable guarded-delete count = 0",
)

check(
    "digest catalogue-only absent count repaired to four",
    "Legacy adapter catalogue-only already-absent chains: 4" in digest,
    "Expected catalogue-only already-absent count = 4",
)

check(
    "digest retain/deeper-review count repaired to zero",
    "Legacy adapter retain/deeper-review chains: 0" in digest,
    "Expected retain/deeper-review count = 0",
)

check(
    "legacy inventory classifications changed away from stale probable-delete rows",
    inventory.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4
    and "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN" not in inventory,
    "Expected 4 catalogue-only absent rows and no stale probable-delete rows",
)

check(
    "source-presence reconciliation artifact generated",
    "=== PHASE 45b LEGACY ADAPTER CHAIN SOURCE-PRESENCE RECONCILIATION ===" in recon
    and recon.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "Expected reconciliation artifact with 4 catalogue-only absent rows",
)

check(
    "conclusion text updated",
    "Only source-present groups with no post-marker liveness count as actionable guarded-delete candidates." in conclusion,
    "Expected repaired explanatory conclusion text",
)

lines = ["=== PHASE55 TARGETED ASSERTIONS ==="]
failed = 0
for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "09_targeted_assertions.txt").write_text(
    "\\n".join(lines) + "\\n",
    encoding="utf-8",
)

digest_out = [
    "=== PHASE55 DIGEST ===",
    "Phase45b script patch: PASS",
    "Phase45b bash syntax check: PASS",
    "Repaired Phase45b run: PASS",
    f"Targeted assertion failures: {failed}",
    "",
    "Expected repaired accounting state:",
    "- actionable guarded-delete candidate chains: 0",
    "- catalogue-only already-absent chains: 4",
    "- retain/deeper-review chains: 0",
    "",
    "Interpretation:",
    "Phase45b no longer mistakes retired catalogue entries for actionable router source debt.",
    "The legacy-adapter branch is now correctly closed unless future router source reintroduces one of those chains.",
    "",
    "Review:",
    "- 05_repaired_legacy_adapter_inventory.txt",
    "- 06_repaired_legacy_adapter_source_presence_reconciliation.txt",
    "- 07_repaired_phase45b_conclusion.txt",
    "- 08_repaired_phase45b_console_digest.txt",
    "- 09_targeted_assertions.txt",
]

(out / "10_console_digest.txt").write_text(
    "\\n".join(digest_out) + "\\n",
    encoding="utf-8",
)

print("\\n".join(digest_out))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE55_OUT=$OUT"
