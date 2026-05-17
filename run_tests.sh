#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  ELI MKXI — Test Runner
#  Usage:
#    ./run_tests.sh              # full suite
#    ./run_tests.sh imports      # imports only
#    ./run_tests.sh fast         # skip slow integration tests
#    ./run_tests.sh html         # full suite + HTML report
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$SCRIPT_DIR/tests"
REPORTS_DIR="$SCRIPT_DIR/test_reports"

mkdir -p "$REPORTS_DIR"

MODE="${1:-full}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║       ELI MKXI — Test Suite  ($TIMESTAMP)        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

BASE_ARGS="-v --tb=short --color=yes"

case "$MODE" in
  imports)
    echo "▶  Running IMPORT tests only..."
    python3 -m pytest "$TESTS_DIR/test_00_imports.py" $BASE_ARGS
    ;;
  fast)
    echo "▶  Running fast tests (skip test_11_integration)..."
    python3 -m pytest "$TESTS_DIR" $BASE_ARGS --ignore="$TESTS_DIR/test_11_integration.py"
    ;;
  html)
    echo "▶  Running full suite with HTML report..."
    pip install pytest-html -q
    REPORT="$REPORTS_DIR/eli_report_$TIMESTAMP.html"
    python3 -m pytest "$TESTS_DIR" $BASE_ARGS \
      --html="$REPORT" --self-contained-html \
      --junitxml="$REPORTS_DIR/junit_$TIMESTAMP.xml" \
      || true
    echo ""
    echo "📄  HTML report: $REPORT"
    ;;
  full|*)
    echo "▶  Running full test suite..."
    python3 -m pytest "$TESTS_DIR" $BASE_ARGS \
      --junitxml="$REPORTS_DIR/junit_$TIMESTAMP.xml" \
      || true
    ;;
esac

echo ""
echo "══════════════════════════════════════════════════"
echo "  Done. Reports saved to: $REPORTS_DIR"
echo "══════════════════════════════════════════════════"
