from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from eli.execution.operator_policy import load_policy
from eli.runtime.operator_state import safe_proposal_summary, safe_goal_summary
from eli.planning.attention_queue import append_attention, recent_attention, summarize_attention

# Autonomous self-upgrade/LoRA triggering fires only in "goal_driven" mode, the one policy mode
# that already carries elevated-autonomy semantics here (goal_tick attention severity is bumped
# for it). Intervals are conservative: this decides whether to invoke the existing, already-gated
# upgrade/training machinery, not how to run it.
_SELF_UPGRADE_CHECK_INTERVAL_SEC = 3 * 24 * 3600
_LORA_CHECK_INTERVAL_SEC = 7 * 24 * 3600


def _artifacts_dir() -> Path:
    """The user data dir on a packaged install; the source tree in dev."""
    from eli.core.paths import artifacts_dir
    return artifacts_dir()


def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths
        return get_paths().project_root
    except Exception:
        return Path(__file__).resolve().parents[3]


def scheduler_state_path() -> Path:
    # artifacts_dir() rather than project_root()/artifacts: identical under the
    # frozen rthook (both pin the same user root) and correct for a bare pip
    # install, where the project root is the package directory.
    return _artifacts_dir() / "runtime" / "autonomy_scheduler.json"


def load_scheduler_state() -> Dict[str, Any]:
    p = scheduler_state_path()
    if not p.exists():
        return {
            "ok": True,
            "path": str(p),
            "last_run": None,
            "last_mode": None,
            "last_status": "never_run",
            "last_goal_tick_count": 0,
            "last_attention_added": 0,
            "last_self_upgrade_check": None,
            "last_lora_check": None,
        }
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}
    raw.setdefault("ok", True)
    raw["path"] = str(p)
    raw.setdefault("last_run", None)
    raw.setdefault("last_mode", None)
    raw.setdefault("last_status", "unknown")
    raw.setdefault("last_goal_tick_count", 0)
    raw.setdefault("last_attention_added", 0)
    raw.setdefault("last_self_upgrade_check", None)
    raw.setdefault("last_lora_check", None)
    return raw


def save_scheduler_state(state: Dict[str, Any]) -> Dict[str, Any]:
    p = scheduler_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state or {})
    state.setdefault("ok", True)
    state["path"] = str(p)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def _proposal_counts(summary: Dict[str, Any]) -> Dict[str, int]:
    if not isinstance(summary, dict):
        return {}
    counts = summary.get("counts")
    if isinstance(counts, dict):
        return {str(k): int(v) for k, v in counts.items()}
    return {
        str(k): int(v)
        for k, v in summary.items()
        if isinstance(v, (int, float))
    }


def _maybe_check_self_upgrade(state: Dict[str, Any], now: float) -> int:
    """Autonomously schedule a self-upgrade check when a newer release exists
    and it has been long enough since the last check. Returns attention items
    added (0 or 1). Never raises -- a failed check just tries again next
    interval.

    This is the "decide to invoke it" layer that was missing: SelfUpgrader
    and the `self_upgrade` scheduled-task kind both already exist and are
    fully gated (network behind netguard, the upgrade itself behind the same
    verified-download/rollback machinery as a manual "update ELI" request) --
    nothing here bypasses that. It only decides WHEN to ask.
    """
    last = state.get("last_self_upgrade_check")
    last_f = float(last) if isinstance(last, (int, float)) else 0.0
    if last_f > 0 and (now - last_f) < _SELF_UPGRADE_CHECK_INTERVAL_SEC:
        return 0
    state["last_self_upgrade_check"] = now
    try:
        from eli.core.config import network_allowed
        if not network_allowed():
            return 0
        from eli.kernel.self_upgrade import SelfUpgrader, _ver_tuple
        up = SelfUpgrader()
        local_v = up._local_version()
        latest_tag = up._latest_tag()
        if _ver_tuple(latest_tag.lstrip("v")) <= _ver_tuple(local_v):
            return 0
        from eli.runtime.scheduled_tasks import schedule_request
        res = schedule_request(
            f"Autonomous check: a newer ELI release ({latest_tag}) is available -- "
            f"apply the update.",
            when_spec="now", kind="self_upgrade", recurring=False,
        )
        if not res.get("ok"):
            return 0
        append_attention(
            kind="self_upgrade_available",
            title=f"Newer ELI release available ({latest_tag} > {local_v}) -- upgrade scheduled",
            state="pending",
            severity="medium",
            source="autonomy_scheduler",
            metadata={"local_version": local_v, "latest_tag": latest_tag, "job": res.get("job_id")},
            suppression_key="self_upgrade_available",
            suppression_window_sec=_SELF_UPGRADE_CHECK_INTERVAL_SEC,
        )
        return 1
    except Exception:
        import logging
        logging.getLogger(__name__).debug("autonomous self-upgrade check failed", exc_info=True)
        return 0


def _maybe_check_lora_retrain(state: Dict[str, Any], now: float) -> int:
    """Autonomously schedule a LoRA training pass when preflight reports at
    least one target ready to train and it has been long enough since the
    last check. Same "decide when to ask" role as _maybe_check_self_upgrade --
    the actual training still runs through the existing scheduled `lora`
    task kind and its own preflight/DAG machinery."""
    last = state.get("last_lora_check")
    last_f = float(last) if isinstance(last, (int, float)) else 0.0
    if last_f > 0 and (now - last_f) < _LORA_CHECK_INTERVAL_SEC:
        return 0
    state["last_lora_check"] = now
    try:
        from eli.learning.training_preflight import preflight_all
        pf = preflight_all()
        ready = [r for r in (pf.get("reports") or []) if r.get("can_train")]
        if not ready:
            return 0
        target = str(ready[0].get("target") or "eli_phi")
        from eli.runtime.scheduled_tasks import schedule_request
        res = schedule_request(
            f"Autonomous check: {target} is ready for LoRA training -- run it.",
            when_spec="tonight", kind="lora", recurring=False,
        )
        if not res.get("ok"):
            return 0
        append_attention(
            kind="lora_ready",
            title=f"LoRA training ready for '{target}' -- run scheduled",
            state="pending",
            severity="medium",
            source="autonomy_scheduler",
            metadata={"target": target, "ready_targets": [r.get("target") for r in ready],
                      "job": res.get("job_id")},
            suppression_key="lora_ready",
            suppression_window_sec=_LORA_CHECK_INTERVAL_SEC,
        )
        return 1
    except Exception:
        import logging
        logging.getLogger(__name__).debug("autonomous LoRA check failed", exc_info=True)
        return 0


def scheduler_tick(limit: int = 3, now: float | None = None, cooldown_sec: int = 60) -> Dict[str, Any]:
    now = time.time() if now is None else float(now)
    cooldown_sec = max(0, int(cooldown_sec))

    policy = load_policy()
    mode = str(policy.get("mode") or "proposal_only")
    state = load_scheduler_state()
    last_run = state.get("last_run")
    last_run_f = float(last_run) if isinstance(last_run, (int, float)) else 0.0

    out: Dict[str, Any] = {
        "ok": True,
        "kind": "autonomy_scheduler_tick",
        "mode": mode,
        "now": now,
        "cooldown_sec": cooldown_sec,
        "status": "idle",
        "goal_tick": None,
        "attention_added": 0,
    }

    if mode == "observe_only":
        out["status"] = "observe_only"
        state.update({
            "last_run": now,
            "last_mode": mode,
            "last_status": out["status"],
            "last_goal_tick_count": 0,
            "last_attention_added": 0,
        })
        save_scheduler_state(state)
        return out

    if cooldown_sec > 0 and last_run_f > 0 and (now - last_run_f) < cooldown_sec:
        out["status"] = "cooldown"
        out["remaining_sec"] = max(0, int(cooldown_sec - (now - last_run_f)))
        state.update({
            "last_mode": mode,
            "last_status": out["status"],
            "last_attention_added": 0,
        })
        save_scheduler_state(state)
        return out

    try:
        from eli.planning.goal_tick import governed_goal_tick
        goal_tick = governed_goal_tick(limit=limit, now=now)
    except Exception as exc:
        goal_tick = {"ok": False, "error": str(exc), "count": 0, "items": []}

    out["goal_tick"] = goal_tick
    emitted = int(goal_tick.get("count") or 0)
    attention_added = 0

    if emitted > 0:
        for item in goal_tick.get("items", []):
            title = str(item.get("title") or item.get("goal_id") or "goal tick")
            append_attention(
                kind="goal_tick",
                title=f"Goal proposal emitted: {title}",
                state="pending",
                severity="high" if mode == "goal_driven" else "medium",
                source="autonomy_scheduler",
                metadata=item,
                suppression_key=f"goal_tick:{item.get('goal_id')}",
                suppression_window_sec=120,
            )
            attention_added += 1

    proposal_summary = safe_proposal_summary()
    counts = _proposal_counts(proposal_summary)

    if int(counts.get("pending_confirmation", 0)) > 0:
        append_attention(
            kind="approval_needed",
            title=f"{counts.get('pending_confirmation', 0)} proposal(s) awaiting operator confirmation",
            state="pending_confirmation",
            severity="high",
            source="autonomy_scheduler",
            metadata={"counts": counts},
            suppression_key="approval_needed",
            suppression_window_sec=180,
        )
        attention_added += 1

    if int(counts.get("blocked", 0)) > 0:
        append_attention(
            kind="blocked_proposal",
            title=f"{counts.get('blocked', 0)} blocked proposal(s) detected",
            state="blocked",
            severity="high",
            source="autonomy_scheduler",
            metadata={"counts": counts},
            suppression_key="blocked_proposal",
            suppression_window_sec=180,
        )
        attention_added += 1

    if int(counts.get("pending", 0)) >= 10:
        append_attention(
            kind="queue_pressure",
            title=f"Proposal queue pressure rising: {counts.get('pending', 0)} pending",
            state="pending",
            severity="medium",
            source="autonomy_scheduler",
            metadata={"counts": counts},
            suppression_key="queue_pressure",
            suppression_window_sec=300,
        )
        attention_added += 1

    # Autonomous self-maintenance triggering: the "decide to invoke it" layer for self_upgrade/lora
    # that didn't exist (both were pull-only, even with a newer release on GitHub or enough reviewed
    # training data). goal_driven mode only; every other mode stays pull-only as before.
    if mode == "goal_driven":
        attention_added += _maybe_check_self_upgrade(state, now)
        attention_added += _maybe_check_lora_retrain(state, now)

    out["proposal_summary"] = proposal_summary
    out["goal_summary"] = safe_goal_summary()
    out["attention_added"] = attention_added
    out["status"] = "ran"

    state.update({
        "last_run": now,
        "last_mode": mode,
        "last_status": out["status"],
        "last_goal_tick_count": emitted,
        "last_attention_added": attention_added,
    })
    save_scheduler_state(state)
    return out


def scheduler_snapshot(limit: int = 25) -> Dict[str, Any]:
    return {
        "ok": True,
        "policy": load_policy(),
        "state": load_scheduler_state(),
        "proposal_summary": safe_proposal_summary(),
        "goal_summary": safe_goal_summary(),
        "attention": recent_attention(limit=limit),
        "attention_summary": summarize_attention(),
    }
