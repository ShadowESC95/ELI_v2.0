from __future__ import annotations

from eli.runtime.user_visible_response_surface import install_engine_response_surface


class DummyEngine:
    pass


def _original_process(self, user_input="", *args, **kwargs):
    return {"ok": True, "content": "structured result"}


def test_response_surface_installer_is_inert():
    DummyEngine.process = _original_process
    before = DummyEngine.process

    install_engine_response_surface(DummyEngine)

    assert DummyEngine.process is before
    assert not getattr(DummyEngine.process, "_eli_user_visible_response_surface_final", False)
