"""Tests for the background task manager, the cost/should-background heuristic,
and the CHECK_JOB / BACKGROUND_JOBS executor actions. No model required."""

import time


# ── background task manager ─────────────────────────────────────────────────

def test_background_job_marks_inference_background_so_it_yields():
    # A background job's model calls must be marked background so a foreground turn
    # preempts them (no more 200-530s memory waits queued behind a PDF/codegen job).
    import eli.cognition.gguf_inference as gi
    from eli.runtime.background_tasks import BackgroundTasks
    gi.set_background_inference(False)  # this (main) thread = foreground
    bt = BackgroundTasks(max_workers=1)
    seen = {}
    try:
        def _job():
            seen["bg"] = gi.is_background_inference()
            return "ok"
        bt.wait(bt.submit("job", _job), timeout=5)
        assert seen.get("bg") is True            # job inference is background → yields
        assert gi.is_background_inference() is False  # foreground thread untouched
    finally:
        bt.shutdown()


def test_background_runs_and_reports():
    from eli.runtime.background_tasks import BackgroundTasks
    bt = BackgroundTasks(max_workers=2)
    try:
        def _work(x):
            time.sleep(0.3)
            return {"ok": True, "script_path": f"/tmp/x{x}.py", "solved": True}
        jid = bt.submit("codegen", _work, 7)
        assert bt.get(jid)["status"] in ("queued", "running")
        done = bt.wait(jid, timeout=5)
        assert done["status"] == "done"
        assert done["result"]["solved"] is True
        assert "/tmp/x7.py" in done["note"]
    finally:
        bt.shutdown()


def test_background_captures_failure():
    from eli.runtime.background_tasks import BackgroundTasks
    bt = BackgroundTasks(max_workers=1)
    try:
        def boom():
            raise ValueError("nope")
        jid = bt.submit("fail", boom)
        bt.wait(jid, timeout=5)
        t = bt.get(jid)
        assert t["status"] == "failed" and "ValueError" in t["error"]
    finally:
        bt.shutdown()


# ── cost / should-background heuristic ──────────────────────────────────────

def test_cost_light_vs_heavy():
    from eli.coding.cost import should_background
    assert should_background("add two numbers")["background"] is False
    heavy = should_background("run a monte carlo simulation and benchmark the optimisation")
    assert heavy["background"] is True


def test_cost_explicit_phrasing_wins():
    from eli.coding.cost import should_background
    assert should_background("implement dijkstra in the background and notify me")["background"] is True
    assert should_background("run a huge monte carlo simulation right now")["background"] is False


def test_cost_open_ended_backgrounds():
    # Open-ended/hard tasks must background (they ran foreground and blocked the
    # UI for minutes before this fix).
    from eli.coding.cost import should_background
    assert should_background("solve the P vs NP problem")["background"] is True
    assert should_background("design a compiler from scratch")["background"] is True
    # …but a trivial script stays foreground.
    assert should_background("write a function to add two numbers")["background"] is False


# ── executor job-inspection actions ─────────────────────────────────────────

def test_executor_check_and_list_jobs():
    from eli.runtime.background_tasks import get_background_tasks
    from eli.execution.executor_enhanced import execute
    bt = get_background_tasks()
    jid = bt.submit("unit-test-job", lambda: {"ok": True, "script_path": "/tmp/u.py", "solved": True})
    bt.wait(jid, timeout=5)

    r = execute("CHECK_JOB", {"job_id": jid})
    assert r["ok"] and "done" in r["content"].lower() and "/tmp/u.py" in r["content"]

    r2 = execute("BACKGROUND_JOBS", {})
    assert r2["ok"] and f"#{jid}" in r2["content"]

    r3 = execute("CHECK_JOB", {"job_id": 999999})
    assert r3["ok"] is False and "no background job" in r3["content"].lower()
