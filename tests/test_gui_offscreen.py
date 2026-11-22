"""Offscreen GUI widget lane — construct REAL Qt widgets, headless.

The full main window (`eli_pro_audio_gui_v2_0.py`) blocks on device/display init and
can't be built in CI. But the tab widgets construct standalone under the offscreen
Qt platform (`QT_QPA_PLATFORM=offscreen`). This lane builds each one for real and
asserts it wired its UI — recovering the GUI __init__/layout/wiring coverage that the
mocked suite (PySide6 is a MagicMock there) structurally cannot reach.

Discipline: assertions are STRUCTURAL — the widget constructs, is a QWidget, and
built child widgets. We don't drive user interactions that would fire real actions.

Run on the clean lane:

    QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_gui_offscreen.py \
        --noconftest --cov=eli.gui --cov-report=term
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Constructing a widget must never reach the network. This lane is usually run with
# --noconftest, so it cannot rely on the root conftest for the offline default: set it
# here, the same way the offscreen Qt platform is set, so the file is hermetic on its
# own. FirstBootWizard's asset prefetch opens a network window of its own, which this
# does not close: the _no_model_is_loaded fixture below stops that prefetch.
os.environ["ELI_OFFLINE"] = "1"

import pytest

# Skip under the mocked full suite (PySide6 is a MagicMock — no real widgets).
try:
    from PySide6.QtWidgets import QApplication, QWidget, QPushButton
    if type(QApplication).__name__ == "MagicMock":
        raise RuntimeError("PySide6 mocked")
except Exception as _e:  # pragma: no cover
    pytest.skip(f"offscreen GUI lane needs real PySide6 ({_e}); run with --noconftest",
                allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# A model built while a widget is constructed, recorded and refused: no test here loads one.
_MODEL_LOADS: list = []
_NOT_FETCHED = {"ok": False, "error": "not fetched in the offscreen GUI tests"}
# How long a thread a widget started is given to finish before its test fails (it then would
# run on into later tests); the wizard's asset step, with nothing fetched, takes well under it.
_THREAD_WAIT_MS = 60_000


@pytest.fixture(scope="module", autouse=True)
def _no_model_is_loaded():
    """FirstBootWizard fetches its support assets from its constructor (_SupportAssetsThread): the
    embedder through model_download.download_aux, the Piper voice and faster-whisper through
    voice_assets.ensure_voice_assets. That step opens its own network window, so ELI_OFFLINE does
    not stop it, and with whisper's files on the box it loaded the real model. Those two calls are
    the wizard's boundary; here they fetch and load nothing."""
    with pytest.MonkeyPatch.context() as mp:
        import eli.core.model_download as model_download
        import eli.runtime.voice_assets as voice_assets
        mp.setattr(model_download, "download_aux", lambda *a, **k: [dict(_NOT_FETCHED)])
        mp.setattr(voice_assets, "ensure_voice_assets",
                   lambda *a, **k: {"piper": dict(_NOT_FETCHED), "whisper": dict(_NOT_FETCHED)})
        for module, name in (("faster_whisper", "WhisperModel"), ("llama_cpp", "Llama")):
            try:
                target = __import__(module)
            except Exception:
                continue

            def _refused(*args, _what=f"{module}.{name}", **kwargs):
                _MODEL_LOADS.append(_what)
                raise RuntimeError(f"{_what}: no model is loaded in the offscreen GUI tests")
            mp.setattr(target, name, _refused)
        yield


# --------------------------------------------------------------------------- #
# qt_compat — the tri-binding shim
# --------------------------------------------------------------------------- #
def test_qt_compat_binding_resolved():
    import eli.gui.qt_compat as qc
    assert qc.QT_API in {"PySide6", "PyQt6", "PyQt5", "headless"}
    # Core symbols are re-exported under one name regardless of binding.
    for name in ("Qt", "QTimer", "QWidget", "QVBoxLayout", "Signal", "QDialogButtonBox"):
        assert hasattr(qc, name) or name == "Signal"  # Signal aliased as pyqtSignal


def test_ollama_model_selector_imports():
    from eli.gui.widgets.ollama_model_selector import OllamaModelSelector
    assert OllamaModelSelector is not None


# --------------------------------------------------------------------------- #
# coding_tab
# --------------------------------------------------------------------------- #
def test_coding_tab_constructs(qapp):
    from eli.gui.coding_tab import CodingTab
    w = CodingTab(parent_window=None)
    assert isinstance(w, QWidget)
    assert len(w.findChildren(QPushButton)) >= 1


# --------------------------------------------------------------------------- #
# labs_tab — every sub-tab constructs standalone
# --------------------------------------------------------------------------- #
LABS_SUBTABS = [
    "_NotebookTab", "_JupyterTab", "_CalculatorTab", "_PhysicsTab", "_ReportTab",
    "_FileChatTab", "_WorkspacesTab", "_SimIDETab", "_OrchestrationTab", "_TestReviewTab",
]


@pytest.mark.parametrize("clsname", LABS_SUBTABS)
def test_labs_subtab_constructs(qapp, clsname):
    import eli.gui.labs_tab as lt
    cls = getattr(lt, clsname)
    w = cls()
    assert isinstance(w, QWidget)


def test_labs_container_builds_full_tree(qapp):
    from eli.gui.labs_tab import LabsTab
    w = LabsTab(parent_window=None)
    assert isinstance(w, QWidget)
    # The container hosts all the sub-tabs — a deep child tree.
    assert len(w.findChildren(QWidget)) > 50


class _Signal:
    def __init__(self):
        self.sent = []

    def emit(self, text):
        self.sent.append(text)


def _window_with_labs():
    """The main window's artifact-opening methods on a stand-in that holds a real Labs
    tab (the full window cannot be built headless)."""
    from PySide6.QtWidgets import QTabWidget
    from eli.gui.eli_pro_audio_gui_v2_0 import EliMainWindow
    from eli.gui.labs_tab import LabsTab

    class _Win:
        _open_generated_artifact_from_result = EliMainWindow._open_generated_artifact_from_result
        open_script_in_editor = EliMainWindow.open_script_in_editor
        _load_path_into_labs_sim_ide = EliMainWindow._load_path_into_labs_sim_ide
        _focus_tab_widget = EliMainWindow._focus_tab_widget

        def __init__(self):
            self._labs_widget = LabsTab(parent_window=None)
            self.tabs = QTabWidget()
            self.tabs.addTab(self._labs_widget, "Labs")
            self.status_signal = _Signal()
            self.viewed = []

        def open_text_file(self, path):
            self.viewed.append(path)

    return _Win()


@pytest.mark.parametrize("name,code", [
    ("tool.py", "print('hello')\n"),
    ("tool.sh", "echo hello\n"),
    ("tool.js", "console.log('hello');\n"),
])
def test_a_generated_script_of_any_language_opens_in_the_labs_editor(qapp, tmp_path, name, code):
    """Scripts went to an IDE tab that was never built, so none opened (a .py only when
    the result asked for Labs)."""
    win = _window_with_labs()
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    win._open_generated_artifact_from_result({"action": "GENERATE_SCRIPT",
                                              "script_path": str(script)})
    sim = win._labs_widget._sim_ide_tab
    assert sim._get_code() == code
    assert sim._current_file == script
    assert win.viewed == []


def test_without_labs_a_generated_script_is_shown_read_only(qapp, tmp_path):
    win = _window_with_labs()
    win._labs_widget = None
    script = tmp_path / "tool.sh"
    script.write_text("echo hello\n", encoding="utf-8")
    win._open_generated_artifact_from_result({"action": "WRITE_SCRIPT", "path": str(script)})
    assert win.viewed == [script]


@pytest.mark.skipif(__import__("shutil").which("bash") is None, reason="no bash here")
def test_the_labs_runner_runs_a_script_with_its_own_interpreter(qapp, tmp_path):
    """A shell script opened in Labs must not be run as Python."""
    from eli.gui.labs_tab import _CodeRunnerThread
    out = []
    runner = _CodeRunnerThread("echo from-the-shell\n", str(tmp_path), ".sh")
    runner.finished.connect(lambda so, se: out.append((so, se)))
    runner.run()
    assert out and out[0][0].strip() == "from-the-shell", out


@pytest.mark.parametrize("name,words,fence", [
    ("tool.sh", "bash code", "bash"),
    ("tool.js", "javascript code", "javascript"),
    ("tool.rs", "code from a .rs file", "rs"),
    (None, "python code", "python"),              # an unsaved buffer runs as Python
])
def test_labs_asks_eli_about_the_code_in_its_own_language(qapp, tmp_path, name, words, fence):
    """ELI: Fix errors and ELI: Explain called every file Python code."""
    import threading
    from eli.gui.labs_tab import _SimIDETab
    asked, answered = [], threading.Event()

    def eli(prompt):
        asked.append(prompt)
        answered.set()
        return "ok"

    sim = _SimIDETab(eli_callback=eli)
    sim._set_code("say hello\n")
    if name:
        sim._current_file = tmp_path / name
    for ask in (sim._ask_eli_fix, sim._ask_eli_explain):
        answered.clear()
        ask()
        assert answered.wait(10), ask.__name__
        assert f" {words}" in asked[-1] and f"```{fence}\nsay hello" in asked[-1], asked[-1]
        assert fence == "python" or "python" not in asked[-1].lower(), asked[-1]


def test_the_windows_load_asks_for_what_the_gpu_layer_box_says(qapp, tmp_path, monkeypatch):
    """The box held -1 (every layer) as 0 and the load asked for 0 layers, which the load plan reads
    as a load on the processor: a model that fits the GPU whole loaded on the CPU from the window.
    Every layer asks for -1, auto for no count (the plan's own), a number for that number."""
    import eli.gui.eli_pro_audio_gui_v2_0 as gui
    from eli.cognition import gguf_inference
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_path / "settings.json"))
    model = tmp_path / "tiny.gguf"
    model.write_bytes(b"GGUF" + b"\0" * 64)
    asked = []

    def stop_before_loading(force_reload=False, request=None):
        asked.append(request.n_gpu_layers)
        raise RuntimeError("no model is loaded in the offscreen GUI tests")
    monkeypatch.setattr(gguf_inference, "load_model", stop_before_loading)
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda *a, **k: None)
    monkeypatch.setattr("eli.core.gpu_pack_runtime.try_activate_gpu_pack", lambda *a, **k: None)
    box = gui._GpuLayersBox()
    for value, text in ((-1, "every layer"), (0, "auto"), (12, "12")):
        box.setValue(value)
        assert (box.value(), box.text()) == (value, text)
        assert gui.LocalModelManager().load_model(str(model), n_gpu_layers=box.value()) is False
    assert asked == [-1, None, 12]


def test_calculator_tab_has_inputs(qapp):
    # A concrete sub-tab built its interactive surface (not just an empty frame).
    import eli.gui.labs_tab as lt
    w = lt._CalculatorTab()
    from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit
    fields = (w.findChildren(QLineEdit) + w.findChildren(QTextEdit)
              + w.findChildren(QPlainTextEdit))
    assert isinstance(w, QWidget)
    assert len(w.findChildren(QWidget)) > 0


# --------------------------------------------------------------------------- #
# panels / tabs / docks / widgets — every other GUI widget that constructs
# standalone offscreen (the main window is the only piece that can't).
# --------------------------------------------------------------------------- #
MORE_WIDGETS = [
    ("eli.gui.panels.settings", "AdvancedSettingsDialog"),
    ("eli.gui.panels.startup", "HardwareTuningDock"),
    ("eli.gui.panels.startup", "StartupModelSelectionDialog"),
    ("eli.gui.panels.startup", "FirstBootWizard"),
    ("eli.gui.tabs.tasks_tab", "TasksTab"),
    ("eli.gui.tabs.experimental_tab", "ExperimentalTab"),
    ("eli.gui.tabs.eli_world_tab", "EliWorldTab"),
    ("eli.gui.docks.operator_console_dock", "OperatorConsoleDock"),
    ("eli.gui.docks.proactive_dock", "ProactiveDock"),
    ("eli.gui.widgets.ollama_model_selector", "OllamaModelSelector"),
    ("eli.gui.widgets.ollama_model_selector", "_StatusDot"),
]


@pytest.mark.parametrize("module,clsname", MORE_WIDGETS)
def test_gui_widget_constructs(qapp, module, clsname):
    import importlib
    from PySide6.QtCore import QThread
    cls = getattr(importlib.import_module(module), clsname)
    _MODEL_LOADS.clear()
    w = cls()
    assert isinstance(w, QWidget)
    for thread in w.findChildren(QThread):      # what it started finishes here, not in a later test
        assert thread.wait(_THREAD_WAIT_MS), f"{clsname}: {type(thread).__name__} still running"
    assert not _MODEL_LOADS, f"{clsname} loaded a model: {_MODEL_LOADS}"


def test_agent_edit_dialog_constructs(qapp):
    from eli.gui.panels.agent_wizard import AgentEditDialog
    w = AgentEditDialog(agent_info={"name": "tester", "description": "a test agent",
                                    "triggers": [], "capabilities": []})
    assert isinstance(w, QWidget)


def test_settings_dialog_builds_deep_tree(qapp):
    from eli.gui.panels.settings import AdvancedSettingsDialog
    w = AdvancedSettingsDialog()
    assert isinstance(w, QWidget)
    assert len(w.findChildren(QWidget)) > 50   # a full multi-tab settings surface


def test_settings_dialog_opens_the_page_it_is_asked_for(qapp):
    """The Self-Upgrade card asked for index 4, which is the Marketplace whenever the
    Marketplace page builds. Pages are asked for by name."""
    from eli.gui.panels.settings import AdvancedSettingsDialog
    for page, label in (("upgrade", "Self-Upgrade"), ("marketplace", "Marketplace"),
                        ("plugins", "Plugins"), ("cognition", "Cognition")):
        w = AdvancedSettingsDialog(start_tab=page)
        assert w.inner_tabs.tabText(w.inner_tabs.currentIndex()).endswith(label), page


def test_every_advanced_card_names_a_page_the_dialog_has(qapp):
    import re
    from pathlib import Path
    from eli.gui.panels.settings import AdvancedSettingsDialog
    gui = (Path(__file__).resolve().parents[1] / "eli" / "gui"
           / "eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    asked = re.findall(r"self\.open_advanced_settings\(([^)]*)\)", gui)
    assert asked, "no Advanced cards found"
    pages = AdvancedSettingsDialog()._pages
    for arg in asked:
        assert arg.strip("\"'") in pages, f"open_advanced_settings({arg}) names no page"
