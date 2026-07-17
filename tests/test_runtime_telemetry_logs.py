"""Behaviour lock: "give me the raw metrics / agent logs for that cycle" is
answered from REAL logged telemetry, never a confabulated "I have no logs".

A real session: the user asked for raw metric breakdowns and agent logs; the
request routed to SELF_REPORT (a settings snapshot with no event rows), so ELI
concluded it had "no logs" — while agent_dispatches (per-agent timings) and
runtime_events held the exact data. Two things are locked:

  * routing  — such a request reaches EXPLAIN_LAST_RESPONSE, not SELF_REPORT
  * evidence — EXPLAIN_LAST_RESPONSE carries the real agent_dispatches +
    runtime_events telemetry
"""

import sqlite3

import pytest

from eli.execution.router_enhanced import route
from eli.runtime import control_contracts as cc


@pytest.mark.parametrize("text", [
    "I want raw metric breakdowns and agent logs for that cycle",
    "show me the agent logs for the last response",
    "give me the metrics for that request",
    "what's the trace for the previous turn",
    "raw logs for that run please",
])
def test_metrics_request_routes_to_grounded_last_response(text):
    assert str(route(text).get("action")) == "EXPLAIN_LAST_RESPONSE"


@pytest.mark.parametrize("text", ["delete the logs", "play music", "clear that trace"])
def test_unrelated_requests_do_not_hijack_the_metrics_route(text):
    assert str(route(text).get("action")) != "EXPLAIN_LAST_RESPONSE"


def test_last_response_evidence_includes_real_dispatch_telemetry(monkeypatch):
    fake = [
        {"ts": 1.0, "action": "CHAT",
         "agents_used": ["memory", "orchestrator"], "confidence": 0.62,
         "elapsed_ms": 809.0, "ok": True, "summary": "x"},
    ]
    monkeypatch.setattr("eli.cognition.agent_bus.recent_dispatches", lambda limit=8: fake)
    monkeypatch.setattr(cc, "_last_trace", lambda engine=None: {"request_id": "req-1"})
    ev = cc.build_control_evidence(engine=None, action="EXPLAIN_LAST_RESPONSE",
                                   args={}, user_input="agent logs for that cycle")
    text = ev["content"]
    assert "Recent agent-dispatch telemetry" in text
    assert "elapsed=809ms" in text and "memory, orchestrator" in text
    assert ev["evidence_source"] == "last_trace+telemetry"


def test_evidence_ok_even_when_no_trace_but_telemetry_exists(monkeypatch):
    """The confabulation was 'no logs' — telemetry alone makes the evidence usable."""
    monkeypatch.setattr(cc, "_last_trace", lambda engine=None: {})
    monkeypatch.setattr("eli.cognition.agent_bus.recent_dispatches",
                        lambda limit=8: [{"ts": 1.0, "action": "CHAT", "agents_used": ["memory"],
                                          "confidence": 0.9, "elapsed_ms": 100.0, "ok": True,
                                          "summary": "x"}])
    ev = cc.build_control_evidence(engine=None, action="EXPLAIN_LAST_RESPONSE",
                                   args={}, user_input="metrics for that cycle")
    assert ev["ok"] is True
    assert "Recent agent-dispatch telemetry" in ev["content"]


def test_recent_dispatches_reads_real_rows(tmp_path, monkeypatch):
    db = tmp_path / "agent.sqlite3"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE agent_dispatches (id INTEGER PRIMARY KEY, ts REAL, action TEXT,
                   agents_used TEXT, confidence REAL, elapsed_ms REAL, ok INTEGER, summary TEXT)""")
    con.execute("INSERT INTO agent_dispatches (ts, action, agents_used, confidence, elapsed_ms, ok, summary) "
                "VALUES (2.0,'CHAT','memory,system',0.8,150.0,1,'ok')")
    con.commit(); con.close()
    import eli.cognition.agent_bus as ab
    monkeypatch.setattr("eli.core.paths.agent_db_path", lambda: db)
    rows = ab.recent_dispatches(5)
    assert rows and rows[0]["action"] == "CHAT"
    assert rows[0]["agents_used"] == ["memory", "system"]
