#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  ELI v2.0 — Test Runner
#  Usage:
#    ./run_tests.sh              # full suite
#    ./run_tests.sh claims       # bootstrap manifest + claims suite
#    ./run_tests.sh imports      # imports only
#    ./run_tests.sh fast         # skip slow integration tests
#    ./run_tests.sh html         # full suite + HTML report
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$SCRIPT_DIR/tests"
REPORTS_DIR="$SCRIPT_DIR/test_reports"
PY="${SCRIPT_DIR}/.venv/bin/python"
if [ ! -x "$PY" ]; then
    PY="python3"
fi

mkdir -p "$REPORTS_DIR"

# Ensure subprocess API drivers and lint/MQTT test deps are present on every OS.
if [ -f "$SCRIPT_DIR/requirements-test.txt" ]; then
    "$PY" -m pip install -q -r "$SCRIPT_DIR/requirements-test.txt" 2>/dev/null || true
fi

MODE="${1:-full}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║       ELI v2.0 — Test Suite  ($TIMESTAMP)        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

BASE_ARGS="-v --tb=short --color=yes"

case "$MODE" in
  claims)
    echo "▶  Bootstrapping claims artifacts (manifest + blueprints)..."
    "$PY" "$SCRIPT_DIR/tools/bootstrap_claims_artifacts.py"
    echo "▶  Running claims-verification suite..."
    "$PY" -m pytest "$TESTS_DIR/claims/" $BASE_ARGS
    ;;
  imports)
    echo "▶  Running IMPORT tests only..."
    "$PY" -m pytest "$TESTS_DIR/test_00_imports.py" $BASE_ARGS
    ;;
  fast)
    echo "▶  Running fast tests (skip test_11_integration)..."
    "$PY" -m pytest "$TESTS_DIR" $BASE_ARGS --ignore="$TESTS_DIR/test_11_integration.py"
    ;;
  html)
    echo "▶  Running full suite with HTML report..."
    pip install pytest-html -q
    REPORT="$REPORTS_DIR/eli_report_$TIMESTAMP.html"
    "$PY" -m pytest "$TESTS_DIR" $BASE_ARGS \
      --html="$REPORT" --self-contained-html \
      --junitxml="$REPORTS_DIR/junit_$TIMESTAMP.xml" \
      || true
    echo ""
    echo "📄  HTML report: $REPORT"
    ;;
  full|*)
    echo "▶  Running full test suite..."
    "$PY" -m pytest "$TESTS_DIR" $BASE_ARGS \
      --junitxml="$REPORTS_DIR/junit_$TIMESTAMP.xml" \
      || true
    ;;
esac

echo ""
echo "══════════════════════════════════════════════════"
echo "  Done. Reports saved to: $REPORTS_DIR"
echo "══════════════════════════════════════════════════"
