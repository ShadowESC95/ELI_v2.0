"""'Continue the X project' must reach a real, evidence-backed task lookup — the router's
RESUME_TASK pre-route plus its executor handler, end to end."""
import time

import pytest

from eli.execution.router_enhanced import route
from eli.execution.executor_enhanced import _execute_impl
from eli.planning import goal_store as gs


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "goal_store_path", lambda: tmp_path / "goals.json")
    import eli.world.local_world_bridge as bridge
    monkeypatch.setattr(bridge, "append_event", lambda *a, **k: None)


@pytest.mark.parametrize("text", [
    "continue the RAIMS project",
    "resume the RAIMS project",
    "let's pick back up the RAIMS project",
    "go back to the RAIMS project",
])
def test_resume_phrasings_route_to_resume_task(text):
    r = route(text)
    assert r.get("action") == "RESUME_TASK", f"{text!r} -> {r!r}"
    assert "raims" in (r.get("args") or {}).get("topic", "").lower()


def test_full_round_trip_finds_a_stale_task_and_states_staleness():
    g = gs.open_task("RAIMS project", "build the RAIMS ingestion pipeline", ["must stay offline-first"])
    gs.record_task_event(g.goal_id, "decision", "use SQLite for the staging store")
    gs.record_task_event(g.goal_id, "question", "still need to figure out retry backoff")
    goals = gs.load_goals()
    for gg in goals:
        if gg.goal_id == g.goal_id:
            gg.updated_at -= 40 * 86400
    gs.save_goals(goals)

    routed = route("continue the RAIMS project")
    assert routed["action"] == "RESUME_TASK"
    result = _execute_impl(routed["action"], routed["args"])
    assert result["ok"] is True
    assert result["found"] is True
    assert "40 day" in result["response"]
    assert "SQLite" in result["response"]
    assert "retry backoff" in result["response"]


def test_full_round_trip_is_honest_when_nothing_matches():
    routed = route("continue the nonexistent quantum flux project")
    assert routed["action"] == "RESUME_TASK"
    result = _execute_impl(routed["action"], routed["args"])
    assert result["ok"] is True
    assert result["found"] is False
    assert "don't have a saved task" in result["response"]


def test_empty_topic_is_a_clean_failure_not_a_crash():
    result = _execute_impl("RESUME_TASK", {})
    assert result["ok"] is False
    assert "what should i resume" in result["response"].lower()
