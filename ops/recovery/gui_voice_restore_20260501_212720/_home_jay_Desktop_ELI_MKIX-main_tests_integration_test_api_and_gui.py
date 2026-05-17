import importlib

import pytest

def test_api_server_module_imports():
    """
    Ensure eli.api.server imports when FastAPI is available.
    """
    pytest.importorskip("fastapi", reason="FastAPI not installed; API tests skipped")
    server_mod = importlib.import_module("eli.api.server")
    assert server_mod is not None


def test_gui_app_imports():
    """
    Ensure eli.gui.app imports and exposes a module-level object.
    """
    gui_mod = importlib.import_module("eli.gui.app")
    assert gui_mod is not None
