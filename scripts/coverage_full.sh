#!/usr/bin/env bash
# Full-project test coverage, combined across all four lanes into one auditable
# report. See docs/COVERAGE.md for the rationale and the justified exclusions.
#
#   bash scripts/coverage_full.sh
#
# Output: artifacts/coverage_report.txt (text) + artifacts/coverage_html/ (browsable).
# Every lane runs in the sandbox tests/conftest.py sets up for the suite (every store, the
# settings, the audit chain and its key in a temp folder of the run's own; no display, sound or network),
# so no lane writes to the checkout's artifacts/db. A lane that fails is named at the end and
# the script exits 1; the report is written either way.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
MODEL="${ELI_COVERAGE_MODEL:-models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf}"
mkdir -p artifacts
rm -f .coverage .coverage.*
FAILED=""

lane() {   # lane NAME COMMAND...: run it, and remember it when it fails
  local name="$1"
  shift
  "$@" || FAILED="${FAILED}${FAILED:+, }${name} (exit $?)"
}

echo "== Lane 1/4: full suite (breadth + core logic) =="
lane "1 full suite" $PY -m coverage run -p -m pytest -q -p no:cacheprovider tests/

echo "== Lane 2/4: web server (real FastAPI) =="
lane "2 web server" $PY -m coverage run -p -m pytest -q -p no:cacheprovider tests/test_api_server.py

echo "== Lane 3/4: live engine (real GGUF model) =="
if [ -f "$MODEL" ]; then
  # tests/conftest.py's small_chat_model fixture takes the model from ELI_MODEL_PATH.
  lane "3 live engine" env ELI_MODEL_PATH="$MODEL" ELI_GGUF_MODEL_PATH="$MODEL" \
    $PY -m coverage run -p -m pytest -q -p no:cacheprovider tests/test_engine_integration_live.py
else
  echo "  (skipped — no model at $MODEL; set ELI_COVERAGE_MODEL)"
fi

echo "== Lane 4/4: offscreen GUI widgets (real PySide6, headless) =="
# The main window blocks on device init and stays omitted; the tab widgets construct
# fine under the offscreen Qt platform, so their __init__/layout/wiring is covered.
lane "4 offscreen GUI" env QT_QPA_PLATFORM=offscreen \
  $PY -m coverage run -p -m pytest -q -p no:cacheprovider tests/test_gui_offscreen.py

echo "== Combine + report =="
$PY -m coverage combine
$PY -m coverage report -m | tee artifacts/coverage_report.txt
$PY -m coverage html >/dev/null 2>&1 && echo "HTML: artifacts/coverage_html/index.html"

if [ -n "$FAILED" ]; then
  echo "Lanes that failed: $FAILED" >&2
  exit 1
fi
