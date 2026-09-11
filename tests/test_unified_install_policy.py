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
