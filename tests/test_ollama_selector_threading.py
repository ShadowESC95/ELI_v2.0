"""Ollama model selector — worker-thread → GUI-thread marshalling.

Split out of test_gui_offscreen.py deliberately: that lane aborts partway through
(an unrelated widget test spawns a real Piper voice-asset download), so anything
sharing the file never gets to run. These need a real PySide6 + event loop, so
they run on the same offscreen discipline but stand alone.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# Skip under the mocked full suite (PySide6 is a MagicMock — no real widgets).
try:
    from PySide6.QtWidgets import QApplication
    if type(QApplication).__name__ == "MagicMock":
        raise RuntimeError("PySide6 mocked")
except Exception as _e:  # pragma: no cover
    pytest.skip(f"offscreen GUI lane needs real PySide6 ({_e})",
                allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app



# --------------------------------------------------------------------------- #
# Ollama selector — worker-thread → GUI-thread marshalling
#
# Regression: _fetch_models runs on a plain threading.Thread and originally handed
# its result back with QTimer.singleShot(0, ...). A QTimer started from a thread
# with no Qt event loop never fires, so _update_ui was silently never called: the
# dropdown stayed empty and the status dot stuck on "Checking Ollama..." while the
# client underneath was returning models perfectly. Constructing the widget did NOT
# catch this — only asserting that the models actually LAND in the combo does.
# --------------------------------------------------------------------------- #
def _drive(qapp, predicate, timeout_ms=8000, step_ms=50):
    """Spin the real Qt event loop until predicate() is true or we time out."""
    from PySide6.QtCore import QDeadlineTimer, QEventLoop
    deadline = QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.AllEvents, step_ms)
        if predicate():
            return True
    return predicate()


@pytest.fixture
def _stub_ollama(monkeypatch):
    """Deterministic client — the test must not depend on a live Ollama daemon."""
    import eli.integrations.ollama.client as client
    monkeypatch.setattr(client, "is_running", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(client, "list_models",
                        lambda *a, **k: ["alpha:7b", "beta:13b"], raising=False)
    monkeypatch.setattr(client, "get_active_model", lambda *a, **k: "beta:13b",
                        raising=False)
    monkeypatch.setattr(client, "ensure_server_running", lambda *a, **k: True,
                        raising=False)
    return client


def test_ollama_selector_populates_from_worker_thread(qapp, _stub_ollama):
    """Models fetched off-thread must reach the combo on the GUI thread."""
    from eli.gui.widgets.ollama_model_selector import OllamaModelSelector
    w = OllamaModelSelector()
    assert _drive(qapp, lambda: w._combo.count() > 0), \
        "dropdown never populated — worker result did not reach the GUI thread"
    items = [w._combo.itemText(i) for i in range(w._combo.count())]
    assert items == ["alpha:7b", "beta:13b"]
    assert w._combo.isEnabled()
    # The configured active model wins the restored selection.
    assert w.current_model() == "beta:13b"


def test_ollama_selector_reports_stopped_daemon(qapp, monkeypatch):
    """A stopped daemon must say so, not sit silently on an empty dropdown."""
    import eli.integrations.ollama.client as client
    monkeypatch.setattr(client, "is_running", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(client, "list_models", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(client, "get_active_model", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(client, "ensure_server_running", lambda *a, **k: False,
                        raising=False)
    from eli.gui.widgets.ollama_model_selector import OllamaModelSelector
    w = OllamaModelSelector()
    assert _drive(qapp, lambda: w._combo.count() > 0), "no status ever surfaced"
    assert "not running" in w._combo.itemText(0)
    assert w.current_model() is None      # a status string is not a selectable model


def test_ollama_selector_reports_daemon_with_no_models(qapp, monkeypatch):
    """Running but empty is a different message from stopped."""
    import eli.integrations.ollama.client as client
    monkeypatch.setattr(client, "is_running", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(client, "list_models", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(client, "get_active_model", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(client, "ensure_server_running", lambda *a, **k: True,
                        raising=False)
    from eli.gui.widgets.ollama_model_selector import OllamaModelSelector
    w = OllamaModelSelector()
    assert _drive(qapp, lambda: w._combo.count() > 0)
    assert "No models" in w._combo.itemText(0)
    assert w.current_model() is None


def test_ollama_selector_marshals_over_signals_not_timers(qapp):
    """Guard the mechanism itself, so a refactor can't reintroduce the defect."""
    import inspect
    from eli.gui.widgets import ollama_model_selector as mod
    src = inspect.getsource(mod.OllamaModelSelector._fetch_models)
    # Strip comments/docstring mentions — we care about a real call, not the word.
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "QTimer.singleShot(" not in code, \
        "_fetch_models runs off-thread; a QTimer started there never fires. Emit a signal."
    assert "_models_ready.emit(" in code, "_fetch_models must hand back over the signal"
    assert hasattr(mod.OllamaModelSelector, "_models_ready")
