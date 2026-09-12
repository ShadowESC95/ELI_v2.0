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


def test_nvidia_smi_error_text_is_not_a_gpu(monkeypatch):
    from eli.setup import hardware_policy as hp

    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr(
        hp,
        "_run",
        lambda cmd, timeout=4.0: (
            "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n"
            if "nvidia-smi" in cmd[0]
            else ""
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
