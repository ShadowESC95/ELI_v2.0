#!/usr/bin/env bash
# Full-project test coverage, combined across all three lanes into one auditable
# report. See docs/COVERAGE.md for the rationale and the justified exclusions.
#
#   bash scripts/coverage_full.sh
#
# Output: artifacts/coverage_report.txt (text) + artifacts/coverage_html/ (browsable).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
MODEL="${ELI_COVERAGE_MODEL:-models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf}"
mkdir -p artifacts
rm -f .coverage .coverage.*

echo "== Lane 1/4: mocked unit suite (breadth + core logic) =="
# The clean-lane files skip themselves here (mocked deps); harmless.
$PY -m coverage run -p -m pytest -q -p no:cacheprovider tests/ || true

echo "== Lane 2/4: web-server clean lane (real FastAPI) =="
ELI_ARTIFACTS_DIR="$(mktemp -d)" \
  $PY -m coverage run -p -m pytest tests/test_api_server.py --noconftest -q || true

echo "== Lane 3/4: live engine clean lane (real GGUF model) =="
if [ -f "$MODEL" ]; then
  ELI_GGUF_MODEL_PATH="$MODEL" ELI_MODEL_PATH="$MODEL" ELI_ARTIFACTS_DIR="$(mktemp -d)" \
    $PY -m coverage run -p -m pytest tests/test_engine_integration_live.py --noconftest -q || true
else
  echo "  (skipped — no model at $MODEL; set ELI_COVERAGE_MODEL)"
fi

echo "== Lane 4/4: offscreen GUI widgets (real PySide6, headless) =="
# The main window blocks on device init and stays omitted; the tab widgets construct
# fine under the offscreen Qt platform, so their __init__/layout/wiring is covered.
QT_QPA_PLATFORM=offscreen ELI_ARTIFACTS_DIR="$(mktemp -d)" \
  $PY -m coverage run -p -m pytest tests/test_gui_offscreen.py --noconftest -q || true

echo "== Combine + report =="
$PY -m coverage combine
$PY -m coverage report -m | tee artifacts/coverage_report.txt
$PY -m coverage html >/dev/null 2>&1 && echo "HTML: artifacts/coverage_html/index.html"
