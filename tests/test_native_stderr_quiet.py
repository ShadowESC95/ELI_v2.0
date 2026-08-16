"""Locks on suppressing C-level stderr, and on not over-suppressing it.

A launch of the shipped AppImage printed, before ELI had done anything wrong:
the ALSA/JACK enumeration storm from PortAudio, "neural backend unavailable"
six times, and ~20 copies of llama.cpp's "init: embeddings required but some
input tokens were not marked as outputs -> overriding". Every one of those is
harmless, and together they made a completely healthy boot read as a crash.

None of it is reachable from Python: llama.cpp, PortAudio and JACK write to
fd 2 from C, below anything sys.stderr or a `verbose=False` flag controls.

The risk in fixing it is obvious and is what most of these tests are about —
a suppressor that leaks, that swallows a real diagnosis, or that eats the
return value is worse than the noise it removes.
"""
import os
import subprocess
import sys

import pytest

from eli.utils.native_io import quiet_native_stderr

# A child process writing to fd 2 the way a C extension does — not via
# sys.stderr, which a Python-level redirect would have caught anyway.
_WRITER = (
    "import os,sys;"
    "os.write(2, b'NATIVE_NOISE\\n');"
    "os.write(1, b'REAL_RESULT\\n')"
)


def _run(code: str):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_native_stderr_is_actually_silenced():
    out = _run(
        "from eli.utils.native_io import quiet_native_stderr\n"
        f"with quiet_native_stderr():\n    {_WRITER}\n"
    )
    assert "NATIVE_NOISE" not in out.stderr, "fd-2 write escaped the suppressor"


def test_stdout_is_untouched():
    """The mic probe reports LIVE/DEAD on stdout from inside the guard."""
    out = _run(
        "from eli.utils.native_io import quiet_native_stderr\n"
        f"with quiet_native_stderr():\n    {_WRITER}\n"
    )
    assert "REAL_RESULT" in out.stdout


def test_stderr_works_again_afterwards():
    """A leaked descriptor would silently blind the whole process."""
    out = _run(
        "from eli.utils.native_io import quiet_native_stderr\n"
        "import os\n"
        "with quiet_native_stderr():\n    os.write(2, b'INSIDE\\n')\n"
        "os.write(2, b'AFTER\\n')\n"
    )
    assert "AFTER" in out.stderr
    assert "INSIDE" not in out.stderr


def test_stderr_is_restored_even_when_the_body_raises():
    out = _run(
        "from eli.utils.native_io import quiet_native_stderr\n"
        "import os\n"
        "try:\n"
        "    with quiet_native_stderr():\n        raise ValueError('boom')\n"
        "except ValueError:\n    pass\n"
        "os.write(2, b'AFTER\\n')\n"
    )
    assert "AFTER" in out.stderr


def test_exceptions_propagate():
    """Silencing output must not silence failures."""
    with pytest.raises(ValueError):
        with quiet_native_stderr():
            raise ValueError("boom")


def test_disabled_passes_stderr_through():
    out = _run(
        "from eli.utils.native_io import quiet_native_stderr\n"
        f"with quiet_native_stderr(enabled=False):\n    {_WRITER}\n"
    )
    assert "NATIVE_NOISE" in out.stderr


def test_nesting_restores_correctly():
    out = _run(
        "from eli.utils.native_io import quiet_native_stderr\n"
        "import os\n"
        "with quiet_native_stderr():\n"
        "    with quiet_native_stderr():\n        os.write(2, b'INNER\\n')\n"
        "    os.write(2, b'OUTER\\n')\n"
        "os.write(2, b'AFTER\\n')\n"
    )
    assert "AFTER" in out.stderr
    assert "INNER" not in out.stderr and "OUTER" not in out.stderr


def test_does_not_leak_descriptors():
    """Called once per embedding — a leak here exhausts the process."""
    before = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
    if before is None:
        pytest.skip("no /proc/self/fd on this platform")
    for _ in range(200):
        with quiet_native_stderr():
            pass
    after = len(os.listdir("/proc/self/fd"))
    assert after <= before + 1, f"descriptor leak: {before} -> {after}"


# ── the callers that motivated it ───────────────────────────────────────────
def test_embedder_wraps_only_the_embedding_call():
    """Scoped narrowly on purpose: wrapping model construction or the whole
    store would hide a genuine load failure."""
    import inspect
    from eli.memory import vector_store

    src = inspect.getsource(vector_store)
    assert "quiet_native_stderr" in src, "embedder no longer suppresses llama.cpp noise"
    guarded = src[src.index("with quiet_native_stderr():"):]
    assert "create_embedding" in guarded[:200], "the guard drifted off the embed call"


def test_xtts_probe_is_cached_not_repeated():
    """Six callers each paid a failed-import walk and logged the same line."""
    import builtins

    from eli.perception import tts_xtts

    tts_xtts._reset_availability_cache()
    attempts = 0
    real = builtins.__import__

    def counting(name, *a, **k):
        nonlocal attempts
        if name == "TTS":
            attempts += 1
        return real(name, *a, **k)

    builtins.__import__ = counting
    try:
        for _ in range(6):
            tts_xtts.xtts_available()
    finally:
        builtins.__import__ = real

    assert attempts <= 1, f"{attempts} import attempts for 6 availability checks"


def test_mic_probe_runs_under_the_alsa_guard():
    """_run_probe was the one PyAudio construction in mic_resolver not wrapped,
    and it is the probe that actually runs at startup."""
    import inspect

    from eli.perception import mic_resolver

    src = inspect.getsource(mic_resolver._run_probe)
    guard_at = src.index("_quiet_alsa()")
    audio_at = src.index("pyaudio.PyAudio()")
    assert guard_at < audio_at, "PyAudio is constructed outside the ALSA guard"
