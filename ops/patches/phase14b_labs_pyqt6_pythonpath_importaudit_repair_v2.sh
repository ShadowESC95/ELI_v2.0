#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase14b_labs_pyqt6_pythonpath_importaudit_repair_${STAMP}"
BACKUP="$OUT/backups"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 14B — Labs PyQt6 + PYTHONPATH + IMPORT_AUDIT Repair"
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
  echo "# Phase 14B — Labs PyQt6 + PYTHONPATH + IMPORT_AUDIT Repair"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- Current shell PYTHONPATH before script: \`${PYTHONPATH-<unset>}\`"
  echo
} > "$OUT/SUMMARY.md"

echo "=== 0. Backups ==="
for rel in \
  "eli/gui/labs_tab.py" \
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

if [ -d "$HOME/.config/environment.d" ]; then
  mkdir -p "$BACKUP/home/.config/environment.d"
  find "$HOME/.config/environment.d" -maxdepth 1 -type f -name '*.conf' \
    -exec cp -a '{}' "$BACKUP/home/.config/environment.d/" ';' 2>/dev/null || true
  echo "BACKUP ~/.config/environment.d/*.conf where present"
fi
echo

echo "=== 1. Confirm precise PyQt6 QFileSystemModel import fault ==="
env -u PYTHONPATH python3 - "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

out = Path(sys.argv[1])
lines = []

try:
    from PyQt6.QtWidgets import QFileSystemModel as _QFSM_W
    lines.append("PYQT6_QFILESYSTEMMODEL_FROM_QTWIDGETS=OK")
except Exception as exc:
    lines.append("PYQT6_QFILESYSTEMMODEL_FROM_QTWIDGETS=FAIL")
    lines.append(f"  {type(exc).__name__}: {exc}")

try:
    from PyQt6.QtGui import QFileSystemModel as _QFSM_G
    lines.append("PYQT6_QFILESYSTEMMODEL_FROM_QTGUI=OK")
except Exception as exc:
    lines.append("PYQT6_QFILESYSTEMMODEL_FROM_QTGUI=FAIL")
    lines.append(f"  {type(exc).__name__}: {exc}")

text = "\n".join(lines) + "\n"
(out / "01_pyqt6_qfilesystemmodel_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 2. Patch labs_tab.py robustly: keep PyQt6, import QFileSystemModel from QtGui fallback ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/gui/labs_tab.py"

src = path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

marker = "# === PHASE14B_LABS_PYQT6_QFILESYSTEMMODEL_COMPAT ==="
if marker in src:
    print("SKIP: Labs Phase 14B patch already present.")
    (out / "02_labs_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

# Find the PyQt6 branch that Phase 13 created.
branch_idx = None
for i, line in enumerate(lines):
    if 'if _eli_qt_candidate == "PyQt6":' in line:
        branch_idx = i
        break

if branch_idx is None:
    raise SystemExit('PATCH FAILED: could not find `if _eli_qt_candidate == "PyQt6":` in labs_tab.py.')

# Find the PyQt6 QtWidgets grouped import within the branch.
widgets_start = None
for i in range(branch_idx, min(len(lines), branch_idx + 120)):
    if "from PyQt6.QtWidgets import (" in lines[i]:
        widgets_start = i
        break

if widgets_start is None:
    raise SystemExit("PATCH FAILED: could not find PyQt6.QtWidgets grouped import in Labs PyQt6 branch.")

# Find the end of that grouped import.
widgets_end = None
for i in range(widgets_start + 1, min(len(lines), widgets_start + 120)):
    if lines[i].strip() == ")":
        widgets_end = i
        break

if widgets_end is None:
    raise SystemExit("PATCH FAILED: could not find closing ')' for PyQt6 QtWidgets grouped import.")

# Remove QFileSystemModel from that grouped QtWidgets import.
removed = False
new_block = []
for line in lines[widgets_start:widgets_end + 1]:
    if "QFileSystemModel" in line:
        stripped = line.strip()
        if stripped in {"QFileSystemModel,", "QFileSystemModel"}:
            removed = True
            continue
        replaced = line.replace("QFileSystemModel, ", "")
        replaced = replaced.replace(", QFileSystemModel", "")
        replaced = replaced.replace("QFileSystemModel,", "")
        replaced = replaced.replace("QFileSystemModel", "")
        new_block.append(replaced)
        removed = True
    else:
        new_block.append(line)

if not removed:
    raise SystemExit("PATCH FAILED: PyQt6 QtWidgets block did not contain QFileSystemModel.")

lines[widgets_start:widgets_end + 1] = new_block

# Recompute the branch window after the line deletion.
# Find the PyQt6.QtCore import line and insert compatibility import directly before it.
core_idx = None
for i in range(branch_idx, min(len(lines), branch_idx + 140)):
    if "from PyQt6.QtCore import" in lines[i]:
        core_idx = i
        break

if core_idx is None:
    raise SystemExit("PATCH FAILED: could not find PyQt6.QtCore import line after QtWidgets block.")

indent = lines[core_idx][:len(lines[core_idx]) - len(lines[core_idx].lstrip())]

compat = [
    f"{indent}{marker}\n",
    f"{indent}# PyQt6 on this machine exposes QFileSystemModel through QtGui,\n",
    f"{indent}# not QtWidgets. Do not let that import miss force Labs to PyQt5.\n",
    f"{indent}try:\n",
    f"{indent}    from PyQt6.QtWidgets import QFileSystemModel\n",
    f"{indent}except ImportError:\n",
    f"{indent}    from PyQt6.QtGui import QFileSystemModel\n",
]

lines[core_idx:core_idx] = compat

patched = "".join(lines)
path.write_text(patched, encoding="utf-8")

(out / "02_labs_patch.txt").write_text(
    "PATCHED labs_tab.py: PyQt6 branch no longer fails on QFileSystemModel from QtWidgets; QtGui fallback inserted.\n",
    encoding="utf-8",
)

print("PATCHED labs_tab.py")
PY
echo

echo "=== 3. Remove startup-file PYTHONPATH=/home/jay style contamination ==="
python3 - "$OUT" <<'PY'
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

out = Path(sys.argv[1])
home = Path.home()
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

candidates = [
    home / ".bashrc",
    home / ".profile",
    home / ".bash_profile",
    home / ".zshrc",
]

envd = home / ".config" / "environment.d"
if envd.exists():
    candidates.extend(sorted(envd.glob("*.conf")))

seen = []
changed = []

for path in candidates:
    if not path.exists() or not path.is_file():
        continue

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    new_lines = []
    touched = False

    for line in lines:
        stripped = line.strip()
        is_assignment = (
            stripped.startswith("PYTHONPATH=")
            or stripped.startswith("export PYTHONPATH=")
        )

        mentions_bad_home = (
            "/home/jay" in line
            or "$HOME" in line
            or "${HOME}" in line
        )

        if "PYTHONPATH" in line:
            seen.append(f"{path}: {line}")

        if is_assignment and mentions_bad_home and not stripped.startswith("#"):
            new_lines.append("# PHASE14B_DISABLED_BAD_GLOBAL_PYTHONPATH " + line)
            touched = True
        else:
            new_lines.append(line)

    if touched:
        backup = path.with_name(path.name + f".bak_phase14b_pythonpath_{stamp}")
        shutil.copy2(path, backup)
        path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
        changed.append((str(path), str(backup)))

report = []
report.append("PYTHONPATH lines seen in startup files:")
if seen:
    report.extend("  " + x for x in seen)
else:
    report.append("  none")

report.append("")
report.append("Files changed:")
if changed:
    for path, backup in changed:
        report.append(f"  COMMENTED bad global PYTHONPATH in {path}")
        report.append(f"  BACKUP {backup}")
else:
    report.append("  none")

report.append("")
report.append("Current terminal note:")
report.append("  This script cannot mutate the environment of the shell that invoked it.")
report.append("  Run `unset PYTHONPATH` in the current terminal, or open a new terminal.")

text = "\n".join(report) + "\n"
(out / "03_pythonpath_cleanup.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 4. Upgrade deterministic IMPORT_AUDIT with venv/package environment evidence ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/runtime/deterministic_introspection.py"

src = path.read_text(encoding="utf-8")

marker = "# === PHASE14B_IMPORT_AUDIT_VENV_PACKAGE_EVIDENCE ==="
if marker in src:
    print("SKIP: IMPORT_AUDIT venv/package patch already present.")
    (out / "04_import_audit_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

tree = ast.parse(src)
target = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_import_audit":
        target = node
        break

if target is None:
    raise SystemExit("PATCH FAILED: could not find top-level _import_audit().")

if target.end_lineno is None:
    raise SystemExit("PATCH FAILED: Python AST did not provide end_lineno for _import_audit().")

lines = src.splitlines(keepends=True)
start = target.lineno - 1
end = target.end_lineno

replacement = r'''def _import_audit() -> str:
    # === PHASE14B_IMPORT_AUDIT_VENV_PACKAGE_EVIDENCE ===
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    venv_dir = project_root / ".venv"

    venv_python_candidates = [
        venv_dir / "bin" / "python",
        venv_dir / "bin" / "python3",
    ]
    venv_python = next((p for p in venv_python_candidates if p.exists()), None)

    venv_python_version = ""
    if venv_python is not None:
        try:
            venv_python_version = subprocess.check_output(
                [str(venv_python), "--version"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=4,
            ).strip()
        except Exception as exc:
            venv_python_version = f"ERROR: {type(exc).__name__}: {exc}"

    modules = [
        "eli.kernel.engine",
        "eli.execution.router_enhanced",
        "eli.execution.executor_enhanced",
        "eli.execution.portable_intent_contract",
        "eli.system.portable_app_control",
        "eli.cognition.gguf_inference",
        "eli.cognition.orchestrator",
        "eli.cognition.context_synthesiser",
        "eli.cognition.response_governance",
        "eli.memory.memory_truth",
        "eli.runtime.truth_report",
    ]

    requirement_files = [
        str(p.relative_to(project_root))
        for p in sorted(project_root.glob("requirements*.txt"))
    ]
    if (project_root / "pyproject.toml").exists():
        requirement_files.append("pyproject.toml")

    payload = {
        "surface": "import_audit_evidence",
        "modules": {mod: _module_status(mod) for mod in modules},
        "environment": {
            "project_root": str(project_root),
            "sys_executable": str(sys.executable),
            "sys_python_version": sys.version.split()[0],
            "virtual_env_env": os.environ.get("VIRTUAL_ENV", ""),
            "pythonpath_env": os.environ.get("PYTHONPATH", ""),
            "venv_dir": str(venv_dir),
            "venv_exists": venv_dir.exists(),
            "venv_python_exists": venv_python is not None,
            "venv_python": str(venv_python) if venv_python is not None else "",
            "venv_python_version": venv_python_version,
            "requirements_files": requirement_files,
        },
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        indent=2,
    )
'''

lines[start:end] = [replacement + "\n"]
patched = "".join(lines)

path.write_text(patched, encoding="utf-8")

(out / "04_import_audit_patch.txt").write_text(
    "PATCHED deterministic_introspection.py: IMPORT_AUDIT now includes virtual environment and package-state evidence.\n",
    encoding="utf-8",
)

print("PATCHED deterministic_introspection.py")
PY
echo

echo "=== 5. Compile verification ==="
{
  python3 -m py_compile \
    "$ROOT/eli/gui/labs_tab.py" \
    "$ROOT/eli/runtime/deterministic_introspection.py"

  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"

  echo "PY_COMPILE_OK"
  echo "COMPILEALL_OK"
} | tee "$OUT/05_compile.txt"
echo

echo "=== 6. Post-patch Labs + IMPORT_AUDIT targeted probe ==="
QT_QPA_PLATFORM=offscreen env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

lines = []

# ------------------------------------------------------------
# A. Main GUI vs Labs Qt binding alignment.
# ------------------------------------------------------------
try:
    from eli.gui import eli_pro_audio_gui_MKI as gui_mod
    from eli.gui import labs_tab as labs_mod

    gui_qt = getattr(gui_mod, "QT_API", None)
    labs_qt = getattr(labs_mod, "_QT", None)
    qt_errors = getattr(labs_mod, "_QT_ERRORS", [])

    lines.append(f"QT_BINDING gui={gui_qt!r} labs={labs_qt!r}")
    lines.append("QT_BINDING aligned=" + str(gui_qt == labs_qt))
    lines.append("LABS_QT_ERRORS=" + repr(qt_errors))
except Exception as exc:
    lines.append("QT_BINDING_PROBE_FAILED=" + repr(exc))

# ------------------------------------------------------------
# B. IMPORT_AUDIT now includes venv/package truth.
# ------------------------------------------------------------
try:
    from eli.runtime.deterministic_introspection import handle_diagnostic_action

    raw = handle_diagnostic_action(
        "IMPORT_AUDIT",
        "what is the status of missing imports and virtual environments?",
        engine=None,
    )
    payload = json.loads(raw)
    env = payload.get("environment", {})

    lines.append("IMPORT_AUDIT surface=" + repr(payload.get("surface")))
    lines.append("IMPORT_AUDIT venv_exists=" + repr(env.get("venv_exists")))
    lines.append("IMPORT_AUDIT venv_python_exists=" + repr(env.get("venv_python_exists")))
    lines.append("IMPORT_AUDIT sys_executable=" + repr(env.get("sys_executable")))
    lines.append("IMPORT_AUDIT pythonpath_env=" + repr(env.get("pythonpath_env")))
    lines.append("IMPORT_AUDIT requirements_files=" + repr(env.get("requirements_files")))
except Exception as exc:
    lines.append("IMPORT_AUDIT_PROBE_FAILED=" + repr(exc))

text = "\n".join(lines) + "\n"
(out / "06_targeted_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 7. Status snapshot ==="
{
  echo "Current terminal PYTHONPATH=${PYTHONPATH-<unset>}"
  echo
  echo "Startup-file PYTHONPATH occurrences after cleanup:"
  grep -RIn --color=never 'PYTHONPATH' \
    "$HOME/.bashrc" \
    "$HOME/.profile" \
    "$HOME/.bash_profile" \
    "$HOME/.zshrc" \
    "$HOME/.config/environment.d" \
    2>/dev/null || true
  echo
  echo ".venv status:"
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "FOUND $ROOT/.venv/bin/python"
  else
    echo "MISSING $ROOT/.venv/bin/python"
  fi
  echo
  echo "Embedder status:"
  EMBED="$ROOT/models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
  if [ -f "$EMBED" ]; then
    echo "FOUND $EMBED"
  else
    echo "MISSING $EMBED"
  fi
} | tee "$OUT/07_status_snapshot.txt"
echo

echo "=== 8. Git diff ==="
{
  git diff --stat 2>/dev/null || true
  echo
  git diff -- \
    eli/gui/labs_tab.py \
    eli/runtime/deterministic_introspection.py \
    2>/dev/null || true
} > "$OUT/08_patch_diff.txt"

{
  echo "## Repairs performed"
  echo
  echo "1. Patched Labs PyQt6 compatibility using the real on-disk block structure."
  echo "2. Prevented PyQt6 QFileSystemModel import failure from causing silent PyQt5 fallback."
  echo "3. Commented active startup-file PYTHONPATH assignments that inject /home/jay or \$HOME."
  echo "4. Upgraded deterministic IMPORT_AUDIT with venv/PYTHONPATH/package-state evidence."
  echo "5. Recompiled affected files and ran targeted verification probes."
  echo
  echo "## Read these first"
  echo
  echo "- \`01_pyqt6_qfilesystemmodel_probe.txt\`"
  echo "- \`05_compile.txt\`"
  echo "- \`06_targeted_probe.txt\`"
  echo "- \`07_status_snapshot.txt\`"
  echo "- \`08_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 14B COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/06_targeted_probe.txt"
echo "  $OUT/07_status_snapshot.txt"
echo "======================================================================"
