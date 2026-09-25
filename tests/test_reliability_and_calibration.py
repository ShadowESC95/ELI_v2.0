"""Measured reliability per action, success predictions scored against what happened, and honest absence wording."""
import pytest

from eli.runtime import evidence_ledger as led
from eli.runtime.evidence_arbitration import EvidenceState, absence_statement


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    monkeypatch.setattr(led, "_default_db_path", lambda: path)
    return path


def _run(db, action, ok, t, predicted=None):
    payload = {"ok": ok}
    if predicted is not None:
        payload["predicted"] = predicted
    led.record_event("tool_execution", action=action, subject=f"s{t}", payload=payload, outcome="ok" if ok else "failed", db_path=db, timestamp=t)


def test_no_prediction_without_history(db):
    assert led.predict_success("SCREENSHOT", db_path=db) is None


def test_reliability_follows_recent_outcomes(db):
    import time
    now = time.time()
    for i in range(6):
        _run(db, "SCREENSHOT", False, now - 100 + i * 15)
    for i in range(6):
        _run(db, "OPEN_APP", True, now - 100 + i * 15)
    assert led.predict_success("SCREENSHOT", db_path=db) < 0.25 < 0.75 < led.predict_success("OPEN_APP", db_path=db)
    assert [r["action"] for r in led.unreliable_actions(db_path=db)] == ["SCREENSHOT"]


def test_recent_runs_count_more_than_old_ones(db):
    import time
    now = time.time()
    for i in range(6):
        _run(db, "GPU_STATUS", False, now - 25 * 86400 + i * 15)
    for i in range(6):
        _run(db, "GPU_STATUS", True, now - 3600 + i * 15)
    assert led.predict_success("GPU_STATUS", db_path=db) > 0.7


def test_calibration_scores_predictions_against_outcomes(db):
    import time
    now = time.time()
    for i in range(10):
        _run(db, "A", True, now - 500 + i * 15, predicted=0.9)
    for i in range(10):
        _run(db, "B", i % 2 == 0, now - 300 + i * 15, predicted=0.9)
    rep = led.calibration_report(db_path=db)
    assert rep["n"] == 20 and 0.0 < rep["brier"] < 0.5
    band = [b for b in rep["bands"] if b["range"].startswith("0.80")][0]
    assert band["predicted"] == 0.9 and band["observed"] == 0.75


def test_absence_is_worded_by_why_it_is_absent():
    assert "looked for" in absence_statement(EvidenceState.NOT_FOUND, "the lighthouse code")
    assert "have not looked" in absence_statement(EvidenceState.NOT_INSPECTED, "your screen")
    assert "failed" in absence_statement(EvidenceState.INSPECTION_FAILED, "the GPU")
    assert absence_statement("something else", "x") == ""


def test_the_scope_of_a_search_is_stated_so_a_denial_covers_only_that(monkeypatch):
    from eli.cognition import memory_diag
    rec = memory_diag.retrieval_record(2, 0, 0, 0, None, searched={"semantic": 0, "exact": 1, "claims": 0, "archive": None})
    text = memory_diag.block(rec)
    assert "archive: not searched" in text and "exact codes/phrases 1" in text and "Only say nothing is stored for this scope" in text


def test_the_archive_is_searched_when_live_evidence_is_thin(tmp_path, monkeypatch):
    import sqlite3
    from eli.memory.memory import Memory
    from eli.memory.retrieval import retrieve_for_turn
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    mem.store_memory("The old warehouse alarm code was ZEBRA-4410 before the refit last year", source="assistant", kind="fact", importance=0.2)
    c = sqlite3.connect(mem.db_path)
    c.execute("update memories set timestamp = timestamp - 4000 * 86400, ts = ts - 4000 * 86400, last_seen = last_seen - 4000 * 86400, event_ts = event_ts - 4000 * 86400")
    c.commit()
    c.close()
    mem.apply_weight_decay()
    assert mem.archive_faded()["archived"] == 1
    res = retrieve_for_turn(mem, "what was the old warehouse alarm code", use_cache=False, rerank=False)
    assert res.searched["archive"] == 1
    assert [h for h in res.semantic_hits if str(h.get("id")).startswith("archive:")]


def test_exact_codes_are_looked_up_as_written(tmp_path, monkeypatch):
    from eli.memory.memory import Memory
    from eli.memory.retrieval import retrieve_for_turn
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    mem.store_memory("The validation lighthouse code is ORCHID-7319 and the bird is a silver kestrel", source="user")
    res = retrieve_for_turn(mem, "which fact mentions ORCHID-7319", use_cache=False, rerank=False)
    assert res.searched["semantic"] + res.searched["exact"] >= 1
    assert "orchid-7319" in " ".join(str(h.get("text") or "") for h in res.semantic_hits).lower()
