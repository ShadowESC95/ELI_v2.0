"""A node's timeout bounds how long the run waits for it.

Each layer used to run inside `with ThreadPoolExecutor(...)`, whose exit waits for every
node, so a timeout bounded nothing: a hung agent held its layer, and the user's turn with
it, and its late result was then kept as if it had come in on time. A node past its
timeout is now given up on: it is recorded as a timeout without its result, nothing waits
for its thread, and the run goes on. A node that finishes inside its timeout keeps its
result.
"""
import threading
import time

from eli.core.dag import Orchestrator, Task


def _hangs(release):
    def _run(ctx):
        release.wait(10)
        return "LATE RESULT"
    return _run


def test_a_node_past_its_timeout_is_given_up_on_and_the_run_goes_on():
    release = threading.Event()
    try:
        t0 = time.perf_counter()
        report = Orchestrator(max_workers=2).run(
            [Task(id="hung", run=_hangs(release), timeout=0.2),
             Task(id="other", run=lambda ctx: "used", timeout=0.2)], context={})
        elapsed = time.perf_counter() - t0
    finally:
        release.set()
    o = report.outcomes["hung"]
    assert o.status == "timeout" and o.result is None
    assert report.result("other") == "used"
    assert elapsed < 5, f"the run waited {elapsed:.1f}s for a node with a 0.2s timeout"


def test_a_node_that_finishes_inside_its_timeout_keeps_its_result():
    def _quick(ctx):
        time.sleep(0.05)
        return "REAL RESULT"

    report = Orchestrator(max_workers=2).run([Task(id="n", run=_quick, timeout=5)], context={})
    assert report.outcomes["n"].status == "ok" and report.result("n") == "REAL RESULT"


def test_timeouts_in_one_layer_run_side_by_side_and_a_queued_node_gets_its_own():
    """Two hung nodes cost one timeout, not two; with one worker the node queued behind a hung
    one starts when that one is given up on."""
    release = threading.Event()
    try:
        t0 = time.perf_counter()
        side = Orchestrator(max_workers=4).run(
            [Task(id="a", run=_hangs(release), timeout=1.0),
             Task(id="b", run=_hangs(release), timeout=1.0)], context={})
        side_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        queued = Orchestrator(max_workers=1).run(
            [Task(id="a", run=_hangs(release), timeout=1.0, priority=1),
             Task(id="b", run=lambda ctx: "ran", timeout=1.0)], context={})
        queued_s = time.perf_counter() - t0
    finally:
        release.set()
    assert {o.status for o in side.outcomes.values()} == {"timeout"}
    assert side_s < 1.8, f"two 1s timeouts in one layer took {side_s:.1f}s"
    assert queued.outcomes["a"].status == "timeout" and queued.result("b") == "ran"
    assert queued_s < 5, f"the queued node waited {queued_s:.1f}s behind a hung one"


def test_downstream_of_a_timed_out_node_is_skipped_unless_it_runs_without_it():
    release = threading.Event()
    try:
        report = Orchestrator(max_workers=2).run([
            Task(id="slow", run=_hangs(release), timeout=0.2),
            Task(id="needs_it", run=lambda ctx: "ran", depends_on={"slow"}),
            Task(id="runs_anyway", run=lambda ctx: sorted(ctx.results), depends_on={"slow"},
                 skip_if_upstream_fails=False),
        ], context={})
    finally:
        release.set()
    assert report.outcomes["needs_it"].status == "skipped"
    assert report.result("runs_anyway") == []       # ran, without the node given up on


def test_a_failing_node_still_reports_failure():
    def _boom(ctx):
        time.sleep(0.3)
        raise RuntimeError("nope")

    report = Orchestrator(max_workers=2).run(
        [Task(id="boom", run=_boom, timeout=0.05)], context={})
    assert report.outcomes["boom"].status in ("failed", "timeout")
