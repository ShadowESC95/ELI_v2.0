"""The daemon's foreground gate must be re-read, never snapshotted per tick.

Each block the gate protects runs multi-minute LLM work, so a reading taken at
the top of a tick is stale by the time later guards consult it. Live on a
CPU-offloaded 27B, one user turn waited behind BOTH a 241s news synthesis and a
156s self-improvement pass that started from a single reading taken seconds
before the user typed. The in-flight abort can yield a generation already
running; only a fresh reading stops the NEXT one starting.
"""
import inspect
import re

from eli.planning import proactive_daemon as pd


def test_gate_reports_the_broker_state():
    assert callable(pd._foreground_busy)


def test_gate_is_fail_open_when_the_broker_is_unavailable(monkeypatch):
    """A broken broker must not permanently silence the daemon."""
    import eli.cognition.inference_broker as br
    monkeypatch.setattr(br, "foreground_recently_active",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")))
    assert pd._foreground_busy() is False


def test_gate_is_re_read_at_every_guard(monkeypatch):
    calls = {"n": 0}
    import eli.cognition.inference_broker as br

    def _counting(window=30.0):
        calls["n"] += 1
        return False

    monkeypatch.setattr(br, "foreground_recently_active", _counting)
    for _ in range(3):
        pd._foreground_busy()
    assert calls["n"] == 3, "the gate memoised instead of re-reading"


def _tick_source() -> str:
    src = inspect.getsource(pd.ProactiveDaemon)
    return src


def test_tick_does_not_snapshot_the_gate_into_a_variable():
    src = _tick_source()
    assert not re.search(r"_fg_busy\s*=", src), (
        "the tick snapshots the foreground state again; later guards in the same "
        "iteration would read a value that is minutes stale")
    assert "not _foreground_busy()" in src, (
        "guards no longer call the live gate")
