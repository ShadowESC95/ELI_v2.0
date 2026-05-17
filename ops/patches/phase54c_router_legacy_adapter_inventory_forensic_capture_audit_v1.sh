#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase54c_router_legacy_adapter_inventory_forensic_capture_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"

mkdir -p "$OUT"

for f in "$ROUTER" "$PHASE45B_SCRIPT"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase54c — Router Legacy Adapter Inventory Forensic Capture Audit

## Purpose

Phase54b proved that the Phase45b legacy-adapter inventory could not be parsed:

- candidate spans extracted: 0
- candidate symbols extracted: 0
- parser visibility: FAIL-CLOSED
- Phase55 deletion patch not authorised

Phase54c does not modify router source.

It captures the exact raw structure of Phase45b's legacy-adapter output in order
to determine whether:

1. The inventory file is empty or structurally barren.
2. The candidate-chain detail lives in a different artifact.
3. Phase45b computes the candidate count but fails to emit candidate inventory.
4. A very specific parser is needed for the actual inventory format.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

echo "=== PHASE45b REFRESH ===" | tee "$OUT/01_phase45b_refresh.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/01_phase45b_refresh.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/01_phase45b_refresh.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  PHASE45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* 2>/dev/null | head -1 || true)"
fi

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve refreshed Phase45b output directory." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/02_phase45b_out_path.txt"

INV="$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt"
DIGEST="$PHASE45B_OUT/12_console_digest.txt"
CONCLUSION="$PHASE45B_OUT/11_phase45b_conclusion.txt"

echo "=== PHASE45b OUTPUT FILE INVENTORY ===" | tee "$OUT/03_phase45b_output_file_inventory.txt"
find "$PHASE45B_OUT" -maxdepth 1 -type f -printf '%f\t%s bytes\n' \
  | sort \
  | tee -a "$OUT/03_phase45b_output_file_inventory.txt"

echo "=== PHASE45b DIGEST ===" | tee "$OUT/04_phase45b_digest.txt"
if [[ -f "$DIGEST" ]]; then
  cat "$DIGEST" | tee -a "$OUT/04_phase45b_digest.txt"
else
  echo "Missing digest file: $DIGEST" | tee -a "$OUT/04_phase45b_digest.txt"
fi

echo "=== PHASE45b CONCLUSION ===" | tee "$OUT/05_phase45b_conclusion.txt"
if [[ -f "$CONCLUSION" ]]; then
  cat "$CONCLUSION" | tee -a "$OUT/05_phase45b_conclusion.txt"
else
  echo "Missing conclusion file: $CONCLUSION" | tee -a "$OUT/05_phase45b_conclusion.txt"
fi

echo "=== RAW LEGACY ADAPTER INVENTORY FILE STATUS ===" | tee "$OUT/06_legacy_adapter_inventory_file_status.txt"
if [[ -f "$INV" ]]; then
  printf 'path=%s\n' "$INV" | tee -a "$OUT/06_legacy_adapter_inventory_file_status.txt"
  printf 'bytes=' | tee -a "$OUT/06_legacy_adapter_inventory_file_status.txt"
  wc -c < "$INV" | tee -a "$OUT/06_legacy_adapter_inventory_file_status.txt"
  printf 'lines=' | tee -a "$OUT/06_legacy_adapter_inventory_file_status.txt"
  wc -l < "$INV" | tee -a "$OUT/06_legacy_adapter_inventory_file_status.txt"
else
  echo "MISSING: $INV" | tee -a "$OUT/06_legacy_adapter_inventory_file_status.txt"
fi

echo "=== RAW LEGACY ADAPTER INVENTORY ===" | tee "$OUT/07_legacy_adapter_inventory_raw.txt"
if [[ -f "$INV" ]]; then
  cat "$INV" | tee -a "$OUT/07_legacy_adapter_inventory_raw.txt"
else
  echo "MISSING: $INV" | tee -a "$OUT/07_legacy_adapter_inventory_raw.txt"
fi

echo "=== NUMBERED LEGACY ADAPTER INVENTORY ===" | tee "$OUT/08_legacy_adapter_inventory_numbered.txt"
if [[ -f "$INV" ]]; then
  nl -ba "$INV" | tee -a "$OUT/08_legacy_adapter_inventory_numbered.txt"
else
  echo "MISSING: $INV" | tee -a "$OUT/08_legacy_adapter_inventory_numbered.txt"
fi

echo "=== KEYWORD GREP ACROSS ALL PHASE45b OUTPUTS ===" | tee "$OUT/09_keyword_grep_all_phase45b_outputs.txt"
grep -RniE \
  'legacy|adapter|guarded|delete|candidate|chain|transitive|liveness|retire|retirement' \
  "$PHASE45B_OUT" \
  2>/dev/null \
  | tee -a "$OUT/09_keyword_grep_all_phase45b_outputs.txt" || true

echo "=== LEGACY-ADAPTER-FOCUSED PHASE45b ARTIFACT MATCHES ===" | tee "$OUT/10_legacy_adapter_focused_artifact_matches.txt"
find "$PHASE45B_OUT" -maxdepth 1 -type f \
  | sort \
  | while IFS= read -r f; do
      if grep -qiE 'legacy|adapter|guarded|delete|candidate|chain' "$f" 2>/dev/null; then
        echo "----- FILE: $f -----"
        grep -niE 'legacy|adapter|guarded|delete|candidate|chain' "$f" || true
        echo
      fi
    done \
  | tee -a "$OUT/10_legacy_adapter_focused_artifact_matches.txt"

echo "=== PHASE45b SCRIPT STRUCTURE HITS ===" | tee "$OUT/11_phase45b_script_structure_hits.txt"
grep -nE \
  'legacy_adapter|legacy adapter|guarded-delete|guarded delete|candidate chains|07_legacy_adapter|transitive_liveness_inventory|candidate_chain' \
  "$PHASE45B_SCRIPT" \
  | tee -a "$OUT/11_phase45b_script_structure_hits.txt" || true

python3 - "$PHASE45B_SCRIPT" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

script = Path(sys.argv[1])
out = Path(sys.argv[2])

lines = script.read_text(encoding="utf-8").splitlines()

needles = [
    "07_legacy_adapter_chain_transitive_liveness_inventory",
    "Legacy adapter guarded-delete candidate chains",
    "candidate chains",
    "legacy adapter",
    "legacy_adapter",
    "guarded-delete",
    "transitive_liveness",
]

hit_lines = []
for i, line in enumerate(lines, start=1):
    low = line.lower()
    if any(n.lower() in low for n in needles):
        hit_lines.append(i)

windows = []
seen = set()

for hit in hit_lines:
    start = max(1, hit - 12)
    end = min(len(lines), hit + 20)
    key = (start, end)
    if key in seen:
        continue
    seen.add(key)

    windows.append("=" * 140)
    windows.append(f"SCRIPT WINDOW {start}-{end} | trigger_line={hit}")
    windows.append("=" * 140)

    for lineno in range(start, end + 1):
        windows.append(f"{lineno:>6}: {lines[lineno - 1]}")
    windows.append("")

(out / "12_phase45b_script_generation_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

print("PHASE54C_SCRIPT_WINDOW_CAPTURE_OK")
print(f"PHASE45B_SCRIPT_TRIGGER_HITS={len(hit_lines)}")
PY

echo "=== PHASE45b SCRIPT GENERATION WINDOWS ===" | tee "$OUT/13_phase45b_script_generation_windows_console.txt"
cat "$OUT/12_phase45b_script_generation_windows.txt" \
  | tee -a "$OUT/13_phase45b_script_generation_windows_console.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

out = Path(sys.argv[1])

status = (out / "06_legacy_adapter_inventory_file_status.txt").read_text(encoding="utf-8")
raw = (out / "07_legacy_adapter_inventory_raw.txt").read_text(encoding="utf-8")
grep_all = (out / "09_keyword_grep_all_phase45b_outputs.txt").read_text(encoding="utf-8")
focused = (out / "10_legacy_adapter_focused_artifact_matches.txt").read_text(encoding="utf-8")
script_windows = (out / "12_phase45b_script_generation_windows.txt").read_text(encoding="utf-8")

m_bytes = re.search(r"bytes=(\d+)", status)
m_lines = re.search(r"lines=(\d+)", status)

byte_count = int(m_bytes.group(1)) if m_bytes else -1
line_count = int(m_lines.group(1)) if m_lines else -1

raw_effective = [
    line for line in raw.splitlines()
    if line.strip()
    and not line.startswith("=== RAW LEGACY ADAPTER INVENTORY ===")
]

raw_nonempty_lines = len(raw_effective)

keyword_hit_count = sum(
    1 for line in grep_all.splitlines()
    if ":" in line and not line.startswith("=== ")
)

focused_has_hits = "----- FILE:" in focused
script_has_windows = "SCRIPT WINDOW" in script_windows

digest = [
    "=== PHASE 54c DIGEST ===",
    "Router compile: PASS",
    "Phase45b refresh: PASS",
    f"Legacy inventory byte count: {byte_count}",
    f"Legacy inventory line count: {line_count}",
    f"Legacy inventory non-empty content lines captured: {raw_nonempty_lines}",
    f"Keyword grep hits across Phase45b artifacts: {keyword_hit_count}",
    f"Focused artifact keyword hits present: {focused_has_hits}",
    f"Phase45b script generation windows captured: {script_has_windows}",
    "",
]

if raw_nonempty_lines == 0:
    digest.extend([
        "Conclusion:",
        "The specific Phase45b legacy-adapter inventory artifact is effectively empty.",
        "Phase45b reports 4 candidate chains in its digest, but its designated",
        "inventory file is not carrying those candidate details.",
        "",
        "That strongly suggests a Phase45b audit-emission defect, not a parser defect.",
    ])
else:
    digest.extend([
        "Conclusion:",
        "The legacy-adapter inventory file contains real content.",
        "Its exact structure is now captured and can be parsed precisely in Phase54d.",
    ])

digest.extend([
    "",
    "Review:",
    "- 07_legacy_adapter_inventory_raw.txt",
    "- 08_legacy_adapter_inventory_numbered.txt",
    "- 09_keyword_grep_all_phase45b_outputs.txt",
    "- 10_legacy_adapter_focused_artifact_matches.txt",
    "- 12_phase45b_script_generation_windows.txt",
])

(out / "14_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
print()
print(f"PHASE54C_OUT={out}")
PY

echo
echo "PHASE54C_OUT=$OUT"
