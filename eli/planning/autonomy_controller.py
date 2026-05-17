from __future__ import annotations

from typing import Any, Dict


def safe_tick(reason: str = "manual") -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "reason": reason,
        "code_monitor": None,
        "overlay_refresh": None,
        "proposal_drain": None,
        "proposal_policy_summary": None,
        "errors": [],
    }

    try:
        from eli.runtime.code_monitor import CodeMonitor
        mon = CodeMonitor()
        rep = mon.check()
        out["code_monitor"] = {
            "has_changes": rep.has_changes,
            "file_count": rep.file_count,
            "summary": rep.summary(),
            "git_ref": rep.git_ref,
            "prev_ref": rep.prev_ref,
            "method": rep.method,
        }
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(f"code_monitor:{exc}")

    try:
        from eli.runtime.self_model_refresh import refresh_all_overlays_nonfatal
        out["overlay_refresh"] = refresh_all_overlays_nonfatal(reason=reason)
        if not out["overlay_refresh"].get("ok", True):
            out["ok"] = False
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(f"overlay_refresh:{exc}")

    try:
        from eli.planning.proposal_queue import summarize_by_state
        out["proposal_policy_summary"] = summarize_by_state()
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(f"proposal_summary:{exc}")

    try:
        from eli.planning.proposal_memory_bridge import drain_proposals_to_agent_memory
        out["proposal_drain"] = drain_proposals_to_agent_memory(max_items=64, archive=True)
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(f"proposal_drain:{exc}")

    return out


def safe_goal_tick(limit: int = 3):
    try:
        from eli.planning.goal_tick import governed_goal_tick
        return governed_goal_tick(limit=limit)
    except Exception as exc:
        return {"ok": False, "kind": "safe_goal_tick", "error": str(exc)}


try:
    if "AutonomyController" in globals() and not hasattr(AutonomyController, "goal_tick"):
        def _goal_tick(self, limit: int = 3):
            return safe_goal_tick(limit=limit)
        AutonomyController.goal_tick = _goal_tick
except Exception:
    pass

def safe_scheduler_tick(limit: int = 3, cooldown_sec: int = 60):
    try:
        from eli.planning.autonomy_scheduler import scheduler_tick
        return scheduler_tick(limit=limit, cooldown_sec=cooldown_sec)
    except Exception as exc:
        return {"ok": False, "kind": "safe_scheduler_tick", "error": str(exc)}


def safe_scheduler_snapshot(limit: int = 25):
    try:
        from eli.planning.autonomy_scheduler import scheduler_snapshot
        return scheduler_snapshot(limit=limit)
    except Exception as exc:
        return {"ok": False, "kind": "safe_scheduler_snapshot", "error": str(exc)}


try:
    if "AutonomyController" in globals() and not hasattr(AutonomyController, "scheduler_tick"):
        def _scheduler_tick(self, limit: int = 3, cooldown_sec: int = 60):
            return safe_scheduler_tick(limit=limit, cooldown_sec=cooldown_sec)
        AutonomyController.scheduler_tick = _scheduler_tick
except Exception:
    pass
