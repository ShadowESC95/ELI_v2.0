"""A transient GPU-detection failure must not be permanently cached as "cpu".

`_gpu_identity()` memoizes once per process for performance. It used to
memoize "cpu" for BOTH a confirmed CPU-only machine and a probe that merely
raised an exception (driver not ready yet at early boot, a transient
subprocess failure) -- so a one-off detection hiccup would permanently
mislabel the load-probe cache identity as "cpu" for the rest of the session,
even after the GPU became detectable. A genuine "no GPU found" (clean,
no exception) still memoizes, since that answer will not change mid-session.
"""
from __future__ import annotations

from eli.core import load_probe


def test_probe_exception_is_not_memoized(monkeypatch):
    monkeypatch.setattr(load_probe, "_gpu_identity_memo", None)

    def _boom():
        raise RuntimeError("nvidia-smi not ready yet")

    monkeypatch.setattr(
        "eli.core.startup_hardware_optimizer.detect_nvidia_gpus", _boom,
    )

    first = load_probe._gpu_identity()
    assert first == "cpu", "still a safe, conservative answer for this one call"
    assert load_probe._gpu_identity_memo is None, (
        "a probe FAILURE must not be permanently cached -- the next call "
        "should get a real chance to detect the GPU"
    )


def test_confirmed_no_gpu_is_memoized(monkeypatch):
    monkeypatch.setattr(load_probe, "_gpu_identity_memo", None)
    monkeypatch.setattr(
        "eli.core.startup_hardware_optimizer.detect_nvidia_gpus", lambda: [],
    )
    monkeypatch.setattr(
        "eli.core.startup_hardware_optimizer.select_gpu", lambda gpus: None,
    )

    first = load_probe._gpu_identity()
    assert first == "cpu"
    assert load_probe._gpu_identity_memo == "cpu", (
        "a clean, confirmed 'no GPU' answer should still memoize -- it will "
        "not change mid-session"
    )
