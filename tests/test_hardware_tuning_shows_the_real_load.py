"""The Hardware Tuning tab must report the same figures as the terminal.

The tab showed only the TUNER's output: a recommendation computed before the
model loads. The load then plans against what is free on every card — all of it
printed to the terminal as [LOAD_PLAN] lines, and none of it reaching the tab.
So a launch showed "ctx=4096" in the panel while the session ran at 8192.

Rather than recompute anything for the panel (a second source of truth that can
drift), the dock subscribes to the lines ELI already writes.
"""
import logging
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "eli" / "gui" / "panels" / "startup.py"
GUI = pathlib.Path(__file__).resolve().parents[1] / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py"


def _relay_namespace():
    """Load the relay without importing PySide6 (mocked in this suite)."""
    src = SRC.read_text(encoding="utf-8")
    i = src.index("HARDWARE_LOG_MARKERS = (")
    j = src.index("class HardwareTuningDock(QDockWidget):")
    ns = {"logging": logging}
    exec(src[i:j], ns)
    return ns


class _Signal:
    def __init__(self):
        self.sent = []

    def emit(self, msg):
        self.sent.append(msg)


class _Dock:
    def __init__(self):
        self.log_line = _Signal()


def _drive(messages):
    ns = _relay_namespace()
    dock = _Dock()
    relay = ns["HardwareTuningLogRelay"](dock)
    lg = logging.getLogger("eli.test.hw_relay")
    lg.handlers = [relay]
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    for m in messages:
        lg.debug(m)
    return dock.log_line.sent


REAL_TERMINAL_LINES = [   # a 2.5.17-dev launch on two RTX 2060 SUPER, 2026-10-19
    "[STARTUP_DIALOG][HW_OPT] regenerated profile ctx=50000 gpu_layers=43 batch=128 "
    "gpu=NVIDIA GeForce RTX 2060 SUPER ×2 free_vram=13991MB",
    "[LOAD_PLAN] your settings fit as asked",
    "[LOAD_PLAN] 2 configurations simulated by llama.cpp",
    "[LOAD_PLAN] gemma-4-E4B-it-Q8_0.gguf: ctx=50000 batch=128 42/42 layers on GPU + output "
    "(CUDA0 NVIDIA GeForce RTX 2060 SUPER: uses 3241 of 6330 MB free; CUDA1 NVIDIA GeForce RTX 2060 SUPER: "
    "uses 3831 of 7689 MB free), KV q8_0, flash attention on, measured",
    "[LOAD_PLAN] mode budgets re-derived from effective ctx=50000: ['max_tokens', 'mode_presets']",
    "[GUI][LOAD] mode budget re-derivation skipped: no model loaded",
    "[HW_AUTHORITY] advisory (not enforced): n_ctx 50000 > recommended 40960",
]


def test_every_hardware_line_reaches_the_dock():
    assert _drive(REAL_TERMINAL_LINES) == REAL_TERMINAL_LINES


def test_what_loaded_is_shown():
    """The plan line says what actually loads and where — the single most important figure the tab
    was missing."""
    sent = _drive(REAL_TERMINAL_LINES)
    assert any("layers on GPU" in m and "measured" in m for m in sent)


def test_unrelated_logging_is_not_dumped_into_the_tab():
    noise = ["[COGNITIVE] Habit scheduler started",
             "[MEMORY] Fetched 9 conversation turns",
             "[ROUTER] explicit priority pipeline installed",
             "[PROACTIVE] autonomy tick: code_changed=False"]
    assert _drive(noise) == []


def test_a_broken_record_does_not_take_the_app_down():
    """A logging handler that raises breaks whatever was logging."""
    ns = _relay_namespace()
    relay = ns["HardwareTuningLogRelay"](None)
    rec = logging.LogRecord("eli.x", logging.DEBUG, __file__, 1, "[GUI][LOAD] x", None, None)
    relay.emit(rec)          # dock is None
    relay._dock = object()   # no log_line attribute
    relay.emit(rec)


def test_the_relay_is_scoped_to_eli_not_the_root_logger():
    """Attaching to root would format every record in the process — including
    third-party libraries — just to substring-match it."""
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def _install_hardware_log_relay")
    body = src[i:src.index("\n    def ", i + 10)]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    assert 'getLogger("eli")' in code
    assert "getLogger()" not in code


def test_the_relay_does_not_raise_the_log_level():
    """Forcing DEBUG would add console noise the operator did not ask for; if the
    lines are absent from the terminal they should be absent from the tab too."""
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def _install_hardware_log_relay")
    body = src[i:src.index("\n    def ", i + 10)]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    assert "setLevel" not in code


def test_the_dock_appends_on_the_gui_thread():
    """These records originate on worker threads; a QPlainTextEdit may only be
    touched on the GUI thread, so the relay emits a signal."""
    src = SRC.read_text(encoding="utf-8")
    assert "log_line = pyqtSignal(str)" in src
    assert "self.log_line.connect(self.append_log)" in src


def test_the_relay_is_installed_once():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def _install_hardware_log_relay")
    body = src[i:src.index("\n    def ", i + 10)]
    assert "_hardware_log_relay" in body and "is not None:" in body
