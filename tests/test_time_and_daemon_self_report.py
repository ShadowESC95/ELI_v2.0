"""Two things ELI got wrong about itself, from one live 2.3.8 session.

**The clock.** At 10:47 ELI opened with "Morning's barely past noon" and the user
had to correct it. `part_of_day()` had existed in eli/runtime/reflection.py all
along and was correct, but only the proactive daemon's greeting and the daily-report
title called it — the chat prompt never carried the time, so the model guessed.
Three separate output blocklists already stripped "current time (authoritative" from
replies, filtering a string nothing produced: the consumers outlived the producer.

**The daemon.** In the same session the startup log said "Daemon started — continuous
learning active", the daemon visibly produced world suggestions, a news digest and a
pattern analysis, and the identity audit reported `daemon_running=False pid=0`.
`frontier_status` only looked for `proactive/daemon.pid`, and the GUI runs the daemon
as a thread inside its own process, so no pid file is ever written. Disowning a
capability you are actively using is the same class of fault as claiming one you lack.
"""
import json
import os
import re
import threading
import time
from datetime import datetime

import pytest


# ── the clock ─────────────────────────────────────────────────────────────────

def _brief(text: str = "hello") -> str:
    from eli.cognition.context_synthesiser import build_persona_handoff
    return json.dumps(build_persona_handoff(text), default=str)


def test_the_prompt_carries_the_current_time():
    assert "CURRENT TIME" in _brief(), "the model has no idea what time it is"


def test_the_time_in_the_prompt_is_actually_now():
    blob = _brief()
    m = re.search(r"CURRENT TIME[^\"]*?(\d{2}):(\d{2})", blob)
    assert m, "no clock time found in the brief"
    now = datetime.now()
    prompt_minutes = int(m.group(1)) * 60 + int(m.group(2))
    real_minutes = now.hour * 60 + now.minute
    assert abs(prompt_minutes - real_minutes) <= 2, "the injected time is not the wall clock"


def test_the_part_of_day_matches_the_hour():
    from eli.runtime.reflection import part_of_day
    blob = _brief()
    expected = part_of_day()
    assert expected in blob, f"brief does not say it is {expected}"


@pytest.mark.parametrize("hour,expected", [
    # Night was added after ELI opened with "Morning, Alex" at 00:21: with
    # only three bands, `hour < 12` claimed morning for every hour past
    # midnight and the model was handed that as authoritative fact. 18:16
    # stays "evening" below -- the case these tests were written for.
    (0, "night"), (4, "night"),
    (5, "morning"), (9, "morning"), (11, "morning"),
    (12, "afternoon"), (16, "afternoon"),
    (17, "evening"), (20, "evening"),
    (21, "night"), (23, "night"),
])
def test_part_of_day_boundaries(hour, expected):
    """10:47 is morning. The reply that started this said otherwise."""
    ts = time.mktime(datetime.now().replace(hour=hour, minute=30).timetuple())
    from eli.runtime.reflection import part_of_day
    assert part_of_day(ts) == expected


def test_the_brief_tells_the_model_not_to_guess():
    blob = _brief()
    assert "Do not guess the time" in blob


# ── the daemon ────────────────────────────────────────────────────────────────

def test_safe_mode_starts_no_proactive_daemon(monkeypatch):
    """`eli_startup.sh --safe-mode` exported ELI_SAFE_MODE and ELI_DISABLE_PROACTIVE, which nothing
    read: the daemon started as on any other run."""
    import types
    import eli.planning.proactive_daemon as pd
    from eli.kernel.engine import CognitiveEngine

    started = []
    monkeypatch.setattr(pd, "start_daemon", lambda: started.append(True) or "daemon")
    monkeypatch.delenv("ELI_PROACTIVE", raising=False)
    monkeypatch.delenv("ELI_PROACTIVE_STARTED", raising=False)
    engine = types.SimpleNamespace(add_observation=lambda *a, **k: None)

    monkeypatch.setenv("ELI_SAFE_MODE", "1")
    CognitiveEngine._start_proactive_listener(engine)
    assert started == [] and engine.proactive_daemon is None

    monkeypatch.delenv("ELI_SAFE_MODE")
    CognitiveEngine._start_proactive_listener(engine)
    assert started == [True] and engine.proactive_daemon == "daemon"


def _starters(monkeypatch, safe):
    """Everything engine start-up, the window's start-up and the launcher start in the background,
    recorded instead of run: the threads started, and the restores and daemon starts called."""
    import atexit
    import signal
    import types

    import eli.gui.app as launcher
    import eli.gui.eli_pro_audio_gui_v2_0 as gui
    import eli.perception.ambient_vision as av
    import eli.planning.proactive_daemon as pd
    import eli.runtime.agenda as agenda
    import eli.runtime.scheduled_tasks as scheduled
    from eli.kernel import engine as engine_mod
    from eli.memory.memory import Memory

    threads, calls = [], []
    monkeypatch.setattr(threading.Thread, "start", lambda self: threads.append(self.name))
    monkeypatch.setattr(atexit, "register", lambda f, *a, **k: f)
    monkeypatch.setattr(signal, "signal", lambda *a, **k: None)
    monkeypatch.setattr(engine_mod, "_eli_test_mode", lambda: False)    # start-up as in the app
    monkeypatch.delenv("ELI_TEST_MODE", raising=False)
    monkeypatch.delenv("ELI_PROACTIVE", raising=False)
    monkeypatch.delenv("ELI_PROACTIVE_STARTED", raising=False)
    monkeypatch.setattr(Memory, "upkeep_due", lambda self: True)
    monkeypatch.setattr(pd, "start_daemon", lambda: calls.append("proactive daemon"))
    monkeypatch.setattr(scheduled, "restore_scheduled_tasks", lambda: calls.append("scheduled tasks") or 0)
    monkeypatch.setattr(agenda, "restore", lambda: calls.append("reminders") or 0)
    monkeypatch.setattr(av, "start_ambient_vision", lambda: calls.append("ambient vision"))
    if safe:
        monkeypatch.setenv("ELI_SAFE_MODE", "1")
    else:
        monkeypatch.delenv("ELI_SAFE_MODE", raising=False)

    engine_mod.CognitiveEngine(auto_init_gguf=False, enforce_hardware_authority=False)
    gui.EliMainWindow._start_background_work(types.SimpleNamespace(_proactive_daemon=None))
    launcher._start_background_work()
    return threads, calls


def test_safe_mode_starts_no_background_work_at_all(monkeypatch):
    """Safe mode held back the proactive daemon (only where the engine started it) and plugin
    loading; the habit scheduler, which fires habits, the self-improvement loop, the reflection and
    habit loops, memory upkeep, the jobs and reminders of earlier sessions, the window's own start
    of the daemon, ambient vision and the launcher's warm-up all started as on any other run. Each
    starter now asks config.background_start_allowed."""
    threads, calls = _starters(monkeypatch, safe=False)
    assert {"eli-memory-upkeep", "eli-reflection", "eli-habits", "embed-prewarm"} <= set(threads), threads
    assert len(threads) >= 6, threads                    # and the habit scheduler's and the self-improvement loop's
    assert sorted(calls) == ["ambient vision", "proactive daemon", "proactive daemon",
                             "reminders", "scheduled tasks"], calls

    threads, calls = _starters(monkeypatch, safe=True)
    assert threads == [] and calls == [], f"safe mode started {threads} and {calls}"


def test_is_running_does_not_construct_a_daemon():
    """A status check that creates the thing it reports on is not a status check."""
    import eli.planning.proactive_daemon as pd
    before = pd._daemon
    pd.is_running()
    assert pd._daemon is before


def test_no_daemon_reports_not_running(monkeypatch):
    import eli.planning.proactive_daemon as pd
    monkeypatch.setattr(pd, "_daemon", None, raising=False)
    state = pd.is_running()
    assert state["running"] is False and state["mode"] == "none"


def test_a_live_in_process_daemon_is_reported_running(monkeypatch):
    import eli.planning.proactive_daemon as pd

    class _Live:
        running = True

    class _Thread:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(pd, "_daemon", _Live(), raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", _Thread(), raising=False)
    assert pd.is_running()["running"] is True


def test_a_dead_thread_is_not_reported_running(monkeypatch):
    """The flag stays True if the thread dies without calling stop(), so the flag
    alone would keep claiming the daemon is alive after it crashed."""
    import eli.planning.proactive_daemon as pd

    class _Live:
        running = True

    class _Dead:
        @staticmethod
        def is_alive():
            return False

    monkeypatch.setattr(pd, "_daemon", _Live(), raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", _Dead(), raising=False)
    state = pd.is_running()
    assert state["running"] is False
    assert state["thread_alive"] is False
    assert state["flag"] is True          # the discrepancy stays visible


def test_frontier_status_prefers_the_in_process_answer(monkeypatch):
    import eli.planning.proactive_daemon as pd

    class _Live:
        running = True

    class _Thread:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(pd, "_daemon", _Live(), raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", _Thread(), raising=False)

    from eli.runtime.frontier_status import build_frontier_status_report
    proactive = build_frontier_status_report("")["proactive"]
    assert proactive["running"] is True
    assert proactive["detected_via"] == "in_process"


def test_a_leftover_pid_file_does_not_make_the_daemon_running(monkeypatch, tmp_path):
    # the daemon only runs in ELI's own process now; a daemon.pid an older version left behind named
    # a process that had ended, and once the system gave that number to another program the status
    # said the daemon was running when nothing ran it
    import eli.planning.proactive_daemon as pd
    import eli.runtime.frontier_status as fs

    (tmp_path / "proactive").mkdir()
    (tmp_path / "proactive" / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(fs, "_artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(pd, "_daemon", None, raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", None, raising=False)
    proactive = fs._proactive_status()
    assert proactive["running"] is False
    assert proactive["detected_via"] == "none"


class _LoopDaemon:
    """Stands in for ProactiveDaemon: the same running flag / stop event protocol, no work."""

    def __init__(self):
        self.running = False
        self.paused = False
        self._stop_event = threading.Event()

    def run(self):
        stop = self._stop_event
        self.running = True
        while self.running and not stop.is_set():
            stop.wait(60)

    def stop(self):
        self.running = False
        self._stop_event.set()


def test_proactive_start_and_stop_act_on_the_in_process_daemon(monkeypatch, tmp_path):
    """PROACTIVE_START launched `python -m eli.proactive.proactive_daemon`, which does not exist,
    and replied "proactive started"; PROACTIVE_STOP only killed the pid in a file. The daemon ELI
    runs is a thread in its own process, so that is the one they start and stop."""
    import subprocess
    import eli.planning.proactive_daemon as pd
    from eli.execution.executor_enhanced import execute
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: launched.append(a))
    monkeypatch.setenv("ELI_ARTIFACTS_DIR", str(tmp_path))
    fake = _LoopDaemon()
    monkeypatch.setattr(pd, "_daemon", fake, raising=False)
    monkeypatch.setattr(pd, "_daemon_thread", None, raising=False)
    try:
        started = execute("PROACTIVE_START", {})
        assert not launched, "no process is launched: the daemon runs in this process"
        assert started["ok"] is True and pd.is_running()["running"] is True
        assert "Started" in started["response"]
        assert execute("PROACTIVE_STATUS", {})["running"] is True

        stopped = execute("PROACTIVE_STOP", {})
        assert stopped["stopped"] is True and pd.is_running()["running"] is False
        assert "Stopped" in stopped["response"]
        assert "was not running" in execute("PROACTIVE_STOP", {})["response"]

        # a stopped (or crashed) daemon starts again; it used to be started once per process
        again = execute("PROACTIVE_START", {})
        assert again["ok"] is True and pd.is_running()["running"] is True
        assert "already running" in execute("PROACTIVE_START", {})["response"]
    finally:
        pd.stop_daemon()


def test_a_stop_ends_a_sleeping_daemon_loop_at_once():
    """The loop slept with time.sleep between ticks, so a stop took effect only when the sleep ran out."""
    import eli.cognition.gguf_inference  # noqa: F401 -- imported by run() before its loop starts
    import eli.planning.proactive_daemon as pd
    daemon = object.__new__(pd.ProactiveDaemon)
    daemon.running, daemon.paused, daemon._stop_event = False, True, threading.Event()
    loop = threading.Thread(target=daemon.run, daemon=True)
    loop.start()
    for _ in range(200):
        if daemon.running:
            break
        time.sleep(0.01)
    time.sleep(0.5)          # inside the paused loop's wait by now
    daemon.stop()
    loop.join(2.0)
    assert not loop.is_alive()


# ── the probe budget ──────────────────────────────────────────────────────────

