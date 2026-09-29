"""Work in progress survives the conversation: constraints, decisions, finished steps and open questions."""
import pytest

from eli.planning import goal_store as gs


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "goal_store_path", lambda: tmp_path / "goals.json")


def test_a_task_is_a_goal_the_scheduler_does_not_tick():
    t = gs.open_task("Rebuild the tuner", "fit ctx before layers", ["keep ctx"])
    assert gs.due_goals() == [] and gs.open_task("rebuild the tuner").goal_id == t.goal_id


def test_events_land_on_the_task_and_questions_can_be_closed():
    t = gs.open_task("Rebuild the tuner")
    for kind, text in (("decision", "we use the joint planner"), ("step_done", "clamp fixed"), ("question", "does mmap page in"),
                       ("artifact", "tests/test_fit.py"), ("constraint", "must not shrink ctx")):
        assert gs.record_task_event(t.goal_id, kind, text)
    gs.record_task_event(t.goal_id, "question_resolved", "does mmap page in")
    brief = gs.task_brief()
    assert "Rebuild the tuner" in brief and "clamp fixed" in brief and "must not shrink ctx" in brief and "does mmap" not in brief


def test_a_restart_still_has_the_brief():
    t = gs.open_task("Ship the release")
    gs.record_task_event(t.goal_id, "question", "who signs the checksums")
    assert "who signs the checksums" in gs.task_brief()


def test_clear_phrasings_start_and_extend_a_task():
    assert gs.capture_task_events("Let's work on the memory benchmark for the release") == 0
    assert gs.current_task().title.startswith("memory benchmark")
    assert gs.capture_task_events("We decided to keep the scenarios deterministic and offline") == 1
    assert gs.capture_task_events("We still need to add a knowledge update scenario") == 1
    assert "keep the scenarios deterministic" in gs.task_brief() and "add a knowledge update" in gs.task_brief()


def test_chatter_and_questions_add_nothing():
    gs.open_task("Anything")
    assert gs.capture_task_events("haha that is funny") == 0
    assert gs.capture_task_events("did we decide to use the joint planner?") == 0


def test_an_abandoned_task_falls_out_of_the_brief():
    gs.open_task("Old work")
    assert gs.task_brief(now=__import__("time").time() + 30 * 86400) == ""


def test_find_task_recovers_what_the_passive_brief_drops():
    t = gs.open_task("RAIMS project", "build the RAIMS ingestion pipeline")
    gs.record_task_event(t.goal_id, "decision", "use SQLite for the staging store")
    goals = gs.load_goals()
    for g in goals:
        if g.goal_id == t.goal_id:
            g.updated_at -= 30 * 86400
    gs.save_goals(goals)

    # passive lookup: correctly silent past the idle window
    assert gs.current_task() is None
    assert gs.task_brief() == ""
    # explicit lookup: still finds it, brief still has the real recorded content
    found = gs.find_task("continue the raims project")
    assert found is not None and found.goal_id == t.goal_id
    assert "use SQLite" in gs.task_brief_for(found)
    # explicit lookup can also honor the idle gate when asked to
    assert gs.find_task("continue the raims project", include_idle=False) is None


def test_find_task_returns_none_for_no_match():
    gs.open_task("Something else entirely")
    assert gs.find_task("a totally unrelated query with no overlap") is None
    assert gs.find_task("") is None


def test_open_task_notifies_world_close_task_notifies_world(monkeypatch):
    calls = []
    import eli.world.local_world_bridge as bridge
    monkeypatch.setattr(bridge, "append_event", lambda *a, **k: calls.append((a, k)))

    t = gs.open_task("Bridge test project")
    assert calls and calls[0][0][0] == "task_opened"
    assert calls[0][0][3]["goal_id"] == t.goal_id

    ok = gs.close_task(t.goal_id)
    assert ok is True
    assert calls[-1][0][0] == "task_closed"
    assert calls[-1][0][3]["goal_id"] == t.goal_id
    # the task record itself is marked done, not deleted
    goals = gs.load_goals()
    assert any(g.goal_id == t.goal_id and g.status == "done" for g in goals)


def test_close_task_is_a_no_op_for_unknown_or_already_closed(monkeypatch):
    import eli.world.local_world_bridge as bridge
    monkeypatch.setattr(bridge, "append_event", lambda *a, **k: None)
    assert gs.close_task("no-such-goal-id") is False
    t = gs.open_task("Twice closed")
    assert gs.close_task(t.goal_id) is True
    assert gs.close_task(t.goal_id) is False  # already done, not active
