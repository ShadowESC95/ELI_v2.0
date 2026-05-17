#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase17_packaging_runtime_readiness_audit_${STAMP}"

mkdir -p "$OUT"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 17 — Packaging + Runtime Readiness Audit"
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
  echo "# Phase 17 — Packaging + Runtime Readiness Audit"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- Shell PYTHONPATH: \`${PYTHONPATH-<unset>}\`"
  echo
} > "$OUT/SUMMARY.md"

echo "=== 1. High-level package/runtime inventory ==="
{
  echo "ROOT=$ROOT"
  echo
  echo ".venv:"
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "FOUND $ROOT/.venv/bin/python"
    "$ROOT/.venv/bin/python" --version || true
  else
    echo "MISSING $ROOT/.venv/bin/python"
  fi
  echo
  echo "Project Python currently visible:"
  command -v python3 || true
  python3 --version || true
  echo
  echo "ELI launchers:"
  ls -l "$ROOT/bin/elix" "$ROOT/bin/elix.real" 2>/dev/null || true
  echo
  echo "Model files:"
  find "$ROOT/models" -type f -name '*.gguf' 2>/dev/null | sort || true
  echo
  echo "Embedder path expected by previous logs:"
  EMBED="$ROOT/models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
  if [ -f "$EMBED" ]; then
    echo "FOUND $EMBED"
  else
    echo "MISSING $EMBED"
  fi
  echo
  echo "Piper packaged assets:"
  find "$ROOT/tts_piper" -maxdepth 4 -type f 2>/dev/null | sort || true
} | tee "$OUT/01_inventory.txt"
echo

echo "=== 2. Pyproject packaging policy and external asset references ==="
{
  echo "--- pyproject dependency / optional dependency / package-data sections ---"
  sed -n '/^\[project\]/,/^\[project.urls\]/p' "$ROOT/pyproject.toml" 2>/dev/null || true
  echo
  sed -n '/^\[tool.setuptools.package-data\]/,$p' "$ROOT/pyproject.toml" 2>/dev/null || true
  echo
  echo "--- Does pyproject mention external runtime asset roots? ---"
  grep -RIn --color=never \
    -E 'tts_piper|models/|models"|bin/elix|artifacts|embeddings' \
    "$ROOT/pyproject.toml" || true
} | tee "$OUT/02_pyproject_packaging_policy.txt"
echo

echo "=== 3. Qt binding policy versus actual import resolution ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

payload = {
    "qt_compat_import": None,
    "qt_api": None,
    "pyqt6_available": None,
    "pyside6_available": None,
    "pyqt5_available": None,
    "labs_qt_api": None,
    "error": None,
}

try:
    import importlib.util

    payload["pyside6_available"] = importlib.util.find_spec("PySide6") is not None
    payload["pyqt6_available"] = importlib.util.find_spec("PyQt6") is not None
    payload["pyqt5_available"] = importlib.util.find_spec("PyQt5") is not None

    from eli.gui import qt_compat
    payload["qt_compat_import"] = "OK"
    payload["qt_api"] = getattr(qt_compat, "QT_API", None)

    from eli.gui import labs_tab
    payload["labs_qt_api"] = getattr(labs_tab, "_QT", None)

except Exception as exc:
    payload["error"] = f"{type(exc).__name__}: {exc}"

(out / "03_qt_policy_runtime.json").write_text(
    json.dumps(payload, indent=2),
    encoding="utf-8",
)

for key, value in payload.items():
    print(f"{key}={value!r}")
PY
echo

echo "=== 4. Launcher behavior audit: elix / elix.real model/env assumptions ==="
{
  echo "--- bin/elix model and env references ---"
  grep -nE \
    'MODEL|GGUF|ELIX_MODEL_DIR|ELI_GGUF_MODEL_PATH|\.env\.mkxi|models|setup|picker' \
    "$ROOT/bin/elix" 2>/dev/null || true
  echo
  echo "--- bin/elix.real env/runtime references ---"
  grep -nE \
    'VENV|\.venv|PYTHONPATH|ELI_PROJECT_ROOT|MODEL|GGUF|runtime_snapshot|python' \
    "$ROOT/bin/elix.real" 2>/dev/null || true
} | tee "$OUT/04_launcher_audit.txt"
echo

echo "=== 5. Asset paths referenced by source code ==="
{
  echo "--- Embedding/model path references ---"
  grep -RIn --color=never \
    -E 'nomic|embeddings|embed.*gguf|models/embeddings|embedding.*model' \
    "$ROOT/eli" "$ROOT/config" "$ROOT/bin" 2>/dev/null || true
  echo
  echo "--- Piper/TTS path references ---"
  grep -RIn --color=never \
    -E 'tts_piper|models/tts/piper|ELI_PIPER|piper' \
    "$ROOT/eli" "$ROOT/config" "$ROOT/bin" 2>/dev/null || true
  echo
  echo "--- Image/model path references ---"
  grep -RIn --color=never \
    -E 'models/image|image_engine|diffusers|stable-diffusion|safetensors' \
    "$ROOT/eli" "$ROOT/config" "$ROOT/bin" 2>/dev/null || true
} | tee "$OUT/05_asset_path_references.txt"
echo

echo "=== 6. Build-manifest candidates ==="
{
  echo "MANIFEST.in:"
  if [ -f "$ROOT/MANIFEST.in" ]; then
    cat "$ROOT/MANIFEST.in"
  else
    echo "MISSING"
  fi
  echo
  echo "setup.cfg:"
  if [ -f "$ROOT/setup.cfg" ]; then
    cat "$ROOT/setup.cfg"
  else
    echo "MISSING"
  fi
  echo
  echo "setup.py:"
  if [ -f "$ROOT/setup.py" ]; then
    sed -n '1,240p' "$ROOT/setup.py"
  else
    echo "MISSING"
  fi
} | tee "$OUT/06_build_manifest_candidates.txt"
echo

echo "=== 7. Candidate non-Python assets outside eli/ that redistribution may need ==="
{
  for path in \
    "$ROOT/bin" \
    "$ROOT/models" \
    "$ROOT/tts_piper" \
    "$ROOT/config" \
    "$ROOT/scripts" \
    "$ROOT/assets"
  do
    if [ -e "$path" ]; then
      echo "FOUND $path"
      find "$path" -maxdepth 3 -type f 2>/dev/null | sort | sed 's/^/  /'
      echo
    else
      echo "MISSING $path"
      echo
    fi
  done
} | tee "$OUT/07_external_assets_inventory.txt"
echo

echo "=== 8. Lightweight code health confirmation after Phase 16C ==="
{
  python3 -m py_compile \
    "$ROOT/eli/runtime/control_contracts.py" \
    "$ROOT/eli/learning/dataset_builder.py" \
    "$ROOT/eli/learning/dataset_filters.py" \
    "$ROOT/eli/gui/labs_tab.py" \
    "$ROOT/eli/runtime/deterministic_introspection.py"

  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"

  echo "PY_COMPILE_OK"
  echo "COMPILEALL_OK"
} | tee "$OUT/08_compile_confirmation.txt"
echo

echo "=== 9. Packaging/runtime risk summary generator ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

risks = []

if not (root / ".venv" / "bin" / "python").exists():
    risks.append({
        "severity": "high",
        "issue": "No project .venv present",
        "impact": "ELI currently depends on ambient system Python packages; redistribution/install reproducibility is not proven.",
    })

embed = root / "models" / "embeddings" / "nomic-embed-text-v1.5.Q4_K_M.gguf"
if not embed.exists():
    risks.append({
        "severity": "high",
        "issue": "Expected nomic GGUF embedder missing",
        "impact": "Vector store / semantic recall falls back to keyword behavior or degrades.",
    })

pyproject = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
for external in ("tts_piper", "models", "bin/elix"):
    if external not in pyproject:
        risks.append({
            "severity": "medium",
            "issue": f"pyproject.toml does not explicitly mention external asset root: {external}",
            "impact": "A plain wheel/package build may omit runtime assets unless a separate installer/bundler supplies them.",
        })

manifest_present = (root / "MANIFEST.in").exists()
if not manifest_present:
    risks.append({
        "severity": "medium",
        "issue": "MANIFEST.in missing",
        "impact": "Source-distribution inclusion of non-package assets is not declared in the standard setuptools manifest path.",
    })

payload = {"risks": risks}
(out / "09_packaging_runtime_risks.json").write_text(
    json.dumps(payload, indent=2),
    encoding="utf-8",
)

for risk in risks:
    print(f"[{risk['severity'].upper()}] {risk['issue']}")
    print(f"  {risk['impact']}")
PY
echo

echo "=== 10. Git status ==="
{
  git status --short 2>/dev/null || true
} | tee "$OUT/10_git_status.txt"
echo

{
  echo "## Audit conclusion"
  echo
  echo "This phase is audit-only. It does not create a venv, install dependencies, download models, or alter packaging manifests."
  echo
  echo "It records the remaining redistributable-runtime risks before the next repair phase:"
  echo
  echo "1. missing project .venv,"
  echo "2. missing nomic embedding GGUF,"
  echo "3. PySide6 package policy versus current local source runtime binding,"
  echo "4. external runtime asset roots that may not be represented in the Python packaging manifest."
  echo
  echo "## Read these first"
  echo
  echo "- \`03_qt_policy_runtime.json\`"
  echo "- \`04_launcher_audit.txt\`"
  echo "- \`05_asset_path_references.txt\`"
  echo "- \`07_external_assets_inventory.txt\`"
  echo "- \`09_packaging_runtime_risks.json\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 17 COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/09_packaging_runtime_risks.json"
echo "======================================================================"
