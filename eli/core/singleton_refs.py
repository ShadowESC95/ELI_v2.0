"""Keep None, True and False from being freed by an extension that drops references to them.

Before Python 3.12 these objects are reference counted like any other. A C extension that returns
None without taking a reference takes one away on every call, and when the count reaches zero the
interpreter aborts: "Fatal Python error: none_dealloc: deallocating None". PySide6 6.12.0 does this
on Python 3.11 on every Qt call that returns nothing (setText, setItem, addItem, ...), measured
-1.000 per call; ELI's window refreshes its audit table 2000 cells at a time and died after about
twenty minutes. From 3.12 these objects are immortal and nothing here applies.
"""
from __future__ import annotations

import ctypes
import gc
import os
import sys

# Far more references than any session can lose: at a million lost a second this lasts weeks.
_RESERVE = 1 << 40

_pinned = False


def applies() -> bool:
    return sys.version_info < (3, 12) and sys.implementation.name == "cpython"


def pin_singletons() -> bool:
    """Add a large reserve to the reference counts of None, True and False. Once, before 3.12 only."""
    global _pinned
    if _pinned or not applies():
        return False
    for obj in (None, True, False):
        # ob_refcnt is the first field of every object on these versions.
        ctypes.c_ssize_t.from_address(id(obj)).value += _RESERVE
    _pinned = True
    return True


def none_refs_lost_per_qt_call(samples: int = 2000) -> float:
    """References to None one Qt call that returns nothing takes away; 0.0 for a sound binding and
    on 3.12+. Needs a QApplication, which it creates when there is none (off-screen on a Linux
    machine with no display; Windows and macOS always have their own platform)."""
    if not applies():
        return 0.0
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])  # noqa: F841 - must exist for widgets
    label = QLabel()
    label.setText("x")
    gc.collect()
    before = sys.getrefcount(None)
    for _ in range(samples):
        label.setText("x")
    gc.collect()
    lost = (before - sys.getrefcount(None)) / samples
    label.deleteLater()
    return lost
