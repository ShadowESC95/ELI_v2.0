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
