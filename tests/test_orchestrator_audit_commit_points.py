"""Every CognitiveEngine.process() call writes exactly one audit-chain row.

Live report (2026-10-03): about 10 messages over an hour left 2 rows in the
GUI's Audit tab. _process_impl has ~80 exits and the chain was only written
from two of them (finalize_turn's call site and the end of the followthrough
stream), so commands, fast paths, refusals and errors were never recorded.
process() now writes the row itself, once, however the turn ended, from what
that turn recorded about itself.

History kept from the earlier versions of this file: the chain was first
written from AgentBus.dispatch() using a planned stage list (intent, not
outcome), and later every row carried the same stale self._pipeline_req_id.
"""
import gc
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from eli.kernel import request_context as rc
from eli.kernel.engine import MAIN_REPLY_DONE_SENTINEL, CognitiveEngine
from eli.runtime import orchestrator_audit_ledger as L

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "eli" / "kernel" / "engine.py"
AGENT_BUS = ROOT / "eli" / "cognition" / "agent_bus.py"


@pytest.fixture()
def audit_db(tmp_path, monkeypatch):
    db = tmp_path / "orch.sqlite3"
    monkeypatch.setenv("ELI_ORCHESTRATOR_AUDIT_DB", str(db))
    yield db
    L.flush(timeout=10.0)  # nothing still queued when the env var goes back


def _rows(db):
    assert L.flush(timeout=10.0)
    if not Path(db).exists():
        return []
    return list(reversed(L.recent_turns(limit=100, db_path=db)))


def _bare(session="gui-session", user="desktop"):
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._fallback_session_id = session
    eng._fallback_user_id = user
    return eng


def _run(eng, impl, *args, **kwargs):
    with patch.object(CognitiveEngine, "_process_impl", impl):
        return eng.process(*args, **kwargs)


# ── one row per call, every exit shape ───────────────────────────────────────

def test_a_command_turn_writes_one_row_with_its_own_identity(audit_db):
    eng = _bare()
    _run(eng, lambda self, *a, **k: {"ok": True, "action": "OPEN_APP", "content": "Opened."},
         "open firefox", source="api:alice", user_id="alice", session_id="s-alice")

    rows = _rows(audit_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["request_id"].startswith("req-")
    assert (r["user_id"], r["session_id"], r["source"]) == ("alice", "s-alice", "api:alice")
    assert (r["action"], r["ok"], r["outcome"], r["parent_request_id"]) == ("OPEN_APP", True, "ok", "")
    assert r["elapsed_ms"] is not None
    assert L.verify_chain(db_path=audit_db)["ok"] is True


def test_ten_turns_make_ten_rows(audit_db):
    """The live symptom, directly."""
    eng = _bare()
    for i in range(10):
        _run(eng, lambda self, *a, **k: {"ok": True, "content": "fine"}, f"message {i}")
    rows = _rows(audit_db)
    assert len(rows) == 10
    assert len({r["request_id"] for r in rows}) == 10
    assert L.verify_chain(db_path=audit_db)["chained"] == 10


def test_a_failed_action_records_its_error(audit_db):
    _run(_bare(), lambda self, *a, **k: {"ok": False, "action": "OPEN_APP", "error": "app not found"},
         "open nothing")
    r = _rows(audit_db)[0]
    assert (r["ok"], r["outcome"]) == (False, "app not found")


def test_an_exception_is_recorded_then_reraised(audit_db):
    def boom(self, *a, **k):
        raise ValueError("pipeline blew up")

    with pytest.raises(ValueError):
        _run(_bare(), boom, "hi")
    r = _rows(audit_db)[0]
    assert r["ok"] is False
    assert r["outcome"].startswith("error: ValueError: pipeline blew up")


def test_a_plain_text_reply_is_recorded(audit_db):
    _run(_bare(), lambda self, *a, **k: "Good morning.", "good morning")
    r = _rows(audit_db)[0]
    assert (r["ok"], r["outcome"]) == (True, "ok")


def _streaming(*pieces, fail_after=None):
    def impl(self, *a, **k):
        def g():
            for i, p in enumerate(pieces):
                if fail_after is not None and i == fail_after:
                    raise RuntimeError("model crashed mid-reply")
                yield p
        return g()
    return impl


def test_a_streamed_reply_is_recorded_once_when_it_ends(audit_db):
    eng = _bare()
    with patch.object(CognitiveEngine, "_process_impl",
                      _streaming("Hel", "lo", MAIN_REPLY_DONE_SENTINEL)):
        gen = eng.process("hi", stream=True)
        assert next(gen) == "Hel"
        assert _rows(audit_db) == []  # still running: no row yet
        assert list(gen) == ["lo", MAIN_REPLY_DONE_SENTINEL]

    rows = _rows(audit_db)
    assert len(rows) == 1
    assert (rows[0]["action"], rows[0]["ok"], rows[0]["outcome"]) == ("CHAT", True, "ok")


def test_an_empty_stream_is_not_ok(audit_db):
    eng = _bare()
    with patch.object(CognitiveEngine, "_process_impl", _streaming(MAIN_REPLY_DONE_SENTINEL)):
        list(eng.process("hi", stream=True))
    r = _rows(audit_db)[0]
    assert (r["ok"], r["outcome"]) == (False, "empty_reply")


def test_a_stream_closed_early_is_cancelled(audit_db):
    eng = _bare()
    with patch.object(CognitiveEngine, "_process_impl", _streaming("a", "b", "c")):
        gen = eng.process("hi", stream=True)
        next(gen)
        gen.close()
    rows = _rows(audit_db)
    assert len(rows) == 1
    assert (rows[0]["ok"], rows[0]["outcome"]) == (False, "cancelled")


def test_a_stream_dropped_unread_is_still_recorded(audit_db):
    eng = _bare()
    with patch.object(CognitiveEngine, "_process_impl", _streaming("a")):
        gen = eng.process("hi", stream=True)
        del gen
        gc.collect()
    rows = _rows(audit_db)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "abandoned"


def test_a_stream_that_fails_midway_records_the_error(audit_db):
    eng = _bare()
    with patch.object(CognitiveEngine, "_process_impl", _streaming("a", "b", fail_after=1)):
        gen = eng.process("hi", stream=True)
        with pytest.raises(RuntimeError):
            list(gen)
    rows = _rows(audit_db)
    assert len(rows) == 1
    assert rows[0]["outcome"].startswith("error: RuntimeError")


# ── facts come from this turn, never a previous one ──────────────────────────

def test_action_confidence_and_agents_come_from_the_turns_own_meta(audit_db):
    eng = _bare()

    def first(self, *a, **k):
        self._last_request_meta = {"action": "NEWS_FETCH", "confidence": 0.81,
                                   "agents_used": ["web", "critic"]}
        return {"ok": True, "content": "Here's the news."}

    _run(eng, first, "news")
    # The session store still holds turn 1's meta; turn 2 set none of its own.
    _run(eng, lambda self, *a, **k: "ok then", "thanks")

    r1, r2 = _rows(audit_db)
    assert (r1["action"], r1["confidence"], r1["agents_used"]) == ("NEWS_FETCH", 0.81, "web,critic")
    assert r2["action"] == "UNKNOWN"
    assert r2["confidence"] is None  # unmeasured, not a 0.0 that reads as "measured, worthless"
    assert r2["agents_used"] == ""


def test_trace_and_row_share_the_turns_request_id(audit_db):
    eng = _bare()

    def impl(self, *a, **k):
        trace = self._next_trace("q", {"action": "CHAT"}, "quick")
        return {"ok": True, "action": "CHAT", "rid": trace["request_id"]}

    out = _run(eng, impl, "q")
    assert _rows(audit_db)[0]["request_id"] == out["rid"]


def test_next_trace_outside_a_turn_leaves_no_id_behind():
    eng = CognitiveEngine.__new__(CognitiveEngine)
    t1 = eng._next_trace("hello", {"action": "CHAT"}, "quick")
    t2 = eng._next_trace("world", {"action": "CHAT"}, "quick")
    assert t1["request_id"] != t2["request_id"]
    assert rc.request_id_var.get() is None


def test_the_recorded_mode_is_the_one_the_turn_actually_used(audit_db):
    def impl(self, *a, **k):
        self._reasoning_mode = "quick"  # e.g. the phatic fast path dropping research
        return "hi"

    _run(_bare(), impl, "hey", reasoning_mode="research")
    assert _rows(audit_db)[0]["reasoning_mode"] == "quick"


# ── nested turns ─────────────────────────────────────────────────────────────

def test_a_nested_turn_gets_its_own_row_linked_to_its_parent(audit_db):
    eng = _bare()

    def impl(self, user_input, *a, **k):
        if user_input == "two questions":
            self.process("first part?")
            self.process("second part?")
            return {"ok": True, "action": "CHAT"}
        return {"ok": True, "action": "WEB_SEARCH"}

    _run(eng, impl, "two questions", source="user")
    a, b, outer = _rows(audit_db)
    assert outer["parent_request_id"] == ""
    assert a["parent_request_id"] == b["parent_request_id"] == outer["request_id"]
    assert a["source"] == b["source"] == "user"
    assert len({a["request_id"], b["request_id"], outer["request_id"]}) == 3


def test_a_followthrough_run_is_labelled_as_one(audit_db):
    eng = _bare()

    def impl(self, user_input, *a, **k):
        if user_input == "let me check the news":
            self._in_followthrough = True
            self.process("fetch the latest news")
            return {"ok": True, "action": "CHAT"}
        return {"ok": True, "action": "NEWS_FETCH"}

    _run(eng, impl, "let me check the news", source="user")
    child, outer = _rows(audit_db)
    assert (child["source"], child["action"]) == ("followthrough", "NEWS_FETCH")
    assert child["parent_request_id"] == outer["request_id"]
    assert outer["source"] == "user"


# ── identity under the real callers' threading ───────────────────────────────

def test_concurrent_turns_each_record_their_own_identity(audit_db):
    eng = _bare(session="engine-default", user="engine-default-user")
    barrier = threading.Barrier(2)

    def impl(self, *a, **k):
        barrier.wait(timeout=5)  # both turns in flight at once
        return {"ok": True, "action": f"A_{self.user_id}"}

    with patch.object(CognitiveEngine, "_process_impl", impl):
        ts = [threading.Thread(target=eng.process, args=("hi",),
                               kwargs={"user_id": u, "session_id": f"s-{u}"})
              for u in ("alice", "bob")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

    rows = _rows(audit_db)
    assert len(rows) == 2
    for r in rows:
        assert r["action"] == f"A_{r['user_id']}".upper()
        assert r["session_id"] == f"s-{r['user_id']}"


def test_starlette_stream_row_is_the_requesting_user(audit_db):
    """/v1/chat/stream pulls each chunk through anyio in a fresh context; the
    row is written after the last chunk and must still be alice's."""
    anyio = pytest.importorskip("anyio")
    concurrency = pytest.importorskip("starlette.concurrency")
    eng = _bare(session="engine-default", user="engine-default-user")

    def gen():
        yield from eng.process("hi", stream=True, user_id="alice", session_id="s-alice")

    async def drive():
        async for _ in concurrency.iterate_in_threadpool(gen()):
            pass

    with patch.object(CognitiveEngine, "_process_impl", _streaming("a", "b")):
        anyio.run(drive)

    r = _rows(audit_db)[0]
    assert (r["user_id"], r["session_id"], r["ok"]) == ("alice", "s-alice", True)


# ── one commit point ─────────────────────────────────────────────────────────

def test_the_pipeline_body_never_writes_the_chain_itself():
    """A second writer inside _process_impl would double-record some turns."""
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("    def _process_impl(")
    j = src.index("\n    def ", i + 10)
    body = src[i:j]
    assert "orchestrator_audit_ledger" not in body
    assert "record_turn_async" not in body
    assert "_record_turn_audit_row" not in body
    assert "_record_orchestrator_audit_turn" not in src
    assert src.count("record_turn_async(") == 1


def test_followthrough_no_longer_takes_a_request_id():
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("def _stream_with_followthrough")
    assert "request_id" not in src[i:src.index(")", i)]


def test_dispatch_does_not_write_the_chain():
    """dispatch() runs before a turn's outcome is known."""
    src = AGENT_BUS.read_text(encoding="utf-8")
    assert "orchestrator_audit_ledger" not in src
    assert "_persist_orchestrator_audit" not in src
