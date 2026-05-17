#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase13_surface_integrity_package_repair_${STAMP}"
BACKUP="$OUT/backups"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 13 — Surface Integrity + Package Repair"
echo "ROOT : $ROOT"
echo "OUT  : $OUT"
echo "TIME : $(date -Is)"
echo "======================================================================"
echo

if [ ! -d "$ROOT/eli" ] || [ ! -f "$ROOT/bin/elix" ]; then
  echo "FATAL: this does not look like an ELI project root:"
  echo "  $ROOT"
  echo "Expected:"
  echo "  eli/"
  echo "  bin/elix"
  return 1 2>/dev/null || exit 1
fi

TARGETS=(
  "eli/cognition/output_governor.py"
  "eli/gui/labs_tab.py"
  "eli/execution/router_enhanced.py"
  "eli/kernel/engine.py"
  "eli/runtime/visible_text.py"
  "eli/gui/eli_pro_audio_gui_MKI.py"
  "config/settings.json"
  ".env.mkxi"
)

echo "=== Backing up target files ==="
for rel in "${TARGETS[@]}"; do
  src="$ROOT/$rel"
  if [ -f "$src" ]; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp -a "$src" "$BACKUP/$rel"
    echo "BACKUP $rel"
  else
    echo "MISSING $rel"
  fi
done
echo

{
  echo "# Phase 13 Surface Integrity + Package Repair"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: $(python3 --version 2>&1)"
  echo "- Git HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo 'no-git-head')"
  echo "- Git branch: $(git branch --show-current 2>/dev/null || echo 'no-branch')"
  echo
} > "$OUT/SUMMARY.md"

echo "=== Environment snapshot ===" | tee "$OUT/01_environment.txt"
{
  echo "PWD=$ROOT"
  echo "PYTHONPATH=${PYTHONPATH-<unset>}"
  echo "VIRTUAL_ENV=${VIRTUAL_ENV-<unset>}"
  echo ".venv exists? $( [ -x "$ROOT/.venv/bin/python" ] && echo yes || echo no )"
  echo
  echo "python3:"
  command -v python3 || true
  python3 --version || true
  echo
  echo "pip:"
  python3 -m pip --version 2>/dev/null || echo "python3 -m pip unavailable"
  echo
  echo "git status:"
  git status --short 2>/dev/null || true
} | tee -a "$OUT/01_environment.txt"
echo

echo "=== Asset/package inventory ===" | tee "$OUT/02_assets.txt"
{
  echo "GGUF models in packaged tree:"
  find "$ROOT/models" -type f -name '*.gguf' 2>/dev/null | sort || true
  echo
  echo "Expected embedder:"
  EMBED="$ROOT/models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
  if [ -f "$EMBED" ]; then
    echo "FOUND $EMBED"
  else
    echo "MISSING $EMBED"
  fi
  echo
  echo "Potential local embedder candidates elsewhere:"
  find "$HOME/Desktop/ELI_MKXI" "$HOME/eli" "$HOME" \
    -path '*/nomic-embed-text-v1.5.Q4_K_M.gguf' \
    -type f 2>/dev/null | sort -u | head -20 || true
  echo
  echo "Piper/TTS configuration references:"
  grep -RIn --color=never \
    -E 'en_US-amy-medium|PIPER|piper|voice model|voice_model' \
    "$ROOT/eli" "$ROOT/config" "$ROOT/.env.mkxi" 2>/dev/null | head -200 || true
  echo
  echo "Potential local amy-medium Piper assets:"
  find "$HOME" \
    \( -iname '*en_US-amy-medium*' -o -iname '*amy-medium*' \) \
    -type f 2>/dev/null | sort -u | head -50 || true
} | tee -a "$OUT/02_assets.txt"
echo

echo "=== Attempting local embedder reconciliation, without downloading ==="
mkdir -p "$ROOT/models/embeddings"
EMBED_DST="$ROOT/models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
if [ ! -f "$EMBED_DST" ]; then
  EMBED_SRC="$(
    find "$HOME/Desktop/ELI_MKXI" "$HOME/eli" "$HOME" \
      -path '*/nomic-embed-text-v1.5.Q4_K_M.gguf' \
      -type f 2>/dev/null | head -1 || true
  )"
  if [ -n "${EMBED_SRC:-}" ] && [ -f "$EMBED_SRC" ]; then
    ln -sfn "$(readlink -f "$EMBED_SRC")" "$EMBED_DST"
    echo "LINKED embedder:"
    echo "  $EMBED_DST -> $(readlink -f "$EMBED_DST")"
  else
    echo "No existing embedder found locally. Leaving missing, report records it."
  fi
else
  echo "Embedder already present."
fi
echo

echo "=== Patch 1: output_governor wrong-frame replacement guard ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/cognition/output_governor.py"
src = path.read_text(encoding="utf-8")

marker = "# === PHASE13_OUTPUT_GOVERNOR_REPAIR_CONTEXT_GATE ==="
if marker in src:
    print("SKIP output_governor.py already contains Phase 13 gate")
    (out / "03_patch_output_governor.txt").write_text(
        "SKIP: marker already present\n", encoding="utf-8"
    )
    raise SystemExit(0)

old = '''    # If the model starts doing encyclopaedia-medical sludge after an ELI repair
    # metaphor, do not let that through as if it were a valid answer.
    if _MEDICAL_METAPHOR_DRIFT_RE.search(result):
        return (
            "Wrong frame. You meant surgery on ELI — code/persona/memory repair — "
            "not human neurosurgery. The response drifted into generic medical filler "
            "and should be regenerated from local system context."
        )
'''

new = '''    # === PHASE13_OUTPUT_GOVERNOR_REPAIR_CONTEXT_GATE ===
    # The old branch replaced *any* answer containing one of the medical drift
    # keywords, even when the user's current prompt had nothing to do with ELI
    # repair/surgery metaphors. That can corrupt unrelated phatic replies.
    # Only emit the corrective "Wrong frame" response when the *user prompt*
    # itself carries the local-repair metaphor frame.
    _eli_phase13_repair_prompt = str(user_input or "")
    _eli_phase13_repair_context = bool(
        _LOCAL_REPAIR_FRAME_RE.search(_eli_phase13_repair_prompt)
    )
    if _eli_phase13_repair_context and _MEDICAL_METAPHOR_DRIFT_RE.search(result):
        return (
            "Wrong frame. You meant surgery on ELI — code/persona/memory repair — "
            "not human neurosurgery. The response drifted into generic medical filler "
            "and should be regenerated from local system context."
        )
'''

if old in src:
    patched = src.replace(old, new, 1)
else:
    # Fallback regex for very small local formatting drift.
    pat = re.compile(
        r'''(?ms)
^    \# If the model starts doing encyclopaedia-medical sludge after an ELI repair\n
^    \# metaphor, do not let that through as if it were a valid answer\.\n
^    if _MEDICAL_METAPHOR_DRIFT_RE\.search\(result\):\n
^        return \(\n
^            "Wrong frame\. You meant surgery on ELI — code/persona/memory repair — "\n
^            "not human neurosurgery\. The response drifted into generic medical filler "\n
^            "and should be regenerated from local system context\."\n
^        \)\n
'''.replace("\n", ""),
        re.MULTILINE | re.DOTALL,
    )
    patched, n = pat.subn(new, src, count=1)
    if n != 1:
        raise SystemExit("PATCH FAILED: could not locate unconditional wrong-frame branch in output_governor.py")

path.write_text(patched, encoding="utf-8")
(out / "03_patch_output_governor.txt").write_text(
    "PATCHED output_governor.py: wrong-frame response is now gated by user repair context.\n",
    encoding="utf-8",
)
print("PATCHED output_governor.py")
PY
echo

echo "=== Patch 2: Labs tab Qt binding consistency ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/gui/labs_tab.py"
src = path.read_text(encoding="utf-8")

marker = "# === PHASE13_LABS_QT_BINDING_ALIGNMENT ==="
if marker in src:
    print("SKIP labs_tab.py already contains Phase 13 Qt alignment")
    (out / "04_patch_labs_tab.txt").write_text(
        "SKIP: marker already present\n", encoding="utf-8"
    )
    raise SystemExit(0)

start = src.find("# ── Qt imports")
end = src.find("# ── Optional: QsciScintilla")
if start < 0 or end < 0 or end <= start:
    raise SystemExit("PATCH FAILED: could not locate Qt import block in labs_tab.py")

new_block = r'''# ── Qt imports ─────────────────────────────────────────────────────────────
# === PHASE13_LABS_QT_BINDING_ALIGNMENT ===
# Labs must use the same Qt binding as the already-loaded main GUI.
# A PySide6 QWidget cannot accept a PyQt6 QMainWindow as parent, and vice versa.
# Prefer the live binding already imported by the GUI; otherwise honour
# ELI_QT_API; otherwise fall back PySide6 → PyQt6 → PyQt5.

_QT = None
_QT_ERRORS = []

_eli_qt_pref = str(os.environ.get("ELI_QT_API") or "").strip()
if "PySide6.QtWidgets" in sys.modules or "PySide6" in sys.modules:
    _QT_IMPORT_ORDER = ["PySide6", "PyQt6", "PyQt5"]
elif "PyQt6.QtWidgets" in sys.modules or "PyQt6" in sys.modules:
    _QT_IMPORT_ORDER = ["PyQt6", "PySide6", "PyQt5"]
elif "PyQt5.QtWidgets" in sys.modules or "PyQt5" in sys.modules:
    _QT_IMPORT_ORDER = ["PyQt5", "PySide6", "PyQt6"]
elif _eli_qt_pref in {"PySide6", "PyQt6", "PyQt5"}:
    _QT_IMPORT_ORDER = [_eli_qt_pref] + [
        x for x in ("PySide6", "PyQt6", "PyQt5") if x != _eli_qt_pref
    ]
else:
    _QT_IMPORT_ORDER = ["PySide6", "PyQt6", "PyQt5"]

for _eli_qt_candidate in _QT_IMPORT_ORDER:
    try:
        if _eli_qt_candidate == "PySide6":
            from PySide6.QtWidgets import (
                QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplitter,
                QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit,
                QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
                QGroupBox, QFormLayout, QComboBox, QCheckBox, QTreeView,
                QFileDialog, QMessageBox, QInputDialog, QScrollArea,
                QFileSystemModel, QHeaderView, QSizePolicy, QFrame,
                QApplication, QProgressBar, QSpinBox, QDoubleSpinBox,
                QAbstractItemView, QStackedWidget,
            )
            from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal as pyqtSignal, QSize, QDir
            from PySide6.QtGui import QFont, QColor, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QPalette
            _QT = "PySide6"
            break

        if _eli_qt_candidate == "PyQt6":
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
            from PyQt6.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal, QSize, QDir
            from PyQt6.QtGui import QFont, QColor, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QPalette
            _QT = "PyQt6"
            break

        if _eli_qt_candidate == "PyQt5":
            from PyQt5.QtWidgets import (
                QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QSplitter,
                QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit,
                QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
                QGroupBox, QFormLayout, QComboBox, QCheckBox, QTreeView,
                QFileDialog, QMessageBox, QInputDialog, QScrollArea,
                QFileSystemModel, QHeaderView, QSizePolicy, QFrame,
                QApplication, QProgressBar, QSpinBox, QDoubleSpinBox,
                QAbstractItemView, QStackedWidget,
            )
            from PyQt5.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal, QSize, QDir
            from PyQt5.QtGui import QFont, QColor, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QPalette
            _QT = "PyQt5"
            break

    except ImportError as _eli_qt_err:
        _QT_ERRORS.append(f"{_eli_qt_candidate}: {_eli_qt_err}")

if _QT is None:
    raise ImportError(
        "Labs tab could not load a compatible Qt binding. Attempts: "
        + " | ".join(_QT_ERRORS)
    )

'''

patched = src[:start] + new_block + src[end:]
path.write_text(patched, encoding="utf-8")
(out / "04_patch_labs_tab.txt").write_text(
    "PATCHED labs_tab.py: Labs now reuses the already-loaded GUI Qt binding.\n",
    encoding="utf-8",
)
print("PATCHED labs_tab.py")
PY
echo

echo "=== Patch 3: final router guard for clarification chat + import/venv audit ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import ast
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/execution/router_enhanced.py"
src = path.read_text(encoding="utf-8")

marker = "# === PHASE13_ROUTE_SURFACE_GUARD ==="
if marker in src:
    print("SKIP router_enhanced.py already contains Phase 13 route guard")
    (out / "05_patch_router.txt").write_text(
        "SKIP: marker already present\n", encoding="utf-8"
    )
    raise SystemExit(0)

tree = ast.parse(src)
route_defs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "route"]
if not route_defs:
    raise SystemExit("PATCH FAILED: no top-level def route(...) found in router_enhanced.py")

target = route_defs[-1]
first_arg = target.args.args[0].arg if target.args.args else None
if not first_arg:
    raise SystemExit("PATCH FAILED: final route(...) has no positional first argument")

lines = src.splitlines(keepends=True)

# Find the end of the route() signature line(s).
sig_i = target.lineno - 1
sig_end = sig_i
while sig_end < len(lines):
    if lines[sig_end].rstrip().endswith(":"):
        break
    sig_end += 1
if sig_end >= len(lines):
    raise SystemExit("PATCH FAILED: could not find end of final route(...) signature")

helper = r'''
# === PHASE13_ROUTE_SURFACE_GUARD ===
def _eli_phase13_route_surface_preempt(_raw_user_text):
    """
    Final route guard:
    - Conversational clarification/frustration stays CHAT unless the user
      explicitly names a technical diagnostic/audit target.
    - Questions about missing imports / virtual environments preempt into the
      grounded IMPORT_AUDIT surface instead of falling through to generic CHAT.
    """
    _raw = str(_raw_user_text or "")
    _low = re.sub(r"\s+", " ", _raw.strip().lower())
    if not _low:
        return None

    _technical_terms = (
        "audit", "diagnostic", "diagnose", "runtime", "runtime status",
        "model", "gguf", "gpu", "ctx", "context", "memory db",
        "router", "executor", "orchestrator", "pipeline", "engine",
        "traceback", "stack trace", "import", "imports", "module",
        "dependency", "dependencies", "virtual environment", "venv", ".venv",
        "file", "files", "settings", "config",
    )

    _asks_import_or_venv_status = (
        any(x in _low for x in ("import", "imports", "module", "modules", "dependency", "dependencies"))
        and any(x in _low for x in ("status", "missing", "failing", "failure", "audit", "check", "what is"))
    ) or (
        any(x in _low for x in ("virtual environment", "virtual environments", "venv", ".venv"))
        and any(x in _low for x in ("status", "missing", "failing", "failure", "audit", "check", "what is"))
    )

    if _asks_import_or_venv_status:
        return {
            "action": "IMPORT_AUDIT",
            "args": {
                "query": _raw,
                "include_venv": True,
                "scope": "project_and_runtime",
            },
            "confidence": 0.98,
            "meta": {
                "matched_by": "phase13.import_venv_audit.preempt",
                "need_grounding": True,
                "task_family": "grounded_audit",
            },
        }

    _clarification_patterns = (
        r"^what(?: the fuck)? is happening[?!., ]*$",
        r"^what(?: the fuck)? is going on[?!., ]*$",
        r"^what are you talking about[?!., ]*$",
        r"^what do you mean[?!., ]*$",
        r"^why did you say that[?!., ]*$",
        r"^is that a note to yourself(?:,? or me)?[?!., ]*$",
        r"^was that a note to yourself(?:,? or me)?[?!., ]*$",
        r"^what was that[?!., ]*$",
    )
    _looks_like_conversational_clarification = any(
        re.match(_pat, _low) for _pat in _clarification_patterns
    )

    if _looks_like_conversational_clarification and not any(t in _low for t in _technical_terms):
        return {
            "action": "CHAT",
            "args": {"message": _raw},
            "confidence": 0.96,
            "meta": {
                "matched_by": "phase13.conversational_clarification.chat_guard",
                "need_grounding": False,
                "task_family": "chat",
            },
        }

    return None

'''

guard = (
    f"    _eli_phase13_preempt = _eli_phase13_route_surface_preempt({first_arg})\n"
    f"    if _eli_phase13_preempt is not None:\n"
    f"        return _eli_phase13_preempt\n"
)

# Insert helper before final route def, then guard at start of final route.
insert_at = target.lineno - 1
lines[insert_at:insert_at] = [helper]
shift = helper.count("\n")
# Re-find line indexes after helper insertion.
source_after_helper = "".join(lines)
tree2 = ast.parse(source_after_helper)
route_defs2 = [n for n in tree2.body if isinstance(n, ast.FunctionDef) and n.name == "route"]
target2 = route_defs2[-1]
lines2 = source_after_helper.splitlines(keepends=True)
sig_end2 = target2.lineno - 1
while sig_end2 < len(lines2):
    if lines2[sig_end2].rstrip().endswith(":"):
        break
    sig_end2 += 1
if sig_end2 >= len(lines2):
    raise SystemExit("PATCH FAILED: could not re-find final route signature after helper insert")

lines2[sig_end2 + 1:sig_end2 + 1] = [guard]
patched = "".join(lines2)

path.write_text(patched, encoding="utf-8")
(out / "05_patch_router.txt").write_text(
    "PATCHED router_enhanced.py: final route guard installed for clarification-chat and import/venv audit preemption.\n",
    encoding="utf-8",
)
print("PATCHED router_enhanced.py")
PY
echo

echo "=== Patch 4: engine veto for implicit META_DIAGNOSTIC upgrades ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/kernel/engine.py"
src = path.read_text(encoding="utf-8")

helper_marker = "# === PHASE13_META_DIAGNOSTIC_EXPLICITNESS_GUARD ==="
veto_marker = "# === PHASE13_IMPLICIT_META_DIAGNOSTIC_VETO ==="

patched = src

if helper_marker not in patched:
    anchor = "# Response governance"
    idx = patched.find(anchor)
    if idx < 0:
        raise SystemExit("PATCH FAILED: could not locate '# Response governance' anchor in engine.py")

    helper = r'''
# === PHASE13_META_DIAGNOSTIC_EXPLICITNESS_GUARD ===
def _eli_phase13_explicit_meta_diagnostic_request(_text: str) -> bool:
    """
    Ordinary confusion/frustration must not be upgraded into META_DIAGNOSTIC.
    The user must explicitly ask for a diagnostic/audit/runtime/system report.
    """
    _low = " ".join(str(_text or "").strip().lower().split())
    if not _low:
        return False
    _explicit_terms = (
        "diagnose", "diagnostic", "meta diagnostic", "audit",
        "runtime status", "system status", "full status",
        "show your runtime", "what is broken internally",
        "what failed internally", "trace the failure",
        "inspect your pipeline", "control surface", "route this",
        "debug yourself", "self diagnostic",
    )
    return any(_term in _low for _term in _explicit_terms)


'''
    patched = patched[:idx] + helper + patched[idx:]

if veto_marker not in patched:
    lines = patched.splitlines(keepends=True)
    hits = [
        i for i, line in enumerate(lines)
        if "Control contract upgraded action ->" in line
    ]
    if not hits:
        raise SystemExit(
            "PATCH FAILED: could not find 'Control contract upgraded action ->' log line in engine.py"
        )

    # Patch every current upgrade log site; typically one.
    offset = 0
    for hit in hits:
        i = hit + offset
        line = lines[i]
        indent = line[:len(line) - len(line.lstrip())]
        veto = [
            f"{indent}# === PHASE13_IMPLICIT_META_DIAGNOSTIC_VETO ===\n",
            f"{indent}if str(action or \"\").strip().upper() == \"META_DIAGNOSTIC\":\n",
            f"{indent}    _eli_phase13_diag_probe = str(\n",
            f"{indent}        locals().get(\"user_input\")\n",
            f"{indent}        or locals().get(\"user_text\")\n",
            f"{indent}        or locals().get(\"message\")\n",
            f"{indent}        or locals().get(\"prompt\")\n",
            f"{indent}        or locals().get(\"text\")\n",
            f"{indent}        or \"\"\n",
            f"{indent}    )\n",
            f"{indent}    if not _eli_phase13_explicit_meta_diagnostic_request(_eli_phase13_diag_probe):\n",
            f"{indent}        print(\"[COGNITIVE] Phase 13 implicit META_DIAGNOSTIC veto -> CHAT\")\n",
            f"{indent}        action = \"CHAT\"\n",
            f"{indent}        for _eli_phase13_route_obj in (\n",
            f"{indent}            locals().get(\"parsed\"),\n",
            f"{indent}            locals().get(\"route_result\"),\n",
            f"{indent}            locals().get(\"routed\"),\n",
            f"{indent}            locals().get(\"route_payload\"),\n",
            f"{indent}        ):\n",
            f"{indent}            if isinstance(_eli_phase13_route_obj, dict):\n",
            f"{indent}                _eli_phase13_route_obj[\"action\"] = \"CHAT\"\n",
            f"{indent}                _eli_phase13_route_obj.setdefault(\"args\", {{}})\n",
            f"{indent}                if isinstance(_eli_phase13_route_obj[\"args\"], dict):\n",
            f"{indent}                    _eli_phase13_route_obj[\"args\"].setdefault(\"message\", _eli_phase13_diag_probe)\n",
            f"{indent}                _eli_phase13_route_obj.setdefault(\"meta\", {{}})\n",
            f"{indent}                if isinstance(_eli_phase13_route_obj[\"meta\"], dict):\n",
            f"{indent}                    _eli_phase13_route_obj[\"meta\"][\"phase13_meta_diagnostic_veto\"] = True\n",
        ]
        lines[i + 1:i + 1] = veto
        offset += len(veto)

    patched = "".join(lines)

path.write_text(patched, encoding="utf-8")
(out / "06_patch_engine.txt").write_text(
    "PATCHED engine.py: implicit META_DIAGNOSTIC upgrades now require explicit diagnostic language.\n",
    encoding="utf-8",
)
print("PATCHED engine.py")
PY
echo

echo "=== Syntax/compile verification of patched files ==="
{
  python3 -m py_compile \
    "$ROOT/eli/cognition/output_governor.py" \
    "$ROOT/eli/gui/labs_tab.py" \
    "$ROOT/eli/execution/router_enhanced.py" \
    "$ROOT/eli/kernel/engine.py" \
    "$ROOT/eli/runtime/visible_text.py" \
    "$ROOT/eli/gui/eli_pro_audio_gui_MKI.py"
  echo "PY_COMPILE_OK"
} | tee "$OUT/07_py_compile.txt"
echo

echo "=== compileall recursive project scan ==="
{
  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"
  echo "COMPILEALL_OK"
} | tee "$OUT/08_compileall.txt"
echo

echo "=== Full ELI module import sweep, isolated subprocesses ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import json
import os
import pkgutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

import eli  # noqa: F401

mods = sorted({
    m.name
    for m in pkgutil.walk_packages([str(root / "eli")], prefix="eli.")
})

records = []
for name in mods:
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys; "
            f"sys.path.insert(0, {str(root)!r}); "
            f"import {name}; "
            "print('OK')"
        ),
    ]
    try:
        p = subprocess.run(
            cmd,
            cwd=str(root),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            text=True,
            capture_output=True,
            timeout=12,
        )
        records.append({
            "module": name,
            "returncode": p.returncode,
            "ok": p.returncode == 0,
            "stdout": p.stdout[-800:],
            "stderr": p.stderr[-1600:],
        })
    except subprocess.TimeoutExpired as ex:
        records.append({
            "module": name,
            "returncode": None,
            "ok": False,
            "stdout": (ex.stdout or "")[-800:] if isinstance(ex.stdout, str) else "",
            "stderr": "TIMEOUT after 12s",
        })

(out / "09_import_sweep.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

fails = [r for r in records if not r["ok"]]
summary = [
    f"modules_total={len(records)}",
    f"modules_failed={len(fails)}",
    "",
]
for r in fails:
    summary.append(f"FAIL {r['module']}")
    if r["stderr"]:
        summary.append("  STDERR " + r["stderr"].replace("\n", " | ")[:700])
    elif r["stdout"]:
        summary.append("  STDOUT " + r["stdout"].replace("\n", " | ")[:700])

text = "\n".join(summary) + "\n"
(out / "09_import_sweep_summary.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== Duplicate top-level symbols + hardcoded /home path audit ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

results = {}
for path in sorted((root / "eli").rglob("*.py")):
    rel = str(path.relative_to(root))
    data = {
        "duplicate_top_level_symbols": [],
        "hardcoded_home_paths": [],
    }
    text = path.read_text(encoding="utf-8", errors="replace")

    try:
        tree = ast.parse(text)
        seen = defaultdict(list)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen[node.name].append(node.lineno)
        for name, lines in sorted(seen.items()):
            if len(lines) > 1:
                data["duplicate_top_level_symbols"].append({
                    "symbol": name,
                    "lines": lines,
                })
    except SyntaxError as ex:
        data["syntax_error"] = f"{ex.msg} line={ex.lineno}"

    for i, line in enumerate(text.splitlines(), start=1):
        if "/home/" in line:
            data["hardcoded_home_paths"].append({"line": i, "text": line.strip()[:260]})

    if data["duplicate_top_level_symbols"] or data["hardcoded_home_paths"] or data.get("syntax_error"):
        results[rel] = data

(out / "10_structure_audit.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

for rel, data in results.items():
    print(rel)
    for item in data.get("duplicate_top_level_symbols", []):
        print(f"  DUPLICATE {item['symbol']} lines={item['lines']}")
    for item in data.get("hardcoded_home_paths", []):
        print(f"  HOME_PATH line={item['line']} {item['text']}")
    if data.get("syntax_error"):
        print(f"  SYNTAX_ERROR {data['syntax_error']}")
PY
echo

echo "=== Surface/control string audit ==="
{
  grep -RIn --color=never \
    -E 'control_result_without_visible_synthesis|runtime_truth_evidence|import_audit_evidence|META_DIAGNOSTIC|DETERMINISTIC_INTROSPECTION|Wrong frame|Stage 11 primary path yielded zero visible tokens' \
    "$ROOT/eli" 2>/dev/null || true
} | tee "$OUT/11_surface_control_grep.txt"
echo

echo "=== Targeted post-patch behavioral probe ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

lines = []

from eli.cognition.output_governor import repair_local_persona_drift

unrelated = repair_local_persona_drift(
    "The surgeon mentioned a skull in an irrelevant generated sentence.",
    user_input="you alive buddy ?",
)
repair_context = repair_local_persona_drift(
    "The surgeon mentioned a skull in an irrelevant generated sentence.",
    user_input="did the open-head surgery on your memory/persona work?",
)

lines.append("OUTPUT_GOVERNOR unrelated_prompt_result=" + repr(unrelated))
lines.append("OUTPUT_GOVERNOR repair_prompt_result=" + repr(repair_context))
lines.append("OUTPUT_GOVERNOR unrelated_wrong_frame=" + str(unrelated.startswith("Wrong frame.")))
lines.append("OUTPUT_GOVERNOR repair_wrong_frame=" + str(repair_context.startswith("Wrong frame.")))

from eli.execution.router_enhanced import route

cases = [
    "what the fuck is happening?",
    "What are you talking about? is that a note to yourself, or me?",
    "there is more failing than that. what is the status of missing imports and virtual environments?",
    "run full audit and diagnostic!",
]
for case in cases:
    routed = route(case)
    action = routed.get("action") if isinstance(routed, dict) else type(routed).__name__
    matched = routed.get("meta", {}).get("matched_by") if isinstance(routed, dict) else ""
    lines.append(f"ROUTE case={case!r} action={action!r} matched_by={matched!r}")

text = "\n".join(lines) + "\n"
(out / "12_targeted_behavior_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== Settings/runtime snapshot truth comparison ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

settings = root / "config" / "settings.json"
snapshot = root / "artifacts" / "runtime_snapshot.json"

payload = {
    "settings_exists": settings.exists(),
    "snapshot_exists": snapshot.exists(),
    "settings": None,
    "snapshot": None,
    "selected_fields": {},
}

if settings.exists():
    try:
        payload["settings"] = json.loads(settings.read_text(encoding="utf-8"))
    except Exception as ex:
        payload["settings"] = {"error": repr(ex)}

if snapshot.exists():
    try:
        payload["snapshot"] = json.loads(snapshot.read_text(encoding="utf-8"))
    except Exception as ex:
        payload["snapshot"] = {"error": repr(ex)}

keys = (
    "provider", "model_path", "n_ctx", "context_size",
    "n_gpu_layers", "gpu_layers", "n_threads", "cpu_threads",
    "n_batch", "batch_size", "kv_cache_k", "kv_cache_v",
)
for key in keys:
    payload["selected_fields"][key] = {
        "settings": payload["settings"].get(key) if isinstance(payload["settings"], dict) else None,
        "snapshot": payload["snapshot"].get(key) if isinstance(payload["snapshot"], dict) else None,
    }

(out / "13_runtime_settings_snapshot_compare.json").write_text(
    json.dumps(payload, indent=2), encoding="utf-8"
)

print(json.dumps(payload["selected_fields"], indent=2))
PY
echo

echo "=== Optional venv repair note ==="
{
  echo "Current .venv:"
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "PRESENT: $ROOT/.venv/bin/python"
  else
    echo "MISSING: $ROOT/.venv/bin/python"
  fi
  echo
  echo "Requirements files:"
  find "$ROOT" -maxdepth 2 -type f \
    \( -iname 'requirements*.txt' -o -iname 'pyproject.toml' \) \
    | sort
} | tee "$OUT/14_venv_requirements_status.txt"
echo

echo "=== Diff summary ==="
{
  git diff --stat 2>/dev/null || true
  echo
  git diff -- \
    eli/cognition/output_governor.py \
    eli/gui/labs_tab.py \
    eli/execution/router_enhanced.py \
    eli/kernel/engine.py 2>/dev/null || true
} > "$OUT/15_patch_diff.txt"

{
  echo "## Applied repairs"
  echo
  echo "1. output_governor.py: false Wrong-frame replacement now requires user repair context."
  echo "2. labs_tab.py: Labs reuses the already-loaded GUI Qt binding."
  echo "3. router_enhanced.py: final route guard preserves normal clarification chat and preempts import/venv status into IMPORT_AUDIT."
  echo "4. engine.py: implicit META_DIAGNOSTIC upgrades are vetoed unless diagnostic intent is explicit."
  echo "5. local embedder was symlinked if a pre-existing copy was found elsewhere."
  echo
  echo "## Review these report files"
  echo
  echo "- \`12_targeted_behavior_probe.txt\`"
  echo "- \`09_import_sweep_summary.txt\`"
  echo "- \`10_structure_audit.json\`"
  echo "- \`13_runtime_settings_snapshot_compare.json\`"
  echo "- \`15_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo
echo "======================================================================"
echo "PHASE 13 COMPLETE"
echo "Report:"
echo "  $OUT"
echo
echo "Key files:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/12_targeted_behavior_probe.txt"
echo "  $OUT/09_import_sweep_summary.txt"
echo "  $OUT/13_runtime_settings_snapshot_compare.json"
echo "======================================================================"
