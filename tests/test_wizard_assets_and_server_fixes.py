"""Setup wizard must hard-fail missing nomic/piper correctly."""
from __future__ import annotations

from pathlib import Path


def test_wizard_embedder_stage_uses_aux_cli():
    src = Path("eli/setup/wizard.py").read_text(encoding="utf-8")
    assert '"-m", "eli.core.model_download", "--aux"' in src
    assert "required_only=False" not in src


def test_has_embedder_uses_models_dir_status():
    src = Path("eli/setup/status.py").read_text(encoding="utf-8")
    assert "aux_status" in src
    assert "models_dir" in src


def test_voice_assets_main_ignores_repair_for_exit():
    src = Path("eli/runtime/voice_assets.py").read_text(encoding="utf-8")
    assert 'required = ("piper", "whisper")' in src


def test_windows_installer_no_desktop_server_icon():
    iss = Path("packaging/windows/installer.iss").read_text(encoding="utf-8")
    assert 'Name: "{autodesktop}\\ELI Server"' not in iss
    assert 'Name: "{autodesktop}\\{#MyAppName}"' in iss
    assert iss.count("[Run]") >= 1
    # Only one postinstall Launch ELI line in the final [Run] block
    assert 'Description: "Launch ELI"' in iss


def test_eli_entry_has_gui_singleton():
    src = Path("packaging/pyinstaller/eli_entry.py").read_text(encoding="utf-8")
    assert "_gui_singleton_or_exit" in src
    assert "ELI_ALLOW_MULTI_INSTANCE" in src


def test_windows_setup_bat_uses_wizard():
    src = Path("packaging/windows/build-windows.ps1").read_text(encoding="utf-8")
    assert "eli.setup --full-install" in src
    assert "install.ps1" in src
