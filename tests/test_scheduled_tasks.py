"""Scheduled/timed background tasks (overnight jobs)."""
from __future__ import annotations
import time
from eli.runtime.background_tasks import BackgroundTasks


def test_immediate_submit_still_works():
    bt = BackgroundTasks()
    jid = bt.submit("x", lambda: 42)
    bt.wait(jid, timeout=3)
    d = bt.get(jid)
    assert d["status"] == "done" and d["result"] == 42 and d["kind"] == "task"


def test_scheduled_task_fires_after_delay():
    bt = BackgroundTasks()
    jid = bt.schedule("overnight", lambda: "built", delay=0.2, kind="code")
    d0 = bt.get(jid)
    assert d0["status"] == "scheduled" and d0["scheduled_for"] is not None and d0["kind"] == "code"
    time.sleep(0.5)
    d1 = bt.get(jid)
    assert d1["status"] == "done" and d1["result"] == "built"


def test_cancel_scheduled_before_fire():
    bt = BackgroundTasks()
    jid = bt.schedule("later", lambda: "should-not-run", delay=30)
    assert bt.cancel(jid) is True
    assert bt.get(jid)["status"] == "cancelled"
    time.sleep(0.1)
    assert bt.get(jid)["result"] is None  # never ran


def test_schedule_when_absolute_time():
    bt = BackgroundTasks()
    jid = bt.schedule("at-time", lambda: "ok", when=time.time() + 0.2)
    assert bt.get(jid)["status"] == "scheduled"
    time.sleep(0.5)
    assert bt.get(jid)["status"] == "done"


def test_list_includes_scheduled():
    bt = BackgroundTasks()
    bt.schedule("s", lambda: 1, delay=60)
    statuses = [t["status"] for t in bt.list()]
    assert "scheduled" in statuses


# ── Increment 2: SCHEDULE_TASK capability (router + parse + kind + handler) ───
def test_schedule_router_prepass_routes_and_skips():
    from eli.execution.router_enhanced import _eli_schedule_prepass
    for q in ["research the Riemann hypothesis overnight", "build a todo app at 2am",
              "design me a new element overnight", "upgrade yourself tonight"]:
        r = _eli_schedule_prepass(q)
        assert r and r["action"] == "SCHEDULE_TASK"
    for q in ["what's on tonight?", "hey how's it going", "play music"]:
        assert _eli_schedule_prepass(q) is None


def test_infer_kind():
    from eli.runtime.scheduled_tasks import infer_kind
    assert infer_kind("build a script to parse logs") == "code"
    assert infer_kind("design me a new element") == "research"
    assert infer_kind("upgrade yourself") == "self_upgrade"
    assert infer_kind("reflect on today") == "reflection"


def test_parse_when_future():
    import time
    from eli.runtime.scheduled_tasks import parse_when
    now = time.time()
    assert parse_when("do X in 3 hours") - now > 2.5 * 3600
    assert parse_when("do X overnight") - now > 0      # next 2am, always future
    assert parse_when("do X tomorrow") - now > 12 * 3600


def test_schedule_task_action_schedules(monkeypatch):
    # far-future so the worker never fires during the test
    from eli.execution.executor_enhanced import execute
    r = execute("SCHEDULE_TASK", {"request": "research dark matter in 999 minutes",
                                   "when": "research dark matter in 999 minutes"})
    assert r["ok"] and r.get("job_id") and r.get("kind") == "research"
    from eli.runtime.background_tasks import get_background_tasks
    job = get_background_tasks().get(r["job_id"])
    assert job["status"] == "scheduled"
    get_background_tasks().cancel(r["job_id"])  # cleanup


def test_schedule_request_stores_meta_for_edit():
    from eli.runtime.scheduled_tasks import schedule_request
    from eli.runtime.background_tasks import get_background_tasks
    r = schedule_request("research batteries in 999 minutes", when_spec="in 999 minutes", kind="research")
    d = get_background_tasks().get(r["job_id"])
    assert d["meta"]["request"] == "research batteries in 999 minutes"
    assert d["meta"]["when_spec"] == "in 999 minutes"
    assert d["meta"]["kind"] == "research"
    get_background_tasks().cancel(r["job_id"])
