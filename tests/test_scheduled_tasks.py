"""Scheduled/timed background tasks (overnight jobs)."""
from __future__ import annotations
import time
from eli.runtime.background_tasks import BackgroundTasks
# The schedule store lives under the in-project test artifacts dir (conftest sets
# ELI_ARTIFACTS_DIR); _store_path() honours it, so these tests never touch the real
# artifacts/runtime/scheduled_tasks.json that holds the user's standing jobs.


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
    # "tomorrow" → a near-future day. NOT >12h (tomorrow-morning is <12h away when
    # it's already late evening — that assertion was wall-clock-flaky).
    assert 0 < parse_when("do X tomorrow") - now < 48 * 3600


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


# ── Increment 5: durability across restarts ──────────────────────────────────
def _clear_store():
    import eli.runtime.scheduled_tasks as ST
    for e in ST._load_store():
        ST.forget(e["pid"])


def test_schedule_persists_and_forget_removes():
    import eli.runtime.scheduled_tasks as ST
    _clear_store()
    r = ST.schedule_request("research X in 999 minutes", when_spec="in 999 minutes")
    assert any(e["pid"] == r["pid"] for e in ST._load_store())
    ST.forget(r["pid"])
    assert not any(e["pid"] == r["pid"] for e in ST._load_store())
    _clear_store()


def test_restore_rearms_future_task():
    import eli.runtime.scheduled_tasks as ST
    _clear_store()
    r = ST.schedule_request("research Y in 999 minutes", when_spec="in 999 minutes")
    ST._RESTORED = False
    n = ST.restore_scheduled_tasks()
    assert n >= 1
    ST.forget(r["pid"]); _clear_store()


def test_restore_catches_up_missed_task():
    import time, uuid
    import eli.runtime.scheduled_tasks as ST
    from eli.runtime.background_tasks import get_background_tasks
    _clear_store()
    pid = uuid.uuid4().hex[:12]
    ST._persist_add({"pid": pid, "request": "missed job", "when_spec": "overnight",
                     "kind": "research", "when_ts": time.time() - 3600, "created": time.time()})
    ST._RESTORED = False
    ST.restore_scheduled_tasks()
    jobs = [t for t in get_background_tasks().list(limit=50) if (t.get("meta") or {}).get("pid") == pid]
    assert jobs and float(jobs[0]["scheduled_for"]) > time.time()  # rescheduled to the future, not the past
    ST.forget(pid); _clear_store()


# ── Phase 2/3: active project (memory namespacing + task ownership) ───────────
def test_active_project_set_get_clear(tmp_path, monkeypatch):
    import eli.runtime.active_project as AP
    AP.clear_active()
    assert AP.get_active() is None and AP.active_name() == ""
    AP.set_active("Atlas", "project.atlas")
    assert AP.active_name() == "Atlas" and AP.active_memory_tag() == "project.atlas"
    AP.clear_active()
    assert AP.get_active() is None


def test_task_ownership_follows_active_project():
    import eli.runtime.active_project as AP
    import eli.runtime.scheduled_tasks as ST
    AP.clear_active()
    r0 = ST.schedule_request("research A in 999 minutes", when_spec="in 999 minutes")
    assert r0.get("project") == ""
    ST.forget(r0["pid"])
    AP.set_active("Atlas", "project.atlas")
    r1 = ST.schedule_request("research B in 999 minutes", when_spec="in 999 minutes")
    assert r1.get("project") == "Atlas"
    from eli.runtime.background_tasks import get_background_tasks
    assert (get_background_tasks().get(r1["job_id"])["meta"] or {}).get("project") == "Atlas"
    ST.forget(r1["pid"]); AP.clear_active()


def test_memory_tagging_only_facts_when_active(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib, eli.memory as MEM
    import eli.runtime.active_project as AP
    AP.set_active("PT", "project.pt_unique_tag")
    m = MEM.get_memory()
    m.store_memory("a concrete project fact", kind="memory")
    m.store_memory("a reflection note", kind="reflection")
    hits = m.get_memories_by_tag("project.pt_unique_tag", limit=20)
    assert any("concrete project fact" in h["text"] for h in hits)
    assert not any("reflection note" in h["text"] for h in hits)  # reflections stay global
    AP.clear_active()


# ── Finish-up: state providers (Phase 4 sim/component resume hook) ────────────
def test_state_providers_capture_restore():
    import eli.runtime.state_providers as SP
    box = {"v": "original"}
    SP.register("unit_test_prov", lambda: box["v"], lambda x: box.__setitem__("v", x))
    try:
        snap = SP.capture_all()
        assert snap.get("unit_test_prov") == "original"
        box["v"] = "mutated"
        assert SP.restore_all(snap) >= 1
        assert box["v"] == "original"
    finally:
        SP.unregister("unit_test_prov")


def test_state_providers_isolate_failures():
    import eli.runtime.state_providers as SP
    def _boom():
        raise RuntimeError("nope")
    SP.register("bad", _boom, lambda x: None)
    try:
        snap = SP.capture_all()          # must not raise
        assert "bad" not in snap          # failed capture is skipped
    finally:
        SP.unregister("bad")
