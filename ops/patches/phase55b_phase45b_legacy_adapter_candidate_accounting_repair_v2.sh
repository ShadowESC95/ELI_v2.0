#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase55b_phase45b_legacy_adapter_candidate_accounting_repair_${STAMP}"

SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT/backups"

for f in "$SCRIPT" "$ROUTER"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$SCRIPT" "$OUT/backups/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh.before_phase55b.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase55b — Phase45b Legacy Adapter Candidate Accounting Repair v2

## Why Phase55 v1 failed

Phase55 v1 attempted to replace a specific multi-line
`adapter_delete_candidate_count = ...` anchor that is not present in the
current Phase45b audit script.

The repair intent was correct; the anchor strategy was not.

## Verified source state before this repair

Phase54d proved:

- parsed Phase45b legacy-adapter rows: 4
- concrete source-present candidate chains: 0
- catalogue-only already-absent chains: 4
- retain/deeper-review chains: 0

Therefore the current Phase45b digest is misleading when it still reports:

- `Legacy adapter guarded-delete candidate chains: 4`

## Repair strategy

This patch updates Phase45b itself so it:

1. distinguishes source-present actionable delete candidates from catalogue-only absent rows;
2. writes a dedicated source-presence reconciliation artifact;
3. reports corrected digest and conclusion counts;
4. preserves audit-only behaviour and modifies no router source.
EOF

python3 - "$SCRIPT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

script_path = Path(sys.argv[1])
out = Path(sys.argv[2])

text = script_path.read_text(encoding="utf-8")
changes: list[str] = []

def replace_once(old: str, new: str, label: str) -> None:
    global text
    if new in text:
        changes.append(f"SKIP already present: {label}")
        return
    if old not in text:
        raise SystemExit(f"Required Phase45b anchor not found: {label}")
    text = text.replace(old, new, 1)
    changes.append(label)

# ---------------------------------------------------------------------
# 1. Update Phase45b SUMMARY wording so it no longer frames all no-liveness
#    adapter rows as prospective delete candidates.
# ---------------------------------------------------------------------

replace_once(
    '4. Which legacy adapter chains have no post-marker liveness and may become guarded delete candidates in a later phase.',
    '4. Which legacy adapter groups are source-present actionable delete candidates versus catalogue-only already-retired rows.',
    "summary wording: legacy adapter source-presence distinction",
)

# ---------------------------------------------------------------------
# 2. Replace the legacy adapter inventory classification loop.
#    This exact old block was captured by Phase54c.
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

new_loop = '''pre_marker_source = "\\n".join(lines[:PHASE38_LINE - 1])

adapter_actionable_delete_candidate_count = 0
adapter_catalogue_only_absent_count = 0
adapter_retain_or_review_count = 0

adapter_source_presence_reconciliation = [
    "=== PHASE 45b LEGACY ADAPTER CHAIN SOURCE-PRESENCE RECONCILIATION ===",
    "",
    "group | premarker_source_hits | postmarker_source_hits | classification",
    "-" * 240,
]

for group_name, symbols in adapter_groups.items():
    ast_hits = sorted(symbols & post_marker_ast_loads)
    text_hits = sorted(sym for sym in symbols if re.search(rf"\\b{re.escape(sym)}\\b", post_marker_source))

    pre_source_hits = sorted(
        sym for sym in symbols
        if re.search(rf"\\b{re.escape(sym)}\\b", pre_marker_source)
    )
    post_source_hits = sorted(
        sym for sym in symbols
        if re.search(rf"\\b{re.escape(sym)}\\b", post_marker_source)
    )

    has_current_source_presence = bool(pre_source_hits or post_source_hits)
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
        f"{', '.join(pre_source_hits) or '-'} | "
        f"{', '.join(post_source_hits) or '-'} | "
        f"{classification}"
    )
'''

replace_once(
    old_loop,
    new_loop,
    "legacy adapter classification loop: source-presence-aware accounting",
)

# ---------------------------------------------------------------------
# 3. Extend artifact writing: keep existing inventory and add reconciliation.
# ---------------------------------------------------------------------

old_inventory_write = '''(out / "07_legacy_adapter_chain_transitive_liveness_inventory.txt").write_text(
    "\\n".join(adapter_inventory) + "\\n",
    encoding="utf-8",
)
'''

new_inventory_write = '''(out / "07_legacy_adapter_chain_transitive_liveness_inventory.txt").write_text(
    "\\n".join(adapter_inventory) + "\\n",
    encoding="utf-8",
)

(out / "07b_legacy_adapter_chain_source_presence_reconciliation.txt").write_text(
    "\\n".join(adapter_source_presence_reconciliation) + "\\n",
    encoding="utf-8",
)
'''

replace_once(
    old_inventory_write,
    new_inventory_write,
    "artifact write: added 07b source-presence reconciliation",
)

# ---------------------------------------------------------------------
# 4. Insert an authoritative count override immediately before the conclusion.
#    This intentionally avoids relying on the old count-definition shape.
# ---------------------------------------------------------------------

old_conclusion_anchor = '''conclusion = [
'''

new_conclusion_anchor = '''# Phase55b correction:
# Only source-present adapter groups with no post-marker liveness are actionable
# guarded-delete candidates. Catalogue-only absent rows must not inflate this count.
adapter_delete_candidate_count = adapter_actionable_delete_candidate_count

conclusion = [
'''

replace_once(
    old_conclusion_anchor,
    new_conclusion_anchor,
    "late authoritative adapter_delete_candidate_count override before conclusion",
)

# ---------------------------------------------------------------------
# 5. Repair conclusion lines.
# ---------------------------------------------------------------------

replace_once(
    '    f"Legacy adapter chains classified as probable guarded-delete candidates: {adapter_delete_candidate_count}",\n',
    '''    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
''',
    "conclusion counts: actionable / catalogue-only / retain",
)

replace_once(
    '    "- Adapter chains with no post-marker AST/text hits are candidates for a separate exact-semantic guarded deletion patch.",\n',
    '''    "- Only source-present adapter groups with no post-marker AST/text liveness count as actionable guarded-delete candidates.",
    "- Catalogue-only already-absent rows are retired inventory residue, not remaining router source debt.",
''',
    "conclusion interpretation: source-presence-aware adapter accounting",
)

# ---------------------------------------------------------------------
# 6. Repair digest lines.
# ---------------------------------------------------------------------

replace_once(
    '    f"Legacy adapter guarded-delete candidate chains: {adapter_delete_candidate_count}",\n',
    '''    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
''',
    "digest counts: actionable / catalogue-only / retain",
)

replace_once(
    '    "- 07_legacy_adapter_chain_transitive_liveness_inventory.txt",\n',
    '''    "- 07_legacy_adapter_chain_transitive_liveness_inventory.txt",
    "- 07b_legacy_adapter_chain_source_presence_reconciliation.txt",
''',
    "digest review list: added 07b reconciliation artifact",
)

script_path.write_text(text, encoding="utf-8")

(out / "01_changes_applied.txt").write_text(
    "\\n".join(f"- {change}" for change in changes) + "\\n",
    encoding="utf-8",
)

print("PHASE55B_PATCH_APPLIED_OK")
for change in changes:
    print(f"- {change}")
PY

echo "=== PHASE55b SCRIPT SYNTAX CHECK ===" | tee "$OUT/02_script_syntax_check.txt"
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

python3 - "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

out = Path(sys.argv[1])

digest = (out / "08_repaired_phase45b_console_digest.txt").read_text(encoding="utf-8")
inventory = (out / "05_repaired_legacy_adapter_inventory.txt").read_text(encoding="utf-8")
recon = (out / "06_repaired_legacy_adapter_source_presence_reconciliation.txt").read_text(encoding="utf-8")
conclusion = (out / "07_repaired_phase45b_conclusion.txt").read_text(encoding="utf-8")

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "digest actionable guarded-delete count is zero",
    "Legacy adapter actionable guarded-delete candidate chains: 0" in digest,
    "expected actionable guarded-delete candidate count = 0",
)

check(
    "digest catalogue-only already-absent count is four",
    "Legacy adapter catalogue-only already-absent chains: 4" in digest,
    "expected catalogue-only already-absent count = 4",
)

check(
    "digest retain/deeper-review count is zero",
    "Legacy adapter retain/deeper-review chains: 0" in digest,
    "expected retain/deeper-review count = 0",
)

check(
    "legacy inventory has four catalogue-only absent classifications",
    inventory.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "expected 4 catalogue-only classifications in repaired inventory",
)

check(
    "legacy inventory no longer reports probable guarded-delete candidates",
    "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN" not in inventory,
    "expected no probable guarded-delete rows in current router state",
)

check(
    "source-presence reconciliation artifact exists and contains four catalogue-only absent rows",
    "=== PHASE 45b LEGACY ADAPTER CHAIN SOURCE-PRESENCE RECONCILIATION ===" in recon
    and recon.count("CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT") == 4,
    "expected 07b reconciliation artifact with 4 catalogue-only absent rows",
)

check(
    "conclusion explains corrected accounting",
    "Only source-present adapter groups with no post-marker AST/text liveness count as actionable guarded-delete candidates." in conclusion
    and "Catalogue-only already-absent rows are retired inventory residue, not remaining router source debt." in conclusion,
    "expected corrected Phase45b interpretation text",
)

check(
    "old misleading digest wording absent",
    "Legacy adapter guarded-delete candidate chains: 4" not in digest,
    "old stale digest wording should be absent",
)

check(
    "old misleading conclusion wording absent",
    "Legacy adapter chains classified as probable guarded-delete candidates: 4" not in conclusion,
    "old stale conclusion wording should be absent",
)

failed = 0
lines = ["=== PHASE55b TARGETED ASSERTIONS ==="]
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
    "=== PHASE55b DIGEST ===",
    "Phase45b accounting repair patch: PASS",
    "Phase45b patched script bash syntax: PASS",
    "Repaired Phase45b audit execution: PASS",
    f"Targeted assertion failures: {failed}",
    "",
    "Corrected current Phase45b legacy-adapter accounting:",
    "- actionable guarded-delete candidate chains: 0",
    "- catalogue-only already-absent chains: 4",
    "- retain/deeper-review chains: 0",
    "",
    "Conclusion:",
    "Phase45b no longer misreports retired catalogue rows as live guarded-delete source debt.",
    "The legacy-adapter deletion branch is now accounting-clean.",
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
echo "PHASE55B_OUT=$OUT"
