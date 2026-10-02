"""Where the orchestrator audit chain actually commits a row — and where it
must NOT.

First draft committed from AgentBus.dispatch() (Stage 6) using a pre-computed
"required stages" plan as the record — the chain recorded intent, not outcome,
and a stage never had to actually run to be logged as part of it. Moved to
the two points where a turn's REAL outcome is known: learning_coordinator's
finalize_turn() call site (non-streaming/action turns) and
_stream_with_followthrough's completion point (streaming CHAT turns) — both
read confidence/agents_used from data already computed by that point, not a
rule evaluated in advance.

Second fix, same session: _record_orchestrator_audit_turn originally read
self._pipeline_req_id for request_id — generated once, reused for every turn
on the engine singleton, so every row carried the SAME id instead of one per
turn. request_id is now a required caller-supplied argument, sourced from
trace["request_id"] (real per-turn, via self._request_counter) at every call
site instead.
"""
import sqlite3
import time
from unittest.mock import patch

ENGINE = __import__("pathlib").Path(__file__).resolve().parents[1] / "eli" / "kernel" / "engine.py"
AGENT_BUS = __import__("pathlib").Path(__file__).resolve().parents[1] / "eli" / "cognition" / "agent_bus.py"


def test_dispatch_no_longer_persists_to_the_audit_chain():
    """The premature commit point is gone — dispatch() doesn't know a turn's
    real outcome yet when it runs."""
    src = AGENT_BUS.read_text(encoding="utf-8")
    assert "orchestrator_audit_ledger" not in src
    assert "_persist_orchestrator_audit" not in src


def test_finalize_turn_call_site_commits_a_real_outcome():
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("from eli.cognition.learning_coordinator import finalize_turn")
    j = src.index("def _parse_intent", i)
    block = src[i:j]
    assert "_record_orchestrator_audit_turn(" in block
    # Sourced from the turn's actual result/trace, not a pre-computed plan.
    assert "result.get(\"ok\"" in block
    assert "trace.get(\"agents_used\")" in block


def test_streaming_completion_commits_a_real_outcome():
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("def _stream_with_followthrough")
    j = src.index("full = ", i)
    # The commit call must sit between the sentinel yield and the function's
    # own early-return checks, so it fires once per genuine streamed reply.
    k = src.index("yield MAIN_REPLY_DONE_SENTINEL", j)
    m = src.index("if not commit:", k)
    block = src[k:m]
    assert "_record_orchestrator_audit_turn(" in block
    assert 'action="CHAT"' in block


def test_record_orchestrator_audit_turn_writes_a_real_row(tmp_path):
    db_path = tmp_path / "orch.sqlite3"
    from eli.kernel.engine import CognitiveEngine

    eng = CognitiveEngine()
    eng.session_id = "s-live"
    eng.user_id = "u-live"

    with patch("eli.core.paths.orchestrator_audit_db_path", return_value=db_path):
        eng._record_orchestrator_audit_turn(
            request_id="req-live-001",
            action="NEWS_FETCH",
            agents_used=["system", "voice"],
            confidence=0.93,
            ok=True,
            outcome="ok",
            reasoning_mode="quick",
        )
        time.sleep(0.3)  # let the daemon write thread finish before the patch unwinds

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT request_id, session_id, user_id, action, agents_used, confidence, ok, outcome "
        "FROM orchestrator_audit"
    ).fetchone()
    conn.close()
    assert row == ("req-live-001", "s-live", "u-live", "NEWS_FETCH", "system,voice", 0.93, 1, "ok")


def test_request_id_is_a_required_argument_not_read_off_self():
    """Regression: the original version read self._pipeline_req_id, which is
    generated once and reused for every turn — every audit row carried the
    same id. request_id must now be a required kwarg with no self.* fallback."""
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("def _record_orchestrator_audit_turn")
    j = src.index("def _stream_with_followthrough", i)
    block = src[i:j]
    assert 'getattr(self, "_pipeline_req_id"' not in block
    assert "request_id: str," in block


def test_each_stream_with_followthrough_call_site_passes_a_real_request_id():
    """All three call sites must pass request_id sourced from trace["request_id"]
    (or an equally fresh per-call id) — never left to default to empty."""
    src = ENGINE.read_text(encoding="utf-8")
    sites = []
    idx = 0
    while True:
        idx = src.find("self._stream_with_followthrough(", idx)
        if idx == -1:
            break
        # Each call's closing paren is within a few lines — grab a generous window.
        sites.append(src[idx:idx + 400])
        idx += 1
    assert len(sites) == 3, f"expected 3 call sites, found {len(sites)}"
    for site in sites:
        assert "request_id=" in site


def test_consecutive_turns_on_the_same_engine_get_distinct_request_ids(tmp_path):
    """The actual bug: self._pipeline_req_id is set once and reused forever on
    this engine singleton. trace["request_id"] (self._request_counter) must
    not have that problem — two turns must never share an id."""
    from eli.kernel.engine import CognitiveEngine

    eng = CognitiveEngine()
    t1 = eng._next_trace("hello", {"action": "CHAT"}, "quick")
    t2 = eng._next_trace("world", {"action": "CHAT"}, "quick")
    assert t1["request_id"] != t2["request_id"]

    db_path = tmp_path / "orch.sqlite3"
    with patch("eli.core.paths.orchestrator_audit_db_path", return_value=db_path):
        eng._record_orchestrator_audit_turn(
            request_id=t1["request_id"], action="CHAT", agents_used=[],
            confidence=0.5, ok=True, outcome="ok")
        eng._record_orchestrator_audit_turn(
            request_id=t2["request_id"], action="CHAT", agents_used=[],
            confidence=0.5, ok=True, outcome="ok")
        time.sleep(0.3)

    conn = sqlite3.connect(str(db_path))
    ids = [r[0] for r in conn.execute("SELECT request_id FROM orchestrator_audit ORDER BY id")]
    conn.close()
    assert ids == [t1["request_id"], t2["request_id"]]
    assert ids[0] != ids[1]
