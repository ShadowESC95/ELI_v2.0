"""Install script regressions — catch fresh-clone failures before users hit them."""
from __future__ import annotations

from pathlib import Path


def test_install_sh_does_not_use_set_e_unsafe_wheel_lookup():
    text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    assert "WHEEL=$(ls" not in text, (
        "install.sh must not use WHEEL=$(ls ...) under set -e — ls fails when no wheel exists and aborts the installer"
    )
    assert 'install -e ".[full]"' in text or "install -e '.[full]'" in text


def test_install_ps1_uses_editable_dot_full_not_scriptdir_subscript():
    text = (Path(__file__).resolve().parents[1] / "install.ps1").read_text(encoding="utf-8")
    assert '$ScriptDir[full]' not in text, "PowerShell treats $ScriptDir[full] as indexing, not pip extras syntax"
    assert '.[full]' in text
