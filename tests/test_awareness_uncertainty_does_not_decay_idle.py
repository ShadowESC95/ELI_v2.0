"""uncertainty / repair_pressure must not decay away purely from idle time.

`local_world_bridge.get_awareness_driven_suggestions()` raises a real,
user-facing "evidence quality needs review" proposal when
`state.awareness.uncertainty > 0.75` -- a genuinely autonomous suggestion fed
into agent memory. `EliWorldAutonomyEngine._update_awareness_from_event()` used
to apply a blanket time-based decay to `uncertainty` and `repair_pressure`
alongside pacing signals (autonomy_pressure/reflection_depth/tool_activity),
so a real unresolved evidence-quality concern would silently fall back below
that threshold purely because enough idle time passed -- with zero
correlation to whether evidence quality had actually improved. For a product
whose pitch is trustworthy, grounded local intelligence, "ELI stopped
worrying about it because nobody looked in an hour" is not the same as "ELI
verified the problem is gone", and presenting the two identically is exactly
the failure this test locks against.

Pacing signals (autonomy_pressure, reflection_depth, tool_activity) legitimately
cool down when idle and must keep decaying -- this is not a blanket "nothing
should ever decay" fix.
"""
from __future__ import annotations

from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.core.schemas import AwarenessState, EliWorldState, WorldEvent

_ONE_HOUR_AGO = 3700.0  # well past the 60-minute full-decay point


def _state_with(**awareness_kwargs) -> EliWorldState:
    state = EliWorldState()
    state.awareness = AwarenessState(timestamp=0.0, **awareness_kwargs)
    return state


def _tick(state: EliWorldState, *, now: float, event_type: str = "reflection") -> None:
    # Any real WorldEvent triggers the decay-then-apply pass; use a low-impact
    # event type (reflection) so its own effects don't confound the assertion.
    event = WorldEvent(event_type=event_type, source="test", summary="tick", timestamp=now)
    EliWorldAutonomyEngine._update_awareness_from_event(None, state, event)  # type: ignore[arg-type]


def test_uncertainty_survives_an_hour_of_idle_time(monkeypatch):
    state = _state_with(uncertainty=0.9, repair_pressure=0.8)
    monkeypatch.setattr("eli.world.agency.autonomy_engine.time", lambda: _ONE_HOUR_AGO)

    _tick(state, now=_ONE_HOUR_AGO, event_type="reflection")

    assert state.awareness.uncertainty == 0.9, (
        "a real unresolved uncertainty signal must not decay from idle time alone"
    )
    assert state.awareness.repair_pressure == 0.8, (
        "a real unresolved repair-pressure signal must not decay from idle time alone"
    )


def test_pacing_signals_still_decay_when_idle(monkeypatch):
    """The fix is scoped, not a blanket removal of decay."""
    state = _state_with(autonomy_pressure=0.9, reflection_depth=0.9, tool_activity=0.9)
    monkeypatch.setattr("eli.world.agency.autonomy_engine.time", lambda: _ONE_HOUR_AGO)

    _tick(state, now=_ONE_HOUR_AGO, event_type="reflection")

    assert state.awareness.autonomy_pressure < 0.9
    assert state.awareness.tool_activity < 0.9


def test_uncertainty_only_falls_on_a_real_resolution_event(monkeypatch):
    state = _state_with(uncertainty=0.9)
    monkeypatch.setattr("eli.world.agency.autonomy_engine.time", lambda: 10.0)  # no idle decay window

    _tick(state, now=10.0, event_type="task_completed")

    assert state.awareness.uncertainty < 0.9, (
        "uncertainty should still fall on an explicit resolution event"
    )
