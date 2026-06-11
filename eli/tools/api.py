"""eli.api — a small, curated callable surface over ELI's action executor.

Sugar, not a new execution path: code written in code-mode reads cleanly —
`api.call("SUMMARIZE_FILE", path=...)` or `api.summarize_file(path)` — instead of poking
the raw dispatcher. EVERY call proxies to `eli.execution.executor_enhanced.execute()`
(the canonical surface that already runs all 207 actions). Discovery: `api.actions()`
lists the live action names from the capability registry / manifest.

Used by the code-mode restricted executor (`eli.coding.restricted_exec`), which whitelists
only `api.*` / `execute(...)` calls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _execute(action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from eli.execution.executor_enhanced import execute as _ex
    return _ex(str(action), dict(args or {}))


class ELIApi:
    """Curated proxy over the action executor. `.call(action, **args)` is the generic
    escape hatch; named helpers cover a few common, mostly-read actions. Each returns the
    executor's result dict unchanged."""

    def call(self, action: str, **args: Any) -> Dict[str, Any]:
        """Run any action by name: api.call("SUMMARIZE_FILE", path="/x.pdf")."""
        return _execute(action, dict(args))

    # ── convenience helpers over confirmed actions (read-mostly) ──
    def summarize_file(self, path: str, **kw: Any) -> Dict[str, Any]:
        return _execute("SUMMARIZE_FILE", {"path": path, **kw})

    def check_job(self, job_id: Any) -> Dict[str, Any]:
        return _execute("CHECK_JOB", {"job_id": job_id})

    def background_jobs(self) -> Dict[str, Any]:
        return _execute("BACKGROUND_JOBS", {})

    def actions(self) -> List[str]:
        """Live list of available action names — for discovery / the code-mode digest.
        Tries the capability registry, then the generated manifest. Never raises."""
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
