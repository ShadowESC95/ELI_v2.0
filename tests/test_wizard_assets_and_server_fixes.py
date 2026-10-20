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


def test_windows_installer_never_waits_on_an_unseen_runtime_install():
    """Setup hung at its last step: a non-admin Setup ran the VC++ runtime installer with /quiet, and
    Windows' permission prompt could open behind the Setup window while Setup waited on it with no
    visible prompt. The release job installs the built Setup to prove it finishes; this keeps the
    shape that made the hang impossible."""
    iss = Path("packaging/windows/installer.iss").read_text(encoding="utf-8")
    code = "\n".join(l for l in iss.splitlines() if not l.lstrip().startswith(";"))
    assert "/quiet" not in code
    assert "Check: VCRuntimeNeeded" in code and "AfterInstall: InstallVCRuntime" in code
    assert "ShellExec('runas'" in code and "/passive" in code
    assert "SysErrorMessage(Code)" in code, "a declined permission prompt must be said, not swallowed"
    assert "SetupLogging=yes" in code
    assert "--install-gpu-pack" not in code, "the GPU pack download belongs to ELI's first start"
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "/VCRUNTIME=force" in release and "WaitForExit(" in release


def test_eli_entry_has_gui_singleton():
    src = Path("packaging/pyinstaller/eli_entry.py").read_text(encoding="utf-8")
    assert "_gui_singleton_or_exit" in src
    assert "ELI_ALLOW_MULTI_INSTANCE" in src
    assert "os.kill(" not in src, "os.kill(pid, 0) sends Ctrl+C on Windows; it does not test a process"


_HOLD_SINGLETON = r"""
import importlib.util, sys, time
sys.argv = ["ELI"]
spec = importlib.util.spec_from_file_location("eli_entry", "packaging/pyinstaller/eli_entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
entry._message_box_warning = lambda title, text: print("BLOCKED:", title, flush=True)
entry._gui_singleton_or_exit()
print("HOLDING", flush=True)
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 0)
"""


def test_a_second_window_is_refused_while_the_first_runs_and_allowed_after(tmp_path):
    """Two real processes against one lock file: the second exits while the first holds it, and a
    third starts once the first has gone (the OS released its lock; no stale-file cleanup)."""
    import os
    import subprocess
    import sys
    env = dict(os.environ, ELI_DATA_DIR=str(tmp_path))
    env.pop("ELI_ALLOW_MULTI_INSTANCE", None)
    first = subprocess.Popen([sys.executable, "-c", _HOLD_SINGLETON.replace('sys.argv = ["ELI"]', 'sys.argv = ["ELI", "30"]')],
                             env=env, stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout.readline().strip() == "HOLDING"
        second = subprocess.run([sys.executable, "-c", _HOLD_SINGLETON], env=env, capture_output=True,
                                text=True, timeout=120)
        assert second.returncode == 0 and "BLOCKED: ELI is already running" in second.stdout
        assert "HOLDING" not in second.stdout
    finally:
        first.kill()
        first.wait()
    third = subprocess.run([sys.executable, "-c", _HOLD_SINGLETON], env=env, capture_output=True,
                           text=True, timeout=120)
    assert "HOLDING" in third.stdout


def test_windows_setup_bat_uses_wizard():
    src = Path("packaging/windows/build-windows.ps1").read_text(encoding="utf-8")
    assert "eli.setup --full-install" in src
    assert "install.ps1" in src
