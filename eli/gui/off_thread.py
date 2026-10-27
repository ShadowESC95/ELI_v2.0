"""Blocking work off the Qt window's thread, with the window kept alive meanwhile.

No Qt import here: the caller passes its QApplication, so the helper is shared by the main window
and the start-up window and is testable without a Qt binding.
"""
from __future__ import annotations

import threading
import time


def run_pumping(fn, app, *args, _poll: float = 0.02, **kwargs):
    """Run blocking, widget-free `fn` off the Qt main thread while pumping `app`'s event loop so
    the window stays responsive, then return fn's result on the calling thread (exceptions
    propagate). `app` is the QApplication instance, or None to run inline (headless / tests).

    detect_hardware() shells out to nvidia-smi/lspci with multi-second timeouts and is deliberately
    uncached (it must read CURRENT free VRAM), and the load planner has llama.cpp simulate the load:
    run inline on the window's thread, either froze it ("Not Responding"). `fn` runs on a daemon
    thread here; no widget is ever touched off-thread, the caller applies the result on its own
    thread once it returns.
    """
    if app is None:
        return fn(*args, **kwargs)
    box: dict = {}

    def _run():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:            # re-raised on the caller's thread below
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="eli-off-gui-thread")
    worker.start()
    while worker.is_alive():
        app.processEvents()
        time.sleep(_poll)
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")
