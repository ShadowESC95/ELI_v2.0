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

echo "== Lane 1/3: mocked unit suite (breadth + core logic) =="
# The two clean-lane files skip themselves here (mocked deps); harmless.
$PY -m coverage run -p -m pytest -q -p no:cacheprovider tests/ || true

echo "== Lane 2/3: web-server clean lane (real FastAPI) =="
ELI_ARTIFACTS_DIR="$(mktemp -d)" \
  $PY -m coverage run -p -m pytest tests/test_api_server.py --noconftest -q || true

echo "== Lane 3/3: live engine clean lane (real GGUF model) =="
if [ -f "$MODEL" ]; then
  ELI_GGUF_MODEL_PATH="$MODEL" ELI_MODEL_PATH="$MODEL" ELI_ARTIFACTS_DIR="$(mktemp -d)" \
    $PY -m coverage run -p -m pytest tests/test_engine_integration_live.py --noconftest -q || true
else
  echo "  (skipped — no model at $MODEL; set ELI_COVERAGE_MODEL)"
fi

echo "== Combine + report =="
$PY -m coverage combine
$PY -m coverage report -m | tee artifacts/coverage_report.txt
$PY -m coverage html >/dev/null 2>&1 && echo "HTML: artifacts/coverage_html/index.html"
