"""RAM budget fraction — startup dialog + hardware fit share one source of truth."""
from __future__ import annotations

import os

import pytest


def test_ram_budget_fraction_defaults_to_sixty_percent(monkeypatch):
    monkeypatch.delenv("ELI_RAM_BUDGET_PERCENT", raising=False)
    monkeypatch.delenv("ELI_RAM_BUDGET_FRACTION", raising=False)
    from eli.core import hardware_profile as hp

    # Bypass settings file by patching load_settings
    monkeypatch.setattr(
        "eli.core.runtime_settings.load_settings",
        lambda: {},
    )
    # The default depends on the machine: a discrete-GPU host keeps 60%, a CPU-only one with little
    # RAM uses more of it. This passed on GPU machines and failed on a CPU-only CI runner.
    monkeypatch.setattr(hp, "detect_hardware", lambda: hp.HardwareProfile(has_gpu=True, ram_gb=32.0))
    assert hp.ram_budget_fraction() == pytest.approx(0.60)
    monkeypatch.setattr(hp, "detect_hardware", lambda: hp.HardwareProfile(has_gpu=False, ram_gb=16.0))
    assert hp.ram_budget_fraction() == pytest.approx(0.70)


def test_ram_budget_fraction_respects_env_percent(monkeypatch):
    monkeypatch.setenv("ELI_RAM_BUDGET_PERCENT", "45")
    monkeypatch.setattr("eli.core.runtime_settings.load_settings", lambda: {})
    from eli.core.hardware_profile import cpu_ram_budget_mb, ram_budget_fraction

    assert ram_budget_fraction() == pytest.approx(0.45)
    assert cpu_ram_budget_mb(8.0) == int(8.0 * 1024 * 0.45)


def test_ram_budget_fraction_caps_at_seventy_five(monkeypatch):
    monkeypatch.setenv("ELI_RAM_BUDGET_PERCENT", "99")
    monkeypatch.setattr("eli.core.runtime_settings.load_settings", lambda: {})
    from eli.core.hardware_profile import ram_budget_fraction

    assert ram_budget_fraction() == pytest.approx(0.75)
