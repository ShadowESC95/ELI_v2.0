"""Silence stderr written by C extensions, at the file-descriptor level.

Python-level tricks (``contextlib.redirect_stderr``, a logging level, a library's
own ``verbose=False``) cannot stop this: llama.cpp, PortAudio/ALSA and JACK write
straight to fd 2 from C, below anything ``sys.stderr`` controls. Only swapping the
descriptor works.

This is the canonical implementation. Three ad-hoc copies of the same dup2 dance
predate it — ``mic_resolver._quiet_alsa``, ``audio_stt._suppress_alsa`` and an
inline block in ``kernel/engine.py``. They are left in place deliberately (each is
load-bearing on a path with its own tests); new callers should use this one rather
than adding a fourth, and the existing three can converge here when they are next
touched.

Scope discipline: this hides a *known, harmless* vendor banner. Never wrap a call
whose stderr might carry a real diagnosis — that is how a genuine failure becomes
invisible. Wrap the narrowest possible call, never a whole subsystem.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager

from eli.utils.log import get_logger

log = get_logger(__name__)


@contextmanager
def quiet_native_stderr(enabled: bool = True):
    """Redirect fd 2 to os.devnull for the duration of the block.

    Restores the original descriptor even if the body raises. A failure to
    redirect is never fatal: the worst case is the noise the caller wanted gone.
    """
    if not enabled:
        yield
        return

    saved = devnull = None
    try:
        sys.stderr.flush()
    except Exception:
        pass
    try:
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
    except Exception:
        # Could not swap the descriptor — carry on unsilenced rather than fail.
        log.debug("native stderr suppression unavailable", exc_info=True)
        _close(saved, devnull)
        yield
        return

    try:
        yield
    finally:
        try:
            os.dup2(saved, 2)
        except Exception:
            log.debug("native stderr restore failed", exc_info=True)
        _close(saved, devnull)


def _close(*fds) -> None:
    for fd in fds:
        if fd is None:
            continue
        try:
            os.close(fd)
        except Exception:
            pass
