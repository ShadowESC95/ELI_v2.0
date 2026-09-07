"""Linux volume fallback chain tests."""
from __future__ import annotations

import pytest


def test_linux_set_volume_tries_wpctl_first(monkeypatch):
    from eli.utils import platform_compat as pc
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc, "ANDROID", False)
    monkeypatch.setattr(pc.shutil, "which", lambda name: name == "wpctl")
    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.set_volume(50) is True
    assert calls[0][0] == "wpctl"


def test_linux_set_volume_falls_back_to_amixer(monkeypatch):
    from eli.utils import platform_compat as pc
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc, "ANDROID", False)
    monkeypatch.setattr(pc.shutil, "which", lambda name: name == "amixer")
    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.set_volume(40) is True
    assert calls[0][0] == "amixer"
