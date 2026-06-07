#!/usr/bin/env python3
"""Run the test suite and emit a results DOCUMENT (artifacts/test_report.md).

The suite-vs-claims examination, turned into a readable report: totals, the
claims-suite breakdown, per-file pass/fail/xfail counts, and any failures. Pure
stdlib (parses pytest's JUnit XML). This is the artifact ELI can later read and
summarise in chat (see the proposal in the blueprints).

Usage:
    python tools/run_test_report.py            # full suite
    python tools/run_test_report.py tests/claims   # a subset
"""
from __future__ import annotations

import datetime
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "artifacts" / "test_report.md"
JUNIT = REPO / "artifacts" / "test_report.junit.xml"


def run(target: str) -> int:
    JUNIT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider",
           f"--junitxml={JUNIT}"]
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def report() -> dict:
    tree = ET.parse(JUNIT)
    root = tree.getroot()
    suites = root.findall(".//testsuite") or [root]
    totals = defaultdict(int)
    per_file = defaultdict(lambda: defaultdict(int))
    failures = []
    for ts in suites:
        for tc in ts.findall("testcase"):
            f = tc.get("file") or tc.get("classname", "?")
            per_file[f]["total"] += 1
            totals["total"] += 1
            if tc.find("failure") is not None or tc.find("error") is not None:
                per_file[f]["failed"] += 1
                totals["failed"] += 1
                failures.append(f"{tc.get('classname')}::{tc.get('name')}")
            elif tc.find("skipped") is not None:
                kind = (tc.find("skipped").get("type") or "").lower()
                if "xfail" in kind:
                    per_file[f]["xfailed"] += 1; totals["xfailed"] += 1
                else:
                    per_file[f]["skipped"] += 1; totals["skipped"] += 1
            else:
                per_file[f]["passed"] += 1; totals["passed"] += 1
    return {"totals": dict(totals), "per_file": per_file, "failures": failures}


def write(data: dict, target: str) -> None:
    t = data["totals"]
    lines = [
        "# ELI — Test Suite Report",
        f"\n*Generated {datetime.datetime.now().isoformat(timespec='seconds')} · target `{target}`*\n",
        "## Totals\n",
        f"- **Total:** {t.get('total', 0)}",
        f"- **Passed:** {t.get('passed', 0)}",
        f"- **Failed:** {t.get('failed', 0)}",
        f"- **xfailed (known gaps):** {t.get('xfailed', 0)}",
        f"- **Skipped:** {t.get('skipped', 0)}",
        f"\n**Verdict:** {'✅ GREEN' if t.get('failed', 0) == 0 else '❌ FAILURES PRESENT'}\n",
        "## Per-file\n",
        "| Test file | Total | Pass | Fail | xfail | Skip |",
        "|---|---|---|---|---|---|",
    ]
    for f in sorted(data["per_file"]):
        c = data["per_file"][f]
        lines.append(f"| `{f}` | {c['total']} | {c['passed']} | {c['failed']} | "
                     f"{c['xfailed']} | {c['skipped']} |")
    if data["failures"]:
        lines.append("\n## Failures\n")
        lines += [f"- `{x}`" for x in data["failures"]]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "tests/"
    rc = run(target)
    try:
        data = report()
        write(data, target)
        print(f"Wrote {OUT} — {data['totals'].get('passed', 0)} passed, "
              f"{data['totals'].get('failed', 0)} failed, "
              f"{data['totals'].get('xfailed', 0)} xfailed")
    except Exception as e:
        print(f"report generation failed: {e}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
