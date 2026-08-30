"""Unified self-maintenance orchestration for ELI.

Single entry surface for the full self-evolution loop:

  analyse → improve → propose → patch → upgrade → examine

All user-facing verbs (`self analyse`, `self improve`, `self fix`, `self patch`,
`self upgrade`, `generate patch`) converge here before touching the codebase,
failure DB, or install layer.

Layers:
  * **Failure analysis** — agent.sqlite3 failures + failure_taxonomy
  * **Deterministic repair** — known alias/parameter bugs (no LLM)
  * **Coding-agent propose** — verified fix proposals (not applied)
  * **Patch apply** — guarded apply_code_patch with revert
  * **Install upgrade** — SelfUpgrader (git/pip/AppImage/index rebuild)
  * **Code examine** — tiered code_examiner scans + pending fix confirm
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

from eli.runtime.self_maintenance_config import (
    ANALYSIS_MIN_CLUSTER,
    DEFAULT_ANALYSIS_DAYS,
    PATCH_MIN_CLUSTER,
    USER_PATCH_MIN_CLUSTER,
)

# Canonical maintenance verbs → internal mode
MAINTENANCE_MODES = frozenset({"report", "analyze", "improve", "propose", "patch"})


def run_maintenance_cycle(
    *,
    mode: str = "analyze",
    days: int = DEFAULT_ANALYSIS_DAYS,
    max_patches: int = 3,
    max_proposals: int = 3,
    dry_run: bool = False,
    min_cluster_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Unified self-maintenance cycle consumed by SELF_IMPROVE / SELF_PATCH / SELF_ANALYZE."""
    from eli.runtime.self_improvement import get_self_improvement

    mode = str(mode or "analyze").strip().lower()
    engine = get_self_improvement()
    window_days = int(days) if days else DEFAULT_ANALYSIS_DAYS
    result: Dict[str, Any] = {
        "mode": mode,
        "days": window_days,
        "failures": [],
        "improvements": [],
        "proposals": [],
        "patch_cycle": {},
        "summary": "",
        "content": "",
        "proposal_count": 0,
        "failure_count": 0,
    }

    cluster = ANALYSIS_MIN_CLUSTER if min_cluster_size is None else int(min_cluster_size)
    failures = engine.analyze_failures(
        limit=25,
        days=window_days,
        min_cluster_size=cluster,
    )
    result["failures"] = failures
    result["failure_count"] = len(failures)

    if mode == "report":
        result["summary"] = f"{len(failures)} open failure(s) in the last {days} day(s)"
        result["content"] = result["summary"]
        return result

    if mode == "propose":
        prop = engine.propose_via_agent(max_items=max_proposals)
        proposals = list(prop.get("proposals") or [])
        result["proposals"] = proposals
        result["proposal_count"] = len(proposals)
        lines = [f"Coding-agent fix proposals (verified, not applied): {len(proposals)}"]
        for p in proposals[:max_proposals]:
            lines.append(
                f"  - {p.get('failure')}: "
                f"{'VERIFIED' if p.get('verified') else 'best-effort'} "
                f"(score {p.get('score')}) — {p.get('approach') or p.get('message')}"
            )
        if not proposals:
            lines.append(f"  ({prop.get('reason') or prop.get('error') or 'nothing to propose'})")
        lines.append('Say "self fix" or "apply self-improvement patch" to apply gated fixes.')
        result["content"] = "\n".join(lines)
        result["summary"] = result["content"]
        return result

    if mode == "patch":
        patch_result = engine.run_patch_cycle(
            max_patches=max_patches,
            dry_run=bool(dry_run),
            days=window_days,
            min_cluster_size=USER_PATCH_MIN_CLUSTER,
        )
        result["patch_cycle"] = patch_result
        result["proposal_count"] = int(patch_result.get("patches_generated") or 0)
        result["failure_count"] = int(patch_result.get("failures_analyzed") or 0)
        result["summary"] = str(patch_result.get("summary") or "Patch cycle complete.")
        lines = [result["summary"]]
        for d in (patch_result.get("details") or [])[:5]:
            line = f"  [{d.get('status', '?')}] {str(d.get('failure', ''))[:70]}"
            if d.get("reason"):
                line += f" — {str(d.get('reason'))[:120]}"
            if d.get("hint"):
                line += f"\n      hint: {d.get('hint')}"
            lines.append(line)
        result["content"] = "\n".join(lines)
        return result

    # Default: analyze + log improvements (+ optional coding-agent proposals when model ready)
    improve = engine.analyze_and_improve(propose=True)
    imps = list(improve.get("improvements") or [])
    result["improvements"] = imps
    result["proposal_count"] = int(improve.get("proposals_made") or 0)
    lines = [
        "Improvement cycle complete.",
        "- code_changes_made: 0",
        f"- failures_inspected: {len(failures)}",
        f"- new_improvement_records: {len(imps)}",
        "- patch_cycle_run: false",
    ]
    if failures:
        last = failures[0]
        err = " ".join(str(last.get("error") or "").split())
        ui = " ".join(str(last.get("user_input") or "").split())
        lines.append(f"- last_failure_error: {err[:220] or '-'}")
        lines.append(f"- last_failure_input: {ui[:160] or '-'}")
    if imps:
        lines.append("- logged_improvements:")
        lines.extend(f"  - {i.get('description', '')}" for i in imps[:5])
    lines.append('Next: "self fix" applies patches; "self upgrade" updates the install.')
    result["content"] = "\n".join(lines)
    result["summary"] = result["content"]
    return result


def fire_maintenance_world_event(cycle_result: Dict[str, Any]) -> None:
    """Update repair/autonomy pressure from a maintenance cycle (never raises)."""
    try:
        from eli.world.world_event_bus import fire_improvement_event
        fire_improvement_event(
            proposal_count=int(cycle_result.get("proposal_count") or 0),
            failure_count=int(cycle_result.get("failure_count") or 0),
        )
    except Exception:
        log.debug("fire_maintenance_world_event skipped", exc_info=True)


def maintenance_surface_help() -> str:
    """User-facing map of the self-maintenance verbs."""
    return (
        "ELI self-maintenance (unified):\n"
        "  self analyse   — failure report + root causes (grounded, no GGUF)\n"
        "  self improve   — analyse failures, log improvements, queue proposals\n"
        "  self fix/patch — deterministic rules → LLM patch → guarded apply\n"
        "  (set ELI_SOURCE_ROOT=/path/to/git/checkout to patch dev tree from AppImage)\n"
        "  self upgrade   — install update (AppImage/git/pip) + index rebuild\n"
        "  self update    — refresh overlays/manifest (not a version bump)\n"
        "  examine code   — tiered scan; confirm to apply a pending fix\n"
        f"Analysis window: {DEFAULT_ANALYSIS_DAYS} days (override: \"analyse failures over 30 days\")."
    )
