from __future__ import annotations

from typing import Any, Dict

from eli.core.first_run import first_run_status, mark_first_run_complete
from eli.core.runtime_settings import update_settings


def run_first_run_wizard(**overrides: Any) -> Dict[str, Any]:
    if overrides:
        update_settings(**overrides)
    mark_first_run_complete(True)
    status = first_run_status()
    status["wizard_completed"] = True
    return status


def wizard_status() -> Dict[str, Any]:
    status = first_run_status()
    status["wizard_completed"] = bool(status.get("first_run_complete"))
    return status


__all__ = ["run_first_run_wizard", "wizard_status"]
