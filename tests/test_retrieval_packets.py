"""retrieval_packets — build uniform StagePacket telemetry from each retrieval
stage's raw result. Pure shaping; structural assertions.
"""
from __future__ import annotations

from eli.runtime import retrieval_packets as rp


def test_parallel_packet_from_dict():
    p = rp.build_parallel_retrieval_packet({"keyword": [{"text": "a"}], "vector": [{"text": "b"}]})
    assert p.stage == "retrieval" and isinstance(p.summary, str)


def test_parallel_packet_tolerates_empty():
    assert hasattr(rp.build_parallel_retrieval_packet({}), "stage")


def test_hybrid_and_rerank_packets():
    assert hasattr(rp.build_hybrid_merge_packet([{"text": "x"}]), "stage")
    assert hasattr(rp.build_rerank_packet([{"text": "y"}]), "stage")


def test_context_source_trace():
    p1 = rp.build_parallel_retrieval_packet({"keyword": []})
    assert hasattr(rp.build_context_source_trace_packet([p1]), "stage")
