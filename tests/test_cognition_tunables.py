"""User-tunable cognition parameters: registry integrity, persistence/clamp, and
that the cognition code reads the live config value (GUI control is real)."""
from __future__ import annotations
from unittest.mock import patch
import pytest
import eli.core.config as C
from eli.core import cognition_tunables as T


def test_registry_integrity():
    keys = [t.key for t in T.TUNABLES]
    assert len(keys) == len(set(keys)), "duplicate tunable keys"
    for t in T.TUNABLES:
        assert t.key.startswith("cog."), t.key
        assert t.minimum <= t.default <= t.maximum, t.key
        assert t.help and t.label and t.group
    # groups() preserves all entries
    assert sum(len(v) for v in T.groups().values()) == len(T.TUNABLES)


def test_get_default_when_unset():
    C.delete("cog.mem_semantic_shown")
    assert T.get_tunable("cog.mem_semantic_shown") == 24


def test_set_and_clamp_roundtrip():
    assert T.set_tunable("cog.rerank_top_k", 33)
    assert T.get_tunable("cog.rerank_top_k") == 33
    T.set_tunable("cog.rerank_top_k", 99999)          # over max
    assert T.get_tunable("cog.rerank_top_k") == 80
    T.set_tunable("cog.rerank_top_k", -5)             # under min
    assert T.get_tunable("cog.rerank_top_k") == 1
    T.reset_defaults()
    assert T.get_tunable("cog.rerank_top_k") == 20


def test_unknown_key_rejected():
    with pytest.raises(KeyError):
        T.get_tunable("cog.does_not_exist")
    assert T.set_tunable("cog.does_not_exist", 5) is False


def test_snapshot_one_read_all_keys():
    snap = T.snapshot()
    assert set(snap) == {t.key for t in T.TUNABLES}
    assert all(isinstance(v, int) for v in snap.values())


class _FM:
    db_path = "/tmp/x.sqlite3"
    def recall_memory(self, q, limit=8):
        return [{"id": str(i), "text": f"fact {i} about research"} for i in range(limit)]
    def search_conversations(self, q, user_id=None, limit=5): return []
    def get_recent_conversation(self, limit=6, user_id=None): return []
    def get_session_summaries(self, user_id=None, limit=3): return []


@pytest.mark.parametrize("val", [6, 19])
def test_memory_agent_honours_live_tunable(val):
    from eli.cognition.agent_bus import BusMemoryAgent
    C.set("cog.mem_semantic_recall", val)
    C.set("cog.mem_semantic_shown", val)
    try:
        with patch("eli.memory.get_memory", return_value=_FM()):
            r = BusMemoryAgent().run(
                "tell me everything about my research and projects in depth",
                {"action": "CHAT"}, "s", "u")
        assert (r.data or {}).get("memory_context", "").count("fact ") == val
    finally:
        T.reset_defaults()
