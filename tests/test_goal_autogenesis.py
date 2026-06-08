"""Goal autogenesis: ELI turns his own signals into governed goals.

Closes the autonomy gap where the goal store was always empty (create_goal was
operator-only) so the scheduler/goal-tick ticked nothing. Goals are proposal_only,
deduped by a stable id, capped, and thresholded.
"""
import importlib


def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_GOAL_STORE", str(tmp_path / "goals.json"))
    # Reimport so the store path picks up the env each time.
    import eli.planning.goal_store as gs
    importlib.reload(gs)
    import eli.planning.goal_autogenesis as ga
    importlib.reload(ga)
    return ga, gs


def test_autogenesis_creates_governed_goals_from_signals(monkeypatch, tmp_path):
    ga, gs = _fresh(monkeypatch, tmp_path)
    world = [
        {"action": "SELF_ANALYZE", "reason": "repair_pressure=0.72", "priority": 0.72},
        {"action": "MEMORY_STATUS", "reason": "low", "priority": 0.30},   # < 0.6 → filtered
    ]
    patterns = [
        {"type": "recurring_error", "error": "LoRA build_job failed", "count": 30},
        {"type": "recurring_error", "error": "blip", "count": 2},          # < 5 → filtered
        {"type": "time_habit", "error": "x"},                              # not error → filtered
    ]
    created = ga.propose_goals_from_signals(world, patterns)
    assert len(created) == 2, created

    goals = gs.load_goals()
    assert len(goals) == 2
    # All governed (proposal_only) — never silent execution.
    assert all(g.autonomy_mode == "proposal_only" for g in goals)
    assert all(ga.AUTO_TAG in g.tags for g in goals)
    # Highest-priority signal (the 30x failure) is the top goal.
    assert max(goals, key=lambda g: g.priority).title.startswith("Resolve recurring failure")


def test_autogenesis_is_idempotent(monkeypatch, tmp_path):
    ga, gs = _fresh(monkeypatch, tmp_path)
    world = [{"action": "SELF_ANALYZE", "reason": "r", "priority": 0.8}]
    first = ga.propose_goals_from_signals(world, [])
    second = ga.propose_goals_from_signals(world, [])
    assert len(first) == 1
    assert len(second) == 0          # same signal must not spawn a duplicate goal
    assert len(gs.load_goals()) == 1


def test_autogenesis_generates_self_improvement_goals(monkeypatch, tmp_path):
    # Generative (not just failure-reactive): code-health signals about ELI's own
    # code become self-betterment goals, thresholded so noise (small fns, TODOs) is out.
    ga, gs = _fresh(monkeypatch, tmp_path)
    improvements = [
        {"file": "engine.py", "type": "long_function", "function": "process",
         "lines": 450, "suggestion": "split it"},
        {"file": "executor.py", "type": "duplicate_code", "count": 12, "suggestion": "dedup"},
        {"file": "r.py", "type": "long_function", "function": "tiny", "lines": 80},  # < 150 → out
        {"file": "x.py", "type": "todos", "count": 9},                               # noise → out
    ]
    created = ga.propose_goals_from_signals(improvements=improvements)
    assert len(created) == 2
    goals = gs.load_goals()
    assert all("self_improve" in g.tags for g in goals)
    assert all(g.autonomy_mode == "proposal_only" for g in goals)


def test_autogenesis_respects_cap(monkeypatch, tmp_path):
    ga, gs = _fresh(monkeypatch, tmp_path)
    # Many distinct high-priority signals, but the cap bounds active auto goals.
    world = [
        {"action": f"ACTION_{i}", "reason": "r", "priority": 0.9}
        for i in range(ga.MAX_AUTO_GOALS + 4)
    ]
    total = 0
    for _ in range(10):  # repeated ticks
        total += len(ga.propose_goals_from_signals(world, []))
    assert total <= ga.MAX_AUTO_GOALS
    assert len(gs.load_goals()) <= ga.MAX_AUTO_GOALS
