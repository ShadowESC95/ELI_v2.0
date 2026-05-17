#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase14_labs_qt_pythonpath_import_venv_audit_repair_${STAMP}"
BACKUP="$OUT/backups"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 14 — Labs Qt + PYTHONPATH + Import/Venv Audit Repair"
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
  echo "# Phase 14 — Labs Qt + PYTHONPATH + Import/Venv Audit Repair"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- Current PYTHONPATH: \`${PYTHONPATH-<unset>}\`"
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

echo "=== 1. Pre-patch exact Qt import probe ==="
env -u PYTHONPATH python3 - "$OUT" <<'PY'
from __future__ import annotations

import traceback
import sys
from pathlib import Path

out = Path(sys.argv[1])
lines = []

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplitter,
        QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit,
        QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
        QGroupBox, QFormLayout, QComboBox, QCheckBox, QTreeView,
        QFileDialog, QMessageBox, QInputDialog, QScrollArea,
        QFileSystemModel, QHeaderView, QSizePolicy, QFrame,
        QApplication, QProgressBar, QSpinBox, QDoubleSpinBox,
        QAbstractItemView, QStackedWidget,
    )
    lines.append("PYQT6_WIDGETS_BLOCK_WITH_QFILESYSTEMMODEL=OK")
except Exception as exc:
    lines.append("PYQT6_WIDGETS_BLOCK_WITH_QFILESYSTEMMODEL=FAIL")
    lines.append(f"  {type(exc).__name__}: {exc}")

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
(out / "01_prepatch_qt_import_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 2. Patch labs_tab.py PyQt6 QFileSystemModel import compatibility ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/gui/labs_tab.py"

src = path.read_text(encoding="utf-8")

marker = "# === PHASE14_LABS_PYQT6_QFILESYSTEMMODEL_COMPAT ==="

if marker in src:
    print("SKIP: Phase 14 Labs PyQt6 QFileSystemModel patch already present.")
    (out / "02_labs_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

# Remove QFileSystemModel from the explicit PyQt6.QtWidgets grouped import only.
pyqt6_block_re = re.compile(
    r'''(?P<prefix>\s*if _eli_qt_candidate == "PyQt6":\n\s*from PyQt6\.QtWidgets import \(\n)
(?P<body>.*?)
(?P<suffix>\n\s*\)\n\s*from PyQt6\.QtCore import .*?\n\s*from PyQt6\.QtGui import .*?\n\s*_QT = "PyQt6"\n\s*break\n)''',
    re.DOTALL,
)

match = pyqt6_block_re.search(src)
if not match:
    raise SystemExit("PATCH FAILED: could not locate Phase 13 PyQt6 block in labs_tab.py.")

body = match.group("body")
body_new = re.sub(r'(?m)^(\s*)QFileSystemModel,\s*\n', '', body)
body_new = body_new.replace("QFileSystemModel, ", "")
body_new = body_new.replace(", QFileSystemModel", "")

suffix = match.group("suffix")

compat_insert = '''        # === PHASE14_LABS_PYQT6_QFILESYSTEMMODEL_COMPAT ===
        # PyQt6 installations can expose QFileSystemModel through QtGui rather
        # than QtWidgets. Do not let that single import failure silently force
        # the entire Labs tab down to PyQt5, which produces cross-binding QWidget
        # parent errors inside the PyQt6 main GUI.
        try:
            from PyQt6.QtWidgets import QFileSystemModel
        except ImportError:
            from PyQt6.QtGui import QFileSystemModel
'''

# Insert compatibility import before the QtCore import in suffix.
suffix_new = suffix.replace(
    "        from PyQt6.QtCore",
    compat_insert + "        from PyQt6.QtCore",
    1,
)

replacement = match.group("prefix") + body_new + suffix_new
patched = src[:match.start()] + replacement + src[match.end():]

path.write_text(patched, encoding="utf-8")

(out / "02_labs_patch.txt").write_text(
    "PATCHED labs_tab.py: PyQt6 QFileSystemModel now imports from QtWidgets with QtGui fallback.\n",
    encoding="utf-8",
)

print("PATCHED labs_tab.py")
PY
echo

echo "=== 3. Remove global PYTHONPATH=/home/jay style startup contamination ==="
python3 - "$OUT" <<'PY'
from __future__ import annotations

import re
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

pattern = re.compile(
    r"""^\s*
        (?:export\s+)?PYTHONPATH\s*=\s*
        ["']?
        (?:
            /home/jay(?::[^"']*)?
            |\$HOME(?::[^"']*)?
            |\$\{HOME\}(?::[^"']*)?
        )
        ["']?
        \s*$
    """,
    re.VERBOSE,
)

scan_lines = []
changed = []

for path in candidates:
    if not path.exists() or not path.is_file():
        continue

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    new_lines = []
    touched = False

    for line in lines:
        if "PYTHONPATH" in line:
            scan_lines.append(f"{path}: {line}")

        if pattern.match(line):
            new_lines.append("# PHASE14_DISABLED_BAD_GLOBAL_PYTHONPATH " + line)
            touched = True
        else:
            new_lines.append(line)

    if touched:
        backup = path.with_name(path.name + f".bak_phase14_pythonpath_{stamp}")
        shutil.copy2(path, backup)
        path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
        changed.append((str(path), str(backup)))

report = []
report.append("Matched startup-file PYTHONPATH lines:")
if scan_lines:
    report.extend("  " + line for line in scan_lines)
else:
    report.append("  none found")

report.append("")
report.append("Files changed:")
if changed:
    for path, backup in changed:
        report.append(f"  COMMENTED bad PYTHONPATH in {path}")
        report.append(f"  BACKUP {backup}")
else:
    report.append("  none")

report.append("")
report.append("NOTE: the current terminal process still retains its inherited PYTHONPATH until you run:")
report.append("  unset PYTHONPATH")
report.append("or open a fresh terminal.")

text = "\n".join(report) + "\n"
(out / "03_pythonpath_cleanup.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 4. Upgrade deterministic IMPORT_AUDIT to include virtual environment/package truth ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/runtime/deterministic_introspection.py"

src = path.read_text(encoding="utf-8")

marker = "# === PHASE14_IMPORT_AUDIT_VENV_PACKAGE_EVIDENCE ==="

if marker in src:
    print("SKIP: Phase 14 import/venv audit patch already present.")
    (out / "04_import_audit_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

func_re = re.compile(
    r"def _import_audit\(\) -> str:\n(?:    .*\n)+?(?=\n\ndef |\n\nclass |\Z)",
    re.MULTILINE,
)

match = func_re.search(src)
if not match:
    raise SystemExit("PATCH FAILED: could not locate _import_audit() in deterministic_introspection.py.")

replacement = r'''def _import_audit() -> str:
    # === PHASE14_IMPORT_AUDIT_VENV_PACKAGE_EVIDENCE ===
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
        str(path.relative_to(project_root))
        for path in sorted(project_root.glob("requirements*.txt"))
    ]
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
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

patched = src[:match.start()] + replacement + src[match.end():]
path.write_text(patched, encoding="utf-8")

(out / "04_import_audit_patch.txt").write_text(
    "PATCHED deterministic_introspection.py: IMPORT_AUDIT now includes venv/PYTHONPATH/package evidence.\n",
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

echo "=== 6. Post-patch Qt/Labs/ImportAudit targeted probe ==="
QT_QPA_PLATFORM=offscreen env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

lines = []

# A. Exact PyQt6 QFileSystemModel import state.
try:
    from PyQt6.QtWidgets import QFileSystemModel as _QFSM_W
    lines.append("POST_PYQT6_QFILESYSTEMMODEL_FROM_QTWIDGETS=OK")
except Exception as exc:
    lines.append("POST_PYQT6_QFILESYSTEMMODEL_FROM_QTWIDGETS=FAIL")
    lines.append(f"  {type(exc).__name__}: {exc}")

try:
    from PyQt6.QtGui import QFileSystemModel as _QFSM_G
    lines.append("POST_PYQT6_QFILESYSTEMMODEL_FROM_QTGUI=OK")
except Exception as exc:
    lines.append("POST_PYQT6_QFILESYSTEMMODEL_FROM_QTGUI=FAIL")
    lines.append(f"  {type(exc).__name__}: {exc}")

# B. Binding alignment after GUI import.
try:
    from eli.gui import eli_pro_audio_gui_MKI as gui_mod
    from eli.gui import labs_tab as labs_mod

    gui_qt = getattr(gui_mod, "QT_API", None)
    labs_qt = getattr(labs_mod, "_QT", None)

    lines.append(f"QT_BINDING gui={gui_qt!r} labs={labs_qt!r}")
    lines.append("QT_BINDING aligned=" + str(gui_qt == labs_qt))
    lines.append("LABS_QT_ERRORS=" + repr(getattr(labs_mod, "_QT_ERRORS", [])))
except Exception as exc:
    lines.append("QT_BINDING_IMPORT_FAILED=" + repr(exc))

# C. IMPORT_AUDIT payload now includes venv/package environment.
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

echo "=== 7. Structural status snapshot ==="
{
  echo "Current terminal PYTHONPATH=${PYTHONPATH-<unset>}"
  echo
  echo "Startup-file PYTHONPATH occurrences after patch:"
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
  echo "1. Patched Labs PyQt6 import handling so QFileSystemModel no longer forces a fallback to PyQt5."
  echo "2. Commented user-shell startup PYTHONPATH lines that globally inject /home/jay or \$HOME, with timestamped backups."
  echo "3. Upgraded deterministic IMPORT_AUDIT so it reports virtual environment and package-state truth."
  echo "4. Recompiled the affected code and ran targeted probes."
  echo
  echo "## Read these first"
  echo
  echo "- \`01_prepatch_qt_import_probe.txt\`"
  echo "- \`05_compile.txt\`"
  echo "- \`06_targeted_probe.txt\`"
  echo "- \`07_status_snapshot.txt\`"
  echo "- \`08_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 14 COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/06_targeted_probe.txt"
echo "  $OUT/07_status_snapshot.txt"
echo "======================================================================"
