"""Cross-OS desktop capability + UI grounding hooks."""
from __future__ import annotations

from eli.perception import desktop_capabilities as dc
from eli.perception import ui_ground as ug


def test_runtime_tools_report_has_platform():
    rep = dc.runtime_tools_report()
    assert rep["platform"] in {"linux", "windows", "macos", "android"}
    assert "input" in rep
    assert "locate" in rep


def test_display_server_on_linux():
    ds = dc.display_server()
    assert ds in {"wayland", "x11", "linux-headless", "windows", "macos", "android", "other"}


def test_precision_backend_disabled_by_default(monkeypatch):
    monkeypatch.setattr(ug, "_setting", lambda k, d="": d)
    assert ug.configured_precision_backend() == ""


def test_locate_without_backend_returns_error():
    hit = ug.locate_with_precision_backend("blue icon", "/tmp/nope.png", backend="none")
    assert hit.get("ok") is False


def test_no_http_in_module_source():
    import inspect
    src = inspect.getsource(ug)
    assert "urlopen" not in src
    assert "127.0.0.1" not in src
