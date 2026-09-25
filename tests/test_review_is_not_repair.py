"""A review cycle eases pressure; only a verified repair counts as a repair."""
from eli.world import world_event_bus as bus


def _capture(monkeypatch):
    fired = []
    monkeypatch.setattr(bus, "fire_world_event", lambda t, s, m, p=None: fired.append(t))
    return fired


def test_an_empty_review_is_review_completed_only(monkeypatch):
    fired = _capture(monkeypatch)
    bus.fire_improvement_event(0, 0)
    assert fired == ["review_completed"]


def test_proposals_are_not_repairs(monkeypatch):
    fired = _capture(monkeypatch)
    bus.fire_improvement_event(2, 5)
    assert fired == ["improvement_proposal", "review_completed"]


def test_a_verified_repair_fires_repair_completed(monkeypatch):
    fired = _capture(monkeypatch)
    bus.fire_improvement_event(1, 3, repaired=1)
    assert fired[-1] == "repair_completed" and "review_completed" in fired


def _pressure_after(event_type):
    from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
    from eli.world.core.schemas import EliWorldState, WorldEvent
    engine = EliWorldAutonomyEngine.__new__(EliWorldAutonomyEngine)
    state = EliWorldState()
    state.awareness.repair_pressure = 0.8
    engine._update_awareness_from_event(state, WorldEvent(event_type, "test", "x"))
    return state.awareness.repair_pressure


def test_a_review_eases_repair_pressure_less_than_a_repair():
    review, repair = _pressure_after("review_completed"), _pressure_after("repair_completed")
    assert repair < review < 0.8
