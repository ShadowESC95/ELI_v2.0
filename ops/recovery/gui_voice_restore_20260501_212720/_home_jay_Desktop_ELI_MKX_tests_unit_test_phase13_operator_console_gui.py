from __future__ import annotations

import importlib


def test_operator_console_dock_import():
    mod = importlib.import_module("eli.gui.docks.operator_console_dock")
    assert hasattr(mod, "OperatorConsoleDock")
