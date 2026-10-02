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
    eng._pipeline_req_id = "req-live-001"
    eng.session_id = "s-live"
    eng.user_id = "u-live"

    with patch("eli.core.paths.orchestrator_audit_db_path", return_value=db_path):
        eng._record_orchestrator_audit_turn(
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
