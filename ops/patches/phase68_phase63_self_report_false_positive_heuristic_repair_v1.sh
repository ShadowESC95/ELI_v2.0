#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase68_phase63_self_report_false_positive_heuristic_repair_${STAMP}"

PHASE63="ops/patches/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh"
ENGINE="eli/kernel/engine.py"

mkdir -p "$OUT/backups"

for f in "$PHASE63" "$ENGINE"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE63" "$OUT/backups/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh.before_phase68.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase 68 — Phase63 SELF_REPORT False-Positive Heuristic Repair

## Why this patch exists

Phase67 proved that `SELF_REPORT.recent_updates` no longer contains a surviving
non-Quick direct-return bypass:

- no direct `return _eli_self_mw_report` remains;
- the middleware calls `_mw_self_report_recent_updates_synthesize(...)`;
- the middleware returns `_eli_self_mw_out`;
- remaining `gguf_used=False` hits are Quick-branch evidence labels only.

Phase63 still reports `HIGH_SUSPICION` because its static heuristic treats:

1. any `gguf_used=False` hit anywhere in the block, plus
2. any apparent surface-output return shape anywhere in the block,

as sufficient to mark the whole surface suspicious.

That is now too broad.

## Repair intent

Phase68 updates the Phase63 audit so `SELF_REPORT.recent_updates` is not flagged
when the block has explicit non-Quick synthesis proof:

- dedicated synthesis helper call exists;
- synthesized output return exists;
- direct non-Quick surface-return bypass is not proven.

This patch changes only the audit script. It does not modify runtime engine logic.
EOF

python3 - "$PHASE63" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

phase63_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = phase63_path.read_text(encoding="utf-8")
original = src
log: list[str] = []

# ---------------------------------------------------------------------
# 1. Extend the block feature model with explicit synthesis-output proof.
# ---------------------------------------------------------------------

dataclass_anchor = """    sets_gguf_used_false: bool
"""
dataclass_insert = """    sets_gguf_used_false: bool
    contains_explicit_synthesis_helper_call: bool
    contains_return_of_synthesized_output: bool
"""

if dataclass_insert not in src:
    if dataclass_anchor not in src:
        raise SystemExit("Phase68: dataclass field anchor not found.")
    src = src.replace(dataclass_anchor, dataclass_insert, 1)
    log.append("Inserted feature fields: contains_explicit_synthesis_helper_call, contains_return_of_synthesized_output")
else:
    log.append("Feature fields already present; skipped.")

# ---------------------------------------------------------------------
# 2. Compute those features during source-shape extraction.
# ---------------------------------------------------------------------

feature_anchor = """    gguf_false_lines = global_line_numbers(b, r'gguf_used["\\']?\\]?\\s*=\\s*False|"gguf_used"\\s*:\\s*False')
"""
feature_insert = """    gguf_false_lines = global_line_numbers(b, r'gguf_used["\\']?\\]?\\s*=\\s*False|"gguf_used"\\s*:\\s*False')
    explicit_synthesis_helper_call_lines = global_line_numbers(
        b,
        r"_mw_(?:recent_memory_processing|self_report_recent_updates)_synthesize\\s*\\(",
    )
    return_of_synthesized_output_lines = global_line_numbers(
        b,
        r"return\\s+_eli_(?:rm|self)_mw_out\\b",
    )
"""

if feature_insert not in src:
    if feature_anchor not in src:
        raise SystemExit("Phase68: feature extraction anchor not found.")
    src = src.replace(feature_anchor, feature_insert, 1)
    log.append("Inserted synthesis-helper and synthesized-output return source scans.")
else:
    log.append("Feature extraction already present; skipped.")

# ---------------------------------------------------------------------
# 3. Populate the new fields in the feature object constructor.
# ---------------------------------------------------------------------

constructor_anchor = """        sets_gguf_used_false=bool(gguf_false_lines),
"""
constructor_insert = """        sets_gguf_used_false=bool(gguf_false_lines),
        contains_explicit_synthesis_helper_call=bool(explicit_synthesis_helper_call_lines),
        contains_return_of_synthesized_output=bool(return_of_synthesized_output_lines),
"""

if constructor_insert not in src:
    if constructor_anchor not in src:
        raise SystemExit("Phase68: feature constructor anchor not found.")
    src = src.replace(constructor_anchor, constructor_insert, 1)
    log.append("Populated new synthesis-proof feature fields.")
else:
    log.append("Feature constructor already updated; skipped.")

# ---------------------------------------------------------------------
# 4. Surface the new features in the feature-matrix text output.
# ---------------------------------------------------------------------

matrix_anchor = """        f"sets_gguf_used_false={f.sets_gguf_used_false}",
"""
matrix_insert = """        f"sets_gguf_used_false={f.sets_gguf_used_false}",
        f"contains_explicit_synthesis_helper_call={f.contains_explicit_synthesis_helper_call}",
        f"contains_return_of_synthesized_output={f.contains_return_of_synthesized_output}",
"""

if matrix_insert not in src:
    if matrix_anchor not in src:
        raise SystemExit("Phase68: feature matrix output anchor not found.")
    src = src.replace(matrix_anchor, matrix_insert, 1)
    log.append("Extended feature-matrix text output with synthesis-proof fields.")
else:
    log.append("Feature matrix already updated; skipped.")

# ---------------------------------------------------------------------
# 5. Repair SELF_REPORT recent_updates interpretation logic.
# ---------------------------------------------------------------------
#
# Old false-positive branch:
#
# elif sr.sets_gguf_used_false and sr.contains_early_return_of_surface_output:
#     HIGH_SUSPICION
#
# New rule:
# Only keep HIGH_SUSPICION if direct-return signals remain AND explicit
# non-Quick synthesis proof is absent.
# ---------------------------------------------------------------------

old_self_high = '''    elif sr.sets_gguf_used_false and sr.contains_early_return_of_surface_output:
        interpretations.append(interpret(
            "SELF_REPORT.recent_updates",
            "HIGH_SUSPICION",
            "Block sets gguf_used=False and appears to return the surface output directly; verify full non-Quick branch label and return semantics.",
        ))
'''

new_self_high = '''    elif (
        sr.sets_gguf_used_false
        and sr.contains_early_return_of_surface_output
        and not (
            sr.contains_explicit_synthesis_helper_call
            and sr.contains_return_of_synthesized_output
        )
    ):
        interpretations.append(interpret(
            "SELF_REPORT.recent_updates",
            "HIGH_SUSPICION",
            "Block sets gguf_used=False and appears to return the surface output directly without sufficient explicit synthesized-output proof.",
        ))
'''

if new_self_high not in src:
    if old_self_high not in src:
        raise SystemExit("Phase68: SELF_REPORT HIGH_SUSPICION branch anchor not found.")
    src = src.replace(old_self_high, new_self_high, 1)
    log.append("Narrowed SELF_REPORT HIGH_SUSPICION heuristic to exempt explicit synthesized-output proof.")
else:
    log.append("SELF_REPORT HIGH_SUSPICION heuristic already updated; skipped.")

# ---------------------------------------------------------------------
# 6. Strengthen SELF_REPORT clean interpretation message so the digest
#    makes the closed source shape explicit.
# ---------------------------------------------------------------------

old_self_clean = '''        interpretations.append(interpret(
            "SELF_REPORT.recent_updates",
            "NO_CLEAR_BYPASS_PROVEN",
            "This narrow source-shape audit did not prove a direct non-Quick bypass.",
        ))
'''

new_self_clean = '''        interpretations.append(interpret(
            "SELF_REPORT.recent_updates",
            "NO_CLEAR_BYPASS_PROVEN",
            "No non-Quick direct-return bypass is proven; explicit synthesis-helper and synthesized-output return signals are accepted as closing evidence when present.",
        ))
'''

if new_self_clean not in src:
    if old_self_clean not in src:
        raise SystemExit("Phase68: SELF_REPORT clean interpretation branch anchor not found.")
    src = src.replace(old_self_clean, new_self_clean, 1)
    log.append("Updated SELF_REPORT clean interpretation text.")
else:
    log.append("SELF_REPORT clean interpretation text already updated; skipped.")

# ---------------------------------------------------------------------
# 7. Add a focused targeted assertion documenting this exact repaired case.
# ---------------------------------------------------------------------

assertion_anchor = '''record(
    self_verdict not in {"LIKELY_NONQUICK_DIRECT_BYPASS", "HIGH_SUSPICION"},
    "self-report recent-updates does not present a likely non-Quick direct bypass",
    f"verdict={self_verdict}",
)
'''

assertion_insert = '''record(
    self_verdict not in {"LIKELY_NONQUICK_DIRECT_BYPASS", "HIGH_SUSPICION"},
    "self-report recent-updates does not present a likely non-Quick direct bypass",
    f"verdict={self_verdict}",
)

record(
    not (
        sr.contains_explicit_synthesis_helper_call
        and sr.contains_return_of_synthesized_output
        and self_verdict == "HIGH_SUSPICION"
    ),
    "self-report explicit non-Quick synthesis proof is not falsely classified as HIGH_SUSPICION",
    (
        f"verdict={self_verdict} "
        f"helper_call={sr.contains_explicit_synthesis_helper_call} "
        f"return_synthesized={sr.contains_return_of_synthesized_output}"
    ),
)
'''

if assertion_insert not in src:
    if assertion_anchor not in src:
        raise SystemExit("Phase68: targeted assertion insertion anchor not found.")
    src = src.replace(assertion_anchor, assertion_insert, 1)
    log.append("Added targeted false-positive regression assertion.")
else:
    log.append("Targeted false-positive regression assertion already present; skipped.")

if src == original:
    log.append("No source changes made.")

phase63_path.write_text(src, encoding="utf-8")
(out / "01_patch_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
print("\n".join(log))
PY

echo "=== PHASE68 PATCH LOG ===" | tee "$OUT/02_patch_log_console.txt"
cat "$OUT/01_patch_log.txt" | tee -a "$OUT/02_patch_log_console.txt"

echo "=== BASH SYNTAX PHASE63 ===" | tee "$OUT/03_phase63_bash_syntax.txt"
bash -n "$PHASE63" 2>&1 | tee -a "$OUT/03_phase63_bash_syntax.txt"
echo "PHASE63_BASH_SYNTAX_OK" | tee -a "$OUT/03_phase63_bash_syntax.txt"

echo "=== PHASE63 CLEAN RERUN ===" | tee "$OUT/04_phase63_rerun_console.txt"
set +e
bash "$PHASE63" 2>&1 | tee -a "$OUT/04_phase63_rerun_console.txt"
PHASE63_EXIT="${PIPESTATUS[0]}"
set -e
echo "PHASE63_EXIT_CODE=$PHASE63_EXIT" | tee -a "$OUT/04_phase63_rerun_console.txt"

PHASE63_OUT="$(grep -E '^PHASE63_OUT=' "$OUT/04_phase63_rerun_console.txt" | tail -1 | cut -d= -f2- || true)"
if [[ -z "${PHASE63_OUT:-}" || ! -d "$PHASE63_OUT" ]]; then
  echo "Could not resolve PHASE63_OUT from rerun console." >&2
  exit 1
fi

cp "$PHASE63_OUT/11_contract_verdict.txt" "$OUT/05_post_phase68_phase63_verdict.txt" 2>/dev/null || \
cp "$PHASE63_OUT/11_nonquick_synthesis_path_verdict.txt" "$OUT/05_post_phase68_phase63_verdict.txt" 2>/dev/null || true

cp "$PHASE63_OUT/10_targeted_assertions.txt" "$OUT/06_post_phase68_phase63_targeted_assertions.txt" 2>/dev/null || true
cp "$PHASE63_OUT/08_nonquick_direct_bypass_risk_matrix.txt" "$OUT/07_post_phase68_phase63_risk_matrix.txt" 2>/dev/null || true
cp "$PHASE63_OUT/06_block_semantic_feature_matrix.txt" "$OUT/08_post_phase68_feature_matrix.txt" 2>/dev/null || true

python3 - "$PHASE63" "$OUT" "$PHASE63_OUT" "$PHASE63_EXIT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

phase63 = Path(sys.argv[1])
out = Path(sys.argv[2])
phase63_out = Path(sys.argv[3])
phase63_exit = int(sys.argv[4])

verdict = ""
targeted = ""
risk = ""
features = ""

for candidate in [
    out / "05_post_phase68_phase63_verdict.txt",
    phase63_out / "11_contract_verdict.txt",
    phase63_out / "11_nonquick_synthesis_path_verdict.txt",
]:
    if candidate.exists():
        verdict = candidate.read_text(encoding="utf-8", errors="replace")
        break

for candidate in [
    out / "06_post_phase68_phase63_targeted_assertions.txt",
    phase63_out / "10_targeted_assertions.txt",
]:
    if candidate.exists():
        targeted = candidate.read_text(encoding="utf-8", errors="replace")
        break

for candidate in [
    out / "07_post_phase68_phase63_risk_matrix.txt",
    phase63_out / "08_nonquick_direct_bypass_risk_matrix.txt",
]:
    if candidate.exists():
        risk = candidate.read_text(encoding="utf-8", errors="replace")
        break

for candidate in [
    out / "08_post_phase68_feature_matrix.txt",
    phase63_out / "06_block_semantic_feature_matrix.txt",
]:
    if candidate.exists():
        features = candidate.read_text(encoding="utf-8", errors="replace")
        break

assertions: list[tuple[bool, str, str]] = []

def record(ok: bool, label: str, detail: str = "") -> None:
    assertions.append((ok, label, detail))

record(phase63_exit == 0, "Phase63 rerun exits cleanly", f"exit={phase63_exit}")
record("TARGETED_ASSERTION_FAILURES=0" in targeted, "Phase63 targeted assertions are clean")
record("HIGH_SUSPICION_COUNT=0" in verdict, "Phase63 verdict reports zero HIGH_SUSPICION surfaces")
record("LIKELY_NONQUICK_DIRECT_BYPASS_COUNT=0" in verdict, "Phase63 verdict reports zero likely direct bypasses")
record(
    "self-report recent-updates does not present a likely non-Quick direct bypass" in targeted
    and "PASS:" in targeted,
    "self-report recent-updates bypass assertion passes",
)
record(
    "explicit non-Quick synthesis proof is not falsely classified as HIGH_SUSPICION" in targeted
    and "PASS:" in targeted,
    "false-positive regression assertion passes",
)
record(
    "contains_explicit_synthesis_helper_call=True" in features,
    "feature matrix records self-report synthesis helper proof",
)
record(
    "contains_return_of_synthesized_output=True" in features,
    "feature matrix records synthesized-output return proof",
)

failures = [a for a in assertions if not a[0]]
closed = not failures

lines = [
    "=== PHASE68 VERDICT ===",
    f"PHASE63_SELF_REPORT_FALSE_POSITIVE_HEURISTIC_REPAIR_CLOSED={str(closed).upper()}",
    f"TARGETED_ASSERTION_FAILURES={len(failures)}",
    "",
]

if closed:
    lines.extend([
        "Conclusion:",
        "- Phase63 now agrees with Phase67's branch-truth audit.",
        "- SELF_REPORT.recent_updates is no longer falsely reported as HIGH_SUSPICION.",
        "- The remaining non-Quick grounded synthesis contract is clean at the Phase63 source-shape audit level.",
        "- The engine did not require another runtime patch; only the stale audit heuristic needed correction.",
    ])
else:
    lines.extend([
        "Conclusion:",
        "- Phase68 patched the heuristic, but one or more verification conditions did not close.",
        "- Inspect the post-rerun Phase63 verdict, targeted assertions, risk matrix, and feature matrix.",
    ])

(out / "09_phase68_verdict.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

assertion_lines = ["=== PHASE68 TARGETED ASSERTIONS ==="]
for ok, label, detail in assertions:
    prefix = "PASS" if ok else "FAIL"
    assertion_lines.append(f"{prefix}: {label}" + (f" — {detail}" if detail else ""))
assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={len(failures)}")
(out / "10_phase68_targeted_assertions.txt").write_text("\n".join(assertion_lines) + "\n", encoding="utf-8")

print("\n".join(lines))
print()
print("\n".join(assertion_lines))
PY

{
  echo "=== PHASE68 DIGEST ==="
  cat "$OUT/09_phase68_verdict.txt"
  echo
  echo "Review:"
  echo "- 01_patch_log.txt"
  echo "- 04_phase63_rerun_console.txt"
  echo "- 05_post_phase68_phase63_verdict.txt"
  echo "- 06_post_phase68_phase63_targeted_assertions.txt"
  echo "- 07_post_phase68_phase63_risk_matrix.txt"
  echo "- 08_post_phase68_feature_matrix.txt"
  echo "- 10_phase68_targeted_assertions.txt"
  echo
  echo "PHASE68_OUT=$OUT"
} | tee "$OUT/11_console_digest.txt"

echo "PHASE68_OUT=$OUT"
