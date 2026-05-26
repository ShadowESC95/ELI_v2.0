"""
eli/world/world_event_bus.py
────────────────────────────
Non-blocking fire-and-forget bridge that feeds runtime signals into
EliWorldAutonomyEngine without adding latency to the hot response path.

All calls enqueue a (event_type, source, summary, payload) tuple into a
daemon thread that flushes to EliWorldStorage. If the world subsystem is
unavailable or raises, it fails silently — world state is never on the
critical path.

Usage (anywhere in the runtime):
    from eli.world.world_event_bus import fire_world_event
    fire_world_event("memory_recall", "agent_bus", "Memory agent returned 5 hits",
                     {"confidence": 0.82, "hit_count": 5})
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Dict, Optional

_event_queue: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=512)
_worker_started = False
_lock = threading.Lock()


def _world_worker() -> None:
    while True:
        item = _event_queue.get()
        if item is None:          # sentinel — shut down
            break
        event_type, source, summary, payload = item
        try:
            from eli.world.local_world_bridge import append_event
            append_event(event_type, source, summary, payload)
        except Exception:
            pass                  # world unavailable — don't crash runtime
        finally:
            _event_queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if not _worker_started:
            t = threading.Thread(target=_world_worker, daemon=True,
                                 name="eli-world-bus")
            t.start()
            _worker_started = True


def fire_world_event(
    event_type: str,
    source: str,
    summary: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Enqueue a world event for async processing. Never blocks the caller.
    Drops silently if the queue is full (world lag, not a runtime fault).
    """
    _ensure_worker()
    try:
        _event_queue.put_nowait((event_type, source, summary, payload or {}))
    except queue.Full:
        pass


# ── Convenience helpers used by the engine ───────────────────────────────────

def fire_confidence_event(
    grounding_confidence: float,
    aggregated_confidence: float,
    agents_used: list,
    action: str,
) -> None:
    """Map bus confidence signals to world awareness events."""
    if grounding_confidence < 0.10:
        fire_world_event(
            "evidence_weak",
            "agent_bus",
            f"Low grounding signal on action={action} (grounding={grounding_confidence:.2f})",
            {"grounding_confidence": grounding_confidence,
             "aggregated_confidence": aggregated_confidence,
             "action": action},
        )
    elif grounding_confidence >= 0.40:
        fire_world_event(
            "memory_recall",
            "agent_bus",
            f"Strong evidence on action={action}: agents={agents_used}",
            {"confidence": grounding_confidence,
             "agents": agents_used,
             "action": action},
        )


def fire_tool_result_event(action: str, ok: bool, source: str = "executor") -> None:
    """Fire task_completed or error_detected based on executor result."""
    if ok:
        fire_world_event(
            "task_completed",
            source,
            f"Action {action} completed successfully.",
            {"action": action},
        )
    else:
        fire_world_event(
            "error_detected",
            source,
            f"Action {action} failed.",
            {"action": action},
        )


def fire_improvement_event(proposal_count: int, failure_count: int) -> None:
    """Fire when self-improvement cycle produces proposals.

    Always fires repair_completed so repair_pressure decreases after a review
    cycle — regardless of whether new proposals were generated.  Firing
    runtime_fault on a 0-proposal cycle (the normal steady-state) was
    incorrectly causing repair_pressure to accumulate across every SELF_IMPROVE
    run and triggering an infinite proactive-daemon loop.
    """
    if proposal_count > 0:
        fire_world_event(
            "improvement_proposal",
            "self_improvement",
            f"Self-improvement cycle: {proposal_count} proposals from {failure_count} failures.",
            {"proposal_count": proposal_count, "failure_count": failure_count},
        )
    # Always acknowledge cycle completion so repair_pressure can decrease.
    fire_world_event(
        "repair_completed",
        "self_improvement",
        f"Self-improvement review cycle complete: {failure_count} failure(s) inspected, "
        f"{proposal_count} proposal(s) generated.",
        {"proposal_count": proposal_count, "failure_count": failure_count},
    )


def fire_reasoning_stage_event(
    mode: str,
    stage: int,
    total_stages: int,
    stage_name: str,
) -> None:
    """
    Fire a world event at the start of each GGUF pass in a multi-pass reasoning mode.

    This is the live progress signal for the World tab during the 30-60s silence
    that would otherwise occur while private reasoning modes buffer their output.
    Non-blocking; fails silently if the world subsystem is unavailable.

    Args:
        mode:         Reasoning mode name ("chain_of_thought", "tree_of_thoughts", etc.)
        stage:        1-based index of the current stage.
        total_stages: Total number of stages for this mode invocation.
        stage_name:   Human-readable stage label (e.g. "private_scratchpad_reasoning").
    """
    fire_world_event(
        "reasoning_stage",
        "reasoning_engine",
        f"[{mode}] Stage {stage}/{total_stages}: {stage_name}",
        {
            "mode": mode,
            "stage": stage,
            "total_stages": total_stages,
            "stage_name": stage_name,
        },
    )
