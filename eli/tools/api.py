"""eli.api — a small, curated callable surface over ELI's action executor.

Sugar, not a new execution path: code written in code-mode reads cleanly —
`api.call("SUMMARIZE_FILE", path=...)` or `api.summarize_file(path)` — instead of poking
the raw dispatcher. EVERY call proxies to `eli.execution.executor_enhanced.execute()`
(the canonical surface that runs every action), and only for an action a model may choose
on its own and the caller's role allows: the program is the model's choice of actions.
Discovery: `api.actions()` lists those action names from the capability registry / manifest.

Used by the code-mode restricted executor (`eli.coding.restricted_exec`), which whitelists
only `api.*` / `execute(...)` calls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


def _execute(action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from eli.execution.executor_enhanced import execute as _ex
    return _ex(str(action), dict(args or {}))


def _may_call(action: str) -> Optional[str]:
    """Why a program written by the model may not call `action`, or None when it may. It is held
    to the rule for every action a model proposes (the orchestrator's ReAct loop, the failure
    re-plan): only one a model may choose on its own (llm_intent.model_may_choose: the intent
    resolver's catalogue, so no explicit-only or internal action), and only one the caller's
    role allows (authority_gate, which the executor also checks at its entry)."""
    from eli.cognition.llm_intent import model_may_choose
    from eli.runtime.authority_gate import check
    if not model_may_choose(action):
        return (f"{action} is not an action a model may call on its own: it needs the user to ask "
                f"for it in their own words")
    verdict = check(action, {})
    if not verdict.get("allowed", False):
        return str(verdict.get("reason") or f"{action} is not allowed for this account")
    return None


class ELIApi:
    """Curated proxy over the action executor for programs the model writes (code-mode).
    `.call(action, **args)` is the generic escape hatch; named helpers cover a few common,
    mostly-read actions. Each returns the executor's result dict unchanged. An action the model
    may not choose, or the caller may not have run, raises PermissionError before anything runs:
    the program stops there, and code-mode reports why."""

    def _run(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        name = str(action or "").strip().upper()
        why = _may_call(name)
        if why:
            raise PermissionError(why)
        return _execute(name, args)

    def call(self, action: str, **args: Any) -> Dict[str, Any]:
        """Run an action by name: api.call("SUMMARIZE_FILE", path="/x.pdf")."""
        return self._run(action, dict(args))

    # ── convenience helpers over confirmed actions (read-mostly) ──
    def summarize_file(self, path: str, **kw: Any) -> Dict[str, Any]:
        return self._run("SUMMARIZE_FILE", {"path": path, **kw})

    def check_job(self, job_id: Any) -> Dict[str, Any]:
        return self._run("CHECK_JOB", {"job_id": job_id})

    def background_jobs(self) -> Dict[str, Any]:
        return self._run("BACKGROUND_JOBS", {})

    def actions(self) -> List[str]:
        """Live list of the action names a program may call — for discovery / the code-mode
        digest. Tries the capability registry, then the generated manifest, and keeps the ones
        a model may choose. Never raises."""
        try:
            from eli.cognition.llm_intent import model_may_choose
        except Exception:
            log.debug("[API] the model's action catalogue is unavailable; no action is offered", exc_info=True)
            return []
        return [name for name in self._listed() if model_may_choose(name)]

    def _listed(self) -> List[str]:
        names: set = set()
        try:
            from eli.tools.registry.capability_registry import list_capabilities
            for c in (list_capabilities() or []):
                n = str((c or {}).get("action") or (c or {}).get("name") or "").strip()
                if n:
                    names.add(n)
        except Exception:
            pass
        if not names:
            try:
                import json
                from pathlib import Path
                p = Path(__file__).resolve().parents[1] / "capability_inventory.generated.json"
                if p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    items = data if isinstance(data, list) else (data.get("capabilities") or data.get("actions") or [])
                    for c in items:
                        n = str((c or {}).get("action") or (c or {}).get("name") or "").strip() if isinstance(c, dict) else str(c).strip()
                        if n:
                            names.add(n)
            except Exception:
                pass
        return sorted(names)


# Module-level singleton — what the restricted executor injects as `api`.
api = ELIApi()

__all__ = ["api", "ELIApi"]
