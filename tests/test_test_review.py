"""Tests for the test/project run → review workflow (eli/runtime/test_review.py)."""
from __future__ import annotations

from pathlib import Path

import eli.runtime.test_review as TR


_JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite>
  <testcase classname="tests.test_a" name="test_pass"/>
  <testcase classname="tests.test_a" name="test_fail"><failure message="assert 1==2">boom</failure></testcase>
  <testcase classname="tests.test_b" name="test_err"><error message="ImportError x">trace</error></testcase>
  <testcase classname="tests.test_c" name="test_xf"><skipped type="pytest.xfail">gap</skipped></testcase>
  <testcase classname="tests.test_c" name="test_skip"><skipped type="pytest.skip">later</skipped></testcase>
</testsuite></testsuites>
"""


def test_parse_junit_counts_and_failures(tmp_path):
    j = tmp_path / "j.xml"
    j.write_text(_JUNIT)
    totals, failures = TR._parse_junit(j)
    assert totals["total"] == 5
    assert totals["passed"] == 1 and totals["failed"] == 1 and totals["errored"] == 1
    assert totals["xfailed"] == 1 and totals["skipped"] == 1
    nodes = {f["node"] for f in failures}
    assert "tests.test_a::test_fail" in nodes and "tests.test_b::test_err" in nodes


def test_build_options_for_failures():
    failures = [{"node": "tests.test_a::x", "module": "tests.test_a", "message": "m"}]
    opts = TR.build_options({"xfailed": 0}, failures)
    ids = {o["id"] for o in opts}
    assert {"examine", "propose", "rerun"} <= ids
    examine = next(o for o in opts if o["id"] == "examine")
    assert "tests/test_a.py" in examine["command"]


def test_build_options_clean_run_offers_growth():
    opts = TR.build_options({"xfailed": 2}, [])
    ids = {o["id"] for o in opts}
    assert "generate" in ids and "eval" in ids and "gaps" in ids
    assert all("command" in o and "label" in o for o in opts)


def test_run_and_review_integration():
    # light: run a small real target; the subprocess + parent both resolve the same
    # ELI_ARTIFACTS_DIR (the in-project test dir from conftest), so totals are parsed.
    res = TR.run_and_review("tests/test_lora_pipeline.py", timeout=300)
    assert "totals" in res and res["totals"]["total"] >= 1
    assert isinstance(res["options"], list) and res["options"]
    if res["ok"]:
        assert res["error_file"] is None
    assert res["report_path"]
