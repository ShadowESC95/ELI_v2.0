"""The model dropdown and the custom path must never disagree about what will load."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ELI_OFFLINE"] = "1"

# Real widgets only: the full suite mocks PySide6, so this runs in the offscreen lane (--noconftest).
try:
    from PySide6.QtWidgets import QApplication
    if type(QApplication).__name__ == "MagicMock":
        raise RuntimeError("PySide6 mocked")
except Exception as _e:  # pragma: no cover
    pytest.skip(f"needs real PySide6 ({_e}); run with --noconftest", allow_module_level=True)

from eli.gui.panels.startup import StartupModelSelectionDialog as StartupModelDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _dialog(models, path):
    return StartupModelDialog(models=models, current_provider="custom_gguf", current_model_path=path)


def test_a_saved_path_outside_the_scanned_list_is_shown_and_selected(app, tmp_path):
    other = tmp_path / "other.gguf"
    saved = tmp_path / "saved-model.gguf"
    other.write_bytes(b"x" * 10)
    saved.write_bytes(b"x" * 20)
    d = _dialog([{"source": "custom", "name": "other.gguf", "path": str(other), "size_gb": 0.1}], str(saved))
    assert d.gguf_combo.currentData() == str(saved)
    assert "saved-model.gguf" in d.gguf_combo.currentText()
    assert d.selected_model_path() == str(saved) == d.model_path_input.text()


def test_a_listed_path_selects_its_own_entry(app, tmp_path):
    a, b = tmp_path / "a.gguf", tmp_path / "b.gguf"
    for f in (a, b):
        f.write_bytes(b"x")
    d = _dialog([{"source": "custom", "name": n.name, "path": str(n), "size_gb": 0.1} for n in (a, b)], str(b))
    assert d.gguf_combo.currentData() == str(b) and d.gguf_combo.count() == 2


def test_choosing_another_entry_updates_the_path(app, tmp_path):
    a, b = tmp_path / "a.gguf", tmp_path / "b.gguf"
    for f in (a, b):
        f.write_bytes(b"x")
    d = _dialog([{"source": "custom", "name": n.name, "path": str(n), "size_gb": 0.1} for n in (a, b)], str(a))
    d.gguf_combo.setCurrentIndex(1)
    assert d.model_path_input.text() == str(b)
