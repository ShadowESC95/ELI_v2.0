"""Canonical facade for ELI's user-habit + proactive subsystem.

ONE coherent entry point for the (previously scattered) modules that together implement
"notice the user's behaviour → detect habits → propose/offer → schedule → reflect". Import
from here instead of reaching into the individual modules:

    from eli.planning.proactive_system import (
        detect_habits, get_scheduler, ProactiveDaemon, get_daemon, start_daemon,
        refresh_insight, get_cached_insight, set_pending_habit, ...
    )

Members (re-exported, not moved — the existing modules keep working and their import sites
are untouched; this is the additive coherent interface):
    - habit detection + offer state ........ eli.planning.habits
    - habit-rule scheduler ................. eli.planning.habits_scheduler
    - the proactive daemon ................. eli.planning.proactive_daemon
    - background reflection synthesis ...... eli.planning.insight_synthesis

DELIBERATELY NOT merged — distinct concerns that merely share a name (conflating them would
be wrong; they stay separate by design):
    - eli.runtime.awareness_boot ........... the AWARENESS subsystem (world-state briefing)
    - eli.world.agency.habit_engine ........ the WORLD-avatar's symbolic autonomy habits
    - eli.memory.habits_memory_db .......... a habit-EVENT memory store
    - eli.memory.habits_memory_service ..... already a back-compat shim to memory_service
    - eli.planning.habits_state ............ generic ~/.eli_state user-name state
"""
from __future__ import annotations

from eli.planning.habits import (  # noqa: F401
    detect_habits,
    log_event,
    schedule_detection_loop,
    set_pending_habit,
    get_pending_habit,
    clear_pending_habit,
    was_offered,
    mark_offered,
)
from eli.planning.habits_scheduler import HabitScheduler, get_scheduler  # noqa: F401
from eli.planning.proactive_daemon import (  # noqa: F401
    ProactiveDaemon,
    get_daemon,
    start_daemon,
)
from eli.planning.insight_synthesis import get_cached_insight, refresh_insight  # noqa: F401

__all__ = [
    # habit detection + offer
    "detect_habits", "log_event", "schedule_detection_loop",
    "set_pending_habit", "get_pending_habit", "clear_pending_habit",
    "was_offered", "mark_offered",
    # scheduler
    "HabitScheduler", "get_scheduler",
    # proactive daemon
    "ProactiveDaemon", "get_daemon", "start_daemon",
    # reflection synthesis
    "get_cached_insight", "refresh_insight",
]
