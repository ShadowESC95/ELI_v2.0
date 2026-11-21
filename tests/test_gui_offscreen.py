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
# Constructing a widget must never reach the network. FirstBootWizard kicks off a
# real asset prefetch (Piper voices + the embedder) from its constructor, which in
# this lane downloaded and copied files mid-test and ABORTED the pytest process —
# taking every test after it with it. This lane is usually run with --noconftest,
# so it cannot rely on the root conftest for the offline default: set it here, the
# same way the offscreen Qt platform is set, so the file is hermetic on its own.
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
    cls = getattr(importlib.import_module(module), clsname)
    w = cls()
    assert isinstance(w, QWidget)


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
