from __future__ import annotations

from typing import Any, Dict


def refresh_all_overlays_nonfatal(reason: str = "manual") -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "reason": reason,
        "persona_overlay": None,
        "user_profile_overlay": None,
        "user_info_snapshot": None,
        "errors": [],
    }

    try:
        from eli.cognition.persona_updater import update_persona_overlay, update_user_profile_overlay
        out["persona_overlay"] = update_persona_overlay()
        out["user_profile_overlay"] = update_user_profile_overlay()
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(f"persona_refresh:{exc}")

    try:
        from eli.cognition.user_info_builder import maybe_refresh_user_info
        out["user_info_snapshot"] = maybe_refresh_user_info(reason=reason)
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(f"user_info_refresh:{exc}")

    return out


def safe_goal_summary():
    try:
        from eli.planning.goal_store import summarize_goals
        return summarize_goals()
    except Exception as exc:
        return {"ok": False, "kind": "safe_goal_summary", "error": str(exc)}


def refresh_world_model_runtime(snapshot=None):
    try:
        from eli.kernel.world_model import merge_runtime_snapshot
        if snapshot is None:
            try:
                from eli.cognition.gguf_inference import get_runtime_snapshot
                snapshot = get_runtime_snapshot() or {}
            except Exception:
                snapshot = {}
        merge_runtime_snapshot(dict(snapshot or {}))
        return True
    except Exception:
        return False
