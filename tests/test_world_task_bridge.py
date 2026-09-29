"""A task opening/closing must show up as a real, retirable object in Eli's World —
the RETIRE_OBJECT branch and task_opened/task_closed handling in autonomy_engine.py."""
import pytest

from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.core.schemas import WorldEvent
from eli.world.persistence.storage import EliWorldStorage


@pytest.fixture
def engine(tmp_path):
    return EliWorldAutonomyEngine(storage=EliWorldStorage(state_path=tmp_path / "world.json"))


def _linked_object(state, goal_id):
    for obj in state.objects.values():
        for link in obj.links or []:
            if link.get("type") == "task" and link.get("goal_id") == goal_id:
                return obj
    return None


def test_task_opened_creates_a_linked_workbench_object(engine):
    state = engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: RAIMS project",
                                            {"goal_id": "g1", "title": "RAIMS project"}))
    obj = _linked_object(state, "g1")
    assert obj is not None
    assert obj.name == "RAIMS project"
    assert obj.room == "workshop"
    assert obj.retired is False


def test_task_closed_retires_only_its_own_object(engine):
    engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: A", {"goal_id": "ga", "title": "A"}))
    engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: B", {"goal_id": "gb", "title": "B"}))
    state = engine.ingest_event(WorldEvent("task_closed", "test", "Task closed: A", {"goal_id": "ga"}))

    obj_a = _linked_object(state, "ga")
    obj_b = _linked_object(state, "gb")
    assert obj_a.retired is True
    assert obj_b.retired is False  # closing one task must not touch another's object


def test_two_tasks_get_distinct_objects_not_a_shared_one(engine):
    s1 = engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: A", {"goal_id": "ga", "title": "A"}))
    s2 = engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: B", {"goal_id": "gb", "title": "B"}))
    obj_a = _linked_object(s2, "ga")
    obj_b = _linked_object(s2, "gb")
    assert obj_a.object_id != obj_b.object_id


def test_task_closed_for_unknown_goal_is_a_safe_no_op(engine):
    before = engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: A", {"goal_id": "ga", "title": "A"}))
    n_before = len(before.objects)
    after = engine.ingest_event(WorldEvent("task_closed", "test", "Task closed: ghost", {"goal_id": "no-such-goal"}))
    assert len(after.objects) == n_before
    assert not any(o.retired for o in after.objects.values())


def test_retired_object_is_excluded_from_the_active_render_list(engine):
    engine.ingest_event(WorldEvent("task_opened", "test", "Task opened: A", {"goal_id": "ga", "title": "A"}))
    state = engine.ingest_event(WorldEvent("task_closed", "test", "Task closed: A", {"goal_id": "ga"}))
    active = [o for o in state.objects.values() if not o.retired]
    assert not any(_linked_object(state, "ga") is o for o in active)
