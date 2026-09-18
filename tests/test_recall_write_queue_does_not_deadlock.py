"""`_flush_recall_writes_locked()` is documented as "must be called with
`_recall_write_lock` held" -- and it always was, from `_enqueue_recall_write()`.
But its own body ended with a stray, unreachable-looking tail: a one-line
docstring reading "Public flush -- call on idle or shutdown to drain the
queue." followed by `with _recall_write_lock: _flush_recall_writes_locked()`,
with no `def` line separating it from the function above. That tail was
never a separate
function -- it was the END of `_flush_recall_writes_locked()`'s own body, so
every real flush (the queue hitting `_RECALL_FLUSH_BATCH` items) executed
straight into it: re-acquiring a plain, non-reentrant `threading.Lock` it was
already holding, then recursing into itself while blocked on that lock.
`threading.Lock` never times out and is never released by the same thread
re-entering it, so this was a guaranteed deadlock on every 50th queued
recall-write in any sufficiently long-running process -- not just under full
test-suite load, though that's the only place thousands of prior
`recall_memory()` calls reliably pushed the queue that far in one process.

Fixed by restoring the missing `def flush_recall_writes():` line, making the
public wrapper an actual separate function instead of dead code appended to
the locked helper.
"""
import threading

from eli.memory import memory as m


def _run_with_timeout(fn, *, timeout=5.0):
    """Run `fn` in a background thread; return True if it completed in time.
    A real deadlock would hang the whole test process if called directly."""
    done = threading.Event()

    def _target():
        fn()
        done.set()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    finished = done.wait(timeout=timeout)
    return finished


def test_flush_recall_writes_is_a_real_standalone_function():
    """The missing `def` line made this unreachable/uncallable before the fix."""
    assert callable(m.flush_recall_writes)
    assert m.flush_recall_writes.__doc__ and "Public flush" in m.flush_recall_writes.__doc__


def test_enqueue_does_not_deadlock_when_the_batch_threshold_is_hit(tmp_path, monkeypatch):
    """Queue exactly _RECALL_FLUSH_BATCH writes against a throwaway sqlite db --
    this triggers the internal flush on the last enqueue. Before the fix, this
    call never returned."""
    db_path = tmp_path / "recall_queue_test.sqlite3"

    monkeypatch.setattr(m, "_recall_write_queue", [], raising=False)

    calls = []

    def _fill_queue():
        for i in range(m._RECALL_FLUSH_BATCH):
            m._enqueue_recall_write(db_path, lambda conn, i=i: calls.append(i))

    finished = _run_with_timeout(_fill_queue, timeout=5.0)
    assert finished, (
        "_enqueue_recall_write hung when the flush batch threshold was hit -- "
        "the recall-write-queue deadlock is back"
    )
    # Queue was drained by the flush, not left sitting at the threshold.
    assert m._recall_write_queue == []


def test_flush_recall_writes_does_not_deadlock_on_a_nonempty_queue(tmp_path, monkeypatch):
    db_path = tmp_path / "recall_queue_test2.sqlite3"
    monkeypatch.setattr(m, "_recall_write_queue", [(db_path, lambda conn: None)], raising=False)

    finished = _run_with_timeout(m.flush_recall_writes, timeout=5.0)
    assert finished, "flush_recall_writes() hung -- the recall-write-queue deadlock is back"
