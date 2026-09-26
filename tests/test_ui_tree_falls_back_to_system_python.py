"""When the bundled Python cannot load PyGObject, the accessibility tree is read by the system interpreter."""
import pytest

from eli.perception import ui_tree as u


@pytest.fixture(autouse=True)
def bundled_python(monkeypatch):
    monkeypatch.setattr(u, "_atspi", lambda: None)
    monkeypatch.setattr(u, "_system_probe", None)


def test_available_asks_the_system_interpreter(monkeypatch):
    calls = []
    monkeypatch.setattr(u, "_via_system_python", lambda payload, timeout=20.0: calls.append(payload["op"]) or {"available": True, "reason": ""})
    assert u.available() is True and u.available() is True
    assert calls == ["probe"]


def test_find_returns_boxes_tagged_with_where_they_came_from(monkeypatch):
    def fake(payload, timeout=20.0):
        if payload["op"] == "probe":
            return {"available": True}
        assert payload["op"] == "find" and payload["query"] == "Save"
        return [{"text": "Save", "role": "push button", "cx": 10, "cy": 20, "score": 1.0}]
    monkeypatch.setattr(u, "_via_system_python", fake)
    boxes = u.find("Save")
    assert boxes[0]["_via"] == "system-python" and boxes[0]["text"] == "Save"


def test_invoke_is_resolved_again_where_the_widget_lives(monkeypatch):
    seen = {}

    def fake(payload, timeout=20.0):
        seen.update(payload)
        return {"ok": True, "action_used": "click", "error": ""}
    monkeypatch.setattr(u, "_via_system_python", fake)
    res = u.invoke({"text": "Save", "role": "push button", "cx": 10, "cy": 20, "_via": "system-python"})
    assert res["ok"] and seen["op"] == "invoke" and seen["text"] == "Save" and seen["cx"] == 10


def test_no_system_interpreter_means_an_honest_empty_result(monkeypatch):
    monkeypatch.setattr(u, "_via_system_python", lambda payload, timeout=20.0: None)
    assert u.available() is False and u.find("Save") == []


def test_the_helper_never_calls_itself(monkeypatch):
    monkeypatch.setenv(u._INPROC_ENV, "1")
    assert u._via_system_python({"op": "probe"}) is None


def test_the_real_helper_speaks_json():
    import os
    if not os.path.exists(u._SYSTEM_PYTHON):
        pytest.skip("no system interpreter")
    res = u._via_system_python({"op": "probe"})
    assert res is None or isinstance(res, dict) and "available" in res
