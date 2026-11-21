"""Hardware policy is the single install planner for every OS entrypoint."""
from __future__ import annotations

from pathlib import Path

from eli.setup.hardware_policy import (
    AcceleratorInventory,
    recommend_cpu_only,
    summarize_for_ui,
)
from eli.setup.platform_profile import install_script_for_profile


def test_recommend_cpu_only_respects_env(monkeypatch):
    monkeypatch.setenv("ELI_INSTALL_CPU_ONLY", "0")
    inv = AcceleratorInventory(intel_igpu=True, ram_gb=8)
    assert recommend_cpu_only(inv) is False
    monkeypatch.setenv("ELI_INSTALL_CPU_ONLY", "1")
    inv2 = AcceleratorInventory(nvidia=True)
    assert recommend_cpu_only(inv2) is True


def test_recommend_cpu_only_gpu_classes():
    assert recommend_cpu_only(AcceleratorInventory(nvidia=True), respect_env=False) is False
    assert recommend_cpu_only(AcceleratorInventory(amd=True), respect_env=False) is False
    assert recommend_cpu_only(AcceleratorInventory(intel_arc=True), respect_env=False) is False
    assert recommend_cpu_only(AcceleratorInventory(apple_metal=True), respect_env=False) is False
    assert recommend_cpu_only(AcceleratorInventory(intel_igpu=True), respect_env=False) is True
    assert recommend_cpu_only(AcceleratorInventory(ram_gb=8), respect_env=False) is True


def _fake_smi_result(returncode: int, stdout: str):
    import subprocess as _sp

    return _sp.CompletedProcess(args=["nvidia-smi"], returncode=returncode, stdout=stdout, stderr="")


def test_nvidia_smi_error_text_is_not_a_gpu(monkeypatch):
    from eli.setup import hardware_policy as hp

    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    # The classic pre-existing failure: nonzero exit, one line of prose.
    monkeypatch.setattr(
        hp.subprocess, "run",
        lambda *a, **k: _fake_smi_result(
            1, "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n"
        ),
    )
    monkeypatch.setattr(hp, "_lspci_display_lines", lambda: [
        "00:02.0 VGA compatible controller: Intel Corporation Iris Xe Graphics",
        "01:00.0 3D controller: NVIDIA Corporation Device 25a0",
    ])
    monkeypatch.setattr(hp, "_ram_gb", lambda: 7)
    inv = hp.detect_accelerators()
    assert inv.nvidia is False
    assert inv.intel_igpu is True
    assert recommend_cpu_only(inv, respect_env=False) is True


def test_nvidia_smi_nvml_version_mismatch_is_not_a_gpu(monkeypatch):
    """Field regression: nvidia-smi's SECOND line on a driver/library version
    mismatch ("NVML library version: 595.91") matches no keyword filter and
    used to survive as a fake GPU name. The exit code (nonzero on this
    failure) is what must gate it, not text pattern-matching alone."""
    from eli.setup import hardware_policy as hp

    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr(
        hp.subprocess, "run",
        lambda *a, **k: _fake_smi_result(
            18,
            "Failed to initialize NVML: Driver/library version mismatch\n"
            "NVML library version: 595.91\n",
        ),
    )
    assert hp._nvidia_smi_gpu_names() == []
    inv = hp.detect_accelerators()
    assert inv.nvidia is False
    assert recommend_cpu_only(inv, respect_env=False) is True


def test_rocm_smi_present_but_no_amd_gpu_is_not_a_gpu(monkeypatch):
    """Field regression: rocm-smi can be installed as a generic driver-utils
    package with no AMD GPU behind it at all ("Driver not initialized
    (amdgpu not found in modules)"). The binary existing must not be enough —
    it has to actually report a card."""
    from eli.setup import hardware_policy as hp

    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None)
    monkeypatch.setattr(hp, "_run", lambda cmd, timeout=4.0: (
        "ERROR:root:Driver not initialized (amdgpu not found in modules)\n"
        if "rocm-smi" in cmd[0] else ""
    ))
    monkeypatch.setattr(hp, "_nvidia_smi_gpu_names", lambda: [])
    monkeypatch.setattr(hp, "_lspci_display_lines", lambda: [])
    monkeypatch.setattr(hp, "_ram_gb", lambda: 31)
    inv = hp.detect_accelerators()
    assert inv.amd is False
    assert recommend_cpu_only(inv, respect_env=False) is True


def test_rocm_smi_working_still_selects_amd(monkeypatch):
    from eli.setup import hardware_policy as hp

    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None)
    monkeypatch.setattr(hp, "_run", lambda cmd, timeout=4.0: (
        "GPU[0]\t\t\t\t: Card series: \t\tRadeon RX 7900 XTX\n" if "rocm-smi" in cmd[0] else ""
    ))
    monkeypatch.setattr(hp, "_nvidia_smi_gpu_names", lambda: [])
    monkeypatch.setattr(hp, "_lspci_display_lines", lambda: [])
    monkeypatch.setattr(hp, "_ram_gb", lambda: 31)
    inv = hp.detect_accelerators()
    assert inv.amd is True
    assert recommend_cpu_only(inv, respect_env=False) is False


def test_install_sh_filters_dead_nvidia_smi():
    text = Path("install.sh").read_text(encoding="utf-8")
    assert "driver unusable — not selecting CUDA" in text
    assert "couldn.t communicate" in text


def test_launchers_isolate_env():
    for rel in (
        "eli.sh",
        "scripts/eli_setup.sh",
        "scripts/eli_startup.sh",
        "scripts/eli_launch.sh",
        "scripts/eli_serve.sh",
    ):
        src = Path(rel).read_text(encoding="utf-8")
        assert "eli_isolate_env" in src, rel
    assert Path("scripts/eli_isolate_env.sh").is_file()


def test_core_install_complete_probes_backend():
    src = Path("eli/setup/unified_installer.py").read_text(encoding="utf-8")
    assert "llama_backend_init" in src
    assert "llama_cpp outside .venv" in src


def test_gui_server_has_frozen_subprocess_fallback():
    src = Path("eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert "_eli_server_start_subprocess" in src
    assert 'loop="asyncio"' in src
    assert "ELI-Server" in src
    assert "did not bind" in src
    # LAN QRs must paint before bind confirmation on phone/Wi-Fi start.
    assert "Paint QRs immediately" in src


def test_spec_pins_segno_and_cryptography():
    spec = Path("ELI.spec").read_text(encoding="utf-8")
    assert '"segno"' in spec or "'segno'" in spec
    assert "cryptography" in spec
    assert "web-server packaging requires segno" in spec


def test_selftest_probes_qr_png():
    src = Path("packaging/pyinstaller/eli_entry.py").read_text(encoding="utf-8")
    assert "qr_png_bytes" in src
    assert "import segno" in src


def test_summarize_for_ui_mentions_path():
    text = summarize_for_ui(AcceleratorInventory(nvidia=True, ram_gb=32))
    assert "NVIDIA" in text or "CUDA" in text
    assert "GPU" in text or "CPU" in text


def test_install_script_adds_cpu_only_when_policy_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_INSTALL_CPU_ONLY", "1")
    root = tmp_path
    (root / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr("eli.setup.platform_profile.detect_install_profile",
                        lambda: __import__("eli.setup.platform_profile", fromlist=["InstallProfile"]).InstallProfile.DESKTOP)
    monkeypatch.setattr("sys.platform", "linux")
    _script, argv = install_script_for_profile(root)
    assert "--cpu-only" in argv
    assert "--yes" in argv
    assert "--auto-model" in argv


def test_install_script_omits_cpu_only_for_gpu(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_INSTALL_CPU_ONLY", "0")
    root = tmp_path
    (root / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr("sys.platform", "linux")
    _script, argv = install_script_for_profile(root)
    assert "--cpu-only" not in argv


def test_wrappers_funnel_to_eli_setup():
    for rel in (
        "scripts/eli_one_click_setup.sh",
        "scripts/install_eli.sh",
        "scripts/eli_startup.sh",
    ):
        src = Path(rel).read_text(encoding="utf-8")
        assert "eli_setup.sh" in src


def test_model_download_auto_hard_fails_missing_aux():
    src = Path("eli/core/model_download.py").read_text(encoding="utf-8")
    assert "aux_ok" in src
    assert "return 0 if (ok and aux_ok) else 1" in src


def test_startup_support_assets_always_scoped_network():
    src = Path("eli/gui/panels/startup.py").read_text(encoding="utf-8")
    assert 'allow_network("firstboot-support-assets")' in src
    assert "offline — asset prefetch skipped" not in src


# ── scripts/eli_startup.sh (RUN_ELI.sh), run in a tree whose setup, Python and restore only log ─
def _startup_tree(tmp_path, *, with_venv: bool):
    """A copy of eli_startup.sh whose setup, Python and asset restore write down what they were
    asked to do, in order, and nothing else."""
    import shlex
    import shutil
    repo = Path(__file__).resolve().parents[1]
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    for name in ("eli_startup.sh", "eli_isolate_env.sh"):
        shutil.copy(repo / "scripts" / name, root / "scripts" / name)
    log = tmp_path / "ran.log"
    fake_python = root / "scripts" / "fake_python"
    fake_python.write_text("#!/usr/bin/env bash\n"
                           f'echo "python $* SAFE=${{ELI_SAFE_MODE:-}} DISABLE=${{ELI_DISABLE_PROACTIVE:-}}" >> {shlex.quote(str(log))}\n',
                           encoding="utf-8")
    fake_python.chmod(0o755)
    (root / "scripts" / "eli_setup.sh").write_text(
        "#!/usr/bin/env bash\nset -e\n"
        f"echo setup >> {shlex.quote(str(log))}\n"
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        'mkdir -p "$ROOT/.venv/bin" && cp "$ROOT/scripts/fake_python" "$ROOT/.venv/bin/python"\n',
        encoding="utf-8")
    if with_venv:
        (root / ".venv" / "bin").mkdir(parents=True)
        shutil.copy(fake_python, root / ".venv" / "bin" / "python")
    return root, log


def _run_startup(root, log, *args):
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if k not in ("ELI_SAFE_MODE", "ELI_DISABLE_PROACTIVE")}
    ran = subprocess.run(["bash", str(root / "scripts" / "eli_startup.sh"), *args, "--no-log"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    steps = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line == "setup":
            steps.append("setup")
        elif "restore_github_asset_files.py" in line:
            steps.append("restore")
        elif " -m eli" in line:
            steps.append("launch " + line.split(" SAFE=", 1)[1])
    return steps


def test_safe_mode_reaches_eli_as_the_variable_it_reads(tmp_path):
    root, log = _startup_tree(tmp_path, with_venv=True)
    assert _run_startup(root, log, "--safe-mode", "--no-setup") == ["launch 1 DISABLE="]
    assert _run_startup(root, log, "--no-setup")[-1] == "launch  DISABLE="


def test_assets_are_restored_after_the_setup_the_same_run_does(tmp_path):
    """`./RUN_ELI.sh --with-github-assets` on a fresh extract ran setup and then skipped the restore,
    because the restore was only done on runs without setup: the one run that needed it."""
    root, log = _startup_tree(tmp_path, with_venv=False)
    assert _run_startup(root, log, "--with-github-assets") == ["setup", "restore", "launch  DISABLE="]
    assert _run_startup(root, log, "--with-github-assets", "--no-setup")[-2:] == ["restore", "launch  DISABLE="]


def test_the_launch_hint_names_the_launcher_this_tree_has(tmp_path, monkeypatch):
    """Clone users were told to run RUN_ELI.sh, which only the portable package has."""
    import shlex
    import shutil
    import subprocess
    import sys
    from eli.setup.status import launcher_command

    on_posix = sys.platform != "win32" and shutil.which("bash")
    monkeypatch.setattr(sys, "platform", "linux")
    clone, portable = tmp_path / "clone", tmp_path / "portable"
    clone.mkdir()
    portable.mkdir()
    (portable / "RUN_ELI.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    assert launcher_command(clone) == f'"{clone / "eli.sh"}"'
    assert launcher_command(portable) == f'bash "{portable / "RUN_ELI.sh"}"'
    assert launcher_command(clone, headless=True) == f'"{clone / "eli.sh"}" --headless'
    installer = Path("eli/setup/unified_installer.py").read_text(encoding="utf-8")
    assert "RUN_ELI.sh'}" not in installer and "launcher_command(root, headless=" in installer

    setup = Path("scripts/eli_setup.sh").read_text(encoding="utf-8")
    assert setup.count("Launch ELI with: $LAUNCH") == 3 and 'with: bash \\"$ROOT/RUN_ELI.sh' not in setup
    if on_posix:
        line = next(l for l in setup.splitlines() if l.startswith('if [ -f "$ROOT/RUN_ELI.sh" ]'))
        for tree, expected in ((clone, f'"{clone}/eli.sh"'), (portable, f'bash "{portable}/RUN_ELI.sh"')):
            said = subprocess.run(["bash", "-c", f'ROOT={shlex.quote(str(tree))}\n{line}\necho "$LAUNCH"'],
                                  capture_output=True, text=True).stdout.strip()
            assert said == expected
