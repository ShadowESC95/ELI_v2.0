"""ELI's animated face renders every emotion and covers the whole palette."""
from __future__ import annotations

import pytest

_qt = pytest.importorskip("eli.gui.qt_compat")


def _qt_is_mocked() -> bool:
    """The test harness mocks PySide6 (MagicMock); real widget rendering can't run then."""
    try:
        from eli.gui.qt_compat import QWidget
        return "mock" in type(QWidget).__name__.lower() or type(QWidget).__module__.startswith("unittest")
    except Exception:
        return True


@pytest.fixture(scope="module")
def _app():
    if _qt_is_mocked():
        pytest.skip("Qt is mocked in this test env — real face rendering verified out-of-suite")
    try:
        from eli.gui.qt_compat import QApplication
        app = QApplication.instance() or QApplication([])
    except Exception as e:
        pytest.skip(f"Qt unavailable: {e}")
    return app


def test_every_palette_expression_has_a_face():
    from eli.cognition import emotion_palette as ep
    from eli.gui.widgets.eli_face import _FACES
    for tone in ep.list_tones():
        expr = ep.get_tone(tone)["expression"]
        assert expr in _FACES, f"palette tone {tone!r} → expression {expr!r} has no face"


def test_face_params_fallback_to_neutral():
    from eli.gui.widgets.eli_face import face_params, _FACES
    assert face_params("does-not-exist") == _FACES["neutral"]
    assert set(face_params("angry")) == {"brow", "slant", "eye", "curve", "open", "pupil"}


def test_face_widget_renders_all_expressions(_app):
    from eli.gui.qt_compat import QPixmap
    from eli.gui.widgets.eli_face import EliFaceWidget, _FACES
    f = EliFaceWidget(poll_tone=False, size=120)
    f.resize(120, 120)
    for expr in _FACES:
        f.set_expression(expr)
        f._tick(); f._tick()
        pm = QPixmap(120, 120)
        f.render(pm)  # exercises paintEvent — must not raise
        assert not pm.isNull()
    assert f.current_expression() in _FACES


def test_face_polls_tone_when_enabled(_app, monkeypatch):
    import eli.cognition.tone_adaptor as ta
    from eli.gui.widgets.eli_face import EliFaceWidget
    monkeypatch.setattr(ta, "expression", lambda: "grinning")
    f = EliFaceWidget(poll_tone=False, size=100)
    f._poll_tone()
    assert f.current_expression() == "grinning"


def test_face_render_offscreen_smoke():
    """Real (un-mocked) render of a couple of expressions, when PySide6 is genuinely
    importable — proves paintEvent runs. Skipped under the harness Qt mock."""
    if _qt_is_mocked():
        pytest.skip("Qt mocked")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from eli.gui.qt_compat import QApplication, QPixmap
    QApplication.instance() or QApplication([])
    from eli.gui.widgets.eli_face import EliFaceWidget
    f = EliFaceWidget(poll_tone=False, size=100)
    f.resize(100, 100)
    for expr in ("grinning", "angry", "downcast"):
        f.set_expression(expr); f._tick()
        pm = QPixmap(100, 100); f.render(pm)
        assert not pm.isNull()
