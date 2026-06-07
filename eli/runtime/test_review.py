"""Full test/project run → review workflow.

One call runs the suite (or a subset), backs up the previous report, writes an
errors file capturing any failures, derives the result-relevant follow-up options,
and returns everything the GUI / the LLM need to summarise and drive a chat process:

    run_and_review() -> {ok, totals, failures, report_text, report_path,
                         backup_path, error_file, options, stdout}

The LLM summary is produced by the normal grounded pipeline (the TEST_REVIEW action
returns report_text → the engine synthesises it). `options` is a deterministic menu
tied to the actual results — each carries a chat `command` that routes to an existing
action (examine code / propose fixes / generate tests / run eval), so the user can
"run through the options" conversationally.

Pure stdlib + the existing test-report generator; no new model path.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

REPO = Path(__file__).resolve().parents[2]


def _art() -> Path:
    """Artifacts root, honouring ELI_ARTIFACTS_DIR (so tests/users can redirect)."""
    import os
    env = os.environ.get("ELI_ARTIFACTS_DIR")
    base = Path(env).expanduser() if env else (REPO / "artifacts")
    return base


def _parse_junit(path: Path) -> Tuple[Dict[str, int], List[Dict[str, str]]]:
    totals = {"total": 0, "passed": 0, "failed": 0, "xfailed": 0, "skipped": 0, "errored": 0}
    failures: List[Dict[str, str]] = []
    if not path.is_file():
        return totals, failures
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return totals, failures
    for tc in root.findall(".//testcase"):
        totals["total"] += 1
        cls = tc.get("classname", "")
        name = tc.get("name", "")
        fail = tc.find("failure")
        err = tc.find("error")
        skip = tc.find("skipped")
        if fail is not None or err is not None:
            node = fail if fail is not None else err
            totals["failed" if fail is not None else "errored"] += 1
            failures.append({
                "node": f"{cls}::{name}",
                "module": cls,
                "message": (node.get("message") or "")[:300],
            })
        elif skip is not None:
            if "xfail" in (skip.get("type") or "").lower():
                totals["xfailed"] += 1
            else:
                totals["skipped"] += 1
        else:
            totals["passed"] += 1
    return totals, failures


def _module_to_path(classname: str) -> str:
    """tests.claims.test_x → tests/claims/test_x.py (best-effort, for examine)."""
    parts = classname.split(".")
    return "/".join(parts) + ".py" if parts else classname


def build_options(totals: Dict[str, int], failures: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Deterministic, results-driven follow-up menu. Each option's `command` routes to
    an existing action when the user picks it in chat."""
    opts: List[Dict[str, str]] = []
    if failures:
        mods = sorted({f["module"] for f in failures if f.get("module")})[:4]
        paths = " ".join(_module_to_path(m) for m in mods)
        opts.append({"id": "examine", "label": f"Examine the {len(mods)} failing module(s) for errors",
                     "command": f"examine {paths} for errors"})
        opts.append({"id": "propose", "label": "Propose verified fixes (coding agent)",
                     "command": "improve your code: propose verified fixes for the failing tests"})
        opts.append({"id": "rerun", "label": "Re-run just the failing tests",
                     "command": "run the test suite"})
    if totals.get("xfailed"):
        opts.append({"id": "gaps", "label": f"Review the {totals['xfailed']} known gap(s) (xfail)",
                     "command": "analyse your failures"})
    if not failures:
        opts.append({"id": "generate", "label": "Generate more behavioural tests to grow coverage",
                     "command": "generate tests for your code"})
        opts.append({"id": "eval", "label": "Run the model-backed engine eval",
                     "command": "run the engine eval"})
    return opts


def propose_fixes(failures: List[Dict[str, str]], *, run_tier3: bool = False,
                  max_modules: int = 5) -> Dict[str, Any]:
    """Delegate failure analysis to the EXISTING code examiner, orchestrated over the
    failing modules IN PARALLEL via the DAG (run_graph). This reuses the coding/
    analysis algorithms already in place rather than reinventing them — the same
    pattern many actions should use: compose existing functions/agents, don't rebuild.
    Returns concrete per-module findings (propose-only; nothing is applied)."""
    mods: List[str] = []
    seen = set()
    for f in failures:
        p = _module_to_path(f.get("module", ""))
        if p and p not in seen and (REPO / p).exists():
            seen.add(p)
            mods.append(p)
        if len(mods) >= max_modules:
            break
    if not mods:
        return {"ok": False, "reason": "no resolvable failing modules", "proposals": []}
    try:
        from eli.core.dag import Task, run_graph
        from eli.runtime.code_examiner import examine

        def _mk(path: str):
            def _run(ctx):
                findings = examine([REPO / path], run_tier3=run_tier3)
                return [fn.to_dict() for fn in findings]
            return _run

        tasks = [Task(id=m, run=_mk(m), critical=False) for m in mods]
        report = run_graph(tasks, max_workers=max(2, len(mods)))
        proposals = []
        for m in mods:
            o = report.outcomes.get(m)
            if o is not None and o.ok and o.result:
                proposals.append({"module": m, "findings": o.result})
        return {"ok": True, "proposals": proposals, "examined": mods,
                "orchestration": report.to_dict()}
    except Exception as e:
        log.debug(f"[TEST_REVIEW] propose_fixes failed: {e}")
        return {"ok": False, "reason": str(e), "proposals": []}


def _render_errors(ts: str, totals: Dict[str, int], failures: List[Dict[str, str]],
                   target: str) -> str:
    lines = [f"# ELI — Test errors backup ({ts})",
             f"\nTarget `{target}` — {totals.get('failed', 0)} failed, "
             f"{totals.get('errored', 0)} errored of {totals.get('total', 0)}.\n",
             "## Failing tests (possible errors)\n"]
    for f in failures:
        lines.append(f"- `{f['node']}`\n  - {f.get('message') or '(no message)'}")
    return "\n".join(lines) + "\n"


def run_and_review(target: str = "tests/", *, timeout: int = 3600,
                   on_progress: Optional[Any] = None) -> Dict[str, Any]:
    """Run the suite, back up the prior report, write an errors file on failure,
    and return the results + a results-driven options menu."""
    art = _art()
    reports_dir = art / "test_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    def _say(m: str) -> None:
        if on_progress:
            try:
                on_progress(m)
            except Exception:
                pass

    # 1) Back up the previous report before it is overwritten.
    prev = art / "test_report.md"
    backup_path = None
    if prev.is_file():
        backup_path = reports_dir / f"test_report_{ts}.bak.md"
        try:
            shutil.copy2(prev, backup_path)
        except Exception:
            backup_path = None

    # 2) Run the suite (writes test_report.md + the junit via the conftest hook /
    #    run_test_report).
    _say(f"running {target} …")
    try:
        r = subprocess.run([sys.executable, "tools/run_test_report.py", target],
                           cwd=str(REPO), capture_output=True, text=True, timeout=timeout)
        stdout = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"test run exceeded {timeout}s", "options": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "options": []}

    # 3) Parse + write an errors backup file when there are failures.
    totals, failures = _parse_junit(art / "test_report.junit.xml")
    error_file = None
    if failures:
        error_file = reports_dir / f"errors_{ts}.md"
        try:
            error_file.write_text(_render_errors(ts, totals, failures, target), encoding="utf-8")
        except Exception:
            error_file = None

    # On failure, delegate concrete analysis to the code examiner (orchestrated,
    # parallel) so the review already points at real issues — propose-only.
    fix_analysis = propose_fixes(failures) if failures else {"ok": True, "proposals": []}

    options = build_options(totals, failures)
    report_text = ""
    try:
        if prev.is_file():
            report_text = prev.read_text(encoding="utf-8")[:6000]
    except Exception:
        report_text = stdout[-2000:]
    _say("done")
    return {
        "ok": not failures,
        "totals": totals,
        "failures": failures[:50],
        "report_text": report_text,
        "report_path": str(prev),
        "backup_path": str(backup_path) if backup_path else None,
        "error_file": str(error_file) if error_file else None,
        "options": options,
        "fix_analysis": fix_analysis,
        "stdout": stdout[-1500:],
    }


__all__ = ["run_and_review", "build_options", "propose_fixes"]
