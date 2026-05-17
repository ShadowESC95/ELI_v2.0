#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/phase22_prevenv_full_dependency_audit_${STAMP}"
mkdir -p "$OUT"

echo "# Phase 22 — Pre-Venv Full ELI Dependency Audit" > "$OUT/00_header.txt"
{
  echo "Generated: $(date -Is)"
  echo "Root: $ROOT"
  echo "Host: $(hostname)"
  echo "User: $(whoami)"
  echo "Kernel: $(uname -a)"
  echo "Python: $(python3 --version 2>&1 || true)"
  echo "Pip: $(python3 -m pip --version 2>&1 || true)"
  echo
  if [ -d ".venv" ]; then
    echo ".venv: PRESENT"
  else
    echo ".venv: ABSENT"
  fi
  echo
  if [ -d ".git" ]; then
    echo "Git repo: PRESENT"
    git rev-parse --show-toplevel 2>/dev/null || true
    git rev-parse --short HEAD 2>/dev/null || true
    git status --short 2>/dev/null || true
  else
    echo "Git repo: ABSENT in this tree"
  fi
} >> "$OUT/00_header.txt"

# ──────────────────────────────────────────────────────────────────────────────
# 1. Existing packaging/dependency manifests
# ──────────────────────────────────────────────────────────────────────────────

find . \
  \( -path './ops/reports' -o -path './.venv' -o -path './__pycache__' \) -prune \
  -o -type f \
  \( \
    -name 'pyproject.toml' \
    -o -name 'setup.py' \
    -o -name 'setup.cfg' \
    -o -name 'requirements*.txt' \
    -o -name 'Pipfile' \
    -o -name 'Pipfile.lock' \
    -o -name 'poetry.lock' \
    -o -name 'uv.lock' \
    -o -name 'environment.yml' \
    -o -name 'environment.yaml' \
    -o -name 'tox.ini' \
    -o -name 'conda*.yml' \
    -o -name 'conda*.yaml' \
  \) \
  -print | sort > "$OUT/01_existing_dependency_manifest_files.txt"

{
  echo "# Existing dependency / packaging manifests"
  echo
  if [ ! -s "$OUT/01_existing_dependency_manifest_files.txt" ]; then
    echo "NONE FOUND"
  else
    while IFS= read -r f; do
      echo
      echo "================================================================================"
      echo "FILE: $f"
      echo "================================================================================"
      sed -n '1,320p' "$f" || true
    done < "$OUT/01_existing_dependency_manifest_files.txt"
  fi
} > "$OUT/02_existing_dependency_manifest_contents.txt"

# Extract declared dependencies from pyproject / requirements where possible
python3 - <<'PY' > "$OUT/03_declared_dependency_extract.txt"
from pathlib import Path
import re
import sys

root = Path(".")
manifest_paths = []

for p in root.rglob("*"):
    if not p.is_file():
        continue
    if "ops/reports" in p.as_posix() or ".venv" in p.as_posix():
        continue
    if p.name == "pyproject.toml" or p.name.startswith("requirements") and p.suffix == ".txt":
        manifest_paths.append(p)

print("# Declared dependency extraction")
print()

if not manifest_paths:
    print("NO pyproject.toml or requirements*.txt files found.")
    raise SystemExit(0)

try:
    import tomllib
except Exception:
    tomllib = None

for p in sorted(manifest_paths):
    print("=" * 88)
    print(f"FILE: {p}")
    print("=" * 88)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"[READ ERROR] {exc}")
        print()
        continue

    if p.name == "pyproject.toml" and tomllib is not None:
        try:
            data = tomllib.loads(text)
            project = data.get("project", {}) or {}
            deps = project.get("dependencies", []) or []
            optional = project.get("optional-dependencies", {}) or {}
            print("[project.dependencies]")
            for d in deps:
                print(f"- {d}")
            if not deps:
                print("- NONE")
            print()
            print("[project.optional-dependencies]")
            if optional:
                for group, items in optional.items():
                    print(f"{group}:")
                    for item in items or []:
                        print(f"  - {item}")
            else:
                print("- NONE")
        except Exception as exc:
            print(f"[TOML PARSE ERROR] {exc}")
    elif p.name.startswith("requirements") and p.suffix == ".txt":
        lines = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
        print("[requirements lines]")
        if lines:
            for line in lines:
                print(f"- {line}")
        else:
            print("- NONE")
    print()
PY

# ──────────────────────────────────────────────────────────────────────────────
# 2. AST-level Python import inventory
# ──────────────────────────────────────────────────────────────────────────────

python3 - <<'PY'
from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(".").resolve()
OUT = Path(os.environ.get("OUT_OVERRIDE", "")) if os.environ.get("OUT_OVERRIDE") else None
if OUT is None:
    matches = sorted(Path("ops/reports").glob("phase22_prevenv_full_dependency_audit_*"))
    OUT = matches[-1]

scan_roots = [
    Path("eli"),
    Path("bin"),
    Path("scripts"),
    Path("ops"),
    Path("experimental"),
]

excluded_parts = {
    ".venv",
    "__pycache__",
}
excluded_prefixes = (
    "ops/reports/",
)

# Local top-level names
local_top = set()
for p in ROOT.iterdir():
    if p.name.startswith("."):
        continue
    if p.is_dir():
        local_top.add(p.name)
    elif p.suffix == ".py":
        local_top.add(p.stem)

stdlib = set(getattr(sys, "stdlib_module_names", set()))
stdlib |= set(sys.builtin_module_names)

records = []
syntax_errors = []
dynamic_hits = []
imports_all = defaultdict(set)
imports_try = defaultdict(set)
imports_regular = defaultdict(set)

class Collector(ast.NodeVisitor):
    def __init__(self, relpath: str):
        self.relpath = relpath
        self.try_depth = 0

    def _add(self, module: str):
        if not module:
            return
        top = module.split(".")[0]
        imports_all[top].add(self.relpath)
        if self.try_depth > 0:
            imports_try[top].add(self.relpath)
        else:
            imports_regular[top].add(self.relpath)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level and not node.module:
            return
        if node.level:
            return
        if node.module:
            self._add(node.module)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        self.try_depth += 1
        for item in node.body:
            self.visit(item)
        self.try_depth -= 1

        for handler in node.handlers:
            self.visit(handler)
        for item in node.orelse:
            self.visit(item)
        for item in node.finalbody:
            self.visit(item)

paths = []
for base in scan_roots:
    if not base.exists():
        continue
    for p in base.rglob("*.py"):
        rel = p.as_posix()
        if any(part in p.parts for part in excluded_parts):
            continue
        if rel.startswith(excluded_prefixes):
            continue
        paths.append(p)

for p in sorted(paths):
    rel = p.as_posix()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=rel)
        Collector(rel).visit(tree)
    except SyntaxError as exc:
        syntax_errors.append({
            "file": rel,
            "line": exc.lineno,
            "msg": exc.msg,
        })
    except Exception as exc:
        syntax_errors.append({
            "file": rel,
            "line": None,
            "msg": f"{type(exc).__name__}: {exc}",
        })

def classify(top: str) -> str:
    if top in local_top or top == "eli":
        return "local"
    if top in stdlib:
        return "stdlib"
    return "third_party_or_unresolved"

rows = []
for top in sorted(imports_all):
    rows.append({
        "module": top,
        "class": classify(top),
        "files_count": len(imports_all[top]),
        "files": sorted(imports_all[top]),
        "try_import_files_count": len(imports_try[top]),
        "regular_import_files_count": len(imports_regular[top]),
    })

third_party = [r for r in rows if r["class"] == "third_party_or_unresolved"]
stdlib_rows = [r for r in rows if r["class"] == "stdlib"]
local_rows = [r for r in rows if r["class"] == "local"]

(OUT / "04_ast_import_inventory_full.json").write_text(
    json.dumps({
        "scan_roots": [str(x) for x in scan_roots],
        "files_scanned": len(paths),
        "syntax_or_parse_errors": syntax_errors,
        "imports": rows,
    }, indent=2),
    encoding="utf-8",
)

with (OUT / "05_third_party_or_unresolved_imports.txt").open("w", encoding="utf-8") as f:
    f.write("# Third-party or unresolved top-level imports inferred from AST\n\n")
    for r in third_party:
        f.write(
            f"{r['module']:<28} files={r['files_count']:<4} "
            f"regular={r['regular_import_files_count']:<4} "
            f"inside_try={r['try_import_files_count']:<4}\n"
        )

with (OUT / "06_local_imports.txt").open("w", encoding="utf-8") as f:
    f.write("# Local/importable project modules\n\n")
    for r in local_rows:
        f.write(f"{r['module']:<28} files={r['files_count']}\n")

with (OUT / "07_stdlib_imports.txt").open("w", encoding="utf-8") as f:
    f.write("# Standard-library imports\n\n")
    for r in stdlib_rows:
        f.write(f"{r['module']:<28} files={r['files_count']}\n")

with (OUT / "08_imports_inside_try_blocks_optional_candidates.txt").open("w", encoding="utf-8") as f:
    f.write("# Imports observed inside try blocks — optional/fallback candidates, not automatically optional\n\n")
    for top in sorted(imports_try):
        cls = classify(top)
        f.write(f"{top:<28} class={cls:<28} files={len(imports_try[top])}\n")
        for file in sorted(imports_try[top])[:20]:
            f.write(f"  - {file}\n")
        if len(imports_try[top]) > 20:
            f.write(f"  - ... {len(imports_try[top]) - 20} more\n")

with (OUT / "09_syntax_or_parse_errors.txt").open("w", encoding="utf-8") as f:
    f.write("# Files that could not be parsed during AST import inventory\n\n")
    if not syntax_errors:
        f.write("NONE\n")
    else:
        for err in syntax_errors:
            f.write(f"{err['file']}:{err['line']} {err['msg']}\n")
PY

# ──────────────────────────────────────────────────────────────────────────────
# 3. Candidate pip package mapping from imports
#    This is intentionally a candidate map; final requirements will be curated.
# ──────────────────────────────────────────────────────────────────────────────

python3 - <<'PY' > "$OUT/10_candidate_pip_mapping_from_imports.txt"
from pathlib import Path

out = sorted(Path("ops/reports").glob("phase22_prevenv_full_dependency_audit_*"))[-1]
imports_file = out / "05_third_party_or_unresolved_imports.txt"

mods = []
for line in imports_file.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    mods.append(line.split()[0])

known = {
    "PySide6": "PySide6",
    "PyQt5": "PyQt5",
    "PyQt6": "PyQt6",
    "qtpy": "QtPy",
    "qdarktheme": "pyqtdarktheme",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "numpy": "numpy",
    "scipy": "scipy",
    "sympy": "sympy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "pyqtgraph": "pyqtgraph",
    "pyvista": "pyvista",
    "vtk": "vtk",
    "psutil": "psutil",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "markdown": "Markdown",
    "dateutil": "python-dateutil",
    "pydantic": "pydantic",
    "platformdirs": "platformdirs",
    "rich": "rich",
    "tqdm": "tqdm",
    "networkx": "networkx",
    "rapidfuzz": "rapidfuzz",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "joblib": "joblib",
    "faiss": "faiss-cpu OR faiss-gpu",
    "llama_cpp": "llama-cpp-python",
    "torch": "torch",
    "transformers": "transformers",
    "sentence_transformers": "sentence-transformers",
    "datasets": "datasets",
    "accelerate": "accelerate",
    "peft": "peft",
    "sounddevice": "sounddevice",
    "soundfile": "soundfile",
    "pyaudio": "PyAudio",
    "speech_recognition": "SpeechRecognition",
    "faster_whisper": "faster-whisper",
    "whisper": "openai-whisper",
    "pyttsx3": "pyttsx3",
    "edge_tts": "edge-tts",
    "mss": "mss",
    "pyautogui": "PyAutoGUI",
    "pynput": "pynput",
    "keyboard": "keyboard",
    "mouse": "mouse",
    "selenium": "selenium",
    "playwright": "playwright",
    "fitz": "PyMuPDF",
    "pypdf": "pypdf",
    "PyPDF2": "PyPDF2",
    "pdfplumber": "pdfplumber",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "odf": "odfpy",
    "jupyter_client": "jupyter_client",
    "IPython": "ipython",
    "nbformat": "nbformat",
    "zmq": "pyzmq",
    "websockets": "websockets",
    "flask": "Flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "watchdog": "watchdog",
    "serial": "pyserial",
    "evdev": "evdev",
    "Xlib": "python-xlib",
    "pyperclip": "pyperclip",
    "cryptography": "cryptography",
    "Pygments": "Pygments",
    "jinja2": "Jinja2",
    "lxml": "lxml",
}

mapped = []
unmapped = []

for mod in mods:
    if mod in known:
        mapped.append((mod, known[mod]))
    else:
        unmapped.append(mod)

print("# Candidate pip mapping inferred from import names")
print("# Final requirements must be curated against actual runtime paths and optionality.")
print()
print("[mapped]")
for mod, pkg in mapped:
    print(f"{mod:<28} -> {pkg}")
print()
print("[unmapped]")
if unmapped:
    for mod in unmapped:
        print(mod)
else:
    print("NONE")
PY

# ──────────────────────────────────────────────────────────────────────────────
# 4. Dynamic import / optional runtime loading hits
# ──────────────────────────────────────────────────────────────────────────────

rg -n --hidden -S \
  'importlib\.import_module|__import__\(|find_spec\(|try:|except ImportError|except ModuleNotFoundError|optional dependency|not available|fallback' \
  eli bin scripts ops experimental \
  --glob '*.py' \
  --glob '!ops/reports/**' \
  2>/dev/null \
  > "$OUT/11_dynamic_import_and_optional_dependency_hits.txt" || true

# ──────────────────────────────────────────────────────────────────────────────
# 5. Qt binding / GUI dependency surface
# ──────────────────────────────────────────────────────────────────────────────

{
  echo "# Qt / GUI dependency surface"
  echo
  echo "=== qt_compat.py ==="
  if [ -f eli/gui/qt_compat.py ]; then
    sed -n '1,260p' eli/gui/qt_compat.py
  else
    echo "eli/gui/qt_compat.py NOT FOUND"
  fi
  echo
  echo "=== Direct GUI binding imports ==="
  rg -n --hidden --glob '*.py' \
    'from (PySide6|PyQt6|PyQt5|PySide2)\b|import (PySide6|PyQt6|PyQt5|PySide2)\b|QScintilla|Qsci' \
    eli \
    2>/dev/null || true
} > "$OUT/12_qt_gui_binding_surface.txt"

# ──────────────────────────────────────────────────────────────────────────────
# 6. External binaries / system command references
# ──────────────────────────────────────────────────────────────────────────────

rg -n --hidden -S \
  'subprocess\.(run|Popen|check_output|check_call)|shutil\.which\(|os\.system\(|QProcess|nvidia-smi|ollama|pandoc|lualatex|xelatex|pdflatex|latexmk|ffmpeg|ffprobe|piper|aplay|paplay|playerctl|xdg-open|gio open|open -a|libreoffice|soffice|git |git"|git\]|wpctl|pactl|pacmd|wl-copy|wl-paste|xclip|xsel|wmctrl|ydotool|wtype|grim|slurp|gnome-screenshot|scrot|tesseract|espeak|festival|arecord|parec|pw-record' \
  eli bin scripts ops experimental \
  --glob '*.py' \
  --glob '*.sh' \
  --glob '!ops/reports/**' \
  2>/dev/null \
  > "$OUT/13_external_binary_and_subprocess_hits.txt" || true

# Compact candidate executable list from code hit text
python3 - <<'PY' > "$OUT/14_external_binary_candidate_summary.txt"
from pathlib import Path
import re

out = sorted(Path("ops/reports").glob("phase22_prevenv_full_dependency_audit_*"))[-1]
text = (out / "13_external_binary_and_subprocess_hits.txt").read_text(encoding="utf-8", errors="replace")

candidates = [
    "nvidia-smi", "ollama",
    "pandoc", "lualatex", "xelatex", "pdflatex", "latexmk",
    "ffmpeg", "ffprobe",
    "piper", "aplay", "paplay", "playerctl",
    "xdg-open", "gio", "libreoffice", "soffice",
    "git",
    "wpctl", "pactl", "pacmd",
    "wl-copy", "wl-paste", "xclip", "xsel",
    "wmctrl", "ydotool", "wtype",
    "grim", "slurp", "gnome-screenshot", "scrot",
    "tesseract", "espeak", "festival",
    "arecord", "parec", "pw-record",
]

found = []
for c in candidates:
    if c in text:
        found.append(c)

print("# External executable names referenced somewhere in source/script hits")
print()
if found:
    for c in found:
        print(f"- {c}")
else:
    print("NONE DETECTED BY CURRENT PATTERN")
PY

# ──────────────────────────────────────────────────────────────────────────────
# 7. Runtime models, voices, assets, large artifact dependencies
# ──────────────────────────────────────────────────────────────────────────────

{
  echo "# Runtime asset / model directory inventory"
  echo
  for d in models assets resources voices data config; do
    if [ -e "$d" ]; then
      echo "================================================================================"
      echo "PATH: $d"
      echo "================================================================================"
      du -sh "$d" 2>/dev/null || true
      find "$d" -type f \
        \( \
          -name '*.gguf' \
          -o -name '*.onnx' \
          -o -name '*.bin' \
          -o -name '*.pt' \
          -o -name '*.pth' \
          -o -name '*.safetensors' \
          -o -name '*.json' \
          -o -name '*.jsonl' \
          -o -name '*.yaml' \
          -o -name '*.yml' \
          -o -name '*.toml' \
          -o -name '*.wav' \
          -o -name '*.mp3' \
          -o -name '*.png' \
          -o -name '*.jpg' \
          -o -name '*.jpeg' \
        \) \
        -printf '%s\t%p\n' 2>/dev/null \
        | sort -nr \
        | awk -F '\t' '{printf "%12s bytes  %s\n", $1, $2}' \
        | sed -n '1,600p'
      echo
    fi
  done
} > "$OUT/15_runtime_asset_and_model_inventory.txt"

# Source references to specific model/assets
rg -n --hidden -S \
  '\.gguf|\.onnx|\.safetensors|\.pt\b|\.pth\b|embedding|embedder|piper|voice model|model_path|models/' \
  eli config bin scripts ops experimental \
  --glob '*.py' \
  --glob '*.json' \
  --glob '*.toml' \
  --glob '*.yaml' \
  --glob '*.yml' \
  --glob '*.sh' \
  --glob '!ops/reports/**' \
  2>/dev/null \
  > "$OUT/16_model_and_asset_reference_hits.txt" || true

# ──────────────────────────────────────────────────────────────────────────────
# 8. Repo / upstream / download URL references already present in tree
# ──────────────────────────────────────────────────────────────────────────────

rg -n --hidden -S \
  'github\.com|huggingface\.co|pypi\.org|git\+https|https?://|upstream|repository|repo:' \
  eli config bin scripts ops README* LICENSE* pyproject.toml setup.py setup.cfg \
  --glob '!ops/reports/**' \
  --glob '!*.log' \
  2>/dev/null \
  > "$OUT/17_repo_upstream_and_url_reference_hits.txt" || true

# Installation command references
rg -n --hidden -S \
  'pip install|python3 -m pip install|apt(-get)? install|dnf install|pacman -S|brew install|conda install|uv pip install|poetry add' \
  eli config bin scripts ops README* \
  --glob '!ops/reports/**' \
  2>/dev/null \
  > "$OUT/18_install_command_reference_hits.txt" || true

# ──────────────────────────────────────────────────────────────────────────────
# 9. Current project Python importability without venv
# ──────────────────────────────────────────────────────────────────────────────

{
  echo "# Current raw interpreter import probe"
  echo
  echo "PWD: $(pwd)"
  echo "PYTHONPATH: ${PYTHONPATH-<unset>}"
  echo
  echo "=== import eli ==="
  python3 - <<'PY'
try:
    import eli
    print("IMPORT_ELI_OK", getattr(eli, "__file__", "<no file>"))
except Exception as exc:
    print("IMPORT_ELI_FAIL", type(exc).__name__, str(exc))
PY
  echo
  echo "=== import core GUI surfaces ==="
  python3 - <<'PY'
mods = [
    "eli.gui.qt_compat",
    "eli.gui.labs_tab",
    "eli.gui.eli_pro_audio_gui_MKI",
    "eli.cognition.inference_broker",
    "eli.cognition.gguf_inference",
]
for mod in mods:
    try:
        __import__(mod)
        print(f"IMPORT_OK   {mod}")
    except Exception as exc:
        print(f"IMPORT_FAIL {mod} :: {type(exc).__name__}: {exc}")
PY
} > "$OUT/19_raw_interpreter_import_probe.txt" 2>&1 || true

# ──────────────────────────────────────────────────────────────────────────────
# 10. Requirements skeleton candidates — not final, but useful input
# ──────────────────────────────────────────────────────────────────────────────

python3 - <<'PY' > "$OUT/20_requirements_candidate_skeleton_unvetted.txt"
from pathlib import Path

out = sorted(Path("ops/reports").glob("phase22_prevenv_full_dependency_audit_*"))[-1]
mapping_file = out / "10_candidate_pip_mapping_from_imports.txt"

mapped = []
unmapped = []
mode = None

for line in mapping_file.read_text(encoding="utf-8", errors="replace").splitlines():
    if line.strip() == "[mapped]":
        mode = "mapped"
        continue
    if line.strip() == "[unmapped]":
        mode = "unmapped"
        continue
    if not line.strip() or line.startswith("#"):
        continue
    if mode == "mapped":
        if "->" in line:
            pkg = line.split("->", 1)[1].strip()
            mapped.append(pkg)
    elif mode == "unmapped":
        if line.strip() != "NONE":
            unmapped.append(line.strip())

print("# UNVETTED requirements candidate skeleton")
print("# Do not install this blindly. This is raw import-name inference only.")
print()
print("# Candidate mapped packages")
for pkg in sorted(set(mapped), key=str.lower):
    print(pkg)
print()
print("# Unmapped import names requiring manual resolution")
for mod in sorted(set(unmapped), key=str.lower):
    print(f"# UNMAPPED_IMPORT: {mod}")
PY

# ──────────────────────────────────────────────────────────────────────────────
# 11. Summary
# ──────────────────────────────────────────────────────────────────────────────

THIRD_PARTY_COUNT="$(grep -vcE '^\s*$|^#' "$OUT/05_third_party_or_unresolved_imports.txt" || true)"
OPTIONAL_COUNT="$(grep -vcE '^\s*$|^#' "$OUT/08_imports_inside_try_blocks_optional_candidates.txt" || true)"
MANIFEST_COUNT="$(grep -vcE '^\s*$' "$OUT/01_existing_dependency_manifest_files.txt" || true)"
BINARY_COUNT="$(grep -cE '^- ' "$OUT/14_external_binary_candidate_summary.txt" || true)"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 22 — Pre-Venv Full ELI Dependency Audit Summary

## Root
\`$ROOT\`

## Immediate state
- Existing \`.venv\`: $([ -d ".venv" ] && echo PRESENT || echo ABSENT)
- Git metadata in this tree: $([ -d ".git" ] && echo PRESENT || echo ABSENT)
- Packaging / dependency manifests found: ${MANIFEST_COUNT}

## Dependency evidence produced
- Third-party or unresolved top-level imports: approximately **${THIRD_PARTY_COUNT}**
- Imports observed inside \`try:\` blocks: optional/fallback candidates recorded
- External executable names referenced in source/scripts: approximately **${BINARY_COUNT}**
- Runtime model/assets inventory written
- Upstream/repo/download URL references written
- Existing declared dependencies extracted where files exist
- Raw current-interpreter import probe written

## Files to inspect first
1. \`05_third_party_or_unresolved_imports.txt\`
2. \`10_candidate_pip_mapping_from_imports.txt\`
3. \`12_qt_gui_binding_surface.txt\`
4. \`14_external_binary_candidate_summary.txt\`
5. \`15_runtime_asset_and_model_inventory.txt\`
6. \`16_model_and_asset_reference_hits.txt\`
7. \`17_repo_upstream_and_url_reference_hits.txt\`
8. \`19_raw_interpreter_import_probe.txt\`
9. \`20_requirements_candidate_skeleton_unvetted.txt\`

## Important
This audit does **not** create a venv and does **not** install or remove packages.
It exists to derive a correct dependency specification before bootstrapping redistribution-grade environments.
EOF

cat > "$OUT/INDEX.txt" <<EOF
00_header.txt
01_existing_dependency_manifest_files.txt
02_existing_dependency_manifest_contents.txt
03_declared_dependency_extract.txt
04_ast_import_inventory_full.json
05_third_party_or_unresolved_imports.txt
06_local_imports.txt
07_stdlib_imports.txt
08_imports_inside_try_blocks_optional_candidates.txt
09_syntax_or_parse_errors.txt
10_candidate_pip_mapping_from_imports.txt
11_dynamic_import_and_optional_dependency_hits.txt
12_qt_gui_binding_surface.txt
13_external_binary_and_subprocess_hits.txt
14_external_binary_candidate_summary.txt
15_runtime_asset_and_model_inventory.txt
16_model_and_asset_reference_hits.txt
17_repo_upstream_and_url_reference_hits.txt
18_install_command_reference_hits.txt
19_raw_interpreter_import_probe.txt
20_requirements_candidate_skeleton_unvetted.txt
SUMMARY.md
INDEX.txt
EOF

echo
echo "AUDIT_OUT=$OUT"
echo
cat "$OUT/SUMMARY.md"
