#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase22_full_dependency_audit_and_venv_bootstrap_${STAMP}"
REQDIR="$ROOT/requirements/generated"
README="$ROOT/requirements/README_ELI_ENVIRONMENT.md"
RUNNER="$ROOT/scripts/run_eli_repo_venv.sh"
VENV="$ROOT/.venv"
OLD_VENV_BACKUP="$ROOT/.venv.before_phase22_${STAMP}"
PYBIN="${PYTHON_BIN:-python3}"

mkdir -p "$OUT" "$REQDIR" "$ROOT/scripts"

export ELI_PHASE22_ROOT="$ROOT"
export ELI_PHASE22_OUT="$OUT"
export ELI_PHASE22_REQDIR="$REQDIR"

{
  echo "# Phase 22 — Full ELI Dependency Audit + Venv Bootstrap"
  echo
  echo "Generated: $(date -Is)"
  echo "Root: $ROOT"
  echo "Python binary requested: $PYBIN"
  echo "Host: $(hostname)"
  echo "User: $(whoami)"
  echo "Kernel: $(uname -a)"
  echo
  echo "Existing .venv: $([ -d "$VENV" ] && echo PRESENT || echo ABSENT)"
  echo "Git metadata: $([ -d ".git" ] && echo PRESENT || echo ABSENT)"
  echo
  "$PYBIN" --version 2>&1 || true
  "$PYBIN" -m pip --version 2>&1 || true
} > "$OUT/00_header.txt"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Capture existing venv state before replacement
# ─────────────────────────────────────────────────────────────────────────────

if [ -x "$VENV/bin/python" ]; then
  {
    echo "# Existing pre-Phase22 venv freeze"
    "$VENV/bin/python" -m pip freeze 2>&1 || true
  } > "$OUT/01_existing_venv_freeze.txt"

  "$VENV/bin/python" - <<'PY' > "$OUT/02_existing_venv_packages_distributions.json" 2>&1 || true
import json
try:
    from importlib.metadata import packages_distributions
    print(json.dumps(packages_distributions(), indent=2, sort_keys=True))
except Exception as exc:
    print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2))
PY
else
  echo "NO_EXISTING_VENV" > "$OUT/01_existing_venv_freeze.txt"
  echo "{}" > "$OUT/02_existing_venv_packages_distributions.json"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. Find existing dependency manifests
# ─────────────────────────────────────────────────────────────────────────────

find "$ROOT" \
  \( \
    -path "$ROOT/.git" \
    -o -path "$ROOT/.venv" \
    -o -path "$ROOT/ops/reports" \
    -o -path "$ROOT/artifacts" \
    -o -path "$ROOT/models" \
    -o -path '*/__pycache__' \
  \) -prune \
  -o -type f \
  \( \
    -name 'pyproject.toml' \
    -o -name 'requirements*.txt' \
    -o -name 'setup.py' \
    -o -name 'setup.cfg' \
    -o -name 'Pipfile' \
    -o -name 'Pipfile.lock' \
    -o -name 'poetry.lock' \
    -o -name 'uv.lock' \
    -o -name 'environment.yml' \
    -o -name 'environment.yaml' \
    -o -name 'tox.ini' \
  \) \
  -print | sort > "$OUT/03_existing_dependency_manifest_paths.txt"

{
  echo "# Existing dependency/package manifest contents"
  echo
  if [ ! -s "$OUT/03_existing_dependency_manifest_paths.txt" ]; then
    echo "NONE FOUND"
  else
    while IFS= read -r f; do
      echo
      echo "================================================================================"
      echo "FILE: $f"
      echo "================================================================================"
      sed -n '1,360p' "$f" || true
    done < "$OUT/03_existing_dependency_manifest_paths.txt"
  fi
} > "$OUT/04_existing_dependency_manifest_contents.txt"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Full repo import audit + requirement synthesis
# ─────────────────────────────────────────────────────────────────────────────

"$PYBIN" - <<'PY'
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ["ELI_PHASE22_ROOT"]).resolve()
OUT = Path(os.environ["ELI_PHASE22_OUT"]).resolve()
REQDIR = Path(os.environ["ELI_PHASE22_REQDIR"]).resolve()

EXCLUDE_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "artifacts",
    "models",
    "dist",
    "build",
}
EXCLUDE_PREFIXES = (
    "ops/reports/",
)

# Scan the whole actual working tree, including experimental/, ops/, scripts/, bin/, eli/.
python_files: list[Path] = []
for p in ROOT.rglob("*.py"):
    rel = p.relative_to(ROOT).as_posix()
    if any(part in EXCLUDE_PARTS for part in p.parts):
        continue
    if rel.startswith(EXCLUDE_PREFIXES):
        continue
    python_files.append(p)

local_top_level = set()
for p in ROOT.iterdir():
    if p.name.startswith("."):
        continue
    if p.is_dir():
        local_top_level.add(p.name)
    elif p.suffix == ".py":
        local_top_level.add(p.stem)
local_top_level.add("eli")

stdlib = set(getattr(sys, "stdlib_module_names", set()))
stdlib |= set(sys.builtin_module_names)

imports_by_module: dict[str, set[str]] = defaultdict(set)
imports_try_by_module: dict[str, set[str]] = defaultdict(set)
imports_regular_by_module: dict[str, set[str]] = defaultdict(set)
parse_errors: list[dict] = []

class ImportCollector(ast.NodeVisitor):
    def __init__(self, rel: str):
        self.rel = rel
        self.try_depth = 0

    def _record(self, module_name: str):
        if not module_name:
            return
        top = module_name.split(".")[0]
        imports_by_module[top].add(self.rel)
        if self.try_depth > 0:
            imports_try_by_module[top].add(self.rel)
        else:
            imports_regular_by_module[top].add(self.rel)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._record(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level:
            return
        if node.module:
            self._record(node.module)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        self.try_depth += 1
        for n in node.body:
            self.visit(n)
        self.try_depth -= 1

        for h in node.handlers:
            self.visit(h)
        for n in node.orelse:
            self.visit(n)
        for n in node.finalbody:
            self.visit(n)

for p in sorted(python_files):
    rel = p.relative_to(ROOT).as_posix()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=rel)
        ImportCollector(rel).visit(tree)
    except Exception as exc:
        parse_errors.append({
            "file": rel,
            "error": f"{type(exc).__name__}: {exc}",
        })

def classify(top: str) -> str:
    if top in local_top_level:
        return "local"
    if top in stdlib:
        return "stdlib"
    return "third_party_or_unresolved"

import_rows = []
for mod in sorted(imports_by_module):
    import_rows.append({
        "module": mod,
        "class": classify(mod),
        "files_count": len(imports_by_module[mod]),
        "files": sorted(imports_by_module[mod]),
        "regular_import_files_count": len(imports_regular_by_module[mod]),
        "try_import_files_count": len(imports_try_by_module[mod]),
    })

third_party_modules = [
    r for r in import_rows
    if r["class"] == "third_party_or_unresolved"
]
local_modules = [
    r for r in import_rows
    if r["class"] == "local"
]
stdlib_modules = [
    r for r in import_rows
    if r["class"] == "stdlib"
]

(OUT / "05_repo_ast_import_inventory.json").write_text(
    json.dumps({
        "python_files_scanned": len(python_files),
        "parse_errors": parse_errors,
        "imports": import_rows,
    }, indent=2),
    encoding="utf-8",
)

with (OUT / "06_third_party_or_unresolved_imports.txt").open("w", encoding="utf-8") as f:
    f.write("# Third-party / unresolved top-level imports from full repo AST scan\n\n")
    for r in third_party_modules:
        f.write(
            f"{r['module']:<30} "
            f"files={r['files_count']:<4} "
            f"regular={r['regular_import_files_count']:<4} "
            f"try={r['try_import_files_count']:<4}\n"
        )

with (OUT / "07_local_imports.txt").open("w", encoding="utf-8") as f:
    f.write("# Project-local top-level imports\n\n")
    for r in local_modules:
        f.write(f"{r['module']:<30} files={r['files_count']}\n")

with (OUT / "08_stdlib_imports.txt").open("w", encoding="utf-8") as f:
    f.write("# Standard library imports\n\n")
    for r in stdlib_modules:
        f.write(f"{r['module']:<30} files={r['files_count']}\n")

with (OUT / "09_imports_inside_try_blocks.txt").open("w", encoding="utf-8") as f:
    f.write("# Modules observed inside try-block imports; possible optional/fallback dependencies\n\n")
    for mod in sorted(imports_try_by_module):
        f.write(
            f"{mod:<30} class={classify(mod):<30} "
            f"files={len(imports_try_by_module[mod])}\n"
        )
        for rel in sorted(imports_try_by_module[mod])[:30]:
            f.write(f"  - {rel}\n")
        if len(imports_try_by_module[mod]) > 30:
            f.write(f"  - ... {len(imports_try_by_module[mod]) - 30} more\n")

with (OUT / "10_ast_parse_errors.txt").open("w", encoding="utf-8") as f:
    f.write("# AST parse errors during full-repo scan\n\n")
    if not parse_errors:
        f.write("NONE\n")
    else:
        for err in parse_errors:
            f.write(f"{err['file']} :: {err['error']}\n")

# ── Read old venv import -> distribution map, if available ──────────────────

venv_dist_map_path = OUT / "02_existing_venv_packages_distributions.json"
try:
    old_dist_map = json.loads(venv_dist_map_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(old_dist_map, dict):
        old_dist_map = {}
except Exception:
    old_dist_map = {}

# ── Existing declared requirement extraction ────────────────────────────────

declared_requirements: list[str] = []

for p in ROOT.rglob("*"):
    if not p.is_file():
        continue
    rel = p.relative_to(ROOT).as_posix()
    if any(part in EXCLUDE_PARTS for part in p.parts):
        continue
    if rel.startswith(EXCLUDE_PREFIXES):
        continue

    name = p.name
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue

    if name.startswith("requirements") and p.suffix == ".txt":
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("-", "--")):
                continue
            declared_requirements.append(line)

    elif name == "pyproject.toml":
        try:
            data = tomllib.loads(text)
            project = data.get("project", {}) or {}
            for dep in project.get("dependencies", []) or []:
                declared_requirements.append(str(dep).strip())
            optional = project.get("optional-dependencies", {}) or {}
            for _, deps in optional.items():
                for dep in deps or []:
                    declared_requirements.append(str(dep).strip())
        except Exception:
            pass

# normalize / dedupe raw declared req lines
seen_decl = set()
declared_clean: list[str] = []
for req in declared_requirements:
    norm = req.strip()
    if not norm:
        continue
    if norm not in seen_decl:
        declared_clean.append(norm)
        seen_decl.add(norm)

(OUT / "11_declared_requirement_lines.txt").write_text(
    "\n".join(declared_clean) + ("\n" if declared_clean else ""),
    encoding="utf-8",
)

# ── Import -> pip distribution mapping ──────────────────────────────────────

hard_map = {
    # GUI / Qt
    "PySide6": "PySide6",
    "shiboken6": "shiboken6",
    "qtpy": "QtPy",
    "qdarktheme": "pyqtdarktheme",
    "pyqtgraph": "pyqtgraph",

    # Scientific / numerical
    "numpy": "numpy",
    "scipy": "scipy",
    "sympy": "sympy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "networkx": "networkx",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "joblib": "joblib",

    # LLM / retrieval / ML
    "llama_cpp": "llama-cpp-python",
    "faiss": "faiss-cpu",
    "torch": "torch",
    "transformers": "transformers",
    "sentence_transformers": "sentence-transformers",
    "datasets": "datasets",
    "accelerate": "accelerate",
    "peft": "peft",
    "safetensors": "safetensors",
    "onnxruntime": "onnxruntime",

    # Files / docs / serialization
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "markdown": "Markdown",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "fitz": "PyMuPDF",
    "pypdf": "pypdf",
    "PyPDF2": "PyPDF2",
    "pdfplumber": "pdfplumber",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "odf": "odfpy",
    "nbformat": "nbformat",
    "jupyter_client": "jupyter_client",
    "IPython": "ipython",
    "zmq": "pyzmq",
    "jinja2": "Jinja2",
    "Pygments": "Pygments",

    # Requests / web / APIs
    "requests": "requests",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "websockets": "websockets",
    "feedparser": "feedparser",
    "flask": "Flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",

    # Audio / voice
    "speech_recognition": "SpeechRecognition",
    "sounddevice": "sounddevice",
    "soundfile": "soundfile",
    "pyaudio": "PyAudio",
    "pyttsx3": "pyttsx3",
    "faster_whisper": "faster-whisper",
    "whisper": "openai-whisper",
    "edge_tts": "edge-tts",
    "pydub": "pydub",

    # Vision / gaze / screen / automation
    "cv2": "opencv-python",
    "mediapipe": "mediapipe",
    "mss": "mss",
    "pyautogui": "PyAutoGUI",
    "pynput": "pynput",
    "keyboard": "keyboard",
    "mouse": "mouse",
    "pyperclip": "pyperclip",
    "Xlib": "python-xlib",
    "evdev": "evdev",

    # Utility
    "psutil": "psutil",
    "dateutil": "python-dateutil",
    "pydantic": "pydantic",
    "platformdirs": "platformdirs",
    "rich": "rich",
    "tqdm": "tqdm",
    "watchdog": "watchdog",
    "serial": "pyserial",
    "cryptography": "cryptography",
    "rapidfuzz": "rapidfuzz",
}

# Existing venv map helps for packages already installed previously.
resolved_import_to_package: dict[str, str] = {}
resolution_sources: dict[str, str] = {}
unresolved_modules: list[str] = []

for row in third_party_modules:
    mod = row["module"]
    pkg = None
    source = None

    old = old_dist_map.get(mod)
    if isinstance(old, list) and old:
        pkg = str(old[0])
        source = "existing_venv_packages_distributions"
    elif isinstance(old, str) and old:
        pkg = old
        source = "existing_venv_packages_distributions"
    elif mod in hard_map:
        pkg = hard_map[mod]
        source = "curated_import_mapping"

    if pkg:
        resolved_import_to_package[mod] = pkg
        resolution_sources[mod] = source
    else:
        unresolved_modules.append(mod)

# Extract declared package basenames for merge/dedupe.
def req_basename(req: str) -> str:
    s = req.strip()
    s = re.split(r"[<>=!~;\[]", s, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", s).lower()

qt_conflict_base = {
    "pyqt5",
    "pyqt6",
    "pyside2",
    "pyqt5-qt5",
    "pyqt6-qt6",
    "pyqt5-sip",
    "pyqt6-sip",
    "sip",
    "qscintilla",  # excluded from canonical PySide6-first full env; audit retains reference
}

# Start from import-derived packages.
canonical_packages: dict[str, str] = {}

for mod, pkg in resolved_import_to_package.items():
    base = req_basename(pkg)
    if base in qt_conflict_base:
        continue
    canonical_packages.setdefault(base, pkg)

# Merge declared requirements unless they are explicitly Qt-conflicting.
declared_excluded_qt: list[str] = []
for req in declared_clean:
    base = req_basename(req)
    if not base:
        continue
    if base in qt_conflict_base:
        declared_excluded_qt.append(req)
        continue
    canonical_packages.setdefault(base, req)

# Enforce PySide6 as canonical GUI binding.
canonical_packages[req_basename("PySide6")] = "PySide6"

# Sort stable full requirement list.
full_requirements = sorted(canonical_packages.values(), key=lambda s: req_basename(s))

# Categorize requirements for readable generated files.
GUI_NAMES = {
    "pyside6", "shiboken6", "qtpy", "pyqtdarktheme", "pyqtgraph",
}
LLM_NAMES = {
    "llama-cpp-python", "faiss-cpu", "torch", "transformers",
    "sentence-transformers", "datasets", "accelerate", "peft",
    "safetensors", "onnxruntime",
}
AUDIO_NAMES = {
    "speechrecognition", "sounddevice", "soundfile", "pyaudio",
    "pyttsx3", "faster-whisper", "openai-whisper", "edge-tts", "pydub",
}
VISION_NAMES = {
    "opencv-python", "mediapipe", "mss", "pyautogui",
    "pynput", "keyboard", "mouse", "pyperclip", "python-xlib", "evdev",
}
DOCSCI_NAMES = {
    "numpy", "scipy", "sympy", "pandas", "matplotlib", "networkx",
    "scikit-learn", "scikit-image", "joblib",
    "pillow", "pyyaml", "python-dotenv", "markdown", "beautifulsoup4",
    "lxml", "pymupdf", "pypdf", "pypdf2", "pdfplumber",
    "python-docx", "openpyxl", "odfpy", "nbformat",
    "jupyter-client", "ipython", "pyzmq", "jinja2", "pygments",
}

groups = {
    "eli-gui-pyside6.txt": [],
    "eli-local-llm.txt": [],
    "eli-audio-voice.txt": [],
    "eli-vision-automation.txt": [],
    "eli-docs-labs-science.txt": [],
    "eli-runtime-core-misc.txt": [],
}

for req in full_requirements:
    base = req_basename(req)
    if base in GUI_NAMES:
        groups["eli-gui-pyside6.txt"].append(req)
    elif base in LLM_NAMES:
        groups["eli-local-llm.txt"].append(req)
    elif base in AUDIO_NAMES:
        groups["eli-audio-voice.txt"].append(req)
    elif base in VISION_NAMES:
        groups["eli-vision-automation.txt"].append(req)
    elif base in DOCSCI_NAMES:
        groups["eli-docs-labs-science.txt"].append(req)
    else:
        groups["eli-runtime-core-misc.txt"].append(req)

# Write generated requirements.
(REQDIR / "eli-full.txt").write_text(
    "# Auto-generated Phase 22 ELI full requirement candidate\n"
    "# Built from repo imports + existing manifest lines + old venv package map.\n"
    "# PySide6 is retained; PyQt5/PyQt6/PySide2 are intentionally excluded.\n\n"
    + "\n".join(full_requirements)
    + ("\n" if full_requirements else ""),
    encoding="utf-8",
)

for filename, reqs in groups.items():
    (REQDIR / filename).write_text(
        f"# Auto-generated Phase 22 group: {filename}\n\n"
        + "\n".join(sorted(reqs, key=lambda s: req_basename(s)))
        + ("\n" if reqs else ""),
        encoding="utf-8",
    )

(REQDIR / "eli-unresolved-imports.txt").write_text(
    "# Imports that could not be mapped to a pip distribution automatically.\n"
    "# These require manual resolution or confirmation that they are local/dynamic/non-pip.\n\n"
    + "\n".join(sorted(unresolved_modules))
    + ("\n" if unresolved_modules else "NONE\n"),
    encoding="utf-8",
)

(REQDIR / "eli-qt-conflicting-declared-requirements-excluded.txt").write_text(
    "# Declared manifest requirements excluded from canonical Phase 22 full env under PySide6-only policy.\n\n"
    + "\n".join(declared_excluded_qt)
    + ("\n" if declared_excluded_qt else "NONE\n"),
    encoding="utf-8",
)

(OUT / "12_import_to_package_resolution.json").write_text(
    json.dumps({
        "resolved_import_to_package": resolved_import_to_package,
        "resolution_sources": resolution_sources,
        "unresolved_modules": unresolved_modules,
        "declared_requirements_lines": declared_clean,
        "declared_qt_conflicts_excluded": declared_excluded_qt,
        "full_requirements": full_requirements,
        "groups": groups,
    }, indent=2),
    encoding="utf-8",
)

with (OUT / "13_import_to_package_resolution.txt").open("w", encoding="utf-8") as f:
    f.write("# Import -> pip package resolution\n\n")
    for mod in sorted(resolved_import_to_package):
        pkg = resolved_import_to_package[mod]
        src = resolution_sources.get(mod, "?")
        f.write(f"{mod:<30} -> {pkg:<40} [{src}]\n")
    f.write("\n# Unresolved imports\n\n")
    if unresolved_modules:
        for mod in sorted(unresolved_modules):
            f.write(f"- {mod}\n")
    else:
        f.write("NONE\n")

PY

# ─────────────────────────────────────────────────────────────────────────────
# 4. Code/reference scans for subprocess, binaries, repos, Qt surfaces
# ─────────────────────────────────────────────────────────────────────────────

rg -n --hidden -S \
  'from (PySide6|PyQt6|PyQt5|PySide2)\b|import (PySide6|PyQt6|PyQt5|PySide2)\b|Qsci|QScintilla|qt_compat' \
  eli scripts bin ops experimental \
  --glob '*.py' \
  --glob '!ops/reports/**' \
  2>/dev/null > "$OUT/14_qt_binding_surface_hits.txt" || true

rg -n --hidden -S \
  'subprocess\.(run|Popen|check_output|check_call)|shutil\.which\(|os\.system\(|QProcess|nvidia-smi|ollama|pandoc|lualatex|xelatex|pdflatex|latexmk|ffmpeg|ffprobe|piper|aplay|paplay|playerctl|xdg-open|gio open|open -a|libreoffice|soffice|git |wpctl|pactl|pacmd|wl-copy|wl-paste|xclip|xsel|wmctrl|ydotool|wtype|grim|slurp|gnome-screenshot|scrot|tesseract|espeak|festival|arecord|parec|pw-record' \
  eli scripts bin ops experimental \
  --glob '*.py' \
  --glob '*.sh' \
  --glob '!ops/reports/**' \
  2>/dev/null > "$OUT/15_external_binary_and_subprocess_hits.txt" || true

rg -n --hidden -S \
  'github\.com|huggingface\.co|pypi\.org|git\+https|https?://|upstream|repository|repo:' \
  eli scripts bin ops experimental README* LICENSE* pyproject.toml setup.py setup.cfg \
  --glob '!ops/reports/**' \
  --glob '!*.log' \
  2>/dev/null > "$OUT/16_upstream_repo_and_url_hits.txt" || true

rg -n --hidden -S \
  '\.gguf|\.onnx|\.safetensors|\.pt\b|\.pth\b|embedding|embedder|piper|voice model|model_path|models/' \
  eli scripts bin ops experimental config \
  --glob '*.py' \
  --glob '*.json' \
  --glob '*.toml' \
  --glob '*.yaml' \
  --glob '*.yml' \
  --glob '*.sh' \
  --glob '!ops/reports/**' \
  2>/dev/null > "$OUT/17_model_asset_reference_hits.txt" || true

{
  echo "# Current runtime asset/model inventory"
  echo
  for d in models assets resources config; do
    if [ -e "$d" ]; then
      echo "================================================================================"
      echo "PATH: $d"
      echo "================================================================================"
      du -sh "$d" 2>/dev/null || true
      find "$d" -type f \
        \( \
          -name '*.gguf' \
          -o -name '*.onnx' \
          -o -name '*.safetensors' \
          -o -name '*.pt' \
          -o -name '*.pth' \
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
        | sed -n '1,800p'
      echo
    fi
  done
} > "$OUT/18_runtime_asset_model_inventory.txt"

# ─────────────────────────────────────────────────────────────────────────────
# 5. Back up old venv and create fresh one
# ─────────────────────────────────────────────────────────────────────────────

if [ -d "$VENV" ]; then
  echo "Backing up existing .venv -> $OLD_VENV_BACKUP"
  mv "$VENV" "$OLD_VENV_BACKUP"
fi

"$PYBIN" -m venv "$VENV"

"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel packaging \
  2>&1 | tee "$OUT/19_venv_bootstrap_pip_upgrade.log"

# ─────────────────────────────────────────────────────────────────────────────
# 6. Install generated full requirements
# ─────────────────────────────────────────────────────────────────────────────

INSTALL_LOG="$OUT/20_pip_install_full_requirements.log"
FAILED_REQS="$OUT/21_pip_install_failed_requirements.txt"
: > "$FAILED_REQS"

set +e
"$VENV/bin/python" -m pip install -r "$REQDIR/eli-full.txt" \
  2>&1 | tee "$INSTALL_LOG"
BULK_RC="${PIPESTATUS[0]}"
set -e

echo "BULK_INSTALL_EXIT_CODE=$BULK_RC" > "$OUT/22_bulk_install_exit_code.txt"

if [ "$BULK_RC" -ne 0 ]; then
  echo
  echo "Bulk install failed. Attempting one-by-one salvage install to identify exact blockers."
  echo

  while IFS= read -r req; do
    req="${req#"${req%%[![:space:]]*}"}"
    req="${req%"${req##*[![:space:]]}"}"
    [ -z "$req" ] && continue
    [[ "$req" == \#* ]] && continue

    echo "=== INSTALLING: $req ===" | tee -a "$OUT/23_one_by_one_install.log"
    set +e
    "$VENV/bin/python" -m pip install "$req" \
      2>&1 | tee -a "$OUT/23_one_by_one_install.log"
    RC="${PIPESTATUS[0]}"
    set -e
    if [ "$RC" -ne 0 ]; then
      echo "$req" >> "$FAILED_REQS"
    fi
  done < "$REQDIR/eli-full.txt"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. Freeze final venv and run checks
# ─────────────────────────────────────────────────────────────────────────────

"$VENV/bin/python" -m pip freeze | sort \
  > "$REQDIR/eli-full-freeze.txt"

"$VENV/bin/python" -m pip freeze | sort \
  > "$OUT/24_final_venv_freeze.txt"

set +e
"$VENV/bin/python" -m pip check \
  > "$OUT/25_pip_check.txt" 2>&1
PIP_CHECK_RC="$?"
set -e
echo "PIP_CHECK_EXIT_CODE=$PIP_CHECK_RC" >> "$OUT/25_pip_check.txt"

# ─────────────────────────────────────────────────────────────────────────────
# 8. Import spec probe for discovered third-party modules
# ─────────────────────────────────────────────────────────────────────────────

PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
"$VENV/bin/python" - <<'PY' > "$OUT/26_postinstall_import_spec_probe.txt" 2>&1
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

out_candidates = sorted(Path("ops/reports").glob("phase22_full_dependency_audit_and_venv_bootstrap_*"))
out = out_candidates[-1]
inv = json.loads((out / "05_repo_ast_import_inventory.json").read_text(encoding="utf-8"))

rows = [
    r for r in inv["imports"]
    if r["class"] == "third_party_or_unresolved"
]

print("# Post-install importlib.util.find_spec probe")
print()

missing = []
for row in rows:
    mod = row["module"]
    try:
        ok = importlib.util.find_spec(mod) is not None
    except Exception as exc:
        ok = False
        print(f"ERROR   {mod:<30} {type(exc).__name__}: {exc}")
    if ok:
        print(f"FOUND   {mod}")
    else:
        print(f"MISSING {mod}")
        missing.append(mod)

print()
print("MISSING_COUNT =", len(missing))
for mod in missing:
    print("MISSING_IMPORT =", mod)
PY

# ─────────────────────────────────────────────────────────────────────────────
# 9. ELI module import probes under fresh .venv
# ─────────────────────────────────────────────────────────────────────────────

PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
"$VENV/bin/python" - <<'PY' > "$OUT/27_eli_core_import_probe.txt" 2>&1
mods = [
    "eli",
    "eli.gui.qt_compat",
    "eli.gui.labs_tab",
    "eli.gui.eli_pro_audio_gui_MKI",
    "eli.cognition.inference_broker",
    "eli.cognition.gguf_inference",
    "eli.kernel.engine",
    "eli.execution.router_enhanced",
    "eli.execution.executor_enhanced",
]

for mod in mods:
    try:
        __import__(mod)
        print(f"IMPORT_OK   {mod}")
    except Exception as exc:
        print(f"IMPORT_FAIL {mod} :: {type(exc).__name__}: {exc}")
PY

# ─────────────────────────────────────────────────────────────────────────────
# 10. Create repo launcher using venv + repo-root PYTHONPATH
# ─────────────────────────────────────────────────────────────────────────────

cat > "$RUNNER" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
cd "\$ROOT"
source "\$ROOT/.venv/bin/activate"
export PYTHONPATH="\$ROOT\${PYTHONPATH:+:\$PYTHONPATH}"
exec python -m eli.gui.eli_pro_audio_gui_MKI "\$@"
EOF

chmod +x "$RUNNER"

# ─────────────────────────────────────────────────────────────────────────────
# 11. Create dependency/environment README
# ─────────────────────────────────────────────────────────────────────────────

cat > "$README" <<EOF
# ELI Python Environment and Dependency Files

Generated by:

\`ops/patches/phase22_full_dependency_audit_and_venv_bootstrap_v1.sh\`

Generated at:

\`$(date -Is)\`

## Canonical GUI binding

This environment is built around **PySide6**.

The generated full environment intentionally excludes:
- PyQt5
- PyQt6
- PySide2
- direct Qt conflict packages found in stale manifests

Qt/code references are still audited separately in:

\`$OUT/14_qt_binding_surface_hits.txt\`

## Generated requirements

### Full install candidate
\`requirements/generated/eli-full.txt\`

### Fully frozen resolved environment after installation
\`requirements/generated/eli-full-freeze.txt\`

### Category breakdowns
- \`requirements/generated/eli-gui-pyside6.txt\`
- \`requirements/generated/eli-local-llm.txt\`
- \`requirements/generated/eli-audio-voice.txt\`
- \`requirements/generated/eli-vision-automation.txt\`
- \`requirements/generated/eli-docs-labs-science.txt\`
- \`requirements/generated/eli-runtime-core-misc.txt\`

### Audit exception files
- \`requirements/generated/eli-unresolved-imports.txt\`
- \`requirements/generated/eli-qt-conflicting-declared-requirements-excluded.txt\`

## New venv

The new environment is:

\`$VENV\`

The previous environment, if one existed, was backed up to:

\`$OLD_VENV_BACKUP\`

## Launch ELI from the rebuilt environment

Use:

\`\`\`bash
cd $ROOT
./scripts/run_eli_repo_venv.sh
\`\`\`

This runner activates the venv and exports the repo root through \`PYTHONPATH\`, avoiding the startup-path issue caused by running a deeply nested GUI file directly.

## Full audit report

The complete dependency audit is stored in:

\`$OUT\`

Key files:

1. \`06_third_party_or_unresolved_imports.txt\`
2. \`11_declared_requirement_lines.txt\`
3. \`12_import_to_package_resolution.json\`
4. \`13_import_to_package_resolution.txt\`
5. \`14_qt_binding_surface_hits.txt\`
6. \`15_external_binary_and_subprocess_hits.txt\`
7. \`16_upstream_repo_and_url_hits.txt\`
8. \`17_model_asset_reference_hits.txt\`
9. \`18_runtime_asset_model_inventory.txt\`
10. \`21_pip_install_failed_requirements.txt\`
11. \`25_pip_check.txt\`
12. \`26_postinstall_import_spec_probe.txt\`
13. \`27_eli_core_import_probe.txt\`

## Important interpretation rule

\`eli-full.txt\` is the **generated dependency candidate**.

\`eli-full-freeze.txt\` is the **actual resolved environment lock** produced after the install pass.

For redistribution, the freeze file is the stronger reproducibility record, but the audit files should be retained because they show why those packages were included.
EOF

# ─────────────────────────────────────────────────────────────────────────────
# 12. Summary report
# ─────────────────────────────────────────────────────────────────────────────

THIRD_COUNT="$(grep -vcE '^\s*$|^#' "$OUT/06_third_party_or_unresolved_imports.txt" || true)"
UNRESOLVED_COUNT="$(grep -vcE '^\s*$|^#|^NONE$' "$REQDIR/eli-unresolved-imports.txt" || true)"
FAILED_INSTALL_COUNT="$(grep -vcE '^\s*$' "$FAILED_REQS" || true)"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 22 — Full ELI Dependency Audit + Venv Bootstrap Summary

## Root
\`$ROOT\`

## Output
\`$OUT\`

## Environment rebuild
- Fresh venv created at: \`$VENV\`
- Previous venv backup: \`$OLD_VENV_BACKUP\`
- PySide6 retained as canonical GUI stack.
- PyQt5 / PyQt6 / PySide2 excluded from generated canonical full environment.

## Scan coverage
- Full repository Python import scan executed.
- Existing manifests scanned.
- Existing venv freeze captured before replacement when available.
- Runtime asset/model references scanned.
- External subprocess/binary references scanned.
- Upstream/repo URLs scanned.

## Headline counts
- Third-party or unresolved import names found: **$THIRD_COUNT**
- Import names still unresolved after mapping: **$UNRESOLVED_COUNT**
- Requirement lines that failed during fallback one-by-one install: **$FAILED_INSTALL_COUNT**

## Generated dependency files
- \`requirements/generated/eli-full.txt\`
- \`requirements/generated/eli-full-freeze.txt\`
- \`requirements/generated/eli-gui-pyside6.txt\`
- \`requirements/generated/eli-local-llm.txt\`
- \`requirements/generated/eli-audio-voice.txt\`
- \`requirements/generated/eli-vision-automation.txt\`
- \`requirements/generated/eli-docs-labs-science.txt\`
- \`requirements/generated/eli-runtime-core-misc.txt\`
- \`requirements/generated/eli-unresolved-imports.txt\`
- \`requirements/generated/eli-qt-conflicting-declared-requirements-excluded.txt\`

## Bootstrap / launcher artifacts
- \`requirements/README_ELI_ENVIRONMENT.md\`
- \`scripts/run_eli_repo_venv.sh\`

## Inspect next
1. \`21_pip_install_failed_requirements.txt\`
2. \`25_pip_check.txt\`
3. \`26_postinstall_import_spec_probe.txt\`
4. \`27_eli_core_import_probe.txt\`
5. \`requirements/generated/eli-unresolved-imports.txt\`

## Recommended launch command after this script
\`\`\`bash
cd "$ROOT"
./scripts/run_eli_repo_venv.sh
\`\`\`
EOF

cat > "$OUT/INDEX.txt" <<EOF
00_header.txt
01_existing_venv_freeze.txt
02_existing_venv_packages_distributions.json
03_existing_dependency_manifest_paths.txt
04_existing_dependency_manifest_contents.txt
05_repo_ast_import_inventory.json
06_third_party_or_unresolved_imports.txt
07_local_imports.txt
08_stdlib_imports.txt
09_imports_inside_try_blocks.txt
10_ast_parse_errors.txt
11_declared_requirement_lines.txt
12_import_to_package_resolution.json
13_import_to_package_resolution.txt
14_qt_binding_surface_hits.txt
15_external_binary_and_subprocess_hits.txt
16_upstream_repo_and_url_hits.txt
17_model_asset_reference_hits.txt
18_runtime_asset_model_inventory.txt
19_venv_bootstrap_pip_upgrade.log
20_pip_install_full_requirements.log
21_pip_install_failed_requirements.txt
22_bulk_install_exit_code.txt
23_one_by_one_install.log
24_final_venv_freeze.txt
25_pip_check.txt
26_postinstall_import_spec_probe.txt
27_eli_core_import_probe.txt
SUMMARY.md
INDEX.txt
EOF

echo
echo "============================================================"
echo "PHASE 22 COMPLETE"
echo "============================================================"
echo "OUT=$OUT"
echo "README=$README"
echo "RUNNER=$RUNNER"
echo
cat "$OUT/SUMMARY.md"
