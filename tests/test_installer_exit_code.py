"""GUI installer must not treat Qt Accepted (1) as shell failure."""
from pathlib import Path


def test_run_unified_installer_uses_install_success_not_qt_exec():
    src = Path("eli/setup/unified_installer.py").read_text(encoding="utf-8")
    assert "return 0 if dlg._install_succeeded else 1" in src
    assert "_install_succeeded = True" in src
