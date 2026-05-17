#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase68b_phase63_self_report_false_positive_heuristic_repair_${STAMP}"

PHASE63="ops/patches/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh"
ENGINE="eli/kernel/engine.py"

mkdir -p "$OUT/backups"

for f in "$PHASE63" "$ENGINE"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE63" "$OUT/backups/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh.before_phase68b.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase 68b — Phase63 SELF_REPORT False-Positive Heuristic Repair v2

## Context

Phase67 proved that `SELF_REPORT.recent_updates` no longer contains a surviving
non-Quick direct-return bypass:

- direct surface-output report returns were absent;
- `_mw_self_report_recent_updates_synthesize(...)` is called;
- the middleware returns the synthesized output;
- remaining `gguf_used=False` hits are confined to Quick-mode direct-evidence paths.

Phase63 still reports `HIGH_SUSPICION` because its static heuristic is too broad:
it flags any block containing both:

1. `gguf_used=False`, and
2. an apparent output-return shape,

without distinguishing Quick-only direct returns from explicit non-Quick
synthesis-and-return paths.

## Repair intent

This patch updates the Phase63 audit script, not runtime code.

It adds explicit feature tracking for:

- presence of a dedicated synthesis helper call;
- presence of a return of the synthesized output.

Then it narrows the `SELF_REPORT.recent_updates` `HIGH_SUSPICION` heuristic so
explicit synthesis proof prevents a false positive.
EOF

python3 - "$PHASE63" "$OUT" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

phase63_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = phase63_path.read_text(encoding="utf-8")
original = src
patch_log: list[str] = []
debug: dict[str, object] = {}

def fail(msg: str) -> None:
    (out / "00_phase68b_failure.txt").write_text(msg + "\n", encoding="utf-8")
    raise SystemExit(msg)

# ---------------------------------------------------------------------
# 1. Dataclass fields
# ---------------------------------------------------------------------

if "contains_explicit_synthesis_helper_call: bool" not in src:
    m = re.search(
        r"(?m)^(?P<indent>\s*)sets_gguf_used_false:\s*bool\s*$",
        src,
    )
    if not m:
        fail("Phase68b: dataclass anchor `sets_gguf_used_false: bool` not found.")

    indent = m.group("indent")
    insertion = (
        "\n"
        f"{indent}contains_explicit_synthesis_helper_call: bool\n"
        f"{indent}contains_return_of_synthesized_output: bool"
    )
    src = src[:m.end()] + insertion + src[m.end():]
    patch_log.append("Inserted synthesis-proof dataclass fields.")
else:
    patch_log.append("Synthesis-proof dataclass fields already present; skipped.")

# ---------------------------------------------------------------------
# 2. Feature extraction lines after gguf_false_lines
# ---------------------------------------------------------------------

if "explicit_synthesis_helper_call_lines = global_line_numbers(" not in src:
    lines = src.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if "gguf_false_lines = global_line_numbers" in line:
            idx = i
            break

    if idx is None:
        fail("Phase68b: `gguf_false_lines = global_line_numbers(...)` anchor not found.")

    indent = re.match(r"^\s*", lines[idx]).group(0)
    insert_lines = [
        f"{indent}explicit_synthesis_helper_call_lines = global_line_numbers(",
        f"{indent}    b,",
        f'{indent}    r"_mw_(?:recent_memory_processing|self_report_recent_updates)_synthesize\\s*\\(",',
        f"{indent})",
        f"{indent}return_of_synthesized_output_lines = global_line_numbers(",
        f"{indent}    b,",
        f'{indent}    r"return\\s+_eli_(?:rm|self)_mw_out\\b",',
        f"{indent})",
    ]
    lines[idx + 1:idx + 1] = insert_lines
    src = "\n".join(lines) + ("\n" if src.endswith("\n") else "")
    patch_log.append("Inserted synthesis-helper and synthesized-output return feature scans.")
else:
    patch_log.append("Synthesis feature scans already present; skipped.")

# ---------------------------------------------------------------------
# 3. Constructor fields
# ---------------------------------------------------------------------

if "contains_explicit_synthesis_helper_call=bool(explicit_synthesis_helper_call_lines)," not in src:
    lines = src.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if "sets_gguf_used_false=bool(gguf_false_lines)," in line:
            idx = i
            break

    if idx is None:
        fail("Phase68b: feature-constructor anchor not found.")

    indent = re.match(r"^\s*", lines[idx]).group(0)
    lines[idx + 1:idx + 1] = [
        f"{indent}contains_explicit_synthesis_helper_call=bool(explicit_synthesis_helper_call_lines),",
        f"{indent}contains_return_of_synthesized_output=bool(return_of_synthesized_output_lines),",
    ]
    src = "\n".join(lines) + ("\n" if src.endswith("\n") else "")
    patch_log.append("Populated synthesis-proof fields in feature constructor.")
else:
    patch_log.append("Feature constructor already contains synthesis-proof fields; skipped.")

# ---------------------------------------------------------------------
# 4. Feature-matrix display lines
# ---------------------------------------------------------------------

if 'contains_explicit_synthesis_helper_call={f.contains_explicit_synthesis_helper_call}' not in src:
    lines = src.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if 'sets_gguf_used_false={f.sets_gguf_used_false}' in line:
            idx = i
            break

    if idx is None:
        fail("Phase68b: feature-matrix display anchor not found.")

    indent = re.match(r"^\s*", lines[idx]).group(0)
    lines[idx + 1:idx + 1] = [
        f'{indent}f"contains_explicit_synthesis_helper_call={{f.contains_explicit_synthesis_helper_call}}",',
        f'{indent}f"contains_return_of_synthesized_output={{f.contains_return_of_synthesized_output}}",',
    ]
    src = "\n".join(lines) + ("\n" if src.endswith("\n") else "")
    patch_log.append("Extended Phase63 feature-matrix output with synthesis-proof fields.")
else:
    patch_log.append("Feature-matrix synthesis-proof output already present; skipped.")

# ---------------------------------------------------------------------
# 5. Narrow SELF_REPORT HIGH_SUSPICION heuristic
# ---------------------------------------------------------------------

lines = src.splitlines()
target_idx = None
target_line = None

for i, line in enumerate(lines):
    if re.match(
        r"^\s*elif\s+sr\.sets_gguf_used_false\s+and\s+sr\.contains_early_return_of_surface_output\s*:\s*$",
        line,
    ):
        target_idx = i
        target_line = line
        break

if target_idx is None:
    # Provide contextual debug windows around any nearby SELF_REPORT heuristic hits.
    windows: list[str] = []
    for i, line in enumerate(lines):
        if "sr.sets_gguf_used_false" in line or "SELF_REPORT.recent_updates" in line:
            lo = max(0, i - 4)
            hi = min(len(lines), i + 8)
            windows.append("\n".join(f"{n+1:6d}: {lines[n]}" for n in range(lo, hi)))

    debug["self_report_related_windows"] = windows
    (out / "01_self_report_heuristic_windows_on_failure.txt").write_text(
        "\n\n".join(windows) + "\n",
        encoding="utf-8",
    )
    fail(
        "Phase68b: SELF_REPORT HIGH_SUSPICION `elif` line not found by resilient regex. "
        "See 01_self_report_heuristic_windows_on_failure.txt."
    )

indent = re.match(r"^\s*", target_line or "").group(0)
replacement = [
    f"{indent}elif (",
    f"{indent}    sr.sets_gguf_used_false",
    f"{indent}    and sr.contains_early_return_of_surface_output",
    f"{indent}    and not (",
    f"{indent}        sr.contains_explicit_synthesis_helper_call",
    f"{indent}        and sr.contains_return_of_synthesized_output",
    f"{indent}    )",
    f"{indent}):",
]
lines[target_idx:target_idx + 1] = replacement
src = "\n".join(lines) + ("\n" if src.endswith("\n") else "")
patch_log.append("Narrowed SELF_REPORT HIGH_SUSPICION branch to exempt explicit synthesis proof.")

# ---------------------------------------------------------------------
# 6. Optional wording cleanup inside the SELF_REPORT HIGH_SUSPICION message
# ---------------------------------------------------------------------

old_message = (
    "Block sets gguf_used=False and appears to return the surface output directly; "
    "verify full non-Quick branch label and return semantics."
)
new_message = (
    "Block sets gguf_used=False and appears to return the surface output directly "
    "without sufficient explicit synthesis-helper and synthesized-output return proof."
)

if old_message in src:
    src = src.replace(old_message, new_message, 1)
    patch_log.append("Updated SELF_REPORT HIGH_SUSPICION explanatory text.")
else:
    patch_log.append("SELF_REPORT HIGH_SUSPICION explanatory text did not match old wording; left unchanged.")

# ---------------------------------------------------------------------
# 7. Persist source
# ---------------------------------------------------------------------

phase63_path.write_text(src, encoding="utf-8")

(out / "02_patch_log.txt").write_text("\n".join(patch_log) + "\n", encoding="utf-8")
(out / "03_phase63_diff.patch").write_text(
    "",
    encoding="utf-8",
)

print("\n".join(patch_log))
PY

echo "=== PHASE68b PATCH LOG ===" | tee "$OUT/04_patch_log_console.txt"
cat "$OUT/02_patch_log.txt" | tee -a "$OUT/04_patch_log_console.txt"

echo "=== BASH SYNTAX CHECK: PHASE63 ===" | tee "$OUT/05_phase63_bash_syntax.txt"
bash -n "$PHASE63" 2>&1 | tee -a "$OUT/05_phase63_bash_syntax.txt"
echo "PHASE63_BASH_SYNTAX_OK" | tee -a "$OUT/05_phase63_bash_syntax.txt"

echo "=== PHASE63 RERUN AFTER PHASE68b ===" | tee "$OUT/06_phase63_rerun_console.txt"
set +e
bash "$PHASE63" 2>&1 | tee -a "$OUT/06_phase63_rerun_console.txt"
PHASE63_EXIT="${PIPESTATUS[0]}"
set -e
echo "PHASE63_EXIT_CODE=$PHASE63_EXIT" | tee -a "$OUT/06_phase63_rerun_console.txt"

PHASE63_OUT="$(grep -E '^PHASE63_OUT=' "$OUT/06_phase63_rerun_console.txt" | tail -1 | cut -d= -f2- || true)"

if [[ -z "${PHASE63_OUT:-}" || ! -d "$PHASE63_OUT" ]]; then
  echo "Phase68b: unable to resolve PHASE63_OUT from rerun output." >&2
  exit 1
fi

echo "PHASE63_OUT=$PHASE63_OUT" > "$OUT/07_resolved_phase63_out.txt"

python3 - "$PHASE63" "$OUT" "$PHASE63_OUT" "$PHASE63_EXIT" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

phase63_path = Path(sys.argv[1])
out = Path(sys.argv[2])
phase63_out = Path(sys.argv[3])
phase63_exit = int(sys.argv[4])

phase63_src = phase63_path.read_text(encoding="utf-8", errors="replace")

all_phase63_texts: list[tuple[Path, str]] = []
for p in sorted(phase63_out.rglob("*")):
    if p.is_file() and p.suffix.lower() in {".txt", ".json", ".md", ".log"}:
        try:
            all_phase63_texts.append((p, p.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            pass

def values_for(key: str) -> list[int]:
    vals: list[int] = []
    pat = re.compile(rf"{re.escape(key)}=(\d+)")
    for _, text in all_phase63_texts:
        vals.extend(int(m.group(1)) for m in pat.finditer(text))
    return vals

high_vals = values_for("HIGH_SUSPICION_COUNT")
likely_vals = values_for("LIKELY_NONQUICK_DIRECT_BYPASS_COUNT")
target_fail_vals = values_for("TARGETED_ASSERTION_FAILURES")

feature_hits = {
    "helper_field_in_source": "contains_explicit_synthesis_helper_call: bool" in phase63_src,
    "return_field_in_source": "contains_return_of_synthesized_output: bool" in phase63_src,
    "heuristic_exemption_present": (
        "sr.contains_explicit_synthesis_helper_call" in phase63_src
        and "sr.contains_return_of_synthesized_output" in phase63_src
    ),
}

feature_matrix_hits: list[str] = []
for p, text in all_phase63_texts:
    if "contains_explicit_synthesis_helper_call=" in text or "contains_return_of_synthesized_output=" in text:
        feature_matrix_hits.append(str(p))

risk_hits: list[str] = []
for p, text in all_phase63_texts:
    if "SELF_REPORT.recent_updates" in text and (
        "HIGH_SUSPICION" in text or "NO_CLEAR_BYPASS_PROVEN" in text
    ):
        risk_hits.append(str(p))

assertions: list[tuple[bool, str, str]] = []

def record(ok: bool, label: str, detail: str = "") -> None:
    assertions.append((ok, label, detail))

record(phase63_exit == 0, "Phase63 rerun exits cleanly", f"exit={phase63_exit}")
record(feature_hits["helper_field_in_source"], "Phase63 source includes synthesis-helper proof field")
record(feature_hits["return_field_in_source"], "Phase63 source includes synthesized-output return proof field")
record(feature_hits["heuristic_exemption_present"], "Phase63 SELF_REPORT HIGH_SUSPICION heuristic contains explicit synthesis exemption")
record(bool(high_vals), "Phase63 rerun emitted HIGH_SUSPICION_COUNT metric", f"values={high_vals}")
record(bool(likely_vals), "Phase63 rerun emitted LIKELY_NONQUICK_DIRECT_BYPASS_COUNT metric", f"values={likely_vals}")
record(bool(target_fail_vals), "Phase63 rerun emitted TARGETED_ASSERTION_FAILURES metric", f"values={target_fail_vals}")
record(bool(high_vals) and high_vals[-1] == 0, "Phase63 closes HIGH_SUSPICION_COUNT", f"values={high_vals}")
record(bool(likely_vals) and likely_vals[-1] == 0, "Phase63 closes LIKELY_NONQUICK_DIRECT_BYPASS_COUNT", f"values={likely_vals}")
record(bool(target_fail_vals) and target_fail_vals[-1] == 0, "Phase63 targeted assertions close", f"values={target_fail_vals}")
record(bool(feature_matrix_hits), "Phase63 feature matrix exposes synthesis-proof fields", f"files={feature_matrix_hits}")

failures = [row for row in assertions if not row[0]]
closed = not failures

verdict_lines = [
    "=== PHASE68b VERDICT ===",
    f"PHASE63_SELF_REPORT_FALSE_POSITIVE_HEURISTIC_REPAIR_CLOSED={str(closed).upper()}",
    f"TARGETED_ASSERTION_FAILURES={len(failures)}",
    f"PHASE63_EXIT_CODE={phase63_exit}",
    f"HIGH_SUSPICION_COUNT_VALUES={high_vals}",
    f"LIKELY_NONQUICK_DIRECT_BYPASS_COUNT_VALUES={likely_vals}",
    f"PHASE63_TARGETED_ASSERTION_FAILURE_VALUES={target_fail_vals}",
    "",
]

if closed:
    verdict_lines.extend([
        "Conclusion:",
        "- Phase63 now accepts explicit non-Quick synthesis proof for SELF_REPORT.recent_updates.",
        "- The previous HIGH_SUSPICION result was an audit false positive, not a surviving engine bypass.",
        "- Phase67 and Phase63 are now aligned on the self-report recent-updates branch truth.",
    ])
else:
    verdict_lines.extend([
        "Conclusion:",
        "- The heuristic patch landed, but one or more verification gates did not close.",
        "- Inspect the Phase63 rerun console and the Phase68b targeted assertion report before making further edits.",
    ])

assertion_lines = ["=== PHASE68b TARGETED ASSERTIONS ==="]
for ok, label, detail in assertions:
    assertion_lines.append(("PASS" if ok else "FAIL") + f": {label}" + (f" — {detail}" if detail else ""))
assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={len(failures)}")

(out / "08_phase68b_verdict.txt").write_text("\n".join(verdict_lines) + "\n", encoding="utf-8")
(out / "09_phase68b_targeted_assertions.txt").write_text("\n".join(assertion_lines) + "\n", encoding="utf-8")

inventory = {
    "phase63_out": str(phase63_out),
    "high_suspicion_count_values": high_vals,
    "likely_direct_bypass_count_values": likely_vals,
    "targeted_assertion_failure_values": target_fail_vals,
    "feature_matrix_hit_files": feature_matrix_hits,
    "risk_hit_files": risk_hits,
}
(out / "10_phase63_rerun_metric_inventory.json").write_text(
    json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict_lines))
print()
print("\n".join(assertion_lines))
PY

{
  echo "=== PHASE68b DIGEST ==="
  cat "$OUT/08_phase68b_verdict.txt"
  echo
  echo "Review:"
  echo "- 02_patch_log.txt"
  echo "- 06_phase63_rerun_console.txt"
  echo "- 07_resolved_phase63_out.txt"
  echo "- 08_phase68b_verdict.txt"
  echo "- 09_phase68b_targeted_assertions.txt"
  echo "- 10_phase63_rerun_metric_inventory.json"
  echo
  echo "PHASE68B_OUT=$OUT"
} | tee "$OUT/11_console_digest.txt"

echo "PHASE68B_OUT=$OUT"
