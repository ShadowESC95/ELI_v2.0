"""
brain.awareness.boot
~~~~~~~~~~~~~~~~~~~~~
Single entry point that runs all awareness subsystems on startup
and returns an AwarenessState the cognitive engine can query.

Usage (in CognitiveEngine.__init__ or GUI boot):

    from eli.runtime.awareness_boot import boot_awareness
    self._awareness = boot_awareness()

Then in _build_grounded_evidence_context:

    if self._awareness:
        lines.append(self._awareness.context_block())
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class AwarenessState:
    """
    Snapshot of Eli's self-knowledge.  Attached to the cognitive engine
    so it can inject awareness context into the system prompt.
    """

    def __init__(self):
        self.capability_count: int = 0
        self.capability_names: List[str] = []
        self.capability_delta_summary: str = ""
        self.capability_delta_has_changes: bool = False
        self.code_report_summary: str = ""
        self.code_report_has_changes: bool = False
        self.code_report_briefing: str = ""
        self.persona_cleaned: bool = False
        self.boot_time: float = 0.0
        self._cap_sync = None
        self._code_mon = None

    def refresh(self) -> "AwarenessState":
        """Re-run both subsystems (e.g. after SELF_IMPROVE)."""
        if self._cap_sync:
            delta = self._cap_sync.run()
            self.capability_count = self._cap_sync.capability_count()
            self.capability_names = self._cap_sync.live_capability_names()
            self.capability_delta_summary = delta.summary()
            self.capability_delta_has_changes = delta.has_changes
        if self._code_mon:
            report = self._code_mon.check()
            self.code_report_summary = report.summary()
            self.code_report_has_changes = report.has_changes
            self.code_report_briefing = report.cognitive_briefing()
        return self

    def context_block(self) -> str:
        """
        Text block for injection into the cognitive engine's system prompt.
        Compact — adds awareness without bloating context.
        """
        parts = [f"[Self-Awareness: {self.capability_count} capabilities loaded]"]
        if self.capability_delta_has_changes:
            parts.append(f"  Capability changes: {self.capability_delta_summary}")
        if self.code_report_has_changes:
            parts.append(f"  Code changes: {self.code_report_summary}")
        return "\n".join(parts)

    def full_briefing(self) -> str:
        """Detailed report for SELF_ANALYZE / AWARENESS_STATUS actions."""
        lines = [
            f"Self-Awareness Report — {self.capability_count} capabilities",
            "",
        ]
        if self.capability_delta_has_changes:
            lines.append(f"Capability changes: {self.capability_delta_summary}")
        else:
            lines.append("Capability inventory: no changes since last sync.")
        lines.append("")
        if self.code_report_has_changes:
            lines.append(self.code_report_briefing)
        else:
            lines.append("No code changes detected since last check.")
        if self.persona_cleaned:
            lines.append("\nPersona auto-overlay was cleaned (duplicates/noise pruned).")
        lines.append(f"\nBoot time: {self.boot_time:.2f}s")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_awareness: Optional[AwarenessState] = None


def get_awareness() -> Optional[AwarenessState]:
    """Return the current awareness state (None if not booted yet)."""
    return _awareness


def boot_awareness(
    repo_root: Optional[Path] = None,
    memory: Any = None,
    quiet: bool = False,
) -> AwarenessState:
    """
    Run the full awareness boot sequence:
      1. Sync capabilities (AST parse, diff, write inventory)
      2. Check for code changes (git diff)
      3. Clean persona auto-overlay (dedup, prune noise)
      4. Store findings in memory
      5. Return AwarenessState

    Parameters
    ----------
    repo_root : path to the eli repository (auto-detected if None)
    memory    : optional Memory instance (auto-discovered if None)
    quiet     : suppress info logging
    """
    global _awareness
    t0 = time.time()

    if repo_root is None:
        try:
            from eli.core.paths import get_paths
            repo_root = Path(get_paths().project_root)
        except Exception:
            repo_root = Path(__file__).resolve().parents[3]

    if not quiet:
        log.info("awareness: booting …")

    state = AwarenessState()

    # 1. Capability sync
    try:
        from eli.runtime.capability_sync import CapabilitySync
        cap_sync = CapabilitySync(repo_root)
        delta = cap_sync.run()
        state._cap_sync = cap_sync
        state.capability_count = cap_sync.capability_count()
        state.capability_names = cap_sync.live_capability_names()
        state.capability_delta_summary = delta.summary()
        state.capability_delta_has_changes = delta.has_changes
    except Exception as exc:
        log.warning("awareness: capability sync failed: %s", exc)

    # 2. Code change detection
    try:
        from eli.runtime.code_monitor import CodeMonitor
        code_mon = CodeMonitor(repo_root)
        report = code_mon.check()
        state._code_mon = code_mon
        state.code_report_summary = report.summary()
        state.code_report_has_changes = report.has_changes
        state.code_report_briefing = report.cognitive_briefing()
    except Exception as exc:
        log.warning("awareness: code monitor failed: %s", exc)

    # 3. Persona hygiene (dedup/prune)
    try:
        from eli.cognition.persona_hygiene import clean_auto_persona
        result = clean_auto_persona(repo_root)
        state.persona_cleaned = bool(result.get("changed"))
    except Exception as exc:
        log.warning("awareness: persona hygiene failed: %s", exc)

    # 4. Persona auto-update (rebuild overlay from current memory state)
    try:
        from eli.runtime.profile_extractor import backfill_user_patterns
        backfill_user_patterns(limit=2500)
    except Exception as exc:
        log.warning("awareness: user-pattern backfill failed: %s", exc)

    try:
        from eli.cognition.persona_updater import update_persona_overlay
        update_persona_overlay(memory=memory)
    except Exception as exc:
        log.warning("awareness: persona update failed: %s", exc)

    state.boot_time = time.time() - t0

    # 4. Store in memory
    if memory is None:
        try:
            from eli.memory import get_memory
            memory = get_memory()
        except Exception:
            memory = None

    if memory is not None:
        _store_to_memory(memory, state)

    _awareness = state

    if not quiet:
        log.info(
            "awareness: boot done in %.2fs — %d capabilities, %s",
            state.boot_time, state.capability_count,
            state.code_report_summary if state.code_report_has_changes else "no code changes",
        )

    return state


def _store_to_memory(memory: Any, state: AwarenessState) -> None:
    """Store awareness findings via Memory.store_memory / add_observation."""
    if state.capability_delta_has_changes:
        try:
            memory.store_memory(
                f"Capability inventory updated: {state.capability_delta_summary}",
                tags=["capability_change", "self_awareness", "system"],
                source="awareness",
                kind="system",
            )
        except Exception as exc:
            log.debug("awareness: memory store (caps) failed: %s", exc)

    if state.code_report_has_changes:
        try:
            memory.add_observation(
                category="code_change",
                observation=state.code_report_summary,
                source="awareness",
            )
        except Exception as exc:
            log.debug("awareness: observation store (code) failed: %s", exc)

    if state.persona_cleaned:
        try:
            memory.add_observation(
                category="persona_hygiene",
                observation="Persona auto-overlay cleaned: duplicates and noise pruned.",
                source="awareness",
            )
        except Exception as exc:
            log.debug("awareness: observation store (persona) failed: %s", exc)

# Compatibility alias expected by test suite
BootAwareness = AwarenessState
