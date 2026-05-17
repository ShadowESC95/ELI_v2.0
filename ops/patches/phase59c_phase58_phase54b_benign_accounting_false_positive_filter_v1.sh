#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase59c_phase58_phase54b_benign_accounting_false_positive_filter_${STAMP}"

PHASE58="ops/patches/phase58_phase54_readiness_branch_reconciliation_audit_v1.sh"

mkdir -p "$OUT/backups"

if [[ ! -f "$PHASE58" ]]; then
  echo "Required Phase58 script missing: $PHASE58" >&2
  exit 1
fi

cp "$PHASE58" "$OUT/backups/$(basename "$PHASE58").before_phase59c.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase59c — Phase58 Phase54b Benign Accounting False-Positive Filter

## Defect

After Phase59 and Phase59b:

- Phase54 is retired cleanly.
- Phase54b is retired cleanly.
- Phase54b reruns with zero targeted assertion failures.
- Phase58 still reports:
  `phase54b_source_stale_hits_present=True`

The surviving hit is not stale branch guidance. It is the valid retired-accounting
line:

`Legacy adapter actionable guarded-delete candidate chains: 0`

Phase58's Phase54b stale-source scan is therefore over-broad. This patch narrows
that scan so it continues to catch obsolete deletion/parser guidance but does not
flag the current truthful zero-actionable accounting line.
EOF

{
  echo "=== PRE-PATCH PHASE58 PHASE54b STALE-SCAN BLOCK WINDOW ==="
  grep -n -A18 -B6 \
    'PHASE54b SOURCE STALE-READINESS / PARSER HIT SCAN' \
    "$PHASE58" || true
} > "$OUT/01_pre_patch_phase58_phase54b_scan_window.txt"

python3 - "$PHASE58" "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys

phase58 = Path(sys.argv[1])
out = Path(sys.argv[2])

text = phase58.read_text(encoding="utf-8")
before = text

pattern = re.compile(
    r'''
    (?P<block>
    \{\n
    [^\n]*PHASE54b\ SOURCE\ STALE-READINESS\ /\ PARSER\ HIT\ SCAN[^\n]*\n
    .*?
    \}\s*>\s*"\$OUT/09_phase54b_source_stale_hits\.txt"
    )
    ''',
    re.VERBOSE | re.DOTALL,
)

match = pattern.search(text)
if not match:
    raise SystemExit(
        "Could not locate the Phase58 Phase54b source-stale scan block; "
        "no change made."
    )

replacement = r'''{
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
} > "$OUT/09_phase54b_source_stale_hits.txt"'''

text = text[:match.start("block")] + replacement + text[match.end("block"):]

if text == before:
    raise SystemExit("Phase58 text did not change; aborting.")

phase58.write_text(text, encoding="utf-8")

(out / "02_patch_result.txt").write_text(
    "PHASE58_PHASE54B_STALE_SCAN_BLOCK_REPLACED_OK\n",
    encoding="utf-8",
)
PY

{
  echo "=== POST-PATCH PHASE58 PHASE54b STALE-SCAN BLOCK WINDOW ==="
  grep -n -A40 -B6 \
    'PHASE54b SOURCE STALE-READINESS / PARSER HIT SCAN' \
    "$PHASE58" || true
} > "$OUT/03_post_patch_phase58_phase54b_scan_window.txt"

echo "=== BASH SYNTAX CHECK ===" | tee "$OUT/04_bash_syntax_check.txt"
bash -n "$PHASE58" 2>&1 | tee -a "$OUT/04_bash_syntax_check.txt"
echo "PHASE58_BASH_SYNTAX_OK" | tee -a "$OUT/04_bash_syntax_check.txt"

echo "=== RERUN PHASE58 ===" | tee "$OUT/05_phase58_rerun.txt"
bash "$PHASE58" 2>&1 | tee -a "$OUT/05_phase58_rerun.txt"

PHASE58_OUT="$(
  grep -oE 'PHASE58_OUT=.*' "$OUT/05_phase58_rerun.txt" \
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
  echo "Could not resolve fresh Phase58 output directory." >&2
  exit 1
fi

echo "PHASE58_OUT=$PHASE58_OUT" | tee "$OUT/06_phase58_out_path.txt"

for f in \
  "$PHASE58_OUT/09_phase54b_source_stale_hits.txt" \
  "$PHASE58_OUT/12_reconciliation_matrix.txt" \
  "$PHASE58_OUT/13_recommended_next_move.txt" \
  "$PHASE58_OUT/14_targeted_assertions.txt" \
  "$PHASE58_OUT/15_console_digest.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected fresh Phase58 artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE58_OUT/09_phase54b_source_stale_hits.txt" \
   "$OUT/07_phase58_phase54b_source_stale_hits.txt"

cp "$PHASE58_OUT/12_reconciliation_matrix.txt" \
   "$OUT/08_phase58_reconciliation_matrix.txt"

cp "$PHASE58_OUT/13_recommended_next_move.txt" \
   "$OUT/09_phase58_recommended_next_move.txt"

cp "$PHASE58_OUT/14_targeted_assertions.txt" \
   "$OUT/10_phase58_targeted_assertions.txt"

cp "$PHASE58_OUT/15_console_digest.txt" \
   "$OUT/11_phase58_console_digest.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

out = Path(sys.argv[1])

hits = (out / "07_phase58_phase54b_source_stale_hits.txt").read_text(encoding="utf-8")
matrix = (out / "08_phase58_reconciliation_matrix.txt").read_text(encoding="utf-8")
recommended = (out / "09_phase58_recommended_next_move.txt").read_text(encoding="utf-8")
assertions = (out / "10_phase58_targeted_assertions.txt").read_text(encoding="utf-8")
digest = (out / "11_phase58_console_digest.txt").read_text(encoding="utf-8")

def numbered_hit_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.strip() and line[:1].isdigit() and ":" in line
    ]

hit_lines = numbered_hit_lines(hits)

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

check(
    "Phase58 Phase54b source-stale hit file is now empty of numbered hits",
    not hit_lines,
    f"remaining={hit_lines}",
)

check(
    "Phase58 matrix reports Phase54b source stale indicators false",
    "phase54b_source_stale_hits_present=False" in matrix,
    "phase54b_source_stale_hits_present did not flip False",
)

check(
    "Phase58 matrix preserves all other stale indicators false",
    "phase54_source_stale_hits_present=False" in matrix
    and "phase54_runtime_stale_guidance_present=False" in matrix
    and "phase54b_runtime_stale_guidance_present=False" in matrix,
    "one or more non-Phase54b-source stale indicators regressed",
)

check(
    "Phase58 rerun targeted assertions remain zero",
    "TARGETED_ASSERTION_FAILURES=0" in assertions,
    "Phase58 targeted assertions not zero",
)

check(
    "Phase58 recommendation no longer loops back to Phase59 retirement work",
    "Phase59 should reconcile and retire" not in recommended,
    "old Phase59 retirement recommendation still present",
)

check(
    "Phase58 console digest reports Phase54b stale source/runtime indicators false",
    "Phase54b stale source/runtime indicators present: False" in digest,
    "Phase58 digest still reports Phase54b stale indicators",
)

failed = 0
lines = ["=== PHASE59c TARGETED ASSERTIONS ==="]

for label, ok, detail in checks:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "12_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

if failed == 0:
    digest_lines = [
        "=== PHASE59c DIGEST ===",
        "Phase58 Phase54b benign-accounting false-positive filter: PASS",
        "Fresh Phase58 rerun: PASS",
        "Targeted assertion failures: 0",
        "",
        "Final result:",
        "- Phase54 remains retired.",
        "- Phase54b remains retired.",
        "- The truthful Phase54b zero-actionable accounting line is preserved.",
        "- Phase58 no longer misclassifies that line as stale source debt.",
        "- The obsolete Phase54 / Phase54b retirement thread is now properly closed.",
    ]
else:
    digest_lines = [
        "=== PHASE59c DIGEST ===",
        "Phase58 Phase54b benign-accounting false-positive filter: PARTIAL / NEEDS FOLLOW-UP",
        "Fresh Phase58 rerun: COMPLETED",
        f"Targeted assertion failures: {failed}",
        "",
        "Interpretation:",
        "- The Phase58 detector was narrowed, but at least one closure condition still failed.",
        "- Trust 12_targeted_assertions.txt and the copied Phase58 artifacts.",
    ]

digest_lines.extend([
    "",
    "Review:",
    "- 07_phase58_phase54b_source_stale_hits.txt",
    "- 08_phase58_reconciliation_matrix.txt",
    "- 09_phase58_recommended_next_move.txt",
    "- 11_phase58_console_digest.txt",
    "- 12_targeted_assertions.txt",
])

(out / "13_console_digest.txt").write_text(
    "\n".join(digest_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(digest_lines))

if failed:
    raise SystemExit(1)
PY

echo
echo "PHASE59C_OUT=$OUT"
