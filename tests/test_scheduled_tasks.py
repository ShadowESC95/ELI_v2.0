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
