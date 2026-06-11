"""Code-mode — the model writes a small program against ELI's own capabilities.

This is the planner→run→retry loop (the same shape as the coding agent) pointed at
`eli.api` instead of producing a standalone script: the model emits a short Python program
that calls `api.*`, which is gated (Full Control), AST-whitelisted, and run in-process by
`restricted_exec`. The reply is then grounded in the program's real `result`.

`generate` is injected (a `prompt -> text` callable) so the whole loop is testable without
a model — exactly like `eli.coding.agent`.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from eli.coding.restricted_exec import run_restricted

GenerateFn = Callable[[str], str]

_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.S | re.I)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _build_prompt(request: str, actions: List[str], *, prev_code: str = "", error: str = "") -> str:
    helpers = (
        "api.call('ACTION_NAME', arg=value, ...)   # run any action, returns a result dict\n"
        "api.summarize_file(path)\n"
        "api.check_job(job_id)\n"
        "api.background_jobs()\n"
    )
    catalogue = ("\nAvailable actions (subset): " + ", ".join(actions[:40])) if actions else ""
    base = (
        "You control ELI by writing a SHORT Python program. Rules:\n"
        "- Call ELI ONLY through `api` (see helpers below). No imports, no def/class/lambda.\n"
        "- Use only plain Python: variables, loops, comprehensions, arithmetic, f-strings.\n"
        "- Assign the final answer to a variable named `result`.\n"
        "- Output ONLY the program (optionally in a ```python block), nothing else.\n\n"
        f"Helpers:\n{helpers}{catalogue}\n\n"
        f"TASK: {request}\n"
    )
    if error:
        base += (
            f"\nYour previous program was rejected/failed:\n{prev_code}\n\nERROR: {error}\n"
            "Return a corrected program (same rules).\n"
        )
    return base


def run_code_mode(
    request: str,
    generate: GenerateFn,
    *,
    api: Any = None,
    max_attempts: int = 2,
) -> Dict[str, Any]:
    """Generate → gate+validate+run → (retry on failure) → grounded result dict.

    Returns: {ok, result, stdout, code, attempts} on success; {ok:False, blocked:True,
    message} if Full Control is off; {ok:False, error, code, attempts} if it couldn't
    produce a valid/working program within max_attempts.
    """
    if api is None:
        from eli.api import api as _default_api
        api = _default_api
    try:
        actions = api.actions() if hasattr(api, "actions") else []
    except Exception:
        actions = []

    prev_code, last_error = "", ""
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        prompt = _build_prompt(request, actions, prev_code=prev_code, error=last_error)
        code = _strip_fences(generate(prompt))
        r = run_restricted(code, api=api)

        if r.blocked:  # Full Control off — terminal, no retry, no execution happened
            return {"ok": False, "blocked": True,
                    "message": r.meta.get("reason", "code-mode requires Full Control"),
                    "attempts": attempt}
        if r.ok:
            return {"ok": True, "result": r.result, "stdout": r.stdout,
                    "code": code, "attempts": attempt}

        last_error = r.validation_error or r.runtime_error or "unknown failure"
        prev_code = code

    return {"ok": False, "error": last_error, "code": prev_code, "attempts": max_attempts}
