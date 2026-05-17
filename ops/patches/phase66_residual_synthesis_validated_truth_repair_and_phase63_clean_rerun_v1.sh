#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase66_residual_synthesis_validated_truth_repair_and_phase63_clean_rerun_${STAMP}"

ENGINE="eli/kernel/engine.py"
PHASE63="ops/patches/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh"

mkdir -p "$OUT/backups"

for f in "$ENGINE" "$PHASE63"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$ENGINE" "$OUT/backups/engine.py.before_phase66.bak"
cp "$PHASE63" "$OUT/backups/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh.before_phase66.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase 66 — Residual synthesis_validated Truth Repair / Phase63 Clean Rerun

## Repair intent

Phase65b successfully:
- restored engine syntax;
- installed dedicated non-Quick synthesis helpers for:
  - MEMORY_STATUS.recent_processing
  - SELF_REPORT.recent_updates;
- removed the old direct-return bypass labels.

However, the post-patch grep exposed one surviving dict-literal metadata lie:

    "synthesis_validated": None if mode == "quick" else True,

That still preclaims non-Quick synthesis validation before synthesis has happened.

Phase66:
1. Replaces that exact remaining dict-literal truth defect with:
       "synthesis_validated": None,
2. Quotes the Phase63 SUMMARY heredoc so backticked prose is not executed by Bash.
3. Recompiles engine.py.
4. Reruns Phase63 and captures artifacts even if the audit fails.
EOF

python3 - "$ENGINE" "$PHASE63" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

engine_path = Path(sys.argv[1])
phase63_path = Path(sys.argv[2])
out = Path(sys.argv[3])

log: list[str] = []
assertions: list[tuple[bool, str]] = []

def check(ok: bool, msg: str) -> None:
    assertions.append((ok, msg))

# ---------------------------------------------------------------------
# 1. Repair the residual dict-literal synthesis_validated truth defect
# ---------------------------------------------------------------------

engine = engine_path.read_text(encoding="utf-8")

pattern = re.compile(
    r'(?m)^(?P<indent>\s*)"synthesis_validated": None if mode == "quick" else True,\s*$'
)

matches = list(pattern.finditer(engine))
if len(matches) != 1:
    inventory = [
        "Expected exactly one residual dict-literal synthesis_validated preclaim.",
        f"Observed match count: {len(matches)}",
        "",
        "Matching lines:",
    ]
    for m in matches:
        line_no = engine[:m.start()].count("\n") + 1
        inventory.append(f"- line {line_no}: {m.group(0).strip()}")
    (out / "00_unexpected_residual_match_inventory.txt").write_text(
        "\n".join(inventory) + "\n",
        encoding="utf-8",
    )
    raise SystemExit(
        f"Expected exactly one residual dict-literal synthesis_validated preclaim; found {len(matches)}. "
        f"See {out / '00_unexpected_residual_match_inventory.txt'}"
    )

m = matches[0]
line_no_before = engine[:m.start()].count("\n") + 1
replacement = f'{m.group("indent")}"synthesis_validated": None,'

engine = engine[:m.start()] + replacement + engine[m.end():]
engine_path.write_text(engine, encoding="utf-8")

log.append(f"RESIDUAL_SYNTHESIS_VALIDATED_DICT_LITERAL_REPAIRED=YES line_before={line_no_before}")

post_engine = engine_path.read_text(encoding="utf-8")
check(
    '"synthesis_validated": None if mode == "quick" else True,' not in post_engine,
    "residual dict-literal non-Quick synthesis preclaim removed",
)
check(
    '"synthesis_validated": None,' in post_engine,
    "truthful synthesis_validated=None literal present",
)

# ---------------------------------------------------------------------
# 2. Quote the Phase63 SUMMARY heredoc to stop command-substitution noise
# ---------------------------------------------------------------------

phase63 = phase63_path.read_text(encoding="utf-8")

unquoted = 'cat > "$OUT/SUMMARY.md" <<EOF'
quoted = 'cat > "$OUT/SUMMARY.md" <<\'EOF\''

if unquoted in phase63:
    phase63 = phase63.replace(unquoted, quoted, 1)
    phase63_path.write_text(phase63, encoding="utf-8")
    log.append("PHASE63_SUMMARY_HEREDOC_QUOTED=YES")
elif quoted in phase63:
    log.append("PHASE63_SUMMARY_HEREDOC_ALREADY_QUOTED=YES")
else:
    log.append("PHASE63_SUMMARY_HEREDOC_ANCHOR_NOT_FOUND=YES")

post_phase63 = phase63_path.read_text(encoding="utf-8")
check(
    quoted in post_phase63,
    "Phase63 SUMMARY heredoc is quoted",
)

# ---------------------------------------------------------------------
# 3. Evidence windows
# ---------------------------------------------------------------------

def source_window(text: str, needle: str, before: int = 4, after: int = 4) -> str:
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if needle in line]
    chunks: list[str] = []
    for idx in hits:
        lo = max(0, idx - before)
        hi = min(len(lines), idx + after + 1)
        chunks.append("=" * 100)
        for j in range(lo, hi):
            chunks.append(f"{j+1:6d}: {lines[j]}")
    return "\n".join(chunks) + ("\n" if chunks else "")

(out / "01_patch_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
(out / "02_engine_synthesis_validated_source_window.txt").write_text(
    source_window(post_engine, '"synthesis_validated": None,'),
    encoding="utf-8",
)
(out / "03_phase63_heredoc_source_window.txt").write_text(
    source_window(post_phase63, 'cat > "$OUT/SUMMARY.md"'),
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 4. Assertions
# ---------------------------------------------------------------------

lines = ["=== PHASE66 TARGETED ASSERTIONS ==="]
fails = 0
for ok, msg in assertions:
    lines.append(("PASS: " if ok else "FAIL: ") + msg)
    if not ok:
        fails += 1
lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={fails}")

(out / "04_targeted_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print("\n".join(lines))

if fails:
    raise SystemExit(f"Phase66 targeted assertions failed: {fails}")
PY

echo "=== PY_COMPILE ENGINE ===" | tee "$OUT/05_py_compile_engine.txt"
python3 -m py_compile "$ENGINE" 2>&1 | tee -a "$OUT/05_py_compile_engine.txt"
echo "PY_COMPILE_ENGINE_OK" | tee -a "$OUT/05_py_compile_engine.txt"

echo "=== PY_COMPILE PHASE63 SCRIPT PYTHON-FREE SHELL SYNTAX CHECK ===" | tee "$OUT/06_phase63_bash_syntax_check.txt"
bash -n "$PHASE63" 2>&1 | tee -a "$OUT/06_phase63_bash_syntax_check.txt"
echo "PHASE63_BASH_SYNTAX_OK" | tee -a "$OUT/06_phase63_bash_syntax_check.txt"

echo "=== RESIDUAL PATTERN RECHECK ===" | tee "$OUT/07_residual_pattern_recheck.txt"
grep -nF '"synthesis_validated": None if mode == "quick" else True,' "$ENGINE" 2>&1 | tee -a "$OUT/07_residual_pattern_recheck.txt" || true

echo "=== FOCUSED ENGINE GREP ===" | tee "$OUT/08_focused_engine_grep.txt"
grep -nE \
  'synthesis_validated|_mw_recent_memory_processing_synthesize|_mw_self_report_recent_updates_synthesize|MEMORY_STATUS recent_processing non-Quick: synthesized via GGUF|SELF_REPORT recent_updates non-Quick: synthesized via GGUF' \
  "$ENGINE" 2>&1 | tee -a "$OUT/08_focused_engine_grep.txt" || true

# ---------------------------------------------------------------------
# 5. Rerun Phase63 without losing our own artifacts if it returns nonzero
# ---------------------------------------------------------------------

echo "=== PHASE63 POST-PHASE66 RERUN ===" | tee "$OUT/09_phase63_rerun_console.txt"

set +e
bash "$PHASE63" 2>&1 | tee -a "$OUT/09_phase63_rerun_console.txt"
PHASE63_RC=${PIPESTATUS[0]}
set -e

echo "PHASE63_EXIT_CODE=$PHASE63_RC" | tee "$OUT/10_phase63_exit_code.txt"

POST63="$(ls -td ops/reports/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_* 2>/dev/null | head -1 || true)"
if [[ -n "${POST63:-}" && -d "$POST63" ]]; then
  echo "$POST63" > "$OUT/11_post_phase63_report_path.txt"

  cp "$POST63/11_console_verdict.txt" \
     "$OUT/12_post_phase63_verdict.txt" 2>/dev/null || true

  cp "$POST63/10_targeted_assertions.txt" \
     "$OUT/13_post_phase63_targeted_assertions.txt" 2>/dev/null || true

  cp "$POST63/08_nonquick_direct_bypass_risk_matrix.txt" \
     "$OUT/14_post_phase63_risk_matrix.txt" 2>/dev/null || true

  cp "$POST63/09_focused_engine_source_windows.txt" \
     "$OUT/15_post_phase63_focused_engine_source_windows.txt" 2>/dev/null || true
fi

PHASE63_VERDICT_OK=0
if [[ -f "$OUT/12_post_phase63_verdict.txt" ]]; then
  if grep -q 'TARGETED_ASSERTION_FAILURES=0' "$OUT/12_post_phase63_verdict.txt" \
     && grep -q 'LIKELY_NONQUICK_DIRECT_BYPASS_COUNT=0' "$OUT/12_post_phase63_verdict.txt" \
     && grep -q 'HIGH_SUSPICION_COUNT=0' "$OUT/12_post_phase63_verdict.txt"; then
    PHASE63_VERDICT_OK=1
  fi
fi

{
  echo "=== PHASE66 DIGEST ==="
  echo "Residual dict-literal synthesis_validated truth defect: REPAIRED"
  echo "Phase63 SUMMARY heredoc command-substitution noise: REPAIRED"
  echo "engine.py compile: PASS"
  echo "Phase63 bash syntax: PASS"
  echo "Phase63 exit code: $PHASE63_RC"
  echo "Phase63 clean verdict recognised: $PHASE63_VERDICT_OK"
  echo
  if [[ -f "$OUT/12_post_phase63_verdict.txt" ]]; then
    echo "--- POST-PHASE66 PHASE63 VERDICT ---"
    cat "$OUT/12_post_phase63_verdict.txt"
  else
    echo "--- POST-PHASE66 PHASE63 VERDICT ---"
    echo "Verdict file not copied; inspect 09_phase63_rerun_console.txt."
  fi
  echo
  echo "Review:"
  echo "- 01_patch_log.txt"
  echo "- 04_targeted_assertions.txt"
  echo "- 05_py_compile_engine.txt"
  echo "- 07_residual_pattern_recheck.txt"
  echo "- 08_focused_engine_grep.txt"
  echo "- 12_post_phase63_verdict.txt"
  echo "- 13_post_phase63_targeted_assertions.txt"
  echo "- 14_post_phase63_risk_matrix.txt"
  echo
  echo "PHASE66_OUT=$OUT"
} | tee "$OUT/16_console_digest.txt"

if [[ "$PHASE63_RC" -ne 0 || "$PHASE63_VERDICT_OK" -ne 1 ]]; then
  echo "Phase66 repair applied, but Phase63 did not return a fully clean verdict. See $OUT." >&2
  exit 1
fi

echo "PHASE66_SUCCESS"
