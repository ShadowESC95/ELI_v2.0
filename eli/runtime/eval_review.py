"""Eval + LLM-judge board, in the shape Labs ▸ Test & Review already renders.

`tools/eval/` has carried a real eval harness for a long time — a router/executor
board that needs no model, engine cases that exercise the live pipeline, and rubric
assertions graded by ELI's OWN local model (never a cloud judge). All of it was
reachable only from a terminal, so a regression board that exists to be watched was
invisible in the product.

This adapts `run_eval.run_board()` into the same dict `eli.runtime.test_review`
returns, so the existing table, detail pane and click-to-fix handoff render eval
failures with no changes to the tab's rendering code.

In-process on purpose: the rubric judge asks the already-loaded chat model. Running
the board in a subprocess would load a second copy of the model into the same VRAM.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional


def _harness():
    """Import the eval harness, tolerating a build that did not ship tools/."""
    try:
        from tools.eval import run_eval
        return run_eval
    except Exception:
        try:
            from eli.core.paths import project_root
            root = str(project_root())
        except Exception:
            root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.insert(0, root)
        from tools.eval import run_eval  # noqa: F811
        return run_eval


def available() -> bool:
    try:
        _harness()
        return True
    except Exception:
        return False


def run_eval_board(target: str = "router", *, smoke: bool = False,
                   case_filter: str = "",
                   on_case: Optional[Callable[[str, int, int], None]] = None) -> dict[str, Any]:
    """Run the board and return it in the Test & Review result shape.

    `target`: router (instant, model-free) · engine (needs the model) · all.
    """
    try:
        run_eval = _harness()
    except Exception as exc:
        return {"error": f"eval harness unavailable in this build: {exc}"}

    try:
        board = run_eval.run_board(target, case_filter=case_filter, smoke=smoke,
                                   on_case=on_case)
    except Exception as exc:
        return {"error": f"eval board failed: {exc}"}

    failures = []
    for rec in board["records"]:
        if rec.get("status") not in ("fail", "error"):
            continue
        failed_checks = [c for c in (rec.get("checks") or []) if c.startswith("✗")]
        message_parts = []
        if rec.get("error"):
            message_parts.append(f"driver raised: {rec['error']}")
        if rec.get("prompt"):
            message_parts.append(f"prompt: {rec['prompt']}")
        if failed_checks:
            message_parts.append("failed checks:\n  " + "\n  ".join(failed_checks))
        if rec.get("answer"):
            message_parts.append(f"answer: {rec['answer']}")
        res = rec.get("result") or {}
        if res:
            message_parts.append("telemetry: " + ", ".join(
                f"{k}={v}" for k, v in res.items() if v is not None))
        failures.append({
            "node": f"eval::{rec['id']}",
            # The tab derives a "module" from the node for the code examiner; an eval
            # case is not a file, so it stays symbolic and the examiner simply finds
            # nothing rather than trying to lint a path that does not exist.
            "message": "\n\n".join(message_parts) or "case failed",
        })

    total = board["total"]
    return {
        "ok": board["ok"],
        "kind": "eval",
        "target": target,
        "model": board.get("model"),
        "totals": {
            "passed": board["passed"],
            "failed": board["failed"],
            "errored": 0,
            "xfailed": board["skipped"],
            "total": total,
        },
        "failures": failures,
        "options": ([] if board["ok"] else [{
            "id": "explain_eval_failures",
            "label": "Ask ELI what these eval failures mean",
            "command": ("Look at the failing eval cases in the Test & Review panel and "
                        "explain what behaviour regressed and where in the code to look."),
        }]),
        "summary": (f"eval [{target}] — {board['passed']} passed, {board['failed']} failed, "
                    f"{board['skipped']} skipped of {total}"),
    }


__all__ = ["run_eval_board", "available"]
