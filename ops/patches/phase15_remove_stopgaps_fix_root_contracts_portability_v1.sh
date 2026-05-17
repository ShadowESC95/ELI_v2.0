#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase15_remove_stopgaps_fix_root_contracts_portability_${STAMP}"
BACKUP="$OUT/backups"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 15 — Remove Stopgaps, Fix Root Contracts, Portability Cleanup"
echo "ROOT : $ROOT"
echo "OUT  : $OUT"
echo "TIME : $(date -Is)"
echo "======================================================================"
echo

if [ ! -d "$ROOT/eli" ] || [ ! -f "$ROOT/bin/elix" ]; then
  echo "FATAL: not an ELI project root:"
  echo "  $ROOT"
  false
fi

{
  echo "# Phase 15 — Remove Stopgaps, Fix Root Contracts, Portability Cleanup"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- Current shell PYTHONPATH: \`${PYTHONPATH-<unset>}\`"
  echo
} > "$OUT/SUMMARY.md"

echo "=== 0. Backups ==="
for rel in \
  "eli/execution/router_enhanced.py" \
  "eli/kernel/engine.py" \
  "eli/cognition/output_governor.py" \
  "eli/runtime/control_contracts.py" \
  "eli/runtime/deterministic_introspection.py"
do
  SRC="$ROOT/$rel"
  DST="$BACKUP/$rel"
  if [ -f "$SRC" ]; then
    mkdir -p "$(dirname "$DST")"
    cp -a "$SRC" "$DST"
    echo "BACKUP $rel"
  else
    echo "MISSING $rel"
  fi
done

for shellfile in \
  "$HOME/.bashrc" \
  "$HOME/.profile" \
  "$HOME/.bash_profile" \
  "$HOME/.zshrc"
do
  if [ -f "$shellfile" ]; then
    DST="$BACKUP/home/$(basename "$shellfile")"
    mkdir -p "$(dirname "$DST")"
    cp -a "$shellfile" "$DST"
    echo "BACKUP $shellfile"
  fi
done
echo

echo "=== 1. Remove temporary Phase 13B append-only router phrase guard ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/execution/router_enhanced.py"

src = path.read_text(encoding="utf-8")

marker = "# === PHASE13B_V2_APPEND_ONLY_ROUTE_SURFACE_GUARD ==="

if marker in src:
    head = src.split(marker, 1)[0].rstrip() + "\n"
    src = head
    removed_guard = True
else:
    removed_guard = False

# Replace the non-portable active example literal.
src = src.replace(
    "/home/jay/path/File.pdf",
    "<path-to-pdf-file>",
)

path.write_text(src, encoding="utf-8")

report = [
    f"removed_phase13b_router_guard={removed_guard}",
    "replaced_literal=/home/jay/path/File.pdf -> <path-to-pdf-file>",
]
(out / "01_router_cleanup.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
print("\n".join(report))
PY
echo

echo "=== 2. Remove temporary Phase 13 engine META_DIAGNOSTIC veto shim ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/kernel/engine.py"

src = path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

helper_marker = "# === PHASE13_META_DIAGNOSTIC_EXPLICITNESS_GUARD ==="
response_governance_anchor = "# Response governance"
veto_marker = "# === PHASE13_IMPLICIT_META_DIAGNOSTIC_VETO ==="

removed_helper = False
removed_veto_blocks = 0

# ------------------------------------------------------------------
# A. Remove helper function inserted near top of engine.py.
# ------------------------------------------------------------------
if helper_marker in src and response_governance_anchor in src:
    start = src.index(helper_marker)
    end = src.index(response_governance_anchor, start)
    src = src[:start] + src[end:]
    removed_helper = True

# Re-split after helper removal.
lines = src.splitlines(keepends=True)

# ------------------------------------------------------------------
# B. Remove one or more indented veto blocks.
# ------------------------------------------------------------------
def indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

new_lines = []
i = 0

while i < len(lines):
    line = lines[i]

    if veto_marker in line:
        base_indent = indent_width(line)
        removed_veto_blocks += 1
        i += 1

        while i < len(lines):
            current = lines[i]
            stripped = current.strip()

            if not stripped:
                i += 1
                continue

            cur_indent = indent_width(current)

            # Stop when original sibling code resumes.
            if cur_indent <= base_indent:
                break

            i += 1

        continue

    new_lines.append(line)
    i += 1

patched = "".join(new_lines)
path.write_text(patched, encoding="utf-8")

report = [
    f"removed_phase13_engine_helper={removed_helper}",
    f"removed_phase13_engine_veto_blocks={removed_veto_blocks}",
]
(out / "02_engine_cleanup.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
print("\n".join(report))
PY
echo

echo "=== 3. Remove hard-coded Wrong-frame user-visible replacements from output_governor.py ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/cognition/output_governor.py"

src = path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

removed_blocks = 0

def indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

def remove_enclosing_if_block(lines: list[str], hit_index: int) -> tuple[list[str], bool]:
    # Walk upward to nearest preceding `if ...:` at a lower/same indentation scope.
    hit_indent = indent_width(lines[hit_index])
    start = None

    for j in range(hit_index, -1, -1):
        stripped = lines[j].lstrip()
        if stripped.startswith("if ") and stripped.rstrip().endswith(":"):
            start = j
            break

    if start is None:
        return lines, False

    base_indent = indent_width(lines[start])

    end = start + 1
    while end < len(lines):
        current = lines[end]
        stripped = current.strip()

        if not stripped:
            end += 1
            continue

        cur_indent = indent_width(current)
        if cur_indent <= base_indent:
            break
        end += 1

    return lines[:start] + lines[end:], True

while True:
    hit = None
    for idx, line in enumerate(lines):
        if "Wrong frame. You meant surgery on ELI" in line:
            hit = idx
            break

    if hit is None:
        break

    lines, ok = remove_enclosing_if_block(lines, hit)
    if not ok:
        raise SystemExit("PATCH FAILED: found Wrong-frame literal but could not remove enclosing if-block.")
    removed_blocks += 1

# Remove orphaned Phase 13 comment marker if still left behind.
lines = [
    line for line in lines
    if "PHASE13_OUTPUT_GOVERNOR_REPAIR_CONTEXT_GATE" not in line
]

patched = "".join(lines)
path.write_text(patched, encoding="utf-8")

report = [f"removed_wrong_frame_replacement_blocks={removed_blocks}"]
(out / "03_output_governor_cleanup.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
print("\n".join(report))
PY
echo

echo "=== 4. Patch control_contracts.py: remove over-broad META_DIAGNOSTIC catch, keep explicit technical diagnostics ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/runtime/control_contracts.py"

src = path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

marker = "# === PHASE15_REDISTRIBUTABLE_META_DIAGNOSTIC_GATE ==="
if marker in src:
    print("SKIP: Phase 15 control-contract patch already present.")
    (out / "04_control_contracts_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

# Locate old final catch block by comment.
start = None
for i, line in enumerate(lines):
    if "Meta-diagnostic catch:" in line:
        start = i
        break

if start is None:
    raise SystemExit("PATCH FAILED: could not find old Meta-diagnostic catch comment.")

# Find the end after the matching return "META_DIAGNOSTIC".
end = None
for i in range(start, min(len(lines), start + 80)):
    if 'return "META_DIAGNOSTIC"' in lines[i]:
        end = i + 1
        break

if end is None:
    raise SystemExit("PATCH FAILED: could not find return META_DIAGNOSTIC after old catch comment.")

replacement = [
    "    # === PHASE15_REDISTRIBUTABLE_META_DIAGNOSTIC_GATE ===\n",
    "    # Do not convert ordinary conversational confusion into internal diagnostics.\n",
    "    # META_DIAGNOSTIC is reserved for prompts that explicitly refer to ELI's\n",
    "    # response/output/runtime/tooling and ask for fault explanation or tracing.\n",
    "    _eli_phase15_meta_referent = bool(re.search(\n",
    "        r\"\\b(response|answer|output|runtime|pipeline|router|executor|orchestrator|agent|tool|memory|browser|web|online|search|diagnostic|audit|system|eli)\\b\",\n",
    "        low,\n",
    "    ))\n",
    "    _eli_phase15_meta_failure = bool(re.search(\n",
    "        r\"\\b(wrong|broken|failed|failing|failure|issue|problem|root cause|empty|terrible|awful|bad|incorrect|drift|leak|leaking|happening|going on)\\b\",\n",
    "        low,\n",
    "    ))\n",
    "    _eli_phase15_meta_request = bool(re.search(\n",
    "        r\"\\b(debug|diagnose|diagnostic|audit|trace|inspect|explain|why|what)\\b\",\n",
    "        low,\n",
    "    ))\n",
    "    _eli_phase15_browser_fault = bool(re.search(\n",
    "        r\"\\bwhy\\b.{0,80}\\b(browser|web|online|search|youtube)\\b\",\n",
    "        low,\n",
    "    ))\n",
    "\n",
    "    if (\n",
    "        _eli_phase15_browser_fault\n",
    "        or (\n",
    "            _eli_phase15_meta_referent\n",
    "            and _eli_phase15_meta_failure\n",
    "            and _eli_phase15_meta_request\n",
    "        )\n",
    "    ):\n",
    "        return \"META_DIAGNOSTIC\"\n",
]

lines[start:end] = replacement

patched = "".join(lines)
path.write_text(patched, encoding="utf-8")

(out / "04_control_contracts_patch.txt").write_text(
    "PATCHED control_contracts.py: over-broad confusion-to-META_DIAGNOSTIC catch replaced with explicit redistributable diagnostic gate.\n",
    encoding="utf-8",
)

print("PATCHED control_contracts.py")
PY
echo

echo "=== 5. Patch deterministic_introspection.py: general import/dependency/venv diagnostic classifier ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/runtime/deterministic_introspection.py"

src = path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

marker = "# === PHASE15_REDISTRIBUTABLE_IMPORT_VENV_CLASSIFIER ==="
if marker in src:
    print("SKIP: Phase 15 deterministic classifier patch already present.")
    (out / "05_deterministic_classifier_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

# Find the classify_diagnostic_action function.
tree = ast.parse(src)
func = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "classify_diagnostic_action":
        func = node
        break

if func is None or func.end_lineno is None:
    raise SystemExit("PATCH FAILED: could not find classify_diagnostic_action().")

start_idx = func.lineno - 1
end_idx = func.end_lineno

# Within the function, find the old import audit `if re.search(...): return`.
block_start = None
block_end = None

for i in range(start_idx, end_idx):
    if "imports? failing" in lines[i] or "missing imports?" in lines[i]:
        # Walk upward to the `if re.search(` line.
        for j in range(i, max(start_idx - 1, i - 5), -1):
            if lines[j].lstrip().startswith("if re.search("):
                block_start = j
                break
        if block_start is not None:
            break

if block_start is None:
    raise SystemExit("PATCH FAILED: could not find old import-audit classifier block.")

for i in range(block_start, min(end_idx, block_start + 15)):
    if 'return "IMPORT_AUDIT"' in lines[i]:
        block_end = i + 1
        break

if block_end is None:
    raise SystemExit("PATCH FAILED: could not find return IMPORT_AUDIT in old classifier block.")

replacement = [
    "    # === PHASE15_REDISTRIBUTABLE_IMPORT_VENV_CLASSIFIER ===\n",
    "    _eli_phase15_import_subject = bool(re.search(\n",
    "        r\"\\b(imports?|modules?|dependencies?|packages?|virtual environments?|venv|\\.venv|python environment)\\b\",\n",
    "        low,\n",
    "    ))\n",
    "    _eli_phase15_import_request = bool(re.search(\n",
    "        r\"\\b(status|missing|failing|failure|failures|broken|audit|check|inspect|what is|what are|show me|tell me)\\b\",\n",
    "        low,\n",
    "    ))\n",
    "    if _eli_phase15_import_subject and _eli_phase15_import_request:\n",
    "        return \"IMPORT_AUDIT\"\n",
]

lines[block_start:block_end] = replacement

patched = "".join(lines)
path.write_text(patched, encoding="utf-8")

(out / "05_deterministic_classifier_patch.txt").write_text(
    "PATCHED deterministic_introspection.py: IMPORT_AUDIT detection is now generalised for imports/modules/dependencies/venv rather than relying on a narrow phrase list.\n",
    encoding="utf-8",
)

print("PATCHED deterministic_introspection.py")
PY
echo

echo "=== 6. Disable bad global PYTHONPATH startup contamination ==="
python3 - "$OUT" <<'PY'
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

out = Path(sys.argv[1])
home = Path.home()
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

targets = [
    home / ".bashrc",
    home / ".profile",
    home / ".bash_profile",
    home / ".zshrc",
]

seen = []
changed = []

for path in targets:
    if not path.exists() or not path.is_file():
        continue

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    new_lines = []
    touched = False

    for line in lines:
        stripped = line.strip()

        if "PYTHONPATH" in line:
            seen.append(f"{path}: {line}")

        bad_dynamic_pwd = (
            stripped.startswith("export PYTHONPATH=$PWD:")
            or stripped.startswith("PYTHONPATH=$PWD:")
            or stripped.startswith('export PYTHONPATH="$PWD:')
            or stripped.startswith('PYTHONPATH="$PWD:')
        )

        bad_home_bootstrap = (
            (
                stripped.startswith("export PYTHONPATH=")
                or stripped.startswith("PYTHONPATH=")
            )
            and (
                "/home/jay" in stripped
                or "$HOME/Desktop/eli" in stripped
                or "${HOME}/Desktop/eli" in stripped
            )
            and not stripped.startswith("#")
        )

        if bad_dynamic_pwd or bad_home_bootstrap:
            new_lines.append("# PHASE15_DISABLED_GLOBAL_PYTHONPATH_CONTAMINATION " + line)
            touched = True
        else:
            new_lines.append(line)

    if touched:
        backup = path.with_name(path.name + f".bak_phase15_pythonpath_{stamp}")
        shutil.copy2(path, backup)
        path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
        changed.append((str(path), str(backup)))

report = []
report.append("PYTHONPATH lines seen:")
if seen:
    report.extend("  " + s for s in seen)
else:
    report.append("  none")

report.append("")
report.append("Changed:")
if changed:
    for path, backup in changed:
        report.append(f"  COMMENTED contamination in {path}")
        report.append(f"  BACKUP {backup}")
else:
    report.append("  none")

report.append("")
report.append("Run `unset PYTHONPATH` in the current terminal after this script.")
report.append("New terminals should no longer recreate PYTHONPATH=/home/jay: from $PWD.")

text = "\n".join(report) + "\n"
(out / "06_pythonpath_cleanup.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 7. Compile verification ==="
{
  python3 -m py_compile \
    "$ROOT/eli/execution/router_enhanced.py" \
    "$ROOT/eli/kernel/engine.py" \
    "$ROOT/eli/cognition/output_governor.py" \
    "$ROOT/eli/runtime/control_contracts.py" \
    "$ROOT/eli/runtime/deterministic_introspection.py"

  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"

  echo "PY_COMPILE_OK"
  echo "COMPILEALL_OK"
} | tee "$OUT/07_compile.txt"
echo

echo "=== 8. Targeted redistribution-safety behavior probe ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

lines = []

# ------------------------------------------------------------------
# A. Output governor must no longer emit hard-coded Wrong-frame answers.
# ------------------------------------------------------------------
try:
    from eli.cognition.output_governor import repair_local_persona_drift

    result_a = repair_local_persona_drift(
        "The surgeon mentioned the skull in a bad generated sentence.",
        user_input="you alive buddy ?",
    )
    result_b = repair_local_persona_drift(
        "The surgeon mentioned the skull in a bad generated sentence.",
        user_input="did the open-head surgery on your memory/persona work?",
    )

    lines.append("OUTPUT_GOVERNOR normal_prompt_result=" + repr(result_a))
    lines.append("OUTPUT_GOVERNOR repair_prompt_result=" + repr(result_b))
    lines.append("OUTPUT_GOVERNOR wrong_frame_present=" + str(
        "Wrong frame. You meant surgery on ELI" in (str(result_a) + str(result_b))
    ))
except Exception as exc:
    lines.append("OUTPUT_GOVERNOR_PROBE_FAILED=" + repr(exc))

# ------------------------------------------------------------------
# B. Control contract: ordinary confusion remains non-diagnostic.
# ------------------------------------------------------------------
try:
    from eli.runtime.control_contracts import route_control_text

    contract_cases = [
        "what the fuck is happening?",
        "What are you talking about? is that a note to yourself, or me?",
        "what is wrong with your last response?",
        "why did you search the web for that?",
        "run a diagnostic audit of your runtime pipeline",
    ]

    for case in contract_cases:
        action = route_control_text(case, current_action=None)
        lines.append(f"CONTROL case={case!r} action={action!r}")
except Exception as exc:
    lines.append("CONTROL_CONTRACT_PROBE_FAILED=" + repr(exc))

# ------------------------------------------------------------------
# C. Deterministic diagnostic classifier: import/venv is generic, not one-off.
# ------------------------------------------------------------------
try:
    from eli.runtime.deterministic_introspection import classify_diagnostic_action

    diag_cases = [
        "what is the status of missing imports and virtual environments?",
        "check package dependencies and modules",
        "is the venv missing?",
        "hello there",
    ]

    for case in diag_cases:
        action = classify_diagnostic_action(case)
        lines.append(f"DIAG_CLASSIFIER case={case!r} action={action!r}")
except Exception as exc:
    lines.append("DIAG_CLASSIFIER_PROBE_FAILED=" + repr(exc))

# ------------------------------------------------------------------
# D. Verify no exact /home/jay source literals remain in eli/.
# ------------------------------------------------------------------
matches = []
for path in sorted((root / "eli").rglob("*.py")):
    text = path.read_text(encoding="utf-8", errors="replace")
    if "/home/jay" in text:
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "/home/jay" in line:
                matches.append(f"{path.relative_to(root)}:{lineno}:{line.strip()}")

lines.append("EXACT_HOME_JAY_SOURCE_MATCH_COUNT=" + str(len(matches)))
for match in matches[:50]:
    lines.append("EXACT_HOME_JAY_SOURCE_MATCH " + match)

text = "\n".join(lines) + "\n"
(out / "08_behavior_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 9. Portability classification audit for remaining /home/ source lines ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

records = []

for path in sorted((root / "eli").rglob("*.py")):
    rel = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8", errors="replace")

    for lineno, line in enumerate(text.splitlines(), start=1):
        if "/home/" not in line:
            continue

        stripped = line.strip()

        if "/home/jay" in stripped:
            cls = "NONPORTABLE_EXACT_USER_PATH"
        elif (
            "re.compile" in stripped
            or "_RX" in stripped
            or "_RE" in stripped
            or "regex" in stripped.lower()
            or "Redact" in stripped
            or "redact" in stripped
            or stripped.startswith("#")
        ):
            cls = "LIKELY_PATH_DETECTOR_OR_COMMENT"
        else:
            cls = "REVIEW_GENERIC_HOME_LITERAL"

        records.append({
            "file": rel,
            "line": lineno,
            "classification": cls,
            "text": stripped[:320],
        })

(out / "09_home_path_portability_audit.json").write_text(
    json.dumps(records, indent=2),
    encoding="utf-8",
)

counts = {}
for record in records:
    counts[record["classification"]] = counts.get(record["classification"], 0) + 1

summary = ["Portability classification counts:"]
for key in sorted(counts):
    summary.append(f"  {key}: {counts[key]}")

summary.append("")
for record in records:
    summary.append(
        f"{record['classification']} {record['file']}:{record['line']} {record['text']}"
    )

text = "\n".join(summary) + "\n"
(out / "09_home_path_portability_audit.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 10. Startup PYTHONPATH status after cleanup ==="
{
  echo "Current terminal PYTHONPATH=${PYTHONPATH-<unset>}"
  echo
  echo "Startup-file PYTHONPATH lines:"
  grep -RIn --color=never 'PYTHONPATH' \
    "$HOME/.bashrc" \
    "$HOME/.profile" \
    "$HOME/.bash_profile" \
    "$HOME/.zshrc" \
    2>/dev/null || true
} | tee "$OUT/10_pythonpath_status.txt"
echo

echo "=== 11. Git diff ==="
{
  git diff --stat 2>/dev/null || true
  echo
  git diff -- \
    eli/execution/router_enhanced.py \
    eli/kernel/engine.py \
    eli/cognition/output_governor.py \
    eli/runtime/control_contracts.py \
    eli/runtime/deterministic_introspection.py \
    2>/dev/null || true
} > "$OUT/11_patch_diff.txt"

{
  echo "## Repairs performed"
  echo
  echo "1. Removed the temporary Phase 13B phrase-specific router wrapper."
  echo "2. Removed the temporary Phase 13 engine META_DIAGNOSTIC veto shim."
  echo "3. Removed hard-coded Wrong-frame user-visible replacement responses from output_governor.py."
  echo "4. Replaced the broad confusion→META_DIAGNOSTIC catch with a redistributable explicit diagnostic gate in control_contracts.py."
  echo "5. Generalised deterministic import/dependency/venv detection in deterministic_introspection.py."
  echo "6. Replaced the exact /home/jay/path/File.pdf router literal with a portable placeholder."
  echo "7. Disabled bad global PYTHONPATH startup contamination, including export PYTHONPATH=\$PWD:\$PYTHONPATH."
  echo "8. Compiled and probed the resulting behavior."
  echo
  echo "## Read these first"
  echo
  echo "- \`07_compile.txt\`"
  echo "- \`08_behavior_probe.txt\`"
  echo "- \`09_home_path_portability_audit.txt\`"
  echo "- \`10_pythonpath_status.txt\`"
  echo "- \`11_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 15 COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/08_behavior_probe.txt"
echo "  $OUT/09_home_path_portability_audit.txt"
echo "======================================================================"
