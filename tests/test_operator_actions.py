"""operator_actions — the proposal-queue file helpers (jsonl round-trip, paths).
Pure file logic, isolated to tmp.
"""
from __future__ import annotations

from pathlib import Path

from eli.execution import operator_actions as oa


def test_queue_path_explicit(tmp_path):
    assert oa.queue_path(str(tmp_path / "q.jsonl")) == Path(str(tmp_path / "q.jsonl"))


def test_queue_path_default():
    p = oa.queue_path()
    assert isinstance(p, Path) and p.name == "proposal_queue.jsonl"


def test_read_missing_is_empty(tmp_path):
    assert oa._read_jsonl(tmp_path / "nope.jsonl") == []


def test_write_then_read_roundtrip(tmp_path):
    p = tmp_path / "q.jsonl"
    oa._write_jsonl(p, [{"id": "a", "state": "offered"}, {"id": "b", "state": "done"}])
    got = oa._read_jsonl(p)
    assert len(got) == 2 and got[0]["id"] == "a"
