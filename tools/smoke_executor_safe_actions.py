#!/usr/bin/env python3
from __future__ import annotations

import importlib
import inspect
import json
import traceback
from typing import Any, Dict


def get_executor():
    mod = importlib.import_module("eli.execution.executor_enhanced")
    fn = getattr(mod, "execute", None)
    if not callable(fn):
        raise RuntimeError("eli.execution.executor_enhanced.execute is not callable")
    return fn


def call_execute(fn, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
    attempts = [
        lambda: fn(action, args),
        lambda: fn(action=action, args=args),
        lambda: fn({"action": action, "args": args}),
        lambda: fn({"action": action, **args}),
    ]

    errors = []

    for attempt in attempts:
        try:
            result = attempt()
            if isinstance(result, dict):
                return result
            return {
                "ok": False,
                "action": action,
                "error": f"Executor returned non-dict result: {type(result).__name__}",
                "result_repr": repr(result),
            }
        except TypeError as exc:
            errors.append(str(exc))
        except Exception as exc:
            return {
                "ok": False,
                "action": action,
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            }

    return {
        "ok": False,
        "action": action,
        "error": "Could not call executor with known signatures.",
        "signature_errors": errors,
    }


def main() -> int:
    fn = get_executor()

    print("=== Executor Safe Smoke Test ===")
    print("executor:", fn)
    try:
        print("signature:", inspect.signature(fn))
    except Exception as exc:
        print("signature: unavailable:", exc)

    cases = [
        ("SYSTEM_STATS", {}),
        ("CPU_USAGE", {}),
        ("RAM_USAGE", {}),
        ("WEB_SEARCH", {}),          # should fail gracefully: no query
        ("POMODORO_STATUS", {}),
        ("LIST_NOTES", {}),
        ("SEARCH_NOTES", {}),        # should fail gracefully: no query
    ]

    failures = []

    for action, args in cases:
        print()
        print(f"--- {action} ---")
        result = call_execute(fn, action, args)
        print(json.dumps(result, indent=2, default=str)[:4000])

        if not isinstance(result, dict):
            failures.append(f"{action}: non-dict result")
            continue

        # Hard failure only means exception/signature/non-dict.
        # Some actions are allowed to return ok=False for missing arguments.
        if "traceback" in result:
            failures.append(f"{action}: raised exception")

        if "Could not call executor" in str(result.get("error", "")):
            failures.append(f"{action}: executor call signature failed")

    print()
    print("=== Summary ===")
    print(f"failures: {len(failures)}")
    for item in failures:
        print("FAIL:", item)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
