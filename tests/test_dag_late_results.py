"""A node that overruns its timeout must not be discarded after being waited for.

The orchestrator runs each layer inside `with ThreadPoolExecutor(...)`, whose
exit calls shutdown(wait=True) and therefore blocks until every submitted task
finishes. Recording a timeout and dropping the result paid the full wall-clock
cost and threw the finished answer away. Live on a CPU-offloaded 27B: a memory
node needing 121.408s against a ~121s ceiling was written off as a timeout while
the bus still waited 121.557s for it, so the reply was generated with
memory_chars=0 and grounding fell to 0.30 (low).
"""
import time

from eli.core.dag import Orchestrator, Task


def test_result_that_lands_after_its_timeout_is_still_used():
    def _slow(ctx):
        time.sleep(0.5)
        return "REAL RESULT"

    report = Orchestrator(max_workers=2).run(
        [Task(id="slow", run=_slow, timeout=0.1)], context={})
    o = report.outcomes["slow"]
    assert o.status != "timeout", (
        "the node was written off as a timeout even though the pool had already "
        "waited for it to finish")
    assert o.result == "REAL RESULT"


def test_the_harvest_adds_no_extra_waiting():
    """Two slow nodes must not serialise into a longer run than the work itself."""
    def _slow(ctx):
        time.sleep(0.4)
        return "ok"

    t0 = time.perf_counter()
    report = Orchestrator(max_workers=4).run(
        [Task(id="a", run=_slow, timeout=0.05),
         Task(id="b", run=_slow, timeout=0.05)], context={})
    elapsed = time.perf_counter() - t0
    assert all(report.outcomes[i].result == "ok" for i in ("a", "b"))
    assert elapsed < 1.5, f"harvest added waiting: {elapsed:.2f}s for 0.4s of work"


def test_a_failing_node_still_reports_failure():
    def _boom(ctx):
        time.sleep(0.3)
        raise RuntimeError("nope")

    report = Orchestrator(max_workers=2).run(
        [Task(id="boom", run=_boom, timeout=0.05)], context={})
    assert report.outcomes["boom"].status in ("failed", "timeout")
